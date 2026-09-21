import json
from pathlib import Path

from fastapi.testclient import TestClient

from runtime.app import create_app
from runtime.engines import FixtureEngine
from runtime import cast as cast_model


HEADERS = {'x-voxstage': '1'}


def make_book(client, title='书'):
    script = '第一章\n风吹过窗。\n第二章\n雨落下来。\n'
    response = client.post('/api/master-books', json={
        'title': title, 'language': 'zh', 'script': script,
    })
    assert response.status_code == 200, response.text
    return response.json()


def book_path(root, book_id):
    return root / 'books' / (book_id + '.json')


def read_book(root, book_id):
    return json.loads(book_path(root, book_id).read_text())


def write_book(root, book):
    book_path(root, book['id']).write_text(
        json.dumps(book, ensure_ascii=False, indent=2), encoding='utf-8')


def test_whole_book_unify_clears_local_override_and_old_undo_snapshot(tmp_path):
    app = create_app(tmp_path / 'projects', FixtureEngine())
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        book = make_book(client)
        pid = book['projects'][0]['id']
        raw = app.state.store.read(pid)
        raw['pause_ms'] = 900
        raw['history'] = [{
            'name': raw['name'], 'language': raw['language'],
            'segments': raw['segments'], 'source_script': raw['source_script'],
            'pause_ms': 700, '_settings_snapshot': ['pause_ms'],
        }]
        app.state.store.write(raw)

        current = read_book(tmp_path, book['id'])
        response = client.post(f"/api/master-books/{book['id']}/settings/unify", json={
            'revision': current['revision'], 'values': {'pause_ms': 500},
        })
        assert response.status_code == 200, response.text
        result = response.json()
        assert pid in result['updated_projects']
        after = app.state.store.read(pid)
        assert 'pause_ms' not in after
        assert 'pause_ms' not in after['history'][0]
        assert 'pause_ms' not in after['history'][0]['_settings_snapshot']

        state = client.get('/api/projects/' + pid + '/settings').json()
        assert state['effective']['pause_ms'] == 500
        undone = client.post('/api/projects/' + pid + '/undo', json={
            'revision': state['project_revision'],
        })
        assert undone.status_code == 200, undone.text
        assert client.get('/api/projects/' + pid + '/settings').json()['effective']['pause_ms'] == 500

        snap = tmp_path / 'books' / (book['id'] + '.snapshots') / result['snapshot_id']
        assert json.loads((snap / 'meta.json').read_text())['status'] == 'committed'
        assert (snap / 'book.json').is_file()
        assert (snap / 'projects' / (pid + '.json')).is_file()


def seed_cast(app, root, book_id, project_ids):
    book = read_book(root, book_id)
    entry = cast_model.new_entry('阿宁', 'person')
    book['cast'] = [entry]
    book['aliases'] = {}
    book['settings']['voices'] = {'阿宁': 'Vivian'}
    book['settings']['colors'] = {'阿宁': '#112233'}
    write_book(root, book)
    for pid in project_ids:
        raw = app.state.store.read(pid)
        raw['processing_state'] = 'processed'
        raw['segments'] = [{
            'id': 's-' + pid[:8], 'speaker': '阿宁', 'kind': 'dialogue',
            'text': '回来吧。', 'spoken_as': '', 'source_start': 0, 'source_end': 4,
            'audio': None, 'error': None,
        }]
        raw['cast_ids'] = {'阿宁': entry['id']}
        raw['attribution'] = {
            'confirmed_labels': [{'id': 'u1', 'kind': 'dialogue', 'speaker': '阿宁',
                                  'confirmed': True, 'source': 'person'}],
            'cast': [{'id': entry['id'], 'name': '阿宁', 'aliases': [],
                      'colours': [], 'sex': '', 'source': 'person'}],
        }
        raw['history'] = [{
            'name': raw['name'], 'language': raw['language'],
            'segments': [dict(raw['segments'][0])], 'source_script': raw['source_script'],
            'voices': {'阿宁': 'Vivian'}, '_settings_snapshot': ['voices'],
        }]
        app.state.store.write(raw)
    return entry


