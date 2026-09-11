"""Evidence for Claude Hera's portable-delivery criteria; no NLE compatibility claims."""
import csv
import html
import io
import json
from pathlib import Path, PurePosixPath
import zipfile
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.audio import export_audio, timestamp
from runtime.tempo import ffmpeg_path
from test_workflow import HEADERS, create, generate
from test_timeline import SpeechTone


def inspect_package(folder,full,rate,project,legacy):
    manifest=json.loads((folder/'timeline.json').read_text())
    with (folder/'timeline.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==len(manifest['segments'])==len(project['segments'])
    reconstructed=np.zeros(manifest['total_samples'],dtype=np.int16)
    srt=(folder/'subtitles.srt').read_text();vtt=(folder/'subtitles.vtt').read_text()
    assert vtt.startswith('WEBVTT\n\n') and manifest['reconstruction_tolerance_samples']==0
    for row,entry,segment,old in zip(rows,manifest['segments'],project['segments'],legacy['segments'],strict=True):
        relative=PurePosixPath(entry['file'])
        assert not relative.is_absolute() and '..' not in relative.parts and '\\' not in entry['file']
        assert row['file']==entry['file'] and (folder/relative).resolve().is_relative_to(folder.resolve())
        assert entry['speaker']==row['speaker']==segment['speaker']
        assert entry['text']==row['text']==segment['text']
        assert relative.name.startswith(f"{entry['index']:04d}_")
        pcm,sr=sf.read(folder/relative,dtype='int16')
        assert pcm.ndim==1 and sr==rate==entry['sample_rate']==manifest['sample_rate']
        assert len(pcm)==entry['samples']==entry['end_sample']-entry['start_sample']
        assert int(row['start_sample'])==entry['start_sample']==old['file_start_sample']
        assert int(row['end_sample'])==entry['end_sample']==old['file_end_sample']
        assert entry['duration']==len(pcm)/rate and float(row['start'])==entry['start_sample']/rate
        reconstructed[entry['start_sample']:entry['end_sample']]=pcm
        assert entry['speech_start_sample']==old['speech_start_sample']
        assert entry['speech_end_sample']==old['speech_end_sample']
        start=timestamp(entry['speech_start_sample'],rate);end=timestamp(entry['speech_end_sample'],rate)
        assert start+' --> '+end in srt
        assert start.replace(',','.')+' --> '+end.replace(',','.') in vtt
        assert html.escape(entry['text'],quote=False) in vtt
    assert len(reconstructed)==len(full) and np.array_equal(reconstructed,full)
    assert not list(folder.rglob('*.safetensors'))
    return manifest


@pytest.mark.parametrize('language,mode,pause_ms',[
    ('zh','plain',0),('en','plain',250),('zh','tempo',150),('en','cuts',500),('zh','clips',1000),('en','global',250)])
def test_portable_package_matches_final_audio_and_legacy_exports(tmp_path,monkeypatch,language,mode,pause_ms):
    if mode!='plain' and not ffmpeg_path():pytest.skip('Existing FFmpeg required for tempo/clip checks')
    script='旁/白：窗外的雨停了。\n小雪：我们出去走走。' if language=='zh' else 'Narrator: She saw the <door>, and waited.\nMira: Shall we go outside?'
    with TestClient(create_app(tmp_path/'projects',SpeechTone()),base_url='http://127.0.0.1',headers=HEADERS) as c:
        p=generate(c,create(c,language,script));base='/api/projects/'+p['id'];sid=p['segments'][0]['id']
        r=c.patch(base,json={'revision':p['revision'],'pause_ms':pause_ms});assert r.status_code==200;p=r.json()
        if mode=='global':
            p=c.patch(base,json={'revision':p['revision'],'speech_rate':1.2}).json()
        elif mode in ('tempo','cuts'):
            body={'revision':p['revision'],'regions':[{'start':3,'end':6,'speed':1.5}] if mode=='tempo' else [],'cuts':[{'start':1,'end':2}] if mode=='cuts' else []}
            r=c.post(base+'/segments/'+sid+'/tempo',json=body);assert r.status_code==200,r.text;p=r.json()
        elif mode=='clips':
            r=c.post(base+'/segments/'+sid+'/clips',json={'revision':p['revision'],'clips':[
                {'id':'second','source_start':3,'source_end':5,'speed':1.5},
                {'id':'first','source_start':0,'source_end':1,'speed':.75}]})
            assert r.status_code==200,r.text;p=r.json()
        store=c.app.state.store;audio=store.directory(p['id'])/'audio'
        originals={f.name:(f.read_bytes(),f.stat().st_mtime_ns) for f in audio.glob('*.wav')}
        # Existing exporter is the baseline; enabling delivery must not alter its four artifacts.
        with monkeypatch.context() as patch:
            patch.setattr('runtime.app.export_audio',lambda project,directory,output,**kwargs:export_audio(project,directory,output))
            r=c.post(base+'/export/create',json={'revision':p['revision']});assert r.status_code==200,r.text
            links=r.json();old={name:c.get(links[name]).content for name in ('full.wav','subtitles.srt','timeline.json','content-check.json')}
        r=c.post(base+'/export/create',json={'revision':p['revision']});assert r.status_code==200,r.text;links=r.json()
        assert all(c.get(links[name]).content==data for name,data in old.items())
        download=c.get(links['delivery.zip']);assert download.status_code==200
        with zipfile.ZipFile(io.BytesIO(download.content)) as bundle:
            assert all(name.startswith('delivery/') and '..' not in PurePosixPath(name).parts for name in bundle.namelist())
            bundle.extractall(tmp_path/'recipient')
        folder=tmp_path/'recipient'/'delivery';moved=folder.with_name('改名后的交付包');folder.rename(moved)
        full,rate=sf.read(io.BytesIO(old['full.wav']),dtype='int16')
        manifest=inspect_package(moved,full,rate,p,json.loads(old['timeline.json']))
        assert (moved/'subtitles.srt').read_bytes()==old['subtitles.srt']
        assert not (tmp_path/'recipient'/'delivery').exists()
        original,source_rate=sf.read(audio/(p['segments'][0]['audio']['fingerprint']+'.wav'),dtype='int16')
        if mode!='plain':assert manifest['segments'][0]['samples']!=len(original)
        assert originals=={f.name:(f.read_bytes(),f.stat().st_mtime_ns) for f in audio.glob('*.wav')}
        assert c.get(base+'/export/'+str(p['revision'])+'/other.zip').status_code==422

# 最后更新：2026-09-11 · Astra


def test_filename_carries_the_line_within_a_byte_budget(tmp_path):
    """Resolve labels a timeline clip with the file name and ignores the XML's
    name field, so the line has to be in the file name to be visible at all."""
    from runtime.delivery import _slug
    assert _slug('门上贴着一张纸，写着', 84) == '_门上贴着一张纸_写着'
    assert _slug('“……”', 84) == ''                     # punctuation only: no suffix
    assert _slug('', 84) == ''
    long = _slug('林' * 200, 84)
    assert len(long.encode()) <= 84 and long.startswith('_林')
    # A multi-byte character is never cut in half.
    assert long.encode().decode() == long
