"""Loopback-only API and serial render queue. Astra, 2026-09-09."""
import argparse
import hashlib
import shutil
import json
import logging
import time
import os
import random
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
from .fcp7 import timeline_xml, IMPORT_GUIDE
from .rhythm import analyze_file, analyze, duration_marker, VERSION as RHYTHM_VERSION
from . import readings
from .core import reads_aloud, Store, fingerprint, spoken_text, inherit_settings, voice_of
from .pauses import split_at_pauses, join_with_silence
from .voices import VoiceLibrary, is_custom, custom_id, PREFIX as CUSTOM_PREFIX
from .script_check import inspect as inspect_script, apply_fix
from .attribution import RoleDraftEngine, ROLE_MODELS, project_segments, source_units, carry_locks
from .content_check import WhisperChecker, compare_text, file_sha
from .engines import MlxEngine, FixtureEngine, VOICES
from .project_settings import application_defaults
from .project_service import ProjectService
from .book_transactions import BookTransactions

ROOT = Path(__file__).resolve().parent.parent

class ImportRequest(BaseModel):
    name: str = Field(default='Untitled', max_length=120)
    script: str = Field(max_length=300000)
    language: Literal['zh','en']

class RoleLabel(BaseModel):
    id: str = Field(max_length=40)
    kind: Literal['narration','dialogue']
    speaker: str = Field(max_length=80)

class Hint(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    speaker: str = Field(default='', max_length=80)     # '' = the author marked it as speech but named nobody
    colour: str | None = Field(default=None, pattern=r'^#[0-9a-f]{6}$')   # the colour the author used, kept with the character

class BookRequest(BaseModel):
    title: str = Field(default='', max_length=120)
    script: str = Field(min_length=1, max_length=2_000_000)
    language: Literal['zh','en']
    chapter_chars: int | None = Field(default=None, ge=1000, le=12000)
    token_mode: bool = False                                      # test mode: split by estimated model token budget
    headings: list[int] | None = Field(default=None, max_length=5000)   # line numbers, from a Markdown or Word import
    hints: list[Hint] | None = Field(default=None, max_length=20000)     # spans whose speaker the manuscript's colours settle
    silent: list[int] | None = Field(default=None, max_length=5000)     # line numbers kept but not read aloud (headings)
    cut: Literal['lines'] | None = None                                 # 'lines': the colours cut the lines, quotation marks do not

class MasterBookRequest(BaseModel):
    title: str = Field(default='', max_length=120)
    script: str = Field(min_length=1, max_length=2_000_000)
    language: Literal['zh','en']
    headings: list[int] | None = Field(default=None, max_length=5000)
    hints: list[Hint] | None = Field(default=None, max_length=20000)
    silent: list[int] | None = Field(default=None, max_length=5000)
    cut: Literal['lines'] | None = None

class MasterChapterRequest(BaseModel):
    revision: int = Field(ge=0)
    title: str = Field(default='', max_length=120)
    text: str = Field(min_length=1, max_length=2_000_000)
    copy_settings_from: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    hints: list[Hint] | None = Field(default=None, max_length=20000)
    silent: list[int] | None = Field(default=None, max_length=5000)
    cut: Literal['lines'] | None = None

class SettingPatchRequest(BaseModel):
    revision: int = Field(ge=0)
    values: dict = Field(default_factory=dict)
    inherit: list[str] = Field(default_factory=list, max_length=32)

class BookCastRenameRequest(BaseModel):
    revision: int = Field(ge=0)
    cast_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    name: str = Field(min_length=1, max_length=80)

class BookStructureRequest(BaseModel):
    op: Literal['split','merge','reorder','attach','detach','dissolve']
    revision: int | None = Field(default=None, ge=0)
    project_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    at: int | None = Field(default=None, ge=1)
    left_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    right_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    resolutions: dict[str, object] = Field(default_factory=dict)
    members: list[str] = Field(default_factory=list, max_length=5000)
    position: int | None = Field(default=None, ge=0)
    inherit: bool = False
    identities: dict[str, dict] = Field(default_factory=dict)

class DocxImportRequest(BaseModel):
    name: str = Field(default='', max_length=200)
    data: str = Field(min_length=1, max_length=28_000_000)              # base64 of the .docx (≤ 20 MB)

class DocxApplyRequest(BaseModel):
    choices: dict[str, dict] = Field(default_factory=dict)              # colour -> {'as': character|narration|drop|ignore, 'name'}

class MarkdownRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)

class RoleEstimateRequest(BaseModel):
    script: str = Field(min_length=1, max_length=2_000_000)
    cut: Literal['lines'] | None = None

class RoleDraftRequest(BaseModel):
    script: str = Field(min_length=1, max_length=20000)     # long chapters enter only through the internal validated batch adapter
    debug_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')   # local UI may poll llama-server output while this draft runs
    hints: list[Hint] | None = Field(default=None, max_length=5000)     # from a coloured or marked manuscript: settled speakers
    silent: list[int] | None = Field(default=None, max_length=2000)     # line numbers not read aloud (headings)
    cut: Literal['lines'] | None = None                                 # 'lines': one unit per line, whatever quotation marks the text holds (本人 2026-09-17)
    language: Literal['zh','en']
    book_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')   # lines confirmed in the book's other chapters teach the habits
    prepared_token: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$', exclude=True)
    target_project_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$', exclude=True)

class AttributionBatchRequest(BaseModel):
    revision: int = Field(ge=0)
    resume: bool = True

class SuggestUnit(BaseModel):
    id: str = Field(max_length=16)
    text: str = Field(max_length=12000)
    kind: Literal['narration','dialogue']
    speaker: str = Field(default='', max_length=80)
    fixed: bool = False            # named by the model with certainty, or typed by the person: teaches, is not re-suggested
    turn: str = Field(default='', max_length=80)   # the page's own guess for an unsettled line: two people taking turns
    source: Literal['person', 'tag', 'model', 'guess', ''] = ''   # who settled the speaker: the person, the narration's tag, the model, a rule

class SuggestRequest(BaseModel):
    book_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    units: list[SuggestUnit] = Field(max_length=1000)
    draft_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')   # the draft's saved decisions are the final word on what is fixed
    revision: int | None = Field(default=None, ge=1)

class Decision(BaseModel):
    unit_id: str = Field(max_length=16)
    speaker: str | None = Field(default=None, max_length=80)      # None: the unit's speaker is not decided here (kind only)
    kind: Literal['narration', 'dialogue'] | None = None
    edited: bool = True                                          # the person changed it; False with confirmed: accepted as it was
    confirmed: bool = True
    clear: bool = False                                          # take the decision away: back to the program's suggestion

class CastRename(BaseModel):
    cast_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    name: str = Field(min_length=1, max_length=80)

class CastAlias(BaseModel):
    cast_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    alias: str = Field(min_length=1, max_length=80)

class DraftPatch(BaseModel):
    expected_revision: int = Field(ge=1)
    decisions: list[Decision] = Field(default_factory=list, max_length=500)
    rename: CastRename | None = None
    alias: CastAlias | None = None                               # 老板娘 is 陈小雪 — the reviewer carried a rename along
    split: str | None = Field(default=None, max_length=80)      # this alias is a character of its own after all
    unsplit: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')   # undo a split: the character made from an alias

class RoleConfirmRequest(BaseModel):
    draft_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    name: str = Field(default='Untitled', max_length=120)
    labels: list[RoleLabel] = Field(min_length=1,max_length=2000)     # units incl. blanks: up to twice the largest tier
    book_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')   # the chapter this came from, if any
    chapter_index: int | None = Field(default=None, ge=1)
    aliases: dict[str, str] = Field(default_factory=dict)                   # 老板娘 → 陈小雪, learned while reviewing
    silent: list[int] | None = Field(default=None, max_length=2000)         # line numbers whose segments are kept but not read aloud
    review: dict | None = None                                              # how much the reviewer had to do; see RoleImport
    expected_revision: int | None = Field(default=None, ge=1)               # the draft revision the page confirmed from

class InheritRequest(BaseModel):
    revision: int = Field(ge=0)
    source_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')     # another project
    template_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')   # or a saved template

class TemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    project_id: str = Field(pattern=r'^[a-f0-9]{32}$')

class AuditionRequest(BaseModel):
    voice: str = Field(max_length=40)
    text: str = Field(min_length=1, max_length=120)
    language: Literal['zh','en'] = 'zh'
    rate: float = Field(default=1.0, ge=0.5, le=2.0, allow_inf_nan=False)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)   # omitted: a fresh take each time

class VoiceDesignRequest(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=120)
    language: Literal['zh','en'] = 'zh'
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)   # omitted: a fresh one each time

class VoiceSaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    language: Literal['zh','en'] = 'zh'
    reference_text: str = Field(min_length=1, max_length=400)
    from_voice: str | None = Field(default=None, max_length=80)
    from_design: str | None = Field(default=None, max_length=64)   # an audition file name from /voices/design
    from_audition: str | None = Field(default=None, max_length=64) # an audition file name from /voices/audition
    audio_base64: str | None = Field(default=None, max_length=8_000_000)
    consent_confirmed: bool = False

class VoiceRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)

class SettingsRequest(BaseModel):
    favourite_voices: list[str] | None = Field(default=None, max_length=40)
    role_model: str | None = Field(default=None, max_length=80)
    voice_tags: dict[str, list[str]] | None = None      # voice id -> tags such as 老人、男性、威严

class CharacterRequest(BaseModel):
    revision: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=80)

class CrowdRequest(BaseModel):
    revision: int = Field(ge=0)
    speaker: str = Field(min_length=1, max_length=80)
    pool: list[str] = Field(min_length=1, max_length=40)
    seed: int = Field(default=260909, ge=0)

class ScriptRequest(BaseModel):
    revision: int = Field(ge=0)
    source_script: str = Field(min_length=1, max_length=2_000_000)
    labels: list[RoleLabel] | None = Field(default=None, max_length=5000)

class ScriptFixRequest(BaseModel):
    source_script: str = Field(min_length=1, max_length=12000)
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
    read_aloud: bool | None = None
    speaker_muted: bool | None = None                     # with speaker: mute/unmute the whole role without losing its chosen voice
    lexicon: dict[str, str] | None = None
    preset_model: Literal['0.6B', '1.7B'] | None = None
    clone_model: Literal['0.6B', '1.7B'] | None = None      # the model that reads fixed and designed voices (2026-09-16)
    ellipsis_pause_ms: Literal[0, 300, 500] | None = None   # a line read in parts at …… / ——, joined with this much silence (本人 2026-09-17)
    color: str | None = Field(default=None, pattern=r'^(#[0-9a-fA-F]{6}|auto)$')   # with speaker: this character's colour on screen
    color_scope: Literal['name', 'text', 'both'] | None = None                       # where the colours show: the name, the words, or both
    sex: Literal['m', 'f', 'auto'] | None = None                                     # with speaker: the character's sex for the speaker rules; 'auto' = as the voice suggests

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