def test_book_cast_rename_updates_active_refs_history_and_book_settings(tmp_path):
    app = create_app(tmp_path / 'projects', FixtureEngine())
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        ids = [p['id'] for p in created['projects']]
        entry = seed_cast(app, tmp_path, created['id'], ids)
        book = read_book(tmp_path, created['id'])

        plan = client.post(f"/api/master-books/{created['id']}/cast/rename/plan", json={
            'revision': book['revision'], 'cast_id': entry['id'], 'name': '小宁',
        })
        assert plan.status_code == 200, plan.text
        assert not plan.json()['conflicts']
        assert len(plan.json()['affected_projects']) == 2

        done = client.post(f"/api/master-books/{created['id']}/cast/rename", json={
            'revision': book['revision'], 'cast_id': entry['id'], 'name': '小宁',
        })
        assert done.status_code == 200, done.text
        renamed = read_book(tmp_path, created['id'])
        assert renamed['cast'][0]['name'] == '小宁'
        assert renamed['aliases']['阿宁'] == '小宁'
        assert renamed['settings']['voices'] == {'小宁': 'Vivian'}
        assert renamed['settings']['colors'] == {'小宁': '#112233'}

        for pid in ids:
            raw = app.state.store.read(pid)
            assert raw['segments'][0]['speaker'] == '小宁'
            assert raw['cast_ids'] == {'小宁': entry['id']}
            assert raw['attribution']['confirmed_labels'][0]['speaker'] == '小宁'
            assert raw['history'][0]['segments'][0]['speaker'] == '小宁'
            assert raw['history'][0]['voices'] == {'小宁': 'Vivian'}
            assert raw['attribution']['cast'][0]['name'] == '小宁'
            assert raw['attribution']['cast'][0]['aliases'] == ['阿宁']


def test_book_cast_rename_refuses_existing_other_person_without_writes(tmp_path):
    app = create_app(tmp_path / 'projects', FixtureEngine())
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        ids = [p['id'] for p in created['projects']]
        entry = seed_cast(app, tmp_path, created['id'], ids)
        book = read_book(tmp_path, created['id'])
        book['cast'].append(cast_model.new_entry('小宁', 'person'))
        write_book(tmp_path, book)
        before = book_path(tmp_path, created['id']).read_bytes()

        plan = client.post(f"/api/master-books/{created['id']}/cast/rename/plan", json={
            'revision': book['revision'], 'cast_id': entry['id'], 'name': '小宁',
        })
        assert plan.status_code == 200
        assert plan.json()['conflicts']
        apply = client.post(f"/api/master-books/{created['id']}/cast/rename", json={
            'revision': book['revision'], 'cast_id': entry['id'], 'name': '小宁',
        })
        assert apply.status_code == 400
        assert book_path(tmp_path, created['id']).read_bytes() == before


def test_structure_preview_rejects_member_change_then_reorder_commits_atomically(tmp_path):
    app = create_app(tmp_path / 'projects', FixtureEngine())
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        book_id = created['id']
        original = read_book(tmp_path, book_id)
        order = list(reversed(original['members']))
        plan = client.post(f'/api/master-books/{book_id}/structure/plan', json={
            'op': 'reorder', 'members': order,
        })
        assert plan.status_code == 200, plan.text
        assert plan.json()['members_after'] == order

        first = original['members'][0]
        state = client.get('/api/projects/' + first + '/settings').json()
        changed = client.patch('/api/projects/' + first + '/settings', json={
            'revision': state['project_revision'], 'values': {'pause_ms': 333},
        })
        assert changed.status_code == 200
        stale = client.post(f'/api/master-books/{book_id}/structure/apply', json={
            'op': 'reorder', 'members': order, 'revision': original['revision'],
        })
        assert stale.status_code == 409
        assert read_book(tmp_path, book_id)['members'] == original['members']

        fresh_book = read_book(tmp_path, book_id)
        plan = client.post(f'/api/master-books/{book_id}/structure/plan', json={
            'op': 'reorder', 'members': order,
        })
        assert plan.status_code == 200
        done = client.post(f'/api/master-books/{book_id}/structure/apply', json={
            'op': 'reorder', 'members': order, 'revision': fresh_book['revision'],
        })
        assert done.status_code == 200, done.text
        after = read_book(tmp_path, book_id)
        assert after['members'] == order
        assert [app.state.store.read(pid)['book']['index'] for pid in order] == [1, 2]
        snap = tmp_path / 'books' / (book_id + '.snapshots') / done.json()['snapshot_id']
        assert json.loads((snap / 'meta.json').read_text())['status'] == 'committed'


