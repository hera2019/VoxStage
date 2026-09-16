"""Integration checks of source retention and review handoff, not role accuracy scores."""
import json
import pytest
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine
from runtime.attribution import source_units

HEADERS={'X-VoxStage':'1'}
class Roles:
    ready=True
    broken=False
    def annotate(self,text,log_path):
        units=source_units(text)
        labels=[{'id':u['id'],'kind':'dialogue' if u['text'].startswith(('“','"')) else 'narration',
                 'speaker':'UNKNOWN' if u['text'].startswith(('“','"')) else 'NARRATOR'} for u in units]
        if self.broken:labels=labels[:-1]
        return {'labels':labels,'model_sha256':'fixture'}

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/'projects',FixtureEngine(),role_engine=Roles()),base_url='http://127.0.0.1',headers=HEADERS) as c:
        yield c

def draft(client,text='小雪看着窗外。“雨停了吗？”她问。',language='zh'):
    response=client.post('/api/attribution/draft',json={'script':text,'language':language})
    assert response.status_code==200,response.text
    return response.json()

def confirm(client,d):
    return client.post('/api/attribution/confirm',json={'draft_id':d['draft_id'],'name':'角色草稿接入检查',
        'labels':[{k:u[k] for k in ('id','kind','speaker')} for u in d['units']]})

@pytest.mark.parametrize('language,text',[('zh','小雪看着窗外。“雨停了吗？”她问。'),('en','Mira looked outside. "Has the rain stopped?" she asked.')])
def test_review_source_reopen_and_render(client,language,text):
    d=draft(client,text,language)
    assert client.get('/api/projects').json()==[]
    assert ''.join(u['text'] for u in d['units'])==text
    assert confirm(client,d).status_code==400
    for u in d['units']:
        if u['kind']=='dialogue':u['speaker']='小雪' if language=='zh' else 'Mira'
    response=confirm(client,d);assert response.status_code==200,response.text
    p=response.json();saved=client.app.state.store.read(p['id'])
    assert saved['source_script']==text and saved['attribution']['human_confirmed'] is True
    assert ''.join(s['text'] for s in p['segments'])==text
    assert all(s['text']==text[s['source_start']:s['source_end']] for s in p['segments'])
    assert client.get('/api/projects/'+p['id']).json()['segments']==p['segments']
    response=client.post('/api/projects/'+p['id']+'/render/start',json={'revision':p['revision']})
    assert response.status_code==200,response.text

def test_changed_kind_alias_and_missing_duplicate_ids(client):
    d=draft(client)
    for u in d['units']:u.update(kind='dialogue',speaker='小雪')
    invalid={**d,'units':d['units'][:-1]}
    assert confirm(client,invalid).status_code==400
    invalid={**d,'units':[d['units'][0]]*len(d['units'])}
    assert confirm(client,invalid).status_code==400
    p=confirm(client,d).json();assert set(p['voices'])=={'小雪'}
    assert all(s['kind']=='dialogue' for s in p['segments'])

def test_source_never_comes_from_confirm_body(client):
    d=draft(client,'窗外很安静。')
    d['units'][0]['text']='替换后的恶意文本'
    p=confirm(client,d).json();assert p['segments'][0]['text']=='窗外很安静。'

def test_long_unit_is_split_without_losing_source(client):
    text='这是一段没有引号的原文。'*20
    d=draft(client,text);p=confirm(client,d).json()
    assert ''.join(s['text'] for s in p['segments'])==text
    assert all(len(s['text'])<=60 for s in p['segments'])

def test_rejects_cross_origin_and_over_limit(client):
    assert client.post('/api/attribution/draft',json={'script':'a'*3001,'language':'en'}).status_code==400   # over this machine's tier (capacity.py); tests pin it at 3,000
    assert client.post('/api/attribution/draft',json={'script':'a'*12001,'language':'en'}).status_code==422  # over any tier
    assert client.post('/api/attribution/draft',headers={'Origin':'https://example.com'},json={'script':'Hi','language':'en'}).status_code==403

