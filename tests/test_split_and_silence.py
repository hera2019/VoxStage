"""Cut a line in two in place, and keep a line in the script but out of the recording."""
import io

import pytest
import soundfile as sf

from runtime.core import split_segment, reads_aloud
from tests.test_workflow import client, create, generate  # noqa: F401  (fixtures)


def project_with_ranges():
    src = '周远点点头。林小雪凑过去看那本子。'
    return {'source_script': src, 'voices': {'旁白': 'Vivian'}, 'segments': [
        {'id': 'a', 'speaker': '旁白', 'kind': 'narration', 'text': src, 'spoken_as': '慢慢地念',
         'source_start': 0, 'source_end': len(src), 'audio': {'fingerprint': 'x', 'samples': 1, 'sample_rate': 24000},
         'error': None, 'pause_after': 500, 'take': 2, 'content_check': {'status': 'match'}}]}


def test_split_in_place_keeps_the_source_and_moves_the_pause_to_the_right():
    p = project_with_ranges()
    left, right = split_segment(p, 'a', 6)
    assert [s['text'] for s in p['segments']] == ['周远点点头。', '林小雪凑过去看那本子。']
    assert ''.join(s['text'] for s in p['segments']) == p['source_script']
    assert (left['source_start'], left['source_end'], right['source_start'], right['source_end']) == (0, 6, 6, 17)
    assert left['id'] != right['id'] != 'a'
    # Right half: locked against re-merging, keeps the pause that followed the original.
    assert right['lock_before'] is True and right['pause_after'] == 500
    # Left half: no pause of its own, so the split inserts no gap that was not there.
    assert left['lock_before'] is False and left['pause_after'] == 0
    # Audio, retake counter and checks belong to the old text and are dropped;
    # the replacement reading cannot be shared out by position, so it is cleared.
    for s in (left, right):
        assert s['audio'] is None and s['spoken_as'] == '' and 'take' not in s and 'content_check' not in s
        assert s['speaker'] == '旁白' and s['kind'] == 'narration'


@pytest.mark.parametrize('at,message', [(0, '内部'), (17, '内部'), (30, '内部')])
def test_split_refuses_the_ends(at, message):
    with pytest.raises(ValueError, match=message):
        split_segment(project_with_ranges(), 'a', at)


def test_split_refuses_a_half_with_no_text_and_a_cut_inside_a_character():
    p = project_with_ranges()
    p['segments'][0]['text'] = p['source_script'] = '　　世界'
    p['segments'][0]['source_end'] = 4
    with pytest.raises(ValueError, match='两半'):
        split_segment(p, 'a', 1)                 # left half would be only whitespace
    q = project_with_ranges()
    q['segments'][0]['text'] = q['source_script'] = 'éclair'      # e + combining acute
    q['segments'][0]['source_end'] = 7
    with pytest.raises(ValueError, match='中间'):
        split_segment(q, 'a', 1)


def test_split_needs_source_positions():
    p = project_with_ranges()
    del p['segments'][0]['source_start']
    with pytest.raises(ValueError, match='原稿位置'):
        split_segment(p, 'a', 6)


def test_older_projects_read_every_line():
    assert reads_aloud({'text': 'x'}) is True
    assert reads_aloud({'text': 'x', 'read_aloud': False}) is False


def test_a_silenced_line_leaves_the_recording_but_not_the_script(client):
    p = generate(client, create(client, 'zh'))
    base = '/api/projects/' + p['id']
    before = client.post(base + '/export/create', json={'revision': p['revision']}).json()
    before_wav = client.get(before['full.wav']).content
    victim = p['segments'][1]
    p = client.patch(base, json={'revision': p['revision'], 'segment_id': victim['id'], 'read_aloud': False}).json()
    assert [s['status'] for s in p['segments']][1] == 'silent'
    assert p['segments'][1]['text'] == victim['text'] and p['source_script'] == p['source_script']
    after = client.post(base + '/export/create', json={'revision': p['revision']}).json()
    timeline = client.get(after['timeline.json']).json()
    assert [e['id'] for e in timeline['segments']] == [s['id'] for s in p['segments'] if s['id'] != victim['id']]
    assert victim['text'] not in client.get(after['subtitles.srt']).text
    pcm, _ = sf.read(io.BytesIO(client.get(after['full.wav']).content), dtype='int16')
    old, _ = sf.read(io.BytesIO(before_wav), dtype='int16')
    assert len(pcm) < len(old)
    # Generating skips it, and asking for it alone is refused with a reason.
    r = client.post(base + '/render/start', json={'revision': p['revision'], 'segment_id': victim['id']})
    assert r.status_code == 400 and '不朗读' in r.json()['detail']
    # Switching it back on restores the line with its audio still attached.
    p = client.patch(base, json={'revision': p['revision'], 'segment_id': victim['id'], 'read_aloud': True}).json()
    assert p['segments'][1]['status'] == 'ready'
    assert client.get(client.post(base + '/export/create', json={'revision': p['revision']}).json()['full.wav']).content == before_wav


def test_every_line_silenced_cannot_be_exported(client):
    p = generate(client, create(client, 'zh'))
    base = '/api/projects/' + p['id']
    for s in list(p['segments']):
        p = client.patch(base, json={'revision': p['revision'], 'segment_id': s['id'], 'read_aloud': False}).json()
    r = client.post(base + '/export/create', json={'revision': p['revision']})
    assert r.status_code == 400 and '不朗读' in r.json()['detail']


def test_split_through_the_api_is_undoable(ranged):
    """A project built from prose keeps source positions, so it can be split in place."""
    client, p = ranged
    base = '/api/projects/' + p['id']
    target = next(s for s in p['segments'] if len(s['text']) > 3)
    n = len(p['segments'])
    r = client.post(base + '/segments/' + target['id'] + '/split', json={'revision': p['revision'], 'at': 2})
    assert r.status_code == 200, r.text
    p = r.json()
    assert len(p['segments']) == n + 1
    assert ''.join(s['text'] for s in p['segments']) == p['source_script']
    assert all(s['text'] == p['source_script'][s['source_start']:s['source_end']] for s in p['segments'])
    p = client.post(base + '/undo', json={'revision': p['revision']}).json()
    assert len(p['segments']) == n and any(s['id'] == target['id'] for s in p['segments'])


def test_a_project_pasted_as_labelled_lines_cannot_be_split_in_place(client):
    """It has no source positions, and the spec says not to guess them."""
    p = create(client, 'zh')
    target = p['segments'][0]
    r = client.post('/api/projects/' + p['id'] + '/segments/' + target['id'] + '/split',
                    json={'revision': p['revision'], 'at': 1})
    assert r.status_code == 400 and '原稿位置' in r.json()['detail']


@pytest.fixture
def ranged(tmp_path):
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from runtime.engines import FixtureEngine
    from tests.test_attribution_import import Roles, draft, confirm, HEADERS
    with TestClient(create_app(tmp_path / 'projects', FixtureEngine(), role_engine=Roles()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = draft(c, '小雪看着窗外。“雨停了吗？”她问。周远点点头。')
        labels = [{**{k: u[k] for k in ('id', 'kind', 'speaker')}, 'speaker': '小雪' if u['speaker'] == 'UNKNOWN' else u['speaker']}
                  for u in d['units']]
        p = c.post('/api/attribution/confirm', json={'draft_id': d['draft_id'], 'name': '拆分', 'labels': labels})
        assert p.status_code == 200, p.text
        yield c, p.json()
