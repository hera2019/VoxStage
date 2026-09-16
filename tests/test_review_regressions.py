"""Self-written fixtures for review data integrity; not model accuracy scores."""
import importlib
import pytest
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine
from tests.test_attribution_import import Roles, HEADERS
from tests.test_cast import Tags, TEXT


@pytest.mark.parametrize('text,name,expected,suggested', [
    ('“Not today,” said Finch.', 'Mr. Finch', 'Mr. Finch', True),
    ('“Not today,” Finch replied.', 'Mr. Finch', 'Mr. Finch', True),
    ('“Not today,” said Miss Finch.', 'Mr. Finch', 'UNKNOWN', False),
    ('“Not today,” said Fincher.', 'Mr. Finch', 'UNKNOWN', False),
    ('“Not today,” said Mr Finch.', 'Mr. Finch', 'Mr. Finch', False),
    ('“Not today,” said Mrs. Finch.', 'Mr. Finch', 'UNKNOWN', False),
    ('“Not today,” said Eleanor Ashford.', 'Eleanor Ashford', 'Eleanor Ashford', False),
])
def test_english_names_keep_titles_distinct(tmp_path, text, name, expected, suggested):
    class Named(Roles):
        def annotate(self, text, log_path):
            result = super().annotate(text, log_path)
            for label in result['labels']:
                if label['kind'] == 'dialogue':
                    label['speaker'] = name
            return result
    with TestClient(create_app(tmp_path/'p', FixtureEngine(), role_engine=Named()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        r = c.post('/api/attribution/draft', json={'script': text, 'language': 'en'})
        assert r.status_code == 200, r.text
        line = next(u for u in r.json()['units'] if u['kind'] == 'dialogue')
        assert line['speaker'] == expected
        assert (line.get('tier') == 'suggested') is suggested


@pytest.mark.parametrize('send_revision', [True, False])
def test_confirm_rechecks_revision_after_building_segments(tmp_path, monkeypatch, send_revision):
    """A save during confirmation must survive; no stale project may be created."""
    app_module = importlib.import_module('runtime.app')
    original = app_module.project_segments
    with TestClient(create_app(tmp_path/'p', FixtureEngine(), role_engine=Tags()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = c.post('/api/attribution/draft', json={'script': TEXT, 'language': 'zh'}).json()
        cat = next(u for u in d['units'] if '猫' in u['text'])
        def racing_segments(*args, **kwargs):
            saved = c.patch('/api/attribution/draft/' + d['draft_id'], json={
                'expected_revision': 1,
                'decisions': [{'unit_id': cat['id'], 'speaker': '阿宁', 'edited': True, 'confirmed': True}]})
            assert saved.status_code == 200, saved.text
            return original(*args, **kwargs)
        monkeypatch.setattr(app_module, 'project_segments', racing_segments)
        labels = [{'id': u['id'], 'kind': u['kind'], 'speaker': u['speaker'] if u['speaker'] != 'UNKNOWN' else '王伯'} for u in d['units']]
        body = {'draft_id': d['draft_id'], 'name': '并发检查', 'labels': labels}
        if send_revision:
            body['expected_revision'] = 1
        r = c.post('/api/attribution/confirm', json=body)
        assert r.status_code == 409, r.text
        current = c.get('/api/attribution/draft/' + d['draft_id']).json()
        assert current['revision'] == 2
        assert current['decisions'][cat['id']]['speaker'] == '阿宁'
        assert c.get('/api/projects').json() == []



def test_confirm_does_not_overwrite_another_chapters_cast_change(tmp_path, monkeypatch):
    app_module = importlib.import_module('runtime.app')
    original = app_module.project_segments
    with TestClient(create_app(tmp_path/'p', FixtureEngine(), role_engine=Tags()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        book = c.post('/api/books', json={'title': '并发人物表', 'language': 'zh', 'script': TEXT}).json()
        def make_draft():
            return c.post('/api/attribution/draft', json={'script': TEXT, 'language': 'zh', 'book_id': book['id']}).json()
        first, other = make_draft(), make_draft()
        person = next(e for e in other['cast'] if e['name'] == '陈小雪')
        def racing_segments(*args, **kwargs):
            saved = c.patch('/api/attribution/draft/'+other['draft_id'], json={
                'expected_revision': 1, 'rename': {'cast_id': person['id'], 'name': '小雪'}})
            assert saved.status_code == 200, saved.text
            return original(*args, **kwargs)
        monkeypatch.setattr(app_module, 'project_segments', racing_segments)
        labels = [{'id': u['id'], 'kind': u['kind'], 'speaker': u['speaker'] if u['speaker'] != 'UNKNOWN' else '王伯'} for u in first['units']]
        r = c.post('/api/attribution/confirm', json={'draft_id': first['draft_id'], 'name': '并发人物表', 'labels': labels, 'expected_revision': 1})
        assert r.status_code == 409, r.text
        current = c.get('/api/attribution/draft/'+other['draft_id']).json()
        assert next(e for e in current['cast'] if e['id'] == person['id'])['name'] == '小雪'
        assert c.get('/api/projects').json() == []
