"""One-off Resolve import probe; never imported by the product. Astra."""
import hashlib,json,math,subprocess,sys,urllib.request,zipfile
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'user-data/resolve-xml-spike'
REPORT=ROOT/'results/resolve-xml-spike.json'

def xml(package,mode='absolute',fps=25):
    manifest=json.loads((package/'timeline.json').read_text());rate=manifest['sample_rate']
    def frame(sample):return math.floor(sample*fps/rate+.5)
    def add(parent,name,value=None):
        e=ET.SubElement(parent,name)
        if value is not None:e.text=str(value)
        return e
    def framerate(parent):
        r=add(parent,'rate');add(r,'timebase',fps);add(r,'ntsc','FALSE')
    root=ET.Element('xmeml',version='5');seq=add(root,'sequence');seq.set('id',f'voxstage-{mode}-{fps}')
    add(seq,'name',f'VoxStage {mode} {fps}fps');add(seq,'duration',frame(manifest['total_samples']));framerate(seq)
    tc=add(seq,'timecode');framerate(tc);add(tc,'string','00:00:00:00');add(tc,'frame',0);add(tc,'displayformat','NDF')
    media=add(seq,'media');video=add(media,'video');fmt=add(video,'format');sc=add(fmt,'samplecharacteristics');framerate(sc);add(sc,'width',1920);add(sc,'height',1080);add(sc,'pixelaspectratio','square');add(sc,'fielddominance','none')
    audio=add(media,'audio');add(audio,'numOutputChannels',1);fmt=add(audio,'format');sc=add(fmt,'samplecharacteristics');add(sc,'depth',16);add(sc,'samplerate',rate);track=add(audio,'track')
    targets=[]
    for s in manifest['segments']:
        start,end=frame(s['start_sample']),frame(s['end_sample']);duration=end-start
        clip=add(track,'clipitem');clip.set('id',f'clip-{s["index"]}');add(clip,'name',Path(s['file']).name);add(clip,'enabled','TRUE');framerate(clip);add(clip,'duration',math.ceil(s['samples']*fps/rate));add(clip,'start',start);add(clip,'end',end);add(clip,'in',0);add(clip,'out',duration)
        file=add(clip,'file');file.set('id',f'file-{s["index"]}');add(file,'name',Path(s['file']).name)
        path=(package/s['file']).resolve().as_uri() if mode=='absolute' else quote(s['file'])
        add(file,'pathurl',path);framerate(file);add(file,'duration',math.ceil(s['samples']*fps/rate))
        fm=add(file,'media');fa=add(fm,'audio');sc=add(fa,'samplecharacteristics');add(sc,'depth',16);add(sc,'samplerate',rate);add(fa,'channelcount',1)
        st=add(clip,'sourcetrack');add(st,'mediatype','audio');add(st,'trackindex',1)
        targets.append({'index':s['index'],'file':s['file'],'original_start_sample':s['start_sample'],'original_end_sample':s['end_sample'],'xml_start_frame':start,'xml_end_frame':end,'rounding_start_ms':1000*(start/fps-s['start_sample']/rate),'rounding_end_ms':1000*(end/fps-s['end_sample']/rate)})
    add(track,'enabled','TRUE');add(track,'locked','FALSE');ET.indent(root)
    path=package/f'{mode}-{fps}.xml';ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
    return targets

