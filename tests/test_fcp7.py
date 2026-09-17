"""XML export regressions; integration acceptance remains with the reviewer."""
import io
import zipfile
from fractions import Fraction
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import pytest
from runtime.fcp7 import frame, timeline_xml, clip_name, FPS_CHOICES
from test_workflow import client, create, generate


def manifest(count=32, samples=67313, pause=6000):
    return {'sample_rate':24000, 'total_samples':count*(samples+pause)-pause,
        'segments':[{'index':i+1,'file':f'audio/{i+1:04d}_旁白.wav','text':'A & B <门> "hello"',
            'samples':samples,'start_sample':i*(samples+pause),'end_sample':i*(samples+pause)+samples} for i in range(count)]}


@pytest.mark.parametrize('fps', FPS_CHOICES)
def test_independent_rounding_including_long_timeline(fps):
    m=manifest(count=2000)
    clips=ET.fromstring(timeline_xml(m,fps)).findall('.//clipitem')
    for row,c in zip(m['segments'],clips,strict=True):
        for sample_key,xml_key in [('start_sample','start'),('end_sample','end')]:
            actual=int(c.findtext(xml_key))
            exact=Fraction(row[sample_key]*fps,24000)
            assert abs(actual-exact)<=Fraction(1,2)
            assert actual==int(exact+Fraction(1,2))
    assert int(clips[-1].findtext('start')) != 1999*frame(73313,24000,fps)


@pytest.mark.parametrize('fps', FPS_CHOICES)
def test_half_frame_ties_and_large_integer_precision(fps):
    # Choose a sample rate with exact half-frame sample positions for every fps.
    rate=240000
    for k in (0,1,10**16):
        boundary=(2*k+1)*rate//(2*fps)
        assert frame(boundary-1,rate,fps)==k
        assert frame(boundary,rate,fps)==k+1
        assert frame(boundary+1,rate,fps)==k+1


def test_xml_text_paths_and_zero_length():
    m=manifest(count=1)
    c=ET.fromstring(timeline_xml(m)).find('.//clipitem')
    assert c.findtext('name')==m['segments'][0]['text']
    assert unquote(c.findtext('file/pathurl'))=='delivery/audio/0001_旁白.wav'
    assert len(clip_name('中'*200))==120 and clip_name('a\x00b')=='ab'
    with pytest.raises(ValueError,match='太短'):timeline_xml(manifest(count=1,samples=1))
    m['segments'][0]['file']='../outside.wav'
    with pytest.raises(ValueError,match='相对路径'):timeline_xml(m)


@pytest.mark.parametrize('fps',[23,29.97,True,'30',0])
def test_invalid_fps(fps):
    with pytest.raises(ValueError):timeline_xml(manifest(),fps)


def zip_members(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:return {n:z.read(n) for n in z.namelist()}


def test_api_defaults_fps_downloads_and_preserves_existing_exports(client):
    p=generate(client,create(client));base='/api/projects/'+p['id'];body={'revision':p['revision']}
    links=client.post(base+'/export/create',json=body).json()
    before={name:client.get(url).content for name,url in links.items()}
    directory=client.app.state.store.directory(p['id'])
    source={f.name:(f.read_bytes(),f.stat().st_mtime_ns) for f in (directory/'audio').glob('*.wav')}
    saved=(directory/'project.json').read_bytes()
    for fps in FPS_CHOICES:
        response=client.post(base+'/export/xml',json=body if fps==30 else {**body,'video_fps':fps})
        assert response.status_code==200,response.text
        exported=response.json();from runtime.tempo import ffmpeg_path;assert len(exported)==(8 if ffmpeg_path() else 7) and ('full.mp3' in exported)==bool(ffmpeg_path())   # the MP3 rides along where ffmpeg is
        tree=ET.fromstring(client.get(exported[f'timeline-{fps}fps.xml']).content)
        assert tree.findtext('.//sequence/rate/timebase')==str(fps)
        assert [c.findtext('name') for c in tree.findall('.//clipitem')]==[s['text'] for s in p['segments']]
        for name,data in before.items():
            actual=client.get(exported[name]).content
            assert zip_members(actual)==zip_members(data) if name=='delivery.zip' else actual==data
        assert 'delivery/audio' in client.get(exported['timeline-README.txt']).text
    assert (directory/'project.json').read_bytes()==saved
    assert source=={f.name:(f.read_bytes(),f.stat().st_mtime_ns) for f in (directory/'audio').glob('*.wav')}
    for fps in FPS_CHOICES:assert client.get(base+f'/export/{p["revision"]}/timeline-{fps}fps.xml').status_code==200
    for invalid in (True,30.0,'30'):
        assert client.post(base+'/export/xml',json={**body,'video_fps':invalid}).status_code==422
    assert client.post(base+'/export/xml',json={**body,'video_fps':29}).status_code==400
    assert client.post(base+'/export/xml',json={'revision':p['revision']+1}).status_code==409
    p=client.patch(base,json={**body,'segment_id':p['segments'][0]['id'],'text':'Changed.'}).json()
    assert client.post(base+'/export/xml',json={'revision':p['revision']}).status_code==400

# 最后更新：2026-09-11 · Astra
