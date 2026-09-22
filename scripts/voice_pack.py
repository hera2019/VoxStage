"""Export the default voice pack from this machine's library into
`voicepack/default/` (FLAC + manifest), for the repository and for others to
install. Only voices marked with the pack are taken; each must be synthetic.

    .venv/bin/python scripts/voice_pack.py export [--version N]

The names stay as they are in the library (Chinese now); the manifest carries
the English name each will take in the English release (docs/voice-pack-roster.md).
Claude Hera, 2026-09-23."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.voices import VoiceLibrary      # noqa: E402
from runtime import voicepack                # noqa: E402

ENGLISH = {'稳重旁白': 'Steady Narrator', '温暖旁白': 'Warm Narrator', '青年男声': 'Young Man', '青年女声': 'Young Woman',
           '温和男声': 'Gentle Man', '温和女声': 'Gentle Woman', '粗嗓男声': 'Gruff Man', '爽利女声': 'Sharp Woman',
           '冷峻男声': 'Cold Voice Man', '冷峻女声': 'Cold Voice Woman', '老年男声': 'Old Man', '老年女声': 'Old Woman',
           '男孩': 'Child Boy', '女孩': 'Child Girl'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('action', choices=['export'])
    ap.add_argument('--version', type=int, default=None, help='默认：比现有包的版本 +1')
    args = ap.parse_args()
    library = VoiceLibrary(ROOT / 'user-data/voices')
    settings = ROOT / 'user-data/settings.json'
    tags = json.loads(settings.read_text(encoding='utf-8')).get('voice_tags', {}) if settings.is_file() else {}
    folder = ROOT / 'voicepack' / 'default'
    old = voicepack.read(folder)
    version = args.version or ((old or {}).get('version', 0) + 1)
    manifest = voicepack.export(library, folder, tags=tags, english=ENGLISH, version=version)
    missing = [n for n in ENGLISH if n not in {v['name'] for v in manifest['voices']}]
    size = sum(f.stat().st_size for f in folder.iterdir())
    print(f"音色包 v{version}：{len(manifest['voices'])} 个声线，{size / 1e6:.1f} MB → {folder}")
    if missing:
        print('名单里缺：', '、'.join(missing))


if __name__ == '__main__':
    main()

# 最后更新：2026-09-23 · Claude Hera
