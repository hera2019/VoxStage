"""Behavioral acceptance for the local workflow. Astra, 2026-09-09."""
import json
import threading
import time
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.audio import process_audio, timestamp
from runtime.engines import FixtureEngine

ROOT = Path(__file__).resolve().parent.parent
HEADERS = {'X-VoxStage':'1'}

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, FixtureEngine()), base_url='http://127.0.0.1:8765', headers=HEADERS) as client:
        yield client

def create(client, language='zh', script=None):
    response = client.post('/api/projects', json={'name':'Test', 'language':language,
            'script':script or (ROOT/'examples'/f'{language}.txt').read_text()})
    assert response.status_code == 200, response.text
    return response.json()

def wait(client, pid):
    for _ in range(500):
        p = client.get('/api/projects/'+pid).json()
        if p['job']['status'] != 'running':
            return p
        time.sleep(.01)
    raise AssertionError('Render did not finish')

def generate(client, p, **extra):
    response = client.post(f'/api/projects/{p["id"]}/render/start', json={'revision':p['revision'], **extra})
    assert response.status_code == 200, response.text
    return wait(client, p['id'])

@pytest.mark.parametrize('language',['zh','en'])
def test_roundtrip_cache_timeline_and_export(client, language):
    p = generate(client, create(client, language))
    assert all(s['status']=='ready' for s in p['segments'])
    root = client.app.state.store.directory(p['id'])
    originals = {s['id']:(s['audio']['fingerprint'], (root/'audio'/(s['audio']['fingerprint']+'.wav')).stat().st_mtime_ns) for s in p['segments']}
    first = p['segments'][0]
    response = client.patch('/api/projects/'+p['id'], json={'revision':p['revision'], 'segment_id':first['id'], 'text':first['text']+'!'} )
    assert response.status_code == 200
    edited = response.json()
    assert [s['status'] for s in edited['segments']] == ['pending','ready','ready','ready']
    assert client.post(f'/api/projects/{p["id"]}/export/create', json={'revision':edited['revision']}).status_code==400
    p = generate(client, edited)
    assert p['segments'][0]['audio']['fingerprint']!=originals[first['id']][0]
    for s in p['segments'][1:]:
        digest, mtime = originals[s['id']]
        assert s['audio']['fingerprint']==digest
        assert (root/'audio'/(digest+'.wav')).stat().st_mtime_ns==mtime
    # read_aloud/lock_before are filled in on read for projects saved before they existed.
    reloaded = client.app.state.store.read(p['id'])
    assert reloaded['voices']==p['voices'] and reloaded['segments']==[{k:v for k,v in s.items() if k not in ('status','check_status','listening_status','tempo_status','rhythm_status','read_aloud','lock_before','reads_as','reads_note')} for s in p['segments']]
    links = client.post(f'/api/projects/{p["id"]}/export/create', json={'revision':p['revision']}).json()
    timeline = client.get(links['timeline.json']).json()
    assert timeline['synthetic_audio']
    expected = sum(s['audio']['samples'] for s in p['segments'])+3*round(24000*p['pause_ms']/1000)
    assert timeline['total_samples']==expected
    assert sf.info(root/'exports'/str(p['revision'])/'full.wav').frames==expected
    srt = client.get(links['subtitles.srt']).text
    for s in timeline['segments']:
        assert s['file_start_sample']<s['speech_start_sample']<s['speech_end_sample']<s['file_end_sample']
        # A segment may yield several cues and a very short one is held longer,
        # but a cue always opens exactly where the segment's speech opens.
        assert timestamp(s['speech_start_sample'],24000)+' --> ' in srt

