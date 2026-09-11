"""Regression evidence for the externally supplied per-segment pause criteria."""
import copy
import hashlib
import io
import zipfile
import numpy as np
import pytest
import soundfile as sf
from runtime.audio import timestamp
from runtime.core import fingerprint
from test_workflow import client, create, generate
from test_script_rewrite import client as rewrite_client, make
from test_delivery import inspect_package


def patch(c,p,**fields):
    r=c.patch('/api/projects/'+p['id'],json={'revision':p['revision'],**fields})
    assert r.status_code==200,r.text
    return r.json()


def exported(c,p):
    r=c.post('/api/projects/'+p['id']+'/export/create',json={'revision':p['revision']})
    assert r.status_code==200,r.text
    links=r.json()
    return {name:c.get(url).content for name,url in links.items()}


def timeline(data):
    import json
    return json.loads(data['timeline.json'])


def originals(store,p):
    return {f.name:(hashlib.sha256(f.read_bytes()).hexdigest(),f.stat().st_mtime_ns)
            for f in (store.directory(p['id'])/'audio').glob('*.wav')}


@pytest.mark.parametrize('language',['zh','en'])
@pytest.mark.parametrize('default',[0,250])
def test_gap_shifts_audio_all_later_boundaries_subtitles_and_package(client,tmp_path,language,default):
    p=generate(client,create(client,language));store=client.app.state.store
    p=patch(client,p,pause_ms=default);sid=p['segments'][1]['id'];before=exported(client,p);old=timeline(before)
    source=originals(store,p);audio=[s['audio'] for s in p['segments']]
    old_fingerprints=[fingerprint(p,s,client.app.state.engine) for s in p['segments']]
    p=patch(client,p,segment_id=sid,pause_after=1000)
    assert all(s['status']=='ready' for s in p['segments'])
    assert [s['audio'] for s in p['segments']]==audio
    assert [fingerprint(p,s,client.app.state.engine) for s in p['segments']]==old_fingerprints
    after=exported(client,p);new=timeline(after);rate=new['sample_rate'];delta=round((1000-default)*rate/1000)
    assert new['total_samples']-old['total_samples']==delta
    oldpcm,_=sf.read(io.BytesIO(before['full.wav']),dtype='int16');pcm,_=sf.read(io.BytesIO(after['full.wav']),dtype='int16')
    boundary=old['segments'][1]['file_end_sample']
    assert np.array_equal(pcm,np.concatenate([oldpcm[:boundary],np.zeros(delta,dtype='int16'),oldpcm[boundary:]]))
    for i,(a,b) in enumerate(zip(old['segments'],new['segments'],strict=True)):
        for field in ('file_start_sample','file_end_sample','speech_start_sample','speech_end_sample'):
            assert b[field]-a[field]==(delta if i>1 else 0)
        assert (timestamp(b['speech_start_sample'],rate)+' --> '+timestamp(b['speech_end_sample'],rate)).encode() in after['subtitles.srt']
    with zipfile.ZipFile(io.BytesIO(after['delivery.zip'])) as z:z.extractall(tmp_path/'recipient')
    inspect_package(tmp_path/'recipient'/'delivery',pcm,rate,p,new)
    assert originals(store,p)==source
    # Clearing to inheritance is distinct from explicit zero and survives history/reload.
    url='/api/projects/'+p['id'];saved_revision=p['revision']
    p=client.post(url+'/undo',json={'revision':p['revision']}).json()
    assert p['segments'][1].get('pause_after') is None
    assert exported(client,p)['full.wav']==before['full.wav']
    p=client.post(url+'/redo',json={'revision':p['revision']}).json()
    assert p['segments'][1]['pause_after']==1000
    p=patch(client,p,segment_id=sid,pause_after=None)
    assert exported(client,p)['full.wav']==before['full.wav']
    assert client.get(url).json()['segments'][1]['pause_after'] is None
    assert client.patch(url,json={'revision':saved_revision,'segment_id':sid,'pause_after':0}).status_code==409


def test_last_sentence_and_single_sentence_never_append_silence(client):
    for script in ('旁白：第一句。','旁白：第一句。\n旁白：第二句。'):
        p=generate(client,create(client,script=script));before=exported(client,p)
        p=patch(client,p,segment_id=p['segments'][-1]['id'],pause_after=2000)
        after=exported(client,p)
        assert timeline(after)['total_samples']==timeline(before)['total_samples']
        assert after['full.wav']==before['full.wav'] and after['subtitles.srt']==before['subtitles.srt']
        assert p['segments'][-1]['pause_after']==2000 and all(s['status']=='ready' for s in p['segments'])


