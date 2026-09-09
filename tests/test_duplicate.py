"""Independent project copies retain audio/edit bindings and fail atomically. Astra, 2026-09-09."""
import json
import pytest
from test_workflow import create,generate,ReferenceFixture,fix_voice,HEADERS
from fastapi.testclient import TestClient
from runtime.app import create_app

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path,ReferenceFixture()),base_url='http://127.0.0.1:8765',headers=HEADERS) as c:
        yield c


def test_duplicate_retains_audio_settings_and_independent_edits(client):
    p=generate(client,create(client));url='/api/projects/'+p['id'];s=p['segments'][0]
    p=generate(client,fix_voice(client,p))
    clipbase=url+'/segments/'+s['id']+'/clips';clips=client.get(clipbase).json()['clips'];clips[0]['speed']=1.2
    edited=client.post(clipbase,json={'revision':p['revision'],'clips':clips});assert edited.status_code==200,edited.text;p=edited.json()
    store=client.app.state.store;source=store.directory(p['id']);snapshot=(source/'project.json').read_bytes()
    # Copy current manifest and all fixed synthetic reference assets without inference.
    response=client.post(url+'/duplicate',json={'revision':p['revision']});assert response.status_code==200,response.text
    duplicate=response.json();dest=store.directory(duplicate['id']);assert duplicate['id']!=p['id'] and duplicate['revision']==0 and not duplicate['can_undo']
    assert duplicate['voice_profiles']==p['voice_profiles'] and duplicate['segments']==p['segments']
    assert (source/'project.json').read_bytes()==snapshot
    for folder in ('audio','references'):
        for asset in (source/folder).rglob('*'):
            if asset.is_file():
                copied=dest/asset.relative_to(source);assert copied.read_bytes()==asset.read_bytes();assert copied.stat().st_mtime_ns==asset.stat().st_mtime_ns
    changed=client.patch('/api/projects/'+duplicate['id'],json={'revision':0,'segment_id':s['id'],'text':'这是独立修改。'})
    assert changed.status_code==200 and client.get(url).json()['segments'][0]['text']==s['text']


def test_duplicate_rejects_stale_and_running(client):
    p=create(client);store=client.app.state.store;url='/api/projects/'+p['id']+'/duplicate'
    assert client.post(url,json={'revision':99}).status_code==409
    stored=store.read(p['id']);stored['job']['status']='running';store.write(stored)
    assert client.post(url,json={'revision':p['revision']}).status_code==409
    assert len(list(store.root.glob('*/project.json')))==1


def test_duplicate_symlink_failure_leaves_no_partial_project(client,tmp_path):
    p=create(client);store=client.app.state.store;source=store.directory(p['id']);(source/'audio').mkdir();outside=tmp_path/'outside.wav';outside.write_bytes(b'private')
    (source/'audio'/'linked.wav').symlink_to(outside)
    before=set(store.root.iterdir());response=client.post('/api/projects/'+p['id']+'/duplicate',json={'revision':p['revision']})
    assert response.status_code==400 and set(store.root.iterdir())==before and outside.read_bytes()==b'private'

# 最后更新：2026-09-09 · Astra
