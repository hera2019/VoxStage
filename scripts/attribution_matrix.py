"""Every installed role model on the fixed set of reviewed texts, through the
whole draft pipeline (model + rules + the page's own turn-taking), scored
against the reviewer's labels. Runs the app in-process on a scratch copy of
the books and project records: the running service and the author's data
are not touched, and no model switching (fallback) happens inside a run.

    .venv/bin/python scripts/attribution_matrix.py                 # all installed models
    .venv/bin/python scripts/attribution_matrix.py qwen3-14b-q4km  # one or more model ids

Texts: the cases exported to user-data/attribution-cases/ (see
attribution_case.py) and every non-archived chapter project of a book with
confirmed labels. Names from the author's own texts are never printed —
only counts. Scoring (2026-09-16, ai-lab 实测 17): every line the reviewer
called dialogue counts, and a line the page silenced or a narration it made
speech is an error too; a name the reviewer never used (a stand-in, a
description like 短衣帮) counts as right once renamed to the reviewer's
name for most of its lines; "to fix" is everything else the reviewer would
have to touch. Results also go to results/speaker-attribution/matrix-<date>.json.
"""
import glob
import json
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient                      # noqa: E402
from runtime.app import create_app                             # noqa: E402
from runtime.engines import FixtureEngine                      # noqa: E402
from runtime.attribution import RoleDraftEngine, ROLE_MODELS   # noqa: E402

HEADERS = {'X-VoxStage': '1'}
ORDER = list(ROLE_MODELS)


def scratch_copy():
    """Project records and books only — no audio, no drafts of the author's."""
    root = Path(tempfile.mkdtemp(prefix='voxstage-matrix-'))
    (root / 'projects').mkdir()
    for f in glob.glob(str(ROOT / 'user-data/projects/*/project.json')):
        pid = Path(f).parent.name
        (root / 'projects' / pid).mkdir()
        shutil.copy(f, root / 'projects' / pid / 'project.json')
    if (ROOT / 'user-data/books').is_dir():
        shutil.copytree(ROOT / 'user-data/books', root / 'books')
    (root / 'projects-role-drafts').mkdir()
    return root


def texts():
    """[(label, text, language, book_id, gold)] — chapters with confirmed labels, then the case files."""
    out = []
    books = [json.load(open(f, encoding='utf-8')) for f in glob.glob(str(ROOT / 'user-data/books/*.json'))]
    for f in glob.glob(str(ROOT / 'user-data/projects/*/project.json')):
        p = json.load(open(f, encoding='utf-8'))
        book = next((b for b in books if b['id'] == (p.get('book') or {}).get('id')), None)
        if book and not p.get('archived') and (p.get('attribution') or {}).get('confirmed_labels'):
            # The project's own text and its segments as the reviewer keeps them in
            # the editor (splits, merges, text edits move the unit ids the confirmed
            # labels were made with): each unit takes the speaker of the segment
            # holding its first character; the narrator's, or a silent one, is narration.
            out.append((f"{book['title'][:6]} 第{p['book']['index']}章", p['source_script'], book['language'], book['id'], gold_from_segments(p)))
    import hashlib
    for path in sorted(glob.glob(str(ROOT / 'user-data/attribution-cases/*.json'))):
        case = json.load(open(path, encoding='utf-8'))
        stem = Path(path).stem
        # A case from the author's own text is named by a hash, not its title, so the
        # results file can be shown around; the public-domain samples keep their names.
        label = stem[:10] if any(k in stem for k in ('孔乙己', '阿Q', '傲慢', '风波', 'pride', 'fengbo')) else '私稿·' + hashlib.sha256(stem.encode()).hexdigest()[:4]
        out.append((label, case['text'], case.get('language', 'zh'), case.get('book_id'), {l['id']: l for l in case['labels']}))
    seen, unique = set(), []                      # one entry per text: a case exported from a project repeats it
    for t in out:
        if t[1] not in seen:
            seen.add(t[1]); unique.append(t)
    return unique


def gold_from_segments(project):
    from evals.speaker_attribution.source_units import source_units
    segments = sorted(project['segments'], key=lambda x: x['source_start'])
    quoted = any(c in project['source_script'] for c in '“"「『')
    gold = {}
    for u in source_units(project['source_script'], project.get('cut')):
        if not u['text'].strip():
            continue
        at = u['start'] + (len(u['text']) - len(u['text'].lstrip()))
        seg = next((x for x in segments if x['source_start'] <= at < x['source_end']), None)
        if seg is None:
            continue
        speaker = seg['speaker'].strip()
        # In a text that marks speech with quotation marks the pipeline calls
        # every unquoted unit prose; a beat the reviewer left inside a character's
        # segment (，阿Q想，) is not a line the draft could have given anyone.
        unquoted_prose = quoted and u['text'].strip()[0] not in '“"「『'
        if speaker in ('旁白', 'Narrator', 'NARRATOR') or not seg.get('read_aloud', True) or unquoted_prose:
            gold[u['id']] = {'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR'}
        else:
            gold[u['id']] = {'id': u['id'], 'kind': 'dialogue', 'speaker': speaker}
    return gold


def unresolved(s):
    return not s.strip() or s.strip().upper() == 'UNKNOWN'


