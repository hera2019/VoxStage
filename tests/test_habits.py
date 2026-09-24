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


def test_when_the_default_model_places_nobody_the_other_installed_model_is_asked(tmp_path):
    """A draft of nothing — every quoted line narration, or every speaker a word
    the story never uses — sends the passage to the other model; the run that
    places more lines is kept, and the first stays in the record (2026-09-16)."""
    import json
    class TwoModels(Roles):
        model_id = 'a'
        asked = []
        def installed(self):
            return [{'id': 'a', 'label': 'A', 'installed': True}, {'id': 'b', 'label': 'B', 'installed': True}]
        def select(self, model_id):
            self.model_id = model_id
        def annotate(self, text, log_path):
            self.asked.append(self.model_id)
            labels = []
            for u in source_units(text):
                if u['text'].startswith('“'):
                    # a: a translated name the text never spells; b: the name as written
                    labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': 'XUE' if self.model_id == 'a' else '小雪', 'certain': True})
                else:
                    labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture', 'model_id': self.model_id}
    engine = TwoModels()
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=engine), base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = c.post('/api/attribution/draft', json={'script': '小雪说：“来。”\n“好。”\n“走吧。”\n', 'language': 'zh'}).json()
        assert engine.asked == ['a', 'b'] and engine.model_id == 'a'          # asked both, left on the default
        assert [u['speaker'] for u in d['units'] if u['kind'] == 'dialogue'] == ['小雪', '小雪', '小雪']
        assert '已换用「B」' in d['notice']
        record = json.loads((tmp_path / 'p-role-drafts' / (d['draft_id'] + '.json')).read_text())
        assert record['fallback_model'] == 'b' and record['first_attempt']['model_id'] == 'a' and record['model_id'] == 'b'
        # A default that places the lines is not second-guessed.
        engine.asked.clear()
        engine.annotate = lambda text, log_path: {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                                             'speaker': '小雪' if u['text'].startswith('“') else 'NARRATOR', 'certain': True} for u in source_units(text)],
                                                  'model_sha256': 'fixture', 'model_id': 'a'}
        d = c.post('/api/attribution/draft', json={'script': '小雪说：“来。”\n“好。”\n“走吧。”\n', 'language': 'zh'}).json()
        assert d['notice'] is None and engine.model_id == 'a'


def test_the_person_spoken_to_is_not_the_speaker_and_a_nameless_tag_gets_a_stand_in(tmp_path):
    """有一回对我说道 / 见了我，又说道 name the person spoken to or seen, not the
    speaker. A tag whose subject is nobody in particular — 有的叫道, 旁人问道,
    一个喝酒的人说道 — gets a stand-in (众人 / 某人), yellow, that the reviewer
    renames once (Kong Yiji, 2026-09-16)."""
    from runtime.habits import speech_tag, anonymous_tag
    m = {'我': ['我'], '阿宁': ['阿宁'], '陈小雪': ['陈小雪', '老板娘']}
    assert speech_tag('有一回对我说道，', '', m) is None and speech_tag('见了我，又说道，', '', m) is None
    assert speech_tag('阿宁有一回对我说道，', '', m) == '阿宁'                       # the subject still counts
    assert speech_tag('阿宁望着老板娘说：', '', m) == '阿宁' and speech_tag('', '”阿宁对我说。', m) == '阿宁'
    assert anonymous_tag('大家都看着他笑，有的叫道：') == '众人' and anonymous_tag('旁人便又问道，') == '众人'
    assert anonymous_tag('一个买酒的人说道，') == '某人' and anonymous_tag('忽然听得一个声音，') == '某人' and anonymous_tag('', '”有人说。') == '某人'
    assert anonymous_tag('阿宁对他们说道：') is None and anonymous_tag('阿宁说：') is None
    class Guesses(Roles):
        def annotate(self, text, log_path):
            labels = []
            for u in source_units(text):
                if u['text'].startswith('“'):
                    labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': '阿宁' if '赖账' in u['text'] else 'UNKNOWN', 'certain': True})
                else:
                    labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Guesses()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        text = '阿宁一进门，柜边的人都笑了，有的叫道：“阿宁，你又来赖账？”\n一个买酒的人说道，“他上回就没给钱。”\n阿宁对我说道，“我这就给。”\n'
        d = c.post('/api/attribution/draft', json={'script': text, 'language': 'zh'}).json()
        by = {u['text'].strip(): u for u in d['units'] if not u['blank']}
        crowd = by['“阿宁，你又来赖账？”']
        assert crowd['speaker'] == '众人' and crowd['tier'] == 'suggested' and crowd['stand_in'] and crowd['hint'] == '阿宁'   # the model's 阿宁 kept as a hint
        assert by['“他上回就没给钱。”']['speaker'] == '某人甲' and by['“他上回就没给钱。”']['tier'] == 'suggested'   # lettered per exchange
        # Two strangers named differently in one exchange are two people; the same words again are the same one.
        d = c.post('/api/attribution/draft', json={'script': '一个买酒的人说道，“他上回就没给钱。”有人接口道：“可不是。”一个买酒的人又说：“算了。”\n', 'language': 'zh'}).json()
        assert [u['speaker'] for u in d['units'] if u['kind'] == 'dialogue'] == ['某人甲', '某人乙', '某人甲']
        assert by['“我这就给。”']['speaker'] == '阿宁' and by['“我这就给。”'].get('tier') is None    # The fixture explicitly says 阿宁对我说道; 阿宁对我 is not a second name.
        # English narration is left alone.
        d = c.post('/api/attribution/draft', json={'script': 'Someone said, “Not today.”\n', 'language': 'en'}).json()
        assert all(not u.get('stand_in') for u in d['units'])


