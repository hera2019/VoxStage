"""Suggestions for an unplaced line: the model's uncertain judgement, the way
a character talked in confirmed chapters, and the rules a reader applies
without thinking. All text here is written for the test. Claude Hera, 2026-09-15."""
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine
from runtime.habits import profiles, suggest
from evals.speaker_attribution.source_units import source_units
from tests.test_attribution_import import Roles, HEADERS

# A shop with three people: 陈小雪 the owner (also 老板娘), her helper 阿宁, and old 王伯.
LINES = [('老板娘～，猫又跑出去啦～', '阿宁'), ('老板娘～，帮帮忙～', '阿宁'), ('嗯～，赏你一块糖～', '陈小雪'),
         ('哈哈～，你们又想赖账？', '陈小雪'), ('两个小笨蛋～', '陈小雪'), ('小雪啊，账本我看过了。', '王伯')]


def test_a_character_is_recognised_by_habit_and_never_by_being_addressed():
    prof = profiles(LINES)
    best, margin = suggest('老板娘～，猫饿了～', prof)
    assert best == '阿宁' and margin > 0
    best, _ = suggest('陈小雪～，你过来～', prof)                      # 陈小雪 is named -> not her line
    assert best != '陈小雪'
    assert suggest('x', {}) == (None, 0.0)


def test_uncertain_model_names_and_habit_matches_arrive_yellow_not_empty(tmp_path):
    class Judges(Roles):
        def annotate(self, text, log_path):
            labels = []
            for u in source_units(text):
                if u['text'].startswith('“'):
                    labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': '小雪' if '雨' in u['text'] else 'UNKNOWN', 'certain': False})
                else:
                    labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Judges()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        book = c.post('/api/books', json={'title': '雪', 'language': 'zh', 'script': '第一章 一\n小雪说：“雨停了吗～，好冷呀～”阿宁说：“没停。”\n\n第二章 二\n“雨还下着吗～，好冷呀～”她问。“下着。”\n'}).json()
        ch1 = c.get(f"/api/books/{book['id']}/chapters/1").json()
        d1 = c.post('/api/attribution/draft', json={'script': ch1['text'], 'language': 'zh', 'book_id': book['id']}).json()
        labels = []
        for u in d1['units']:
            sp = u['speaker']
            if u['kind'] == 'dialogue':
                sp = '小雪' if '雨' in u['text'] else '阿宁'
            labels.append({'id': u['id'], 'kind': u['kind'], 'speaker': sp})
        c.post('/api/attribution/confirm', json={'draft_id': d1['draft_id'], 'name': ch1['project_name'], 'labels': labels, 'book_id': book['id'], 'chapter_index': 1})
        ch2 = c.get(f"/api/books/{book['id']}/chapters/2").json()
        d2 = c.post('/api/attribution/draft', json={'script': ch2['text'], 'language': 'zh', 'book_id': book['id']}).json()
        by = {u['text'].strip(): u for u in d2['units'] if not u['blank']}
        rain = by['“雨还下着吗～，好冷呀～”']
        assert rain['speaker'] == '小雪' and rain['tier'] == 'suggested' and '推断' in rain['basis']
        short = by['“下着。”']
        assert short['speaker'] in ('阿宁', 'UNKNOWN')
        assert short.get('tier') == 'suggested' or short.get('hint') in ('阿宁', '小雪') or short['speaker'] == 'UNKNOWN'


def test_a_model_that_skips_the_blank_units_and_pads_with_repeats_is_mended_by_id(tmp_path, monkeypatch):
    """The schema fixes the count and the vocabulary of ids but not uniqueness."""
    import json
    from runtime import attribution as A
    text = '“来了。”\n“好。”\n她笑了。'
    units = source_units(text)
    assert [u['text'] for u in units] == ['“来了。”', '\n', '“好。”', '\n她笑了。']
    padded = [{'id': 'u0', 'kind': 'dialogue', 'speaker': '甲', 'certain': True}, {'id': 'u2', 'kind': 'dialogue', 'speaker': '乙', 'certain': True},
              {'id': 'u3', 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True}, {'id': 'u3', 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True}]
    class Server:
        def __init__(self, *a, **k): pass
        def poll(self): return None
        def terminate(self): pass
        def wait(self, timeout=None): pass
        def kill(self): pass
    monkeypatch.setattr(A.subprocess, 'Popen', Server)
    responses = iter([{'ok': True}, {'choices': [{'message': {'content': json.dumps({'labels': padded}, ensure_ascii=False)}}]}])
    class Reply:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps(self.payload).encode()
    monkeypatch.setattr(A.urllib.request, 'urlopen', lambda req, timeout=0: Reply(next(responses)))
    engine = A.RoleDraftEngine()
    monkeypatch.setattr(engine, 'ready', True)
    monkeypatch.setattr(A.hashlib, 'file_digest', lambda stream, name: type('D', (), {'hexdigest': lambda self: engine.sha256})())
    engine.model = tmp_path / 'm.gguf'; (tmp_path / 'm.gguf').write_bytes(b'x')
    result = engine.annotate(text, tmp_path / 'log')
    assert result['repaired'] == 'skipped_units_filled'
    assert [(l['id'], l['kind'], l['speaker']) for l in result['labels']] == [
        ('u0', 'dialogue', '甲'), ('u1', 'narration', 'NARRATOR'), ('u2', 'dialogue', '乙'), ('u3', 'narration', 'NARRATOR')]