def test_undo_redo_and_stale_edit(client):
    p = create(client)
    path='/api/projects/'+p['id']
    body={'revision':p['revision'],'segment_id':p['segments'][0]['id'],'text':'新的句子。'}
    newer = client.patch(path,json=body).json()
    assert client.patch(path,json=body).status_code==409
    undo = client.post(path+'/undo',json={'revision':newer['revision']}).json()
    assert undo['segments']==p['segments']
    redo = client.post(path+'/redo',json={'revision':undo['revision']}).json()
    assert redo['segments'][0]['text']=='新的句子。'
    assert client.app.state.store.read(p['id'])['segments'][0]['text']=='新的句子。'

def test_force_regenerate_and_spoken_text(client):
    p=generate(client,create(client))
    first=p['segments'][0]
    old=first['audio']['fingerprint']
    p=generate(client,p,segment_id=first['id'],force=True)
    assert p['segments'][0]['audio']['fingerprint']!=old
    assert (client.app.state.store.directory(p['id'])/'audio'/(old+'.wav')).exists()
    p=client.patch('/api/projects/'+p['id'],json={'revision':p['revision'],'segment_id':first['id'],'spoken_as':'改用这段文字朗读。'}).json()
    assert p['segments'][0]['text']==first['text'] and p['segments'][0]['status']=='pending'

def test_failed_segment_continues_and_retry(tmp_path):
    class FailOnce(FixtureEngine):
        calls=0
        def synthesize(self,*args):
            self.calls+=1
            if self.calls==2:
                raise ValueError('Injected one-time failure')
            return super().synthesize(*args)
    with TestClient(create_app(tmp_path,FailOnce()),base_url='http://127.0.0.1',headers=HEADERS) as c:
        p=generate(c,create(c))
        assert p['job']['status']=='completed_with_errors'
        assert [s['status'] for s in p['segments']]==['ready','failed','ready','ready']
        p=generate(c,p)
        assert all(s['status']=='ready' for s in p['segments'])