def test_invalid_model_labels_release_queue(tmp_path):
    roles=Roles();roles.broken=True
    with TestClient(create_app(tmp_path/'projects',FixtureEngine(),role_engine=roles),base_url='http://127.0.0.1',headers=HEADERS) as c:
        assert c.post('/api/attribution/draft',json={'script':'原文。','language':'zh'}).status_code==400
        roles.broken=False
        assert c.post('/api/attribution/draft',json={'script':'原文。','language':'zh'}).status_code==200

# 最后更新：2026-09-10 · Astra


def test_a_drafted_name_loses_a_trailing_speech_verb_but_keeps_short_names():
    """The draft model returned 众人都道 for a line introduced by 众人都道：."""
    from runtime.attribution import tidy_speaker
    assert tidy_speaker('众人都道') == '众人'
    assert tidy_speaker('宝玉道') == '宝玉'
    assert tidy_speaker('袭人笑道') == '袭人'
    assert tidy_speaker('宝玉因说') == '宝玉'
    # Two characters have to survive, so a real name ending in 道 is left alone.
    assert tidy_speaker('张道') == '张道'
    assert tidy_speaker('道') == '道'
    assert tidy_speaker('晴雯') == '晴雯'
    assert tidy_speaker('  宝玉  ') == '宝玉'
    assert tidy_speaker('') == ''


def test_a_name_the_story_never_uses_is_handed_back_as_unresolved(tmp_path):
    """The model wrote ME for 我 and WU DI for 吴迪. WU DI spells a name in the
    text and becomes it (本人 2026-09-16: 等价人名); a name that spells nothing
    there is handed back unresolved."""
    class Romanising(Roles):
        def annotate(self, text, log_path):
            units = source_units(text)
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                'speaker': self.name if u['text'].startswith('“') else 'NARRATOR'} for u in units],
                    'model_sha256': 'fixture'}
    engine = Romanising()
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=engine),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        engine.name = 'THE BOSS'
        d = draft(c, '吴迪看着我。“别干了，好吗？”')
        quoted = next(u for u in d['units'] if u['text'].startswith('“'))
        assert quoted['speaker'] == 'UNKNOWN' and quoted['suggested'] == 'THE BOSS'
        engine.name = 'WU DI'
        d = draft(c, '吴迪看着我。“别干了，好吗？”')
        quoted = next(u for u in d['units'] if u['text'].startswith('“'))
        assert quoted['speaker'] == '吴迪' and 'suggested' not in quoted
        # A name that is in the text passes through untouched.
        engine.name = '吴迪'
        d = draft(c, '吴迪看着我。“别干了，好吗？”')
        quoted = next(u for u in d['units'] if u['text'].startswith('“'))
        assert quoted['speaker'] == '吴迪' and 'suggested' not in quoted