def test_the_rules_beside_the_model_and_learning_while_reviewing(tmp_path):
    class Names(Roles):
        def annotate(self, text, log_path):
            labels = []
            for u in source_units(text):
                if u['text'].startswith('“'):
                    labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': '陈小雪', 'certain': True})   # even for 陈小雪～，你过来
                else:
                    labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Names()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = c.post('/api/attribution/draft', json={'script': '阿宁说：“陈小雪～，你过来～”陈小雪说：“来了。”\n“陈小雪～，帮帮忙～”', 'language': 'zh'}).json()
        by = {u['text'].strip(): u for u in d['units'] if not u['blank']}
        # Rule 1: the speech tag beside the line beats the model.
        assert by['“陈小雪～，你过来～”']['speaker'] == '阿宁' and '旁边的叙述' in by['“陈小雪～，你过来～”']['basis']
        assert by['“来了。”'].get('tier') is None and by['“来了。”']['speaker'] == '陈小雪'
        # Rule 2: no tag, the line names 陈小雪, the cast has one other person.
        assert by['“陈小雪～，帮帮忙～”']['speaker'] == '阿宁' and by['“陈小雪～，帮帮忙～”']['tier'] == 'suggested' and '剩下的只有' in by['“陈小雪～，帮帮忙～”']['basis']
        # Learning while reviewing: two settled lines teach, the third is scored.
        r = c.post('/api/attribution/suggest', json={'units': [
            {'id': 'a', 'text': '老板娘～，帮帮忙～', 'kind': 'dialogue', 'speaker': '阿宁', 'fixed': True},
            {'id': 'b', 'text': '嗯～，赏你一块糖～', 'kind': 'dialogue', 'speaker': '陈小雪', 'fixed': True},
            {'id': 'c', 'text': '老板娘～，猫跑了～', 'kind': 'dialogue', 'speaker': '', 'fixed': False}]}).json()
        assert r['taught'] == 2 and r['suggestions']['c']['speaker'] == '阿宁'


def test_an_alias_learned_while_reviewing_is_applied_to_the_next_draft_of_the_book(tmp_path):
    class Boss(Roles):
        def annotate(self, text, log_path):
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                'speaker': '老板娘' if u['text'].startswith('“') else 'NARRATOR', 'certain': True} for u in source_units(text)],
                    'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Boss()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        book = c.post('/api/books', json={'title': '书', 'language': 'zh', 'script': '第一章 一\n老板娘说：“来。”\n\n第二章 二\n老板娘又说：“来呀。”\n'}).json()
        ch1 = c.get(f"/api/books/{book['id']}/chapters/1").json()
        d1 = c.post('/api/attribution/draft', json={'script': ch1['text'], 'language': 'zh', 'book_id': book['id']}).json()
        assert [u['speaker'] for u in d1['units'] if u['kind'] == 'dialogue'] == ['老板娘']
        labels = [{'id': u['id'], 'kind': u['kind'], 'speaker': '陈小雪' if u['kind'] == 'dialogue' else u['speaker']} for u in d1['units']]
        r = c.post('/api/attribution/confirm', json={'draft_id': d1['draft_id'], 'name': ch1['project_name'], 'labels': labels,
                                                    'book_id': book['id'], 'chapter_index': 1, 'aliases': {'老板娘': '陈小雪'}})
        assert r.status_code == 200, r.text
        assert c.get('/api/books/' + book['id']).json()['aliases'] == {'老板娘': '陈小雪'}
        ch2 = c.get(f"/api/books/{book['id']}/chapters/2").json()
        d2 = c.post('/api/attribution/draft', json={'script': ch2['text'], 'language': 'zh', 'book_id': book['id']}).json()
        assert [u['speaker'] for u in d2['units'] if u['kind'] == 'dialogue'] == ['陈小雪']    # the model still said 老板娘


def test_mentions_calls_and_the_sex_of_a_line():
    from runtime.habits import mentioned, addressed, sex_profiles, sex_of_line, names_from_tags, speech_tag
    assert addressed('阿宁～，快来～', '阿宁') and not addressed('给娘看看', '娘') and not addressed('娘的话', '娘')
    assert mentioned('阿宁，你去问老板娘', '老板娘') and mentioned('阿宁，你去问老板娘', '阿宁')
    assert not mentioned('给娘看看', '娘') and mentioned('娘～，来', '娘')            # one character: only as a call
    prof = sex_profiles([('嗯～，赏你一块糖～，乖～', 'f'), ('哈哈～，你们又想赖账呀～', 'f'),
                         ('账本我看过了，这个月亏了。', 'm'), ('老板娘，货到了，我去搬。', 'm')])
    assert sex_of_line('老板娘，车修好了，我去开。', prof)[0] == 'm'
    assert sex_of_line('嗯～，乖～，再赏你一块～', prof)[0] == 'f'
    assert names_from_tags(['阿宁说：', '他说：', '陈小雪笑道：', '她冷笑一声，说道：']) == ['阿宁', '陈小雪']
    m = {'阿宁': ['阿宁'], '陈小雪': ['陈小雪', '老板娘', '娘']}
    assert speech_tag('陈小雪笑道：', '', m) == '陈小雪' and speech_tag('', '”阿宁说。', m) == '阿宁'
    assert speech_tag('阿宁说：', '陈小雪说：', m) == '阿宁'          # the narration after introduces the next line