def test_cancel_and_restart_recovery(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Slow(FixtureEngine):
        def synthesize(self,*args):
            entered.set(); assert release.wait(5)
            return super().synthesize(*args)
    with TestClient(create_app(tmp_path,Slow()),base_url='http://127.0.0.1',headers=HEADERS) as c:
        p=create(c)
        c.post(f'/api/projects/{p["id"]}/render/start',json={'revision':p['revision']})
        assert entered.wait(5)
        assert c.patch('/api/projects/'+p['id'],json={'revision':p['revision'],'pause_ms':0}).status_code==409
        c.post(f'/api/projects/{p["id"]}/render/cancel',json={})
        release.set()
        p=wait(c,p['id'])
        assert p['job']['status']=='cancelled'
        assert sum(s['status']=='ready' for s in p['segments'])==1
    store=create_app(tmp_path,FixtureEngine()).state.store
    raw=store.read(p['id']);raw['job']['status']='running';store.write(raw)
    restored=create_app(tmp_path,FixtureEngine()).state.store.read(p['id'])
    assert restored['job']['status']=='interrupted'

def test_invalid_input_is_not_imported(client):
    assert client.post('/api/projects',json={'language':'zh','script':'没有角色的句子'}).status_code==400
    assert client.get('/api/projects').json()==[]
    assert client.post('/api/projects',json={'language':'zh','script':'旁白：'+'字'*61}).status_code==400

def test_local_security_and_voice_validation(client):
    assert client.get('/api/config',headers={'Host':'attacker.example'}).status_code==403
    assert client.get('/api/config',headers={'Origin':'https://attacker.example'}).status_code==403
    assert client.get('/api/config',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert client.post('/api/projects',json={},headers={'X-VoxStage':'0'}).status_code==403
    assert client.get('/api/projects/not-an-id').status_code==400
    p=create(client)
    assert client.patch('/api/projects/'+p['id'],json={'revision':p['revision'],'voice':'../../secret','speaker':'旁白'}).status_code==400

def test_known_silence_boundaries():
    rate=24000
    tone=.1*np.sin(2*np.pi*440*np.arange(rate)/rate)
    _,meta=process_audio(np.r_[np.zeros(rate//10),tone,np.zeros(rate//5)],rate)
    assert abs(meta['speech_start_sample']-rate//10)<=rate*.01
    assert abs(meta['speech_end_sample']-(rate+rate//10))<=rate*.01
    with pytest.raises(ValueError):process_audio(np.zeros(100),rate)
    with pytest.raises(ValueError):process_audio([float('nan')],rate)


@pytest.mark.parametrize('language,expected_status',[('zh','pending'),('en','ready')])
def test_previous_parameter_assets_are_preserved(client,language,expected_status):
    """Changing Chinese defaults must invalidate old cache without losing assets or English readiness."""
    import hashlib
    from runtime.audio import PROCESSING_VERSION
    p=create(client,language)
    s=p['segments'][0]
    old_parameters={'text':s['text'],'voice':p['voices'][s['speaker']],
        'language':language,'engine':FixtureEngine.identity,'seed':260909,
        'max_tokens':2048,'temperature':0.9,'top_k':50,'top_p':1.0,
        'repetition_penalty':1.05,'runtime':'mlx-audio-0.5.1','processing':PROCESSING_VERSION}
    digest=hashlib.sha256(json.dumps(old_parameters,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    store=client.app.state.store
    folder=store.directory(p['id'])/'audio'
    folder.mkdir()
    asset=folder/(digest+'.wav')
    sf.write(asset,np.zeros(2400),24000)
    before=asset.read_bytes()
    stored=store.read(p['id'])
    stored['segments'][0]['audio']={'fingerprint':digest,'samples':2400,'sample_rate':24000}
    store.write(stored)
    loaded=client.get('/api/projects/'+p['id']).json()
    assert loaded['segments'][0]['status']==expected_status
    assert asset.read_bytes()==before


class ReferenceFixture(FixtureEngine):
    reference_identity='reference-test-fixture-v1'
    reference_ready=True
    def __init__(self):self.calls=[]
    def synthesize_reference(self,text,language,reference_path,reference_text,seed,*,consent_confirmed=False,expected_sha256=None):
        import hashlib
        if not consent_confirmed or not reference_path.exists() or hashlib.sha256(reference_path.read_bytes()).hexdigest()!=expected_sha256:
            raise ValueError('Reference missing or changed')
        self.calls.append((text,reference_text,expected_sha256,seed))
        pcm,rate,meta=self.synthesize(text,'Ryan',language,seed)
        return pcm,rate,{'reference_sha256':expected_sha256,**meta}

def fix_voice(client,p,action='fix',consent=True):
    r=client.post(f'/api/projects/{p["id"]}/voice/{action}',json={'revision':p['revision'],
        'segment_id':p['segments'][0]['id'],'synthetic_reference_consent':consent})
    assert r.status_code==200,r.text
    return r.json()

def test_fixed_voice_reuses_preserved_reference_across_edit_retake_and_restart(tmp_path):
    engine=ReferenceFixture()
    with TestClient(create_app(tmp_path,engine),base_url='http://127.0.0.1:8765',headers=HEADERS) as client:
        p=generate(client,create(client,'en'))
        first=p['segments'][0]['id']
        originals={s['id']:s['audio']['fingerprint'] for s in p['segments']}
        denied=client.post(f'/api/projects/{p["id"]}/voice/fix',json={'revision':p['revision'],'segment_id':first})
        assert denied.status_code==400 and not client.get('/api/projects/'+p['id']).json()['voice_profiles']
        p=fix_voice(client,p)
        assert [s['status'] for s in p['segments']]==['pending','ready','ready','pending']
        profile=dict(p['voice_profiles']['Narrator'])
        ref=tmp_path/p['id']/'references'/(profile['sha256']+'.wav')
        original_ref=ref.read_bytes()
        p=generate(client,p)
        assert len(engine.calls)==2 and all(c[1]==profile['text'] and c[2]==profile['sha256'] for c in engine.calls)
        for s in p['segments'][1:3]:assert s['audio']['fingerprint']==originals[s['id']]
        p=client.patch('/api/projects/'+p['id'],json={'revision':p['revision'],'segment_id':first,'text':'The room was quiet.'}).json()
        p=generate(client,p)
        assert p['voice_profiles']['Narrator']==profile and engine.calls[-1][1]==profile['text']
        closing=p['segments'][-1]
        p=generate(client,p,segment_id=closing['id'],force=True)
        assert engine.calls[-1][3]==260910 and ref.read_bytes()==original_ref
        assert client.post(f'/api/projects/{p["id"]}/export/create',json={'revision':p['revision']}).status_code==200
    fresh=ReferenceFixture()
    with TestClient(create_app(tmp_path,fresh),base_url='http://127.0.0.1:8765',headers=HEADERS) as client:
        restored=client.get('/api/projects/'+p['id']).json()
        assert restored['voice_profiles']['Narrator']==profile
        assert all(s['status']=='ready' for s in restored['segments'])
        p=generate(client,restored,segment_id=closing['id'],force=True)
        assert fresh.calls[-1][2]==profile['sha256'] and ref.read_bytes()==original_ref

def test_fixed_voice_history_voice_change_and_corrupt_reference(tmp_path):
    with TestClient(create_app(tmp_path,ReferenceFixture()),base_url='http://127.0.0.1:8765',headers=HEADERS) as client:
        p=generate(client,create(client,'en'))
        p=fix_voice(client,p)
        profile=p['voice_profiles']['Narrator']
        p=client.post(f'/api/projects/{p["id"]}/undo',json={'revision':p['revision']}).json()
        assert not p['voice_profiles'] and all(s['status']=='ready' for s in p['segments'])
        p=client.post(f'/api/projects/{p["id"]}/redo',json={'revision':p['revision']}).json()
        assert p['voice_profiles']['Narrator']==profile
        p=generate(client,p)
        p=client.patch('/api/projects/'+p['id'],json={'revision':p['revision'],'speaker':'Narrator','voice':'Aiden'}).json()
        assert not p['voice_profiles']
        p=client.post(f'/api/projects/{p["id"]}/undo',json={'revision':p['revision']}).json()
        assert p['voice_profiles']['Narrator']==profile
        p=fix_voice(client,p,'release')
        assert not p['voice_profiles']
        p=client.post(f'/api/projects/{p["id"]}/undo',json={'revision':p['revision']}).json()
        assert p['voice_profiles']['Narrator']==profile
        ref=tmp_path/p['id']/'references'/(profile['sha256']+'.wav')
        ref.write_bytes(b'corrupted reference')
        p=generate(client,p,segment_id=p['segments'][0]['id'],force=True)
        assert p['job']['status']=='completed_with_errors' and p['segments'][0]['status']=='failed'
        assert all(s['status']=='ready' for s in p['segments'][1:])
        assert client.post(f'/api/projects/{p["id"]}/export/create',json={'revision':p['revision']}).status_code==400

def test_reference_engine_requires_consent_and_integrity(tmp_path):
    from runtime.engines import MlxEngine
    engine=MlxEngine(tmp_path)
    with pytest.raises(ValueError,match='已确认'):
        engine.synthesize_reference('Hello','en',tmp_path/'absent.wav','Hello',1)
    ref=tmp_path/'changed.wav';ref.write_bytes(b'changed')
    with pytest.raises(ValueError,match='已改变'):
        engine.synthesize_reference('Hello','en',ref,'Hello',1,consent_confirmed=True,expected_sha256='0'*64)


@pytest.mark.parametrize('expected,actual,language,matched',[
    ('Hello, WORLD!','hello world','en',True),
    ("I can't go.",'I can go.','en',False),
    ('I am not ready.','I am ready.','en',False),
    ('There are 12.5 cups.','There are 125 cups.','en',False),
    ('Go home.','Go home now.','en',False),
    ('雨点轻轻敲着窗。','雨点轻轻敲着窗','zh',True),
    ('不是风。','是风。','zh',False),
    ('一共12.5元。','一共125元。','zh',False),
    ('增长10%。','增长10。','zh',False),
    ('Temperature -5.','Temperature 5.','en',False),
    ('温度-5度。','温度5度。','zh',False),
    ('Hello.','','en',False)])
def test_content_differences_keep_meaningful_words_and_numbers(expected,actual,language,matched):
    from runtime.content_check import compare_text
    result=compare_text(expected,actual,language)
    assert (result['status']=='match')==matched
    assert result['expected_text']==expected and result['recognized_text']==actual
    assert bool(result['differences'])!=matched

class TranscriptFixture:
    ready=True
    identity='transcript-fixture-v1'
    def __init__(self):self.transcripts={};self.calls=[];self.fail_once=set();self.started=None;self.release=None
    def transcribe(self,path,language,work_root):
        self.calls.append(path.stem)
        if self.started:self.started.set();self.release.wait(4)
        if path.stem in self.fail_once:
            self.fail_once.remove(path.stem);raise ValueError('Injected transcription failure')
        return {'recognized_text':self.transcripts[path.stem],'seconds':0.0}

def check_audio(client,p,**extra):
    r=client.post(f'/api/projects/{p["id"]}/checks/start',json={'revision':p['revision'],**extra})
    assert r.status_code==200,r.text
    return wait(client,p['id'])

def test_content_review_cache_staleness_and_export(tmp_path):
    checker=TranscriptFixture()
    with TestClient(create_app(tmp_path,FixtureEngine(),checker=checker),base_url='http://127.0.0.1:8765',headers=HEADERS) as client:
        p=generate(client,create(client,'en'))
        checker.transcripts={s['audio']['fingerprint']:s['text'] for s in p['segments']}
        target=p['segments'][1]
        checker.transcripts[target['audio']['fingerprint']]='Did hear that?'
        p=check_audio(client,p)
        assert [s['check_status'] for s in p['segments']]==['match','review','match','match']
        p=check_audio(client,p);assert len(checker.calls)==4
        p=client.post(f'/api/projects/{p["id"]}/checks/review',json={'revision':p['revision'],'segment_id':target['id']}).json()
        assert p['segments'][1]['check_status']=='confirmed'
        links=client.post(f'/api/projects/{p["id"]}/export/create',json={'revision':p['revision']}).json()
        report=client.get(links['content-check.json']).json()
        assert report['segments'][1]['check_status']=='confirmed'
        p=client.patch('/api/projects/'+p['id'],json={'revision':p['revision'],'segment_id':target['id'],'spoken_as':'Did you see that?'}).json()
        assert p['segments'][1]['check_status']=='stale'
        assert client.post(f'/api/projects/{p["id"]}/checks/review',json={'revision':p['revision'],'segment_id':target['id']}).status_code==400
        p=client.post(f'/api/projects/{p["id"]}/undo',json={'revision':p['revision']}).json()
        assert p['segments'][1]['check_status']=='confirmed'
        p=generate(client,p,segment_id=target['id'],force=True)
        assert p['segments'][1]['check_status']=='stale'
        checker.transcripts[p['segments'][1]['audio']['fingerprint']]=target['text']
        p=check_audio(client,p)
        assert p['segments'][1]['check_status']=='match' and len(checker.calls)==5
        p=client.get('/api/projects/'+p['id']).json()
        assert all(s['check_status']=='match' for s in p['segments'])
    other=TranscriptFixture();other.identity='transcript-fixture-v2'
    with TestClient(create_app(tmp_path,FixtureEngine(),checker=other),base_url='http://127.0.0.1:8765',headers=HEADERS) as client:
        p=client.get('/api/projects/'+p['id']).json()
        assert all(s['check_status']=='stale' for s in p['segments'])

def test_content_errors_cancel_and_audio_preservation(tmp_path):
    checker=TranscriptFixture()
    with TestClient(create_app(tmp_path,FixtureEngine(),checker=checker),base_url='http://127.0.0.1:8765',headers=HEADERS) as client:
        p=generate(client,create(client,'zh'))
        checker.transcripts={s['audio']['fingerprint']:s['text'] for s in p['segments']}
        originals={s['id']:s['audio'] for s in p['segments']}
        checker.fail_once.add(p['segments'][0]['audio']['fingerprint'])
        p=check_audio(client,p)
        assert p['job']['status']=='completed_with_errors' and p['segments'][0]['check_status']=='error'
        assert all(s['check_status']=='match' for s in p['segments'][1:])
        p=check_audio(client,p)
        assert len(checker.calls)==5 and p['segments'][0]['check_status']=='match'
        assert all(s['audio']==originals[s['id']] for s in p['segments'])
        checker.started=threading.Event();checker.release=threading.Event()
        response=client.post(f'/api/projects/{p["id"]}/checks/start',json={'revision':p['revision'],'force':True})
        assert response.status_code==200 and checker.started.wait(2)
        current=client.get('/api/projects/'+p['id']).json()
        assert client.post(f'/api/projects/{p["id"]}/render/start',json={'revision':current['revision']}).status_code==409
        assert client.patch('/api/projects/'+p['id'],json={'revision':current['revision'],'pause_ms':0}).status_code==409
        client.post(f'/api/projects/{p["id"]}/render/cancel');checker.release.set()
        p=wait(client,p['id']);assert p['job']['status']=='cancelled'
        assert len(checker.calls)==6
        source=tmp_path/p['id']/'audio'/(p['segments'][0]['audio']['fingerprint']+'.wav')
        source.write_bytes(source.read_bytes()+b'changed')
        p=client.get('/api/projects/'+p['id']).json()
        assert p['segments'][0]['check_status']=='stale'

# 最后更新：2026-09-09 · Astra


def test_current_export_links_follow_revision_and_stay_stale_after_undo(client):
    p = generate(client, create(client, 'zh'))
    base = f'/api/projects/{p["id"]}'
    assert client.get(base + '/export/current').json() == {}

    links = client.post(base + '/export/create', json={'revision': p['revision']}).json()
    current = client.get(base + '/export/current')
    assert current.status_code == 200
    assert current.json() == links
    old_wav = links['full.wav']
    assert client.get(old_wav).status_code == 200

    # Any saved edit makes the last batch stale, but it remains downloadable.
    # The compatibility endpoint still hides stale links until the new UI can
    # render the warning carried by /export/status.
    changed = client.patch(base, json={'revision': p['revision'], 'pause_ms': 500}).json()
    assert changed['revision'] > p['revision']
    assert client.get(base + '/export/current').json() == {}
    stale = client.get(base + '/export/status').json()
    assert stale['status'] == 'stale' and stale['revision'] == p['revision']
    assert stale['links']['full.wav'] == old_wav
    assert client.get(old_wav).status_code == 200

    # Undo may restore equal content, but revision history still marks the old
    # batch as potentially stale. It stays usable until a new export succeeds.
    restored = client.post(base + '/undo', json={'revision': changed['revision']}).json()
    assert restored['pause_ms'] == p['pause_ms']
    assert restored['revision'] > changed['revision']
    assert client.get(base + '/export/current').json() == {}
    assert client.get(base + '/export/status').json()['status'] == 'stale'
    assert client.get(old_wav).status_code == 200

    # A newly successful batch becomes the only exposed batch and removes the
    # older saved revision. A failed export would have left it in place.
    newest = client.post(base + '/export/create', json={'revision': restored['revision']})
    assert newest.status_code == 200, newest.text
    assert client.get(base + '/export/status').json()['status'] == 'latest'
    assert client.get(old_wav).status_code == 404