def test_attach_same_name_requires_explicit_identity_mapping(tmp_path):
    app = create_app(tmp_path / 'projects', FixtureEngine())
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        member_ids = [p['id'] for p in created['projects']]
        entry = seed_cast(app, tmp_path, created['id'], member_ids)

        loose = client.post('/api/project-records', json={
            'name': '外章', 'language': 'zh', 'script': '外来的正文。',
        }).json()
        raw = app.state.store.read(loose['id'])
        raw['processing_state'] = 'processed'
        raw['segments'] = [{
            'id': 'loose-s', 'speaker': '阿宁', 'kind': 'dialogue',
            'text': '外来。', 'spoken_as': '', 'source_start': 0, 'source_end': 3,
            'audio': None, 'error': None,
        }]
        raw['voices'] = {'阿宁': 'Serena'}
        app.state.store.write(raw)

        preview = client.post(f"/api/master-books/{created['id']}/structure/plan", json={
            'op': 'attach', 'project_id': raw['id'], 'position': 1,
        })
        assert preview.status_code == 200, preview.text
        assert any(q['kind'] == 'same_name' for q in preview.json()['questions'])

        blocked = client.post(f"/api/master-books/{created['id']}/structure/apply", json={
            'op': 'attach', 'project_id': raw['id'], 'position': 1,
            'revision': read_book(tmp_path, created['id'])['revision'],
        })
        assert blocked.status_code == 400
        assert not app.state.store.read(raw['id']).get('book')

        # Identity answers are part of the plan key, so preview the exact answer
        # that will be applied.
        answer = {'阿宁': {'action': 'link', 'cast_id': entry['id']}}
        preview = client.post(f"/api/master-books/{created['id']}/structure/plan", json={
            'op': 'attach', 'project_id': raw['id'], 'position': 1,
            'identities': answer,
        })
        assert preview.status_code == 200
        applied = client.post(f"/api/master-books/{created['id']}/structure/apply", json={
            'op': 'attach', 'project_id': raw['id'], 'position': 1,
            'revision': read_book(tmp_path, created['id'])['revision'],
            'identities': answer,
        })
        assert applied.status_code == 200, applied.text
        joined = app.state.store.read(raw['id'])
        assert joined['book']['id'] == created['id']
        assert joined['cast_ids']['阿宁'] == entry['id']