def test_an_unquoted_unit_in_a_quoted_text_is_prose_whatever_the_model_says(tmp_path):
    """掌柜说： is not the shopkeeper speaking. 27 of 27 reviewed cases agreed."""
    class TagAsSpeech(Roles):
        def annotate(self, text, log_path):
            units = source_units(text)
            return {'labels': [{'id': u['id'], 'kind': 'dialogue', 'speaker': '掌柜'} for u in units],
                    'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=TagAsSpeech()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = draft(c, '掌柜说：“孔乙己么？你还欠十九个钱呢！”')
        prose, quote = d['units'][0], d['units'][1]
        assert prose['kind'] == 'narration' and prose['suggested'] == '掌柜'
        assert quote['kind'] == 'dialogue' and quote['speaker'] == '掌柜'
        # A text with no quotation marks at all is not touched by this rule.
        d = draft(c, '掌柜说孔乙己还欠十九个钱呢。')
        assert d['units'][0]['kind'] == 'dialogue'


def test_citation_context_keeps_quoted_terms_in_narration(tmp_path):
    """Citation cues keep quoted terms in prose; brevity alone does not."""
    class Everything(Roles):
        def annotate(self, text, log_path):
            units = source_units(text)
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                'speaker': '孔乙己' if u['text'].startswith('“') else 'NARRATOR'} for u in units],
                    'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Everything()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = draft(c, '接连便是难懂的话，什么“君子固穷”，什么“者乎”之类。孔乙己说：“温一碗酒。”')
        by = {u['text'].strip(): u for u in d['units']}
        assert by['“君子固穷”']['kind'] == 'narration' and by['“君子固穷”']['suggested'] == '孔乙己'
        assert by['“者乎”']['kind'] == 'narration'
        assert by['“温一碗酒。”']['kind'] == 'dialogue' and by['“温一碗酒。”']['speaker'] == '孔乙己'
        # Confirming as drafted folds the cited words back into their sentence.
        labels = [{'id': u['id'], 'kind': u['kind'], 'speaker': u['speaker']} for u in d['units']]
        p = c.post('/api/attribution/confirm', json={'draft_id': d['draft_id'], 'name': '引述', 'labels': labels}).json()
        assert any('什么“君子固穷”，什么“者乎”之类' in s['text'] for s in p['segments'])
        # Speech that ends in a wave dash, a comma or a particle, or runs long, is
        # not a citation even without a sentence-final mark (本人 2026-09-14:
        # “喜欢～，好滑呀～” had been silenced into narration).
        d = draft(c, '她说：“喜欢～，好滑呀～”他说：“嗯～”她又说：“可能是吧”门口挂着“今天不营业”。')
        by = {u['text'].strip(): u for u in d['units']}
        assert by['“喜欢～，好滑呀～”']['kind'] == 'dialogue'
        assert by['“嗯～”']['kind'] == 'dialogue'
        assert by['“可能是吧”']['kind'] == 'dialogue'
        assert by['“今天不营业”']['kind'] == 'narration'


def test_the_citation_rule_is_chinese_only(tmp_path):
    """English speech carries a comma inside the quotes before a tag; 11 of the
    26 quoted units in the Austen sample would be misread as citations."""
    class Speech(Roles):
        def annotate(self, text, log_path):
            units = source_units(text)
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('"') else 'narration',
                                'speaker': 'Mr. Bennet' if u['text'].startswith('"') else 'NARRATOR'} for u in units],
                    'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Speech()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = draft(c, '"I know," said Mr. Bennet, "and I am glad of it."', language='en')
        quoted = [u for u in d['units'] if u['text'].startswith('"')]
        assert all(u['kind'] == 'dialogue' and u['speaker'] == 'Mr. Bennet' for u in quoted)


def test_a_draft_that_calls_every_quoted_line_narration_falls_back_to_the_quotes(tmp_path):
    """2026-09-14: on an explicit chapter the model labelled all 70 units NARRATOR.
    The reviewer gets the structural draft — quotes are speech, speaker blank —
    and a notice, instead of sixty rows to flip by hand."""
    class Balks(Roles):
        def annotate(self, text, log_path):
            return {'labels': [{'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR'} for u in source_units(text)],
                    'model_sha256': 'fixture'}
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=Balks()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        d = draft(c, '她说：“喜欢～，好滑呀～”\n他说：“嗯～”\n她笑了。“可能是吧～”门口挂着“今天不营业”。')
        assert d['notice'] and '留空' in d['notice'] and '4 句引号' in d['notice']     # the line breaks are not quotes
        assert all(u['kind'] == 'narration' for u in d['units'] if u['blank']), '空白单元不能变成待指定的对白'
        by = {u['text'].strip(): u for u in d['units'] if not u['blank']}
        assert by['“喜欢～，好滑呀～”']['kind'] == 'dialogue' and by['“喜欢～，好滑呀～”']['speaker'] == 'UNKNOWN'
        assert by['“嗯～”']['kind'] == 'dialogue' and by['“可能是吧～”']['kind'] == 'dialogue'
        assert by['“今天不营业”']['kind'] == 'narration'          # a citation stays prose
        assert by['她笑了。']['kind'] == 'narration'
        # Two quoted units are too few to call the model's answer degenerate.
        d = draft(c, '她笑了。“好。”他说。')
        assert d['notice'] is None
