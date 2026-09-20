"""Structure plans for a master book — split, merge, reorder, attach, detach,
dissolve — as pure descriptions the transaction layer commits. All text is
written for the test. Opus 二 · Claude Hera, 2026-09-20."""
import pytest
from runtime import book_structure as S
from runtime.book_master import plan_book
from runtime.project_settings import effective
from evals.speaker_attribution.source_units import source_units


def processed(project, speakers=('阿宁', '陈小雪')):
    """Give a planned chapter segments (one per line) with audio, like a confirmed, generated chapter."""
    pos, segs = 0, []
    for n, line in enumerate(project['source_script'].split('\n')):
        if line.strip():
            seg = {'id': f'{project["id"][:8]}{n:02d}' + '0' * 22, 'text': line, 'source_start': pos, 'source_end': pos + len(line),
                   'speaker': speakers[n % len(speakers)] if line.startswith('“') else '旁白', 'kind': 'dialogue' if line.startswith('“') else 'narration',
                   'audio': {'fingerprint': f'fp{n:02d}' + 'a' * 60, 'samples': 2400, 'sample_rate': 24000}}
            segs.append(seg)
        pos += len(line) + 1
    project['segments'] = segs; project['processing_state'] = 'processed'
    labels = []
    for u in source_units(project['source_script'], project.get('cut')):
        t = u['text'].strip()
        labels.append({'id': u['id'], 'kind': 'dialogue' if t.startswith('“') else 'narration', 'speaker': ('阿宁' if t.startswith('“') else 'NARRATOR'), 'confirmed': True})
    project['attribution'] = {'confirmed_labels': labels, 'human_confirmed': True}
    return project


@pytest.fixture
def book():
    text = ('第一章 猫\n陈小雪看着窗外。\n“猫又跑出去啦～”阿宁说。\n“赏你一块糖～”她笑道。\n\n'
            '第二章 账\n王伯翻开账本。\n“少了三块～”阿宁说。\n“数错了吧？”陈小雪说。\n\n第三章 雪\n雪停了。\n“走吧。”阿宁说。\n')
    chapters = []
    for piece in text.split('\n\n'):
        title, body = piece.split('\n', 1)
        chapters.append({'title': title, 'text': title + '\n' + body, 'silent': [0]})
    plan = plan_book('小店', 'zh', chapters)
    b, ps = plan['book'], plan['projects']
    ps[0] = processed(ps[0]); ps[1] = processed(ps[1])
    ps[0]['pause_ms'] = 300                     # a local override on chapter one only
    return b, ps


def test_split_makes_two_new_chapters_with_the_audio_marks_and_labels_rebased(book):
    b, ps = book
    one = ps[0]
    at = one['segments'][2]['source_start']      # before “猫又跑出去啦～”
    plan = S.plan_split(b, one, at)
    left, right = plan['new_projects']
    assert plan['members_after'] == [left['id'], right['id'], ps[1]['id'], ps[2]['id']] and plan['retired'] == [one['id']]
    assert [c['index'] for c in plan['chapters_after']] == [1, 2, 3, 4] and right['book']['index'] == 2 and right['book']['chapters'] == 4
    assert left['source_script'] + right['source_script'] == one['source_script']
    assert [s['text'] for s in right['segments']] == ['“猫又跑出去啦～”阿宁说。', '“赏你一块糖～”她笑道。']
    assert right['segments'][0]['source_start'] == 0 and right['segments'][0]['lock_before'] is True
    assert right['segments'][1]['audio']['fingerprint'] == one['segments'][3]['audio']['fingerprint']   # kept, not regenerated
    assert left['silent'] == [0] and right['silent'] == []                                            # the heading stays silent, rebased by line
    assert left['pause_ms'] == 300 and right['pause_ms'] == 300 and left['history'] == [] and left['revision'] == 0
    assert {a['to'] for a in plan['assets'] if a['required']} >= {f"{right['id']}/audio/{one['segments'][2]['audio']['fingerprint']}.wav"}
    # labels follow the units: every unit of the right half keeps its confirmed label
    rl = {l['id']: l for l in right['attribution']['confirmed_labels']}
    for u in source_units(right['source_script']):
        if u['text'].strip().startswith('“'):
            assert rl[u['id']]['speaker'] == '阿宁' and rl[u['id']].get('confirmed', True)
    assert right['attribution']['human_confirmed'] is True
    with pytest.raises(ValueError):
        S.plan_split(b, one, at + 1)             # inside a sentence: split the sentence first
    with pytest.raises(ValueError):
        S.plan_split(b, ps[2], 3)                # unprocessed: only at a line start


