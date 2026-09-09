"""Non-destructive cuts combined with local tempo. Astra, 2026-09-09."""
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from types import SimpleNamespace
from runtime.app import create_app
from runtime.tempo import render_tempo
from runtime.audio import timestamp
from test_timeline import SpeechTone,tone
from test_workflow import HEADERS,create,generate

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path,SpeechTone(),checker=SimpleNamespace(ready=False,identity='fixture')),base_url='http://127.0.0.1',headers=HEADERS) as c:yield c


def test_cut_with_tempo_preview_export_restore_and_undo(client):
    c=client;p=generate(c,create(c,script='旁白：你好世界'));base='/api/projects/'+p['id'];s=p['segments'][0];url=base+'/segments/'+s['id']
    root=c.app.state.store.directory(p['id']);source=root/'audio'/(s['audio']['fingerprint']+'.wav');original=source.read_bytes()
    region={'start':3,'end':6,'speed':1.5};cut={'start':2,'end':2.4}
    response=c.post(url+'/tempo',json={'revision':p['revision'],'regions':[region],'cuts':[cut]});assert response.status_code==200,response.text
    p=response.json();preview=c.post(url+'/preview',json={'revision':p['revision']}).json()
    assert abs(preview['duration']-4.6)<.12
    assert [(x['source_start'],x['source_end']) for x in preview['mapping']]==[(0,2),(2.4,3),(3,6)]
    links=c.post(base+'/export/create',json={'revision':p['revision']}).json()
    assert c.get(preview['url']).content==c.get(links['full.wav']).content
    timeline=c.get(links['timeline.json']).json();entry=timeline['segments'][0]
    assert timeline['total_samples']==round(preview['duration']*24000)
    assert timestamp(entry['speech_end_sample'],24000) in c.get(links['subtitles.srt']).text
    assert c.get(links['content-check.json']).json()['segments'][0]['edited_content_requires_review']
    p=c.post(base+'/undo',json={'revision':p['revision']}).json();assert p['segments'][0]['tempo_status']=='none'
    p=c.post(base+'/redo',json={'revision':p['revision']}).json();assert p['segments'][0]['tempo_edit']['cuts']==[cut]
    p=c.post(url+'/tempo',json={'revision':p['revision'],'regions':[region],'cuts':[]}).json()
    assert p['segments'][0]['tempo_edit']['regions']==[region] and not p['segments'][0]['tempo_edit'].get('cuts')
    assert source.read_bytes()==original


@pytest.mark.parametrize('cuts',[
 [{'start':0,'end':6}], [{'start':0,'end':5.9}], [{'start':-1,'end':2}],
 [{'start':1,'end':7}], [{'start':1,'end':1.005}],
 [{'start':1,'end':3},{'start':2,'end':4}],
 [{'start':3,'end':4},{'start':1,'end':2}],
 [{'start':.005,'end':1}], # must not leave an unrenderable tiny remnant
])
def test_invalid_cuts_do_not_change_project(client,cuts):
    c=client;p=generate(c,create(c,script='旁白：你好世界'));base='/api/projects/'+p['id'];sid=p['segments'][0]['id']
    result=c.post(base+'/segments/'+sid+'/tempo',json={'revision':p['revision'],'regions':[],'cuts':cuts})
    assert result.status_code in (400,422),result.text
    assert c.get(base).json()['revision']==p['revision']


def test_trim_and_cut_boundaries_preserve_tone_and_mapping():
    pcm=tone(4)
    out,mapping=render_tempo(pcm,24000,1,[],[{'start':0,'end':.5},{'start':3.5,'end':4}])
    assert len(out)==24000*3 and len(mapping)==1
    assert mapping[0]['source_start']==.5 and mapping[0]['source_end']==3.5
    assert abs(out[0])<1e-6 and abs(out[-1])<1e-6


def test_new_take_disables_cuts_even_for_identical_audio(client):
    c=client;p=generate(c,create(c,script='旁白：你好世界'));base='/api/projects/'+p['id'];sid=p['segments'][0]['id'];url=base+'/segments/'+sid
    p=c.post(url+'/tempo',json={'revision':p['revision'],'regions':[],'cuts':[{'start':2,'end':2.4}]}).json()
    old=c.post(url+'/preview',json={'revision':p['revision']}).json()
    p=generate(c,p,segment_id=sid,force=True)
    assert p['segments'][0]['tempo_status']=='stale'
    new=c.post(url+'/preview',json={'revision':p['revision']}).json()
    assert new['url']!=old['url'] and abs(new['duration']-6)<.01

# 最后更新：2026-09-09 · Astra


def test_frontend_time_mapping_across_cuts_and_speed(tmp_path):
    import subprocess
    from pathlib import Path
    root=Path(__file__).resolve().parent.parent
    compiled=subprocess.run([str(root/'frontend/node_modules/.bin/tsc'),str(root/'frontend/src/timeMapping.ts'),'--target','ES2022','--module','commonjs','--outDir',str(tmp_path),'--skipLibCheck'],capture_output=True,text=True)
    assert compiled.returncode==0,compiled.stdout+compiled.stderr
    script="""const assert=require('node:assert/strict');const {sourceToOutput,outputToSource}=require('./timeMapping.js');
    const map=[{source_start:0,source_end:2,output_start:0,output_end:1,speed:2},{source_start:3,source_end:5,output_start:1,output_end:5,speed:.5}];
    assert.equal(sourceToOutput(1,map),.5);assert.equal(sourceToOutput(2.5,map),1);assert.equal(sourceToOutput(4,map),3);
    assert.equal(outputToSource(.5,map),1);assert.equal(outputToSource(1,map),3);assert.equal(outputToSource(3,map),4);
    assert.equal(outputToSource(5,map),5);assert.equal(sourceToOutput(99,map),5);assert.equal(sourceToOutput(0,[]),0);
    """
    checked=subprocess.run(['node','-e',script],cwd=tmp_path,capture_output=True,text=True)
    assert checked.returncode==0,checked.stdout+checked.stderr

# 最后更新：2026-09-09 · Astra
