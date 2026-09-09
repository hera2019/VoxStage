"""Timeline behaviour and heuristic boundaries, no human quality claims. Astra, 2026-09-09."""
from types import SimpleNamespace
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.rhythm import analyze
from runtime.tempo import render_tempo, ffmpeg_path
from runtime.engines import FixtureEngine
from test_workflow import HEADERS, create, generate, wait
from test_listening import mark


def tone(seconds,rate=24000):
    return .25*np.sin(2*np.pi*440*np.arange(round(seconds*rate))/rate)


def test_internal_pause_excludes_leading_and_trailing_silence():
    pcm=np.r_[np.zeros(24000),tone(1),np.zeros(9600),tone(1),np.zeros(24000)]
    result=analyze(pcm,24000)
    assert len(result['markers'])==1
    assert result['markers'][0]['kind']=='pause'
    assert abs(result['markers'][0]['start']-2)<.02
    assert abs(result['markers'][0]['end']-2.4)<.02
    assert result['manual_checkpoints'] and result['pace']['status']=='unavailable'
    assert not analyze(np.r_[tone(1),np.zeros(2400),tone(1)],24000)['markers']


def test_pace_is_estimate_and_short_insufficient_samples_are_not_passed():
    times=[{'start':i*.25,'end':(i+1)*.25,'text':'你好'} for i in range(16)]
    times += [{'start':4+i*.5,'end':4+(i+1)*.5,'text':'你好'} for i in range(8)]
    result=analyze(tone(8),24000,times)
    assert result['pace']['status']=='estimated'
    assert result['pace']['ratio']==2
    assert any(x['kind']=='pace' and '前快后慢' in x['label'] for x in result['markers'])
    equal=[{'start':i*.5,'end':(i+1)*.5,'text':'你好'} for i in range(16)]
    assert not analyze(tone(8),24000,equal)['markers']
    assert analyze(tone(1),24000,equal[:2])['pace']['status']=='unavailable'


