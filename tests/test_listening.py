"""Listening issue lifecycle and reversible project organization. Astra, 2026-09-09."""
import os
import threading
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine
from test_workflow import HEADERS, create, generate, wait, TranscriptFixture, check_audio


def mark(c, p, index=0, **extra):
    response=c.post(f'/api/projects/{p["id"]}/listening/review',json={
        'revision':p['revision'],'segment_id':p['segments'][index]['id'],
        'kind':'tail','note':'Test fixture issue, not a real listening judgment',**extra})
    assert response.status_code==200,response.text
    return response.json()


def client_for(root,engine=None,checker=None):
    return TestClient(create_app(root,engine or FixtureEngine(),checker=checker or TranscriptFixture()),
                      base_url='http://127.0.0.1',headers=HEADERS)


def test_issue_does_not_change_audio_or_automated_check_and_survives_restart(tmp_path):
    checker=TranscriptFixture()
    with client_for(tmp_path,checker=checker) as c:
        p=generate(c,create(c))
        checker.transcripts={s['audio']['fingerprint']:s['text'] for s in p['segments']}
        p=check_audio(c,p)
        original=p['segments'][0]
        p=mark(c,p)
        s=p['segments'][0]
        assert s['audio']==original['audio'] and s['content_check']==original['content_check']
        assert s['check_status']=='match' and s['listening_status']=='issue'
        issue=s['listening_issue']
        links=c.post(f'/api/projects/{p["id"]}/export/create',json={'revision':p['revision']}).json()
        report=c.get(links['content-check.json']).json()['segments'][0]
        assert report['listening_status']=='issue' and report['listening_issue']==issue
        assert c.post(f'/api/projects/{p["id"]}/listening/review',json={
            'revision':p['revision']-1,'segment_id':s['id'],'clear':True}).status_code==409
        p=mark(c,p,clear=True)
        assert p['segments'][0]['listening_status']=='none'
        p=c.post(f'/api/projects/{p["id"]}/undo',json={'revision':p['revision']}).json()
        assert p['segments'][0]['listening_issue']==issue
    with client_for(tmp_path,checker=checker) as c:
        p=c.get('/api/projects/'+p['id']).json()
        assert p['segments'][0]['listening_status']=='issue'


def test_marked_retake_changes_only_selected_and_requires_new_listening(tmp_path):
    with client_for(tmp_path) as c:
        p=generate(c,create(c))
        old=[s['audio']['fingerprint'] for s in p['segments']]
        root=c.app.state.store.directory(p['id'])/'audio'
        original_files={fp:(root/(fp+'.wav')).read_bytes() for fp in old}
        p=mark(c,p,0);p=mark(c,p,2)
        p=generate(c,p,marked_only=True)
        assert p['job']['total']==2
        assert [s['listening_status'] for s in p['segments']]==['needs_listening','none','needs_listening','none']
        for i,s in enumerate(p['segments']):
            assert (s['audio']['fingerprint']!=old[i])==(i in (0,2))
        assert all((root/(fp+'.wav')).read_bytes()==data for fp,data in original_files.items())
        assert c.post(f'/api/projects/{p["id"]}/render/start',json={'revision':p['revision'],'marked_only':True}).status_code==400
        p=mark(c,p)  # Explicitly mark the new version, not an automatic carry-over.
        assert p['segments'][0]['listening_status']=='issue'


def test_edit_and_external_file_change_invalidate_issue_binding(tmp_path):
    with client_for(tmp_path) as c:
        p=mark(c,generate(c,create(c)))
        sid=p['segments'][0]['id']
        p=c.patch('/api/projects/'+p['id'],json={'revision':p['revision'],'segment_id':sid,'spoken_as':'换成新的句子。'}).json()
        assert p['segments'][0]['listening_status']=='pending'
        p=c.post(f'/api/projects/{p["id"]}/undo',json={'revision':p['revision']}).json()
        assert p['segments'][0]['listening_status']=='issue'
        path=c.app.state.store.directory(p['id'])/'audio'/(p['segments'][0]['audio']['fingerprint']+'.wav')
        stat=path.stat();os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000))
        p=c.get('/api/projects/'+p['id']).json()
        assert p['segments'][0]['listening_status']=='needs_listening'


