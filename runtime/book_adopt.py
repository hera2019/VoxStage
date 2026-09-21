"""Adopt a legacy book as a master book, in place (本人 2026-09-21: 把《阿Q正传》
收进主工程). The old Book record keeps its id — so the chapter projects'
`book.id` links stay true — and gains the master shape: `members` in chapter
order, one project per chapter. A chapter that already has an exact project
keeps it: the project is marked processed, its effective settings frozen as
its own (it was made before inheritance existed), and it joins the book. A
chapter without one becomes a new unprocessed project from the book's own
chapter text, inheriting the book's defaults. The book's defaults are taken
from the first processed chapter, so the unprocessed ones read with the same
voices. Every file touched is backed up first; the whole change is written
through a staging area and applied last, or not at all. Claude Hera."""
import json
import os
import shutil
import tempfile
import time
from copy import deepcopy
from pathlib import Path

from .book_master import plan_chapter, STRUCTURE_KEYS
from .project_settings import SETTING_KEYS, VIEW_KEY, effective, application_defaults

BOOK_LEVEL_KEYS = ('preset_model', 'clone_model', 'pause_ms', 'speech_rate', 'ellipsis_pause_ms', 'color_scope',
                   'lexicon', 'muted_speakers', 'voices', 'colors', 'sexes')   # not voice_profiles (local reference files), not crowds


def adopt_plan(book, projects, *, defaults=None):
    """The master record and the project records the adoption would write.
    `projects` are the store's records that link to this book by id. Pure."""
    if book.get('master_schema') == 1:
        raise ValueError('这本书已经是主工程。')
    chapters = sorted(book.get('chapters', []), key=lambda c: c['index'])
    if not chapters:
        raise ValueError('这本书没有章节记录。')
    exact = {}
    for p in projects:
        link = p.get('book') or {}
        if link.get('id') != book['id'] or p.get('archived'):
            continue
        index = link.get('index')
        chapter = next((c for c in chapters if c['index'] == index), None)
        if chapter is None or (chapter.get('text') or '') != p.get('source_script', ''):
            continue                                   # not an exact chapter: left alone, listed
        if index in exact:
            raise ValueError(f'第 {index} 章有两个工程都与原文一致：先在旧列表里归档一个。')
        exact[index] = p
    defaults = defaults or application_defaults()
    master = {**deepcopy(book), 'master_schema': 1, 'revision': 0, 'members': [], 'chapters': [],
              'settings': deepcopy(defaults), 'chapter_pause_ms': int(book.get('chapter_pause_ms', 0) or 0)}
    master.setdefault('cast', []); master.setdefault('aliases', {})
    first = next((exact[c['index']] for c in chapters if c['index'] in exact), None)
    if first:
        view = effective(first, None, defaults=defaults)
        for key in BOOK_LEVEL_KEYS:
            master['settings'][key] = deepcopy(view[key])
    updated, created = [], []
    for c in chapters:
        if c['index'] in exact:
            raw = deepcopy(exact[c['index']])
            raw.pop(VIEW_KEY, None)
            view = effective(raw, None, defaults=defaults)
            for key in SETTING_KEYS:
                raw[key] = deepcopy(view[key])            # what its audio was made with stays its own
            raw['settings_schema'] = 1
            raw['processing_state'] = 'processed' if raw.get('segments') else 'unprocessed'
            raw['book'] = {'id': book['id'], 'title': book['title'], 'index': c['index'], 'chapters': len(chapters)}
            for key in STRUCTURE_KEYS:
                if key in c and key not in raw:
                    raw[key] = deepcopy(c[key])
            updated.append(raw); pid = raw['id']
        else:
            plan = plan_chapter(c.get('title') or f'第 {c["index"]} 章', c['text'], book['language'], book=master, defaults=defaults,
                                **{k: c[k] for k in STRUCTURE_KEYS if k in c})
            raw = plan['project']
            raw['book'].update(index=c['index'], chapters=len(chapters))
            created.append(raw); pid = raw['id']
        master['members'].append(pid)
        master['chapters'].append({'index': c['index'], 'title': c.get('title') or raw['name'], 'project_id': pid, 'chars': len(c.get('text') or '')})
    return {'book': master, 'updated': updated, 'created': created,
            'left_alone': [p['id'] for p in projects if (p.get('book') or {}).get('id') == book['id'] and p['id'] not in {u['id'] for u in updated}]}


