"""One-shot listening samples using the existing fixed synthetic reference path.

Self-written text is listening material, not an acceptance standard.
Run once per output directory; no candidate selection or automatic retries.
"""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import soundfile as sf
from runtime.audio import process_audio
from runtime.engines import MlxEngine, reference_parameters

GROUPS = [
    {
        'language': 'zh', 'speaker': '旁白', 'voice': 'Vivian',
        'reference': 'user-data/projects/c138d1570f40447fa65e4a0b7f1d00bc/audio/b73d3faf5b98ebf751c5d09563a32b64f72ca83f2332ecb65a1160c5ad644e25.wav',
        'reference_sha256': '17b265394291e74898a4a962f59d0586a164c15eed59a6ccfa42b4f08a41f0fc',
        'reference_text': '雨点轻轻敲着窗。',
        'sentences': [
            '傍晚的雨还没有停，窗边的台灯已经亮了起来。',
            '桌上放着一本旧笔记，蓝色的封面有些褪色。',
            '他翻到夹着书签的那一页，慢慢读完了最后一行。',
            '那是去年春天留下的记录，写着一条通往河边的小路。',
            '杯里的茶渐渐凉了，屋子里只听得到轻轻的雨声。',
            '他合上笔记，把它放回原处，又望了一眼窗外。',
        ],
    },
    {
        'language': 'en', 'speaker': 'Narrator', 'voice': 'Ryan',
        'reference': 'user-data/projects/0389b87c86a24bf18c0a6948731a3743/references/98ff5dafe716610138027f3c5bb9067e3457b5e26aa5ad058ffc12ffed574646.wav',
        'reference_sha256': '98ff5dafe716610138027f3c5bb9067e3457b5e26aa5ad058ffc12ffed574646',
        'reference_text': 'Rain tapped against the window.',
        'sentences': [
            'The evening rain continued as the lamp beside the window came on.',
            'An old notebook lay on the desk, its blue cover faded at the edges.',
            'He opened it at the bookmark and slowly read the final line.',
            'The entry was from last spring and described a narrow path down to the river.',
            'His tea was growing cold, and the soft rain was the only sound in the room.',
            'He closed the notebook, put it back in its place, and looked outside once more.',
        ],
    },
]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'user-data/voice-consistency-listening-2026-09-10')
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        parser.error('Output already exists; retained samples will not be overwritten.')
    for group in GROUPS:
        if sha(ROOT / group['reference']) != group['reference_sha256']:
            raise ValueError('Preserved synthetic reference has changed.')
    out.mkdir(parents=True)
    report = {
        'task': '同一角色跨句音色一致性试听样本', 'synthetic_audio': True,
        'author': 'Astra', 'started_at': now(), 'status': 'running',
        'text_origin': 'self_written_by_Astra; listening_material_only',
        'seed': 260909, 'generation_parameters': reference_parameters(),
        'attempts_per_sentence': 1, 'inserted_gap_seconds': 0.5,
        'postprocessing': 'existing process_audio peak normalization; no trimming or time stretch',
        'runtime': {'python': platform.python_version(), 'platform': platform.platform(),
                    **{name: importlib.metadata.version(name) for name in ('mlx', 'mlx-audio', 'numpy', 'soundfile')}},
        'source_sha256': {name: sha(ROOT / name) for name in (
            'scripts/generate_voice_consistency_samples.py', 'runtime/engines.py', 'runtime/audio.py')},
        'measurement_type': 'measured for timings, frame counts and hashes; generation settings are configured values',
        'unverified': ['same_speaker_timbre', 'same_acoustic_space', 'pronunciation_and_completeness', 'human_listening_acceptance'],
        'groups': [],
    }
    report_path = out / 'results.json'

    def save():
        temporary = report_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(report_path)

    engine = MlxEngine(ROOT / 'user-data/models/qwen-customvoice')
    report['model'] = engine.reference_identity
    save()
    try:
        for group in GROUPS:
            folder = out / group['language']
            folder.mkdir()
            reference = folder / 'reference.wav'
            shutil.copyfile(ROOT / group['reference'], reference)
            record = {key: value for key, value in group.items() if key != 'sentences'}
            record.update({'reference_copy': str(reference.relative_to(out)), 'synthetic_audio': True, 'sentences': []})
            report['groups'].append(record)
            parts, position, rate = [], 0, None
            for index, text in enumerate(group['sentences'], 1):
                entry = {'index': index, 'speaker': group['speaker'], 'text': text, 'started_at': now(), 'attempt': 1}
                record['sentences'].append(entry)
                save()
                try:
                    raw, current_rate, generation = engine.synthesize_reference(
                        text, group['language'], reference, group['reference_text'], report['seed'],
                        consent_confirmed=True, expected_sha256=group['reference_sha256'])
                    raw_path = folder / f'{index:02d}-raw.wav'
                    sf.write(raw_path, raw, current_rate, subtype='FLOAT')
                    pcm, metadata = process_audio(raw, current_rate)
                    path = folder / f'{index:02d}.wav'
                    sf.write(path, pcm, current_rate, subtype='PCM_16')
                    decoded, decoded_rate = sf.read(path, dtype='int16')
                    if decoded.ndim != 1 or len(decoded) != len(pcm) or decoded_rate != current_rate:
                        raise ValueError('Written audio dimensions differ from generated audio.')
                    if rate is not None and rate != current_rate:
                        raise ValueError('Mixed sample rates.')
                    rate = current_rate
                    if parts:
                        silence = np.zeros(round(rate * report['inserted_gap_seconds']), dtype=np.int16)
                        parts.append(silence)
                        position += len(silence)
                    entry.update({**generation, **metadata, 'status': 'generated',
                                  'file': str(path.relative_to(out)), 'sha256': sha(path),
                                  'raw_file': str(raw_path.relative_to(out)), 'raw_sha256': sha(raw_path),
                                  'duration_seconds': len(decoded) / rate,
                                  'joined_start_sample': position, 'joined_end_sample': position + len(decoded),
                                  'pcm_readback_frames': len(decoded), 'finished_at': now()})
                    parts.append(decoded)
                    position += len(decoded)
                except Exception as exc:
                    entry.update({'status': 'error', 'error': f'{type(exc).__name__}: {exc}', 'finished_at': now()})
                save()
                print(f"{group['language']} {index}/{len(group['sentences'])}: {entry['status']}", flush=True)
            if all(entry.get('status') == 'generated' for entry in record['sentences']):
                joined = np.concatenate(parts)
                joined_path = folder / 'continuous.wav'
                sf.write(joined_path, joined, rate, subtype='PCM_16')
                readback, readback_rate = sf.read(joined_path, dtype='int16')
                if readback_rate != rate or not np.array_equal(readback, joined):
                    raise ValueError('Joined audio differs from sentence PCM and silence.')
                record['continuous_audio'] = {'file': str(joined_path.relative_to(out)),
                    'sha256': sha(joined_path), 'samples': len(joined), 'sample_rate': rate,
                    'duration_seconds': len(joined) / rate, 'pcm_readback_identical': True}
            record['reference_copy_sha256_after_generation'] = sha(reference)
            save()
        report['status'] = 'completed' if all('continuous_audio' in group for group in report['groups']) else 'incomplete'
    except Exception as exc:
        report.update({'status': 'error', 'error': f'{type(exc).__name__}: {exc}'})
        raise
    finally:
        report['finished_at'] = now()
        save()
        engine.unload()
    print(report_path, flush=True)
    return 0 if report['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

# 最后更新：2026-09-10 · Astra