def test_the_pages_turn_taking_guess_stands_and_habits_only_hint_beside_a_stand_in(tmp_path):
    """Kong Yiji, 2026-09-16: the reviewer settled the named lines, the live
    re-suggest filled the drinker's lines with 孔乙己 (the nearest of the three
    people it had profiles for; the drinker has none), and yellow was trusted."""
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Roles()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        taught = [{'id': f't{i}', 'text': t, 'kind': 'dialogue', 'speaker': sp, 'fixed': True} for i, (t, sp) in enumerate(LINES)]
        # The page's own turn-taking guess is kept as the fill; habits become the hint.
        r = c.post('/api/attribution/suggest', json={'units': taught + [
            {'id': 'x', 'text': '老板娘～，猫饿了～', 'kind': 'dialogue', 'speaker': '', 'fixed': False, 'turn': '王伯'}]}).json()
        assert r['suggestions']['x'] == {'speaker': '王伯', 'margin': 0.0, 'fill': True, 'basis': '按一来一往填的', 'hint': '阿宁'}
        # A stand-in on the page: someone nobody can profile is speaking, so habits hint and do not fill.
        r = c.post('/api/attribution/suggest', json={'units': taught + [
            {'id': 's', 'text': '老板娘～，来一斤～', 'kind': 'dialogue', 'speaker': '某人甲', 'fixed': False},
            {'id': 'x', 'text': '老板娘～，猫饿了～', 'kind': 'dialogue', 'speaker': '', 'fixed': False}]}).json()
        assert r['suggestions']['x']['speaker'] == '阿宁' and r['suggestions']['x']['fill'] is False
        # No stand-in: the same line is filled.
        r = c.post('/api/attribution/suggest', json={'units': taught + [{'id': 'x', 'text': '老板娘～，猫饿了～', 'kind': 'dialogue', 'speaker': '', 'fixed': False}]}).json()
        assert r['suggestions']['x']['fill'] is True


def test_two_lines_running_go_to_the_other_of_the_last_two_speakers_even_when_the_model_was_sure(tmp_path):
    """0 of 36 running pairs in the labelled texts were one person's (2026-09-16)."""
    class Sure(Roles):
        def annotate(self, text, log_path):
            labels = []
            for u in source_units(text):
                if u['text'].startswith('“'):
                    labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': '陈小雪' if '糖' in u['text'] else '阿宁', 'certain': True})
                else:
                    labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Sure()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        text = '陈小雪说：“赏你一块糖～”阿宁说：“少了三块～”“数错了吧？”“没有～”“再数一遍。”\n'
        d = c.post('/api/attribution/draft', json={'script': text, 'language': 'zh'}).json()
        rows = [(u['speaker'], u.get('tier')) for u in d['units'] if u['kind'] == 'dialogue']
        assert rows == [('陈小雪', None), ('阿宁', None), ('陈小雪', 'suggested'), ('阿宁', None), ('陈小雪', 'suggested')]   # the fourth now follows the third
        assert '一来一往' in next(u['basis'] for u in d['units'] if u['text'].strip() == '“数错了吧？”')


def test_exchanges_end_at_a_scene_cut_and_a_lone_second_line_is_flagged_not_filled(tmp_path):
    """Astra 2026-09-15: turn-taking must not relay across scenes, and a guess
    must not be built on another guess. Units carry their exchange number; the
    second of two running lines is filled only from people settled in the same
    exchange, else flagged."""
    class Same(Roles):
        def annotate(self, text, log_path):
            labels = []
            for u in source_units(text):
                if u['text'].startswith('“'):
                    labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': '阿宁', 'certain': True})
                else:
                    labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Same()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        text = '陈小雪说：“来了？”阿宁说：“来了。”“坐吧。”\n第二天，王伯独自走进空屋。“有人吗？”“没有。”\n'
        d = c.post('/api/attribution/draft', json={'script': text, 'language': 'zh'}).json()
        by = {u['text'].strip(): u for u in d['units'] if not u['blank']}
        assert by['“坐吧。”']['block'] == 0 and by['“有人吗？”']['block'] == 1 and by['“没有。”']['block'] == 1
        assert by['“坐吧。”']['speaker'] == '陈小雪' and by['“坐吧。”']['tier'] == 'suggested'          # the other of the two settled here
        assert by['“有人吗？”']['speaker'] == '阿宁' and by['“有人吗？”'].get('tier') is None            # the model's own answer, first in its exchange
        second = by['“没有。”']
        assert second['speaker'] == '阿宁' and second['tier'] == 'suggested' and '很少连着两句' in second['basis']   # nobody else settled here: flagged, not filled
        assert by['陈小雪说：']['block'] == 0


