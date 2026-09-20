import hashlib
import io
import json
from pathlib import Path
import zipfile

import soundfile as sf
from fastapi.testclient import TestClient

from runtime.app import create_app
from runtime.audio import process_audio
from runtime.core import fingerprint, uid
from runtime.engines import FixtureEngine


HEADERS = {'x-voxstage': '1'}


def make_app(tmp_path):
    engine = FixtureEngine()
    app = create_app(tmp_path / 'projects', engine)
    return app, engine


def make_book(client, title='整书'):
    script = '第一章 风起\n风吹过窗。\n第二章 雨来\n雨落在檐。\n'
    response = client.post('/api/master-books', json={
        'title': title, 'script': script, 'language': 'zh',
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data['projects']) == 2
    return data


def seed_ready(app, engine, project_id, text):
    store = app.state.store
    raw = store.read(project_id)
    raw['processing_state'] = 'processed'
    raw['voices'] = {'旁白': 'Vivian'}
    raw['segments'] = [{
        'id': uid(), 'speaker': '旁白', 'text': text, 'spoken_as': '',
        'source_start': 0, 'source_end': len(text),
        'audio': None, 'error': None,
    }]
    store.write(raw)
    current = store.read(project_id)
    view = store.resolver(current)
    segment = view['segments'][0]
    pcm, rate, _ = engine.synthesize(text, 'Vivian', 'zh')
    pcm, meta = process_audio(pcm, rate)
    fp = fingerprint(view, segment, engine, store.library)
    folder = store.directory(project_id) / 'audio'
    folder.mkdir(exist_ok=True)
    sf.write(folder / (fp + '.wav'), pcm, rate, subtype='PCM_16')
    current = store.read(project_id)
    current['segments'][0]['audio'] = {**meta, 'fingerprint': fp}
    store.write(current)
    return store.read(project_id)


def current_book(client, book_id):
    return client.get('/api/books/' + book_id).json()


def test_streaming_book_export_orders_chapters_and_adds_boundary_pause(tmp_path):
    app, engine = make_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        ids = [p['id'] for p in created['projects']]
        first = seed_ready(app, engine, ids[0], '甲。')
        second = seed_ready(app, engine, ids[1], '乙。')

        book = current_book(client, created['id'])
        saved = client.patch(f"/api/master-books/{created['id']}/export/settings", json={
            'revision': book['revision'], 'chapter_pause_ms': 500,
        })
        assert saved.status_code == 200, saved.text
        revision = saved.json()['revision']

        estimate = client.post(f"/api/master-books/{created['id']}/export/estimate", json={
            'revision': revision, 'chapters': list(reversed(ids)),
            'outputs': ['wav', 'srt', 'timeline', 'report'],
        })
        assert estimate.status_code == 200, estimate.text
        estimate = estimate.json()
        assert estimate['selected_chapters'] == ids
        assert estimate['can_export'] is True

        result = client.post(f"/api/master-books/{created['id']}/export/create", json={
            'revision': revision, 'chapters': list(reversed(ids)),
            'outputs': ['wav', 'srt', 'timeline', 'report'],
        })
        assert result.status_code == 200, result.text
        result = result.json()
        assert result['status'] == 'latest'
        assert set(result['links']) == {'wav', 'srt', 'timeline', 'report', 'manifest'}

        timeline = client.get(result['links']['timeline']).json()
        assert timeline['selected_chapters'] == ids
        assert [row['project_id'] for row in timeline['segments']] == ids
        rate = timeline['sample_rate']
        first_samples = first['segments'][0]['audio']['samples']
        second_samples = second['segments'][0]['audio']['samples']
        # Between chapters: first chapter's normal sentence pause (250 ms)
        # plus the explicit 500 ms chapter pause, exactly once.
        expected_gap = round(rate * .75)
        assert timeline['segments'][1]['file_start_sample'] == first_samples + expected_gap
        assert timeline['total_samples'] == first_samples + expected_gap + second_samples

        wav = client.get(result['links']['wav'])
        assert wav.status_code == 200
        info = sf.info(io.BytesIO(wav.content))
        assert info.frames == timeline['total_samples']
        assert info.samplerate == rate


def test_selected_single_chapter_has_no_trailing_chapter_pause(tmp_path):
    app, engine = make_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        ids = [p['id'] for p in created['projects']]
        seed_ready(app, engine, ids[0], '甲。')
        second = seed_ready(app, engine, ids[1], '乙。')
        book = current_book(client, created['id'])
        saved = client.patch(f"/api/master-books/{created['id']}/export/settings", json={
            'revision': book['revision'], 'chapter_pause_ms': 1800,
        }).json()
        result = client.post(f"/api/master-books/{created['id']}/export/create", json={
            'revision': saved['revision'], 'chapters': [ids[1]],
            'outputs': ['timeline'],
        })
        assert result.status_code == 200, result.text
        timeline = client.get(result.json()['links']['timeline']).json()
        assert timeline['selected_chapters'] == [ids[1]]
        assert timeline['total_samples'] == second['segments'][0]['audio']['samples']


def test_xml_implies_portable_zip_and_contains_same_batch_manifest(tmp_path):
    app, engine = make_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        ids = [p['id'] for p in created['projects']]
        for pid, text in zip(ids, ('甲。', '乙。')):
            seed_ready(app, engine, pid, text)
        revision = current_book(client, created['id'])['revision']
        result = client.post(f"/api/master-books/{created['id']}/export/create", json={
            'revision': revision, 'chapters': ids, 'outputs': ['xml'],
            'video_fps': 30,
        })
        assert result.status_code == 200, result.text
        data = result.json()
        assert data['implicit_outputs'] == ['zip']
        assert {'xml', 'xml_readme', 'zip', 'manifest'} <= set(data['links'])
        archive = client.get(data['links']['zip'])
        assert archive.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            names = set(bundle.namelist())
            assert 'delivery/manifest.json' in names
            assert any(name.startswith('delivery/audio/') and name.endswith('.wav') for name in names)
            inside = json.loads(bundle.read('delivery/manifest.json'))
            assert inside['batch_id'] == data['batch_id']
        xml = client.get(data['links']['xml'])
        assert b'<xmeml' in xml.content


def test_report_only_can_export_before_audio_exists(tmp_path):
    app, _ = make_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        revision = current_book(client, created['id'])['revision']
        estimate = client.post(f"/api/master-books/{created['id']}/export/estimate", json={
            'revision': revision, 'chapters': [], 'outputs': ['report'],
        }).json()
        assert estimate['can_export'] is True
        result = client.post(f"/api/master-books/{created['id']}/export/create", json={
            'revision': revision, 'chapters': [], 'outputs': ['report'],
        })
        assert result.status_code == 200, result.text
        assert set(result.json()['links']) == {'report', 'manifest'}


def test_last_book_export_stays_downloadable_when_stale_then_is_replaced(tmp_path):
    app, engine = make_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        ids = [p['id'] for p in created['projects']]
        for pid, text in zip(ids, ('甲。', '乙。')):
            seed_ready(app, engine, pid, text)
        revision = current_book(client, created['id'])['revision']
        first = client.post(f"/api/master-books/{created['id']}/export/create", json={
            'revision': revision, 'chapters': ids, 'outputs': ['timeline'],
        }).json()
        old_url = first['links']['timeline']
        old_batch = first['batch_id']

        state = client.get('/api/projects/' + ids[0] + '/settings').json()
        changed = client.patch('/api/projects/' + ids[0] + '/settings', json={
            'revision': state['project_revision'], 'values': {'pause_ms': 500},
        })
        assert changed.status_code == 200, changed.text

        stale = client.get(f"/api/master-books/{created['id']}/export/current").json()
        assert stale['status'] == 'stale'
        assert stale['batch_id'] == old_batch
        assert client.get(old_url).status_code == 200

        second = client.post(f"/api/master-books/{created['id']}/export/create", json={
            'revision': revision, 'chapters': ids, 'outputs': ['timeline'],
        })
        assert second.status_code == 200, second.text
        second = second.json()
        assert second['batch_id'] != old_batch
        assert second['status'] == 'latest'
        assert client.get(old_url).status_code == 404


def test_book_export_guard_blocks_same_book_writes(tmp_path):
    app, engine = make_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        pid = created['projects'][0]['id']
        seed_ready(app, engine, pid, '甲。')
        app.state.book_export.active_books.add(created['id'])
        try:
            state = client.get('/api/projects/' + pid + '/settings').json()
            blocked = client.patch('/api/projects/' + pid + '/settings', json={
                'revision': state['project_revision'], 'values': {'pause_ms': 333},
            })
            assert blocked.status_code == 409
            assert '正在导出' in blocked.text
            tasks = client.get('/api/model-tasks').json()
            assert created['id'] in tasks['busy_books']
            assert any(t['kind'] == 'book_export' for t in tasks['tasks'])
        finally:
            app.state.book_export.active_books.discard(created['id'])


def _digest(paths):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths if path.is_file()}