def test_structure_split_copies_existing_segment_audio_without_regeneration(tmp_path):
    app = create_app(tmp_path / 'projects', FixtureEngine())
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        book_id = created['id']
        pid = created['projects'][0]['id']
        raw = app.state.store.read(pid)
        raw['source_script'] = '甲。乙。'
        raw['processing_state'] = 'processed'
        raw['segments'] = [
            {'id': 'left', 'speaker': '旁白', 'kind': 'narration', 'text': '甲。',
             'spoken_as': '', 'source_start': 0, 'source_end': 2,
             'audio': {'fingerprint': 'a' * 64, 'samples': 100, 'sample_rate': 24000},
             'error': None},
            {'id': 'right', 'speaker': '旁白', 'kind': 'narration', 'text': '乙。',
             'spoken_as': '', 'source_start': 2, 'source_end': 4,
             'audio': {'fingerprint': 'b' * 64, 'samples': 100, 'sample_rate': 24000},
             'error': None},
        ]
        app.state.store.write(raw)
        audio = app.state.store.directory(pid) / 'audio'
        audio.mkdir()
        (audio / (('a' * 64) + '.wav')).write_bytes(b'left-audio')
        (audio / (('b' * 64) + '.wav')).write_bytes(b'right-audio')

        preview = client.post(f'/api/master-books/{book_id}/structure/plan', json={
            'op': 'split', 'project_id': pid, 'at': 2,
        })
        assert preview.status_code == 200, preview.text
        assert len(preview.json()['new_projects']) == 2

        done = client.post(f'/api/master-books/{book_id}/structure/apply', json={
            'op': 'split', 'project_id': pid, 'at': 2,
            'revision': read_book(tmp_path, book_id)['revision'],
        })
        assert done.status_code == 200, done.text
        new_ids = done.json()['created']
        assert len(new_ids) == 2
        copied = {
            path.name: path.read_bytes()
            for new_id in new_ids
            for path in (app.state.store.directory(new_id) / 'audio').glob('*.wav')
        }
        assert copied[('a' * 64) + '.wav'] == b'left-audio'
        assert copied[('b' * 64) + '.wav'] == b'right-audio'
        retired = app.state.store.read(pid)
        assert retired['archived'] is True
        assert 'book' not in retired



def test_merge_conflict_preview_has_complete_dialog_shape(tmp_path):
    app = create_app(tmp_path / 'projects', FixtureEngine())
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        left, right = [p['id'] for p in created['projects']]
        for pid, value in ((left, 111), (right, 222)):
            state = client.get('/api/projects/' + pid + '/settings').json()
            changed = client.patch('/api/projects/' + pid + '/settings', json={
                'revision': state['project_revision'], 'values': {'pause_ms': value},
            })
            assert changed.status_code == 200, changed.text
        preview = client.post(f"/api/master-books/{created['id']}/structure/plan", json={
            'op': 'merge', 'left_id': left, 'right_id': right,
        })
        assert preview.status_code == 200, preview.text
        plan = preview.json()
        assert plan['unresolved']
        for key in ('members_after', 'chapters_after', 'new_projects', 'retired',
                    'assets', 'conflicts', 'questions'):
            assert key in plan
            assert isinstance(plan[key], list)



def test_one_characters_voice_can_be_unified_for_the_whole_book_leaving_other_overrides(tmp_path):
    """本人 2026-09-22: a voice changed in one chapter, applied to every chapter —
    but only that character's: a chapter's other entries (the character grown
    old with a voice of its own) stay its own."""
    app = create_app(tmp_path / 'projects', FixtureEngine())
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        book = make_book(client)
        one, two = (p['id'] for p in book['projects'])
        for pid, voices in ((one, {'阿宁': 'Dylan', '王伯': 'Uncle_Fu'}), (two, {'阿宁': 'Serena'})):
            raw = app.state.store.read(pid); raw['voices'] = voices; app.state.store.write(raw)
        current = read_book(tmp_path, book['id'])
        r = client.post(f"/api/master-books/{book['id']}/settings/unify-role", json={'revision': current['revision'], 'key': 'voices', 'name': '阿宁', 'value': 'Dylan'})
        assert r.status_code == 200, r.text
        result = r.json()
        assert result['settings']['voices'] == {'阿宁': 'Dylan'} and set(result['updated_projects']) == {one, two}
        assert app.state.store.read(one)['voices'] == {'王伯': 'Uncle_Fu'} and 'voices' not in app.state.store.read(two)
        assert client.get('/api/projects/' + two).json()['voices']['阿宁'] == 'Dylan'         # inherited now
        stale = client.post(f"/api/master-books/{book['id']}/settings/unify-role", json={'revision': current['revision'], 'key': 'voices', 'name': '阿宁', 'value': 'Vivian'})
        assert stale.status_code == 409