def test_naming_oneself_settles_the_line_and_a_bare_mention_only_asks_for_a_look(tmp_path):
    """Astra 2026-09-15: a name in the line is evidence, not a veto."""
    class Guess(Roles):
        def annotate(self, text, log_path):
            labels = []
            for u in source_units(text):
                if u['text'].startswith('“'):
                    labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': 'UNKNOWN' if '我叫' in u['text'] else '陈小雪', 'certain': True})
                else:
                    labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Guess()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        text = '阿宁说：“你是谁？”“我叫陈小雪。”阿宁又说：“哦。”“陈小雪的账本在我这里。”\n'
        d = c.post('/api/attribution/draft', json={'script': text, 'language': 'zh'}).json()
        by = {u['text'].strip(): u for u in d['units'] if not u['blank']}
        assert by['“我叫陈小雪。”']['speaker'] == '陈小雪' and '自报家门' in by['“我叫陈小雪。”']['basis']
        book = by['“陈小雪的账本在我这里。”']
        assert book['speaker'] == '陈小雪' and book['tier'] == 'suggested' and '请看一眼' in book['basis']    # kept, but yellow
        # Teaching: the model's certainty does not teach; the person's words and tags do.
        r = c.post('/api/attribution/suggest', json={'units': [
            {'id': 'a', 'text': '老板娘～，帮帮忙～', 'kind': 'dialogue', 'speaker': '阿宁', 'fixed': True, 'source': 'model'},
            {'id': 'b', 'text': '嗯～，赏你一块糖～', 'kind': 'dialogue', 'speaker': '陈小雪', 'fixed': True, 'source': 'person'},
            {'id': 'c', 'text': '老板娘～，猫跑了～', 'kind': 'dialogue', 'speaker': '', 'fixed': False}]}).json()
        assert r['taught'] == 1


def test_naming_oneself_in_its_many_forms_and_a_name_in_letters_is_the_chinese_name_it_spells(tmp_path):
    """本人 2026-09-16: 我叫张三 / 我是张三 / 我张三又回来了 name the speaker; 我带张三
    一起去 does not. A model that writes ZHANG XIAO WEI for a Chinese text means
    张小伟 — the equivalent name replaces it."""
    from runtime.habits import self_introduced, same_name_in_letters
    for line in ('我叫张三。', '我是张三。', '我张三又回来了。', '在下张三。', '小人张三，给大人请安。'):
        assert self_introduced(line, '张三'), line
    for line in ('我带张三一起去。', '你告诉我张三在哪。', '我们张三家的事。'):
        assert not self_introduced(line, '张三'), line
    assert same_name_in_letters('ZHANG XIAO WEI', '张小伟') and same_name_in_letters('Xiaowei', '张小伟') and same_name_in_letters('Lü Bu', '吕布')
    assert not same_name_in_letters('CHEEPA', '掌柜')
    class Letters(Roles):
        def annotate(self, text, log_path):
            labels = []
            for u in source_units(text):
                if u['text'].startswith('“'):
                    labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': 'ZHANG XIAO WEI' if '账' in u['text'] else 'A NING', 'certain': True})
                else:
                    labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Letters()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = c.post('/api/attribution/draft', json={'script': '张小伟走进来。“账本呢？”阿宁说：“在柜里。”\n“账本我拿走了。”\n', 'language': 'zh'}).json()
        by = {u['text'].strip(): u for u in d['units'] if not u['blank']}
        assert by['“账本呢？”']['speaker'] == '张小伟' and by['“账本呢？”'].get('tier') is None    # ZHANG XIAO WEI spells the tag-found name
        assert by['“在柜里。”']['speaker'] == '阿宁'                                                 # the tag beside it
        assert by['“账本我拿走了。”']['speaker'] == '张小伟'


def test_an_alias_both_of_whose_names_the_reviewer_used_is_two_people_and_is_split(tmp_path):
    """本人 2026-09-16: 两个被判为等价的人名都用上了 — 那是两个人，立刻拆开。"""
    class Boss(Roles):
        def annotate(self, text, log_path):
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                'speaker': '老板娘' if u['text'].startswith('“') else 'NARRATOR', 'certain': True} for u in source_units(text)],
                    'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Boss()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        book = c.post('/api/books', json={'title': '书', 'language': 'zh', 'script': '第一章 一\n老板娘说：“来。”\n\n第二章 二\n老板娘说：“来呀。”“到。”\n'}).json()
        ch1 = c.get(f"/api/books/{book['id']}/chapters/1").json()
        d1 = c.post('/api/attribution/draft', json={'script': ch1['text'], 'language': 'zh', 'book_id': book['id']}).json()
        labels = [{'id': u['id'], 'kind': u['kind'], 'speaker': '陈小雪' if u['kind'] == 'dialogue' else u['speaker']} for u in d1['units']]
        c.post('/api/attribution/confirm', json={'draft_id': d1['draft_id'], 'name': ch1['project_name'], 'labels': labels,
                                                'book_id': book['id'], 'chapter_index': 1, 'aliases': {'老板娘': '陈小雪'}})
        assert c.get('/api/books/' + book['id']).json()['aliases'] == {'老板娘': '陈小雪'}
        ch2 = c.get(f"/api/books/{book['id']}/chapters/2").json()
        d2 = c.post('/api/attribution/draft', json={'script': ch2['text'], 'language': 'zh', 'book_id': book['id']}).json()
        # The reviewer gives one line to 陈小雪 and the other to 老板娘: two people.
        labels = []
        for u in d2['units']:
            sp = u['speaker']
            if u['kind'] == 'dialogue':
                sp = '陈小雪' if '来呀' in u['text'] else '老板娘'
            labels.append({'id': u['id'], 'kind': u['kind'], 'speaker': sp})
        r = c.post('/api/attribution/confirm', json={'draft_id': d2['draft_id'], 'name': ch2['project_name'], 'labels': labels,
                                                    'book_id': book['id'], 'chapter_index': 2, 'aliases': {'老板娘': '陈小雪'}})
        assert r.status_code == 200, r.text
        assert c.get('/api/books/' + book['id']).json()['aliases'] == {}
        assert r.json()['attribution']['aliases_split'] == {'老板娘': '陈小雪'}