def test_legacy_migration_preview_is_read_only_and_classifies_recovery(tmp_path):
    app, _ = make_app(tmp_path)
    store = app.state.store
    books_dir = tmp_path / 'books'
    legacy_id = 'a' * 32
    legacy_text = '旁白：旧章。'
    legacy = {
        'id': legacy_id, 'title': '旧书', 'language': 'zh',
        'chapters': [{'index': 1, 'title': '第一章', 'chars': len(legacy_text),
                      'units': 1, 'text': legacy_text}],
    }
    (books_dir / (legacy_id + '.json')).write_text(
        json.dumps(legacy, ensure_ascii=False), encoding='utf-8')
    project = store.create('旧书 · 第一章', legacy_text, 'zh')
    project['book'] = {'id': legacy_id, 'title': '旧书', 'index': 1, 'chapters': 1}
    store.write(project)

    orphan_id = 'b' * 32
    orphan = store.create('孤儿工程', '旁白：还在。', 'zh')
    orphan['book'] = {'id': orphan_id, 'title': '已删书', 'index': 1, 'chapters': 1}
    store.write(orphan)

    watched = [books_dir / (legacy_id + '.json'),
               store.directory(project['id']) / 'project.json',
               store.directory(orphan['id']) / 'project.json']
    before = _digest(watched)
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        response = client.get('/api/migration/master-books/preview')
        assert response.status_code == 200, response.text
        data = response.json()
        row = next(x for x in data['legacy'] if x['book_id'] == legacy_id)
        assert row['status'] == 'ready_to_wrap'
        orphan_row = next(x for x in data['orphaned'] if x['book_id'] == orphan_id)
        assert orphan_row['status'] == 'recoverable_complete'
        assert data['read_only'] is True
    assert _digest(watched) == before