def test_merge_lists_conflicts_first_and_joins_with_them_resolved(book):
    b, ps = book
    one, two = ps[0], ps[1]
    two['voices'] = {'阿宁': 'Dylan'}; one['voices'] = {'阿宁': 'Ryan', '陈小雪': 'Vivian'}
    first = S.plan_merge(b, one, two)
    keys = {(c['key'], c.get('role')) for c in first['conflicts']}
    assert ('pause_ms', None) in keys and ('voices', '阿宁') in keys and ('voices', '陈小雪') in keys and first['new_projects'] == []
    plan = S.plan_merge(b, one, two, resolutions={'pause_ms': 'inherit', 'voices:阿宁': 'right', 'voices:陈小雪': 'left'})
    (m,) = plan['new_projects']
    assert 'pause_ms' not in m and m['voices'] == {'阿宁': 'Dylan', '陈小雪': 'Vivian'}
    sep = '' if one['source_script'].endswith('\n') else '\n'                                 # a line break joins them unless the left already ends with one
    assert m['source_script'] == one['source_script'] + sep + two['source_script']
    shift = len(one['source_script']) + len(sep)
    assert [s['text'] for s in m['segments']] == [s['text'] for s in one['segments'] + two['segments']]
    assert m['segments'][len(one['segments'])]['source_start'] == two['segments'][0]['source_start'] + shift
    assert m['segments'][len(one['segments'])]['lock_before'] is True
    assert m['silent'] == [0, m['source_script'].count('\n', 0, shift)]                     # both headings, the second rebased
    assert plan['members_after'] == [m['id'], ps[2]['id']] and sorted(plan['retired']) == sorted([one['id'], two['id']])
    labels = {l['id']: l for l in m['attribution']['confirmed_labels']}
    units = source_units(m['source_script'])
    assert len(labels) == len(units) and m['attribution']['human_confirmed'] is True
    assert labels[units[-2]['id']]['speaker'] == '阿宁'                                       # the last line of chapter two, re-keyed
    with pytest.raises(ValueError):
        S.plan_merge(b, one, ps[2])                                                          # not adjacent
    two['cut'] = 'lines'
    with pytest.raises(ValueError):
        S.plan_merge(b, one, two, resolutions={'pause_ms': 'left', 'voices:阿宁': 'left', 'voices:陈小雪': 'left'})   # cut differently


def test_reorder_attach_detach_and_dissolve(book):
    b, ps = book
    order = [ps[2]['id'], ps[0]['id'], ps[1]['id']]
    plan = S.plan_reorder(b, order)
    assert plan['members_after'] == order and plan['reindex'][ps[2]['id']] == 1 and plan['new_projects'] == []
    with pytest.raises(ValueError):
        S.plan_reorder(b, order[:2])
    # A standalone project joins in the middle; its settings become its own; a shared name is a question.
    loose = processed({'schema_version': 1, 'id': 'f' * 32, 'name': '外传', 'language': 'zh', 'revision': 3, 'source_script': '“来了。”阿宁说。\n“好。”王伯说。\n',
                       'segments': [], 'history': [], 'future': [], 'job': {'status': 'idle'}, 'synthetic_audio': True, 'pause_ms': 400, 'voices': {'阿宁': 'Ryan', '王伯': 'Uncle_Fu'}}, speakers=('阿宁', '王伯'))
    b['cast'] = [{'id': 'c1', 'name': '阿宁'}]
    plan = S.plan_attach(b, loose, 1)
    (j,) = plan['new_projects']
    assert plan['members_after'] == [ps[0]['id'], loose['id'], ps[1]['id'], ps[2]['id']] and j['book']['index'] == 2
    assert j['pause_ms'] == 400 and j['settings_schema'] == 1 and j['preset_model'] == '0.6B'    # every effective value now its own
    assert [q['kind'] for q in plan['questions']] == ['same_name', 'new_name'] and plan['questions'][0]['name'] == '阿宁'
    inherit = S.plan_attach(b, loose, 1, inherit=True)['new_projects'][0]
    assert 'pause_ms' not in inherit and 'voices' not in inherit
    # Detaching chapter three freezes what it was inheriting.
    b['settings']['pause_ms'] = 180
    plan = S.plan_detach(b, ps[2])
    (free,) = plan['new_projects']
    assert 'book' not in free and free['pause_ms'] == 180 and free['settings_schema'] == 1 and plan['members_after'] == [ps[0]['id'], ps[1]['id']]
    assert effective(free)['pause_ms'] == 180
    plan = S.plan_dissolve(b, ps)
    assert plan['members_after'] == [] and len(plan['new_projects']) == 3 and all('book' not in p for p in plan['new_projects'])