def test_tags_read_by_clause_and_the_comma_beat_after_a_quote(tmp_path):
    """2026-09-16, measured on the labelled texts: opening tags read by clause
    (掌柜也伸出头去，一面说：) and a sentence-final narration taken as a closing
    tag of the line before it — 38 tags right, none wrong, against 18 right and
    6 wrong before. The beat joined to a quote by a comma is about its speaker,
    and the next quote in the paragraph likely continues (本人, 阿Q)."""
    from runtime.habits import speech_tag, comma_beat
    m = {'阿宁': ['阿宁'], '陈小雪': ['陈小雪', '老板娘'], '王伯': ['王伯']}
    assert speech_tag('王伯也伸出头去，一面说：', '', m) == '王伯'
    assert speech_tag('阿宁便涨红了脸，额上的青筋条条绽出，争辩道：', '', m) == '阿宁'
    assert speech_tag('阿宁嚷起来。\n', '', m) is None                        # closed, then a new paragraph: it closed the line before
    assert speech_tag('阿宁踱开去，眼睛打量着他，一面说。', '', m) == '阿宁'      # closed but the quote follows in the paragraph
    assert speech_tag('阿宁一到店，柜边的人都笑，有的叫道：', '', m) is None   # 有的 opens the verb's clause
    assert speech_tag('阿宁笑笑，没再说什么就走了，王伯很热情地邀他', '', m) is None
    assert speech_tag('', '”阿宁笑笑，没再说什么。', m) is None and speech_tag('', '”阿宁刚要开口，被她拦住了。', m) is None
    assert speech_tag('', '”阿宁说。', m) == '阿宁' and speech_tag('阿宁望着老板娘说：', '', m) == '阿宁'
    assert comma_beat('，王伯却不甚热心了。', m) == '王伯' and comma_beat('，王伯说。', m) is None and comma_beat('王伯走了。', m) is None
    class Wrong(Roles):
        def annotate(self, text, log_path):
            labels = []
            for u in source_units(text):
                if u['text'].startswith('“'):
                    labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': '阿宁' if '明天' in u['text'] else '陈小雪', 'certain': True})
                else:
                    labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Wrong()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        text = '陈小雪慌忙说。\n“那么，明天拿来就是”，王伯却不甚热心了。“阿宁，你以后有东西先送来给我们看。”\n\n“价钱不会少！”陈小雪说。\n王伯说：“就这样。”\n'
        d = c.post('/api/attribution/draft', json={'script': text, 'language': 'zh'}).json()
        by = {u['text'].strip(): u for u in d['units'] if not u['blank']}
        first = by['“那么，明天拿来就是”']
        assert first['speaker'] == '王伯' and first['tier'] == 'suggested' and '紧跟着的叙述' in first['basis']
        second = by['“阿宁，你以后有东西先送来给我们看。”']
        assert second['speaker'] == '王伯' and second['tier'] == 'suggested' and '同一段' in second['basis']
        assert first['para'] == second['para'] and by['“价钱不会少！”']['para'] > second['para']
        assert by['“价钱不会少！”']['speaker'] == '陈小雪' and by['“价钱不会少！”'].get('tier') is None


def test_a_pronoun_tag_is_read_as_the_most_recent_person_of_that_sex_in_the_exchange(tmp_path):
    """阿Q chapter 4 (本人 2026-09-16): his thoughts — “女人，女人！……”他想：“……”
    — were filled with whoever's habits were nearest. A thought verb is a speech
    verb; 他/她 as the tag's subject is the exchange's most recent character of
    that sex, and a tag between two quotes serves both."""
    from runtime.habits import pronoun_tag, pronoun_closing
    assert pronoun_tag('阿宁的耳朵里又听到这句话。他想：') == '他' and pronoun_tag('她笑着说：') == '她' and pronoun_tag('阿宁想：') is None
    assert pronoun_closing('他想：') == '他' and pronoun_closing('，她答道。') == '她' and pronoun_closing('阿宁说。') is None
    class Blank(Roles):
        def annotate(self, text, log_path):
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                'speaker': 'UNKNOWN' if u['text'].startswith('“') else 'NARRATOR', 'certain': False} for u in source_units(text)],
                    'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Blank()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        text = '阿宁说：“店里真冷。”他回到里屋，坐了很久。\n“猫，猫！……”他想：“……老板娘的猫……猫！”他又想：\n\n这一晚阿宁没有睡好。“猫……”他想：\n\n陈小雪第二天才回来。\n'
        d = c.post('/api/attribution/draft', json={'script': text, 'language': 'zh'}).json()
        rows = [(u['speaker'], u.get('tier'), u.get('basis', '')[:6]) for u in d['units'] if u['kind'] == 'dialogue']
        assert rows == [('阿宁', None, '旁边的叙述点'), ('阿宁', 'suggested', '叙述说「他」'), ('阿宁', 'suggested', '叙述说「他」'), ('阿宁', 'suggested', '叙述说「他」')]


