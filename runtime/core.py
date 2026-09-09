"""Atomic local projects, edit history and content-addressed audio. Astra, 2026-09-09."""
import copy
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from .audio import PROCESSING_VERSION
from .content_check import check_status
from .listening import listening_status
from .tempo import edit_status
from .rhythm import VERSION as RHYTHM_VERSION
from .engines import VOICES, generation_parameters, reference_parameters

def uid():
    return uuid.uuid4().hex

def parse_script(script, language):
    if language not in ('zh','en'):
        raise ValueError('Choose Chinese or English')
    segments = []
    for number, line in enumerate(script.splitlines(), 1):
        if not line.strip():
            continue
        pieces = re.split('[:：]', line.strip(), maxsplit=1)
        if len(pieces) != 2 or not all(x.strip() for x in pieces):
            raise ValueError(f'Line {number}: use Speaker: sentence')
        speaker, text = (x.strip() for x in pieces)
        if len(speaker) > 80 or len(text) > (60 if language == 'zh' else 240):
            raise ValueError(f'Line {number}: split long text into shorter labelled sentences')
        segments.append({'id':uid(), 'speaker':speaker, 'text':text, 'spoken_as':'', 'audio':None, 'error':None})
    if not 1 <= len(segments) <= 500:
        raise ValueError('A project needs 1–500 labelled lines')
    return segments

def fingerprint(project, segment, engine):
    data = {'text':segment.get('spoken_as') or segment['text'], 'voice':project['voices'][segment['speaker']],
            'language':project['language'], 'engine':engine.identity, 'seed':260909+segment.get('take',0),
            **generation_parameters(project['language']),
            'runtime':'mlx-audio-0.5.1', 'processing':PROCESSING_VERSION}
    profile = project.get('voice_profiles',{}).get(segment['speaker'])
    if profile:
        data.update(reference_parameters())
        data.update({'engine':getattr(engine,'reference_identity','unavailable'),
                     'reference_sha256':profile['sha256'],'reference_text':profile['text'],
                     'mode':'fixed_synthetic_reference-v1'})
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

def edit_state(project):
    return copy.deepcopy({**{k:project[k] for k in ('name','language','voices','segments','pause_ms')},'voice_profiles':project.get('voice_profiles',{}), 'archived':project.get('archived',False), 'speech_rate':project.get('speech_rate',1.0)})

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        for path in self.root.glob('*/project.json'):
            data = json.loads(path.read_text())
            if data.get('job',{}).get('status') == 'running':
                data['job']['status'] = 'interrupted'
                self.write(data)

    def directory(self, project_id):
        if not re.fullmatch('[a-f0-9]{32}', project_id):
            raise ValueError('Invalid project ID')
        return self.root / project_id

    def read(self, project_id):
        p=json.loads((self.directory(project_id)/'project.json').read_text())
        p.setdefault('voice_profiles',{})
        p.setdefault('archived',False)
        p.setdefault('speech_rate',1.0)
        return p

    def write(self, data):
        path = self.directory(data['id'])
        path.mkdir(exist_ok=True)
        temporary = path / 'project.json.tmp'
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path / 'project.json')

    def create(self, name, script, language, *, segments=None):
        if segments is None:
            segments = parse_script(script, language)
        presets = ['Vivian','Uncle_Fu','Serena','Dylan'] if language == 'zh' else ['Ryan','Aiden']
        voices = {s:presets[i%len(presets)] for i,s in enumerate(dict.fromkeys(x['speaker'] for x in segments))}
        data = {'schema_version':1, 'id':uid(), 'name':name.strip() or 'Untitled', 'language':language,
                'revision':0, 'source_script':script, 'voices':voices, 'segments':segments, 'pause_ms':250,
                'history':[], 'future':[], 'job':{'status':'idle'}, 'synthetic_audio':True}
        self.write(data)
        return data

    def duplicate(self, project_id, revision):
        with self.lock:
            original=self.read(project_id)
            if original['revision']!=revision or original['job']['status']=='running':
                raise RuntimeError('工程已改变或正在处理，请重新载入后再复制。')
            source=self.directory(project_id)
            if source.is_symlink():raise ValueError('不能复制链接形式的工程目录。')
            data=copy.deepcopy(original)
            data.update(id=uid(),name=original['name'][:114]+' · 副本',revision=0,history=[],future=[],job={'status':'idle'},archived=False)
            target=self.directory(data['id']);target.mkdir()
            try:
                for folder in ('audio','references'):
                    src=source/folder
                    if not src.exists() and not src.is_symlink():continue
                    if src.is_symlink() or any(p.is_symlink() for p in src.rglob('*')):
                        raise ValueError('声音目录含链接，无法直接复制；请先使用普通本地文件。')
                    shutil.copytree(src,target/folder,copy_function=shutil.copy2)
                self.write(data)
            except BaseException:
                shutil.rmtree(target)
                raise
            return data

    def edit(self, project_id, revision, change, action='edit'):
        with self.lock:
            p = self.read(project_id)
            if p['revision'] != revision or p['job']['status'] == 'running':
                raise RuntimeError('工程已在其他窗口改变，或正在处理。请重新载入已保存版本后再编辑。')
            if action in ('undo','redo'):
                source, target = ('history','future') if action == 'undo' else ('future','history')
                if not p[source]:
                    return p
                p[target].append(edit_state(p))
                restored=p[source].pop()
                restored.setdefault('voice_profiles',{})
                restored.setdefault('archived',False)
                restored.setdefault('speech_rate',1.0)
                p.update(restored)
            else:
                before = edit_state(p)
                change(p)
                p['history'].append(before)
                p['history'] = p['history'][-40:]
                p['future'] = []
            p['revision'] += 1
            self.write(p)
            return p

    def public(self, p, engine, checker=None):
        result = copy.deepcopy(p)
        result.setdefault('voice_profiles',{})
        result.setdefault('archived',False)
        result.setdefault('speech_rate',1.0)
        result['can_undo'], result['can_redo'] = bool(p['history']), bool(p['future'])
        result.pop('history'); result.pop('future')
        for s in result['segments']:
            current = fingerprint(p, s, engine)
            audio = s.get('audio')
            s['status'] = 'failed' if s.get('error') else 'pending'
            if audio and audio['fingerprint'] == current and (self.directory(p['id'])/'audio'/(current+'.wav')).exists():
                s['status'] = 'ready'
            s['check_status']=check_status(s,current,getattr(checker,'identity',None))
            audio_stat=None
            if s['status']=='ready':
                stat=(self.directory(p['id'])/'audio'/(current+'.wav')).stat()
                audio_stat=[stat.st_size,stat.st_mtime_ns]
                if s.get('content_check') and s['content_check'].get('audio_stat')!=audio_stat:s['check_status']='stale'
            s['tempo_status']=edit_status(s,audio_stat) if s['status']=='ready' else ('stale' if s.get('tempo_edit') else 'none')
            rhythm=s.get('rhythm_check')
            s['rhythm_status']='not_checked'
            if rhythm:
                if (s['status']!='ready' or rhythm.get('source_fingerprint')!=current or rhythm.get('audio_stat')!=audio_stat
                    or rhythm.get('version')!=RHYTHM_VERSION or rhythm.get('expected_text')!=(s.get('spoken_as') or s['text'])):s['rhythm_status']='stale'
                elif rhythm.get('error'):s['rhythm_status']='error'
                else:s['rhythm_status']='review' if rhythm.get('markers') else 'checked'
            s['listening_status']=listening_status(s,current,audio_stat,p.get('speech_rate',1.0))
        return result

# 最后更新：2026-09-09 · Astra
