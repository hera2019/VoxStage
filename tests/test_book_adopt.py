"""A legacy book becomes a master book in place: exact chapter projects join
as processed members with their settings frozen, missing chapters become
unprocessed projects, the book's defaults come from the first processed
chapter, and everything touched is backed up first. Invented text.
Claude Hera, 2026-09-21."""
import json
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine
from runtime.book_adopt import adopt_plan
from tests.test_attribution_import import Roles, HEADERS


class Never(Roles):
    def annotate(self, text, log_path, **kw):
        raise AssertionError('the model must not be asked')


def test_adopting_a_legacy_book(tmp_path):
    script = '第一章 猫\n陈小雪看着窗外。\n\n第二章 账\n王伯翻开账本。\n\n第三章 雪\n雪停了。\n'
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Never()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        book = c.post('/api/books', json={'title': '小店', 'language': 'zh', 'script': script}).json()
        assert len(book['chapters']) == 3
        # Chapter two gets a project the old way: a labelled script confirmed as that chapter.
        ch = c.get(f"/api/books/{book['id']}/chapters/2").json()
        d = c.post('/api/attribution/draft', json={'script': ch['text'], 'language': 'zh', 'hints': [{'start': 0, 'end': len(ch['text']) - 1, 'speaker': 'NARRATOR'}]}).json()
        labels = [{'id': u['id'], 'kind': u['kind'], 'speaker': u['speaker']} for u in d['units']]
        p = c.post('/api/attribution/confirm', json={'draft_id': d['draft_id'], 'name': ch['project_name'], 'labels': labels, 'book_id': book['id'], 'chapter_index': 2}).json()
        c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'pause_ms': 333})
        r = c.post(f"/api/migration/master-books/{book['id']}/adopt")
        assert r.status_code == 200, r.text
        out = r.json()
        assert out['updated'] == [p['id']] and len(out['created']) == 2 and out['left_alone'] == []
        master = c.get('/api/books/' + book['id']).json()
        assert master['master_schema'] == 1 and len(master['members']) == 3 and master['members'][1] == p['id']
        assert master['settings']['pause_ms'] == 333                       # the book's defaults follow the processed chapter
        kept = c.get('/api/projects/' + p['id']).json()
        assert kept['processing_state'] == 'processed' and kept['pause_ms'] == 333 and kept['book']['chapters'] == 3
        fresh = c.get('/api/projects/' + out['created'][0]).json()
        assert fresh['processing_state'] == 'unprocessed' and fresh['book']['index'] == 1 and fresh['pause_ms'] == 333   # inherited
        assert c.get(f"/api/projects/{out['created'][0]}/settings").json()['sources']['pause_ms']['level'] != 'project'
        backup = next((tmp_path / 'p').parent.glob('books/*.snapshots/adopt-*/meta.json'))
        assert json.loads(backup.read_text())['updated'] == [p['id']]
        r = c.post(f"/api/migration/master-books/{book['id']}/adopt")
        assert r.status_code == 400 and '已经是主工程' in r.json()['detail']
    # Pure plan: a project whose text drifted from the chapter is left alone, listed.
    legacy = {'id': 'b' * 32, 'title': '书', 'language': 'zh', 'chapters': [{'index': 1, 'title': '一', 'text': '甲\n'}], 'cast': [], 'aliases': {}}
    drifted = {'id': 'c' * 32, 'name': '一', 'language': 'zh', 'source_script': '甲乙\n', 'segments': [], 'book': {'id': 'b' * 32, 'index': 1}}
    plan = adopt_plan(legacy, [drifted])
    assert plan['left_alone'] == ['c' * 32] and len(plan['created']) == 1


def test_recovering_an_orphan_group_and_deleting_an_empty_master(tmp_path):
    """Projects still pointing at a deleted book become that book again, same
    id; a master book is deleted only when it has no chapters."""
    from runtime.book_adopt import recover_plan
    linked = [{'id': 'a' * 32, 'name': '一', 'language': 'zh', 'source_script': '甲\n', 'segments': [{'id': 's1', 'text': '甲', 'speaker': '旁白', 'source_start': 0, 'source_end': 1}], 'pause_ms': 200, 'book': {'id': 'b' * 32, 'title': '书', 'index': 2, 'chapters': 2}},
              {'id': 'c' * 32, 'name': '零', 'language': 'zh', 'source_script': '乙\n', 'segments': [], 'book': {'id': 'b' * 32, 'title': '书', 'index': 1, 'chapters': 2}}]
    plan = recover_plan('b' * 32, linked)
    assert plan['book']['members'] == ['c' * 32, 'a' * 32] and plan['book']['title'] == '书' and plan['book']['master_schema'] == 1
    assert plan['updated'][0]['processing_state'] == 'unprocessed' and plan['updated'][1]['processing_state'] == 'processed' and plan['updated'][1]['pause_ms'] == 200
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Never()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        b = c.post('/api/master-books/empty', json={'title': '空', 'language': 'zh'}).json()
        assert b['master_schema'] == 1 and b['chapters'] == []
        r = c.patch('/api/master-books/' + b['id'], json={'revision': b['revision'], 'title': '空书', 'language': 'en'}).json()
        assert r['language'] == 'en' and r['title'] == '空书'
        assert c.delete('/api/master-books/' + b['id']).json() == {'deleted': b['id']}
        assert c.delete('/api/master-books/' + b['id']).status_code in (400, 404)