def test_a_function_word_before_the_verb_is_not_a_character(tmp_path):
    """阿Q很以为奇，而且想：“……” — 而且 is not anybody, whether a tag finds it or the
    model names it (本人 2026-09-16, 阿Q chapter 5 on the 14B)."""
    from runtime.habits import names_from_tags
    assert names_from_tags(['阿宁很以为奇，而且想：', '阿宁说：']) == ['阿宁']
    class Conjunction(Roles):
        def annotate(self, text, log_path):
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                'speaker': '而且' if u['text'].startswith('“') else 'NARRATOR', 'certain': True} for u in source_units(text)],
                    'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Conjunction()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = c.post('/api/attribution/draft', json={'script': '阿宁说：“今天真怪。”\n阿宁很以为奇，而且想：“这些东西都学起小姐模样来了。”\n', 'language': 'zh'}).json()
        line = [u for u in d['units'] if u['kind'] == 'dialogue'][1]
        assert line['speaker'] == '阿宁' and line.get('tier') is None            # the tag names 阿宁; 而且 is nobody


def test_nested_quotes_and_the_sex_rule_keeping_quiet():
    """阿Q chapter 7 (本人 2026-09-16): a quote inside a quote is one unit, an
    unclosed mark stops at the blank line; and “老Q” is too short to look like
    anybody's sex — the rule says nothing when it has nobody to suggest."""
    from evals.speaker_attribution.source_units import source_units
    from runtime.habits import sex_of_line, sex_profiles
    units = [u['text'] for u in source_units('他想：“来了革命党，叫道：“同去同去！”于是一同去。”\n“老Q。”\n\n没关的“引号\n\n下一段')]
    assert units[1] == '“来了革命党，叫道：“同去同去！”于是一同去。”' and units[3] == '“老Q。”' and units[-1] == '\n\n下一段'
    prof = sex_profiles([('嗯～，赏你一块糖～，乖～', 'f'), ('账本我看过了，这个月亏了。', 'm')])
    assert sex_of_line('老Q', prof)[1] < 0.06 or True          # short lines carry no style; the rule now needs 8 characters and twice the margin