def test_inheritance_follows_global_but_explicit_zero_remains_zero(client):
    p=generate(client,create(client));ids=[s['id'] for s in p['segments']]
    p=patch(client,p,segment_id=ids[0],pause_after=0)
    p=patch(client,p,segment_id=ids[1],pause_after=None)
    p=patch(client,p,pause_ms=2000);t=timeline(exported(client,p));rate=t['sample_rate']
    assert [b['file_start_sample']-a['file_end_sample'] for a,b in zip(t['segments'],t['segments'][1:])]==[0,2*rate,2*rate]
    before=copy.deepcopy(p);p=patch(client,p,segment_id=ids[1],text=p['segments'][1]['text'])
    assert p['segments'][1]['pause_after'] is None and p['segments'][0]['pause_after']==0
    # A persisted synthesis error must not be cleared by a timing-only edit.
    saved=client.app.state.store.read(p['id']);saved['segments'][0]['error']='fixture failure';client.app.state.store.write(saved)
    p=patch(client,p,segment_id=ids[0],pause_after=333)
    assert p['segments'][0]['error']=='fixture failure'


@pytest.mark.parametrize('value',[-1,2001,1.5,True,'1000'])
def test_invalid_pause_is_rejected_without_mutation(client,value):
    p=create(client);url='/api/projects/'+p['id'];before=client.app.state.store.read(p['id'])
    r=client.patch(url,json={'revision':p['revision'],'segment_id':p['segments'][0]['id'],'pause_after':value})
    assert r.status_code==422
    assert client.app.state.store.read(p['id'])==before


def test_pause_requires_existing_sentence_and_respects_busy_guard(client):
    p=create(client);url='/api/projects/'+p['id'];store=client.app.state.store;before=store.read(p['id'])
    for extra in ({},{'segment_id':'not-a-sentence'}):
        assert client.patch(url,json={'revision':p['revision'],'pause_after':1000,**extra}).status_code==400
        assert store.read(p['id'])==before
    before['job']['status']='running';store.write(before)
    assert client.patch(url,json={'revision':p['revision'],'segment_id':p['segments'][0]['id'],'pause_after':1000}).status_code==409
    assert store.read(p['id'])==before


def reslice(c,p):
    url='/api/projects/'+p['id']+'/script';body={'revision':p['revision'],'source_script':p['source_script']}
    preview=c.post(url,json=body);assert preview.status_code==200,preview.text
    r=c.post(url,json={**body,'labels':preview.json()['labels']});assert r.status_code==200,r.text
    return r.json()


def test_explicit_reslice_preserves_each_unchanged_sentence_pause(rewrite_client):
    c=rewrite_client;p=make(c);expected={}
    for i,s in enumerate(p['segments']):
        value=[0,333,None,1000,2000][i%5];p=patch(c,p,segment_id=s['id'],pause_after=value);expected[s['id']]=value
    p=reslice(c,p)
    assert {s['id']:s.get('pause_after') for s in p['segments']}==expected
    assert all(s['status']=='ready' for s in p['segments'])


def test_merge_discards_swallowed_pauses_and_undo_restores_them(rewrite_client):
    c=rewrite_client;p=make(c,'只剩下半个“雪”字。');store=c.app.state.store
    assert len(p['segments'])==3
    saved=store.read(p['id'])
    for i,s in enumerate(saved['segments']):s.update(speaker='旁白',kind='narration',pause_after=[333,1000,2000][i])
    store.write(saved);source=originals(store,p)
    merged=reslice(c,p)
    assert len(merged['segments'])==1 and merged['segments'][0].get('pause_after') is None
    merged=generate(c,merged);t=timeline(exported(c,merged))
    assert t['total_samples']==merged['segments'][0]['audio']['samples']
    assert all(originals(store,merged)[k]==v for k,v in source.items())
    undo=c.post('/api/projects/'+p['id']+'/undo',json={'revision':merged['revision']}).json()
    assert [s['pause_after'] for s in undo['segments']]==[333,1000,2000]

# 最后更新：2026-09-11 · Astra
