"""Leftovers in a project folder — takes of a voice since changed, audition
previews, old export batches, check work-dirs — counted and removed without
touching what the lines use (本人 2026-09-22). Claude Hera."""
import json
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine
from tests.test_workflow import create, generate, HEADERS


def test_cleanup_counts_and_removes_only_what_nothing_uses(tmp_path):
    with TestClient(create_app(tmp_path, FixtureEngine()), base_url='http://127.0.0.1:8765', headers=HEADERS) as c:
        p = generate(c, create(c, 'zh'))
        used = {s['audio']['fingerprint'] for s in p['segments'] if s.get('audio')}
        folder = tmp_path / p['id']
        # a changed voice leaves the old takes behind; previews, an old export batch, a check dir, a stray file
        (folder / 'audio' / 'deadbeef.wav').write_bytes(b'x' * 1000); (folder / 'audio' / 'deadbeef.json').write_text('{}')
        (folder / 'previews').mkdir(); (folder / 'previews' / 'a.wav').write_bytes(b'x' * 500)
        (folder / 'exports' / '3').mkdir(parents=True); (folder / 'exports' / '3' / 'full.wav').write_bytes(b'x' * 700)
        (folder / 'exports' / '9').mkdir(parents=True); (folder / 'exports' / '9' / 'full.wav').write_bytes(b'x' * 800)
        (folder / 'checks' / 'abc').mkdir(parents=True); (folder / 'checks' / 'abc' / 'input.wav').write_bytes(b'x' * 300)
        (folder / 'project.json.before-repair').write_text('{}')
        plan = c.get('/api/projects/' + p['id'] + '/cleanup').json()
        assert plan['audio']['files'] == 2 and plan['previews']['files'] == 1 and plan['exports'] == {'files': 1, 'bytes': 700, 'keeps': 9}
        assert plan['checks']['files'] == 1 and plan['stray']['files'] == 1 and plan['total_bytes'] == 1000 + 2 + 500 + 700 + 300 + 2
        r = c.post('/api/projects/' + p['id'] + '/cleanup', json={'revision': p['revision']}).json()
        assert r['freed_bytes'] == plan['total_bytes'] and r['undo_cleared'] is False
        left = {f.name.split('.')[0] for f in (folder / 'audio').iterdir()}
        assert left == used and not (folder / 'previews').exists() and (folder / 'exports' / '9' / 'full.wav').exists() and not (folder / 'exports' / '3').exists()
        assert not (folder / 'checks').exists() and not (folder / 'project.json.before-repair').exists()
        assert c.get('/api/projects/' + p['id'] + '/cleanup').json()['total_bytes'] == 0
        assert all(s['status'] == 'ready' for s in c.get('/api/projects/' + p['id']).json()['segments'])   # the lines' own audio untouched


def test_takes_only_undo_points_at_go_with_include_undo_and_the_stack_is_cleared(tmp_path):
    with TestClient(create_app(tmp_path, FixtureEngine()), base_url='http://127.0.0.1:8765', headers=HEADERS) as c:
        p = generate(c, create(c, 'zh'))
        first = p['segments'][0]
        old = first['audio']['fingerprint']
        p = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'segment_id': first['id'], 'text': first['text'] + '呀'}).json()
        p = generate(c, p)
        plan = c.get('/api/projects/' + p['id'] + '/cleanup').json()
        assert plan['undo_audio']['files'] == 2 and plan['audio']['files'] == 0        # the old take: undo still points at it
        r = c.post('/api/projects/' + p['id'] + '/cleanup', json={'revision': p['revision']}).json()
        assert r['freed_bytes'] == 0 and (tmp_path / p['id'] / 'audio' / (old + '.wav')).exists()
        r = c.post('/api/projects/' + p['id'] + '/cleanup', json={'revision': p['revision'], 'include_undo': True}).json()
        assert r['undo_cleared'] is True and not (tmp_path / p['id'] / 'audio' / (old + '.wav')).exists()
        q = c.get('/api/projects/' + p['id']).json()
        assert q['revision'] == r['revision'] and not q['can_undo'] and all(s['status'] == 'ready' for s in q['segments'])