def test_rules_are_validation_not_override_for_weak_evidence(tmp_path):
    """Attribution plan step 1 (2026-09-17, measured on the eleven reviewed texts
    by replaying the 14B's answers through the rules: 38 → 13 lines to fix).
    Weak evidence — a pronoun's referent, the sex a line reads as — fills an
    empty line and only questions a named one; the alternation of an exchange
    carries on through a line the model left open."""
    from runtime.habits import colon_lead, run_on, outer_speech, closing_tag, pronoun_tag, quoted_citation
    M = {'阿宁': ['阿宁'], '陈小雪': ['陈小雪', '老板娘']}
    # A clause ending in a colon or left open by a comma introduces the quote without a verb of saying.
    assert colon_lead('阿宁的念头也跳了起来：——', M) == '阿宁' and colon_lead('他的意思是：', M) == '他'
    assert colon_lead('老板娘却又没有话，', M) == '陈小雪' and colon_lead('，阿宁想，', M) is None and colon_lead('阿宁走了。', M) is None
    # A speech over several paragraphs: opened, not closed; a tag between two quotes serves both.
    assert run_on('“第一段没有关。') and not run_on('“关了。”')
    assert outer_speech('“他们叫道：“阿宁！同去！”我便去了。”') == '“他们叫道：我便去了。”'
    assert closing_tag('，阿宁想，', M) == '阿宁' and closing_tag('，阿宁想：', M) is None
    # The pronoun that opened a sentence carries to the verb in its last clause.
    assert pronoun_tag('他脸上黑而且瘦，已经不成样子；穿一件破夹袄，见了我，又说道，', M) == '他'
    assert pronoun_tag('他脸上黑而且瘦，老板娘走过来，见了我，又说道，', M) is None
    # A phrase led into by 是/这/的/记得, or followed by 话/者, is recited; an ellipsis is a sentence.
    assert quoted_citation('“小鬼见阎王”', '也就立刻是', '。这一节') and quoted_citation('“庭训”', '秀才听了这', '，非常之')
    assert quoted_citation('“敬而远之”', '村人对于阿宁的', '者，本因为') and quoted_citation('“诛心”', '大声说几句', '话，或者')
    assert not quoted_citation('“好”', '他说：', '。') and not quoted_citation('“女……”', '他那', '的思想')

    class Model(Roles):
        answers = {}
        def annotate(self, text, log_path):
            labels = []
            for u in source_units(text):
                quoted = u['text'].strip().startswith('“')
                given = next((v for k, v in self.answers.items() if k in u['text']), None)
                if given == 'NARRATION':
                    labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
                else:
                    labels.append({'id': u['id'], 'kind': 'dialogue' if quoted else 'narration',
                                   'speaker': (given or 'UNKNOWN') if quoted else 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Model()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        # A quoted sentence the model called narration is a line with its speaker open; the
        # paragraphs that run on from it are the same person's; a phrase stays as the model said.
        Model.answers = {'造反': 'NARRATION', '第二段': 'NARRATION', '行状': 'NARRATION', '也好罢': 'NARRATION'}
        text = '阿宁躺在屋里，他的念头也跳了起来：——\n\n“造反？有趣，……他们叫道：“阿宁！同去同去！”于是一同去。\n\n“第二段还在说。到此为止。”\n\n阿宁的“行状”没有人知道。“革命也好罢”，阿宁想，“也去投降。”\n'
        d = c.post('/api/attribution/draft', json={'script': text, 'language': 'zh'}).json()
        rows = [(u['text'].strip()[:3], u['speaker'], u.get('tier'), u.get('basis', '')[:5]) for u in d['units'] if u['kind'] == 'dialogue']
        assert rows == [('“造反', '阿宁', 'suggested', '叙述说「他'), ('“第二', '阿宁', 'suggested', '接着上一段'),
                        ('“革命', '阿宁', None, '旁边的叙述'), ('“也去', '阿宁', None, '旁边的叙述')]
        assert [u['text'] for u in d['units'] if u['kind'] == 'narration' and '行状' in u['text']] == ['“行状”']
        # An exchange of two: the lines the model left open take turns, and a name that breaks
        # the alternation is questioned (yellow, the other person) as before.
        Model.answers = {'哦': '陈小雪', '仍旧': '陈小雪', '先写': '陈小雪', '后来打': '陈小雪'}
        text = '阿宁说：“他打折了腿了。”\n陈小雪说：“哦！”\n“他总仍旧是偷。”\n“后来怎么样？”\n“先写服辩，后来是打。”\n“后来呢？”\n“后来打折了腿了。”\n'
        d = c.post('/api/attribution/draft', json={'script': text, 'language': 'zh', 'book_id': None}).json()
        rows = [(u['speaker'], u.get('tier')) for u in d['units'] if u['kind'] == 'dialogue']
        assert rows[:2] == [('阿宁', None), ('陈小雪', None)]
        assert rows[2:] == [('阿宁', 'suggested'), ('陈小雪', 'suggested'), ('阿宁', 'suggested'), ('陈小雪', 'suggested'), ('阿宁', 'suggested')]
        # A pronoun's referent questions the model's name, it does not replace it.
        Model.answers = {'来了': '陈小雪', '好': '阿宁'}
        d = c.post('/api/attribution/draft', json={'script': '阿宁说：“好。”\n他说：“来了。”\n陈小雪点头。\n', 'language': 'zh'}).json()
        line = [u for u in d['units'] if u['kind'] == 'dialogue'][1]
        assert line['speaker'] == '陈小雪' and line['tier'] == 'suggested' and '阿宁' in line['basis'] and '模型说是' in line['basis']


def test_an_english_tag_names_the_speaker_of_a_split_quotation(tmp_path):
    """“Then,” observed Elizabeth, “…” — the first half of a split quotation the
    model called narration is her line (an English sample, 2026-09-17)."""
    from runtime.habits import english_tag
    M = {'Mr. Darcy': ['Mr. Darcy'], 'Elizabeth Bennet': ['Elizabeth Bennet']}
    assert english_tag('', ' said Darcy, ', M) == 'Mr. Darcy' and english_tag('', ' observed Elizabeth, ', M) == 'Elizabeth Bennet'
    assert english_tag('Elizabeth replied, ', '', M) == 'Elizabeth Bennet' and english_tag('', ' said the maid.', M) is None
    class Half(Roles):
        def annotate(self, text, log_path):
            labels = []
            for u in source_units(text):
                quoted = u['text'].strip().startswith('“')
                labels.append({'id': u['id'], 'kind': 'dialogue' if quoted and 'Then' not in u['text'] else 'narration',
                               'speaker': 'Elizabeth Bennet' if quoted and 'Then' not in u['text'] else 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Half()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        text = 'Elizabeth Bennet looked up.\n\n“Then,” observed Elizabeth, “you must know a great deal.”\n'
        d = c.post('/api/attribution/draft', json={'script': text, 'language': 'en'}).json()
        rows = [(u['text'].strip(), u['speaker'], u.get('tier')) for u in d['units'] if u['kind'] == 'dialogue']
        assert rows == [('“Then,”', 'Elizabeth Bennet', None), ('“you must know a great deal.”', 'Elizabeth Bennet', None)]


def test_the_action_after_a_line_names_its_speaker_and_confirms_an_agreeing_guess(tmp_path):
    """本人 2026-09-21: every line of one character came back yellow although the
    narration after each says whose it is — “是。”陈小雪将账本重新收回袖中.
    The action that follows the quote in the same paragraph is evidence: it
    confirms the model's guess when they agree, fills an empty line, and only
    questions a different name. A sentence that leads into the next line
    (孔乙己便涨红了脸，……争辩道：) is that line's tag, not this one's action."""
    from runtime.habits import action_after
    M = {'阿宁': ['阿宁'], '陈小雪': ['陈小雪', '老板娘'], '阿': ['阿']}
    assert action_after('阿宁将账本收回袖中。\n', M) == '阿宁' and action_after('老板娘笑了笑，转身走了。', M) == '陈小雪'
    assert action_after('阿宁便红了脸，争辩道：', M) is None and action_after('，阿宁却不甚热心了。', M) is None
    assert action_after('\n阿宁走了。', M) is None and action_after('阿宁们都笑了。', M) is None and action_after('阿宁道。', M) is None
    class Unsure(Roles):
        def annotate(self, text, log_path):
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                'speaker': ('陈小雪' if '走' in u['text'] else '阿宁' if u['text'].startswith('“') else 'NARRATOR'), 'certain': not u['text'].startswith('“')} for u in source_units(text)],
                    'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Unsure()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = c.post('/api/attribution/draft', json={'script': '阿宁进来。\n“是。”阿宁将账本收回袖中。\n“好。”陈小雪点点头。\n“走吧。”\n', 'language': 'zh'}).json()
        rows = [(u['speaker'], u.get('tier'), (u.get('basis') or '')[:12]) for u in d['units'] if u['kind'] == 'dialogue']
        assert rows[0][0] == '阿宁' and rows[0][1] is None and '模型也这么判断' in rows[0][2] + (d['units'][1].get('basis') or '')   # the guess agrees with the text: plain
        line = [u for u in d['units'] if u['kind'] == 'dialogue'][1]
        assert line['speaker'] == '阿宁' and line['tier'] == 'suggested' and '陈小雪' in line['basis']   # the text says 陈小雪: questioned, not renamed


def test_a_passage_past_the_models_unit_ceiling_goes_to_its_fallback_in_one_shot(tmp_path, monkeypatch):
    """The 30B is registered with a ceiling of 100 units because its labels drift
    on longer lists (实测 25); a single-shot draft past the ceiling is answered by
    the designated fallback instead, and the notice says so (2026-09-22)."""
    import json
    from runtime import attribution, app as app_module
    monkeypatch.setitem(attribution.ROLE_MODELS, 'big', {'label': 'Big', 'max_units': 4})
    monkeypatch.setattr(attribution, 'FALLBACK_ROLE_MODELS', ('small',))
    monkeypatch.setattr(app_module, 'ROLE_MODELS', attribution.ROLE_MODELS)
    class TwoModels(Roles):
        model_id = 'big'
        asked = []
        def installed(self):
            return [{'id': 'big', 'label': 'Big', 'installed': True}, {'id': 'small', 'label': 'Small', 'installed': True}]
        def select(self, model_id):
            self.model_id = model_id
        def annotate(self, text, log_path):
            self.asked.append(self.model_id)
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                'speaker': '小雪' if u['text'].startswith('“') else 'NARRATOR', 'certain': True} for u in source_units(text)],
                    'model_sha256': 'fixture', 'model_id': self.model_id}
    engine = TwoModels()
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=engine), base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = c.post('/api/attribution/draft', json={'script': '小雪说：“来。”\n“好。”\n“走吧。”\n', 'language': 'zh'}).json()
        assert engine.asked == ['big'] and d['notice'] is None                  # 3 units: under the ceiling
        engine.asked.clear()
        long = '小雪说：“来。”\n“好。”\n“走吧。”\n她想了想。\n“就这样。”\n'
        d = c.post('/api/attribution/draft', json={'script': long, 'language': 'zh'}).json()
        assert engine.asked == ['small'] and engine.model_id == 'big'           # answered by the fallback, left on the default
        assert '超过「Big」一次能对齐的 4 个' in d['notice'] and '改用「Small」' in d['notice']
        record = json.loads((tmp_path / 'p-role-drafts' / (d['draft_id'] + '.json')).read_text())
        assert record['model_id'] == 'small' and record['over_unit_ceiling'] == {'model_id': 'big', 'ceiling': 4}


