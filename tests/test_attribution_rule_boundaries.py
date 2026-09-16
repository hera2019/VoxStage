"""Self-written boundary regressions, independent of manuscript score targets."""
import pytest
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine
from runtime.attribution import source_units
from runtime.habits import quoted_citation, speech_tag, names_from_tags
from tests.test_attribution_import import Roles, HEADERS


@pytest.mark.parametrize('text,before,after,citation', [
    ('“好”', '林青说', '，随后转身离开。', False),
    ('“请进”', '', '\n\n', False),
    ('“越来越冷”', '林青连说着', '，一同走了。', False),
    ('“回来呀”', '林青说：', '', False),
    ('“量力而行”', '什么', '，什么', True),
    ('“山高水长”', '从描红纸上的', '这几个字里，取了一个别名。', True),
    ('“喵”', '剩下一个', '字。', True),
    ('“暂停营业”', '门口挂着', '。', True),
    ('“门口根本没有人贴过告示”', '但自从周明说了', '这话以后，他便生气了。', True),
    ('“坏人”', '林青曾骂周明是', '，后来后悔了。', True),
    ('“书生”', '他们时常叫他', '。', True),
    ('“明白！”', '林青说：', '', False),
])
def test_citation_needs_context(text, before, after, citation):
    assert quoted_citation(text, before, after) is citation


@pytest.mark.parametrize('before,after,expected', [
    ('', '林青一路点头，说道', None),
    ('', '\n\n林青说。', None),
    ('', '林青说：后来周明回来了。', None),
    ('', '林青说。随后周明走进来，说道', '林青'),
    ('', '林青说。', '林青'),
    ('林青一路走来，坐着吃饭的人站起身，拿着筷子说，', '', None),
    ('林青回来，看见他的朋友很高兴，问他说，', '', None),
    ('林青们连忙招呼，周先生也笑着说', '', None),
    ('林青嫂笑着说', '', '林青嫂'),
    ('', '周明嚷着要添饭。林青伸手去拦，大喝道，', None),
    ('林青望着周明说：', '', '林青'),
    ('林青也伸出头去，一面说：', '', '林青'),
])
def test_speech_tags_do_not_cross_subjects_or_paragraphs(before, after, expected):
    assert speech_tag(before, after, {'林青':['林青'], '林青嫂':['林青嫂'], '周明':['周明']}) == expected


def test_cached_good_answers_survive_rule_boundaries(tmp_path):
    text = ('林青来到门口，坐着吃饭的人站起身，说，'
            '“林青，进来坐！”林青点头，说道“好”'
            '，随后周明过来。\n\n'
            '林青回来，看见他的朋友周明很高兴，问他说，'
            '“路上顺利吗？”\n\n'
            '周明拉着他的手，连说着“越来越冷”，一起进屋了。')
    assigned = {'“林青，进来坐！”':'坐着吃饭的人', '“好”':'林青',
                '“路上顺利吗？”':'周明', '“越来越冷”':'周明'}
    class Cached(Roles):
        def annotate(self, script, log_path):
            return {'model_sha256':'fixture', 'labels':[
                {'id':u['id'], 'kind':'dialogue' if u['text'] in assigned else 'narration',
                 'speaker':assigned.get(u['text'], 'NARRATOR'), 'certain':True}
                for u in source_units(script)]}
    with TestClient(create_app(tmp_path/'p', FixtureEngine(), role_engine=Cached()),
                    base_url='http://127.0.0.1', headers=HEADERS) as client:
        r = client.post('/api/attribution/draft', json={'script':text, 'language':'zh'})
        assert r.status_code == 200, r.text
        data = r.json()
        assert ''.join(u['text'] for u in data['units']) == text
        for u in data['units']:
            if u['text'] in assigned:
                assert (u['kind'], u['speaker']) == ('dialogue', assigned[u['text']])
        assert client.get('/api/projects').json() == []


def test_tag_name_must_not_include_a_preposition_and_addressee():
    assert names_from_tags(['林青对我说：', '林青说：']) == ['林青']
