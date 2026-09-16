"""The cast — characters as ids with names as ways of calling them — and the
reviewer's decisions saved with the draft: revisions, protection, splits.
All text is written for the test. Claude Hera, 2026-09-16 (Astra's first-round hand-off)."""
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine
from runtime import cast as C
from evals.speaker_attribution.source_units import source_units
from tests.test_attribution_import import Roles, HEADERS


def test_a_character_keeps_its_id_through_renames_aliases_and_splits():
    cast = []
    xue, created = C.ensure(cast, '陈小雪', 'tag'); assert created
    C.add_alias(cast, xue['id'], '老板娘')
    assert C.find(cast, '老板娘') is xue and C.alias_table(cast) == {'老板娘': '陈小雪'}
    C.rename(cast, xue['id'], '小雪')
    assert xue['name'] == '小雪' and '陈小雪' in xue['aliases'] and C.find(cast, '陈小雪') is xue
    C.ensure(cast, '阿宁', 'model')
    try:
        C.rename(cast, xue['id'], '阿宁'); assert False
    except ValueError:
        pass                                                       # two characters, one name: refused, not merged
    new = C.split(cast, '老板娘')
    assert new['name'] == '老板娘' and new['id'] != xue['id'] and '老板娘' not in xue['aliases'] and new['split_from'] == xue['id']
    assert C.unsplit(cast, new['id']) is xue and '老板娘' in xue['aliases'] and C.by_id(cast, new['id']) is None


class Tags(Roles):
    def annotate(self, text, log_path):
        labels = []
        for u in source_units(text):
            if u['text'].startswith('“'):
                labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': '陈小雪' if '糖' in u['text'] else 'UNKNOWN', 'certain': '糖' in u['text']})
            else:
                labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
        return {'labels': labels, 'model_sha256': 'fixture'}


TEXT = '陈小雪说：“赏你一块糖～”\n“老板娘～，猫跑了～”\n“哪只？”\n王伯说：“账本呢？”\n'


def test_decisions_are_saved_with_a_revision_and_a_stale_save_is_refused(tmp_path):
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Tags()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = c.post('/api/attribution/draft', json={'script': TEXT, 'language': 'zh'}).json()
        assert d['revision'] == 1 and d['decisions'] == {}
        names = {e['name']: e for e in d['cast']}
        assert set(names) == {'陈小雪', '王伯'} and names['陈小雪']['source'] in ('tag', 'model') and names['王伯']['source'] == 'tag'
        cat = next(u for u in d['units'] if '猫' in u['text'])
        assert cat['speaker'] == 'UNKNOWN'
        r = c.patch('/api/attribution/draft/' + d['draft_id'], json={'expected_revision': 1, 'decisions': [{'unit_id': cat['id'], 'speaker': '阿宁', 'edited': True, 'confirmed': True}]})
        assert r.status_code == 200, r.text
        r = r.json()
        assert r['revision'] == 2 and r['decisions'][cat['id']]['speaker'] == '阿宁' and r['decisions'][cat['id']]['edited'] is True
        assert '阿宁' in {e['name'] for e in r['cast']} and next(e for e in r['cast'] if e['name'] == '阿宁')['source'] == 'person'
        assert next(u for u in r['units'] if u['id'] == cat['id'])['decided'] == {'edited': True, 'confirmed': True, 'source': 'person'}
        # A save that saw revision 1 is stale: refused with the current state.
        stale = c.patch('/api/attribution/draft/' + d['draft_id'], json={'expected_revision': 1, 'decisions': [{'unit_id': cat['id'], 'speaker': '王伯'}]})
        assert stale.status_code == 409 and stale.json()['detail']['revision'] == 2 and stale.json()['detail']['decisions'][cat['id']]['speaker'] == '阿宁'
        # The draft can be read back as the page had it, decisions laid over.
        g = c.get('/api/attribution/draft/' + d['draft_id']).json()
        assert g['revision'] == 2 and next(u for u in g['units'] if u['id'] == cat['id'])['speaker'] == '阿宁'
        # A confirmed-but-unchanged line is protected too, and says its source.
        sugar = next(u for u in d['units'] if '糖' in u['text'])
        r = c.patch('/api/attribution/draft/' + d['draft_id'], json={'expected_revision': 2, 'decisions': [{'unit_id': sugar['id'], 'edited': False, 'confirmed': True}]}).json()
        assert r['decisions'][sugar['id']] == {**r['decisions'][sugar['id']], 'speaker': '陈小雪', 'edited': False, 'confirmed': True, 'source': 'tag'}
        # The live re-suggest treats decided units as fixed, whatever the page sends.
        s = c.post('/api/attribution/suggest', json={'draft_id': d['draft_id'], 'revision': 3, 'units': [
            {'id': cat['id'], 'text': '老板娘～，猫跑了～', 'kind': 'dialogue', 'speaker': '', 'fixed': False},
            {'id': 'x', 'text': '老板娘～，猫饿了～', 'kind': 'dialogue', 'speaker': '', 'fixed': False}]}).json()
        assert cat['id'] not in s['suggestions'] and s['revision'] == 3 and s['suggestions']['x']['speaker'] == '阿宁'
        # Confirm takes the saved decisions over the page's labels, and records sources.
        labels = [{'id': u['id'], 'kind': u['kind'], 'speaker': '王伯' if u['id'] == cat['id'] else (u['speaker'] if u['speaker'] != 'UNKNOWN' else '王伯')} for u in d['units']]
        p = c.post('/api/attribution/confirm', json={'draft_id': d['draft_id'], 'name': '店', 'labels': labels, 'expected_revision': 3}).json()
        confirmed = {l['id']: l for l in p['attribution']['confirmed_labels']}
        assert confirmed[cat['id']]['speaker'] == '阿宁' and confirmed[cat['id']]['source'] == 'person' and confirmed[cat['id']]['edited'] is True
        assert confirmed[sugar['id']]['source'] == 'tag' and confirmed[sugar['id']]['edited'] is False and confirmed[sugar['id']]['confirmed'] is True
        assert set(p['cast_ids']) == {'陈小雪', '阿宁', '王伯'} and p['attribution']['draft_revision'] == 3
        assert c.get('/api/attribution/draft/' + d['draft_id']).json()['confirmed_project_id'] == p['id']
        assert c.post('/api/attribution/confirm', json={'draft_id': d['draft_id'], 'name': '店', 'labels': labels, 'expected_revision': 1}).status_code == 409


