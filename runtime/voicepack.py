"""The default voice pack (本人 2026-09-23: 确定的音色放进音色库作为默认音色，
打包上传，供人下载使用). Fourteen designed voices — synthetic, no one's recording
(D5) — shipped in `voicepack/default/` as FLAC plus a manifest, and installed
into a person's library the first time the service starts. Installed once per
pack version: a voice the person deleted is not forced back. Claude Hera."""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf

PACK = 'default'
MANIFEST = 'manifest.json'
MARKER = 'voicepack-installed.json'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export(library, folder, *, tags=None, english=None, version=1):
    """Write every library voice marked with the pack to `folder`: one FLAC per
    voice and a manifest. Returns the manifest."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob('*.flac'):
        old.unlink()
    voices = []
    for n, entry in enumerate(sorted(library.pack(PACK), key=lambda e: (e['pack_role'].get('narrator') is not True, e['pack_role'].get('rank', 99))), 1):
        if not entry.get('synthetic_audio') or entry.get('source') != 'generated':
            raise ValueError(f"「{entry['name']}」不是合成声线，不能放进公开的音色包。")
        pcm, rate = sf.read(library.audio_path(entry['id']), dtype='float32')
        file = f"{n:02d}.flac"
        sf.write(folder / file, pcm, rate, format='FLAC', subtype='PCM_16')
        voices.append({'file': file, 'sha256': _sha(folder / file), 'name': entry['name'],
                       'english_name': (english or {}).get(entry['name']), 'language': entry.get('language', 'zh'),
                       'reference_text': entry['reference_text'], 'seconds': round(len(pcm) / rate, 2),
                       'tags': list((tags or {}).get('custom:' + entry['id'], [])), 'pack_role': entry['pack_role'],
                       'synthetic_audio': True})
    manifest = {'pack': PACK, 'version': int(version), 'exported': time.strftime('%Y-%m-%d'),
                'made_with': 'Qwen3-TTS 1.7B VoiceDesign (a voice described in words), re-read with the 1.7B Base model on a standard demo line',
                'licence': 'Synthetic speech generated with Apache-2.0 models; no human recording is in this pack.',
                'voices': voices}
    (folder / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    return manifest


def read(folder):
    path = Path(folder) / MANIFEST
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


def install(library, folder, *, marker_root, force=False):
    """Add the pack's voices to the library. Skipped when this version was
    installed before (unless `force`), and per voice when the library already
    holds one with the pack mark and the same name. Returns the installed
    voices as [(entry, tags)]."""
    manifest = read(folder)
    if not manifest:
        return []
    marker = Path(marker_root) / MARKER
    done = json.loads(marker.read_text(encoding='utf-8')) if marker.is_file() else {}
    if not force and done.get(manifest['pack']) == manifest['version']:
        return []
    present = {e['name'] for e in library.pack(manifest['pack'])}
    installed = []
    for voice in manifest['voices']:
        if voice.get('synthetic_audio') is not True:
            raise ValueError(f"音色包里的「{voice['name']}」没有标为合成声音，拒绝安装。")        # D5: never a recording passed off as synthetic
        if voice['name'] in present:
            continue
        path = Path(folder) / voice['file']
        if _sha(path) != voice['sha256']:
            raise ValueError(f"音色包里的「{voice['name']}」文件校验不一致。")
        pcm, rate = sf.read(path, dtype='float32')
        entry = library.create(name=voice['name'], pcm=np.asarray(pcm, dtype=np.float32), rate=rate,
                               reference_text=voice['reference_text'], language=voice.get('language', 'zh'),
                               source='generated', consent_confirmed=True, derived_from=f"voicepack:{manifest['pack']} v{manifest['version']}")
        entry = library.set_pack(entry['id'], manifest['pack'], voice.get('pack_role'))
        installed.append((entry, voice.get('tags', [])))
    done[manifest['pack']] = manifest['version']
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(done, ensure_ascii=False) + '\n', encoding='utf-8')
    return installed

# 最后更新：2026-09-23 · Claude Hera
