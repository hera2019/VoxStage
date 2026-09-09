"""Independent blocks affect actual PCM, not just screen geometry. Astra, 2026-09-09."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.clips import clip_plan,validate_clips,render_clips
from test_workflow import HEADERS,create,generate
from test_timeline import SpeechTone


def test_order_changes_real_audio_not_just_metadata():
    rate=24000;t=np.arange(rate*2)/rate;pcm=np.r_[.2*np.sin(2*np.pi*440*t),.2*np.sin(2*np.pi*880*t)]
    clips=[{'id':'second','source_start':2,'source_end':4,'speed':1},{'id':'first','source_start':0,'source_end':2,'speed':2}]
    output,mapping=render_clips(pcm,rate,clips,1)
    for start,expected in ((.5,880),(2.2,440)):
        window=output[round(start*rate):round((start+.3)*rate)]
        hz=np.fft.rfftfreq(len(window),1/rate)[np.argmax(abs(np.fft.rfft(window)))];assert abs(hz-expected)<5
    assert abs(len(output)/rate-3)<.12
    assert [m['clip_id'] for m in mapping]==['second','first']
    assert mapping[0]['source_start']==2 and mapping[1]['source_start']==0


def test_legacy_cuts_rates_convert_without_lost_or_repeated_content():
    edit={'regions':[{'start':3,'end':6,'speed':1.5}],'cuts':[{'start':2,'end':2.4}]}
    clips=clip_plan(edit,6)
    assert [(c['source_start'],c['source_end'],c['speed']) for c in clips]==[(0,2,None),(2.4,3,None),(3,6,1.5)]
    assert validate_clips(clips,6)==clips


@pytest.mark.parametrize('clips',[
 [], [{'id':'x','source_start':0,'source_end':.1,'speed':1}],
 [{'id':'x','source_start':0,'source_end':7,'speed':1}],
 [{'id':'x','source_start':0,'source_end':1,'speed':2.01}],
 [{'id':'x','source_start':0,'source_end':1,'speed':1},{'id':'x','source_start':1,'source_end':2,'speed':1}],
 [{'id':'x','source_start':0,'source_end':2,'speed':1},{'id':'y','source_start':1,'source_end':3,'speed':1}],
])
def test_invalid_blocks_are_rejected(clips):
    with pytest.raises(ValueError):validate_clips(clips,6)


def test_blocks_save_stretch_split_reorder_undo_and_export(tmp_path):
    with TestClient(create_app(tmp_path,SpeechTone(),checker=SimpleNamespace(ready=False,identity='fixture')),base_url='http://127.0.0.1',headers=HEADERS) as c:
        p=generate(c,create(c,script='旁白：你好世界'));url='/api/projects/'+p['id'];sid=p['segments'][0]['id'];base=url+'/segments/'+sid
        root=c.app.state.store.directory(p['id']);source=root/'audio'/(p['segments'][0]['audio']['fingerprint']+'.wav');original=source.read_bytes()
        before=c.get(base+'/clips').json();assert len(before['clips'])==1
        clips=[{'id':'b','source_start':3,'source_end':6,'speed':.75},{'id':'a','source_start':0,'source_end':3,'speed':1.5}]
        response=c.post(base+'/clips',json={'revision':p['revision'],'clips':clips});assert response.status_code==200,response.text
        p=response.json();preview=c.post(base+'/preview',json={'revision':p['revision']}).json()
        assert abs(preview['duration']-6)<.15
        assert [x['clip_id'] for x in preview['mapping']]==['b','a']
        links=c.post(url+'/export/create',json={'revision':p['revision']}).json()
        assert c.get(preview['url']).content==c.get(links['full.wav']).content
        assert c.get(links['content-check.json']).json()['segments'][0]['edited_content_requires_review']
        # Stretch first block further; real output duration must change.
        clips[0]['speed']=.5
        p=c.post(base+'/clips',json={'revision':p['revision'],'clips':clips}).json()
        after=c.post(base+'/preview',json={'revision':p['revision']}).json();assert after['duration']>preview['duration']+1.8
        p=c.post(url+'/undo',json={'revision':p['revision']}).json();assert p['segments'][0]['tempo_edit']['clips'][0]['speed']==.75
        p=generate(c,p,segment_id=sid,force=True)
        assert p['segments'][0]['tempo_status']=='stale'
        assert len(c.get(base+'/clips').json()['clips'])==1
        assert source.read_bytes()==original


def test_frontend_stretch_split_and_actual_layout(tmp_path):
    root=Path(__file__).resolve().parent.parent
    compiled=subprocess.run([str(root/'frontend/node_modules/.bin/tsc'),str(root/'frontend/src/clipEditing.ts'),'--target','ES2022','--module','commonjs','--outDir',str(tmp_path),'--skipLibCheck'],capture_output=True,text=True)
    assert compiled.returncode==0,compiled.stdout+compiled.stderr
    script="""const a=require('node:assert/strict');const {layoutClips,stretchClip,splitClip}=require('./clipEditing.js');
    const c={id:'a',source_start:0,source_end:4,speed:1};a.equal(stretchClip(c,8).speed,.5);a.equal(stretchClip(c,2).speed,2);a.equal(stretchClip(c,100).speed,.5);
    const blocks=layoutClips([c],1,[{clip_id:'a',source_start:0,source_end:4,output_start:0,output_end:3.99,speed:1}]);a.equal(blocks[0].end,3.99);
    a.equal(layoutClips([{...c,speed:2}],1,[{clip_id:'a',source_start:0,source_end:4,output_start:0,output_end:3.99,speed:1}])[0].end,2);
    a.equal(layoutClips([{...c,source_end:2}],1,[{clip_id:'a',source_start:0,source_end:4,output_start:0,output_end:3.99,speed:1}])[0].end,2);
    const split=splitClip([c],blocks[0],1.995,'b');a.equal(split[0].source_end,2);a.equal(split[1].source_start,2);a.equal(split[1].speed,1);
    a.throws(()=>splitClip([c],blocks[0],.001,'b'));a.equal(layoutClips([{...c,speed:null}],2)[0].end,2);
    """
    checked=subprocess.run(['node','-e',script],cwd=tmp_path,capture_output=True,text=True);assert checked.returncode==0,checked.stdout+checked.stderr

# 最后更新：2026-09-09 · Astra


def test_legacy_boundary_sliver_preserves_content_and_can_edit():
    edit={'regions':[{'start':.819,'end':3.249,'speed':1}],
          'cuts':[{'start':3.254,'end':3.697},{'start':4.562,'end':4.977}]}
    clips=clip_plan(edit,12)
    assert validate_clips(clips,12)
    assert [(c['source_start'],c['source_end']) for c in clips]==[(0,.819),(.819,3.254),(3.697,4.562),(4.977,12)]
    assert sum(c['source_end']-c['source_start'] for c in clips)==pytest.approx(12-.443-.415)
    for proposed in [clips[1:], [{**c,'speed':1.2} for c in clips], [dict(clips[0],source_end=.4),dict(clips[0],id='split',source_start=.4),*clips[1:]]]:
        pcm,mapping=render_clips(np.zeros(24000*12,dtype=np.float32),24000,proposed,1)
        assert len(pcm)>0 and len(mapping)==len(proposed)


def test_short_island_not_silently_deleted_or_joined_across_cut():
    clips=clip_plan({'cuts':[{'start':1,'end':2},{'start':2.005,'end':3}]},4)
    assert [(c['source_start'],c['source_end']) for c in clips]==[(0,1),(2,2.005),(3,4)]

# 最后更新：2026-09-09 · Astra
