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
    assert client.post('/api/attribution/draft',json={'script':'a'*3001,'language':'en'}).status_code==422
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
    """The model wrote ME for 我 and WU DI for 吴迪. Neither is in the text."""
    class Romanising(Roles):
        def annotate(self, text, log_path):
            units = source_units(text)
            return {'labels': [{'id': u['id'], 'kind': 'dialogue' if u['text'].startswith('“') else 'narration',
                                'speaker': self.name if u['text'].startswith('“') else 'NARRATOR'} for u in units],
                    'model_sha256': 'fixture'}
    engine = Romanising()
    with TestClient(create_app(tmp_path / 'p', FixtureEngine(), role_engine=engine),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        engine.name = 'WU DI'
        d = draft(c, '吴迪看着我。“别干了，好吗？”')
        quoted = next(u for u in d['units'] if u['text'].startswith('“'))
        assert quoted['speaker'] == 'UNKNOWN' and quoted['suggested'] == 'WU DI'
        # A name that is in the text passes through untouched.
        engine.name = '吴迪'
        d = draft(c, '吴迪看着我。“别干了，好吗？”')
        quoted = next(u for u in d['units'] if u['text'].startswith('“'))
        assert quoted['speaker'] == '吴迪' and 'suggested' not in quoted
