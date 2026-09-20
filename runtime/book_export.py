"""Streaming master-book export batches.

A batch freezes the selected book/project revisions and hard-links the exact
sentence WAVs it will read. Rendering then uses only that snapshot. The last
successful batch remains downloadable after later edits and is replaced only
after another batch succeeds.
"""
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import zipfile

import numpy as np
import soundfile as sf

from .audio import prepare_segment, timestamp
from .core import reads_aloud
from .delivery import _slug
from .fcp7 import timeline_xml, IMPORT_GUIDE, FPS_CHOICES
from .rhythm import analyze
from .subtitles import cues as subtitle_cues, hold_briefest
from .tempo import ffmpeg_path


OUTPUTS = {'wav', 'mp3', 'srt', 'zip', 'timeline', 'xml', 'report'}
TIMED_OUTPUTS = {'wav', 'mp3', 'srt', 'zip', 'timeline', 'xml'}
WARN_SECONDS = 6 * 3600
MAX_SECONDS = 8 * 3600
CHINESE_CHARS_PER_SECOND = 5.0
ENGLISH_WORDS_PER_SECOND = 2.5
WAV_BYTES_PER_SECOND = 48_000
MP3_BYTES_PER_HOUR = 30_000_000
ZIP_BYTES_PER_HOUR = 130_000_000


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _vtt_time(sample, rate):
    ms = round(sample * 1000 / rate)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02}.{ms%1000:03}'


