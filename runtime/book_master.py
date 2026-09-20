"""Pure construction plans for Book/Project v1; not a live API or a migration.

The caller must commit an entire plan transactionally, including reference
assets. Existing Store.create/Books.create keep their current behavior until
Sol's service adapter and Opus's entry UI are connected together.
"""
from copy import deepcopy
import uuid
from .project_settings import initialize, application_defaults, reference_requirements, _settings

MASTER_SCHEMA = 1
# These are manuscript structure, NEVER inherited production settings.
STRUCTURE_KEYS = ('cut', 'hints', 'silent')


def _id():
    return uuid.uuid4().hex


def new_book(title, language, *, defaults=None):
    if language not in ('zh', 'en'):
        raise ValueError('当前工程支持中文或英文。')
    settings = application_defaults()
    settings.update(_settings(defaults or {}))
    return {'id': _id(), 'title': title.strip()[:120] or '未命名',
            'language': language, 'master_schema': MASTER_SCHEMA, 'revision': 0,
            'members': [], 'chapters': [], 'cast': [], 'aliases': {},
            'settings': settings, 'chapter_pause_ms': 0}


def plan_chapter(name, text, language, *, book=None, defaults=None,
                 copy_from=None, cut=None, hints=None, silent=None):
    """A pending chapter with source intact, not fabricated narration segments."""
    if not text.strip():
        raise ValueError('章节原文不能为空。')
    if language not in ('zh', 'en'):
        raise ValueError('当前工程支持中文或英文。')
    if book and book['language'] != language:
        raise ValueError('第一版主工程与子工程的语言必须一致。')
    if cut not in (None, 'lines'):
        raise ValueError('未知的切句方式。')
    if any(not isinstance(n, int) or isinstance(n, bool) or not 0 <= n < len(text.split('\n'))
           for n in (silent or [])):
        raise ValueError('不朗读行号超出本章范围。')
    for hint in hints or []:
        start, end = hint.get('start'), hint.get('end')
        if (not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(end, int) or isinstance(end, bool)
                or not 0 <= start < end <= len(text)):
            raise ValueError('作者标记范围超出本章原文。')
    raw = {'schema_version': 1, 'id': _id(), 'name': name.strip() or '未命名章节',
           'language': language, 'revision': 0, 'source_script': text,
           'segments': [], 'processing_state': 'unprocessed',
           'history': [], 'future': [], 'job': {'status': 'idle'},
           'synthetic_audio': True, 'cut': cut, 'hints': deepcopy(hints or []),
           'silent': list(silent or [])}
    project = initialize(raw, book=book, defaults=defaults, copy_from=copy_from)
    return {'project': project,
            'reference_copies': reference_requirements(copy_from) if copy_from is not None else []}


def plan_book(title, language, chapters, *, defaults=None):
    """Input chapters are already selected AUTHOR chapters; no token splitting.

    Return all raw records together, without exposing a half-created Book.
    chapters is a projection for compatibility; members is authoritative order.
    Text is stored once, in the Project. Existing old chapter endpoints must
    not be used for this schema without the service adapter.
    """
    if not chapters:
        raise ValueError('主工程至少需要一个章节。')
    book = new_book(title, language, defaults=defaults)
    projects = []
    for index, chapter in enumerate(chapters, 1):
        plan = plan_chapter(chapter.get('title') or f'第 {index} 章', chapter['text'], language,
                            book=book, **{k: chapter[k] for k in STRUCTURE_KEYS if k in chapter})
        project = plan['project']
        project['book'].update(index=index, chapters=len(chapters))
        book['members'].append(project['id'])
        book['chapters'].append({'index': index, 'title': project['name'],
                                 'project_id': project['id'], 'chars': len(chapter['text'])})
        projects.append(project)
    return {'book': book, 'projects': projects, 'reference_copies': []}


def structure_conflicts(left, right):
    """Preflight differences, NOT a merge or proof that equal markers can be reused.

    Even equal local hint offsets/line numbers must be rebased when concatenated.
    Opus's structural adapter owns rebasing, ID mapping and conflict resolution.
    """
    return {key: {'left': deepcopy(left.get(key)), 'right': deepcopy(right.get(key))}
            for key in ('language', *STRUCTURE_KEYS) if left.get(key) != right.get(key)}