def prepare():
    if REPORT.exists():
        raise SystemExit("本轮记录已存在；请保留原始证据，使用 analyze 复算。")
    WORK.mkdir(exist_ok=True)
    def call(path,body=None):
        req=urllib.request.Request('http://127.0.0.1:8765'+path,data=None if body is None else json.dumps(body).encode(),headers={'X-VoxStage':'1','Content-Type':'application/json'})
        return urllib.request.urlopen(req,timeout=60).read()
    pid='339de611b9bd427d9e11bf0b20a5c0fb';p=json.loads(call('/api/projects/'+pid));assert len(p['segments'])==32 and all(s['status']=='ready' for s in p['segments'])
    links=json.loads(call('/api/projects/'+pid+'/export/create',{'revision':p['revision']}));bundle=call(links['delivery.zip']);(WORK/'source.zip').write_bytes(bundle)
    with zipfile.ZipFile(WORK/'source.zip') as z:z.extractall(WORK/'original')
    package=WORK/'original/delivery';targets=xml(package);xml(package,'relative')
    report={'task':'DaVinci Resolve FCP7 XML 导入验证','author':'Astra','source':{'project_id':pid,'revision':p['revision'],'clips':32,'package_sha256':hashlib.sha256(bundle).hexdigest(),'new_synthesis':False},'fps':25,'sample_rate':24000,'targets':targets,'measurement_definitions':{'source_to_xml':'nearest frame, absolute positions independently rounded; no sequential accumulated rounding','xml_to_resolve':'XML target minus actual imported position','source_to_resolve':'actual imported position minus original sample position'},'observations':[],'sources':[{'purpose':'XML syntax only; not evidence of Resolve behavior','url':'https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/FinalCutPro_XML/Elements/Elements.html'}],'runs':[]}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(package/'absolute-25.xml');print('rounding maximum ms',max(abs(t['rounding_start_ms']) for t in targets))

def regression():
    r=subprocess.run([str(ROOT/'.venv/bin/python'),'-m','pytest','-q'],cwd=ROOT,capture_output=True,text=True)
    def clean(s):
        s=s.replace(str(ROOT),'<repo>');return s.replace(str(Path.home()),'<home>')
    d=json.loads(REPORT.read_text());d['runs'].append({'command':'.venv/bin/python -m pytest -q','exit_code':r.returncode,'stdout':clean(r.stdout),'stderr':clean(r.stderr)});REPORT.write_text(json.dumps(d,ensure_ascii=False,indent=2));print(clean(r.stdout))

def analyze():
    """Recalculate from files exported by Resolve, never from input XML alone."""
    from fractions import Fraction as F
    d=json.loads(REPORT.read_text())
    x=ET.parse(WORK/'resolve-absolute.fcpxml')
    clips=x.findall('.//sequence/spine/asset-clip')
    assert len(clips)==len(d['targets'])==32
    actual=[];xml_error=[];source_error=[];gaps=[]
    for target,c in zip(d['targets'],clips,strict=True):
        assert c.get('name')==Path(target['file']).name
        start=F(c.get('offset')[:-1]);duration=F(c.get('duration')[:-1]);actual.append((start,duration))
        xml_error.append(float((F(target['xml_start_frame'],d['fps'])-start)*1000))
        source_error.append(float((start-F(target['original_start_sample'],d['sample_rate']))*1000))
    for i in range(31):
        original=F(d['targets'][i+1]['original_start_sample']-d['targets'][i]['original_end_sample'],d['sample_rate'])
        gaps.append(float((actual[i+1][0]-sum(actual[i])-original)*1000))
    moved=ET.parse(WORK/'resolve-relative-relinked.fcpxml').findall('.//sequence/spine/asset-clip')
    assert [c.attrib for c in moved]==[c.attrib for c in clips]
    result={'actual_clips':len(clips),'max_xml_target_minus_actual_ms':max(map(abs,xml_error)),
            'max_actual_minus_original_start_ms':max(map(abs,source_error)),
            'last_minus_first_start_drift_ms':source_error[-1]-source_error[0],
            'max_gap_change_ms':max(map(abs,gaps)),'relinked_positions_identical':True}
    d['reproduce_analysis']={'command':'.venv/bin/python results/resolve_xml_spike.py analyze',**result}
    REPORT.write_text(json.dumps(d,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    {'prepare':prepare,'regression':regression,'analyze':analyze}[sys.argv[1]]()
# 最后更新：2026-09-11 · Astra