class BookExportService:
    def __init__(self, project_service, engine, checker):
        self.service = project_service
        self.store = project_service.store
        self.books = project_service.books
        self.engine = engine
        self.checker = checker
        self.active_books = set()
        self._active_lock = threading.Lock()
        self.export_root = self.books.root / '.exports'
        self.export_root.mkdir(parents=True, exist_ok=True)
        # Staging directories are never successful batches. A prior process can
        # leave one behind; removing it on startup cannot remove a published batch.
        for path in self.export_root.glob('.staging-*'):
            shutil.rmtree(path, ignore_errors=True)

    def _root(self, book_id):
        return self.export_root / book_id

    def assert_book_writable(self, book_id):
        if not book_id:
            return
        with self._active_lock:
            if book_id in self.active_books:
                raise RuntimeError('这本书正在导出；可以查看内容，但请等本批导出结束后再修改。')

    def guard_project_write(self, raw):
        self.assert_book_writable((raw.get('book') or {}).get('id'))

    def guard_book_write(self, book_id):
        self.assert_book_writable(book_id)

    def active_tasks(self):
        with self._active_lock:
            return sorted(self.active_books)

    def _book(self, book_id):
        book = self.books.get(book_id)
        if book.get('master_schema') != 1:
            raise ValueError('只有新版主工程可以使用整书导出。')
        return book

    def _selected(self, book, chapter_ids):
        members = list(book.get('members') or [])
        if not members:
            raise ValueError('主工程里没有章节。')
        wanted = members if not chapter_ids else list(dict.fromkeys(chapter_ids))
        unknown = [pid for pid in wanted if pid not in members]
        if unknown:
            raise ValueError('所选章节已经不属于这个主工程，请刷新后再导出。')
        chosen = set(wanted)
        return [pid for pid in members if pid in chosen]

    @staticmethod
    def _outputs(outputs):
        selected = list(dict.fromkeys(outputs or []))
        if not selected:
            raise ValueError('至少选择一种导出内容。')
        bad = sorted(set(selected) - OUTPUTS)
        if bad:
            raise ValueError('未知导出内容：' + '、'.join(bad))
        return selected

    def _effective_rows(self, book, ids):
        rows = []
        for pid in ids:
            raw = self.store.read(pid)
            if (raw.get('book') or {}).get('id') != book['id']:
                raise ValueError('章节与主工程关联不一致，请先修复结构。')
            view = self.service.view(raw)
            public = self.store.public(view, self.engine, self.checker)
            rows.append((raw, view, public))
        return rows

    @staticmethod
    def _speech_estimate(project, segment):
        audio = segment.get('audio') or {}
        if audio.get('samples') and audio.get('sample_rate'):
            speed = max(.01, float(project.get('speech_rate', 1.0)))
            return audio['samples'] / audio['sample_rate'] / speed, speed != 1 or bool(segment.get('tempo_edit'))
        text = segment.get('spoken_as') or segment.get('text') or ''
        if project.get('language') == 'zh':
            return max(.2, len(text) / CHINESE_CHARS_PER_SECOND), True
        words = len(re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE))
        return max(.2, words / ENGLISH_WORDS_PER_SECOND), True

    def estimate(self, book_id, revision, chapter_ids, outputs):
        with self.store.lock:
            book = self._book(book_id)
            if book.get('revision', 0) != revision:
                raise RuntimeError('主工程已改变，请刷新后再估算导出。')
            ids = self._selected(book, chapter_ids)
            chosen_outputs = self._outputs(outputs)
            rows = self._effective_rows(book, ids)

        timed = bool(set(chosen_outputs) & TIMED_OUTPUTS)
        total = 0.0
        estimated = False
        waiting = []
        silent_chapters = []
        chapter_rows = []
        chapter_pause = max(0, int(book.get('chapter_pause_ms', 0) or 0))
        for chapter_index, (raw, view, public) in enumerate(rows):
            public_by_id = {s['id']: s for s in public.get('segments', [])}
            spoken = [s for s in view.get('segments', []) if reads_aloud(s, view)]
            if not spoken:
                silent_chapters.append({'project_id': raw['id'], 'name': raw['name']})
                chapter_rows.append({'project_id': raw['id'], 'name': raw['name'],
                                     'seconds': 0, 'estimated': False, 'waiting': 0})
                continue
            chapter_seconds = 0.0
            chapter_estimated = False
            chapter_waiting = 0
            for i, seg in enumerate(spoken):
                state = public_by_id.get(seg['id']) or {}
                if state.get('status') != 'ready':
                    chapter_waiting += 1
                    waiting.append({'project_id': raw['id'], 'segment_id': seg['id'],
                                    'text': seg.get('text', '')[:80]})
                seconds, rough = self._speech_estimate(view, seg)
                chapter_seconds += seconds
                chapter_estimated = chapter_estimated or rough or state.get('status') != 'ready'
                if i < len(spoken) - 1:
                    pause = seg.get('pause_after')
                    if pause is None:
                        pause = view.get('pause_ms', 0)
                    chapter_seconds += max(0, pause) / 1000
                elif chapter_index < len(rows) - 1:
                    pause = seg.get('pause_after')
                    if pause is None:
                        pause = view.get('pause_ms', 0)
                    chapter_seconds += (max(0, pause) + chapter_pause) / 1000
            total += chapter_seconds
            estimated = estimated or chapter_estimated
            chapter_rows.append({'project_id': raw['id'], 'name': raw['name'],
                                 'seconds': chapter_seconds, 'estimated': chapter_estimated,
                                 'waiting': chapter_waiting})

        hours = total / 3600
        sizes = {}
        if 'wav' in chosen_outputs:
            sizes['wav'] = round(total * WAV_BYTES_PER_SECOND)
        if 'mp3' in chosen_outputs:
            sizes['mp3'] = round(hours * MP3_BYTES_PER_HOUR)
        if 'zip' in chosen_outputs or 'xml' in chosen_outputs:
            sizes['zip'] = round(hours * ZIP_BYTES_PER_HOUR)
        if 'srt' in chosen_outputs:
            sizes['srt'] = max(4096, sum(len(s.get('text', '')) for _, v, _ in rows for s in v.get('segments', [])) * 8)
        if 'timeline' in chosen_outputs or 'xml' in chosen_outputs:
            sizes['timeline'] = max(8192, sum(len(v.get('segments', [])) for _, v, _ in rows) * 900)
        if 'report' in chosen_outputs:
            sizes['report'] = max(8192, sum(len(v.get('segments', [])) for _, v, _ in rows) * 1200)

        final_bytes = sum(sizes.values())
        # MP3 conversion needs a temporary full WAV when WAV itself was not asked for.
        temp_bytes = 0
        if 'mp3' in chosen_outputs and 'wav' not in chosen_outputs:
            temp_bytes += round(total * WAV_BYTES_PER_SECOND)
        if 'zip' in chosen_outputs or 'xml' in chosen_outputs:
            # Delivery audio is staged before compression.
            temp_bytes += round(total * WAV_BYTES_PER_SECOND)
        required_bytes = round((final_bytes + temp_bytes) * 1.15) + 64 * 1024 * 1024
        free_bytes = shutil.disk_usage(self.export_root).free
        blocked = []
        warnings = []
        if timed and waiting:
            blocked.append(f'还有 {len(waiting)} 句没有当前可用的声音。')
        if timed and silent_chapters:
            blocked.append('所选章节中有完全不朗读的章节：' + '、'.join(x['name'] for x in silent_chapters[:6]))
        if timed and total > MAX_SECONDS:
            blocked.append('本次音频预计超过 8 小时，请减少章节后分批导出。')
        elif timed and total > WARN_SECONDS:
            warnings.append('本次音频超过 6 小时，属于大型导出，建议确认磁盘空间并考虑分批。')
        if required_bytes > free_bytes:
            blocked.append(f'磁盘空间不足，预计还需要约 {(required_bytes-free_bytes)/1_000_000_000:.1f} GB。')
        implicit = ['zip'] if 'xml' in chosen_outputs and 'zip' not in chosen_outputs else []
        return {
            'book_id': book_id, 'book_revision': revision,
            'selected_chapters': ids, 'outputs': chosen_outputs,
            'implicit_outputs': implicit, 'chapter_pause_ms': chapter_pause,
            'seconds': total, 'estimated': estimated, 'chapters': chapter_rows,
            'waiting': waiting, 'silent_chapters': silent_chapters,
            'estimated_sizes': sizes, 'estimated_final_bytes': final_bytes,
            'estimated_temporary_bytes': temp_bytes, 'estimated_required_bytes': required_bytes,
            'free_bytes': free_bytes, 'warnings': warnings, 'blocked': blocked,
            'can_export': not blocked,
        }

    def _batch_id(self, root):
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')
        seq = 1
        while (root / f'{stamp}-{seq:03d}').exists() or any(
                p.name.endswith(f'{stamp}-{seq:03d}') for p in self.export_root.glob('.staging-*')):
            seq += 1
        return f'{stamp}-{seq:03d}'

    @staticmethod
    def _hardlink(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)

    def _freeze(self, book, rows, ids, staging, outputs, fps, batch_id):
        sources = staging / 'sources'
        projects = []
        assets = []
        need_audio = bool(set(outputs) & TIMED_OUTPUTS)
        for raw, view, public in rows:
            public_by_id = {s['id']: s for s in public.get('segments', [])}
            frozen = deepcopy(view)
            # Histories are not an export input and can be very large.
            frozen.pop('history', None)
            frozen.pop('future', None)
            projects.append({
                'id': raw['id'], 'name': raw['name'], 'revision': raw.get('revision', 0),
                'effective': frozen,
                'public_segments': public.get('segments', []),
            })
            if not need_audio:
                continue
            for seg in frozen.get('segments', []):
                if not reads_aloud(seg, frozen):
                    continue
                state = public_by_id.get(seg['id']) or {}
                if set(outputs) & TIMED_OUTPUTS and state.get('status') != 'ready':
                    raise RuntimeError('导出开始前声音状态发生变化，请刷新后再试。')
                audio = seg.get('audio') or {}
                fp = audio.get('fingerprint')
                if not fp:
                    continue
                source = self.store.directory(raw['id']) / 'audio' / (fp + '.wav')
                if not source.is_file():
                    raise RuntimeError('导出开始前有声音文件缺失，请重新生成受影响句子。')
                source_stat = source.stat()
                target = sources / raw['id'] / 'audio' / source.name
                self._hardlink(source, target)
                assets.append({
                    'project_id': raw['id'], 'segment_id': seg['id'],
                    'fingerprint': fp, 'sha256': _sha256(target),
                    'bytes': target.stat().st_size,
                    'source_mtime_ns': source_stat.st_mtime_ns,
                })
        snapshot = {
            'schema_version': 1, 'batch_id': batch_id, 'book_id': book['id'], 'book_title': book['title'],
            'book_revision': book.get('revision', 0),
            'member_order': list(book.get('members', [])),
            'selected_chapters': ids,
            'project_revisions': {row['id']: row['revision'] for row in projects},
            'cast': deepcopy(book.get('cast', [])), 'aliases': deepcopy(book.get('aliases', {})),
            'book_settings': deepcopy(book.get('settings', {})),
            'chapter_pause_ms': int(book.get('chapter_pause_ms', 0) or 0),
            'outputs': list(outputs), 'video_fps': fps,
            'assets': assets, 'projects': projects,
        }
        _json(staging / 'snapshot.json', snapshot)
        return snapshot

    @staticmethod
    def _srt(cues, rate):
        return '\n'.join(
            f'{i+1}\n{timestamp(a, rate)} --> {timestamp(b, rate)}\n{shown}\n'
            for i, (a, b, shown, _) in enumerate(cues)
        )

    def _delivery(self, staging, entries, cues, rate, total_samples, manifest):
        delivery = staging / 'delivery'
        delivery.mkdir(parents=True, exist_ok=True)
        timeline_rows = []
        for index, entry in enumerate(entries, 1):
            row = {
                'index': index, 'chapter_index': entry['chapter_index'],
                'chapter': entry['chapter'], 'speaker': entry['speaker'],
                'start': entry['file_start_sample'] / rate,
                'end': entry['file_end_sample'] / rate,
                'duration': (entry['file_end_sample'] - entry['file_start_sample']) / rate,
                'file': entry['delivery_file'], 'text': entry['text'],
                'id': entry['id'], 'project_id': entry['project_id'],
                'start_sample': entry['file_start_sample'],
                'end_sample': entry['file_end_sample'],
                'samples': entry['file_end_sample'] - entry['file_start_sample'],
                'sample_rate': rate,
                'speech_start_sample': entry['speech_start_sample'],
                'speech_end_sample': entry['speech_end_sample'],
                'synthetic_audio': True,
            }
            timeline_rows.append(row)
        timeline = {
            'schema_version': 2, 'synthetic_audio': True, 'sample_rate': rate,
            'total_samples': total_samples, 'sample_fields_are_authoritative': True,
            'end_sample_is_exclusive': True,
            'audio_processing': 'final_rendered_pcm; speed and clip edits already applied',
            'reconstruction_tolerance_samples': 0, 'segments': timeline_rows,
        }
        _json(delivery / 'timeline.json', timeline)
        if timeline_rows:
            with (delivery / 'timeline.csv').open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(timeline_rows[0]), quoting=csv.QUOTE_ALL)
                writer.writeheader()
                writer.writerows(timeline_rows)
        (delivery / 'subtitles.srt').write_text(self._srt(cues, rate), encoding='utf-8')
        lines = ['WEBVTT\n']
        for index, (start, end, shown, _) in enumerate(cues, 1):
            lines.append(f'{index}\n{_vtt_time(start, rate)} --> {_vtt_time(end, rate)}\n'
                         f'{html.escape(shown, quote=False)}\n')
        (delivery / 'subtitles.vtt').write_text('\n'.join(lines), encoding='utf-8')
        _json(delivery / 'manifest.json', manifest)
        (delivery / 'README.txt').write_text(
            'VoxStage · Master-book portable delivery\n\n'
            'audio/ contains final sentence WAV files after speed and clip edits.\n'
            'timeline.json/csv use sample positions as the authoritative placement.\n'
            'Subtitles share the same export snapshot and time origin.\n'
            '整包来自同一次主工程导出快照；逐句 WAV 已应用当前语速与剪辑。\n',
            encoding='utf-8')
        return timeline

    def _render(self, snapshot, staging, requested_outputs, fps):
        outputs = list(requested_outputs)
        effective_outputs = list(outputs)
        implicit = []
        if 'xml' in outputs and 'zip' not in effective_outputs:
            effective_outputs.append('zip')
            implicit.append('zip')
        timed = bool(set(outputs) & TIMED_OUTPUTS)
        report_only = not timed
        project_rows = snapshot['projects']
        selected = snapshot['selected_chapters']
        by_id = {row['id']: row for row in project_rows}

        # A report-only batch intentionally does not touch audio.
        if report_only:
            report = self._report(snapshot, by_id)
            _json(staging / 'content-check.json', report)
            return {
                'sample_rate': None, 'total_samples': 0, 'seconds': 0,
                'entries': [], 'cues': [], 'files': {'report': 'content-check.json'},
                'implicit_outputs': implicit,
            }

        need_full = 'wav' in outputs or 'mp3' in outputs
        temporary_wav = need_full
        full_path = staging / 'full.wav'
        writer = None
        rate = None
        position = 0
        entries = []
        cues = []
        ordinal = 0
        need_delivery = 'zip' in effective_outputs or 'xml' in outputs
        if need_delivery:
            (staging / 'delivery' / 'audio').mkdir(parents=True, exist_ok=True)

        try:
            for chapter_pos, pid in enumerate(selected):
                row = by_id[pid]
                project = row['effective']
                source_dir = staging / 'sources' / pid
                spoken = [s for s in project.get('segments', []) if reads_aloud(s, project)]
                if not spoken:
                    raise ValueError(f'《{row["name"]}》没有可朗读内容，请取消勾选或恢复需要朗读的角色。')
                for seg_index, segment in enumerate(spoken):
                    pcm, current_rate, meta, mapping = prepare_segment(project, segment, source_dir)
                    if rate is None:
                        rate = current_rate
                        if temporary_wav:
                            writer = sf.SoundFile(full_path, mode='w', samplerate=rate,
                                                  channels=1, subtype='PCM_16')
                    elif current_rate != rate:
                        raise ValueError('所选章节存在不同采样率，不能合并导出。')
                    ordinal += 1
                    file_start = position
                    speech_start = position + meta['speech_start_sample']
                    speech_end = position + meta['speech_end_sample']
                    if writer is not None:
                        writer.write(pcm)
                    delivery_file = None
                    if need_delivery:
                        role = re.sub(r'[^\w.-]', '_', segment['speaker'],
                                      flags=re.UNICODE).strip('._')[:40] or 'speaker'
                        line = _slug(segment.get('text', ''), 90 - len(role.encode()))
                        delivery_file = f'audio/{ordinal:05d}_{role}{line}.wav'
                        sf.write(staging / 'delivery' / delivery_file, pcm, rate, subtype='PCM_16')
                    entry = {
                        'id': segment['id'], 'project_id': pid,
                        'chapter_index': chapter_pos + 1, 'chapter': row['name'],
                        'speaker': segment['speaker'], 'text': segment['text'],
                        'file_start_sample': file_start,
                        'file_end_sample': position + len(pcm),
                        'speech_start_sample': speech_start,
                        'speech_end_sample': speech_end,
                        'speech_boundary_method': meta['speech_boundary_method'],
                        'synthetic_audio': True, 'speech_rate': project.get('speech_rate', 1.0),
                        'tempo_mapping': mapping, 'delivery_file': delivery_file,
                        'processed_checks': {
                            **{k: v for k, v in analyze(pcm, rate).items() if k != 'waveform'},
                            'notice': '成品低能量检查；时间为该句成品秒数，不代表自然度通过。',
                        },
                    }
                    entries.append(entry)
                    cues += subtitle_cues(segment, segment['text'], speech_start, speech_end,
                                          project['language'], pcm, rate, mapping, position)
                    position += len(pcm)

                    is_last_in_chapter = seg_index == len(spoken) - 1
                    is_last_selected = chapter_pos == len(selected) - 1
                    pause_ms = 0
                    if not is_last_in_chapter:
                        pause_ms = segment.get('pause_after')
                        if pause_ms is None:
                            pause_ms = project.get('pause_ms', 0)
                    elif not is_last_selected:
                        sentence_pause = segment.get('pause_after')
                        if sentence_pause is None:
                            sentence_pause = project.get('pause_ms', 0)
                        pause_ms = max(0, sentence_pause) + max(0, snapshot.get('chapter_pause_ms', 0))
                    if pause_ms:
                        pause_samples = round(rate * pause_ms / 1000)
                        if writer is not None:
                            block = np.zeros(min(pause_samples, rate * 10), dtype=np.float32)
                            left = pause_samples
                            while left:
                                n = min(left, len(block))
                                writer.write(block[:n])
                                left -= n
                        position += pause_samples
                    if rate and position / rate > MAX_SECONDS:
                        raise ValueError('实际合并音频超过 8 小时，本批已停止；上一次成功导出保持不变。')
        finally:
            if writer is not None:
                writer.close()

        if rate is None:
            raise ValueError('所选章节没有可导出的声音。')
        cues = hold_briefest(cues, rate)
        files = {}
        if 'wav' in outputs:
            files['wav'] = 'full.wav'
        if 'srt' in outputs:
            (staging / 'subtitles.srt').write_text(self._srt(cues, rate), encoding='utf-8')
            files['srt'] = 'subtitles.srt'

        timeline = {
            'schema_version': 2, 'batch_id': snapshot['batch_id'], 'book_id': snapshot['book_id'],
            'book_revision': snapshot['book_revision'],
            'project_revisions': snapshot['project_revisions'],
            'selected_chapters': selected, 'sample_rate': rate,
            'total_samples': position, 'seconds': position / rate,
            'synthetic_audio': True,
            'segments': [{k: v for k, v in e.items() if k != 'processed_checks'} for e in entries],
            'subtitle_cues': [
                {'start_sample': a, 'end_sample': b, 'text': shown, 'estimated': estimated}
                for a, b, shown, estimated in cues
            ],
        }
        if 'timeline' in outputs:
            _json(staging / 'timeline.json', timeline)
            files['timeline'] = 'timeline.json'

        report = self._report(snapshot, by_id, entries)
        if 'report' in outputs:
            _json(staging / 'content-check.json', report)
            files['report'] = 'content-check.json'

        delivery_timeline = None
        if need_delivery:
            manifest_stub = {
                'batch_id': snapshot['batch_id'], 'book_id': snapshot['book_id'], 'book_title': snapshot['book_title'],
                'book_revision': snapshot['book_revision'],
                'project_revisions': snapshot['project_revisions'],
                'selected_chapters': selected, 'chapter_pause_ms': snapshot['chapter_pause_ms'],
                'sample_rate': rate, 'total_samples': position,
            }
            delivery_timeline = self._delivery(staging, entries, cues, rate, position, manifest_stub)
            archive = staging / 'delivery.zip'
            with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED,
                                 allowZip64=True) as bundle:
                for path in sorted((staging / 'delivery').rglob('*')):
                    if path.is_file():
                        bundle.write(path, Path('delivery') / path.relative_to(staging / 'delivery'))
            files['zip'] = 'delivery.zip'

        if 'xml' in outputs:
            if fps not in FPS_CHOICES:
                raise ValueError('视频项目帧率请选择 24、25、30、50 或 60')
            payload = timeline_xml(delivery_timeline, fps)
            xml_name = f'timeline-{fps}fps.xml'
            (staging / xml_name).write_bytes(payload)
            (staging / 'timeline-README.txt').write_text(IMPORT_GUIDE, encoding='utf-8')
            files['xml'] = xml_name
            files['xml_readme'] = 'timeline-README.txt'

        if 'mp3' in outputs:
            ffmpeg = ffmpeg_path()
            if not ffmpeg:
                raise ValueError('这台电脑找不到 FFmpeg，不能生成 MP3。')
            done = subprocess.run(
                [ffmpeg, '-y', '-loglevel', 'error', '-i', str(full_path),
                 '-codec:a', 'libmp3lame', '-q:a', '2', str(staging / 'full.mp3')],
                capture_output=True, text=True, timeout=3600)
            if done.returncode != 0 or not (staging / 'full.mp3').is_file():
                raise RuntimeError('MP3 转换失败：' + done.stderr.strip()[:200])
            files['mp3'] = 'full.mp3'

        if temporary_wav and 'wav' not in outputs:
            full_path.unlink(missing_ok=True)
        if need_delivery:
            shutil.rmtree(staging / 'delivery', ignore_errors=True)
        return {
            'sample_rate': rate, 'total_samples': position, 'seconds': position / rate,
            'entries': entries, 'cues': cues, 'files': files,
            'implicit_outputs': implicit,
        }

    @staticmethod
    def _report(snapshot, by_id, rendered_entries=None):
        rendered = {entry['id']: entry for entry in rendered_entries or []}
        chapters = []
        for pid in snapshot['selected_chapters']:
            row = by_id[pid]
            segments = []
            for state in row.get('public_segments', []):
                segments.append({
                    'id': state['id'], 'speaker': state.get('speaker'),
                    'text': state.get('text'), 'status': state.get('status'),
                    'check_status': state.get('check_status'),
                    'content_check': state.get('content_check'),
                    'listening_status': state.get('listening_status'),
                    'listening_issue': state.get('listening_issue'),
                    'rhythm_status': state.get('rhythm_status'),
                    'rhythm_check': state.get('rhythm_check'),
                    'tempo_status': state.get('tempo_status'),
                    'tempo_edit': state.get('tempo_edit'),
                    'rendered': state['id'] in rendered,
                })
            chapters.append({'project_id': pid, 'name': row['name'],
                             'revision': row['revision'], 'segments': segments})
        return {
            'schema_version': 2, 'batch_id': snapshot['batch_id'], 'book_id': snapshot['book_id'],
            'book_title': snapshot['book_title'], 'book_revision': snapshot['book_revision'],
            'project_revisions': snapshot['project_revisions'],
            'selected_chapters': snapshot['selected_chapters'],
            'synthetic_audio': True, 'chapters': chapters,
            'notice': '报告属于本次导出快照；之后的工程修改不会改写这份报告。',
        }

    def create(self, book_id, revision, chapter_ids, outputs, fps):
        chosen_outputs = self._outputs(outputs)
        if fps not in FPS_CHOICES:
            raise ValueError('视频项目帧率请选择 24、25、30、50 或 60')
        # Check existing jobs and claim the book while holding Store.lock. Any
        # later Store.write then sees active_books and is refused by the guard.
        with self.store.lock:
            book = self._book(book_id)
            if book.get('revision', 0) != revision:
                raise RuntimeError('主工程已改变，请刷新后再导出。')
            ids = self._selected(book, chapter_ids)
            rows = self._effective_rows(book, ids)
            all_members = [self.store.read(pid) for pid in book.get('members', [])]
            busy = [raw['name'] for raw in all_members
                    if (raw.get('job') or {}).get('status') in ('queued', 'running')]
            if busy:
                raise RuntimeError('同一主工程有章节正在处理：' + '、'.join(busy[:6]) + '。请完成后再导出。')
            with self._active_lock:
                if self.active_books:
                    raise RuntimeError('已有整书导出正在进行。第一版一次只运行一个大型导出任务。')
                self.active_books.add(book_id)
        staging = None
        try:
            estimate = self.estimate(book_id, revision, chapter_ids, chosen_outputs)
            if estimate['blocked']:
                raise ValueError('；'.join(estimate['blocked']))
            with self.store.lock:
                book = self._book(book_id)
                if book.get('revision', 0) != revision:
                    raise RuntimeError('主工程已改变，请重新打开导出窗口。')
                ids = self._selected(book, chapter_ids)
                rows = self._effective_rows(book, ids)
                for member_id in book.get('members', []):
                    raw = self.store.read(member_id)
                    if (raw.get('job') or {}).get('status') in ('queued', 'running'):
                        raise RuntimeError(f'《{raw["name"]}》正在处理，请结束后再导出。')
                root = self._root(book_id)
                batch_id = self._batch_id(root)
                staging = self.export_root / ('.staging-' + book_id + '-' + batch_id)
                staging.mkdir(parents=True, exist_ok=False)
                snapshot = self._freeze(book, rows, ids, staging, chosen_outputs, fps, batch_id)

            created_utc = datetime.now(timezone.utc).isoformat()
            result = self._render(snapshot, staging, chosen_outputs, fps)
            # The hard-linked source WAVs were only needed to make the render
            # deterministic. Their hashes/stats remain in snapshot.json; keeping
            # thousands of extra links after success would only clutter the disk.
            shutil.rmtree(staging / 'sources', ignore_errors=True)
            manifest = {
                'schema_version': 1, 'batch_id': batch_id, 'status': 'success',
                'created_at_utc': created_utc,
                'created_at_local': datetime.now().astimezone().isoformat(),
                'book_id': book_id, 'book_title': snapshot['book_title'],
                'book_revision': snapshot['book_revision'],
                'project_revisions': snapshot['project_revisions'],
                'selected_chapters': snapshot['selected_chapters'],
                'outputs_requested': chosen_outputs,
                'implicit_outputs': result['implicit_outputs'],
                'files': result['files'], 'video_fps': fps,
                'chapter_pause_ms': snapshot['chapter_pause_ms'],
                'audio_assets': snapshot.get('assets', []),
                'sample_rate': result['sample_rate'],
                'total_samples': result['total_samples'], 'seconds': result['seconds'],
                'snapshot_sha256': _sha256(staging / 'snapshot.json'),
            }
            _json(staging / 'manifest.json', manifest)

            root = self._root(book_id)
            root.mkdir(parents=True, exist_ok=True)
            final = root / batch_id
            os.replace(staging, final)
            staging = None
            last_path = root / 'last.json'
            previous = None
            if last_path.is_file():
                try:
                    previous = json.loads(last_path.read_text()).get('batch_id')
                except (OSError, ValueError):
                    previous = None
            _json(last_path, {'batch_id': batch_id})
            if previous and previous != batch_id:
                shutil.rmtree(root / previous, ignore_errors=True)
            return self.current(book_id)
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
            with self._active_lock:
                self.active_books.discard(book_id)

    def current(self, book_id):
        book = self._book(book_id)
        root = self._root(book_id)
        last_path = root / 'last.json'
        if not last_path.is_file():
            return {'status': 'none', 'book_id': book_id, 'links': {}}
        try:
            batch_id = json.loads(last_path.read_text())['batch_id']
            batch = root / batch_id
            manifest = json.loads((batch / 'manifest.json').read_text())
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return {'status': 'none', 'book_id': book_id, 'links': {}}
        current_revisions = {}
        stale_reasons = []
        if book.get('revision', 0) != manifest.get('book_revision'):
            stale_reasons.append('主工程在导出后有改动')
        for pid, revision in (manifest.get('project_revisions') or {}).items():
            try:
                now = self.store.read(pid).get('revision', 0)
            except (OSError, ValueError):
                now = None
            current_revisions[pid] = now
            if now != revision:
                stale_reasons.append('至少一个章节在导出后有改动')
                break
        # Revision is the normal validity signal. Also catch a manually replaced
        # or externally damaged WAV that bypassed the application revision.
        try:
            for asset in manifest.get('audio_assets', []):
                path = (self.store.directory(asset['project_id']) / 'audio'
                        / (asset['fingerprint'] + '.wav'))
                if not path.is_file():
                    stale_reasons.append('导出后有源声音文件缺失')
                    break
                stat = path.stat()
                if (stat.st_size != asset.get('bytes')
                        or stat.st_mtime_ns != asset.get('source_mtime_ns')):
                    stale_reasons.append('导出后有源声音文件发生变化')
                    break
        except (OSError, ValueError, KeyError):
            stale_reasons.append('无法核对这次导出的声音快照')
        links = {}
        for key, name in (manifest.get('files') or {}).items():
            if (batch / name).is_file():
                links[key] = f'/api/master-books/{book_id}/export/{batch_id}/{name}'
        links['manifest'] = f'/api/master-books/{book_id}/export/{batch_id}/manifest.json'
        return {
            'status': 'stale' if stale_reasons else 'latest',
            'book_id': book_id, 'batch_id': batch_id,
            'book_revision': manifest.get('book_revision'),
            'current_book_revision': book.get('revision', 0),
            'project_revisions': manifest.get('project_revisions', {}),
            'current_project_revisions': current_revisions,
            'selected_chapters': manifest.get('selected_chapters', []),
            'outputs_requested': manifest.get('outputs_requested', []),
            'implicit_outputs': manifest.get('implicit_outputs', []),
            'seconds': manifest.get('seconds', 0),
            'created_at_utc': manifest.get('created_at_utc'),
            'created_at_local': manifest.get('created_at_local'),
            'stale_reasons': list(dict.fromkeys(stale_reasons)),
            'links': links,
        }

    def download(self, book_id, batch_id, name):
        if not re.fullmatch(r'\d{8}-\d{6}-\d{3}', batch_id):
            raise FileNotFoundError
        root = self._root(book_id) / batch_id
        manifest_path = root / 'manifest.json'
        if not manifest_path.is_file():
            raise FileNotFoundError
        manifest = json.loads(manifest_path.read_text())
        allowed = set((manifest.get('files') or {}).values()) | {'manifest.json'}
        if name not in allowed or '/' in name or '\\' in name:
            raise FileNotFoundError
        path = root / name
        if not path.is_file():
            raise FileNotFoundError
        return path

    def export_settings(self, book_id):
        book = self._book(book_id)
        return {'book_id': book_id, 'revision': book.get('revision', 0),
                'chapter_pause_ms': int(book.get('chapter_pause_ms', 0) or 0)}

    def update_export_settings(self, book_id, revision, chapter_pause_ms):
        with self.store.lock:
            self.assert_book_writable(book_id)
            book = self._book(book_id)
            if book.get('revision', 0) != revision:
                raise RuntimeError('主工程已改变，请刷新后再保存导出设置。')
            if isinstance(chapter_pause_ms, bool) or not isinstance(chapter_pause_ms, int) or not 0 <= chapter_pause_ms <= 10_000:
                raise ValueError('章节间停顿必须是 0–10000 毫秒整数。')
            updated = deepcopy(book)
            updated['chapter_pause_ms'] = chapter_pause_ms
            updated['revision'] = revision + 1
            temporary = self.books.root / ('.' + book_id + '.json.tmp')
            self.service._write_json(temporary, updated)
            os.replace(temporary, self.books.root / (book_id + '.json'))
            return self.export_settings(book_id)

