"""Loopback-only API and serial render queue. Astra, 2026-09-09."""
import argparse
import hashlib
import shutil
import json
import logging
import time
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .launcher import workspace_id
from .tempo import ffmpeg_path, valid_regions, valid_cuts, edit_status, change_tempo, VERSION as TEMPO_VERSION
from .audio import process_audio, export_audio, prepare_segment
from .clips import clip_plan, validate_clips
from .rhythm import analyze_file, analyze, VERSION as RHYTHM_VERSION
from .core import Store, fingerprint
from .voices import VoiceLibrary, is_custom, custom_id, PREFIX as CUSTOM_PREFIX
from .script_check import inspect as inspect_script, apply_fix
from .attribution import RoleDraftEngine, project_segments, source_units
from .content_check import WhisperChecker, compare_text, file_sha
from .engines import MlxEngine, FixtureEngine, VOICES

ROOT = Path(__file__).resolve().parent.parent

class ImportRequest(BaseModel):
    name: str = Field(default='Untitled', max_length=120)
    script: str = Field(max_length=300000)
    language: Literal['zh','en']

class RoleLabel(BaseModel):
    id: str = Field(max_length=40)
    kind: Literal['narration','dialogue']
    speaker: str = Field(max_length=80)

class RoleDraftRequest(BaseModel):
    script: str = Field(min_length=1, max_length=3000)
    language: Literal['zh','en']

class RoleConfirmRequest(BaseModel):
    draft_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    name: str = Field(default='Untitled', max_length=120)
    labels: list[RoleLabel] = Field(min_length=1,max_length=80)

class AuditionRequest(BaseModel):
    voice: str = Field(max_length=40)
    text: str = Field(min_length=1, max_length=120)
    language: Literal['zh','en'] = 'zh'
    rate: float = Field(default=1.0, ge=0.5, le=2.0, allow_inf_nan=False)

class VoiceSaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    language: Literal['zh','en'] = 'zh'
    reference_text: str = Field(min_length=1, max_length=400)
    from_voice: str | None = Field(default=None, max_length=80)
    audio_base64: str | None = Field(default=None, max_length=8_000_000)
    consent_confirmed: bool = False

class VoiceRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)

class SettingsRequest(BaseModel):
    favourite_voices: list[str] = Field(default_factory=list, max_length=40)

class ScriptRequest(BaseModel):
    revision: int = Field(ge=0)
    source_script: str = Field(min_length=1, max_length=3000)
    labels: list[RoleLabel] | None = Field(default=None, max_length=200)

class ScriptFixRequest(BaseModel):
    source_script: str = Field(min_length=1, max_length=3000)
    kind: str = Field(max_length=40)

class EditRequest(BaseModel):
    speech_rate: float | None = Field(default=None, ge=0.5, le=2.0, allow_inf_nan=False)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    archived: bool | None = None
    revision: int = Field(ge=0)
    segment_id: str | None = None
    text: str | None = Field(default=None, max_length=500)
    spoken_as: str | None = Field(default=None, max_length=500)
    speaker: str | None = Field(default=None, min_length=1, max_length=80)
    voice: str | None = None
    pause_ms: int | None = Field(default=None, ge=0, le=2000)
    pause_after: int | None = Field(default=None, ge=0, le=2000, strict=True)

