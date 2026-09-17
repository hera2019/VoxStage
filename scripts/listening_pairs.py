"""Blind listening pairs for the author: the same lines read two ways, 甲/乙 in
random order, the key kept aside (TTS plan, 2026-09-17).

    .venv/bin/python scripts/listening_pairs.py --a qwen:0.6B --b qwen:1.7B  PROJECT_ID:14 PROJECT_ID:19 …
    .venv/bin/python scripts/listening_pairs.py --a qwen:1.7B --b chatterbox  PROJECT_ID:3 …
    .venv/bin/python scripts/listening_pairs.py --a qwen:1.7B --b indextts    PROJECT_ID:3 …

A line is `project id:segment number` (the number the page shows). `qwen:SIZE`
reads a preset line with the preset model of that size and a cloned line
(fixed or designed voice) with the Base of that size; `chatterbox` reads
cloned lines only, as does `indextts`. Same text, same voice reference, same seed on both sides;
only the engine differs. Output: ~/Desktop/VoxStage-对听-<date>/对N-甲.wav,
对N-乙.wav and 说明.txt (what each pair is, not which is which); the key goes
to user-data/listening/<date>.json. Nothing in the projects is touched.
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import soundfile as sf                                                  # noqa: E402
from runtime.audio import process_audio                                 # noqa: E402
from runtime.core import Store, spoken_text, voice_of                   # noqa: E402
from runtime.engines import MlxEngine, ChatterboxEngine, IndexTtsEngine  # noqa: E402
from runtime.voices import VoiceLibrary, is_custom, custom_id           # noqa: E402


def engines_for(spec, qwen, chatter, index):
    kind, _, size = spec.partition(':')
    if kind == 'qwen':
        return qwen, size or '0.6B', f'Qwen3-TTS {size or "0.6B"}'
    if kind == 'chatterbox':
        return chatter, '0.6B', 'Chatterbox Multilingual v3'
    if kind == 'indextts':
        return index, '0.6B', 'IndexTTS 1.5'
    raise SystemExit('引擎写法：qwen:0.6B / qwen:1.7B / chatterbox / indextts')


def read(engine, size, project, segment, library):
    text = spoken_text(project, segment); voice = voice_of(project, segment); seed = 260909 + segment.get('take', 0)
    profile = (project.get('voice_profiles') or {}).get(segment['speaker'])
    if profile:
        ref = Store(ROOT / 'user-data/projects').directory(project['id']) / 'references' / (profile['sha256'] + '.wav')
        pcm, rate, _ = engine.synthesize_reference(text, project['language'], ref, profile['text'], seed, consent_confirmed=True, expected_sha256=profile['sha256'], size=size)
        how = '固定声线'
    elif is_custom(voice):
        entry = library.get(custom_id(voice))
        pcm, rate, _ = engine.synthesize_reference(text, project['language'], library.audio_path(entry['id']), entry['reference_text'], seed, consent_confirmed=True, expected_sha256=entry['sha256'], size=size)
        how = '自定义声线'
    else:
        if not hasattr(engine, 'synthesize'):
            raise SystemExit(f'{segment["speaker"]} 用的是预设音色（{voice}），这个引擎只能读参考音克隆的句子。')
        pcm, rate, _ = engine.synthesize(text, voice, project['language'], seed, size=size)
        how = '预设音色 ' + voice
    pcm, _ = process_audio(pcm, rate)
    return pcm, rate, how, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--a', default='qwen:0.6B'); ap.add_argument('--b', default='qwen:1.7B')
    ap.add_argument('lines', nargs='+', help='工程 id:句号')
    args = ap.parse_args()
    store = Store(ROOT / 'user-data/projects'); library = VoiceLibrary(ROOT / 'user-data/voices')
    qwen = MlxEngine(ROOT / 'user-data/models/qwen-customvoice')
    chatter = ChatterboxEngine(ROOT / 'user-data/models/chatterbox-multilingual-v3', ROOT / 'user-data/models/s3tokenizer-v2')
    index = IndexTtsEngine(ROOT / 'user-data/models/indextts-1.5')
    sides = [engines_for(args.a, qwen, chatter, index), engines_for(args.b, qwen, chatter, index)]
    for engine, _, name in sides:
        if not engine.ready:
            raise SystemExit(name + ' 未安装。')
    stamp = time.strftime('%m%d-%H%M')
    out = Path.home() / 'Desktop' / f'VoxStage-对听-{stamp}'; out.mkdir(parents=True, exist_ok=True)
    keys = ROOT / 'user-data/listening'; keys.mkdir(parents=True, exist_ok=True)
    key, notes = {'a': args.a, 'b': args.b, 'pairs': {}}, []
    rng = random.SystemRandom()
    for n, item in enumerate(args.lines, 1):
        pid, _, number = item.partition(':')
        project = store.read(pid); segment = project['segments'][int(number) - 1]
        takes = []
        for engine, size, name in sides:
            started = time.time()
            pcm, rate, how, text = read(engine, size, project, segment, library)
            takes.append((name, pcm, rate, round(time.time() - started, 1)))
        order = [0, 1]; rng.shuffle(order)
        for label, k in zip('甲乙', order):
            sf.write(out / f'对{n}-{label}.wav', takes[k][1], takes[k][2], subtype='PCM_16')
        key['pairs'][f'对{n}'] = {'甲': takes[order[0]][0], '乙': takes[order[1]][0], 'project': project['name'], 'segment': int(number),
                               'seconds': {t[0]: t[3] for t in takes}}
        issue = segment.get('listening_issue') or {}
        notes.append(f"对{n}：《{project['name']}》第 {number} 句 · {segment['speaker']}（{how}）\n    {text.strip()[:80]}"
                     + (f"\n    你标的问题：{issue.get('kind')} — {issue.get('note', '')}" if issue else ''))
        print(f'对{n}', {t[0]: t[3] for t in takes}, flush=True)
    (out / '说明.txt').write_text('每对两个文件，甲/乙顺序随机；同一句、同一声线、同一种子，只换引擎/模型。听完只说每对选甲还是乙（或听不出差别）。\n\n'
                                  + '\n\n'.join(notes) + '\n', encoding='utf-8')
    (keys / f'{stamp}.json').write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding='utf-8')
    print('wrote', out, '\nkey', keys / f'{stamp}.json')


if __name__ == '__main__':
    main()

# 最后更新：2026-09-17 · Claude Hera