def rows_for(units, gold):
    """(tier, page speaker, gold speaker) for every unit either side calls dialogue, with the page's turn-taking."""
    recent = []; block = None; rows = []
    for u in units:
        if u['blank']:
            continue
        g = gold.get(u['id'])
        if not g:
            continue
        page_dialogue = u['kind'] == 'dialogue'; gold_dialogue = g['kind'] == 'dialogue'
        if u.get('block') != block:
            recent = []; block = u.get('block')
        if page_dialogue and not unresolved(u['speaker']):
            s = u['speaker'].strip()
            if u.get('tier') != 'suggested' or u.get('stand_in'):
                recent = [s] + [n for n in recent if n != s]; recent = recent[:2]
        if not page_dialogue and not gold_dialogue:
            continue
        if not gold_dialogue:
            rows.append(('kind', u['speaker'].strip(), 'NARRATION')); continue
        if not page_dialogue:
            rows.append(('kind', 'NARRATION', g['speaker'])); continue
        if not unresolved(u['speaker']):
            rows.append(('named' if not u.get('tier') else 'yellow', u['speaker'].strip(), g['speaker']))
        else:
            sug = recent[1] if len(recent) == 2 else ''
            if sug:
                recent = [sug, recent[0]]
            rows.append(('turn' if sug else 'orange', sug, g['speaker']))
    return rows


def score(rows):
    gold_cast = {g for t, s, g in rows if t != 'kind'}
    renames = {}
    for t, s, g in rows:
        if t != 'kind' and s and s not in gold_cast:
            renames.setdefault(s, Counter())[g] += 1
    def ok(t, s, g):
        return t != 'kind' and (renames[s].most_common(1)[0][0] if s in renames else s) == g
    c = Counter((t, ok(t, s, g)) for t, s, g in rows)
    right = c[('named', True)] + c[('yellow', True)] + c[('turn', True)]
    return {'lines': len(rows), 'right': right, 'named_right': c[('named', True)], 'named_wrong': c[('named', False)],
            'yellow_right': c[('yellow', True)] + c[('turn', True)], 'yellow_wrong': c[('yellow', False)] + c[('turn', False)],
            'orange': c[('orange', False)] + c[('orange', True)], 'kind_errors': c[('kind', False)], 'renames': len(renames), 'to_fix': len(rows) - right}


def main(model_ids):
    root = scratch_copy()
    results = {}
    set_ = texts()
    for model_id in model_ids:
        engine = RoleDraftEngine(model_id=model_id)
        if not engine.ready:
            print(f'== {model_id}: not installed'); continue
        class Solo:                                   # this model alone: no fallback to another inside the endpoint
            ready = engine.ready; model_id = engine.model_id
            def annotate(self, text, log_path, known_names=(), examples=()):
                return engine.annotate(text, log_path, known_names=known_names, examples=examples)
        print(f'== {model_id}', flush=True)
        with TestClient(create_app(root / 'projects', FixtureEngine(), role_engine=Solo()), base_url='http://127.0.0.1', headers=HEADERS) as c:
            for label, text, language, book_id, gold in set_:
                started = time.time()
                r = c.post('/api/attribution/draft', json={'script': text, 'language': language, 'book_id': book_id})
                seconds = round(time.time() - started)
                if r.status_code != 200:
                    results.setdefault(model_id, {})[label] = {'error': r.json().get('detail', r.text)[:100], 'seconds': seconds}
                    print(f'   {label}: ERROR {seconds}s', flush=True); continue
                s = score(rows_for(r.json()['units'], gold)); s['seconds'] = seconds
                results.setdefault(model_id, {})[label] = s
                print(f"   {label}: right {s['right']}/{s['lines']} (named {s['named_right']}/{s['named_right'] + s['named_wrong']}, yellow {s['yellow_right']}/{s['yellow_right'] + s['yellow_wrong']}, "
                      f"orange {s['orange']}, kind errors {s['kind_errors']}, renames {s['renames']}) to fix {s['to_fix']} {seconds}s", flush=True)
    shutil.rmtree(root, ignore_errors=True)
    labels = [t[0] for t in set_]
    print('\n' + 'model'.ljust(38) + ''.join(l.ljust(22) for l in labels) + 'to fix')
    for m in model_ids:
        if m not in results:
            continue
        cells = []; total = 0
        for l in labels:
            s = results[m].get(l)
            if not s or 'error' in s:
                cells.append('ERROR'.ljust(22)); continue
            total += s['to_fix']
            cells.append(f"{s['right']}/{s['lines']} ({s['to_fix']})".ljust(22))
        print(m.ljust(38) + ''.join(cells) + str(total))
    out = ROOT / 'results/speaker-attribution'; out.mkdir(parents=True, exist_ok=True)
    path = out / f"matrix-{time.strftime('%Y-%m-%d-%H%M')}.json"
    path.write_text(json.dumps({'texts': labels, 'results': results, 'note': 'counts only; private texts are named by their case file stem'}, ensure_ascii=False, indent=1), encoding='utf-8')
    print('wrote', path)


if __name__ == '__main__':
    wanted = sys.argv[1:] or [m for m in ORDER if RoleDraftEngine.path_for(m)]
    unknown = [m for m in wanted if m not in ROLE_MODELS]
    if unknown:
        raise SystemExit('没有这个模型：' + ', '.join(unknown) + '\n可选：' + ', '.join(ORDER))
    main(wanted)

# 最后更新：2026-09-17 · Claude Hera