class ExportXmlRequest(RevisionRequest):
    video_fps: int = Field(default=30, strict=True)


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
    from .books import Books
    from .core import Templates
    books = Books(store.root.parent/'books')
    templates = Templates(store.root.parent/'templates')
    def default_preset():
        # New projects start on the larger preset model when it is installed;
        # existing projects keep whatever they were made with. 0.6B stays
        # available for machines with less memory.
        return '1.7B' if getattr(engine, 'large_identity', None) else '0.6B'
    def default_clone():
        # Cloned lines (fixed and designed voices) start on the 1.7B Base where
        # it is installed (本人 2026-09-17, after the blind listening: 1.7B
        # chosen for all three cloned lines, ai-lab 实测 21); existing projects
        # keep what they were made with.
        return '1.7B' if getattr(engine, 'large_reference_ready', False) else '0.6B'
    # Settings and auditions live beside the projects folder, never inside it:
    # Store scans its own root for project.json.
    workspace = store.root.parent
    library = VoiceLibrary(workspace/'voices')
    store.library = library
    engine = engine or MlxEngine(os.environ.get('VOXSTAGE_MODEL', ROOT/'user-data/models/qwen-customvoice'))
    checker = checker or WhisperChecker(ROOT/'user-data/asr-settings.json')
    role_engine = role_engine or RoleDraftEngine()
    project_service = ProjectService(
        store, books,
        lambda: application_defaults(preset_model=default_preset(), clone_model=default_clone()))
    book_transactions = BookTransactions(project_service)
    store.resolver = project_service.view

    def work_project(project):
        return project_service.view(project) if project.get('settings_schema') == 1 else project
    def settings_file():
        path = workspace/'settings.json'
        try:
            return json.loads(path.read_text()) if path.is_file() else {}
        except ValueError:
            return {}
    if hasattr(role_engine, 'select') and settings_file().get('role_model'):
        try:
            role_engine.select(settings_file()['role_model'])
        except ValueError:
            pass
    def role_token_budget():
        from .capacity import draft_limits
        limits = draft_limits()
        spec = ROLE_MODELS.get(getattr(role_engine, 'model_id', None), {})
        context = min(limits['context'], spec.get('max_context', limits['context']))
        return {'context': context, 'max_tokens': limits['max_tokens']}
    drafts = store.root.parent / (store.root.name + '-role-drafts')

    def write_draft(record):
        """Atomic: the record is whole or unchanged, never half-written."""
        path = drafts / (record['draft_id'] + '.json'); tmp = path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, path)

    def read_draft(draft_id):
        path = drafts / (draft_id + '.json')
        if not path.is_file():
            raise ValueError('找不到这份草稿。')
        return json.loads(path.read_text(encoding='utf-8'))

    def draft_cast(record):
        """The cast a draft works with: its book's, else its own."""
        if record.get('book_id'):
            try:
                book_record = books.get(record['book_id'])
                return books.cast_of(book_record), book_record
            except ValueError:
                pass
        record.setdefault('cast', [])
        return record['cast'], None

    def save_cast(record, cast, book_record):
        from . import cast as C
        if book_record is not None:
            book_record['cast'] = cast
            book_record['aliases'] = C.alias_table(cast)
            # In a v1 master book the cast is shared state.  A chapter review,
            # rename or alias decision changes what every other chapter sees,
            # so it participates in the same optimistic book revision used by
            # whole-book and structure transactions.
            if book_record.get('master_schema') == 1:
                book_record['revision'] = book_record.get('revision', 0) + 1
            books.save(book_record)
        else:
            record['cast'] = cast
    drafts.mkdir(exist_ok=True)
    debug_runs = {}        # browser-generated debug id -> server draft id; local and temporary
    prepared_results = {}  # one-use, validated batch result -> existing review pipeline
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
        token_budget = role_token_budget()
        cap = __import__('runtime.capacity',fromlist=['draft_limits','TOKEN_SAFETY_RATIO'])
        return {'engine':engine.label, 'engine_id':engine.identity, 'ready':engine.ready,
                'attribution_ready':role_engine.ready, 'role_models':(role_engine.installed() if hasattr(role_engine,'installed') else []), 'role_model':getattr(role_engine,'model_id',None), 'role_context':token_budget['context'], 'role_token_safe_total':int(token_budget['context']*cap.TOKEN_SAFETY_RATIO), 'speed_ready':bool(ffmpeg_path()),'checker_ready':checker.ready, 'checker_id':checker.identity, 'voices':VOICES, 'fixed_voice_ready':getattr(engine,'reference_ready',False), 'preset_models':['0.6B']+(['1.7B'] if getattr(engine,'large_identity',None) else []), 'default_preset_model':('1.7B' if getattr(engine,'large_identity',None) else '0.6B'), 'design_ready':getattr(engine,'design_ready',False), 'local_only':True, 'synthetic_audio':True, 'draft_limits':cap.draft_limits(), 'clone_models':['0.6B']+(['1.7B'] if getattr(engine,'large_reference_ready',False) else []), 'default_clone_model':default_clone()}

    @app.post('/api/attribution/estimate')
    def estimate_role_draft(body: RoleEstimateRequest):
        from .capacity import estimate_role_tokens
        budget = role_token_budget()
        units = sum(1 for u in source_units(body.script, body.cut) if u['text'].strip())
        estimate = estimate_role_tokens(len(body.script), units, budget['context'], budget['max_tokens'])
        return {'chars': len(body.script), 'units': units, **estimate}

    @app.get('/api/settings')
    def read_settings():
        stored = settings_file()
        return {'favourite_voices': [v for v in stored.get('favourite_voices', []) if v in VOICES],
                'role_model': getattr(role_engine, 'model_id', None), 'voice_tags': stored.get('voice_tags', {})}

    @app.post('/api/settings')
    def write_settings(body: SettingsRequest):
        stored = settings_file()
        if body.favourite_voices is not None:
            stored['favourite_voices'] = list(dict.fromkeys(v for v in body.favourite_voices if v in VOICES))
        if body.voice_tags is not None:
            # Tags describe a voice for choosing — 老人、男性、威严 — and for
            # drawing a crowd's voices from a pool. Free text, a few per voice.
            tags = {}
            for voice, words in body.voice_tags.items():
                clean = [w.strip()[:20] for w in words if w and w.strip()][:12]
                if clean and (voice in VOICES or is_custom(voice)):
                    tags[voice] = list(dict.fromkeys(clean))
            stored['voice_tags'] = tags
        if body.role_model is not None:
            # Switching the role-draft model: only to one that is installed and
            # hash-checked on first use; the draft record says which one answered.
            if not hasattr(role_engine, 'select'):
                raise ValueError('当前环境不能切换分角色模型。')
            with store.lock:
                if active['project_id']:
                    raise RuntimeError('正在处理其他任务，请稍后再切换模型。')
                candidate = next((m for m in role_engine.installed() if m['id'] == body.role_model), None)
                if not candidate or not candidate['installed']:
                    raise ValueError('这个分角色模型还没有安装：运行 scripts/setup_model.py --model role-abliterated。')
                if not candidate.get('loadable', True):
                    raise ValueError(f"这个模型登记的最低内存是 {candidate.get('minimum_memory_gb')} GB，当前电脑不适合加载。")
                role_engine.select(body.role_model)
            stored['role_model'] = body.role_model
        (workspace/'settings.json').write_text(json.dumps(stored, ensure_ascii=False, indent=1))
        return {'favourite_voices': stored.get('favourite_voices', []), 'role_model': getattr(role_engine, 'model_id', None), 'voice_tags': stored.get('voice_tags', {})}

    @app.get('/api/voices/custom')
    def list_custom_voices():
        return library.list()

    @app.post('/api/voices/custom')
    def create_custom_voice(body: VoiceSaveRequest):
        """Keep a voice: either one the model just produced, or one supplied.

        Saving an audition means a good sample never has to be hunted for again,
        and a reference steadies delivery — which is the whole reason to keep it.
        """
        if sum(bool(x) for x in (body.from_voice, body.audio_base64, body.from_design, body.from_audition)) != 1:
            raise ValueError('请三选一：从现有音色生成、从设计的声线保存，或提供一段参考声音。')
        with store.lock:
            if active['project_id']:
                raise RuntimeError('正在处理其他任务，请稍后再建立音色。')
            active['project_id'] = 'voice-library'
        try:
            if body.from_audition:
                # Keep exactly the take the person listened to, not a re-render with
                # another seed or another model.
                if not re.fullmatch(r'[0-9a-f]{16}\.wav', body.from_audition):
                    raise ValueError('无效的试听文件名。')
                sample = workspace/'auditions'/body.from_audition
                if not sample.is_file() or not sample.with_suffix('.json').is_file():
                    raise ValueError('这版试听已清理，请重新试听后再保存。')
                note = json.loads(sample.with_suffix('.json').read_text())
                pcm, rate = sf.read(sample, dtype='float32')
                entry = library.create(name=body.name, pcm=pcm, rate=rate,
                    reference_text=note.get('text') or body.reference_text, language=note.get('language') or body.language,
                    source='generated', consent_confirmed=True,
                    derived_from=f"{note.get('voice')} · seed {note.get('seed')} · {note.get('preset_model')}")
            elif body.from_design:
                # Keep exactly the sample the person listened to, not a re-render.
                if not re.fullmatch(r'design-[0-9a-f]{16}\.wav', body.from_design):
                    raise ValueError('无效的设计试听文件名。')
                sample = workspace/'auditions'/body.from_design
                if not sample.is_file():
                    raise ValueError('设计试听已清理，请重新生成后再保存。')
                note = json.loads(sample.with_suffix('.json').read_text()) if sample.with_suffix('.json').is_file() else {}
                pcm, rate = sf.read(sample, dtype='float32')
                entry = library.create(name=body.name, pcm=pcm, rate=rate,
                    reference_text=note.get('text') or body.reference_text, language=body.language,
                    source='generated', consent_confirmed=True,
                    derived_from='design:' + (note.get('description') or '') + (f' · seed {note["seed"]}' if note.get('seed') is not None else ''))
            elif body.from_voice:
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
            # The model a new project will actually use, so the audition is the
            # voice the person will get, not the smaller model's rendering of it.
            size = default_preset()
            # A fresh take each click unless a seed is named: the same preset reads
            # the same line differently from seed to seed, and the take a person
            # keeps as a reference should be one they chose among several.
            seed = body.seed if body.seed is not None else random.SystemRandom().randrange(1, 2**31 - 1)
            pcm, rate, _ = engine.synthesize(body.text, body.voice, body.language, seed=seed,
                                             **({'size': size} if hasattr(engine, 'identity_for') else {}))
            pcm, meta = process_audio(pcm, rate)
            rate = meta['sample_rate']
            folder = workspace/'auditions'
            folder.mkdir(parents=True, exist_ok=True)
            for old in sorted(folder.glob('[0-9a-f]*.wav'), key=lambda x: x.stat().st_mtime)[:-16]:
                old.unlink(missing_ok=True); old.with_suffix('.json').unlink(missing_ok=True)
            name = hashlib.sha256(
                f'{body.voice}|{body.text}|{body.language}|{size}|{seed}'.encode()).hexdigest()[:16]
            # The take itself, at its own speed — this is the file that can be kept.
            sf.write(folder/(name+'.wav'), pcm, rate, subtype='PCM_16')
            (folder/(name+'.json')).write_text(json.dumps({'voice':body.voice,'text':body.text,'language':body.language,
                                                          'seed':seed,'preset_model':size,'synthetic_audio':True},ensure_ascii=False))
            heard = name+'.wav'
            # Rate is a listening aid applied after synthesis, exactly as the
            # project speed control is; it does not change how a line is generated
            # and it is not what gets kept.
            if body.rate != 1.0:
                heard = f'{name}x{round(body.rate*100):03d}.wav'
                sf.write(folder/heard, change_tempo(pcm, rate, body.rate), rate, subtype='PCM_16')
            return {'url': f'/api/voices/audition/{heard}', 'file': name+'.wav', 'seed': seed, 'seconds': len(pcm)/rate,
                    'preset_model': size, 'voice': body.voice, 'rate': body.rate, 'synthetic_audio': True}
        finally:
            with store.lock:
                active['project_id'] = None

    @app.post('/api/voices/design')
    def design_voice(body: VoiceDesignRequest):
        """Hear a voice described in words. Nothing is kept until it is saved."""
        if not getattr(engine, 'design_ready', False):
            raise ValueError('声音设计模型未安装。')
        with store.lock:
            if active['project_id']:
                raise RuntimeError('正在处理其他任务，请稍后再试。')
            active['project_id'] = 'voice-design'
        try:
            # One description, many voices: each click without a seed draws a new
            # one, so the person can hear several candidates and keep the one they
            # liked. The seed travels with the audition and into the library entry.
            seed = body.seed if body.seed is not None else random.SystemRandom().randrange(1, 2**31 - 1)
            pcm, rate, metrics = engine.design_voice(body.text, body.description, body.language, seed)
            pcm, meta = process_audio(pcm, rate); rate = meta['sample_rate']
            folder = workspace/'auditions'; folder.mkdir(parents=True, exist_ok=True)
            for old in sorted(folder.glob('design-*.wav'), key=lambda x: x.stat().st_mtime)[:-8]:
                old.unlink(missing_ok=True); old.with_suffix('.json').unlink(missing_ok=True)
            name = 'design-' + hashlib.sha256(f'{body.description}|{body.text}|{body.language}|{seed}'.encode()).hexdigest()[:16]
            sf.write(folder/(name+'.wav'), pcm, rate, subtype='PCM_16')
            (folder/(name+'.json')).write_text(json.dumps({'description':body.description,'text':body.text,'language':body.language,'seed':seed,
                                                          'design_identity':metrics.get('design_identity'),'synthetic_audio':True},ensure_ascii=False))
            return {'url': f'/api/voices/audition/{name}.wav', 'file': name+'.wav', 'seconds': len(pcm)/rate, 'seed': seed,
                    'generation_seconds': round(metrics['generation_seconds'], 1), 'synthetic_audio': True}
        finally:
            with store.lock:
                active['project_id'] = None

    @app.get('/api/voices/audition/{name}')
    def audition_file(name: str):
        if not re.fullmatch(r'(?:design-)?[a-f0-9]{16}(?:x\d{3})?\.wav', name):
            raise ValueError('无效的试听文件名。')
        path = workspace/'auditions'/name
        if not path.is_file():
            raise ValueError('试听文件已清理，请重新生成。')
        return FileResponse(path, media_type='audio/wav')

    @app.post('/api/books')
    def create_book(body: BookRequest):
        """Keep a long text as a book cut into chapters; each becomes a project later."""
        token_budget = role_token_budget() if body.token_mode else None
        with store.lock:
            book = books.create(body.title, body.script, body.language, body.headings,
                                hints=[h.model_dump() for h in body.hints] if body.hints else None, silent=body.silent,
                                cut=body.cut, chapter_chars=(None if body.token_mode else body.chapter_chars),
                                token_budget=token_budget)
        return books.public(book)

    def master_chapters(body):
        """Rebase manuscript marks onto author chapters without processing cuts."""
        from .books import author_chapters
        chapters = author_chapters(body.script, body.headings)
        hints = [hint.model_dump() for hint in body.hints] if body.hints else []
        total_lines = body.script.count('\n') + (0 if body.script.endswith('\n') else 1)
        if any(not isinstance(number, int) or isinstance(number, bool)
               or not 0 <= number < total_lines for number in (body.silent or [])):
            raise ValueError('不朗读行号超出原稿范围。')
        offset = 0
        line = 0
        assigned_hints = set()
        for chapter in chapters:
            end = offset + len(chapter['text'])
            line_count = chapter['text'].count('\n') + (0 if chapter['text'].endswith('\n') else 1)
            chapter['cut'] = body.cut
            chapter['hints'] = []
            for hint_index, hint in enumerate(hints):
                if offset <= hint['start'] < hint['end'] <= end:
                    chapter['hints'].append({**hint, 'start': hint['start'] - offset,
                                             'end': hint['end'] - offset})
                    assigned_hints.add(hint_index)
            chapter['silent'] = [number - line for number in (body.silent or [])
                                 if line <= number < line + line_count]
            offset = end
            line += line_count
        if len(assigned_hints) != len(hints):
            raise ValueError('作者颜色标记超出原稿或跨越章节边界，请先调整章节或标记范围。')
        return chapters

    @app.post('/api/master-books')
    def create_master_book(body: MasterBookRequest):
        with store.lock:
            book, projects = project_service.create_book(body.title, body.language, master_chapters(body))
        return {**books.public(book),
                'projects': [{'id': p['id'], 'name': p['name'], 'processing_state': p['processing_state']}
                             for p in projects]}

    @app.post('/api/project-records')
    def create_project_record(body: ImportRequest):
        with store.lock:
            project = project_service.create_standalone(body.name, body.script, body.language)
            return project_service.public_project(project, engine, checker)

    @app.post('/api/master-books/{book_id}/chapters')
    def create_master_chapter(book_id: str, body: MasterChapterRequest):
        with store.lock:
            book, project = project_service.create_chapter(
                book_id, body.revision, body.title, body.text, cut=body.cut,
                hints=[hint.model_dump() for hint in body.hints] if body.hints else None,
                silent=body.silent, copy_from_id=body.copy_settings_from)
            return {'book_revision': book['revision'],
                    'project': project_service.public_project(project, engine, checker)}

    @app.get('/api/master-books/{book_id}/settings')
    def get_master_book_settings(book_id: str):
        book = books.get(book_id)
        if book.get('master_schema') != 1:
            raise ValueError('旧版书目没有主工程设置。')
        return {'book_id': book['id'], 'revision': book.get('revision', 0),
                'settings': book.get('settings', {})}

    @app.patch('/api/master-books/{book_id}/settings')
    def patch_master_book_settings(book_id: str, body: SettingPatchRequest):
        book = project_service.update_book_settings(book_id, body.revision, body.values, body.inherit)
        return {'book_id': book['id'], 'revision': book['revision'], 'settings': book['settings']}

    @app.post('/api/master-books/{book_id}/settings/unify')
    def unify_master_book_settings(book_id: str, body: SettingPatchRequest):
        return book_transactions.unify_settings(
            book_id, body.revision, body.values, body.inherit)

    @app.post('/api/master-books/{book_id}/cast/rename/plan')
    def plan_master_cast_rename(book_id: str, body: BookCastRenameRequest):
        return book_transactions.rename_plan(
            book_id, body.revision, body.cast_id, body.name)

    @app.post('/api/master-books/{book_id}/cast/rename')
    def rename_master_cast(book_id: str, body: BookCastRenameRequest):
        return book_transactions.rename_cast(
            book_id, body.revision, body.cast_id, body.name)

    @app.post('/api/master-books/{book_id}/structure/plan')
    def plan_master_structure(book_id: str, body: BookStructureRequest):
        return book_transactions.preview_structure(book_id, body.model_dump(exclude_none=True))

    @app.post('/api/master-books/{book_id}/structure/apply')
    def apply_master_structure(book_id: str, body: BookStructureRequest):
        if body.revision is None:
            raise ValueError('执行结构操作需要主工程 revision。')
        return book_transactions.apply_structure(book_id, body.model_dump(exclude_none=True))

    imports = {}          # import_id -> parsed document, until its colours are answered (a handful at most)

    @app.post('/api/import/docx')
    def import_docx(body: DocxImportRequest):
        """A Word document: its headings and every colour in it with samples, for the
        reviewer to say who each colour is. Nothing is decided here (本人 2026-09-16: 逐色问)."""
        import base64
        from . import colored
        from .core import uid
        try:
            data = base64.b64decode(body.data, validate=True)
        except (ValueError, __import__('binascii').Error) as exc:
            raise ValueError('文件内容无法解析。') from exc
        if len(data) > 20_000_000:
            raise ValueError('文件超过 20 MB。')
        doc = colored.read_docx(data)
        if not doc['paragraphs']:
            raise ValueError('这个文档里没有正文。')
        import_id = uid()
        if len(imports) >= 8:
            imports.pop(next(iter(imports)))
        imports[import_id] = doc
        return {'import_id': import_id, 'title': doc['title'] or body.name.rsplit('.', 1)[0], 'paragraphs': sum(1 for p in doc['paragraphs'] if not p['level']),
                'chars': sum(len(p['text']) for p in doc['paragraphs']) + max(0, len(doc['paragraphs']) - 1),
                'headings': [{'level': p['level'], 'text': p['text']} for p in doc['paragraphs'] if p['level']],
                'colours': colored.colour_groups(doc['paragraphs']), 'has_quotes': colored.has_quotes(doc['paragraphs'])}

    @app.post('/api/import/docx/{import_id}/apply')
    def apply_docx(import_id: str, body: DocxApplyRequest):
        """The colour answers applied: the text a project stores, its headings, the
        lines not read aloud, and the spans whose speaker the colours settle."""
        from . import colored
        doc = imports.get(import_id)
        if doc is None:
            raise ValueError('这次导入已经过期，请重新选择文件。')
        for colour, choice in body.choices.items():
            if choice.get('as') not in ('character', 'narration', 'drop', 'ignore'):
                raise ValueError(f'颜色 {colour} 的选择无效。')
            if choice.get('as') == 'character' and not str(choice.get('name', '')).strip():
                raise ValueError(f'颜色 {colour} 还没有名字。')
        result = colored.compose(doc['paragraphs'], body.choices)
        if not result['text'].strip():
            raise ValueError('按这些选择，文档里没有剩下正文。')
        imports.pop(import_id, None)
        return result

    @app.post('/api/import/markdown')
    def import_markdown(body: MarkdownRequest):
        """Markdown to the prose a project stores, with its headings' line numbers."""
        from . import markdown
        text, headings = markdown.to_text(body.text)
        if not text.strip():
            raise ValueError('这个 Markdown 文件里没有正文。')
        return {'text': text, 'headings': headings}

    @app.get('/api/books')
    def list_books():
        return books.list()

    @app.get('/api/books/{book_id}')
    def get_book(book_id: str):
        return books.public(books.get(book_id))

    @app.delete('/api/books/{book_id}')
    def delete_book(book_id: str):
        with store.lock:
            record = books.get(book_id)
            if record.get('master_schema') == 1 and record.get('members'):
                raise ValueError('主工程仍有子工程，不能直接删除。')
            books.delete(book_id)
        return {'deleted': book_id}

    @app.get('/api/books/{book_id}/chapters/{index}')
    def get_chapter(book_id: str, index: int):
        book = books.get(book_id)
        chapter = next((c for c in book['chapters'] if c['index'] == index), None)
        if chapter is None:
            raise ValueError('没有这一章。')
        if book.get('master_schema') == 1:
            raw = store.read(chapter['project_id'])
            return {**chapter, 'text': raw['source_script'], 'book_id': book['id'],
                    'book_title': book['title'], 'language': book['language'],
                    'chapters': len(book['members']), 'cut': raw.get('cut'),
                    'project_name': raw['name'], 'known_names': [],
                    'existing_project_id': raw['id'], 'processing_state': raw.get('processing_state')}
        # Names already confirmed in this book's other chapters, offered to the
        # reviewer as candidates so 孔乙己 is typed once, not once per chapter.
        names, existing = [], None
        with store.lock:
            for p in book_projects(book):
                names += [s for s in p['voices'] if s not in ('旁白', 'Narrator') and s not in names]
                if (p.get('book') or {}).get('index') == index and not p.get('archived'):
                    existing = p['id']
        return {**chapter, 'book_id': book['id'], 'book_title': book['title'], 'language': book['language'], 'chapters': len(book['chapters']), 'cut': book.get('cut'),
                'project_name': f"{book['title']} · {chapter['title']}".strip(' ·'), 'known_names': names, 'existing_project_id': existing}

    def clone_size(project):
        """The cloning model the project chose, for engines that offer one."""
        return {'size': project.get('clone_model', '0.6B')} if hasattr(engine, 'reference_identity_for') else {}

    def read_with_pauses(project, segment, read):
        """`read(text)` -> (pcm, rate, metrics). With the project's ellipsis pause
        on, a line that trails off or breaks (…… / ——) is read in parts and the
        parts joined with that much silence (本人 2026-09-17: the version chosen
        by ear); otherwise, or when there is nothing to cut, the line as it is."""
        gap = int(project.get('ellipsis_pause_ms') or 0)
        text = spoken_text(project, segment)
        parts = split_at_pauses(text) if gap else [text]
        if len(parts) < 2:
            return read(text)
        pieces, metrics, rate = [], None, None
        for part in parts:
            pcm, rate_, m = read(part)
            trimmed, meta = process_audio(pcm, rate_)
            pieces.append((trimmed, meta['speech_start_sample'], meta['speech_end_sample']))
            rate = rate_
            metrics = m if metrics is None else {**metrics, 'generation_seconds': metrics.get('generation_seconds', 0) + m.get('generation_seconds', 0),
                                                 'mlx_peak_memory_bytes': max(metrics.get('mlx_peak_memory_bytes', 0), m.get('mlx_peak_memory_bytes', 0))}
        pcm, silence = join_with_silence(pieces, rate, gap)
        return pcm, rate, {**metrics, 'parts': len(parts), 'pause_seconds': silence, 'ellipsis_pause_ms': gap}

    def character_sex(project, speaker):
        """'f', 'm' or '': what the project says of the character, else what
        their voice suggests. The voice is a production choice — a boy may be
        read by a woman — so it is only the default (Astra 2026-09-15)."""
        return (project.get('sexes') or {}).get(speaker) or voice_sex(project['voices'].get(speaker, ''))

    def voice_sex(voice):
        """'f', 'm' or '' from a voice's own description: preset labels say 女声/male; a designed
        or kept voice's library entry says what it was made from."""
        label = VOICES.get(voice, '')
        if is_custom(voice):
            try:
                entry = library.get(custom_id(voice)); origin = entry.get('derived_from') or ''
                label = VOICES.get(origin.split(' · ')[0], '') + ' ' + origin
            except ValueError:
                label = ''
        low = label.lower()
        if any(k in low for k in ('女', 'female', 'girl', 'woman')): return 'f'
        if any(k in low for k in ('男', 'male', 'boy')): return 'm'
        return ''

    def confirmed_dialogue(p):
        """(unit, label) for every dialogue line a person confirmed in a project."""
        record = p.get('attribution') or {}
        labels = {l['id']: l for l in record.get('confirmed_labels', [])}
        if not labels or not p.get('source_script'):
            return []
        return [(u, labels[u['id']]) for u in source_units(p['source_script'], p.get('cut'))
                if u['id'] in labels and labels[u['id']]['kind'] == 'dialogue'
                and labels[u['id']]['speaker'].strip().upper() not in ('', 'UNKNOWN', 'NARRATOR')]

    def book_projects(book):
        """Projects made from this book's chapters — linked by id, or, for projects
        made before the link existed, by the name the chapter flow gave them."""
        prefix = book['title'] + ' · '
        by_name = {f"{book['title']} · {c['title']}".strip(' ·'): c['index'] for c in book['chapters']}
        out = []
        for path in sorted(store.root.glob('*/project.json')):
            p = json.loads(path.read_text())
            if (p.get('book') or {}).get('id') == book['id'] or p['name'].startswith(prefix):
                if not p.get('book') and p['name'] in by_name:
                    # Made before projects remembered their chapter: link it now,
                    # by the name the chapter flow gave it. Not an edit — no revision bump.
                    p['book'] = {'id': book['id'], 'title': book['title'], 'index': by_name[p['name']], 'chapters': len(book['chapters'])}
                    store.write(p)
                out.append(p)
        return out

    with store.lock:
        # Link projects made from chapters before the link existed, once, at startup.
        for summary in books.list():
            book_projects(books.get(summary['id']))

    @app.get('/api/attribution/debug/{debug_id}')
    def role_debug(debug_id: str):
        if not re.fullmatch(r'[a-f0-9]{32}', debug_id):
            raise ValueError('调试编号无效。')
        draft_id = debug_runs.get(debug_id)
        if not draft_id:
            return {'text': '[VoxStage] 等待模型任务开始…', 'running': False}
        chunks = []
        for path in (drafts / (draft_id + '.log'), drafts / (draft_id + '-fallback.log')):
            if path.is_file():
                label = '主模型' if path.name == draft_id + '.log' else '备用模型'
                text = path.read_text(encoding='utf-8', errors='replace')
                chunks.append(f'===== {label} =====\n' + text[-120000:])
        return {'text': '\n\n'.join(chunks) if chunks else '[VoxStage] 正在准备模型…',
                'running': active.get('project_id') == 'role-draft'}

    @app.post('/api/attribution/draft')
    def role_draft(body: RoleDraftRequest):
        from .core import uid
        from .capacity import draft_limits
        limits = draft_limits()
        draft_id = uid()
        if body.debug_id:
            debug_runs[body.debug_id] = draft_id
        owns_active = body.prepared_token is None
        with store.lock:
            if owns_active:
                if active['project_id']:
                    raise RuntimeError('正在处理其他任务，请稍后再生成角色草稿。')
                active['project_id'] = 'role-draft'
        try:
            if hasattr(engine, 'unload'):
                engine.unload()
            names_for_model = []
            if body.book_id:
                try:
                    books.get(body.book_id)
                except ValueError:
                    body.book_id = None          # the book was removed since; draft without it
            # Names the story uses: in this passage, or confirmed in the book's
            # other chapters — a chapter that never spells a name still has it.
            known_names = set(); aliases = {}
            if body.book_id:
                with store.lock:
                    book_record = books.get(body.book_id)
                    aliases = dict(book_record.get('aliases') or {})
                    for sibling in book_projects(book_record):
                        known_names.update(sp for sp in sibling.get('voices', {}) if sp not in ('旁白', 'Narrator', 'NARRATOR'))
                        for sp, voice in sibling.get('voices', {}).items():
                            if sp in ('旁白', 'Narrator', 'NARRATOR') or any(n.startswith(sp) for n in names_for_model):
                                continue
                            # The cast with the sex of each character — as the
                            # book says (settings), else as the voice suggests:
                            # a chapter's speakers told apart by who could have
                            # said what.
                            sex = character_sex(sibling, sp)
                            also = [a for a, n in aliases.items() if n == sp]
                            notes = [x for x in ({'f': '女', 'm': '男'}.get(sex, ''), '又称 ' + '、'.join(also) if also else '') if x]
                            names_for_model.append(sp + ('（' + '；'.join(notes) + '）' if notes else ''))
            # A name the model invents -- ME for 我, WU DI for 吴迪 -- is not a
            # name the story uses. Anything not found in the text is handed to
            # the reviewer as unresolved, with the model's guess kept as a hint.
            # In a text that marks speech with quotation marks, an unquoted unit
            # is prose. The model labels 掌柜说： as the shopkeeper speaking; across
            # four reviewed projects it did so 27 times and the reviewer disagreed
            # 27 times. Texts with no quotation marks at all are left alone.
            quoted = any(c in body.script for c in '“"「『')
            def cites_rather_than_speaks(unit):
                before, after = quote_context[unit['id']]
                return habits.quoted_citation(unit['text'], before, after)
            def speech_by_form(unit):
                """A quoted unit with a sentence inside it — 。！？… — is speech
                or thought unless a citation cue says otherwise; a Chinese phrase
                without one (“行状”) keeps the model's word. In English the
                comma before the closing mark — “Then,” he observed — is the
                first half of a split quotation, speech by form too. On the
                eleven reviewed texts (2026-09-17) no quoted unit a person
                called narration has this form."""
                text = unit['text'].strip()
                if len(text) < 3 or text[0] not in '“"「『':
                    return False
                # A paragraph of a speech that runs on (opened with “, closed
                # only at the last paragraph) has no closing mark of its own.
                inner = text[1:-1] if text[-1] in '”"」』' else text[1:]
                if body.language == 'zh':
                    return any(c in inner for c in '。！？…；!?') and not cites_rather_than_speaks(unit)
                return inner.rstrip().endswith(',')
            def chinese_names(labels):
                """Names in the text's own script that anything has offered for this
                passage: the book's, the tags', and the model's own Chinese answers."""
                return set(known_names) | set(tag_names) | {l['speaker'].strip() for l in labels if l['kind'] == 'dialogue' and re.search('[一-鿿]', l['speaker'])}
            def vetted(label, unit, candidates=()):
                speaker = aliases.get(label['speaker'].strip(), label['speaker'].strip())   # 老板娘 → 陈小雪, as the book learned
                if label['kind'] == 'dialogue' and speaker.upper() == 'NARRATOR':
                    # A line of speech whose speaker is "the narrator" names nobody
                    # (the 9B wrote it for eight of Kong Yiji's lines, 2026-09-16).
                    speaker = 'UNKNOWN'
                if body.language == 'zh' and label['kind'] == 'dialogue' and speaker and not re.search('[一-鿿]', speaker) and speaker.upper() not in ('UNKNOWN', 'NARRATOR'):
                    # A name written in letters for a Chinese text — ZHANG XIAO WEI
                    # — is the name it spells, when exactly one name here does
                    # (本人 2026-09-16: 等价人名). The grammar now keeps the model
                    # from answering in letters; this is the net under it.
                    same = habits.name_in_letters_for(speaker, candidates, body.script)
                    if same:
                        speaker = aliases.get(same, same)
                if quoted and label['kind'] == 'dialogue' and not unit['text'].lstrip().startswith(('“', '"', '「', '『')):
                    return {'kind': 'narration', 'speaker': 'NARRATOR', 'suggested': speaker}
                if body.language == 'zh' and label['kind'] == 'dialogue' and cites_rather_than_speaks(unit):
                    return {'kind': 'narration', 'speaker': 'NARRATOR', 'suggested': speaker}
                if label['kind'] == 'narration' and quoted and speech_by_form(unit):
                    # The reverse: a quoted unit the model called narration that
                    # has the form of speech is a line with its speaker unplaced
                    # (阿Q chapter 7, 2026-09-17: his thoughts, a paragraph each
                    # — “造反？有趣，……” — were all narration to the 14B; the
                    # reviewer reads them as his lines). The rules below fill it
                    # from a tag beside it, a habit, or the exchange.
                    return {'kind': 'dialogue', 'speaker': 'UNKNOWN'}
                english_support = habits.english_name_support(speaker, body.script) if body.language == 'en' and speaker else 0
                name_present = bool(english_support) if body.language == 'en' else speaker in body.script
                if label['kind'] == 'dialogue' and speaker.upper() not in ('', 'UNKNOWN', 'NARRATOR') and (
                        (not name_present and speaker not in known_names) or len(speaker) > (80 if body.language == 'en' else 12) or any(c in speaker for c in '，。！？～“”"：')
                        or speaker in habits.NOT_NAMES):
                    # Not a name the story uses — invented, translated, or the
                    # line itself pasted into the speaker field.
                    return {'kind': 'dialogue', 'speaker': 'UNKNOWN', 'suggested': speaker[:20]}
                if label['kind'] == 'dialogue' and english_support == 1 and speaker not in known_names:
                    return {'kind': 'dialogue', 'speaker': speaker, 'tier': 'suggested', 'basis': '原文说话标记使用省略称谓的名字，请核对是否同一人'}
                if label['kind'] == 'dialogue' and speaker.upper() not in ('', 'UNKNOWN', 'NARRATOR') and not label.get('certain', True):
                    # The model's best judgement, not settled by the passage: filled
                    # in yellow for the reviewer, adopted unless changed.
                    return {'kind': 'dialogue', 'speaker': speaker, 'tier': 'suggested', 'basis': '模型按上下文推断的'}
                return {'kind': label['kind'], 'speaker': speaker}
            units = source_units(body.script, body.cut)
            quote_context = {u['id']: (units[i - 1]['text'] if i else '',
                                       units[i + 1]['text'] if i + 1 < len(units) else '')
                             for i, u in enumerate(units)}
            spoken = [u for u in units if u['text'].strip() and u['text'].strip()[0] in '“"「『']   # '' is "in" any string
            # No book yet: the names the speech tags themselves spell (孔乙己说：)
            # are the cast the model is told about. Without any list, the
            # abliterated fine-tune answered Kong Yiji in English — KONG YIJI,
            # CHEF, A CUSTOMER — and every name was refused as not in the text.
            from . import habits
            unquoted = [u['text'] for u in source_units(body.script, body.cut) if u['text'].strip() and u['text'].strip()[0] not in '“"「『']
            tag_names = habits.names_from_tags(unquoted, body.script)
            if not names_for_model:
                names_for_model = list(tag_names)
            # What the manuscript itself settles: a unit inside a span the
            # author coloured (or marked) has its speaker; a unit on a line
            # not read aloud (a heading) is narration kept silent. When the
            # colours settle every line that could be speech, the model is not
            # asked at all — the text never reaches it (本人 2026-09-16).
            hinted, silent_units, hint_colours = {}, set(), {}
            if body.hints:
                for u in units:
                    stripped = u['text'].strip()
                    if not stripped:
                        continue
                    a = u['start'] + u['text'].index(stripped); b = a + len(stripped)
                    for h in body.hints:
                        if h.start <= a and b <= h.end:
                            hinted[u['id']] = h.speaker.strip()
                            if h.colour and h.speaker.strip():
                                who = h.speaker.strip()
                                if h.colour not in hint_colours.get(who, []):
                                    hint_colours.setdefault(who, []).append(h.colour)
                            break
            if body.silent:
                lines = body.script.split('\n'); starts = []; pos = 0
                for line in lines:
                    starts.append(pos); pos += len(line) + 1
                silent_spans = [(starts[n], starts[n] + len(lines[n])) for n in body.silent if 0 <= n < len(lines)]
                for u in units:
                    if u['text'].strip() and any(a <= u['start'] and u['end'] <= b + 1 for a, b in silent_spans):
                        silent_units.add(u['id'])
            speech_units = spoken if spoken else [u for u in units if u['text'].strip() and u['id'] not in silent_units]
            settled_by_author = bool(hinted) and all(u['id'] in hinted or u['id'] in silent_units for u in speech_units)
            # Test doubles may not take the cast; the real engine does.
            # Worked examples for the model: confirmed exchanges of this book's other
            # chapters, else two invented ones (few-shot, 2026-09-16; off with VOXSTAGE_FEWSHOT=0).
            # Measured 2026-09-16 (14B, ten texts): the book's own examples cut the
            # lines to fix on 阿Q chapters 4 and 5 from 17 to 5; invented generic
            # examples made the texts without a book worse (5 to 14) and are not used.
            from .attribution import book_examples
            examples = []
            if os.environ.get('VOXSTAGE_FEWSHOT', '1') != '0' and body.book_id:
                with store.lock:
                    examples = book_examples(book_projects(books.get(body.book_id)), body.script)
            def annotate_with(engine_, log_name):
                if body.prepared_token:
                    prepared = prepared_results.pop(body.prepared_token, None)
                    if prepared is None:
                        raise ValueError('分批结果已失效，请从子工程重新继续。')
                    return prepared
                params = engine_.annotate.__code__.co_varnames
                kwargs = {}
                if names_for_model and 'known_names' in params:
                    kwargs['known_names'] = names_for_model
                if examples and 'examples' in params:
                    kwargs['examples'] = examples
                if body.cut and 'cut' in params:
                    kwargs['cut'] = body.cut
                elif body.cut:
                    raise ValueError('这个分角色引擎不支持按颜色切句。')
                return engine_.annotate(body.script, drafts/log_name, **kwargs)
            if settled_by_author:
                result = {'labels': [{'id': u['id'], 'kind': 'dialogue' if hinted.get(u['id'], 'NARRATOR') != 'NARRATOR' else 'narration',
                                      'speaker': (hinted[u['id']] or 'UNKNOWN') if hinted.get(u['id'], 'NARRATOR') != 'NARRATOR' else 'NARRATOR', 'certain': True} for u in units],
                          'model_id': None, 'model_sha256': None, 'settled_by': 'manuscript'}
            else:
                result = annotate_with(role_engine, draft_id+'.log')
            # Either model can answer a passage with a draft of nothing: every
            # quoted line narration, or every speaker a word the story never uses
            # (the evaluated model on a chapter with sensitive content; the abliterated one,
            # given no cast, answering Kong Yiji in English). When the chosen one
            # does, and the other is installed, ask that one before falling back
            # on the structural draft. Both runs are kept in the record.
            def placed(labels):
                by = {l['id']: l for l in labels}; pool = chinese_names(labels)
                return [u for u in spoken if u['id'] in by and vetted(by[u['id']], u, pool)['kind'] == 'dialogue'
                        and vetted(by[u['id']], u, pool)['speaker'].upper() not in ('', 'UNKNOWN')]
            def balked(labels):
                # Fewer than half the quoted lines placed. With names held to the
                # text's own script the evaluated model no longer hands in nothing
                # on the author's chapter — it names 11 of 33 lines, all right, and
                # leaves 22 blank where the other model names 28. An interim rule:
                # the second model should answer only the blocks left blank, not
                # the whole text again (Astra 2026-09-15, step 3).
                return len(spoken) >= 3 and len(placed(labels)) < 0.5 * len(spoken)
            fallback_used = None
            if (not body.prepared_token and not settled_by_author and balked(result['labels'])
                    and hasattr(role_engine, 'installed') and hasattr(role_engine, 'select')):
                from .attribution import FALLBACK_ROLE_MODELS
                others = [m['id'] for m in role_engine.installed() if m['installed'] and m['id'] != role_engine.model_id]
                rank = {m: i for i, m in enumerate(FALLBACK_ROLE_MODELS)}
                others.sort(key=lambda m: rank.get(m, len(rank)))             # the designated fallbacks first, in order
                if others:
                    chosen = role_engine.model_id
                    try:
                        role_engine.select(others[0])
                        second = annotate_with(role_engine, draft_id+'-fallback.log')
                    finally:
                        role_engine.select(chosen)
                    if len(placed(second['labels'])) > len(placed(result['labels'])):
                        result = {**second, 'first_attempt': {'model_id': result.get('model_id'), 'labels': result['labels']}}
                        fallback_used = others[0]
            # Validate even injected engines; no unbound model text reaches a project.
            from evals.speaker_attribution.source_units import bind_labels
            bind_labels(body.script,json.dumps({'labels':result['labels']}),body.cut)
            record = {**result,'draft_id':draft_id,'source_script':body.script,'language':body.language,
                      'fallback_model':fallback_used,'cut':body.cut,
                      'target_project_id': body.target_project_id}
            write_draft(record)                       # the model's answer is kept even if the rules below fail
            labels = {x['id']:x for x in result['labels']}
            units = source_units(body.script, body.cut)
            # A degenerate draft: the model called every quoted unit narration.
            # Seen 2026-09-14 on a web-novel chapter with sensitive content — 60 quoted units,
            # 70 labels, all NARRATOR; the schema forces valid JSON, so a model
            # that balks at the text answers with nothing. Hand the reviewer the
            # structural draft instead: quoted units are speech with the speaker
            # left blank (citations excepted), everything else narration.
            notice = None
            silenced = [u for u in spoken if labels[u['id']]['kind'] == 'narration']
            degenerate = len(spoken) >= 3 and (len(silenced) == len(spoken) or (len(spoken) >= 10 and len(silenced) >= 0.9 * len(spoken)))
            if fallback_used and not degenerate:
                labels_of = {m['id']: m['label'] for m in role_engine.installed()}
                notice = f'「{labels_of.get(role_engine.model_id, role_engine.model_id)}」这次没能分出说话人，已换用「{labels_of.get(fallback_used, fallback_used)}」重来一次；下面是它的草稿。'
            if degenerate:
                notice = (f'模型这次没有给出角色划分（{len(spoken)} 句引号里的话，{len(silenced)} 句被标成了旁白）。'
                          '已按引号先把对白分出来，说话人留空，请你填写。')
                for u in silenced:
                    if not (body.language == 'zh' and cites_rather_than_speaks(u)):
                        labels[u['id']] = {'id': u['id'], 'kind': 'dialogue', 'speaker': 'UNKNOWN'}
            # Whitespace between two quoted lines is a unit like any other and
            # still needs a label, but showing the reviewer an empty row to
            # assign a character to is noise. Mark it; the UI leaves it out.
            pool = chinese_names(result['labels'])
            out = [{**unit, **vetted(labels[unit['id']], unit, pool), 'blank': not unit['text'].strip()} for unit in units]
            # The author's own marks stand as they are — a name the text never
            # spells (女主, 老大) included — and no rule below touches them; a
            # silent line is narration the project keeps but does not read.
            for u in out:
                if u['id'] in hinted:
                    for key in ('tier', 'hint', 'suggested', 'basis'):
                        u.pop(key, None)
                    if hinted[u['id']] == 'NARRATOR':
                        u.update({'kind': 'narration', 'speaker': 'NARRATOR', 'source': 'mark'})
                    else:
                        u.update({'kind': 'dialogue', 'speaker': hinted[u['id']] or 'UNKNOWN', 'source': 'mark', 'basis': '原稿里标的'})
                if u['id'] in silent_units:
                    for key in ('tier', 'hint', 'suggested', 'basis'):
                        u.pop(key, None)
                    u.update({'kind': 'narration', 'speaker': 'NARRATOR', 'silent': True})
            known_names.update(name for name in hinted.values() if name and name != 'NARRATOR')
            # Lines still unplaced: who talks like this? Taught by the lines a
            # person confirmed in the same book's other chapters (runtime/habits).
            from . import habits
            profile = {}; taught = []
            if body.book_id:
                with store.lock:
                    taught = [(u['text'], l['speaker']) for p in book_projects(books.get(body.book_id))
                              for u, l in confirmed_dialogue(p)]
                profile = habits.profiles(taught)
                if profile:
                    # Filled later, inside the rules loop, where the exchange is
                    # known: a habit only fills with someone present in the
                    # exchange (阿Q chapter 4, 2026-09-16: his thoughts were filled
                    # with 赵太爷 and 老头子, the nearest profiles in the book).
                    for u in out:
                        if u['kind'] == 'dialogue' and not u['blank'] and u['speaker'].strip().upper() in ('', 'UNKNOWN'):
                            best, margin = habits.suggest(u['text'], profile)
                            if best:
                                u['habit'] = (best, margin)
            # Three rules a person applies without thinking, which the model
            # skips (本人 2026-09-15), in the order of their strength:
            #   1. the narration beside a line names its speaker — 小雪笑道：
            #      before it, or ”小雪说。 after it;
            #   2. a line that names characters is said to them, not by them —
            #      阿宁，你去问老板娘 is neither 阿宁's nor the 老板娘's, and with
            #      a cast of three that leaves the third;
            #   3. two lines in a row without narration between are seldom the
            #      same person's.
            # Rule 1 overrides the model's answer (plain); 2 and 3 fill or demote
            # to yellow. Aliases count as the name: 老板娘 is 陈小雪.
            cast = list(dict.fromkeys(list(known_names) + [u['speaker'].strip() for u in out if u['kind'] == 'dialogue' and u['speaker'].strip().upper() not in ('', 'UNKNOWN', 'NARRATOR')]
                                      + habits.names_from_tags((u['text'] for u in out if u['kind'] == 'narration' and not u['blank']), body.script)))
            cast = [aliases.get(c, c) for c in cast]; cast = list(dict.fromkeys(cast))
            # The sex of each cast member, from the voice the book gave them; and
            # what a female or male line looks like in this book, from confirmed lines.
            sex_of = {}
            if body.book_id:
                with store.lock:
                    for sibling in book_projects(books.get(body.book_id)):
                        for sp in sibling.get('voices', {}):
                            sex_of.setdefault(sp, character_sex(sibling, sp))
            sex_prof = habits.sex_profiles((t, sex_of.get(sp, '')) for t, sp in taught) if body.book_id and taught else None
            mentions = {name: [name] + [a for a, n in aliases.items() if n == name] for name in cast}
            spoken = [i for i, u in enumerate(out) if not u['blank']]
            # A quoted unit the model called narration, beside a tag that names
            # its speaker — “革命也好罢”，阿Q想， — is that person's line
            # (阿Q chapter 7, 2026-09-17). The loop below then fills it from the tag.
            for k, i in enumerate(spoken):
                u = out[i]
                text = u['text'].strip()
                if u['kind'] != 'narration' or u.get('silent') or u['id'] in hinted or not text or text[0] not in '“"「『':
                    continue
                if body.language == 'zh' and cites_rather_than_speaks(u):
                    continue
                before = out[spoken[k - 1]] if k > 0 else None
                after = out[spoken[k + 1]] if k + 1 < len(spoken) else None
                before_text = before['text'] if before and before['kind'] == 'narration' else ''
                after_text = after['text'] if after and after['kind'] == 'narration' else ''
                tag_here = habits.english_tag(before_text, after_text, mentions) if body.language == 'en' else habits.speech_tag(before_text, after_text, mentions)
                if tag_here or (body.language == 'zh' and habits.anonymous_tag(before_text, after_text)):
                    u.update({'kind': 'dialogue', 'speaker': 'UNKNOWN'}); u.pop('suggested', None)
            # Exchanges: a run of lines with only short beats between them. A
            # long stretch of narration, or one that opens with a change of
            # time or place, ends the exchange (Astra 2026-09-15: turn-taking
            # must not relay across scenes; an unnamed person in one exchange
            # is not the unnamed person of the next). Every unit carries its
            # exchange number; the page resets its own turn-taking on it.
            block = 0; since_line = None
            for i in spoken:
                u = out[i]
                if u['kind'] == 'dialogue':
                    if since_line is not None and habits.scene_cut(since_line):
                        block += 1
                    since_line = ''
                elif since_line is not None:
                    since_line += u['text']
                u['block'] = block
            for u in out:
                u.setdefault('block', 0)
                # The paragraph a unit sits in, so the page can show units of one
                # paragraph together (本人 2026-09-16: a line the model gave to the
                # wrong person was obviously the previous speaker's once seen in
                # its paragraph). A unit that opens with a line break belongs to
                # the paragraph after it.
                lead = len(u['text']) - len(u['text'].lstrip('\n'))
                u['para'] = body.script[:u['start']].count('\n') + lead
            LETTERS = '甲乙丙丁戊己庚辛壬癸'
            anonymous = {}          # block -> the stand-in name of its unnamed single speaker
            participants = {}       # block -> names settled in it by the model with certainty, a tag or a stand-in, in order
            def called_names(text, mentions_):
                text = habits.outer_speech(text)
                return [name for name, forms in mentions_.items() if any(habits.addressed(text, f) for f in forms)]
            def recent_names(i, blk, beyond=False):
                """Characters of this exchange before out[i], most recent first: settled
                speakers and names its narration mentions (aliases count as the name).
                With `beyond`, earlier exchanges too — for a pronoun whose exchange
                names nobody (阿Q's thoughts open a scene on their own)."""
                seen = []
                for prior in reversed(out[:i]):
                    if prior.get('block') != blk and not beyond:
                        break
                    found = []
                    if prior['kind'] == 'dialogue':
                        who = prior['speaker'].strip()
                        if who.upper() not in ('', 'UNKNOWN', 'NARRATOR') and (prior.get('tier') != 'suggested' or prior.get('stand_in')):
                            found.append(who)
                    else:
                        # In narration, a name opening a clause (the subject: 阿Q便…)
                        # counts before one inside a clause (an object: 看着桩家…).
                        clean = habits.STRIP.sub('', prior['text'])
                        subjects, objects = [], []
                        for name, forms in mentions.items():
                            for f in forms:
                                k = clean.rfind(f)
                                if k < 0:
                                    continue
                                (subjects if k == 0 or clean[k - 1] in '，。！？；：、' else objects).append((k, name))
                        found = [name for _, name in sorted(subjects, reverse=True)] + [name for _, name in sorted(objects, reverse=True)]
                    for name in found:
                        if name not in seen:
                            seen.append(name)
                return seen
            def in_exchange(i, blk):
                return set(recent_names(i, blk)) | set(participants.get(blk, []))
            def settled(name, blk):
                participants.setdefault(blk, [])
                if name not in participants[blk]:
                    participants[blk].append(name)
            def settled_recent(i, blk):
                """The last two distinct speakers before out[i] in the same exchange — lines
                the model was sure of, tagged, stand-ins or filled by this rule; not other guesses."""
                recent = []
                for prior in reversed(out[:i]):
                    if prior.get('block') != blk:
                        break
                    who = prior['speaker'].strip()
                    if prior['kind'] == 'dialogue' and who.upper() not in ('', 'UNKNOWN', 'NARRATOR') and who not in recent \
                            and (prior.get('tier') != 'suggested' or prior.get('stand_in') or prior.get('basis', '').startswith('上一句已经是这个人，一来一往')):
                        recent.append(who)
                        if len(recent) == 2:
                            break
                return recent
            for k, i in enumerate(spoken):
                u = out[i]
                if u['kind'] != 'dialogue':
                    continue
                blk = u['block']
                if u.get('source') == 'mark':                 # the author said so; nothing to add
                    if u['speaker'].upper() not in ('', 'UNKNOWN'):
                        settled(u['speaker'], blk)
                    continue
                before = out[spoken[k - 1]] if k > 0 else None
                after = out[spoken[k + 1]] if k + 1 < len(spoken) else None
                # A speech over several paragraphs opens each with “ and closes
                # only the last: a quoted paragraph right after an unclosed one
                # is the same speaker's (阿Q chapter 7, 2026-09-17).
                if before and before['kind'] == 'dialogue' and habits.run_on(before['text']) and u['text'].strip()[0] in '“"「『' \
                        and before['speaker'].strip().upper() not in ('', 'UNKNOWN', 'NARRATOR'):
                    for key in ('hint', 'suggested'):
                        u.pop(key, None)
                    u.update({'speaker': before['speaker'], 'basis': '接着上一段，同一个人的话', 'continued': True})
                    if before.get('tier') == 'suggested':
                        u['tier'] = 'suggested'
                    else:
                        u.pop('tier', None)
                    if before.get('source') in ('tag', 'model'):
                        u['source'] = before['source']
                    settled(before['speaker'].strip(), blk)
                    continue
                tagged = (habits.english_tag if body.language == 'en' else habits.speech_tag)(
                    before['text'] if before and before['kind'] == 'narration' else '',
                    after['text'] if after and after['kind'] == 'narration' else '', mentions)
                if tagged:
                    if u['speaker'].strip() != tagged:
                        u.update({'speaker': tagged, 'basis': '旁边的叙述点了这个名字'}); u.pop('tier', None); u.pop('hint', None)
                    u['source'] = 'tag'; settled(tagged, blk)
                    continue
                # A tag that names nobody in particular (有的叫道, 旁人便又问道,
                # 一个喝酒的人说道): the story never names this speaker, so the
                # line gets a stand-in, yellow, over whatever the model said —
                # 众人 for a crowd, 某人甲/乙/… for one person, lettered per
                # exchange. Renaming the stand-in once carries its lines along.
                found = habits.anonymous_tag(before['text'] if before and before['kind'] == 'narration' else '',
                                             after['text'] if after and after['kind'] == 'narration' else '', with_phrase=True) if body.language == 'zh' else None
                stand_in = found[0] if found else None
                if stand_in:
                    if stand_in == habits.STAND_INS['one']:
                        # One stranger per exchange and per way of naming him: 有人 and
                        # 一个喝酒的人 in the same exchange are two (Astra 2026-09-16).
                        key = (blk, found[1])
                        if key not in anonymous:
                            n = len(anonymous)
                            anonymous[key] = stand_in + (LETTERS[n] if n < len(LETTERS) else str(n + 1))
                        stand_in = anonymous[key]
                    was = u['speaker'].strip()
                    u.update({'speaker': stand_in, 'tier': 'suggested', 'basis': '叙述里只说是没有名字的人，先记作', 'stand_in': True, 'source': 'tag'})
                    if was.upper() not in ('', 'UNKNOWN', 'NARRATOR') and was != stand_in:
                        u['hint'] = was
                    settled(stand_in, blk)
                    continue
                sp = u['speaker'].strip()
                named = sp.upper() not in ('', 'UNKNOWN', 'NARRATOR')
                # 他想：/ 她说： — the narration names the speaker by a pronoun.
                # Who that is falls to the exchange: the most recent character
                # of that sex named in it (settled as a speaker, or mentioned in
                # its narration). Yellow: a reader's reading, not the text's word.
                # A clause that ends in a colon introduces the quote even without
                # a verb of saying — 阿Q的思想也迸跳起来了：—— (chapter 7); with a
                # name, yellow over the model's answer; with 他/她, resolved below.
                lead = habits.colon_lead(before['text'] if before and before['kind'] == 'narration' else '', mentions)
                if lead and lead not in ('他', '她') and lead not in called_names(u['text'], mentions):
                    if sp != lead:
                        u.update({'speaker': lead, 'tier': 'suggested', 'basis': '冒号引出这句话的是', **({'hint': sp} if named else {})})
                    settled(lead, blk)
                    continue
                pronoun = (habits.pronoun_tag(before['text'] if before and before['kind'] == 'narration' else '', mentions)
                           or habits.pronoun_closing(after['text'] if after and after['kind'] == 'narration' else '')
                           or (lead if lead in ('他', '她') else None))
                if pronoun:
                    referent = None
                    wanted = 'm' if pronoun == '他' else 'f'
                    for name in recent_names(i, blk) or recent_names(i, blk, beyond=True):
                        if name in ('我', '你', '您', '咱', '俺'):          # 他 is never the narrator's own I
                            continue
                        if sex_of.get(name) in ('', None) or sex_of.get(name) == wanted:
                            referent = name; break
                    if referent and referent not in called_names(u['text'], mentions):
                        # Who a pronoun means is a reading, not the text's word:
                        # it fills an empty line and only questions a named one
                        # (2026-09-17, eleven texts: overriding the 14B's name
                        # never mended a line and twice spoiled one).
                        if sp != referent and named:
                            u.update({'tier': 'suggested', 'basis': f'叙述说「{pronoun}」，这一段最近提到的是{referent}；模型说是'})
                            settled(sp, blk)
                        else:
                            if sp != referent:
                                u.update({'speaker': referent, 'tier': 'suggested', 'basis': f'叙述说「{pronoun}」，这一段最近提到的是'})
                            settled(referent, blk)
                        continue
                if u.get('habit') and not named:
                    best, margin = u.pop('habit')
                    if margin >= habits.MARGIN and best in in_exchange(i, blk) and best not in called_names(u['text'], mentions):
                        u.update({'speaker': best, 'tier': 'suggested', 'basis': '按说话习惯，像是'})
                    else:
                        u['hint'] = best
                    sp = u['speaker'].strip(); named = sp.upper() not in ('', 'UNKNOWN', 'NARRATOR')
                u.pop('habit', None)
                # “那么，明天拿来就是”，赵太爷却不甚热心了。“阿Q，你以后……” — the beat
                # joined to a quote by a comma is about its speaker, and the quote
                # that follows in the same paragraph is usually his too (本人
                # 2026-09-16, 阿Q; one such case in the labelled texts, so yellow).
                beat = habits.comma_beat(after['text'] if after and after['kind'] == 'narration' else '', mentions)
                if beat and beat not in called_names(u['text'], mentions):
                    if sp != beat:
                        u.update({'speaker': beat, 'tier': 'suggested', 'basis': '紧跟着的叙述说的是这个人，像是'}); u.pop('hint', None)
                    u['beat'] = beat
                if before and before['kind'] == 'narration' and before.get('beat_of') and '\n' not in before['text'] \
                        and before['beat_of'] not in called_names(u['text'], mentions) and sp != before['beat_of']:
                    # A new speaker usually gets a new paragraph; the model's
                    # answer is kept as the hint, the reviewer sees both.
                    u.update({'speaker': before['beat_of'], 'tier': 'suggested', 'basis': '同一段里紧跟着这个人的动作，像是', **({'hint': sp} if named else {})})
                if beat and after is not None:
                    after['beat_of'] = beat
                sp = u['speaker'].strip()
                named = sp.upper() not in ('', 'UNKNOWN', 'NARRATOR')
                # Rule 2, graded by evidence (Astra 2026-09-15: a name in the line
                # is evidence, not a veto). Naming oneself — 我叫陈小雪 — is the
                # opposite evidence and settles the line; a call — 老板娘～ — is not
                # the called person's line; a bare mention only asks for a look.
                outer = habits.outer_speech(u['text'])
                introduced = next((name for name, forms in mentions.items() if any(habits.self_introduced(outer, f) for f in forms)), None)
                called = [name for name, forms in mentions.items() if any(habits.addressed(outer, f) for f in forms)]
                spoken_of = [name for name, forms in mentions.items() if name not in called and any(habits.mentioned(outer, f) for f in forms)]
                # Who else is in this exchange: settled so far here, else the cast.
                local = [c for c in participants.get(blk, [])]
                if introduced:
                    if sp != introduced:
                        u.update({'speaker': introduced, 'tier': 'suggested', 'basis': '句里自报家门，像是'})
                    settled(introduced, blk)
                    continue
                if named and sp in called:
                    others = [c for c in (local or cast) if c not in called]
                    if len(others) == 1:
                        u.update({'speaker': others[0], 'tier': 'suggested', 'basis': '句里叫到了别人，剩下的只有'})
                    else:
                        u.update({'tier': 'suggested', 'basis': '句里叫到了这个名字，不像是本人说的；像是'})
                        if profile:
                            best, margin = habits.suggest(u['text'], profile)
                            if best and best not in called and margin >= habits.MARGIN:
                                u['speaker'] = best
                elif named and sp in spoken_of and not labels[u['id']].get('certain', True):
                    u.update({'tier': 'suggested', 'basis': '句里提到了这个名字，请看一眼；像是'})
                elif named and sp in spoken_of:
                    u.update({'tier': 'suggested', 'basis': '句里提到了自己的名字，请看一眼；模型说是'})
                # Rule 4 (本人 2026-09-15: 分清男女，至少能猜对一半): a line that reads
                # like the other sex's lines in this book is not this speaker's.
                # Measured chapter one → two: 27 of 28 decided lines right. The sex
                # of a character is what the book says of them (settings), else
                # what their voice suggests; a weak clue, never plain.
                # Weak evidence, kept weak (本人 2026-09-16: “老Q”, “得，锵，锵令锵，锵！”
                # and “阿Q！” were all called "like a woman's line" — noise on short
                # lines): it needs a line long enough to have a style, a wider
                # margin, and a same-sex person present in the exchange to
                # suggest instead. With nobody to suggest it says nothing.
                line_sex, sex_margin = habits.sex_of_line(u['text'], sex_prof) if sex_prof else (None, 0.0)
                sp = u['speaker'].strip()
                excluded = set(called)
                long_enough = len(habits.STRIP.sub('', u['text'])) >= 8
                if line_sex and long_enough and sex_margin >= 2 * habits.SEX_MARGIN and sp in sex_of and sex_of[sp] and sex_of[sp] != line_sex and not u.get('decided'):
                    same_sex = [c for c in in_exchange(i, blk) if sex_of.get(c) == line_sex and c not in excluded and c != sp]
                    pick = None
                    if profile:
                        pick = next((c for c, _ in habits.rank(u['text'], profile) if c in same_sex), None)
                    pick = pick or (same_sex[0] if len(same_sex) == 1 else None)
                    if pick:
                        # A question, not a change of name (2026-09-17: the one
                        # line it changed on the eleven texts — 老尼姑's “那秀才
                        # 和洋鬼子！” — it changed wrongly).
                        u.update({'tier': 'suggested', 'basis': ('这句像女生说的' if line_sex == 'f' else '这句像男生说的') + f'，请看一眼（{pick}？）；模型说是'})
                # A line still unplaced between two people who are settled in this
                # exchange takes the one who did not speak last (yellow) — the
                # page's own turn-taking, applied here so that rule 3 below can
                # carry the alternation on through it (孔乙己, 2026-09-17: the
                # 后来怎么样 exchange — a question the model left open, an answer
                # it gave to the wrong man, six lines running).
                sp = u['speaker'].strip()
                if sp.upper() in ('', 'UNKNOWN') and before and before['kind'] == 'dialogue' \
                        and before['speaker'].strip().upper() not in ('', 'UNKNOWN', 'NARRATOR'):
                    recent = settled_recent(i, blk)
                    others = [c for c in recent if c != before['speaker'].strip() and c not in excluded]
                    if len(recent) == 2 and len(others) == 1:
                        u.update({'speaker': others[0], 'tier': 'suggested', 'basis': '上一句已经是这个人，一来一往像是'})
                # Rule 3: the same speaker twice running, no narration between.
                # In the labelled texts two quoted lines running were never one
                # person's (0 of 36 pairs, 2026-09-16), so this applies even when
                # the model was certain — as yellow, with the other of the last
                # two people who spoke in this exchange. Nobody else settled in
                # the exchange: the line is flagged, not filled.
                sp = u['speaker'].strip()
                if before and before['kind'] == 'dialogue' and before['speaker'].strip() == sp and sp.upper() not in ('', 'UNKNOWN'):
                    recent = settled_recent(i, blk)
                    alternatives = [c for c in (local or []) if c != sp and c not in excluded]
                    pick = None
                    if profile and alternatives:
                        pick = next((c for c, _ in habits.rank(u['text'], profile) if c in alternatives), None)
                    pick = pick or next((c for c in recent if c in alternatives), None) or (alternatives[0] if len(alternatives) == 1 else None)
                    if pick:
                        u.update({'speaker': pick, 'tier': 'suggested', 'basis': '上一句已经是这个人，一来一往像是'})
                    elif u.get('tier') != 'suggested':
                        u.update({'tier': 'suggested', 'basis': '上一句已经是这个人，很少连着两句；像是'})
                sp = u['speaker'].strip()
                if sp.upper() not in ('', 'UNKNOWN', 'NARRATOR') and u.get('tier') != 'suggested':
                    u['source'] = 'model'; settled(sp, blk)
                elif u.get('basis', '').startswith('上一句已经是这个人，一来一往'):
                    settled(sp, blk)
            for u in out:
                u.pop('habit', None)
            # The cast: every name the draft gave a line, with how it came to be
            # (Astra 2026-09-16: 角色编号独立于名字). A chapter's cast is the
            # book's; a draft made outside a book keeps its own until confirmed.
            from . import cast as C
            with store.lock:
                if body.book_id:
                    book_record = books.get(body.book_id)
                    cast = books.cast_of(book_record, names=sorted(known_names))    # the book's people, confirmed in its other chapters
                else:
                    cast = []
                for u in out:
                    if u['kind'] != 'dialogue' or u['blank']:
                        continue
                    name = u['speaker'].strip()
                    if name.upper() in ('', 'UNKNOWN', 'NARRATOR'):
                        continue
                    source = {'mark': 'mark', 'tag': 'tag', 'model': 'model'}.get(u.get('source') or '', 'rule')
                    entry, _ = C.ensure(cast, name, source, introduced={'draft_id': draft_id, 'unit_id': u['id']}, colours=hint_colours.get(name, ()))
                    u['cast_id'] = entry['id']
                if body.book_id:
                    book_record['aliases'] = C.alias_table(cast); books.save(book_record)
                labels_of = {m['id']: m['label'] for m in role_engine.installed()} if hasattr(role_engine, 'installed') else {}
                model_note = ('作者标的，没有用模型' if settled_by_author else
                              (labels_of.get(result.get('model_id'), result.get('model_id') or '本机模型') + ('（默认模型交了白卷，换的）' if fallback_used else '')))
                view = {'draft_id': draft_id, 'notice': notice, 'units': out, 'revision': 1, 'decisions': {}, 'cast': cast,
                        'model': {'id': result.get('model_id'), 'note': model_note}}
                record.update({'units': out, 'revision': 1, 'decisions': {}, 'book_id': body.book_id, 'cast': None if body.book_id else cast, 'model_note': model_note,
                               'narration_colour': (hint_colours.get('NARRATOR') or [None])[0]})
                write_draft(record)
            return view
        except ValueError as exc:
            # bind_labels rejects a malformed model response. Its wording names
            # internal structures, which tells the reader nothing they can act on.
            # The cause still goes to the server log (2026-09-16: a draft failed
            # for a chapter of a book that had been deleted, and the message
            # blamed the text).
            logging.warning('Role draft %s failed: %s', draft_id, exc)
            raise ValueError('这段原文的角色划分没有成功，通常是角色太多或对话太密。\n\n'
                             '可以先分成两三段分别导入，之后在原稿编辑里合起来；'
                             '或者直接重试一次，每次的结果会略有不同。') from exc
        except (OSError, KeyError, TypeError) as exc:
            logging.warning('Role draft %s failed: %r', draft_id, exc)
            raise ValueError('角色草稿生成失败，请保留原稿后重试。') from exc
        finally:
            if owns_active:
                with store.lock:
                    active['project_id'] = None

    def attribution_batch_context(project):
        from .attribution import book_examples
        names = []
        examples = []
        book_id = (project.get('book') or {}).get('id')
        if book_id:
            book = books.get(book_id)
            names.extend(entry['name'] for entry in book.get('cast', [])
                         if entry.get('name') and entry['name'] not in ('旁白', 'Narrator', 'NARRATOR'))
            siblings = book_projects(book)
            for sibling in siblings:
                for name in sibling.get('voices', {}):
                    if name not in ('旁白', 'Narrator', 'NARRATOR') and name not in names:
                        names.append(name)
            examples = book_examples(siblings, project['source_script'])
        return names, examples

    def attribution_capacity(project):
        from .attribution_batches import plan_batches
        from .capacity import role_batch_limits
        model_id = getattr(role_engine, 'model_id', None)
        spec = ROLE_MODELS.get(model_id, {})
        limits = role_batch_limits(spec)
        names, examples = attribution_batch_context(project)
        plan = plan_batches(project['source_script'], project.get('cut'), limits,
                            known_names=names, examples=examples)
        installed = next((item for item in role_engine.installed() if item['id'] == model_id), None) \
            if hasattr(role_engine, 'installed') else None
        return {
            'model': {'id': model_id, 'label': (installed or {}).get('label', model_id),
                      'installed': (installed or {}).get('installed', bool(getattr(role_engine, 'ready', False))),
                      'loadable': (installed or {}).get('loadable', bool(getattr(role_engine, 'ready', False))),
                      'recommended_for_machine': (installed or {}).get('recommended', False)},
            'machine': {'memory_gb': limits['memory_gb']},
            'limits': {key: limits[key] for key in ('chars', 'units', 'context', 'max_tokens')},
            'source': {'chars': len(project['source_script']), 'units': plan['total_units'],
                       'estimated_segments': sum(max(1, (len(unit['text']) + (60 if project['language'] == 'zh' else 240) - 1)
                                                          // (60 if project['language'] == 'zh' else 240))
                                                 for unit in source_units(project['source_script'], project.get('cut'))
                                                 if unit['text'].strip()),
                       'segment_limit': limits['segments']},
            'batches': len(plan['batches']),
            'batch_sizes': [len(batch['target_ids']) for batch in plan['batches']],
            'explanation': ('章节原稿保持完整；角色归属会按本机内存与当前模型的较小上限分批。'
                            '批次包含只读上下文，人物表和示例也计入预算。'),
            '_plan': plan, '_known_names': names, '_examples': examples,
        }

    def wait_for_model_slot(project_id):
        while True:
            with store.lock:
                project = store.read(project_id)
                batch = project.get('attribution_batch') or {}
                if batch.get('cancel_requested'):
                    return False
                if not active['project_id']:
                    active['project_id'] = 'attribution:' + project_id
                    return True
            time.sleep(.2)

    def attribution_batch_worker(project_id):
        from .core import uid
        from .capacity import estimate_role_batch, role_batch_limits
        from .attribution import FALLBACK_ROLE_MODELS
        from .attribution_batches import (combined_labels, progress, source_fingerprint,
                                          units_for_batch, validate_batch_labels)
        owns_active = False
        selected_before = getattr(role_engine, 'model_id', None)
        try:
            if not wait_for_model_slot(project_id):
                with store.lock:
                    project = store.read(project_id)
                    project['job'].update(status='cancelled', current_batch=None)
                    store.write(project)
                return
            owns_active = True
            with store.lock:
                project = store.read(project_id)
                plan = project['attribution_batch']
                model_id = plan['model_id']
            if hasattr(role_engine, 'select') and getattr(role_engine, 'model_id', None) != model_id:
                role_engine.select(model_id)
            for index in range(len(plan['batches'])):
                with store.lock:
                    project = store.read(project_id)
                    plan = project['attribution_batch']
                    if plan.get('cancel_requested'):
                        project['job'].update(status='cancelled', current_batch=None)
                        store.write(project)
                        return
                    batch = plan['batches'][index]
                    if batch.get('status') == 'completed':
                        continue
                    batch.update(status='running', error=None)
                    project['job'].update(status='running', current_batch=index + 1,
                                          completed=progress(plan)['completed'], total=len(plan['batches']))
                    store.write(project)
                    text, cut = project['source_script'], project.get('cut')
                    known_names = plan.get('known_names', [])
                    examples = plan.get('examples', [])
                    limits = plan['limits']
                if source_fingerprint(text, cut) != plan['source_sha256']:
                    raise ValueError('原稿已改变，不能继续旧批次。')
                batch_units = units_for_batch(text, cut, batch)
                kwargs = {'known_names': known_names, 'examples': examples,
                          'units_override': batch_units,
                          'strict_ids': True, 'limits_override': limits}
                if cut:
                    kwargs['cut'] = cut
                result = role_engine.annotate(text, drafts / f'{project_id}-batch-{index + 1}.log', **kwargs)
                labels = validate_batch_labels(batch, result['labels'])
                target_ids = set(batch['target_ids'])
                quoted = {unit['id'] for unit in batch_units
                          if unit['id'] in target_ids
                          and unit['text'].strip().startswith(('“', '"', '「', '『'))}
                def placed(rows):
                    return sum(row['id'] in quoted and row['kind'] == 'dialogue'
                               and row['speaker'].strip().upper() not in ('', 'UNKNOWN', 'NARRATOR')
                               for row in rows)
                fallback_model = None
                first_model = result.get('model_id')
                if (len(quoted) >= 3 and placed(labels) < .5 * len(quoted)
                        and hasattr(role_engine, 'installed') and hasattr(role_engine, 'select')):
                    installed = [item for item in role_engine.installed()
                                 if item.get('installed') and item.get('loadable', True)
                                 and item['id'] != model_id]
                    order = {candidate: rank for rank, candidate in enumerate(FALLBACK_ROLE_MODELS)}
                    installed.sort(key=lambda item: order.get(item['id'], len(order)))
                    fallback_choice = next((
                        (item['id'], role_batch_limits(ROLE_MODELS[item['id']]))
                        for item in installed
                        if estimate_role_batch(
                            sum(len(unit['text']) for unit in batch_units), len(batch_units),
                            role_batch_limits(ROLE_MODELS[item['id']]),
                            plan.get('extra_prompt_tokens', 0))['fits']), None)
                    if fallback_choice:
                        fallback_model, fallback_limits = fallback_choice
                        try:
                            role_engine.select(fallback_model)
                            fallback_kwargs = {**kwargs, 'limits_override': fallback_limits}
                            second = role_engine.annotate(
                                text, drafts / f'{project_id}-batch-{index + 1}-fallback.log',
                                **fallback_kwargs)
                            second_labels = validate_batch_labels(batch, second['labels'])
                            if placed(second_labels) > placed(labels):
                                result, labels = second, second_labels
                            else:
                                fallback_model = None
                        finally:
                            role_engine.select(model_id)
                with store.lock:
                    project = store.read(project_id)
                    current = project['attribution_batch']['batches'][index]
                    if current.get('status') != 'running' or current.get('sent_ids') != batch.get('sent_ids'):
                        raise RuntimeError('批次状态已改变，请重新继续。')
                    current.update(status='completed', labels=labels, error=None,
                                   model_id=result.get('model_id'), model_sha256=result.get('model_sha256'),
                                   prompt_sha256=result.get('prompt_sha256'), seconds=result.get('seconds_measured'),
                                   repaired=result.get('repaired'), fallback_model=fallback_model,
                                   first_model_id=first_model)
                    done = progress(project['attribution_batch'])
                    project['job'].update(completed=done['completed'], total=done['total'], current_batch=None)
                    store.write(project)
            with store.lock:
                project = store.read(project_id)
                plan = project['attribution_batch']
                labels = combined_labels(project['source_script'], project.get('cut'), plan)
                token = uid()
                prepared_results[token] = {
                    'labels': labels, 'model_id': plan['model_id'],
                    'model_sha256': plan.get('model_sha256'), 'batch_plan_version': plan['version'],
                    'batch_count': len(plan['batches']), 'raw_response': None,
                }
                request = RoleDraftRequest.model_construct(
                    script=project['source_script'], language=project['language'],
                    book_id=(project.get('book') or {}).get('id'), hints=project.get('hints'),
                    silent=project.get('silent'), cut=project.get('cut'),
                    prepared_token=token, target_project_id=project_id)
            draft = role_draft(request)
            prepared_results.pop(token, None)
            with store.lock:
                project = store.read(project_id)
                project['attribution_batch']['draft_id'] = draft['draft_id']
                project['attribution_batch']['completed_at'] = time.time()
                project['job'].update(status='completed', completed=len(plan['batches']),
                                      total=len(plan['batches']), current_batch=None, error=None)
                project['revision'] += 1
                store.write(project)
                record = read_draft(draft['draft_id'])
                record['target_project_revision'] = project['revision']
                write_draft(record)
        except Exception as exc:
            logging.exception('Project attribution batch failed for %s', project_id)
            with store.lock:
                try:
                    project = store.read(project_id)
                    plan = project.get('attribution_batch') or {}
                    for batch in plan.get('batches', []):
                        if batch.get('status') == 'running':
                            batch.update(status='failed', error=str(exc))
                    project.setdefault('job', {}).update(status='failed', current_batch=None,
                                                          error=str(exc))
                    store.write(project)
                except (OSError, ValueError, KeyError):
                    pass
        finally:
            if hasattr(role_engine, 'select') and selected_before and getattr(role_engine, 'model_id', None) != selected_before:
                try:
                    role_engine.select(selected_before)
                except ValueError:
                    pass
            if owns_active:
                with store.lock:
                    if active.get('project_id') == 'attribution:' + project_id:
                        active['project_id'] = None

    @app.get('/api/projects/{project_id}/attribution/capacity')
    def project_attribution_capacity(project_id: str):
        with store.lock:
            project = store.read(project_id)
            if project.get('settings_schema') != 1 or project.get('processing_state') != 'unprocessed':
                raise ValueError('只有新版未处理子工程需要分批角色归属。')
            result = attribution_capacity(project)
            return {key: value for key, value in result.items() if not key.startswith('_')}

    @app.post('/api/projects/{project_id}/attribution/start')
    def start_project_attribution(project_id: str, body: AttributionBatchRequest):
        from .attribution_batches import resume_plan
        with store.lock:
            project = store.read(project_id)
            if project.get('settings_schema') != 1 or project.get('processing_state') != 'unprocessed':
                raise ValueError('只有新版未处理子工程可以继续角色归属。')
            if project['revision'] != body.revision:
                raise RuntimeError('工程已改变，请刷新后再继续。')
            if project.get('job', {}).get('status') in ('queued', 'running'):
                raise RuntimeError('这个子工程已经在等待或处理中。')
            book_id = (project.get('book') or {}).get('id')
            if book_id:
                book = books.get(book_id)
                for member_id in book.get('members', []):
                    if member_id == project_id:
                        continue
                    sibling = store.read(member_id)
                    if sibling.get('job', {}).get('status') in ('queued', 'running'):
                        raise RuntimeError('同一主工程已有章节在处理，请等它完成。')
            capacity = attribution_capacity(project)
            if not capacity['model']['installed']:
                raise ValueError('当前分角色模型尚未安装。')
            if not capacity['model']['loadable']:
                raise ValueError('当前模型不适合在这台电脑的内存配置上加载，请先换较小模型。')
            if capacity['source']['estimated_segments'] > capacity['source']['segment_limit']:
                raise ValueError(
                    f"本章预计至少形成 {capacity['source']['estimated_segments']} 个片段，"
                    f"当前电脑的工程上限是 {capacity['source']['segment_limit']} 个；请先拆成两个作者章节。")
            model_id = capacity['model']['id']
            old = project.get('attribution_batch')
            if body.resume and old and not old.get('draft_id'):
                plan = resume_plan(old, project['source_script'], project.get('cut'), model_id)
            else:
                plan = capacity['_plan']
                plan.update(model_id=model_id, model_sha256=getattr(role_engine, 'sha256', None),
                            known_names=capacity['_known_names'], examples=capacity['_examples'])
            plan['cancel_requested'] = False
            project['attribution_batch'] = plan
            project['job'] = {'kind': 'attribution', 'status': 'queued',
                              'total': len(plan['batches']), 'completed': sum(
                                  batch.get('status') == 'completed' for batch in plan['batches']),
                              'current_batch': None, 'error': None,
                              'queued_at': time.time()}
            project['revision'] += 1
            store.write(project)
            executor.submit(attribution_batch_worker, project_id)
            return project_service.public_project(project, engine, checker)

    @app.post('/api/projects/{project_id}/attribution/cancel')
    def cancel_project_attribution(project_id: str):
        with store.lock:
            project = store.read(project_id)
            if project.get('job', {}).get('kind') != 'attribution' or project['job'].get('status') not in ('queued', 'running'):
                raise ValueError('这个子工程没有正在等待或运行的角色归属。')
            project.setdefault('attribution_batch', {})['cancel_requested'] = True
            store.write(project)
        return {'project_id': project_id, 'cancel_requested': True}

    @app.get('/api/model-tasks')
    def model_tasks():
        tasks = []
        busy_books = set()
        with store.lock:
            for path in store.root.glob('*/project.json'):
                project = json.loads(path.read_text())
                job = project.get('job') or {}
                if job.get('status') not in ('queued', 'running'):
                    continue
                book_id = (project.get('book') or {}).get('id')
                if book_id:
                    busy_books.add(book_id)
                tasks.append({'project_id': project['id'], 'book_id': book_id,
                              'kind': job.get('kind'), 'status': job.get('status'),
                              'completed': job.get('completed', 0), 'total': job.get('total', 0),
                              'queued_at': job.get('queued_at')})
        tasks.sort(key=lambda item: item.get('queued_at') or 0)
        position = 0
        for task in tasks:
            if task['status'] == 'queued':
                position += 1
                task['queue_position'] = position
        return {'active': active.get('project_id'), 'busy_books': sorted(busy_books), 'tasks': tasks}

    def apply_decisions(units, decisions):
        """The page view with the reviewer's saved decisions laid over it: a decided
        unit shows the reviewer's speaker and kind, plain, and says so."""
        out = []
        for u in units:
            d = decisions.get(u['id'])
            if not d:
                out.append(u); continue
            v = {k: x for k, x in u.items() if k not in ('tier', 'hint', 'suggested', 'basis')}
            if d.get('kind'):
                v['kind'] = d['kind']
            if d.get('speaker') is not None:
                v['speaker'] = d['speaker']
            v['decided'] = {'edited': bool(d.get('edited')), 'confirmed': bool(d.get('confirmed')), 'source': d.get('source', 'person')}
            out.append(v)
        return out

    @app.get('/api/attribution/draft/{draft_id}')
    def get_draft(draft_id: str):
        """A draft as the page shows it, with the reviewer's saved decisions and the
        cast — so a review survives a refresh, a step back, or another day."""
        if not re.fullmatch(r'[a-f0-9]{32}', draft_id):
            raise ValueError('找不到这份草稿。')
        with store.lock:
            record = read_draft(draft_id)
            if 'units' not in record:
                raise ValueError('这份草稿是旧版本做的，没有保存页面；请重新生成一次。')
            cast, _ = draft_cast(record)
            return {'draft_id': draft_id, 'revision': record.get('revision', 1), 'decisions': record.get('decisions', {}),
                    'units': apply_decisions(record['units'], record.get('decisions', {})), 'cast': cast,
                    'model': {'id': record.get('model_id'), 'note': record.get('model_note') or record.get('model_id') or ''},
                    'language': record['language'], 'book_id': record.get('book_id'), 'notice': record.get('notice'),
                    'target_project_id': record.get('target_project_id'),
                    'confirmed_project_id': record.get('confirmed_project_id'), 'abandoned': bool(record.get('abandoned'))}

    @app.delete('/api/attribution/draft/{draft_id}')
    def abandon_draft(draft_id: str):
        """An unfinished review the reviewer does not want to finish (本人
        2026-09-17: 继续上次的复核 could only be continued). The record stays —
        it holds the model's answers and the decisions made so far — but no
        page offers it again; a draft already confirmed into a project is
        left as it is."""
        if not re.fullmatch(r'[a-f0-9]{32}', draft_id):
            raise ValueError('找不到这份草稿。')
        with store.lock:
            record = read_draft(draft_id)
            if record.get('confirmed_project_id'):
                raise ValueError('这份草稿已经确认成工程了，没有可放弃的复核。')
            record['abandoned'] = True; record['abandoned_at'] = time.time()
            write_draft(record)
        return {'draft_id': draft_id, 'abandoned': True}

    @app.patch('/api/attribution/draft/{draft_id}')
    def patch_draft(draft_id: str, body: DraftPatch):
        """The reviewer's decisions, saved as they are made (Astra 2026-09-16:
        人工决定保存，刷新与重算保护). Each save names the revision it saw; a
        stale one is refused with the current state, and the page reconciles.
        Also renames, aliases (a rename carried along) and splits in the cast."""
        from . import cast as C
        if not re.fullmatch(r'[a-f0-9]{32}', draft_id):
            raise ValueError('找不到这份草稿。')
        with store.lock:
            record = read_draft(draft_id)
            current = record.get('revision', 1)
            if body.expected_revision != current:
                raise HTTPException(status_code=409, detail={'message': '这份草稿在别处改过了，页面已按最新状态更新。', 'revision': current,
                                                             'decisions': record.get('decisions', {})})
            cast, book_record = draft_cast(record)
            units = {u['id']: u for u in record.get('units', [])}
            decisions = record.setdefault('decisions', {})
            now = time.strftime('%Y-%m-%d %H:%M:%S')
            events = []
            if body.rename:
                entry = C.rename(cast, body.rename.cast_id, body.rename.name)
                for d in decisions.values():                     # decisions name the character by id; their name follows
                    if d.get('cast_id') == entry['id']:
                        d['speaker'] = entry['name']
                for u in units.values():
                    if u.get('cast_id') == entry['id']:
                        u['speaker'] = entry['name']
                events.append({'rename': entry['id'], 'name': entry['name']})
            if body.alias:
                entry = C.add_alias(cast, body.alias.cast_id, body.alias.alias, 'person')
                events.append({'alias': body.alias.alias, 'of': entry['id'] if entry else None})
            if body.split:
                entry = C.split(cast, body.split)
                events.append({'split': body.split, 'entry': entry['id'] if entry else None})
            if body.unsplit:
                holder = C.unsplit(cast, body.unsplit)
                events.append({'unsplit': body.unsplit, 'back_to': holder['id'] if holder else None})
            for d in body.decisions:
                u = units.get(d.unit_id)
                if u is None or not u['text'].strip():
                    continue
                if d.clear:
                    decisions.pop(d.unit_id, None); continue
                speaker = (d.speaker if d.speaker is not None else decisions.get(d.unit_id, {}).get('speaker', u['speaker'])).strip()
                kind = d.kind or decisions.get(d.unit_id, {}).get('kind') or u['kind']
                if kind == 'dialogue' and speaker.upper() not in ('', 'UNKNOWN'):
                    entry, _ = C.ensure(cast, speaker, 'person', introduced={'draft_id': draft_id, 'unit_id': d.unit_id})
                    cast_id = entry['id']; speaker = entry['name']
                else:
                    cast_id = None
                previous = decisions.get(d.unit_id, {})
                decisions[d.unit_id] = {'speaker': speaker if kind == 'dialogue' else 'NARRATOR', 'kind': kind, 'cast_id': cast_id,
                                        'edited': bool(d.edited) or bool(previous.get('edited')), 'confirmed': bool(d.confirmed),
                                        'source': 'person' if d.edited else (u.get('source') or ('rule' if u.get('tier') else 'model')),
                                        'text_fingerprint': hashlib.sha256(u['text'].encode()).hexdigest()[:16], 'at': now}
            record['revision'] = current + 1
            record.setdefault('events', []).extend([{**e, 'revision': record['revision'], 'at': now} for e in events])
            save_cast(record, cast, book_record)
            write_draft(record)
            return {'revision': record['revision'], 'decisions': decisions, 'cast': cast,
                    'units': apply_decisions(record['units'], decisions), 'events': events}

    @app.post('/api/attribution/suggest')
    def resuggest(body: SuggestRequest):
        """Learn as the reviewer works: the lines already settled on the page —
        by the model with certainty or by the person — teach the habits, together
        with the book's confirmed chapters, and every unsettled line is scored
        again. Returns a suggestion per unsettled line; the page decides how to show it."""
        from . import habits
        taught = []
        revision = None
        if body.draft_id:
            # The draft's saved decisions are the final word on what is fixed —
            # protection in the backend, not only in the page's own state.
            with store.lock:
                try:
                    record = read_draft(body.draft_id)
                except ValueError:
                    record = {}
            revision = record.get('revision')
            saved = record.get('decisions', {})
            for u in body.units:
                d = saved.get(u.id)
                if d and (d.get('edited') or d.get('confirmed')):
                    u.fixed = True; u.speaker = d['speaker'] if d.get('kind', 'dialogue') == 'dialogue' else ''; u.source = 'person' if d.get('edited') else (d.get('source') or 'model')
                    if d.get('kind') == 'narration':
                        u.kind = 'narration'
        if body.book_id:
            with store.lock:
                taught += [(u['text'], l['speaker']) for p in book_projects(books.get(body.book_id)) for u, l in confirmed_dialogue(p)]
        # What teaches: lines the person settled and lines the narration tags
        # (the text's own evidence). A line the model was merely sure of does
        # not (Astra 2026-09-15): an unconfirmed answer must not become the
        # reference the other lines are judged by. Pages that do not say the
        # source (older builds) fall back to `fixed`.
        taught += [(u.text, u.speaker.strip()) for u in body.units if u.kind == 'dialogue' and u.speaker.strip().upper() not in ('', 'UNKNOWN', 'NARRATOR')
                   and (u.source in ('person', 'tag') if u.source else u.fixed)]
        profile = habits.profiles(taught)
        # Habits can only choose among the people they were taught. A page with a
        # stand-in on it (众人, 某人) has speakers nobody can profile, so on such a
        # page habits hint and never fill: Kong Yiji, 2026-09-16 — five of the
        # drinker's lines were filled with 孔乙己, the nearest of the three
        # profiled people, and the reviewer, trusting yellow, let them stand.
        # The page's own turn-taking guess, when it has one, is kept as the fill.
        unprofiled = any(u.speaker.strip().startswith(tuple(habits.STAND_INS.values())) for u in body.units if u.kind == 'dialogue')
        out = {}
        for u in body.units:
            if u.kind != 'dialogue' or u.fixed or not u.text.strip():
                continue
            best, margin = habits.suggest(u.text, profile) if profile else (None, 0.0)
            if u.turn.strip():
                out[u.id] = {'speaker': u.turn.strip(), 'margin': 0.0, 'fill': True, 'basis': '按一来一往填的', **({'hint': best} if best and best != u.turn.strip() else {})}
            elif best:
                out[u.id] = {'speaker': best, 'margin': round(margin, 3), 'fill': margin >= habits.MARGIN and not unprofiled, 'basis': '按已确认的说话习惯，像是'}
        return {'suggestions': out, 'taught': len(taught), 'revision': revision}

    @app.post('/api/attribution/confirm')
    def confirm_roles(body: RoleConfirmRequest):
        from . import cast as C
        with store.lock:
            record = read_draft(body.draft_id)
            if body.expected_revision is not None and body.expected_revision != record.get('revision', 1):
                raise HTTPException(status_code=409, detail={'message': '这份草稿在别处改过了，请刷新后再确认。', 'revision': record.get('revision', 1)})
            cast, book_record = draft_cast(record)
        labels = [label.model_dump() for label in body.labels]
        # The reviewer's saved decisions are the final word (Astra 2026-09-16):
        # a label the page sends for a decided unit yields to the decision.
        decisions = record.get('decisions', {})
        units_by_id = {u['id']: u for u in record.get('units', [])}
        for label in labels:
            d = decisions.get(label['id'])
            u = units_by_id.get(label['id'], {})
            if d:
                label['kind'] = d.get('kind', label['kind'])
                label['speaker'] = d['speaker'] if label['kind'] == 'dialogue' else 'NARRATOR'
                label['source'] = 'person' if d.get('edited') else d.get('source', 'model'); label['edited'] = bool(d.get('edited')); label['confirmed'] = True
            else:
                label['source'] = u.get('source') or ('rule' if u.get('tier') else 'model'); label['edited'] = False; label['confirmed'] = True
        # Headings and other lines the import keeps but does not read: cut as
        # their own segments (a lock at each end keeps the merger off them) and
        # kept silent from the start (Astra 2026-09-16: keep the text, do not
        # read it, show it plainly).
        spans = []
        if body.silent:
            lines = record['source_script'].split('\n'); starts, pos = [], 0
            for line in lines:
                starts.append(pos); pos += len(line) + 1
            spans = [(starts[n], starts[n] + len(lines[n]) + 1) for n in body.silent if 0 <= n < len(lines) and lines[n].strip()]
        locks = {x for a, b in spans for x in (a, b) if 0 < x < len(record['source_script'])}
        if record.get('settled_by') == 'manuscript':
            # The author wrote one utterance per line: every line stays its own
            # segment, none merged with the next.
            pos = 0
            for line in record['source_script'].split('\n'):
                pos += len(line) + 1
                if 0 < pos < len(record['source_script']):
                    locks.add(pos)
        segments = project_segments(record['source_script'], labels, record['language'], locks=sorted(locks), cut=record.get('cut'))
        for seg in segments:
            if any(a <= seg['source_start'] and seg['source_end'] <= b for a, b in spans):
                seg['read_aloud'] = False
        with store.lock:
            # Segment construction happens outside the lock. A newer review or
            # shared cast must never be overwritten by that earlier snapshot.
            latest_record = read_draft(body.draft_id)
            latest_cast, latest_book = draft_cast(latest_record)
            if latest_record.get('revision', 1) != record.get('revision', 1) or latest_cast != cast:
                raise HTTPException(status_code=409, detail={'message': '确认期间草稿或人物表有更新，请刷新后再确认。', 'revision': latest_record.get('revision', 1)})
            book_record = latest_book
            for label in labels:
                if label['kind'] == 'dialogue' and label['speaker'].strip().upper() not in ('', 'UNKNOWN'):
                    entry, _ = C.ensure(cast, label['speaker'].strip(), 'person')
                    label['cast_id'] = entry['id']
            save_cast(record, cast, book_record)
            target_id = record.get('target_project_id')
            if target_id:
                project = store.read(target_id)
                if (project.get('settings_schema') != 1
                        or project.get('processing_state') != 'unprocessed'
                        or project.get('source_script') != record['source_script']
                        or (project.get('attribution_batch') or {}).get('draft_id') != body.draft_id):
                    raise RuntimeError('目标子工程或原稿已经改变，请从该章节重新继续。')
                project['name'] = body.name.strip() or project['name']
                project['segments'] = segments
                project['processing_state'] = 'processed'
                project['job'] = {'status': 'idle'}
                if record.get('cut'):
                    project['cut'] = record['cut']
                current_view = project_service.view(project)
                local_voices = project.setdefault('voices', {})
                presets = ['Vivian','Uncle_Fu','Serena','Dylan'] if record['language'] == 'zh' else ['Ryan','Aiden']
                used = set(current_view.get('voices', {}).values())
                for speaker in dict.fromkeys(segment['speaker'] for segment in segments):
                    if speaker not in current_view.get('voices', {}):
                        voice = next((candidate for candidate in presets if candidate not in used),
                                     presets[len(used) % len(presets)])
                        local_voices[speaker] = voice
                        used.add(voice)
                voice_names = set(project_service.view(project).get('voices', {}))
            else:
                project = store.create(body.name, record['source_script'], record['language'], segments=segments,
                                       preset_model=default_preset(), clone_model=default_clone())
                if record.get('cut'):
                    project['cut'] = record['cut']          # the lines were cut by the manuscript's colours; a rewrite cuts the same way
                voice_names = set(project['voices'])
            project['cast_ids'] = {e['name']: e['id'] for e in cast if e['name'] in voice_names}
            # A colour the author gave a character in the manuscript is the
            # character's colour in the project too (本人 2026-09-16).
            for e in cast:
                if e['name'] in voice_names and e.get('colours') and e['colours'][0] != 'none':
                    project.setdefault('colors', {})[e['name']] = e['colours'][0]
            narration_colour = record.get('narration_colour') or (book_record or {}).get('narration_colour')
            if narration_colour:
                narrator = '旁白' if record['language'] == 'zh' else 'Narrator'
                if narrator in voice_names:
                    project.setdefault('colors', {})[narrator] = narration_colour
            project['attribution'] = {'draft_id':body.draft_id,'model_sha256':record.get('model_sha256'),'model_id':record.get('model_id'),
                'model_labels':record['labels'],'confirmed_labels':labels,'human_confirmed':True,'decisions':decisions,'draft_revision':record.get('revision', 1),
                'cast':[{k: e[k] for k in ('id', 'name', 'aliases', 'colours', 'sex', 'source')} for e in cast],
                # The automation measurement the author asked for (2026-09-15): what
                # the page showed, what the person changed, how long it took.
                'review':{k: body.review.get(k) for k in ('seconds','dialogue','orange','yellow','changed','named_changed','yellow_changed','orange_filled')} if body.review else None}
            inherited = None
            if not target_id and body.book_id and body.chapter_index:
                # A chapter of a book: remember which, and start from the settings
                # of the chapter before it — the same characters, the same voices,
                # the same lexicon — so a book is configured once, not per chapter.
                book = books.get(body.book_id)
                speakers = {l['speaker'] for l in labels if l['kind'] == 'dialogue'}
                if body.aliases or (book.get('aliases') and speakers):
                    _, split = books.remember_aliases(book['id'], body.aliases, speakers)
                    if split:
                        project['attribution']['aliases_split'] = split
                project['book'] = {'id': book['id'], 'title': book['title'], 'index': body.chapter_index, 'chapters': len(book['chapters'])}
                siblings = [p for p in book_projects(book) if p['id'] != project['id'] and not p.get('archived')]
                earlier = [p for p in siblings if (p.get('book') or {}).get('index', 0) < body.chapter_index]
                source = max(earlier, key=lambda p: p['book']['index']) if earlier else (siblings[-1] if siblings else None)
                if source:
                    carried = inherit_settings(project, source, store.directory(source['id']), store.directory(project['id']))
                    inherited = {'from': source['name'], **carried}
            if target_id:
                project['revision'] += 1
            store.write(project)
            record['confirmed_project_id'] = project['id']; write_draft(record)
            public = (project_service.public_project(project, engine, checker)
                      if project.get('settings_schema') == 1 else store.public(project, engine, checker))
            return {**public, 'inherited': inherited}

    @app.get('/api/projects')
    def projects(include_archived: bool = False):
        with store.lock:
            # Most recently touched first: a list ordered by folder name is a
            # list ordered by nothing anyone can see.
            return [{'id':p['id'],'name':p['name'],'language':p['language'],
                     'archived':p.get('archived',False),'updated_at':path.stat().st_mtime,
                     'processing_state': p.get('processing_state'), 'book': p.get('book')}
                    for path in sorted(store.root.glob('*/project.json'))
                    for p in [json.loads(path.read_text())] if include_archived or not p.get('archived',False)]

    @app.post('/api/projects')
    def import_project(body: ImportRequest):
        with store.lock:
            return store.public(store.create(body.name, body.script, body.language, preset_model=default_preset(), clone_model=default_clone()), engine, checker)

    @app.get('/api/projects/{project_id}')
    def get_project(project_id: str):
        with store.lock:
            project = store.read(project_id)
            if project.get('settings_schema') == 1:
                return project_service.public_project(project, engine, checker)
            return store.public(project, engine, checker)

    @app.get('/api/projects/{project_id}/settings')
    def get_project_settings(project_id: str):
        with store.lock:
            project = store.read(project_id)
            if project.get('settings_schema') != 1:
                raise ValueError('旧工程继续使用原设置接口，不自动迁移。')
            return project_service.setting_payload(project)

    @app.patch('/api/projects/{project_id}/settings')
    def patch_project_settings(project_id: str, body: SettingPatchRequest):
        project = project_service.update_project_settings(
            project_id, body.revision, body.values, body.inherit)
        return project_service.setting_payload(project)

    @app.patch('/api/projects/{project_id}')
    def edit_project(project_id: str, body: EditRequest):
        has_pause = 'pause_after' in body.model_fields_set
        if has_pause and not body.segment_id:
            raise ValueError('请先选择要设置停顿的句子。')
        def apply(p):
            effective = work_project(p)
            effective_voices = effective['voices']
            if body.name is not None:
                if not body.name.strip():raise ValueError('工程名称不能为空。')
                p['name']=body.name.strip()
            if body.archived is not None:p['archived']=body.archived
            if body.speech_rate is not None:
                if body.speech_rate!=1.0 and not ffmpeg_path():raise ValueError('语速调节需要本机 FFmpeg。')
                p['speech_rate']=body.speech_rate
            if body.pause_ms is not None:
                p['pause_ms'] = body.pause_ms
            if body.preset_model is not None:
                if body.preset_model == '1.7B' and not getattr(engine, 'large_identity', None):
                    raise ValueError('1.7B 预设模型未安装。')
                # Feeds the fingerprint: every preset-voice line changes identity
                # and needs regenerating; cloned-voice lines do not.
                p['preset_model'] = body.preset_model
            if body.lexicon is not None:
                # Written form -> read-as form, project-wide. Empty entries and
                # self-maps are dropped; feeding the fingerprint means only the
                # lines an entry touches lose their audio.
                clean = {k.strip(): v.strip() for k, v in body.lexicon.items() if k.strip() and v.strip() and k.strip() != v.strip()}
                if len(clean) > 200 or any(len(k) > 40 or len(v) > 40 for k, v in clean.items()):
                    raise ValueError('发音词典最多 200 条，每条不超过 40 字。')
                for read in clean.values():
                    readings.resolve(read)            # a bad 字[拼音] is refused here, with its name
                p['lexicon'] = clean
            if body.segment_id:
                s = next((s for s in p['segments'] if s['id']==body.segment_id), None)
                if s is None:
                    raise ValueError('Unknown segment')
                if has_pause:
                    # D48: null means inheritance; a gap never changes synthesis identity.
                    s['pause_after'] = body.pause_after
                if body.read_aloud is not None:
                    # Kept in the script, left out of the recording. Audio and
                    # checks stay attached for when the line is switched back on.
                    s['read_aloud'] = body.read_aloud
                limit = 60 if p['language'] == 'zh' else 240
                for field in ('text','spoken_as'):
                    value = getattr(body, field)
                    if value is not None:
                        # One message per rule: a vague error sends people hunting.
                        if field == 'text' and not value.strip():
                            raise ValueError('这一句不能为空。要去掉它，请用「删除这一句」。')
                        # A line break inside a line is allowed: the slicer keeps
                        # paragraph breaks, the voice reads through them, the
                        # subtitles break there. A split is the way to get a pause.
                        readings.resolve(value)      # a bad 字[拼音] in either field is refused by name
                        if len(value) > limit:
                            raise ValueError(f'一句最多 {limit} 个字符，当前 {len(value)} 个。请在「原稿编辑」里拆成两句。')
                        if field == 'text' and value != s['text']:
                            # Keep the script and the lines telling the same story:
                            # otherwise the script editor would show stale text and
                            # applying it would silently undo this edit.
                            _splice_source(p, s, value)
                        s[field] = value
                if body.speaker is not None:
                    if body.speaker not in effective_voices:
                        # A character who first appears after the project was made
                        # (本人 2026-09-15): named on a line, born with a preset voice
                        # not yet used by anyone, to be changed under 角色音色.
                        name = body.speaker.strip()
                        if not name or len(name) > 80 or any(c in name for c in '：:\n'):
                            raise ValueError('角色名需为 1–80 个字符，且不含冒号。')
                        presets = ['Vivian', 'Uncle_Fu', 'Serena', 'Dylan', 'Eric'] if p['language'] == 'zh' else ['Ryan', 'Aiden']
                        used = set(effective_voices.values())
                        voices = p.setdefault('voices', {})
                        voices[name] = next((v for v in presets if v not in used), presets[len(effective_voices) % len(presets)])
                        body.speaker = name
                    s['speaker'] = body.speaker
                if any(getattr(body, field) is not None for field in ('text', 'spoken_as', 'speaker')):
                    s['error'] = None
            if body.speaker_muted is not None:
                if body.speaker not in effective_voices:
                    raise ValueError('Select an existing speaker')
                if 'muted_speakers' not in p:
                    p['muted_speakers'] = list(effective.get('muted_speakers', []))
                muted = p['muted_speakers']
                if body.speaker_muted:
                    if body.speaker not in muted:
                        muted.append(body.speaker)
                else:
                    p['muted_speakers'] = [name for name in muted if name != body.speaker]
            if body.voice is not None and body.segment_id and body.speaker is None:
                # One line read in a voice of its own — 'auto' returns it to its character's.
                s = next((x for x in p['segments'] if x['id'] == body.segment_id), None)
                if s is None:
                    raise ValueError('Unknown segment')
                if body.voice == 'auto':
                    s.pop('voice', None)
                elif body.voice in VOICES or (is_custom(body.voice) and library.label(body.voice)):
                    s['voice'] = body.voice
                else:
                    raise ValueError('Unknown voice')
                s['error'] = None
            elif body.voice is not None:
                if (body.voice not in VOICES and not (is_custom(body.voice) and library.label(body.voice))) or body.speaker not in effective_voices:
                    raise ValueError('Unknown voice or speaker')
                if effective_voices[body.speaker] != body.voice:
                    p.get('voice_profiles',{}).pop(body.speaker,None)
                p.setdefault('voices', {})[body.speaker] = body.voice
                for s in p['segments']:
                    if s['speaker'] == body.speaker:
                        s['error'] = None
            if body.color_scope is not None:
                p['color_scope'] = body.color_scope
            if body.clone_model is not None:
                if body.clone_model == '1.7B' and not getattr(engine, 'large_reference_ready', False):
                    raise ValueError('1.7B 固定声线模型未安装。')
                p['clone_model'] = body.clone_model
                changed_view = work_project(p)
                for s in p['segments']:
                    work_segment = next(item for item in changed_view['segments'] if item['id'] == s['id'])
                    if s['speaker'] in (changed_view.get('voice_profiles') or {}) or is_custom(voice_of(changed_view, work_segment)):
                        s['error'] = None
            if body.ellipsis_pause_ms is not None:
                p['ellipsis_pause_ms'] = body.ellipsis_pause_ms
                changed_view = work_project(p)
                for s in p['segments']:
                    work_segment = next(item for item in changed_view['segments'] if item['id'] == s['id'])
                    if len(split_at_pauses(spoken_text(changed_view, work_segment))) > 1:
                        s['error'] = None
            if body.sex is not None:
                # Who a character is, apart from which voice reads them (Astra
                # 2026-09-15: the voice chosen must not decide whose line it
                # is). Set here, it is what the speaker rules go by; 'auto'
                # returns to what the voice suggests.
                if body.speaker not in effective_voices:
                    raise ValueError('Select an existing speaker')
                sexes = p.setdefault('sexes', {})
                if body.sex == 'auto':
                    sexes.pop(body.speaker, None)
                else:
                    sexes[body.speaker] = body.sex
            if body.color is not None:
                # A character's colour in the script list: a screen preference,
                # kept with the project, nothing to do with the audio. 'auto'
                # returns the character to the palette's own choice.
                if body.speaker not in effective_voices:
                    raise ValueError('Select an existing speaker')
                colors = p.setdefault('colors', {})
                if body.color == 'auto':
                    colors.pop(body.speaker, None)
                else:
                    colors[body.speaker] = body.color.lower()
        updated = store.edit(project_id, body.revision, apply)
        return (project_service.public_project(updated, engine, checker)
                if updated.get('settings_schema') == 1
                else store.public(updated, engine, checker))

    class SplitRequest(RevisionRequest):
        at: int = Field(ge=1)

    @app.post('/api/projects/{project_id}/segments/{segment_id}/split')
    def split(project_id: str, segment_id: str, body: SplitRequest):
        """Cut one line in two where the reader put the cursor. Undoable."""
        from .core import split_segment
        with store.lock:
            return store.public(store.edit(project_id, body.revision,
                                           lambda p: split_segment(p, segment_id, body.at)), engine, checker)

    class MergeRequest(RevisionRequest):
        direction: Literal['next', 'previous'] = 'next'

    @app.post('/api/projects/{project_id}/segments/{segment_id}/merge')
    def merge(project_id: str, segment_id: str, body: MergeRequest):
        """Join a line with the one after (or before) it. Undoable."""
        from .core import merge_segments
        with store.lock:
            return store.public(store.edit(project_id, body.revision,
                lambda p: merge_segments(p, segment_id, body.direction, p['language'])), engine, checker)

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
                p['muted_speakers'] = [name for name in p.get('muted_speakers', []) if name != speaker]
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
                      else carry_labels(project['segments'], body.source_script, language, project.get('cut')))
            # Boundaries cut by hand survive a reslice; the slicer cuts there and
            # never merges across them.
            locks = carry_locks(project['segments'], body.source_script)
            if body.labels is None:
                unresolved = [{**unit, **{k: label[k] for k in ('kind', 'speaker')}}
                              for unit, label in zip(source_units(body.source_script, project.get('cut')), labels)
                              if label['kind'] == 'dialogue'
                              and label['speaker'].strip().upper() in ('', 'UNKNOWN')]
                # Slicing rejects UNKNOWN, so count with a placeholder that never persists.
                probe = [{**l, 'speaker': ('待指定' if l['speaker'].strip().upper() in ('', 'UNKNOWN')
                                           else l['speaker'])} for l in labels]
                sliced = project_segments(body.source_script, probe, language, locks, project.get('cut'))
                _, stats = carry_state(project['segments'], [dict(s) for s in sliced])
                return {'preview': True, 'labels': labels, 'unresolved': unresolved,
                        'report': report, 'segments': len(sliced), **stats}
            segments = project_segments(body.source_script, labels, language, locks, project.get('cut'))
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

    @app.post('/api/projects/{project_id}/characters')
    def add_character(project_id: str, body: CharacterRequest):
        """A character who first appears after the project was made: born with an
        unused preset voice, to be changed under 角色音色 and assigned on lines.
        Undoable. Nothing else about the project changes."""
        name = body.name.strip()
        if not name or any(c in name for c in '：:\n'):
            raise ValueError('角色名需为 1–80 个字符，且不含冒号。')
        def apply(p):
            if name in p['voices']:
                raise ValueError('已经有这个角色了。')
            presets = ['Vivian', 'Uncle_Fu', 'Serena', 'Dylan', 'Eric'] if p['language'] == 'zh' else ['Ryan', 'Aiden']
            used = set(p['voices'].values())
            p['voices'][name] = next((v for v in presets if v not in used), presets[len(p['voices']) % len(presets)])
        return store.public(store.edit(project_id, body.revision, apply), engine, checker)

    @app.delete('/api/projects/{project_id}/characters/{name}')
    def remove_character(project_id: str, name: str, revision: int):
        """Only a character with no lines can go; its colour and profile go with it."""
        def apply(p):
            if name not in p['voices']:
                raise ValueError('没有这个角色。')
            if any(s['speaker'] == name for s in p['segments']):
                raise ValueError('这个角色还有句子，先把句子改给别人。')
            p['voices'].pop(name); (p.get('colors') or {}).pop(name, None); (p.get('sexes') or {}).pop(name, None); (p.get('voice_profiles') or {}).pop(name, None); (p.get('crowds') or {}).pop(name, None)
            p['muted_speakers'] = [speaker for speaker in p.get('muted_speakers', []) if speaker != name]
        return store.public(store.edit(project_id, revision, apply), engine, checker)

    @app.post('/api/projects/{project_id}/crowd')
    def crowd(project_id: str, body: CrowdRequest):
        """A crowd — 众人, 路人 — is one character in the script and many voices in
        the recording: every line of the speaker draws a voice from the pool, never
        the same voice on two lines in a row. Seeded, so the draw is reproducible;
        change the seed for another draw. Undoable like any edit."""
        pool = list(dict.fromkeys(body.pool))
        for v in pool:
            if v not in VOICES and not (is_custom(v) and library.label(v)):
                raise ValueError(f'没有这个音色：{v}')
        def apply(p):
            if body.speaker not in p['voices']:
                raise ValueError('Select an existing speaker')
            draw = random.Random(body.seed); last = None; n = 0
            for s in p['segments']:
                if s['speaker'] != body.speaker:
                    continue
                choices = [v for v in pool if v != last] or pool
                s['voice'] = draw.choice(choices); s['error'] = None; last = s['voice']; n += 1
            p.setdefault('crowds', {})[body.speaker] = {'pool': pool, 'seed': body.seed}
            if not n:
                raise ValueError('这个角色没有句子。')
        return store.public(store.edit(project_id, body.revision, apply), engine, checker)

    @app.post('/api/projects/{project_id}/inherit')
    def inherit(project_id: str, body: InheritRequest):
        """Carry another project's — or a template's — voices, fixed references (projects only),
        colours, lexicon, model, pause and speed into this one."""
        if bool(body.source_id) == bool(body.template_id):
            raise ValueError('请选择一个工程或一个模板。')
        if body.source_id == project_id:
            raise ValueError('请选择另一个工程。')
        if body.source_id:
            with store.lock:
                source = store.read(body.source_id)
            source_dir = store.directory(source['id'])
        else:
            source = templates.get(body.template_id); source_dir = None
        carried = {}
        def apply(p):
            carried.update(inherit_settings(p, source, source_dir, store.directory(p['id'])))
        return {**store.public(store.edit(project_id, body.revision, apply), engine, checker), 'inherited': {'from': source['name'], **carried}}

    @app.get('/api/templates')
    def list_templates():
        return templates.list()

    @app.post('/api/templates')
    def create_template(body: TemplateRequest):
        with store.lock:
            return templates.create(body.name, store.read(body.project_id))

    @app.delete('/api/templates/{template_id}')
    def delete_template(template_id: str):
        templates.delete(template_id)
        return {'deleted': template_id}

    @app.delete('/api/projects/{project_id}')
    def delete_project(project_id: str, revision: int):
        store.delete(project_id, revision)
        return {'deleted': project_id}

    @app.post('/api/projects/{project_id}/{action}')
    def history(project_id: str, action: Literal['undo','redo'], body: RevisionRequest):
        return store.public(store.edit(project_id, body.revision, lambda p:None, action), engine, checker)

    @app.post('/api/projects/{project_id}/voice/{action}')
    def fixed_voice(project_id: str, action: Literal['fix','release'], body: FixedVoiceRequest):
        def apply(p):
            segment=next((s for s in p['segments'] if s['id']==body.segment_id),None)
            if segment is None:
                raise ValueError('Unknown segment')
            effective = work_project(p)
            work_segment = next(s for s in effective['segments'] if s['id'] == segment['id'])
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
                or audio.get('engine')!=engine.identity
                or segment['speaker'] in effective.get('voice_profiles', {})):
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
            profiles[segment['speaker']]={'sha256':digest,'text':spoken_text(effective,work_segment),
                'voice':effective['voices'][segment['speaker']],'source_fingerprint':audio['fingerprint'],
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
                    work = work_project(p)
                    work_segment = next(item for item in work['segments'] if item['id'] == sid)
                    digest = fingerprint(work, work_segment, engine, library)
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
                        profile=work.get('voice_profiles',{}).get(work_segment['speaker'])
                        if profile:
                            if not profile.get('synthetic_audio') or not profile.get('consent_confirmed'):
                                raise ValueError('固定声线缺少合成来源或授权记录。')
                            digest_ref=profile['sha256']
                            if len(digest_ref)!=64 or any(c not in '0123456789abcdef' for c in digest_ref):
                                raise ValueError('固定声线标识无效。')
                            def read(text): return engine.synthesize_reference(text,work['language'],
                                store.directory(project_id)/'references'/(digest_ref+'.wav'),profile['text'],
                                260909+work_segment.get('take',0),consent_confirmed=True,expected_sha256=digest_ref,**clone_size(work))
                        elif is_custom(voice_of(work, work_segment)):
                            entry = library.get(custom_id(voice_of(work, work_segment)))
                            def read(text): return engine.synthesize_reference(text,work['language'],
                                library.audio_path(entry['id']),entry['reference_text'],
                                260909+work_segment.get('take',0),consent_confirmed=True,expected_sha256=entry['sha256'],**clone_size(work))
                        else:
                            def read(text): return engine.synthesize(text,
                                voice_of(work, work_segment), work['language'], 260909+work_segment.get('take',0),
                                **({'size': work.get('preset_model','0.6B')} if hasattr(engine,'identity_for') else {}))
                        pcm, rate, metrics = read_with_pauses(work, work_segment, read)
                        pcm, meta = process_audio(pcm, rate)
                        # A run-away take: the engine read the line and kept going -- a
                        # video outro, or a 26-character line rendered as 164 seconds.
                        # Seen four times today across both model sizes. One more
                        # attempt with the next seed, before anyone hears it; the
                        # duration marker still reports if the second is bad too.
                        spoken_seconds = (meta['speech_end_sample'] - meta['speech_start_sample']) / rate - metrics.get('pause_seconds', 0)
                        runaway = duration_marker(spoken_text(work,work_segment), spoken_seconds, work['language'])
                        if runaway and not metrics.get('auto_retake') and sid not in retake_ids and not work.get('voice_profiles',{}).get(work_segment['speaker']) and not is_custom(voice_of(work, work_segment)):
                            logging.warning('Run-away take on %s (%.1fs for %d chars); retrying with the next seed', sid, spoken_seconds, len(spoken_text(work,work_segment)))
                            with store.lock:
                                p = store.read(project_id)
                                s = next(x for x in p['segments'] if x['id']==sid)
                                s['take'] = s.get('take',0)+1
                                work = work_project(p)
                                work_segment = next(item for item in work['segments'] if item['id'] == sid)
                                digest = fingerprint(work, work_segment, engine, library)
                                path = folder/(digest+'.wav'); meta_path = folder/(digest+'.json')
                                store.write(p)
                            pcm, rate, metrics = engine.synthesize(spoken_text(work,work_segment),
                                voice_of(work, work_segment), work['language'], 260909+work_segment.get('take',0),
                                **({'size': work.get('preset_model','0.6B')} if hasattr(engine,'identity_for') else {}))
                            pcm, meta = process_audio(pcm, rate)
                            metrics = {**metrics, 'auto_retake': True, 'first_take_seconds': round(spoken_seconds, 2)}
                        meta.update({'fingerprint':digest, 'engine':(engine.reference_identity_for(work.get('clone_model','0.6B')) if hasattr(engine,'reference_identity_for') else getattr(engine,'reference_identity',engine.identity)) if (work.get('voice_profiles',{}).get(work_segment['speaker']) or is_custom(voice_of(work, work_segment))) else engine.identity, **metrics})
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
            work = work_project(p)
            selected = [s for s in work['segments'] if (s['id'] in retake_ids if body.marked_only else (not body.segment_id or s['id']==body.segment_id))]
            if body.segment_id and selected and not reads_aloud(selected[0], work):
                raise ValueError('这一句或它的角色已设为不朗读；要生成它，先恢复朗读。')
            selected = [s for s in selected if reads_aloud(s, work)]
            if not selected:
                raise ValueError('Unknown segment' if body.segment_id else '没有需要朗读的句子。')
            if body.force:
                for s in selected:
                    raw_segment = next(item for item in p['segments'] if item['id'] == s['id'])
                    raw_segment['take'] = raw_segment.get('take',0)+1
                    raw_segment['error'] = None
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
                    work=work_project(p)
                    segment=next(s for s in work['segments'] if s['id']==sid)
                    digest=fingerprint(work,segment,engine,library)
                    expected=spoken_text(work,segment)
                    source=store.directory(project_id)/'audio'/(digest+'.wav')
                    p['job']['current_segment']=sid;store.write(p)
                rhythm={'source_fingerprint':digest,'version':RHYTHM_VERSION,'expected_text':expected}
                try:
                    rhythm.update(analyze_file(source,language=work['language'],expected_text=expected))
                    stat=source.stat();rhythm.update(audio_sha256=file_sha(source),audio_stat=[stat.st_size,stat.st_mtime_ns])
                except Exception:
                    logging.exception('Rhythm analysis failed for %s',sid)
                    rhythm.update(error='本句节奏检查失败，可重试。')
                result={'source_fingerprint':digest,'expected_text':expected,'checker_id':checker.identity,
                        'checked_at':time.time(),'reviewed':False}
                try:
                    before=file_sha(source)
                    transcript=checker.transcribe(source,work['language'],store.directory(project_id)/'checks')
                    if file_sha(source)!=before:raise ValueError('检查过程中音频发生变化，请重试。')
                    stat=source.stat()
                    result.update(transcript)
                    result.update(compare_text(expected,transcript['recognized_text'],work['language'],names=list(work['voices'])))
                    result.update({'audio_sha256':before,'audio_stat':[stat.st_size,stat.st_mtime_ns]})
                except Exception as exc:
                    logging.exception('Local content check failed for segment %s',sid)
                    result.update({'status':'error','error':str(exc) if isinstance(exc,ValueError) else '本句检查失败，可重试。'})
                    if source.exists():
                        stat=source.stat();result['audio_stat']=[stat.st_size,stat.st_mtime_ns]
                with store.lock:
                    p=store.read(project_id)
                    work=work_project(p)
                    target=next(s for s in p['segments'] if s['id']==sid)
                    if result.get('timed_text') and not rhythm.get('error'):
                        try:rhythm.update(analyze_file(source,result['timed_text'],work['language'],expected))
                        except Exception:
                            logging.exception('Pace timing analysis failed for %s',sid)
                            rhythm['pace']={'status':'unavailable','reason':'语速起伏估计失败，请人工试听。'}
                    # The 3,200-point envelope is drawn from the audio on demand
                    # (the preview endpoint); kept in the project it was 25 KB per
                    # line, copied into every undo snapshot — 140 MB for a
                    # 93-line story, rewritten after every checked line.
                    rhythm.pop('waveform', None)
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
            effective = work_project(p)
            work_segment = next(s for s in effective['segments'] if s['id'] == segment['id'])
            segment['listening_issue']={'kind':body.kind,'note':body.note.strip(),'marked_at':time.time(),
                'source_fingerprint':digest,'audio_sha256':sha,'audio_stat':before,'speech_rate':effective.get('speech_rate',1.0),
                'expected_text':spoken_text(effective,work_segment),'tempo_edit':segment.get('tempo_edit')}
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
            effective = work_project(p)
            work_segment = next(x for x in effective['segments'] if x['id'] == segment_id)
            result=analyze_file(path,timed,effective['language'],spoken_text(effective,work_segment))
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
            effective = work_project(p)
            work_target = next(x for x in effective['segments'] if x['id'] == segment_id)
            prepare_segment(effective,work_target,store.directory(project_id))
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
            effective = work_project(p)
            work_target = next(x for x in effective['segments'] if x['id'] == segment_id)
            prepare_segment(effective,work_target,store.directory(project_id))
        return store.public(store.edit(project_id,body.revision,apply),engine,checker)

    @app.post('/api/projects/{project_id}/segments/{segment_id}/preview')
    def segment_preview(project_id: str, segment_id: str, body: RevisionRequest):
        with store.lock:
            p,s,path=ready_segment(project_id,segment_id)
            if p['revision']!=body.revision or p['job']['status']=='running':raise RuntimeError('工程已改变或正在处理，请稍后重试。')
            sha=file_sha(path)
            stat=path.stat()
            effective_edit=s.get('tempo_edit') if edit_status(s,[stat.st_size,stat.st_mtime_ns])=='current' else None
            effective = work_project(p)
            work_segment = next(x for x in effective['segments'] if x['id'] == segment_id)
            identity={'source_sha':sha,'fingerprint':s['audio']['fingerprint'],'tempo':effective_edit,'speed':effective.get('speech_rate',1.),'version':TEMPO_VERSION}
            key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
            directory=store.directory(project_id);folder=directory/'previews';folder.mkdir(exist_ok=True)
            audio_file=folder/(key+'.wav');meta_file=folder/(key+'.json')
            if not audio_file.is_file() or not meta_file.is_file():
                pcm,rate,_,mapping=prepare_segment(effective,work_segment,directory)
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

    def existing_export_links(project_id: str, p: dict):
        """Return only a complete export for the project's current revision.

        Export validity is intentionally revision-based, not content-hash based:
        any edit/undo/redo/render creates a new revision, so even if a person later
        changes the text back to identical content, the older export stays stale.
        """
        revision = p['revision']
        out = store.directory(project_id)/'exports'/str(revision)
        required = ['full.wav','subtitles.srt','timeline.json','content-check.json','delivery.zip']
        if not all((out/name).is_file() for name in required):
            return {}
        try:
            if json.loads((out/'timeline.json').read_text()).get('project_revision') != revision:
                return {}
            if json.loads((out/'content-check.json').read_text()).get('project_revision') != revision:
                return {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        optional = ['full.mp3','timeline-24fps.xml','timeline-25fps.xml','timeline-30fps.xml',
                    'timeline-50fps.xml','timeline-60fps.xml','timeline-README.txt']
        names = required[:]
        if (out/'full.mp3').is_file():
            names.insert(1, 'full.mp3')
        names += [name for name in optional[1:] if (out/name).is_file()]
        return {name:f'/api/projects/{project_id}/export/{revision}/{name}' for name in names}

    @app.get('/api/projects/{project_id}/export/current')
    def current_export(project_id: str):
        with store.lock:
            p = store.read(project_id)
            return existing_export_links(project_id, p)

    @app.post('/api/projects/{project_id}/export/create')
    def export(project_id: str, body: RevisionRequest):
        with store.lock:
            p = store.read(project_id)
            if p['revision'] != body.revision or p['job']['status']=='running':
                raise RuntimeError('Finish generation and reload before exporting')
            effective = work_project(p)
            public = store.public(effective,engine,checker)['segments']
            if all(s['status']=='silent' for s in public):
                raise ValueError('所有句子都设为不朗读，没有可导出的内容。')
            waiting = sum(1 for s in public if s['status'] not in ('ready','silent'))
            if waiting:
                raise ValueError(f'还有 {waiting} 句没有生成声音，先生成再导出。')
            out = store.directory(project_id)/'exports'/str(p['revision'])
            timeline = export_audio(effective, store.directory(project_id), out, delivery=True)
            timeline['project_revision'] = p['revision']
            check_report={'project_revision':p['revision'],'synthetic_audio':True,
                'speech_rate':effective.get('speech_rate',1.0),'checked_audio':'original_generated_audio',
                'notice':'自动文字检查针对原始合成声音；剪切可能移除发音，成品文字及字幕需要重新人工核对。',
                'segments':[{'id':s['id'],'text':s['text'],'check_status':s['check_status'],
                             'content_check':s.get('content_check'),'listening_status':s['listening_status'],
                             'rhythm_status':s['rhythm_status'],'rhythm_check':s.get('rhythm_check'),
                             'tempo_status':s['tempo_status'],'tempo_edit':s.get('tempo_edit'),
                             'edited_content_requires_review':s['tempo_status']=='current' and bool(s.get('tempo_edit',{}).get('cuts') or s.get('tempo_edit',{}).get('clips')),
                             'listening_issue':s.get('listening_issue')} for s in store.public(effective,engine,checker)['segments']]}
            (out/'content-check.json').write_text(json.dumps(check_report,ensure_ascii=False,indent=2))
            (out/'timeline.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=2))
            names = ['full.wav','subtitles.srt','timeline.json','content-check.json','delivery.zip']
            # An MP3 of the full audio beside the WAV when ffmpeg is on the machine
            # (本人 2026-09-18); the WAV stays the reference, the MP3 is for sharing.
            ffmpeg = ffmpeg_path()
            if ffmpeg:
                import subprocess
                done = subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-i', str(out/'full.wav'), '-codec:a', 'libmp3lame', '-q:a', '2', str(out/'full.mp3')],
                                      capture_output=True, text=True, timeout=600)
                if done.returncode == 0 and (out/'full.mp3').is_file():
                    names.insert(1, 'full.mp3')
                else:
                    logging.warning('MP3 export failed: %s', done.stderr.strip()[:200])
            return {name:f'/api/projects/{project_id}/export/{p["revision"]}/{name}' for name in names}

    @app.post('/api/projects/{project_id}/export/xml')
    def export_xml(project_id: str, body: ExportXmlRequest):
        from .fcp7 import FPS_CHOICES
        if body.video_fps not in FPS_CHOICES:
            raise ValueError('视频项目帧率请选择 24、25、30、50 或 60')
        with store.lock:
            links = export(project_id, body)
            out = store.directory(project_id)/'exports'/str(body.revision)
            manifest = json.loads((out/'delivery'/'timeline.json').read_text())
            payload = timeline_xml(manifest, body.video_fps)
            name = f'timeline-{body.video_fps}fps.xml'
            for filename, data in ((name, payload), ('timeline-README.txt', IMPORT_GUIDE.encode('utf-8'))):
                temp = out/(filename+'.tmp')
                temp.write_bytes(data)
                temp.replace(out/filename)
                links[filename] = f'/api/projects/{project_id}/export/{body.revision}/{filename}'
            return links

    @app.get('/api/projects/{project_id}/export/{revision}/{name}')
    def download(project_id: str, revision: int, name: Literal['full.wav','full.mp3','subtitles.srt','timeline.json','content-check.json','delivery.zip','timeline-24fps.xml','timeline-25fps.xml','timeline-30fps.xml','timeline-50fps.xml','timeline-60fps.xml','timeline-README.txt']):
        if revision < 0 or store.read(project_id)['revision'] != revision:
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