def test_a_books_cast_is_shared_by_its_chapters_and_a_split_can_be_undone(tmp_path):
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Tags()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        book = c.post('/api/books', json={'title': '店', 'language': 'zh', 'script': '第一章 一\n' + TEXT + '\n第二章 二\n陈小雪说：“赏你一块糖～”\n“老板娘～，来一斤～”\n'}).json()
        ch1 = c.get(f"/api/books/{book['id']}/chapters/1").json()
        d1 = c.post('/api/attribution/draft', json={'script': ch1['text'], 'language': 'zh', 'book_id': book['id']}).json()
        xue = next(e for e in d1['cast'] if e['name'] == '陈小雪')
        # The reviewer says 老板娘 is 陈小雪 (a rename carried along) — an alias on the book's cast.
        r = c.patch('/api/attribution/draft/' + d1['draft_id'], json={'expected_revision': 1, 'alias': {'cast_id': xue['id'], 'alias': '老板娘'}}).json()
        assert c.get('/api/books/' + book['id']).json()['aliases'] == {'老板娘': '陈小雪'}
        ch2 = c.get(f"/api/books/{book['id']}/chapters/2").json()
        d2 = c.post('/api/attribution/draft', json={'script': ch2['text'], 'language': 'zh', 'book_id': book['id']}).json()
        assert {e['name'] for e in d2['cast']} >= {'陈小雪', '王伯'} and next(e for e in d2['cast'] if e['name'] == '陈小雪')['id'] == xue['id']
        # Then decides the 老板娘 here is someone else: the alias splits into a character; undo puts it back.
        r = c.patch('/api/attribution/draft/' + d2['draft_id'], json={'expected_revision': 1, 'split': '老板娘'}).json()
        boss = next(e for e in r['cast'] if e['name'] == '老板娘')
        assert boss['split_from'] == xue['id'] and c.get('/api/books/' + book['id']).json()['aliases'] == {}
        r = c.patch('/api/attribution/draft/' + d2['draft_id'], json={'expected_revision': 2, 'unsplit': boss['id']}).json()
        assert c.get('/api/books/' + book['id']).json()['aliases'] == {'老板娘': '陈小雪'} and not any(e['name'] == '老板娘' for e in r['cast'])
        # Renaming keeps the id; the same name for two characters is refused.
        r = c.patch('/api/attribution/draft/' + d2['draft_id'], json={'expected_revision': 3, 'rename': {'cast_id': xue['id'], 'name': '小雪'}}).json()
        assert next(e for e in r['cast'] if e['id'] == xue['id'])['name'] == '小雪' and c.get('/api/books/' + book['id']).json()['aliases'] == {'老板娘': '小雪', '陈小雪': '小雪'}
        bad = c.patch('/api/attribution/draft/' + d2['draft_id'], json={'expected_revision': 4, 'rename': {'cast_id': xue['id'], 'name': '王伯'}})
        assert bad.status_code == 400 and '已经有一个' in bad.text


def test_an_unfinished_review_can_be_abandoned_and_a_confirmed_one_cannot(tmp_path):
    """本人 2026-09-17: 继续上次的复核 could only be continued. Abandoning keeps
    the record (the model's answers, the decisions so far) but marks it, so no
    page offers it again; a draft already made into a project stays as it is."""
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Tags()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = c.post('/api/attribution/draft', json={'script': TEXT, 'language': 'zh'}).json()
        assert c.get('/api/attribution/draft/' + d['draft_id']).json()['abandoned'] is False
        r = c.delete('/api/attribution/draft/' + d['draft_id'])
        assert r.status_code == 200 and r.json() == {'draft_id': d['draft_id'], 'abandoned': True}
        g = c.get('/api/attribution/draft/' + d['draft_id']).json()
        assert g['abandoned'] is True and g['revision'] == 1 and len(g['units']) == len(d['units'])
        d2 = c.post('/api/attribution/draft', json={'script': TEXT, 'language': 'zh'}).json()
        labels = [{'id': u['id'], 'kind': u['kind'], 'speaker': u['speaker'] if u['speaker'] != 'UNKNOWN' else '王伯'} for u in d2['units']]
        c.post('/api/attribution/confirm', json={'draft_id': d2['draft_id'], 'name': '店', 'labels': labels})
        r = c.delete('/api/attribution/draft/' + d2['draft_id'])
        assert r.status_code == 400 and '已经确认' in r.json()['detail']
        assert c.delete('/api/attribution/draft/zz').status_code == 400
