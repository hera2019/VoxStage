"""Phonetic tolerance and tempo preserve originals and final timeline. Astra, 2026-09-09."""
import hashlib
from types import SimpleNamespace
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from runtime import tempo
from runtime.app import create_app
from runtime.audio import process_audio, timestamp
from runtime.content_check import compare_text
from runtime.engines import FixtureEngine
from test_workflow import HEADERS, create, generate
from test_listening import mark


@pytest.mark.parametrize('expected,recognized',[
    ('两个人傻傻地笑了。','两个人傻傻的笑了。'),
    ('吃的好，睡的香。','吃得好，睡得香。'),
    ('跑得很快','跑地很快'),('她来了','他来了'),('这里有一棵树','这里有一颗树'),
])
def test_homophones_are_explicitly_tolerated(expected,recognized):
    result=compare_text(expected,recognized,'zh')
    assert result['status']=='match' and not result['differences']
    assert result['equivalences']
    assert result['expected_text']==expected and result['recognized_text']==recognized


@pytest.mark.parametrize('expected,recognized',[
    ('土地','土的'),('目的','目得'),('得意','的意'),('我得走了','我地走了'),
    ('你好','泥好'),('不是风','是风'),('5%','5'),('-5','5'),('他来了','他来'),
])
def test_distinct_pronunciations_and_missing_units_still_need_review(expected,recognized):
    result=compare_text(expected,recognized,'zh')
    assert result['status']=='review' and result['differences']


def test_english_stays_word_based():
    assert compare_text('Their book','There book','en')['status']=='review'
    assert compare_text('Do not go','Do go','en')['status']=='review'


def test_export_tempo_preserves_pitch_duration_and_original_bytes(tmp_path,monkeypatch):
    if not tempo.ffmpeg_path():pytest.skip('Real FFmpeg not installed')
    class Tone(FixtureEngine):
        def synthesize(self,*args):
            rate=24000;t=np.arange(rate*2)/rate
            return np.r_[np.zeros(2400),.2*np.sin(2*np.pi*440*t),np.zeros(2400)],rate,{}
    checker=SimpleNamespace(ready=False,identity='test')
    with TestClient(create_app(tmp_path,Tone(),checker=checker),base_url='http://127.0.0.1',headers=HEADERS) as c:
        p=generate(c,create(c,script='旁白：一个测试。\n旁白：另一个测试。'))
        original=p['segments'];directory=c.app.state.store.directory(p['id'])
        originals={s['audio']['fingerprint']:(directory/'audio'/(s['audio']['fingerprint']+'.wav')).read_bytes() for s in original}
        p=mark(c,p)
        p=c.patch('/api/projects/'+p['id'],json={'revision':p['revision'],'speech_rate':1.2}).json()
        assert p['speech_rate']==1.2 and p['segments'][0]['listening_status']=='needs_listening'
        assert all(s['status']=='ready' for s in p['segments'])
        links=c.post(f'/api/projects/{p["id"]}/export/create',json={'revision':p['revision']}).json()
        timeline=c.get(links['timeline.json']).json()
        pcm,rate=sf.read(directory/'exports'/str(p['revision'])/'full.wav')
        assert timeline['total_samples']==len(pcm) and timeline['speech_rate']==1.2
        expected=2*2.2/1.2+.25
        assert abs(len(pcm)/rate-expected)<.12
        middle=pcm[rate//2:rate]
        peak=np.fft.rfftfreq(len(middle),1/rate)[np.argmax(abs(np.fft.rfft(middle)))]
        assert abs(peak-440)<4  # A pitch-shifting resample would fail this.
        srt=c.get(links['subtitles.srt']).text
        for segment in timeline['segments']:
            assert timestamp(segment['speech_start_sample'],rate)+' --> ' in srt
        assert all((directory/'audio'/(fp+'.wav')).read_bytes()==data for fp,data in originals.items())
        report=c.get(links['content-check.json']).json()
        assert report['checked_audio']=='original_generated_audio' and report['speech_rate']==1.2
        p=c.post(f'/api/projects/{p["id"]}/undo',json={'revision':p['revision']}).json()
        assert p['speech_rate']==1.0 and p['segments'][0]['listening_status']=='issue'
        assert c.patch('/api/projects/'+p['id'],json={'revision':p['revision'],'speech_rate':3}).status_code==422


def test_missing_ffmpeg_retains_original_speed(monkeypatch):
    monkeypatch.setattr(tempo,'ffmpeg_path',lambda:None)
    pcm=np.ones(2400,dtype=np.float32)
    assert tempo.change_tempo(pcm,24000,1) is pcm
    with pytest.raises(ValueError,match='FFmpeg'):tempo.change_tempo(pcm,24000,1.2)