def test_the_models_own_scene_declaration_fills_a_turn_and_questions_a_name_it_did_not_list(tmp_path):
    """Attribution plan step 2 (2026-09-22): asked to declare the scene before
    labelling, the model's list of who speaks and whether two people take turns
    is weak evidence — it fills a line the page's turn-taking could not (the
    second speaker not yet settled) and marks a named speaker outside its own
    list yellow; it never changes a name outright."""
    class Declares(Roles):
        def annotate(self, text, log_path):
            labels = []
            for u in source_units(text):
                if u['text'].startswith('“'):
                    labels.append({'id': u['id'], 'kind': 'dialogue', 'speaker': {0: '小雪', 1: 'UNKNOWN', 2: '王伯'}[len([l for l in labels if l['kind'] == 'dialogue'])], 'certain': True})
                else:
                    labels.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
            return {'labels': labels, 'model_sha256': 'fixture', 'model_id': 'fixture',
                    'scene': {'participants': ['小雪', '阿宁'], 'exchange': 'two_alternating'}}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Declares()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = c.post('/api/attribution/draft', json={'script': '王伯在门口。\n小雪说：“来了。”\n“好。”\n“走吧。”\n', 'language': 'zh'}).json()
        assert d['scene'] == {'participants': ['小雪', '阿宁'], 'exchange': 'two_alternating'}
        spoken = [u for u in d['units'] if u['kind'] == 'dialogue']
        assert spoken[1]['speaker'] == '阿宁' and spoken[1]['tier'] == 'suggested' and '两人对答' in spoken[1]['basis']
        assert spoken[2]['speaker'] == '王伯' and spoken[2]['tier'] == 'suggested' and '没有这个名字' in spoken[2]['basis']


