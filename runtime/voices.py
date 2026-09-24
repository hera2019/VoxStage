"""A named library of reference voices, so a good one can be kept and reused.

The preset checkpoint declares nine speakers and English has two of them, both
male. A reference voice lifts that ceiling: keep a sample you liked, give it a
name, assign it to a character. References measurably steady delivery as well —
a fixed reference constrained a drifting preset from 36% to 9% variation.

Two ways in, and they carry different obligations:

  generated  a line the model itself produced, chosen from an audition. No
             human voice involved, so nothing to consent to.
  provided   audio a person supplies. Requires explicit confirmation that they
             own the voice or hold permission, recorded with the entry.

Reference audio never enters version control, whichever way it arrived.
"""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf

PREFIX = 'custom:'
MIN_SECONDS, MAX_SECONDS = 1.5, 60.0
NAME_PATTERN = re.compile(r'^[^\x00-\x1f/\\]{1,40}$')


def is_custom(voice):
    return isinstance(voice, str) and voice.startswith(PREFIX)


def custom_id(voice):
    return voice[len(PREFIX):] if is_custom(voice) else None


def _sort_key(name):
    """Name order as a Chinese reader expects it: by pinyin (粗嗓 before 冷峻
    before 稳重), Latin letters by themselves, numbers as numbers (Old Man2
    before Old Man10). So a prefix like Z- files a voice at the end
    (本人 2026-09-23: 旧声线前面加了 Z-，好区分)."""
    try:
        from pypinyin import lazy_pinyin
        spelled = ' '.join(lazy_pinyin(name or ''))
    except ImportError:                                # the checker's dependency; without it, plain order
        spelled = name or ''
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', spelled)]


class VoiceLibrary:
    def __init__(self, root):
        self.root = Path(root)

    def _path(self, voice_id, suffix):
        if not re.fullmatch('[a-f0-9]{32}', voice_id or ''):
            raise ValueError('无效的音色编号。')
        return self.root / (voice_id + suffix)

    def list(self):
        """Every kept voice, by name."""
        out = []
        for path in sorted(self.root.glob('*.json')) if self.root.is_dir() else []:
            try:
                entry = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if (self.root / (entry.get('id', '') + '.wav')).is_file():
                out.append(entry)
        # By name (本人 2026-09-23: 建议使用名称排序，好找) — a library of fifty
        # voices is looked through by name, not by when it was made; digits sort
        # as numbers so 声线2 follows 声线, not 声线10.
        out.sort(key=lambda e: _sort_key(e.get('name', '')))
        return out

    def get(self, voice_id):
        entry = json.loads(self._path(voice_id, '.json').read_text())
        audio = self._path(voice_id, '.wav')
        if hashlib.sha256(audio.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('音色参考文件已改变；请重新建立这个音色。')
        return entry

    def audio_path(self, voice_id):
        self.get(voice_id)
        return self._path(voice_id, '.wav')

    def create(self, *, name, pcm, rate, reference_text, language,
               source, consent_confirmed=False, derived_from=None):
        """Store one reference. `provided` audio is refused without confirmation."""
        if not NAME_PATTERN.match((name or '').strip()):
            raise ValueError('音色名称需为 1–40 个字符，且不含斜杠或控制字符。')
        if source not in ('generated', 'provided'):
            raise ValueError('未知的音色来源。')
        if source == 'provided' and not consent_confirmed:
            # The gate is here, in code, not only in a checkbox on a screen.
            raise ValueError('使用他人或本人录音建立音色前，必须确认拥有该声音的使用权或已获授权。')
        pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
        seconds = len(pcm) / rate
        if not MIN_SECONDS <= seconds <= MAX_SECONDS:
            raise ValueError(f'参考声音需在 {MIN_SECONDS:g}–{MAX_SECONDS:g} 秒之间，当前 {seconds:.1f} 秒。')
        if not np.isfinite(pcm).all() or float(np.max(np.abs(pcm))) < 1e-4:
            raise ValueError('参考声音无效或几乎无声。')
        if not (reference_text or '').strip():
            raise ValueError('请填写参考声音实际说出的文字。')
        voice_id = uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        audio = self._path(voice_id, '.wav')
        sf.write(audio, pcm, int(rate), subtype='PCM_16')
        entry = {'id': voice_id, 'name': name.strip(), 'language': language,
                 'reference_text': reference_text.strip(),
                 'sha256': hashlib.sha256(audio.read_bytes()).hexdigest(),
                 'source': source, 'consent_confirmed': bool(consent_confirmed),
                 'derived_from': derived_from, 'sample_rate': int(rate),
                 'seconds': round(seconds, 3), 'created_at': time.time(),
                 'synthetic_audio': source == 'generated'}
        self._path(voice_id, '.json').write_text(json.dumps(entry, ensure_ascii=False, indent=1))
        return entry

    def rename(self, voice_id, name):
        if not NAME_PATTERN.match((name or '').strip()):
            raise ValueError('音色名称需为 1–40 个字符，且不含斜杠或控制字符。')
        entry = self.get(voice_id)
        entry['name'] = name.strip()
        self._path(voice_id, '.json').write_text(json.dumps(entry, ensure_ascii=False, indent=1))
        return entry

    def set_pack(self, voice_id, pack, role=None):
        """Mark a voice as one of a shipped pack (本人 2026-09-23: 默认音色库), with
        what it is for — {'sex': 'm'|'f'|'', 'age': 'adult'|'old'|'child',
        'narrator': bool} — so a new character can be given one that fits.
        `pack=None` takes the mark away."""
        entry = self.get(voice_id)
        if pack:
            entry['pack'] = pack
            entry['pack_role'] = {'sex': (role or {}).get('sex', ''), 'age': (role or {}).get('age', 'adult'),
                                  'narrator': bool((role or {}).get('narrator')), 'rank': int((role or {}).get('rank', 99))}
        else:
            entry.pop('pack', None); entry.pop('pack_role', None)
        self._path(voice_id, '.json').write_text(json.dumps(entry, ensure_ascii=False, indent=1))
        return entry

    def pack(self, name='default'):
        """The voices of a pack, in name order."""
        return [e for e in self.list() if e.get('pack') == name]

    def delete(self, voice_id, in_use_by=()):
        if in_use_by:
            raise ValueError(f"这个音色仍被工程使用：{'、'.join(sorted(in_use_by)[:5])}。请先改用其它音色。")
        self.get(voice_id)
        self._path(voice_id, '.wav').unlink(missing_ok=True)
        self._path(voice_id, '.json').unlink(missing_ok=True)
        return {'deleted': voice_id}

    def label(self, voice):
        """Human-readable name for a voice reference, custom or preset."""
        vid = custom_id(voice)
        if not vid:
            return None
        try:
            entry = self.get(vid)
        except (OSError, ValueError, KeyError):
            return None
        return entry['name']

# 最后更新：2026-09-11 · Claude Hera
