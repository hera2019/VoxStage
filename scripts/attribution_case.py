"""Turn a reviewed project into a speaker-attribution test case, and score the
whole draft pipeline (model + rules + habits, exactly as the app runs it)
against such cases.

A case is the source text plus the labels a person confirmed — made by
reviewing a project carefully in the app, then:

    .venv/bin/python scripts/attribution_case.py export "书名 · 第一章" --to user-data/attribution-cases/
    .venv/bin/python scripts/attribution_case.py score user-data/attribution-cases/*.json

`score` needs the service running on 127.0.0.1:8765; it drafts each case
through /api/attribution/draft (with the case's book, so aliases, cast and
confirmed chapters count, as they would for a person) and reports agreement
with the confirmed labels, split by what the page would have shown: named,
yellow, orange. Cases from the author's own texts stay under user-data/
(ignored by git); public-domain cases may live in evals/.
"""
import argparse
import glob
import json
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evals.speaker_attribution.source_units import source_units  # noqa: E402

API = 'http://127.0.0.1:8765/api'


def call(path, method='GET', data=None):
    req = urllib.request.Request(API + path, method=method, headers={'X-VoxStage': '1', 'Content-Type': 'application/json'},
                                 data=None if data is None else json.dumps(data, ensure_ascii=False).encode())
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())


def export(name, to):
    for path in glob.glob(str(ROOT / 'user-data/projects/*/project.json')):
        p = json.loads(Path(path).read_text(encoding='utf-8'))
        if p['name'] != name:
            continue
        record = p.get('attribution') or {}
        if not record.get('confirmed_labels'):
            raise SystemExit('这个工程没有人工确认的角色标签（不是从草稿建的？）。')
        case = {'name': p['name'], 'language': p['language'], 'text': p['source_script'], 'book_id': (p.get('book') or {}).get('id'),
                'labels': [{k: l[k] for k in ('id', 'kind', 'speaker')} for l in record['confirmed_labels']],
                'exported_at': time.strftime('%Y-%m-%d %H:%M'), 'review': record.get('review')}
        out = Path(to); out.mkdir(parents=True, exist_ok=True)
        target = out / (''.join(c if c.isalnum() or c in '·-_ ' else '_' for c in p['name']).strip() + '.json')
        target.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding='utf-8')
        print('wrote', target, '-', len(case['labels']), 'labels,', sum(1 for l in case['labels'] if l['kind'] == 'dialogue'), 'dialogue')
        return
    raise SystemExit('没有这个工程：' + name)


def score(paths):
    grand = Counter(); grand_total = Counter()
    for path in paths:
        case = json.loads(Path(path).read_text(encoding='utf-8'))
        gold = {l['id']: l for l in case['labels']}
        started = time.time()
        d = call('/attribution/draft', 'POST', {'script': case['text'], 'language': case['language'], 'book_id': case.get('book_id')})
        seconds = time.time() - started
        right = Counter(); total = Counter(); kinds_right = 0; kinds = 0
        for u in d['units']:
            if u['blank'] or u['id'] not in gold:
                continue
            g = gold[u['id']]; kinds += 1; kinds_right += (u['kind'] == g['kind'])
            if g['kind'] != 'dialogue' or u['kind'] != 'dialogue':
                continue
            tier = 'orange' if u['speaker'] in ('UNKNOWN', '') else ('yellow' if u.get('tier') == 'suggested' else 'named')
            total[tier] += 1; right[tier] += (u['speaker'] == g['speaker'])
        print(f"{case['name']}: kind {kinds_right}/{kinds}; speaker " + ', '.join(f'{t} {right[t]}/{total[t]}' for t in ('named', 'yellow', 'orange') if total[t])
              + f"; all {sum(right.values())}/{sum(total.values())}; {seconds:.0f}s" + (f"; reviewer took {case['review']['seconds']}s, changed {case['review']['changed']}" if case.get('review') else ''))
        grand.update(right); grand_total.update(total)
    if len(paths) > 1:
        print('ALL: ' + ', '.join(f'{t} {grand[t]}/{grand_total[t]}' for t in ('named', 'yellow', 'orange') if grand_total[t]) + f"; all {sum(grand.values())}/{sum(grand_total.values())}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('export'); e.add_argument('project'); e.add_argument('--to', default=str(ROOT / 'user-data/attribution-cases'))
    s = sub.add_parser('score'); s.add_argument('cases', nargs='+')
    args = ap.parse_args()
    export(args.project, args.to) if args.cmd == 'export' else score(args.cases)

# 最后更新：2026-09-15 · Claude Hera（本人 2026-09-15：测试集我们自己做）