@pytest.mark.parametrize('speed',[.5,2.])
def test_extreme_tempo_preserves_pitch_and_samples(speed):
    if not ffmpeg_path():pytest.skip('Real FFmpeg required')
    pcm=tone(4);out,mapping=render_tempo(pcm,24000,speed)
    assert abs(len(out)/24000-4/speed)<.12
    window=out[24000//2:24000]
    hz=np.fft.rfftfreq(len(window),1/24000)[np.argmax(abs(np.fft.rfft(window)))]
    assert abs(hz-440)<4
    assert mapping[-1]['output_end']==len(out)/24000


class SpeechTone(FixtureEngine):
    def synthesize(self,*args):return np.r_[tone(2),np.zeros(9600),tone(3.6)],24000,{}


@pytest.fixture
def client(tmp_path):
    checker=SimpleNamespace(ready=True,identity='fixture-timed')
    checker.transcribe=lambda *args:{'recognized_text':'你好世界','timed_text':[]}
    with TestClient(create_app(tmp_path,SpeechTone(),checker=checker),base_url='http://127.0.0.1',headers=HEADERS) as c:yield c


def test_local_tempo_save_preview_export_undo_and_new_take(client):
    c=client;p=generate(c,create(c,script='旁白：你好世界'))
    sid=p['segments'][0]['id'];url='/api/projects/'+p['id'];base=url+'/segments/'+sid
    root=c.app.state.store.directory(p['id']);fp=p['segments'][0]['audio']['fingerprint'];path=root/'audio'/(fp+'.wav');original=path.read_bytes()
    p=mark(c,p)
    p=c.patch(url,json={'revision':p['revision'],'speech_rate':1.2}).json()
    regions=[{'start':3.,'end':6.,'speed':1.5}]
    response=c.post(base+'/tempo',json={'revision':p['revision'],'regions':regions});assert response.status_code==200,response.text
    p=response.json();assert p['segments'][0]['tempo_status']=='current'
    assert p['segments'][0]['status']=='ready' and p['segments'][0]['listening_status']=='needs_listening'
    preview=c.post(base+'/preview',json={'revision':p['revision']}).json()
    assert [x['speed'] for x in preview['mapping']]==[1.2,1.5]  # absolute override, not 1.8
    assert abs(preview['duration']-(3/1.2+3/1.5))<.12
    links=c.post(url+'/export/create',json={'revision':p['revision']}).json()
    assert c.get(preview['url']).content==c.get(links['full.wav']).content
    timeline=c.get(links['timeline.json']).json()
    assert timeline['segments'][0]['tempo_mapping']==preview['mapping']
    report=c.get(links['content-check.json']).json()
    assert report['segments'][0]['tempo_status']=='current'
    assert 'rhythm_status' in report['segments'][0]
    assert path.read_bytes()==original
    p=c.post(url+'/undo',json={'revision':p['revision']}).json();assert p['segments'][0]['tempo_status']=='none'
    p=c.post(url+'/redo',json={'revision':p['revision']}).json();assert p['segments'][0]['tempo_status']=='current'
    p=generate(c,p,segment_id=sid,force=True);assert p['segments'][0]['tempo_status']=='stale'
    changed=c.post(base+'/preview',json={'revision':p['revision']}).json()
    assert [x['speed'] for x in changed['mapping']]==[1.2]
    assert path.read_bytes()==original


@pytest.mark.parametrize('regions',[
 [{'start':1,'end':1.1,'speed':1.2}],
 [{'start':1,'end':7,'speed':1.2}],
 [{'start':-1,'end':2,'speed':1.2}],
 [{'start':1,'end':2,'speed':.49}],
 [{'start':1,'end':2,'speed':2.01}],
 [{'start':2,'end':3,'speed':1},{'start':1,'end':2,'speed':1}],
 [{'start':1,'end':3,'speed':1},{'start':2,'end':4,'speed':1}],
])
def test_invalid_ranges_leave_project_unchanged(client,regions):
    c=client;p=generate(c,create(c,script='旁白：你好世界'));url='/api/projects/'+p['id']
    response=c.post(url+'/segments/'+p['segments'][0]['id']+'/tempo',json={'revision':p['revision'],'regions':regions})
    assert response.status_code in (400,422),response.text
    assert c.get(url).json()['revision']==p['revision']


def test_rhythm_check_survives_asr_failure_and_recheck_tracks_new_audio(client):
    c=client;p=generate(c,create(c,script='旁白：你好世界'));url='/api/projects/'+p['id']
    def failed(*args):raise ValueError('Injected ASR failure')
    c.app.state.checker.transcribe=failed
    response=c.post(url+'/checks/start',json={'revision':p['revision']});assert response.status_code==200
    p=wait(c,p['id']);s=p['segments'][0]
    assert s['check_status']=='error' and s['rhythm_status']=='review'
    assert len(s['rhythm_check']['markers'])==1
    p=generate(c,p,segment_id=s['id'],force=True)
    assert p['segments'][0]['rhythm_status']=='stale'


def test_source_tampering_invalidates_region_and_preview_revision(client):
    c=client;p=generate(c,create(c,script='旁白：你好世界'));url='/api/projects/'+p['id'];s=p['segments'][0];base=url+'/segments/'+s['id']
    p=c.post(base+'/tempo',json={'revision':p['revision'],'regions':[{'start':1,'end':3,'speed':.9}]}).json()
    assert c.post(base+'/preview',json={'revision':p['revision']-1}).status_code==409
    path=c.app.state.store.directory(p['id'])/'audio'/(s['audio']['fingerprint']+'.wav')
    pcm,rate=sf.read(path);sf.write(path,pcm*.9,rate,subtype='PCM_16')
    assert c.get(url).json()['segments'][0]['tempo_status']=='stale'

# 最后更新：2026-09-09 · Astra