def test_failed_new_book_batch_keeps_previous_success(tmp_path, monkeypatch):
    app, engine = make_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        ids = [p['id'] for p in created['projects']]
        for pid, text in zip(ids, ('甲。', '乙。')):
            seed_ready(app, engine, pid, text)
        revision = current_book(client, created['id'])['revision']
        first = client.post(f"/api/master-books/{created['id']}/export/create", json={
            'revision': revision, 'chapters': ids, 'outputs': ['timeline'],
        }).json()
        old_batch = first['batch_id']
        old_url = first['links']['timeline']

        def fail(*args, **kwargs):
            raise RuntimeError('故意让新批失败')
        monkeypatch.setattr(app.state.book_export, '_render', fail)
        failed = client.post(f"/api/master-books/{created['id']}/export/create", json={
            'revision': revision, 'chapters': ids, 'outputs': ['timeline'],
        })
        assert failed.status_code == 409
        current = client.get(f"/api/master-books/{created['id']}/export/current").json()
        assert current['batch_id'] == old_batch
        assert current['status'] == 'latest'
        assert client.get(old_url).status_code == 200
        assert app.state.book_export.active_tasks() == []


def test_master_book_mp3_can_be_selected_without_persisting_temp_wav(tmp_path):
    app, engine = make_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        pid = created['projects'][0]['id']
        seed_ready(app, engine, pid, '甲。')
        revision = current_book(client, created['id'])['revision']
        result = client.post(f"/api/master-books/{created['id']}/export/create", json={
            'revision': revision, 'chapters': [pid], 'outputs': ['mp3'],
        })
        assert result.status_code == 200, result.text
        data = result.json()
        assert set(data['links']) == {'mp3', 'manifest'}
        audio = client.get(data['links']['mp3'])
        assert audio.status_code == 200 and len(audio.content) > 100
        batch = app.state.book_export._root(created['id']) / data['batch_id']
        assert (batch / 'full.mp3').is_file()
        assert not (batch / 'full.wav').exists()



def test_book_export_refuses_when_unselected_sibling_is_processing(tmp_path):
    app, engine = make_app(tmp_path)
    with TestClient(app, base_url='http://127.0.0.1', headers=HEADERS) as client:
        created = make_book(client)
        first, second = [p['id'] for p in created['projects']]
        seed_ready(app, engine, first, '甲。')
        raw = app.state.store.read(second)
        raw['job'] = {'kind': 'attribution', 'status': 'running'}
        # Seed directly before claiming export; this simulates an already-running sibling.
        app.state.store.write(raw)
        revision = current_book(client, created['id'])['revision']
        response = client.post(f"/api/master-books/{created['id']}/export/create", json={
            'revision': revision, 'chapters': [first], 'outputs': ['timeline'],
        })
        assert response.status_code == 409
        assert '同一主工程有章节正在处理' in response.text
        assert app.state.book_export.active_tasks() == []