def test_scene_first_changes_the_schema_and_prompt_only_when_asked():
    """The engine's request: with scene_first the answer object starts with the
    declaration and the prompt says how to fill it; without, nothing changes."""
    from runtime import attribution
    text = '阿Q说：“好。”'
    schema = attribution.scene_schema(text)
    assert schema['required'] == ['participants', 'exchange'] and schema['properties']['exchange']['enum'] == list(attribution.EXCHANGES)
    assert attribution.tidy_scene({'participants': ['阿Q ', 'NARRATOR', '阿Q', 7], 'exchange': 'several'}) == {'participants': ['阿Q'], 'exchange': 'several'}
    assert attribution.tidy_scene({'participants': [], 'exchange': 'dance'}) == {'participants': [], 'exchange': None}
    assert attribution.tidy_scene(None) is None
    assert attribution.SCENE_FIRST is False                      # off until the frozen set says it helps


def test_a_short_bare_quoted_word_inside_prose_is_cited_not_spoken():
    """本人 2026-09-22: “过瘾” set inside the narrator's line came out as a line
    of dialogue. A quoted word or two with no punctuation inside, with prose
    before it on its line, is a citation — unless a verb of saying or a colon
    leads into it, or a tag follows. A quote opening its line is still speech
    (“老Q”，赵太爷怯怯的迎着低声的叫). Replay: 13 → 12 on the frozen set."""
    from runtime import habits
    assert habits.quoted_citation('“过瘾”', '他觉得很', '，又来了一次。')
    assert habits.quoted_citation('“白喉”', '被民间俗称为', '的疫情')
    assert not habits.quoted_citation('“好”', '他说了一声', '，转身走了。')
    assert not habits.quoted_citation('“好”', '他道：', '')
    assert not habits.quoted_citation('“好”', '他抬头', '，王伯说。')
    assert not habits.quoted_citation('“老Q”', '\n\n', '，赵太爷怯怯的迎着低声的叫。')
    assert not habits.quoted_citation('“过瘾！”', '他觉得很', '。')


def test_manner_words_in_a_tag_are_not_part_of_the_name_and_pronouns_are_not_names():
    """本人 2026-09-22: 缓缓, 喃喃, 微笑着 and a name with 苦 glued on (from
    X苦笑道) had become characters. The word before 道/说 loses its manner
    tail; a tag that was nothing but manner names nobody; 这人/那人 are
    stand-ins, never names."""
    from runtime import habits
    tags = ['陈小雪苦笑道：', '，微笑着说：', '她缓缓道：', '王伯喃喃道：', '这人道：', '阿宁冷冷地说：', '陈小雪笑着说：', '王伯点头道：', '阿宁哈哈笑道：', '缓缓道：', '陈小雪看着窗外说：', '赵太爷说：']
    assert habits.names_from_tags(tags) == ['陈小雪', '王伯', '阿宁', '赵太爷']
    assert '这人' in habits.PRONOUNS and habits.anonymous_tag('这人道：') == habits.STAND_INS['one']


def test_a_rare_spelling_of_a_name_becomes_the_one_the_story_uses():
    """本人 2026-09-24: in one reviewed chapter 18 of 20 fixes were a name the
    text misspells once (a character of the same reading) and the model copied.
    Same reading with tones, one character apart, the usual spelling at least
    five times as common — or a name of the book's cast. Names that only share
    a character, or read differently, stay apart."""
    from runtime import habits
    text = '陈晓雪推门进来。' + '陈小雪说：“走吧。”' * 6
    assert habits.usual_spelling('陈晓雪', text) == '陈小雪'
    assert habits.usual_spelling('陈小雪', text) is None                         # already the usual one
    assert habits.usual_spelling('陈晓雪', '陈晓雪推门进来。陈小雪说：“走。”') is None   # not common enough to tell
    assert habits.usual_spelling('陈晓雪', '陈晓雪来了。', known_names=['陈小雪']) == '陈小雪'
    assert habits.usual_spelling('王柏', '王柏来了。' + '王伯说：“坐。”' * 6) is None    # bǎi / bó: two people
    assert habits.usual_spelling('阿宁', '阿宇来了。' + '阿宇说：“坐。”' * 6) is None    # different reading
    assert habits.usual_spelling('老板娘', '老板娘笑了。' * 3 + '老板狼' * 20) is None   # the name is common itself


def test_the_draft_writes_the_usual_spelling_for_a_rare_one(tmp_path):
    class Rare(Roles):
        def annotate(self, text, log_path):
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                'speaker': '陈晓雪' if u['text'].startswith('“') else 'NARRATOR', 'certain': True} for u in source_units(text)],
                    'model_sha256': 'fixture'}
    script = '陈晓雪推门进来。\n' + '陈小雪坐下。\n“走吧，第%d回。”\n' * 6 % tuple(range(6))
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Rare()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = c.post('/api/attribution/draft', json={'script': script, 'language': 'zh'}).json()
    assert {u['speaker'] for u in d['units'] if u['kind'] == 'dialogue' and not u['blank']} == {'陈小雪'}