class TempoRegion(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    speed: float = Field(ge=.5, le=2, allow_inf_nan=False)

class CutRegion(BaseModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)

class TempoRequest(BaseModel):
    revision: int = Field(ge=0)
    regions: list[TempoRegion] = Field(max_length=20)
    cuts: list[CutRegion] | None = Field(default=None, max_length=40)

class ClipRequestItem(BaseModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
    source_start: float = Field(ge=0, allow_inf_nan=False)
    source_end: float = Field(gt=0, allow_inf_nan=False)
    speed: float | None = Field(default=None, ge=.5, le=2, allow_inf_nan=False)

class ClipsRequest(BaseModel):
    revision: int = Field(ge=0)
    clips: list[ClipRequestItem] = Field(min_length=1, max_length=40)

class RenderRequest(BaseModel):
    marked_only: bool = False
    revision: int = Field(ge=0)
    segment_id: str | None = None
    force: bool = False

class FixedVoiceRequest(BaseModel):
    revision: int = Field(ge=0)
    segment_id: str
    synthetic_reference_consent: bool = False

class CheckReviewRequest(BaseModel):
    revision: int = Field(ge=0)
    segment_id: str
    confirmed: bool = True

class ListeningRequest(BaseModel):
    revision: int = Field(ge=0)
    segment_id: str
    kind: Literal['tail','words','voice','pause','pace','other'] = 'other'
    note: str = Field(default='', max_length=300)
    clear: bool = False

class RevisionRequest(BaseModel):
    revision: int = Field(ge=0)

def _splice_source(project, segment, text):
    """Write an edited line back into the source script and shift what follows."""
    start, end = segment.get('source_start'), segment.get('source_end')
    if start is None or end is None or not project.get('source_script'):
        return
    script = project['source_script']
    if script[start:end] != segment['text']:
        return                                   # already out of step; do not guess
    project['source_script'] = script[:start] + text + script[end:]
    shift = len(text) - (end - start)
    segment['source_end'] = start + len(text)
    for other in project['segments']:
        if other is not segment and other.get('source_start') is not None and other['source_start'] >= end:
            other['source_start'] += shift
            other['source_end'] += shift


def create_app(data_root=None, engine=None, frontend=None, checker=None, role_engine=None):
    store = Store(data_root or ROOT/'user-data/projects')
    # Settings and auditions live beside the projects folder, never inside it:
    # Store scans its own root for project.json.
    workspace = store.root.parent
    library = VoiceLibrary(workspace/'voices')
    store.library = library
    engine = engine or MlxEngine(os.environ.get('VOXSTAGE_MODEL', ROOT/'user-data/models/qwen-customvoice'))
    checker = checker or WhisperChecker(ROOT/'user-data/asr-settings.json')
    role_engine = role_engine or RoleDraftEngine()
    drafts = store.root.parent / (store.root.name + '-role-drafts')
    drafts.mkdir(exist_ok=True)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='voxstage-render')
    cancel = threading.Event()
    active = {'project_id':None}

    @asynccontextmanager
    async def lifespan(app):
        yield
        cancel.set()
        executor.shutdown(wait=True)

    app = FastAPI(title='VoxStage', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store, app.state.engine, app.state.checker = store, engine, checker

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        host = request.headers.get('host','')
        hostname = host.split(':')[0]
        origin = request.headers.get('origin')
        if hostname not in ('127.0.0.1','localhost'):
            return JSONResponse({'detail':'Local access only'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != f'http://{host}'):
            return JSONResponse({'detail':'Cross-origin access denied'}, status_code=403)
        if request.method not in ('GET','HEAD'):
            if request.headers.get('x-voxstage') != '1':
                return JSONResponse({'detail':'Missing local request header'}, status_code=403)
            if int(request.headers.get('content-length','0')) > 400000:
                return JSONResponse({'detail':'Request too large'}, status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail':str(exc)}, status_code=400)

    @app.exception_handler(FileNotFoundError)
    async def missing(request, exc):
        return JSONResponse({'detail':'Project or audio not found'}, status_code=404)

    @app.exception_handler(RuntimeError)
    async def conflict(request, exc):
        return JSONResponse({'detail':str(exc)}, status_code=409)

    @app.get('/api/health')
    def health():
        return {'app':'VoxStage', 'workspace_id':workspace_id(ROOT), 'ready':True, 'pid':os.getpid()}

    @app.get('/api/config')
    def config():
        return {'engine':engine.label, 'engine_id':engine.identity, 'ready':engine.ready,
                'attribution_ready':role_engine.ready, 'speed_ready':bool(ffmpeg_path()),'checker_ready':checker.ready, 'checker_id':checker.identity, 'voices':VOICES, 'fixed_voice_ready':getattr(engine,'reference_ready',False), 'local_only':True, 'synthetic_audio':True}

    @app.get('/api/settings')
    def read_settings():
        path = workspace/'settings.json'
        stored = json.loads(path.read_text()) if path.is_file() else {}
        return {'favourite_voices': [v for v in stored.get('favourite_voices', []) if v in VOICES]}

    @app.post('/api/settings')
    def write_settings(body: SettingsRequest):
        favourites = list(dict.fromkeys(v for v in body.favourite_voices if v in VOICES))
        (workspace/'settings.json').write_text(
            json.dumps({'favourite_voices': favourites}, ensure_ascii=False, indent=1))
        return {'favourite_voices': favourites}

    @app.get('/api/voices/custom')
    def list_custom_voices():
        return library.list()

    @app.post('/api/voices/custom')
    def create_custom_voice(body: VoiceSaveRequest):
        """Keep a voice: either one the model just produced, or one supplied.

        Saving an audition means a good sample never has to be hunted for again,
        and a reference steadies delivery — which is the whole reason to keep it.
        """
        if bool(body.from_voice) == bool(body.audio_base64):
            raise ValueError('请二选一：从现有音色生成，或提供一段参考声音。')
        with store.lock:
            if active['project_id']:
                raise RuntimeError('正在处理其他任务，请稍后再建立音色。')
            active['project_id'] = 'voice-library'
        try:
            if body.from_voice:
                if body.from_voice not in VOICES and not (is_custom(body.from_voice) and library.label(body.from_voice)):
                    raise ValueError('没有这个音色。')
                if is_custom(body.from_voice):
                    source_entry = library.get(custom_id(body.from_voice))
                    pcm, rate, _ = engine.synthesize_reference(
                        body.reference_text, body.language, library.audio_path(source_entry['id']),
                        source_entry['reference_text'], 260909,
                        consent_confirmed=True, expected_sha256=source_entry['sha256'])
                else:
                    pcm, rate, _ = engine.synthesize(body.reference_text, body.from_voice, body.language, seed=260909)
                pcm, meta = process_audio(pcm, rate)
                entry = library.create(name=body.name, pcm=pcm, rate=meta['sample_rate'],
                    reference_text=body.reference_text, language=body.language,
                    source='generated', consent_confirmed=True, derived_from=body.from_voice)
            else:
                import base64, io
                try:
                    raw = base64.b64decode(body.audio_base64 or '', validate=True)
                    pcm, rate = sf.read(io.BytesIO(raw), dtype='float32')
                except (ValueError, RuntimeError, sf.LibsndfileError) as exc:
                    raise ValueError('无法读取这段声音；请提供 WAV 等常见未压缩格式。') from exc
                if getattr(pcm, 'ndim', 1) > 1:
                    pcm = pcm.mean(axis=1)
                entry = library.create(name=body.name, pcm=pcm, rate=rate,
                    reference_text=body.reference_text, language=body.language,
                    source='provided', consent_confirmed=body.consent_confirmed)
            return entry
        finally:
            with store.lock:
                active['project_id'] = None

    @app.patch('/api/voices/custom/{voice_id}')
    def rename_custom_voice(voice_id: str, body: VoiceRenameRequest):
        return library.rename(voice_id, body.name)

    @app.delete('/api/voices/custom/{voice_id}')
    def delete_custom_voice(voice_id: str):
        with store.lock:
            used = {json.loads(path.read_text())['name']
                    for path in store.root.glob('*/project.json')
                    if CUSTOM_PREFIX + voice_id in json.loads(path.read_text()).get('voices', {}).values()}
            return library.delete(voice_id, used)

    @app.get('/api/voices/custom/{voice_id}/audio')
    def custom_voice_audio(voice_id: str):
        return FileResponse(library.audio_path(voice_id), media_type='audio/wav')

    @app.post('/api/voices/audition')
    def audition_voice(body: AuditionRequest):
        """Hear a preset before committing a character to it.

        Choosing a voice is the first thing anyone does in a new project, and
        until now the only way to hear one was to build a project and generate a
        line with it. Auditions are written to a scratch directory and never
        touch a project.
        """
        if body.voice not in VOICES:
            raise ValueError('没有这个音色。')
        if not getattr(engine, 'ready', False):
            raise ValueError('声音引擎未就绪。')
        with store.lock:
            if active['project_id']:
                raise RuntimeError('正在处理其他任务，请稍后再试听。')
            active['project_id'] = 'voice-audition'
        try:
            pcm, rate, _ = engine.synthesize(body.text, body.voice, body.language, seed=260909)
            pcm, meta = process_audio(pcm, rate)
            rate = meta['sample_rate']
            # Rate here is a listening aid applied after synthesis, exactly as the
            # project speed control is; it does not change how a line is generated.
            if body.rate != 1.0:
                pcm = change_tempo(pcm, rate, body.rate)
            folder = workspace/'auditions'
            folder.mkdir(parents=True, exist_ok=True)
            for old in sorted(folder.glob('*.wav'))[:-8]:
                old.unlink(missing_ok=True)
            name = hashlib.sha256(
                f'{body.voice}|{body.text}|{body.language}|{body.rate}'.encode()).hexdigest()[:16]
            sf.write(folder/(name+'.wav'), pcm, rate, subtype='PCM_16')
            return {'url': f'/api/voices/audition/{name}.wav', 'seconds': len(pcm)/rate,
                    'voice': body.voice, 'rate': body.rate, 'synthetic_audio': True}
        finally:
            with store.lock:
                active['project_id'] = None

    @app.get('/api/voices/audition/{name}')
    def audition_file(name: str):
        if not re.fullmatch(r'[a-f0-9]{16}\.wav', name):
            raise ValueError('无效的试听文件名。')
        path = workspace/'auditions'/name
        if not path.is_file():
            raise ValueError('试听文件已清理，请重新生成。')
        return FileResponse(path, media_type='audio/wav')

    @app.post('/api/attribution/draft')
    def role_draft(body: RoleDraftRequest):
        from .core import uid
        draft_id = uid()
        with store.lock:
            if active['project_id']:
                raise RuntimeError('正在处理其他任务，请稍后再生成角色草稿。')
            active['project_id'] = 'role-draft'
        try:
            if hasattr(engine, 'unload'):
                engine.unload()
            result = role_engine.annotate(body.script, drafts/(draft_id+'.log'))
            # Validate even injected engines; no unbound model text reaches a project.
            from evals.speaker_attribution.source_units import bind_labels
            bind_labels(body.script,json.dumps({'labels':result['labels']}))
            record = {**result,'draft_id':draft_id,'source_script':body.script,'language':body.language}
            (drafts/(draft_id+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2))
            labels = {x['id']:x for x in result['labels']}
            return {'draft_id':draft_id,'units':[{**unit,**{k:labels[unit['id']][k] for k in ('kind','speaker')}} for unit in source_units(body.script)]}
        except (OSError, KeyError, TypeError) as exc:
            raise ValueError('角色草稿生成失败，请保留原稿后重试。') from exc
        finally:
            with store.lock:
                active['project_id'] = None

    @app.post('/api/attribution/confirm')
    def confirm_roles(body: RoleConfirmRequest):
        record = json.loads((drafts/(body.draft_id+'.json')).read_text())
        labels = [label.model_dump() for label in body.labels]
        segments = project_segments(record['source_script'], labels, record['language'])
        with store.lock:
            project = store.create(body.name, record['source_script'], record['language'], segments=segments)
            project['attribution'] = {'draft_id':body.draft_id,'model_sha256':record.get('model_sha256'),
                'model_labels':record['labels'],'confirmed_labels':labels,'human_confirmed':True}
            store.write(project)
            return store.public(project, engine, checker)

    @app.get('/api/projects')
    def projects(include_archived: bool = False):
        with store.lock:
            # Most recently touched first: a list ordered by folder name is a
            # list ordered by nothing anyone can see.
            return [{'id':p['id'],'name':p['name'],'language':p['language'],
                     'archived':p.get('archived',False),'updated_at':path.stat().st_mtime}
                    for path in sorted(store.root.glob('*/project.json'))
                    for p in [json.loads(path.read_text())] if include_archived or not p.get('archived',False)]

    @app.post('/api/projects')
    def import_project(body: ImportRequest):
        with store.lock:
            return store.public(store.create(body.name, body.script, body.language), engine, checker)

    @app.get('/api/projects/{project_id}')
    def get_project(project_id: str):
        with store.lock:
            return store.public(store.read(project_id), engine, checker)

    @app.patch('/api/projects/{project_id}')
    def edit_project(project_id: str, body: EditRequest):
        has_pause = 'pause_after' in body.model_fields_set
        if has_pause and not body.segment_id:
            raise ValueError('请先选择要设置停顿的句子。')
        def apply(p):
            if body.name is not None:
                if not body.name.strip():raise ValueError('工程名称不能为空。')
                p['name']=body.name.strip()
            if body.archived is not None:p['archived']=body.archived
            if body.speech_rate is not None:
                if body.speech_rate!=1.0 and not ffmpeg_path():raise ValueError('语速调节需要本机 FFmpeg。')
                p['speech_rate']=body.speech_rate
            if body.pause_ms is not None:
                p['pause_ms'] = body.pause_ms
            if body.segment_id:
                s = next((s for s in p['segments'] if s['id']==body.segment_id), None)
                if s is None:
                    raise ValueError('Unknown segment')
                if has_pause:
                    # D48: null means inheritance; a gap never changes synthesis identity.
                    s['pause_after'] = body.pause_after
                limit = 60 if p['language'] == 'zh' else 240
                for field in ('text','spoken_as'):
                    value = getattr(body, field)
                    if value is not None:
                        # One message per rule: a vague error sends people hunting.
                        if field == 'text' and not value.strip():
                            raise ValueError('这一句不能为空。要去掉它，请用「删除这一句」。')
                        if '\n' in value:
                            raise ValueError('一句里不能有换行。请删掉换行，或在「原稿编辑」里重新分句。')
                        if len(value) > limit:
                            raise ValueError(f'一句最多 {limit} 个字符，当前 {len(value)} 个。请在「原稿编辑」里拆成两句。')
                        if field == 'text' and value != s['text']:
                            # Keep the script and the lines telling the same story:
                            # otherwise the script editor would show stale text and
                            # applying it would silently undo this edit.
                            _splice_source(p, s, value)
                        s[field] = value
                if body.speaker is not None:
                    if body.speaker not in p['voices']:
                        raise ValueError('Select an existing speaker')
                    s['speaker'] = body.speaker
                if any(getattr(body, field) is not None for field in ('text', 'spoken_as', 'speaker')):
                    s['error'] = None
            if body.voice is not None:
                if (body.voice not in VOICES and not (is_custom(body.voice) and library.label(body.voice))) or body.speaker not in p['voices']:
                    raise ValueError('Unknown voice or speaker')
                if p['voices'][body.speaker] != body.voice:
                    p.get('voice_profiles',{}).pop(body.speaker,None)
                p['voices'][body.speaker] = body.voice
                for s in p['segments']:
                    if s['speaker'] == body.speaker:
                        s['error'] = None
        return store.public(store.edit(project_id, body.revision, apply), engine, checker)

    @app.post('/api/projects/{project_id}/segments/{segment_id}/delete')
    def delete_segment(project_id: str, segment_id: str, body: RevisionRequest):
        """Drop one line and the source text behind it, so script and lines agree.

        Audio files are left on disk: a deletion should be undoable without
        needing to synthesise anything again.
        """
        def change(p):
            index = next((i for i, s in enumerate(p['segments']) if s['id'] == segment_id), None)
            if index is None:
                raise ValueError('找不到这一句。')
            if len(p['segments']) <= 1:
                raise ValueError('工程至少要保留一句。')
            removed = p['segments'].pop(index)
            start, end = removed.get('source_start'), removed.get('source_end')
            if start is not None and end is not None and p.get('source_script'):
                span = end - start
                p['source_script'] = p['source_script'][:start] + p['source_script'][end:]
                for s in p['segments']:
                    if s.get('source_start') is not None and s['source_start'] >= end:
                        s['source_start'] -= span
                        s['source_end'] -= span
            used = {s['speaker'] for s in p['segments']}
            for speaker in [x for x in p['voices'] if x not in used]:
                p['voices'].pop(speaker, None)
                p.get('voice_profiles', {}).pop(speaker, None)
        with store.lock:
            return store.public(store.edit(project_id, body.revision, change), engine, checker)

    @app.post('/api/projects/{project_id}/script/check')
    def check_script(project_id: str, body: ScriptFixRequest | None = None, source_script: str = ''):
        # Rule-based only: no model, no project mutation, safe to call while typing.
        return inspect_script(source_script or (body.source_script if body else ''))

    @app.post('/api/projects/{project_id}/script/fix')
    def fix_script(project_id: str, body: ScriptFixRequest):
        return {'source_script': apply_fix(body.source_script, body.kind)}

    @app.post('/api/projects/{project_id}/script')
    def rewrite_script(project_id: str, body: ScriptRequest):
        """Preview or apply a source rewrite. Without labels this only previews."""
        from .attribution import carry_labels, carry_state
        with store.lock:
            project = store.read(project_id)
            if project['revision'] != body.revision or project['job']['status'] == 'running':
                raise RuntimeError('工程已改变或正在处理，请重新载入后再修改原稿。')
            language = project['language']
            report = inspect_script(body.source_script)
            if report['blocking']:
                raise ValueError(report['findings'][0]['message'])
            labels = ([label.model_dump() for label in body.labels] if body.labels
                      else carry_labels(project['segments'], body.source_script, language))
            if body.labels is None:
                unresolved = [{**unit, **{k: label[k] for k in ('kind', 'speaker')}}
                              for unit, label in zip(source_units(body.source_script), labels)
                              if label['kind'] == 'dialogue'
                              and label['speaker'].strip().upper() in ('', 'UNKNOWN')]
                # Slicing rejects UNKNOWN, so count with a placeholder that never persists.
                probe = [{**l, 'speaker': ('待指定' if l['speaker'].strip().upper() in ('', 'UNKNOWN')
                                           else l['speaker'])} for l in labels]
                sliced = project_segments(body.source_script, probe, language)
                _, stats = carry_state(project['segments'], [dict(s) for s in sliced])
                return {'preview': True, 'labels': labels, 'unresolved': unresolved,
                        'report': report, 'segments': len(sliced), **stats}
            segments = project_segments(body.source_script, labels, language)
            preview, stats = carry_state(project['segments'], [dict(s) for s in segments])
            presets = ['Vivian','Uncle_Fu','Serena','Dylan'] if language == 'zh' else ['Ryan','Aiden']
            def change(p):
                p['source_script'] = body.source_script
                p['segments'] = preview
                for i, speaker in enumerate(dict.fromkeys(s['speaker'] for s in preview)):
                    p['voices'].setdefault(speaker, presets[i % len(presets)])
                p['attribution'] = {**p.get('attribution', {}), 'confirmed_labels': labels,
                                    'human_confirmed': True, 'rewritten': True}
            return store.public(store.edit(project_id, body.revision, change), engine, checker)

    @app.post('/api/projects/{project_id}/duplicate')
    def duplicate_project(project_id: str, body: RevisionRequest):
        return store.public(store.duplicate(project_id,body.revision),engine,checker)

    @app.post('/api/projects/{project_id}/{action}')
    def history(project_id: str, action: Literal['undo','redo'], body: RevisionRequest):
        return store.public(store.edit(project_id, body.revision, lambda p:None, action), engine, checker)

    @app.post('/api/projects/{project_id}/voice/{action}')
    def fixed_voice(project_id: str, action: Literal['fix','release'], body: FixedVoiceRequest):
        def apply(p):
            segment=next((s for s in p['segments'] if s['id']==body.segment_id),None)
            if segment is None:
                raise ValueError('Unknown segment')
            profiles=p.setdefault('voice_profiles',{})
            if action=='release':
                profiles.pop(segment['speaker'],None)
                return
            if not body.synthetic_reference_consent:
                raise ValueError('请明确选择使用这句合成音作为角色参考声线。')
            if not getattr(engine,'reference_ready',False):
                raise ValueError('固定声线模型未安装。')
            public=store.public(p,engine,checker)
            current=next(s for s in public['segments'] if s['id']==segment['id'])
            audio=segment.get('audio')
            if (current['status']!='ready' or not audio or not audio.get('synthetic_audio')
                or audio.get('engine')!=engine.identity or segment['speaker'] in profiles):
                raise ValueError('请先生成并试听一条预设声音，再固定声线。')
            source=store.directory(project_id)/'audio'/(audio['fingerprint']+'.wav')
            info=sf.info(source)
            if not .3 <= info.duration <= 20 or info.channels!=1:
                raise ValueError('参考声音需为 0.3–20 秒的单声道合成音。')
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            folder=store.directory(project_id)/'references'
            folder.mkdir(exist_ok=True)
            dest=folder/(digest+'.wav')
            if not dest.exists():
                temporary=folder/(digest+'.tmp')
                shutil.copyfile(source,temporary);temporary.replace(dest)
            if hashlib.sha256(dest.read_bytes()).hexdigest()!=digest:
                raise ValueError('已有参考声音校验失败。')
            profiles[segment['speaker']]={'sha256':digest,'text':segment.get('spoken_as') or segment['text'],
                'voice':p['voices'][segment['speaker']],'source_fingerprint':audio['fingerprint'],
                'source_engine':audio['engine'],'synthetic_audio':True,'consent_confirmed':True}
            for s in p['segments']:
                if s['speaker']==segment['speaker']:s['error']=None
        return store.public(store.edit(project_id,body.revision,apply),engine,checker)

    def render_worker(project_id, segment_ids, retake_ids=()):
        try:
            for sid in segment_ids:
                if cancel.is_set():
                    break
                with store.lock:
                    p = store.read(project_id)
                    s = next(s for s in p['segments'] if s['id']==sid)
                    if sid in retake_ids:
                        # D33: advance only when this sentence starts; cancellation preserves untouched issues.
                        s['take']=s.get('take',0)+1
                        s['error']=None
                    digest = fingerprint(p, s, engine, library)
                    folder = store.directory(project_id)/'audio'
                    folder.mkdir(exist_ok=True)
                    path = folder/(digest+'.wav')
                    meta_path = folder/(digest+'.json')
                    p['job']['current_segment'] = sid
                    store.write(p)
                try:
                    if path.exists() and meta_path.exists():
                        meta = json.loads(meta_path.read_text())
                        info = sf.info(path)
                        if info.frames != meta['samples'] or info.samplerate != meta['sample_rate']:
                            raise ValueError('Cached asset is invalid; generate a new take')
                    else:
                        profile=p.get('voice_profiles',{}).get(s['speaker'])
                        if profile:
                            if not profile.get('synthetic_audio') or not profile.get('consent_confirmed'):
                                raise ValueError('固定声线缺少合成来源或授权记录。')
                            digest_ref=profile['sha256']
                            if len(digest_ref)!=64 or any(c not in '0123456789abcdef' for c in digest_ref):
                                raise ValueError('固定声线标识无效。')
                            pcm,rate,metrics=engine.synthesize_reference(s.get('spoken_as') or s['text'],p['language'],
                                store.directory(project_id)/'references'/(digest_ref+'.wav'),profile['text'],
                                260909+s.get('take',0),consent_confirmed=True,expected_sha256=digest_ref)
                        elif is_custom(p['voices'][s['speaker']]):
                            entry = library.get(custom_id(p['voices'][s['speaker']]))
                            pcm,rate,metrics=engine.synthesize_reference(s.get('spoken_as') or s['text'],p['language'],
                                library.audio_path(entry['id']),entry['reference_text'],
                                260909+s.get('take',0),consent_confirmed=True,expected_sha256=entry['sha256'])
                        else:
                            pcm, rate, metrics = engine.synthesize(s.get('spoken_as') or s['text'],
                                p['voices'][s['speaker']], p['language'], 260909+s.get('take',0))
                        pcm, meta = process_audio(pcm, rate)
                        meta.update({'fingerprint':digest, 'engine':getattr(engine,'reference_identity',engine.identity) if p.get('voice_profiles',{}).get(s['speaker']) else engine.identity, **metrics})
                        temp = folder/(digest+'.tmp.wav')
                        sf.write(temp, pcm, rate, subtype='PCM_16')
                        temp.replace(path)
                        meta_path.write_text(json.dumps(meta, indent=2))
                    error = None
                except Exception as exc:
                    logging.exception('Local generation failed for segment %s', sid)
                    meta = None
                    error = str(exc) if isinstance(exc,ValueError) else f'{type(exc).__name__}: generation failed; retry after checking the local engine'
                with store.lock:
                    p = store.read(project_id)
                    target = next(s for s in p['segments'] if s['id']==sid)
                    if meta:
                        target['audio'] = meta
                    target['error'] = error
                    p['job']['completed'] += 1
                    p['job']['failed'] += int(error is not None)
                    p['revision'] += 1
                    store.write(p)
        finally:
            with store.lock:
                p = store.read(project_id)
                p['job']['status'] = 'cancelled' if cancel.is_set() else ('completed_with_errors' if p['job']['failed'] else 'completed')
                p['job']['current_segment'] = None
                p['revision'] += 1
                store.write(p)
                active['project_id'] = None

    # Use two path components to avoid the one-component undo/redo route.
    @app.post('/api/projects/{project_id}/render/start')
    def start(project_id: str, body: RenderRequest):
        with store.lock:
            p = store.read(project_id)
            if active['project_id'] or body.revision != p['revision']:
                raise RuntimeError('A job is running or the project changed; reload and retry')
            if not engine.ready:
                raise ValueError('Local preset model is not installed')
            retake_ids=set()
            if body.marked_only:
                if body.segment_id or body.force:raise ValueError('标记重做不能同时指定单句或强制全部重做。')
                retake_ids={s['id'] for s in store.public(p,engine,checker)['segments'] if s['listening_status']=='issue'}
                if not retake_ids:raise ValueError('没有当前版本的声音问题标记。')
            selected = [s for s in p['segments'] if (s['id'] in retake_ids if body.marked_only else (not body.segment_id or s['id']==body.segment_id))]
            if not selected:
                raise ValueError('Unknown segment')
            if body.force:
                for s in selected:
                    s['take'] = s.get('take',0)+1
                    s['error'] = None
            public = store.public(p, engine, checker)
            pending = {s['id'] for s in public['segments'] if s['status']!='ready'}
            ids = [s['id'] for s in selected if s['id'] in pending or s['id'] in retake_ids]
            cancel.clear()
            active['project_id'] = project_id
            p['job'] = {'kind':'generating','status':'running','total':len(ids),'completed':0,'failed':0,'current_segment':None}
            p['revision'] += 1
            store.write(p)
            executor.submit(render_worker, project_id, ids, retake_ids)
            return store.public(p, engine, checker)

    def check_worker(project_id, segment_ids):
        fatal=None
        try:
            if hasattr(engine,'unload'):engine.unload()
            for sid in segment_ids:
                if cancel.is_set():break
                with store.lock:
                    p=store.read(project_id)
                    segment=next(s for s in p['segments'] if s['id']==sid)
                    digest=fingerprint(p,segment,engine,library)
                    expected=segment.get('spoken_as') or segment['text']
                    source=store.directory(project_id)/'audio'/(digest+'.wav')
                    p['job']['current_segment']=sid;store.write(p)
                rhythm={'source_fingerprint':digest,'version':RHYTHM_VERSION,'expected_text':expected}
                try:
                    rhythm.update(analyze_file(source,language=p['language'],expected_text=expected))
                    stat=source.stat();rhythm.update(audio_sha256=file_sha(source),audio_stat=[stat.st_size,stat.st_mtime_ns])
                except Exception:
                    logging.exception('Rhythm analysis failed for %s',sid)
                    rhythm.update(error='本句节奏检查失败，可重试。')
                result={'source_fingerprint':digest,'expected_text':expected,'checker_id':checker.identity,
                        'checked_at':time.time(),'reviewed':False}
                try:
                    before=file_sha(source)
                    transcript=checker.transcribe(source,p['language'],store.directory(project_id)/'checks')
                    if file_sha(source)!=before:raise ValueError('检查过程中音频发生变化，请重试。')
                    stat=source.stat()
                    result.update(transcript)
                    result.update(compare_text(expected,transcript['recognized_text'],p['language']))
                    result.update({'audio_sha256':before,'audio_stat':[stat.st_size,stat.st_mtime_ns]})
                except Exception as exc:
                    logging.exception('Local content check failed for segment %s',sid)
                    result.update({'status':'error','error':str(exc) if isinstance(exc,ValueError) else '本句检查失败，可重试。'})
                    if source.exists():
                        stat=source.stat();result['audio_stat']=[stat.st_size,stat.st_mtime_ns]
                with store.lock:
                    p=store.read(project_id)
                    target=next(s for s in p['segments'] if s['id']==sid)
                    if result.get('timed_text') and not rhythm.get('error'):
                        try:rhythm.update(analyze_file(source,result['timed_text'],p['language'],expected))
                        except Exception:
                            logging.exception('Pace timing analysis failed for %s',sid)
                            rhythm['pace']={'status':'unavailable','reason':'语速起伏估计失败，请人工试听。'}
                    target['rhythm_check']=rhythm
                    target['content_check']=result
                    p['job']['completed']+=1;p['job']['failed']+=int(result['status']=='error' or bool(rhythm.get('error')))
                    p['revision']+=1;store.write(p)
        except Exception:
            logging.exception('Local content checking job failed')
            fatal='本次文字检查中断，请重试。'
        finally:
            with store.lock:
                p=store.read(project_id)
                p['job']['status']='failed' if fatal else ('cancelled' if cancel.is_set() else ('completed_with_errors' if p['job']['failed'] else 'completed'))
                if fatal:p['job']['error']=fatal
                p['job']['current_segment']=None;p['revision']+=1;store.write(p)
                active['project_id']=None

    @app.post('/api/projects/{project_id}/checks/start')
    def start_check(project_id: str, body: RenderRequest):
        with store.lock:
            p=store.read(project_id)
            if active['project_id'] or p['revision']!=body.revision:
                raise RuntimeError('工程已改变或有任务运行，请刷新后重试。')
            if not checker.ready:raise ValueError('本地文字检查模型未就绪。')
            candidates=[s for s in store.public(p,engine,checker)['segments'] if not body.segment_id or s['id']==body.segment_id]
            if not candidates:raise ValueError('Unknown segment')
            if body.segment_id and candidates[0]['status']!='ready':raise ValueError('请先生成这句声音。')
            ids=[s['id'] for s in candidates if s['status']=='ready' and (body.force or s['check_status'] not in ('match','review','confirmed') or s['rhythm_status'] in ('not_checked','stale','error'))]
            cancel.clear();active['project_id']=project_id
            p['job']={'kind':'checking','status':'running','total':len(ids),'completed':0,'failed':0,'current_segment':None}
            p['revision']+=1;store.write(p)
            executor.submit(check_worker,project_id,ids)
            return store.public(p,engine,checker)

    @app.post('/api/projects/{project_id}/listening/review')
    def listening_review(project_id: str, body: ListeningRequest):
        def apply(p):
            segment=next((s for s in p['segments'] if s['id']==body.segment_id),None)
            if segment is None:raise ValueError('Unknown segment')
            if body.clear:
                segment.pop('listening_issue',None)
                return
            current=next(s for s in store.public(p,engine,checker)['segments'] if s['id']==body.segment_id)
            if current['status']!='ready':raise ValueError('请先生成并试听这句声音。')
            digest=segment['audio']['fingerprint']
            path=store.directory(project_id)/'audio'/(digest+'.wav')
            stat=path.stat();before=[stat.st_size,stat.st_mtime_ns]
            sha=file_sha(path)
            stat=path.stat()
            if before!=[stat.st_size,stat.st_mtime_ns]:raise ValueError('音频发生变化，请重新试听再标记。')
            segment['listening_issue']={'kind':body.kind,'note':body.note.strip(),'marked_at':time.time(),
                'source_fingerprint':digest,'audio_sha256':sha,'audio_stat':before,'speech_rate':p.get('speech_rate',1.0),
                'expected_text':segment.get('spoken_as') or segment['text'],'tempo_edit':segment.get('tempo_edit')}
        return store.public(store.edit(project_id,body.revision,apply),engine,checker)

    @app.post('/api/projects/{project_id}/checks/review')
    def review_check(project_id: str, body: CheckReviewRequest):
        def apply(p):
            current=next((s for s in store.public(p,engine,checker)['segments'] if s['id']==body.segment_id),None)
            if not current or current['status']!='ready':
                raise ValueError('请先检查当前音频，再试听确认文字与节奏。')
            keys=[key for status,key in (('check_status','content_check'),('rhythm_status','rhythm_check'))
                  if current[status] in ('review','confirmed')]
            if not keys:
                raise ValueError('请先检查当前音频，再试听确认文字与节奏。')
            segment=next(s for s in p['segments'] if s['id']==body.segment_id)
            digest=file_sha(store.directory(project_id)/'audio'/(current['audio']['fingerprint']+'.wav'))
            if any(segment[key].get('audio_sha256')!=digest for key in keys):
                raise ValueError('音频文件已变化，请重新检查后再试听确认。')
            reviewed_at=time.time() if body.confirmed else None
            for key in keys:
                segment[key]['reviewed']=body.confirmed
                segment[key]['reviewed_at']=reviewed_at
        return store.public(store.edit(project_id,body.revision,apply),engine,checker)

    @app.post('/api/projects/{project_id}/render/cancel')
    def cancel_job(project_id: str):
        with store.lock:
            store.read(project_id)
            if active['project_id'] == project_id:
                cancel.set()
            return {'message':'Cancellation requested; current sentence may finish'}

    @app.get('/api/projects/{project_id}/audio/{digest}')
    def audio(project_id: str, digest: str):
        p = store.read(project_id)
        if digest not in {s['audio']['fingerprint'] for s in p['segments'] if s.get('audio')}:
            raise HTTPException(404)
        return FileResponse(store.directory(project_id)/'audio'/(digest+'.wav'), media_type='audio/wav')

    def ready_segment(project_id, segment_id):
        p=store.read(project_id)
        current=next((s for s in store.public(p,engine,checker)['segments'] if s['id']==segment_id),None)
        if not current or current['status']!='ready':raise ValueError('请先生成当前句子。')
        segment=next(s for s in p['segments'] if s['id']==segment_id)
        return p,segment,store.directory(project_id)/'audio'/(segment['audio']['fingerprint']+'.wav')

    @app.get('/api/projects/{project_id}/segments/{segment_id}/timeline')
    def segment_timeline(project_id: str, segment_id: str):
        with store.lock:
            p,s,path=ready_segment(project_id,segment_id)
            public=next(x for x in store.public(p,engine,checker)['segments'] if x['id']==segment_id)
            timed=s.get('content_check',{}).get('timed_text') if public['check_status'] not in ('stale','not_checked','error') else None
            result=analyze_file(path,timed,p['language'],segment.get('spoken_as') or segment['text'])
            result.update(source_fingerprint=s['audio']['fingerprint'],revision=p['revision'])
            return result

    @app.post('/api/projects/{project_id}/segments/{segment_id}/tempo')
    def segment_tempo(project_id: str, segment_id: str, body: TempoRequest):
        def apply(p):
            _,s,path=ready_segment(project_id,segment_id)
            target=next(x for x in p['segments'] if x['id']==segment_id)
            if target.get('tempo_edit',{}).get('clips'):raise ValueError('此句已使用区块剪辑，请在新版精细剪辑中调整。')
            regions=valid_regions([x.model_dump() for x in body.regions],sf.info(path).duration)
            stat=path.stat()
            old_cuts=s.get('tempo_edit',{}).get('cuts',[]) if edit_status(s,[stat.st_size,stat.st_mtime_ns])=='current' else []
            cuts=valid_cuts([x.model_dump() for x in body.cuts] if body.cuts is not None else old_cuts,sf.info(path).duration)
            if not regions and not cuts:
                target.pop('tempo_edit',None);return
            if regions and not ffmpeg_path():raise ValueError('局部语速调节需要本机 FFmpeg。')
            stat=path.stat()
            target['tempo_edit']={'source_fingerprint':s['audio']['fingerprint'],'audio_sha256':file_sha(path),
                                 'audio_stat':[stat.st_size,stat.st_mtime_ns],'regions':regions,**({'cuts':cuts} if cuts else {})}
            # Validate the proposed edit before recording it; invalid remnants must not poison exports.
            prepare_segment(p,target,store.directory(project_id))
        return store.public(store.edit(project_id,body.revision,apply),engine,checker)

    @app.get('/api/projects/{project_id}/segments/{segment_id}/clips')
    def get_clips(project_id: str, segment_id: str):
        with store.lock:
            p,s,path=ready_segment(project_id,segment_id);stat=path.stat()
            edit=s.get('tempo_edit') if edit_status(s,[stat.st_size,stat.st_mtime_ns])=='current' else None
            return {'revision':p['revision'],'clips':clip_plan(edit,sf.info(path).duration),
                    'stale':bool(s.get('tempo_edit')) and edit_status(s,[stat.st_size,stat.st_mtime_ns])=='stale'}

    @app.post('/api/projects/{project_id}/segments/{segment_id}/clips')
    def save_clips(project_id: str, segment_id: str, body: ClipsRequest):
        def apply(p):
            _,s,path=ready_segment(project_id,segment_id);stat=path.stat()
            clips=validate_clips([x.model_dump() for x in body.clips],sf.info(path).duration)
            target=next(x for x in p['segments'] if x['id']==segment_id)
            target['tempo_edit']={'source_fingerprint':s['audio']['fingerprint'],'audio_sha256':file_sha(path),
                                 'audio_stat':[stat.st_size,stat.st_mtime_ns],'regions':[],'clips':clips}
            prepare_segment(p,target,store.directory(project_id))
        return store.public(store.edit(project_id,body.revision,apply),engine,checker)

    @app.post('/api/projects/{project_id}/segments/{segment_id}/preview')
    def segment_preview(project_id: str, segment_id: str, body: RevisionRequest):
        with store.lock:
            p,s,path=ready_segment(project_id,segment_id)
            if p['revision']!=body.revision or p['job']['status']=='running':raise RuntimeError('工程已改变或正在处理，请稍后重试。')
            sha=file_sha(path)
            stat=path.stat()
            effective_edit=s.get('tempo_edit') if edit_status(s,[stat.st_size,stat.st_mtime_ns])=='current' else None
            identity={'source_sha':sha,'fingerprint':s['audio']['fingerprint'],'tempo':effective_edit,'speed':p.get('speech_rate',1.),'version':TEMPO_VERSION}
            key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
            directory=store.directory(project_id);folder=directory/'previews';folder.mkdir(exist_ok=True)
            audio_file=folder/(key+'.wav');meta_file=folder/(key+'.json')
            if not audio_file.is_file() or not meta_file.is_file():
                pcm,rate,_,mapping=prepare_segment(p,s,directory)
                if file_sha(path)!=sha:raise ValueError('原音发生变化，请重试。')
                metadata={'mapping':mapping,'duration':len(pcm)/rate,'synthetic_audio':True,
                          'processed_checks':{**analyze(pcm,rate),'notice':'成品的低能量检查；时间为成品秒数，语速与自然度仍需试听。'},'source_sha256':sha}
                temp=folder/(key+'.tmp.wav');sf.write(temp,pcm,rate,subtype='PCM_16');temp.replace(audio_file)
                meta_file.write_text(json.dumps(metadata,ensure_ascii=False))
            result=json.loads(meta_file.read_text());result['url']=f'/api/projects/{project_id}/previews/{key}'
            return result

    @app.get('/api/projects/{project_id}/previews/{key}')
    def preview_audio(project_id: str, key: str):
        if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise HTTPException(404)
        path=store.directory(project_id)/'previews'/(key+'.wav')
        if not path.is_file():raise HTTPException(404)
        return FileResponse(path,media_type='audio/wav')

    @app.post('/api/projects/{project_id}/export/create')
    def export(project_id: str, body: RevisionRequest):
        with store.lock:
            p = store.read(project_id)
            if p['revision'] != body.revision or p['job']['status']=='running':
                raise RuntimeError('Finish generation and reload before exporting')
            if any(s['status']!='ready' for s in store.public(p,engine,checker)['segments']):
                raise ValueError('Generate all pending or failed sentences before export')
            out = store.directory(project_id)/'exports'/str(p['revision'])
            timeline = export_audio(p, store.directory(project_id), out, delivery=True)
            timeline['project_revision'] = p['revision']
            check_report={'project_revision':p['revision'],'synthetic_audio':True,
                'speech_rate':p.get('speech_rate',1.0),'checked_audio':'original_generated_audio',
                'notice':'自动文字检查针对原始合成声音；剪切可能移除发音，成品文字及字幕需要重新人工核对。',
                'segments':[{'id':s['id'],'text':s['text'],'check_status':s['check_status'],
                             'content_check':s.get('content_check'),'listening_status':s['listening_status'],
                             'rhythm_status':s['rhythm_status'],'rhythm_check':s.get('rhythm_check'),
                             'tempo_status':s['tempo_status'],'tempo_edit':s.get('tempo_edit'),
                             'edited_content_requires_review':s['tempo_status']=='current' and bool(s.get('tempo_edit',{}).get('cuts') or s.get('tempo_edit',{}).get('clips')),
                             'listening_issue':s.get('listening_issue')} for s in store.public(p,engine,checker)['segments']]}
            (out/'content-check.json').write_text(json.dumps(check_report,ensure_ascii=False,indent=2))
            (out/'timeline.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=2))
            return {name:f'/api/projects/{project_id}/export/{p["revision"]}/{name}' for name in ('full.wav','subtitles.srt','timeline.json','content-check.json','delivery.zip')}

    @app.get('/api/projects/{project_id}/export/{revision}/{name}')
    def download(project_id: str, revision: int, name: Literal['full.wav','subtitles.srt','timeline.json','content-check.json','delivery.zip']):
        if revision < 0:
            raise HTTPException(404)
        path = store.directory(project_id)/'exports'/str(revision)/name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, filename='VoxStage-'+name)

    dist = Path(frontend or ROOT/'frontend/dist')
    if dist.exists():
        app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
    return app

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--fixture', action='store_true', help='Explicit test tones, never real speech')
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(create_app(engine=FixtureEngine() if args.fixture else None), host='127.0.0.1', port=args.port)

if __name__ == '__main__':
    main()

# 最后更新：2026-09-09 · Astra

# 最后更新：2026-09-10 · Astra（接入原文绑定的角色草稿）

# 最后更新：2026-09-11 · Astra（复用试听确认接口同时处理文字与节奏）

# 最后更新：2026-09-11 · Astra（新增可移植交付包下载）

# 最后更新：2026-09-11 · Astra（可撤销的逐句停顿，空值继承作品设置）
