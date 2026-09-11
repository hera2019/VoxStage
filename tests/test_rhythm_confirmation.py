"""Regression evidence for Claude Hera's rhythm-confirm task, 2026-09-11."""
import os
import numpy as np
import pytest
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine
from test_workflow import HEADERS, create, generate, check_audio, TranscriptFixture

class PausedTone(FixtureEngine):
    def synthesize(self,*args,**kwargs):
        rate=24000
        tone=.1*np.sin(np.arange(rate)*2*np.pi*440/rate)
        return np.r_[tone,np.zeros(rate*2),tone],rate,{}

@pytest.fixture
def prepared(tmp_path):
    checker=TranscriptFixture()
    with TestClient(create_app(tmp_path/'projects',PausedTone(),checker=checker),base_url='http://127.0.0.1',headers=HEADERS) as c:
        p=generate(c,create(c,script='旁白：这是一个测试句子。'))
        checker.transcripts[p['segments'][0]['audio']['fingerprint']]='完全不同的话。'
        p=check_audio(c,p)
        assert (p['segments'][0]['check_status'],p['segments'][0]['rhythm_status'])==('review','review')
        yield c,p,checker

def review(c,p,confirmed=True):
    response=c.post('/api/projects/'+p['id']+'/checks/review',json={'revision':p['revision'],'segment_id':p['segments'][0]['id'],'confirmed':confirmed})
    assert response.status_code==200,response.text
    return response.json()

def audio_path(c,p):
    return c.app.state.store.directory(p['id'])/'audio'/(p['segments'][0]['audio']['fingerprint']+'.wav')

def statuses(p):
    s=p['segments'][0]
    return s['check_status'],s['rhythm_status']

def test_one_confirmation_undo_export_and_audio_untouched(prepared):
    c,p,_=prepared;path=audio_path(c,p);before=(path.read_bytes(),path.stat().st_mtime_ns)
    fingerprint=p['segments'][0]['audio']['fingerprint']
    p=review(c,p);assert statuses(p)==('confirmed','confirmed')
    assert p['segments'][0]['audio']['fingerprint']==fingerprint and p['segments'][0]['status']=='ready'
    assert (path.read_bytes(),path.stat().st_mtime_ns)==before
    p=c.get('/api/projects/'+p['id']).json();assert statuses(p)==('confirmed','confirmed')
    links=c.post('/api/projects/'+p['id']+'/export/create',json={'revision':p['revision']}).json()
    exported=c.get(links['content-check.json']).json()['segments'][0]
    assert exported['check_status']==exported['rhythm_status']=='confirmed'
    p=review(c,p,False);assert statuses(p)==('review','review')
    assert (path.read_bytes(),path.stat().st_mtime_ns)==before
    p=c.post('/api/projects/'+p['id']+'/undo',json={'revision':p['revision']}).json()
    assert statuses(p)==('confirmed','confirmed')
    p=c.post('/api/projects/'+p['id']+'/redo',json={'revision':p['revision']}).json()
    assert statuses(p)==('review','review')

@pytest.mark.parametrize('change',['text','spoken_as','voice','retake','file','file_same_stat'])
def test_old_confirmation_invalidated(prepared,change):
    c,p,_=prepared;p=review(c,p);url='/api/projects/'+p['id'];sid=p['segments'][0]['id']
    if change in ('text','spoken_as'):
        p=c.patch(url,json={'revision':p['revision'],'segment_id':sid,change:'这是修改之后的句子。'}).json()
    elif change=='voice':
        p=c.patch(url,json={'revision':p['revision'],'speaker':'旁白','voice':'Uncle_Fu'}).json()
    elif change=='retake':
        p=generate(c,p,segment_id=sid,force=True)
    else:
        path=audio_path(c,p);stat=path.stat();data=bytearray(path.read_bytes());data[-12]^=1;path.write_bytes(data)
        if change=='file_same_stat':os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        p=c.get(url).json()
    assert statuses(p)==('stale','stale')
    assert c.post(url+'/checks/review',json={'revision':p['revision'],'segment_id':sid}).status_code==400

@pytest.mark.parametrize('mode',['match','error','not_checked'])
def test_rhythm_only_confirmation_preserves_content_state(prepared,mode):
    c,p,checker=prepared;store=c.app.state.store;saved=store.read(p['id'])
    if mode=='not_checked':saved['segments'][0].pop('content_check')
    else:saved['segments'][0]['content_check']['status']=mode
    store.write(saved);p=c.get('/api/projects/'+p['id']).json()
    p=review(c,p);assert statuses(p)==(mode,'confirmed')
    p=review(c,p,False);assert statuses(p)==(mode,'review')

def test_recheck_does_not_inherit_review(prepared):
    c,p,checker=prepared;p=review(c,p)
    p=check_audio(c,p,force=True)
    assert statuses(p)==('review','review')

def test_changed_bytes_before_first_confirmation_rejected(prepared):
    c,p,_=prepared;path=audio_path(c,p);stat=path.stat();data=bytearray(path.read_bytes());data[-12]^=1;path.write_bytes(data)
    os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    response=c.post('/api/projects/'+p['id']+'/checks/review',json={'revision':p['revision'],'segment_id':p['segments'][0]['id']})
    assert response.status_code==400

# 最后更新：2026-09-11 · Astra