def adopt(store, books, book_id, *, defaults=None):
    """Back up, stage, apply. Returns the master book and what was written."""
    book = books.get(book_id)
    projects = [json.loads(p.read_text(encoding='utf-8')) for p in store.root.glob('*/project.json')]
    plan = adopt_plan(book, projects, defaults=defaults)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup = books.root / (book_id + '.snapshots') / f'adopt-{stamp}'
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(books.root / (book_id + '.json'), backup / 'book.json')
    for raw in plan['updated']:
        shutil.copy2(store.directory(raw['id']) / 'project.json', backup / f"project-{raw['id']}.json")
    (backup / 'meta.json').write_text(json.dumps({'kind': 'adopt_legacy_book', 'book_id': book_id, 'at': stamp,
                                                  'updated': [u['id'] for u in plan['updated']], 'created': [c['id'] for c in plan['created']]}, ensure_ascii=False, indent=1), encoding='utf-8')
    staging = Path(tempfile.mkdtemp(prefix='.adopt-', dir=store.root))
    moved = []
    try:
        for raw in plan['created']:
            folder = staging / raw['id']; folder.mkdir()
            (folder / 'project.json').write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
        for raw in plan['updated']:
            tmp = store.directory(raw['id']) / 'project.json.adopt'
            tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
        book_tmp = books.root / ('.' + book_id + '.json.adopt')
        book_tmp.write_text(json.dumps(plan['book'], ensure_ascii=False, indent=2), encoding='utf-8')
        for raw in plan['created']:
            target = store.directory(raw['id'])
            os.replace(staging / raw['id'], target); moved.append(target)
        for raw in plan['updated']:
            os.replace(store.directory(raw['id']) / 'project.json.adopt', store.directory(raw['id']) / 'project.json')
        os.replace(book_tmp, books.root / (book_id + '.json'))
    except BaseException:
        for target in moved:
            shutil.rmtree(target, ignore_errors=True)
        for raw in plan['updated']:
            (store.directory(raw['id']) / 'project.json.adopt').unlink(missing_ok=True)
        (books.root / ('.' + book_id + '.json.adopt')).unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {'book': plan['book'], 'updated': [u['id'] for u in plan['updated']], 'created': [c['id'] for c in plan['created']],
            'left_alone': plan['left_alone'], 'backup': str(backup)}

def recover_plan(book_id, projects, *, defaults=None):
    """A master book rebuilt from the projects that still point at a deleted
    book (the preview's orphan group): same id, so the links stay true;
    members in chapter order; every project a processed member with its
    effective settings frozen; the book's defaults from the first. Pure."""
    linked = sorted([p for p in projects if (p.get('book') or {}).get('id') == book_id and not p.get('archived')],
                    key=lambda p: (p.get('book') or {}).get('index', 0))
    if not linked:
        raise ValueError('没有找到指向这本书的工程。')
    if len({(p.get('book') or {}).get('index') for p in linked}) != len(linked):
        raise ValueError('有两个工程记着同一章号，先归档一个。')
    defaults = defaults or application_defaults()
    title = next(((p.get('book') or {}).get('title') for p in linked if (p.get('book') or {}).get('title')), '恢复的主工程')
    master = {'id': book_id, 'title': title, 'language': linked[0]['language'], 'master_schema': 1, 'revision': 0,
              'members': [], 'chapters': [], 'cast': [], 'aliases': {}, 'settings': deepcopy(defaults), 'chapter_pause_ms': 0,
              'recovered_from': 'orphan_projects'}
    view = effective(linked[0], None, defaults=defaults)
    for key in BOOK_LEVEL_KEYS:
        master['settings'][key] = deepcopy(view[key])
    updated = []
    for n, p in enumerate(linked, 1):
        raw = deepcopy(p); raw.pop(VIEW_KEY, None)
        view = effective(raw, None, defaults=defaults)
        for key in SETTING_KEYS:
            raw[key] = deepcopy(view[key])
        raw['settings_schema'] = 1
        raw['processing_state'] = 'processed' if raw.get('segments') else 'unprocessed'
        raw['book'] = {'id': book_id, 'title': title, 'index': n, 'chapters': len(linked)}
        updated.append(raw)
        master['members'].append(raw['id'])
        master['chapters'].append({'index': n, 'title': raw['name'], 'project_id': raw['id'], 'chars': len(raw.get('source_script') or '')})
    return {'book': master, 'updated': updated, 'created': [], 'left_alone': []}


def recover(store, books, book_id, *, defaults=None):
    """Back up the projects, write them and the rebuilt book through staging."""
    if (books.root / (book_id + '.json')).is_file():
        raise ValueError('这本书还在，不用恢复。')
    projects = [json.loads(p.read_text(encoding='utf-8')) for p in store.root.glob('*/project.json')]
    plan = recover_plan(book_id, projects, defaults=defaults)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup = books.root / (book_id + '.snapshots') / f'recover-{stamp}'
    backup.mkdir(parents=True, exist_ok=True)
    for raw in plan['updated']:
        shutil.copy2(store.directory(raw['id']) / 'project.json', backup / f"project-{raw['id']}.json")
    (backup / 'meta.json').write_text(json.dumps({'kind': 'recover_orphan_book', 'book_id': book_id, 'at': stamp, 'updated': [u['id'] for u in plan['updated']]}, ensure_ascii=False, indent=1), encoding='utf-8')
    try:
        for raw in plan['updated']:
            (store.directory(raw['id']) / 'project.json.adopt').write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
        book_tmp = books.root / ('.' + book_id + '.json.adopt')
        book_tmp.write_text(json.dumps(plan['book'], ensure_ascii=False, indent=2), encoding='utf-8')
        for raw in plan['updated']:
            os.replace(store.directory(raw['id']) / 'project.json.adopt', store.directory(raw['id']) / 'project.json')
        os.replace(book_tmp, books.root / (book_id + '.json'))
    except BaseException:
        for raw in plan['updated']:
            (store.directory(raw['id']) / 'project.json.adopt').unlink(missing_ok=True)
        (books.root / ('.' + book_id + '.json.adopt')).unlink(missing_ok=True)
        raise
    return {'book': plan['book'], 'updated': [u['id'] for u in plan['updated']], 'created': [], 'backup': str(backup)}

# 最后更新：2026-09-21 · Claude Hera