def test_cancel_marked_retake_keeps_untouched_audio_and_issue(tmp_path):
    entered,release=threading.Event(),threading.Event()
    class Slow(FixtureEngine):
        slow=False
        def synthesize(self,*args):
            if self.slow:
                entered.set();assert release.wait(5)
            return super().synthesize(*args)
    engine=Slow()
    with client_for(tmp_path,engine) as c:
        p=generate(c,create(c));p=mark(c,p,0);p=mark(c,p,2)
        untouched=p['segments'][2]
        engine.slow=True
        response=c.post(f'/api/projects/{p["id"]}/render/start',json={'revision':p['revision'],'marked_only':True})
        assert response.status_code==200
        try:
            assert entered.wait(5)
            assert c.post(f'/api/projects/{p["id"]}/listening/review',json={
                'revision':response.json()['revision'],'segment_id':untouched['id'],'clear':True}).status_code==409
            assert c.post(f'/api/projects/{p["id"]}/render/cancel',json={}).status_code==200
        finally:
            release.set()
        p=wait(c,p['id'])
        assert p['job']['status']=='cancelled' and p['job']['completed']==1
        assert p['segments'][0]['listening_status']=='needs_listening'
        assert p['segments'][2]==untouched


def test_failed_marked_retake_preserves_issue_and_can_retry(tmp_path):
    class FailOnce(FixtureEngine):
        fail=False
        def synthesize(self,*args):
            if self.fail:
                self.fail=False
                raise ValueError('Injected failure for marked retake')
            return super().synthesize(*args)
    engine=FailOnce()
    with client_for(tmp_path,engine) as c:
        p=generate(c,create(c));p=mark(c,p,0);p=mark(c,p,2)
        old=p['segments'][0]['audio']
        engine.fail=True
        p=generate(c,p,marked_only=True)
        assert p['job']['failed']==1 and p['job']['completed']==2
        assert p['segments'][0]['listening_status']=='pending' and p['segments'][0]['audio']==old
        assert p['segments'][2]['listening_status']=='needs_listening'
        p=generate(c,p)
        assert p['segments'][0]['status']=='ready' and p['segments'][0]['listening_status']=='needs_listening'


def test_invalid_listening_requests_do_not_mutate_project(tmp_path):
    with client_for(tmp_path) as c:
        p=create(c);url=f'/api/projects/{p["id"]}/listening/review'
        body={'revision':p['revision'],'segment_id':p['segments'][0]['id']}
        assert c.post(url,json=body).status_code==400
        assert c.post(url,json={**body,'kind':'invented'}).status_code==422
        assert c.post(url,json={**body,'note':'x'*301}).status_code==422
        assert c.get('/api/projects/'+p['id']).json()['revision']==p['revision']


def test_rename_archive_restore_and_undo_preserve_audio_and_checks(tmp_path):
    checker=TranscriptFixture()
    with client_for(tmp_path,checker=checker) as c:
        p=generate(c,create(c));p=mark(c,p)
        checker.transcripts={s['audio']['fingerprint']:s['text'] for s in p['segments']}
        p=check_audio(c,p)
        original=p['segments'];name=p['name'];url='/api/projects/'+p['id']
        assert c.patch(url,json={'revision':p['revision'],'name':'   '}).status_code==400
        assert c.patch(url,json={'revision':p['revision'],'name':'x'*121}).status_code==422
        p=c.patch(url,json={'revision':p['revision'],'name':' Revised title '}).json()
        assert p['name']=='Revised title' and p['segments']==original
        p=c.patch(url,json={'revision':p['revision'],'archived':True}).json()
        assert p['segments']==original
        assert c.get('/api/projects').json()==[]
        assert c.get('/api/projects?include_archived=true').json()[0]['archived'] is True
        p=c.post(url+'/undo',json={'revision':p['revision']}).json()
        assert p['archived'] is False and len(c.get('/api/projects').json())==1
        p=c.post(url+'/undo',json={'revision':p['revision']}).json()
        assert p['name']==name and p['segments']==original
        p=c.post(url+'/redo',json={'revision':p['revision']}).json()
        assert p['name']=='Revised title'
        p=c.patch(url,json={'revision':p['revision'],'archived':True}).json()
        p=c.patch(url,json={'revision':p['revision'],'archived':False}).json()
        assert p['segments']==original and len(c.get('/api/projects').json())==1


def test_archived_state_roundtrips_and_legacy_history_defaults_to_active(tmp_path):
    with client_for(tmp_path) as c:
        p=create(c)
        store=c.app.state.store
        raw=store.read(p['id']);raw.pop('archived',None);store.write(raw)
        p=c.patch('/api/projects/'+p['id'],json={'revision':p['revision'],'archived':True}).json()
        raw=store.read(p['id']);raw['history'][0].pop('archived',None);store.write(raw)
    with client_for(tmp_path) as c:
        p=c.get('/api/projects/'+p['id']).json()
        assert p['archived'] is True
        p=c.post(f'/api/projects/{p["id"]}/undo',json={'revision':p['revision']}).json()
        assert p['archived'] is False
