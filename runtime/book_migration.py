"""Read-only preflight for legacy Book/Project data.

Nothing here migrates, rewrites, recreates or deletes user data. It classifies
what can be wrapped into the v1 master-book structure and what needs human
review first.
"""
import json


def _project_rows(store):
    rows = []
    for path in sorted(store.root.glob('*/project.json')):
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        rows.append(raw)
    return rows


def _range_against_chapters(text, chapters):
    whole = ''.join(c.get('text', '') for c in chapters)
    if not text or not whole:
        return {'kind': 'unknown'}
    starts = []
    pos = 0
    for i, chapter in enumerate(chapters):
        starts.append((pos, pos + len(chapter.get('text', '')), i))
        pos += len(chapter.get('text', ''))
    at = whole.find(text)
    if at < 0 or whole.find(text, at + 1) >= 0:
        return {'kind': 'edited_or_ambiguous'}
    end = at + len(text)
    touched = [i for a, b, i in starts if a < end and b > at]
    left_boundary = any(a == at for a, _, _ in starts)
    right_boundary = end == len(whole) or any(a == end for a, _, _ in starts)
    if len(touched) == 1 and left_boundary and right_boundary:
        return {'kind': 'exact_chapter', 'chapter_indexes': [touched[0] + 1]}
    if len(touched) == 1:
        return {'kind': 'partial_chapter', 'chapter_indexes': [touched[0] + 1]}
    if touched:
        return {'kind': 'spans_chapters', 'chapter_indexes': [i + 1 for i in touched],
                'boundary_aligned': left_boundary and right_boundary}
    return {'kind': 'unknown'}


def preview(store, books):
    projects = _project_rows(store)
    paths = sorted(books.root.glob('*.json'))
    records = {}
    for path in paths:
        try:
            book = json.loads(path.read_text(encoding='utf-8'))
            records[book['id']] = book
        except (OSError, ValueError, KeyError):
            continue

    by_book = {}
    for project in projects:
        link = project.get('book') or {}
        bid = link.get('id')
        if bid:
            by_book.setdefault(bid, []).append(project)

    legacy = []
    current = []
    for bid, book in records.items():
        linked = sorted(by_book.get(bid, []), key=lambda p: (p.get('book') or {}).get('index', 0))
        if book.get('master_schema') == 1:
            current.append({
                'book_id': bid, 'title': book.get('title'), 'status': 'current',
                'members': len(book.get('members', [])), 'linked_projects': len(linked),
            })
            continue
        chapters = book.get('chapters') or []
        mappings = []
        for project in linked:
            index = (project.get('book') or {}).get('index')
            exact_index = None
            if isinstance(index, int) and 1 <= index <= len(chapters):
                if project.get('source_script', '') == chapters[index - 1].get('text', ''):
                    exact_index = index
            mapping = {'project_id': project['id'], 'name': project.get('name'),
                       'book_index': index, 'revision': project.get('revision', 0)}
            mapping.update({'kind': 'exact_chapter', 'chapter_indexes': [exact_index]}
                           if exact_index else _range_against_chapters(
                               project.get('source_script', ''), chapters))
            mappings.append(mapping)
        expected = len(chapters)
        exact = [m for m in mappings if m['kind'] == 'exact_chapter']
        exact_indexes = sorted(m['chapter_indexes'][0] for m in exact if m.get('chapter_indexes'))
        complete_exact = expected > 0 and exact_indexes == list(range(1, expected + 1)) and len(mappings) == expected
        if complete_exact:
            status = 'ready_to_wrap'
            note = '每个旧章节都有一份正文完全匹配的工程，可先预览后无损建立新版主工程关系。'
        elif not linked:
            status = 'book_only'
            note = '保留了旧 Book 原文，但没有已关联工程；不要自动制造已处理章节。'
        else:
            status = 'needs_structure_review'
            note = '旧章节与工程不是一一对应；先用拆分/合并方案逐项确认，不能按旧编号硬迁移。'
        legacy.append({
            'book_id': bid, 'title': book.get('title'), 'language': book.get('language'),
            'status': status, 'note': note, 'chapter_count': expected,
            'linked_projects': len(linked), 'mappings': mappings,
            'backup_required': True,
        })

    orphaned = []
    for bid, linked in sorted(by_book.items()):
        if bid in records:
            continue
        linked = sorted(linked, key=lambda p: (p.get('book') or {}).get('index', 0))
        expected_values = [(p.get('book') or {}).get('chapters') for p in linked]
        expected = max((x for x in expected_values if isinstance(x, int)), default=len(linked))
        indexes = [(p.get('book') or {}).get('index') for p in linked]
        complete = expected > 0 and sorted(i for i in indexes if isinstance(i, int)) == list(range(1, expected + 1))
        title = next(((p.get('book') or {}).get('title') for p in linked
                      if (p.get('book') or {}).get('title')), '已删除的主工程')
        orphaned.append({
            'book_id': bid, 'title': title,
            'status': 'recoverable_complete' if complete else 'recoverable_partial',
            'expected_projects': expected, 'found_projects': len(linked),
            'missing_indexes': [i for i in range(1, expected + 1) if i not in indexes],
            'projects': [{'id': p['id'], 'name': p.get('name'),
                          'index': (p.get('book') or {}).get('index'),
                          'revision': p.get('revision', 0)}
                         for p in linked],
            'note': ('工程仍完整，可提供“恢复为主工程”入口；不要自动复活。'
                     if complete else
                     '只剩部分工程，只能恢复为部分主工程；不得伪造缺失章节。'),
        })

    standalone = [p for p in projects if not (p.get('book') or {}).get('id')]
    return {
        'schema_version': 1,
        'summary': {
            'current_master_books': len(current),
            'legacy_books': len(legacy),
            'orphan_groups': len(orphaned),
            'standalone_projects': len(standalone),
            'ready_to_wrap': sum(x['status'] == 'ready_to_wrap' for x in legacy),
            'recoverable_complete': sum(x['status'] == 'recoverable_complete' for x in orphaned),
            'needs_review': sum(x['status'] == 'needs_structure_review' for x in legacy)
                            + sum(x['status'] == 'recoverable_partial' for x in orphaned),
        },
        'current': current,
        'legacy': legacy,
        'orphaned': orphaned,
        'standalone': [{'id': p['id'], 'name': p.get('name'), 'revision': p.get('revision', 0)}
                       for p in standalone],
        'read_only': True,
        'notice': '这是只读预检；没有迁移、创建、删除或修改任何现有工程。',
    }

