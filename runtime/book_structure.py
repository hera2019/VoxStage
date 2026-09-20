"""Structure operations on a master book as pure plans: split a chapter, merge
two adjacent ones, reorder, attach a standalone project, detach a chapter,
dissolve the book. Nothing here reads or writes disk; a plan is a description
the transaction layer (Sol) commits whole — new raw records, the member list
after, the assets to copy, the settings and identity questions the reviewer
must answer first. Opus 二, 2026-09-20 (Claude Hera).

Ground rules (design doc 9-20, review 1–6):
- A chapter is a project; splitting and merging make NEW projects with new
  ids, the originals stay on disk as the recovery snapshot of that operation
  and leave the member list. Content history is not spliced across projects.
- Segment ids and audio fingerprints are kept: a fingerprint depends on the
  line, the voice and the effective settings, not on where the line sits, so
  the audio files are copied under the new project, never regenerated here.
- Author structure (cut, hints, silent) is rebased, never concatenated as is;
  two chapters cut differently cannot be merged.
- Settings: equal local overrides survive, both-inherit stays inherit, a
  difference is a conflict the reviewer resolves (left / right / inherit / a
  value) before the plan exists. Role maps conflict per name.
- Names stay the identity key (review 3): attaching a project whose names
  match the book's cast asks, never merges; detaching freezes the effective
  settings into the project so it keeps its voice when the parent is gone.
"""
from copy import deepcopy
import uuid

from .project_settings import SETTING_KEYS, ROLE_MAPS, VIEW_KEY, effective, reference_requirements
from evals.speaker_attribution.source_units import source_units

STRUCTURE_KEYS = ('cut', 'hints', 'silent')
JOIN = '\n'


def _id():
    return uuid.uuid4().hex


def _member_index(book, project_id):
    try:
        return book['members'].index(project_id)
    except ValueError:
        raise ValueError('这个工程不是这本书的章节。') from None


def _line_of(text, offset):
    return text.count('\n', 0, offset)


def _rebase_marks(project, start, end, *, shift=0, line_shift=0):
    """The author's marks of `project` that fall inside [start, end) of its
    text, moved by `shift` characters and `line_shift` lines (both may be
    negative). A hint straddling a boundary is cut at it."""
    hints = []
    for h in project.get('hints') or []:
        a, b = max(h['start'], start), min(h['end'], end)
        if a < b:
            hints.append({**h, 'start': a + shift, 'end': b + shift})
    first_line, last_line = _line_of(project['source_script'], start), _line_of(project['source_script'], max(start, end - 1))
    silent = [n + line_shift for n in project.get('silent') or [] if first_line <= n <= last_line]
    return hints, silent


def _carry_labels(project, start, end, new_text, shift):
    """Confirmed attribution labels of the units inside [start, end), re-keyed
    to the units of `new_text` (same cut): a unit keeps its label when its
    text sits at the shifted position. Units that gained or lost text are left
    unlabelled — the review page will ask."""
    old = (project.get('attribution') or {}).get('confirmed_labels') or []
    if not old:
        return None
    cut = project.get('cut')
    by_start = {u['start']: (u, l) for u, l in zip(source_units(project['source_script'], cut), old)}
    labels = []
    for u in source_units(new_text, cut):
        hit = by_start.get(u['start'] - shift)
        labels.append({**hit[1], 'id': u['id']} if hit and hit[0]['text'] == u['text'] else _unmatched(u, new_text, cut))
    return {'confirmed_labels': labels, 'human_confirmed': all(l.get('confirmed', True) for l in labels), 'carried_from': project['id']}


def _unmatched(u, text, cut):
    """A unit no old label fits (its text changed at a boundary). In a text
    cut at quotation marks an unquoted unit is prose by construction, so it
    is settled; a quoted one, or any unit of a line-cut text, is asked again."""
    t = u['text'].strip()
    quoted_text = cut != 'lines' and any(c in text for c in '“"「『')
    if not t or (quoted_text and t[0] not in '“"「『'):
        return {'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'confirmed': True, 'source': 'structure'}
    return {'id': u['id'], 'kind': 'dialogue' if t[0] in '“"「『' else 'narration', 'speaker': 'UNKNOWN' if t[0] in '“"「『' else 'NARRATOR', 'confirmed': False, 'source': 'structure'}


def _piece(project, start, end, *, shift, line_shift, new_id, name, index=None):
    """A new raw project holding [start, end) of `project`: its text, the
    segments inside (rebased), the marks, the local settings, the identities;
    no history, revision 0, processing state as the source's."""
    text = project['source_script'][start:end]
    segments = []
    for s in project['segments']:
        if start <= s['source_start'] and s['source_end'] <= end:
            segments.append({**deepcopy(s), 'source_start': s['source_start'] + shift, 'source_end': s['source_end'] + shift})
        elif s['source_start'] < end and s['source_end'] > start:
            raise ValueError('切章的位置落在一句中间：先在那句上拆句，再从这里分章。')
    hints, silent = _rebase_marks(project, start, end, shift=shift, line_shift=line_shift)
    raw = {'schema_version': 1, 'id': new_id, 'name': name, 'language': project['language'], 'revision': 0,
           'source_script': text, 'segments': segments, 'processing_state': project.get('processing_state', 'processed' if project['segments'] else 'unprocessed'),
           'history': [], 'future': [], 'job': {'status': 'idle'}, 'synthetic_audio': True,
           'cut': project.get('cut'), 'hints': hints, 'silent': silent,
           **{k: deepcopy(project[k]) for k in SETTING_KEYS if k in project},
           **({'settings_schema': project['settings_schema']} if 'settings_schema' in project else {}),
           **({'cast_ids': deepcopy(project['cast_ids'])} if project.get('cast_ids') else {}),
           'structure': {'from': project['id'], 'range': [start, end]}}
    carried = _carry_labels(project, start, end, text, shift)
    if carried:
        raw['attribution'] = carried
    if project.get('book'):
        raw['book'] = {**project['book'], **({'index': index} if index else {})}
    return raw


def _assets(old, new):
    """Files the new project needs from the old one: each carried segment's
    audio (by fingerprint) and check folder (by segment id), and the fixed
    voices' reference recordings (by hash). Paths relative to the store root."""
    moves = []
    for s in new['segments']:
        fp = (s.get('audio') or {}).get('fingerprint')
        if fp:
            moves += [{'from': f"{old['id']}/audio/{fp}.{ext}", 'to': f"{new['id']}/audio/{fp}.{ext}", 'required': ext == 'wav'} for ext in ('wav', 'json')]
        moves.append({'from': f"{old['id']}/checks/{s['id']}", 'to': f"{new['id']}/checks/{s['id']}", 'required': False})
    for sp, prof in (new.get('voice_profiles') or {}).items():
        if prof.get('sha256'):
            moves.append({'from': f"{old['id']}/references/{prof['sha256']}.wav", 'to': f"{new['id']}/references/{prof['sha256']}.wav", 'required': True, 'sha256': prof['sha256']})
    return moves


def _members_after(book, replace, with_ids):
    members = list(book['members'])
    i = members.index(replace)
    return members[:i] + list(with_ids) + members[i + 1:]


def _chapters(members, names):
    return [{'index': n, 'title': names[pid], 'project_id': pid} for n, pid in enumerate(members, 1)]


def _finish(book, members, projects, names, *, retired=(), assets=(), conflicts=None, questions=None, op=None, snapshot=None):
    for p in projects:
        p.setdefault('book', {'id': book['id'], 'title': book['title']})
        p['book'].update({'index': members.index(p['id']) + 1, 'chapters': len(members)})
    return {'op': op, 'book_id': book['id'], 'book_revision': book.get('revision', 0), 'members_after': members,
            'chapters_after': _chapters(members, names), 'new_projects': projects, 'retired': list(retired),
            'assets': list(assets), 'conflicts': conflicts or [], 'questions': questions or [],
            'snapshot': snapshot or {'kept': list(retired), 'note': '原工程保留在磁盘上作为这次操作的恢复快照，不再列在成员里。'}}


def plan_split(book, project, at, *, titles=None):
    """Cut a chapter into two at character offset `at` of its text. Processed
    text: `at` must be a segment boundary (split the sentence first
    otherwise); unprocessed text: `at` must start a line."""
    _member_index(book, project['id'])
    text = project['source_script']
    if not 0 < at < len(text):
        raise ValueError('分章位置要在正文中间。')
    if project['segments']:
        if not any(s['source_start'] == at for s in project['segments']):
            raise ValueError('分章的位置要落在两句之间；要从一句中间分，先拆句。')
    elif text[at - 1] != '\n':
        raise ValueError('还没处理的章只能在行首分章。')
    titles = titles or (project['name'] + ' · 上', project['name'] + ' · 下')
    left = _piece(project, 0, at, shift=0, line_shift=0, new_id=_id(), name=titles[0])
    right = _piece(project, at, len(text), shift=-at, line_shift=-_line_of(text, at), new_id=_id(), name=titles[1])
    if right['segments']:
        right['segments'][0]['lock_before'] = True
    members = _members_after(book, project['id'], [left['id'], right['id']])
    names = {**{c['project_id']: c['title'] for c in book.get('chapters', [])}, left['id']: left['name'], right['id']: right['name']}
    return _finish(book, members, [left, right], names, retired=[project['id']], assets=_assets(project, left) + _assets(project, right), op='split')


def settings_conflicts(left, right, book=None):
    """Where two chapters' local settings disagree. A key both inherit is no
    conflict; a key one overrides and the other inherits is; role maps are
    compared name by name. Each item names the key (and role) with both values
    (None = inherits) so the reviewer can pick."""
    items = []
    for key in SETTING_KEYS:
        a, b = left.get(key), right.get(key)
        if key in ROLE_MAPS:
            for name in sorted(set(a or {}) | set(b or {})):
                va, vb = (a or {}).get(name), (b or {}).get(name)
                if va != vb:
                    items.append({'key': key, 'role': name, 'left': deepcopy(va), 'right': deepcopy(vb)})
        elif (key in left) != (key in right) or a != b:
            items.append({'key': key, 'left': deepcopy(a) if key in left else None, 'right': deepcopy(b) if key in right else None})
    return items


def plan_merge(book, left, right, *, resolutions=None, title=None):
    """Join two adjacent chapters into one new project, left then right. With
    `resolutions` — {key or key:role → 'left' | 'right' | 'inherit' | {'value': …}}
    — for every conflict; without them, the plan is only the list of conflicts
    (no new project) so the reviewer can answer first."""
    i, j = _member_index(book, left['id']), _member_index(book, right['id'])
    if j != i + 1:
        raise ValueError('只能合并相邻的两章，先把它们排到一起。')
    if left['language'] != right['language']:
        raise ValueError('两章语言不同，不能合并。')
    if left.get('cut') != right.get('cut'):
        raise ValueError('两章的切句方式不同（一章按颜色切、一章按引号切），不能合并；请分别处理。')
    conflicts = settings_conflicts(left, right)
    resolutions = resolutions or {}
    unresolved = [c for c in conflicts if (f"{c['key']}:{c['role']}" if 'role' in c else c['key']) not in resolutions]
    if unresolved:
        return {'op': 'merge', 'book_id': book['id'], 'book_revision': book.get('revision', 0), 'conflicts': conflicts, 'unresolved': unresolved, 'new_projects': [], 'members_after': list(book['members'])}
    sep = '' if left['source_script'].endswith('\n') else JOIN
    shift = len(left['source_script']) + len(sep)
    text = left['source_script'] + sep + right['source_script']
    new_id = _id()
    merged = _piece(left, 0, len(left['source_script']), shift=0, line_shift=0, new_id=new_id, name=title or f"{left['name']} + {right['name']}")
    tail = _piece(right, 0, len(right['source_script']), shift=shift, line_shift=_line_of(text, shift), new_id=new_id, name=merged['name'])
    seen = {s['id'] for s in merged['segments']}
    remap = {}
    for s in tail['segments']:
        if s['id'] in seen:                       # ids are uuids; a clash is recorded, never silently reused
            remap[s['id']] = _id(); s['id'] = remap[s['id']]
        seen.add(s['id'])
    if tail['segments']:
        tail['segments'][0]['lock_before'] = True     # a reslice never merges across the old chapter boundary
    merged.update({'source_script': text, 'segments': merged['segments'] + tail['segments'], 'hints': merged['hints'] + tail['hints'], 'silent': merged['silent'] + tail['silent'],
                   'processing_state': 'processed' if (left['segments'] or right['segments']) else 'unprocessed', 'structure': {'from': [left['id'], right['id']], 'join_at': shift}})
    if merged['processing_state'] == 'processed' and (not left['segments'] or not right['segments']):
        merged['processing_state'] = 'partial'          # one side never processed: its text has no segments yet
    # Settings: apply the reviewer's answers; equal overrides stayed in place from `left`.
    for c in conflicts:
        key, role = c['key'], c.get('role')
        choice = resolutions[f'{key}:{role}' if role else key]
        if role:
            m = merged.setdefault(key, {})
            if choice == 'left' and c['left'] is not None: m[role] = c['left']
            elif choice == 'right' and c['right'] is not None: m[role] = c['right']
            elif choice == 'inherit': m.pop(role, None)
            elif isinstance(choice, dict) and 'value' in choice: m[role] = choice['value']
            else: raise ValueError(f'角色 {role} 的 {key} 没有可用的处理方式。')
        else:
            if choice == 'left': (merged.__setitem__(key, deepcopy(c['left'])) if c['left'] is not None else merged.pop(key, None))
            elif choice == 'right': (merged.__setitem__(key, deepcopy(c['right'])) if c['right'] is not None else merged.pop(key, None))
            elif choice == 'inherit': merged.pop(key, None)
            elif isinstance(choice, dict) and 'value' in choice: merged[key] = choice['value']
            else: raise ValueError(f'{key} 没有可用的处理方式。')
    if 'cast_ids' in left or 'cast_ids' in right:
        merged['cast_ids'] = {**(left.get('cast_ids') or {}), **(right.get('cast_ids') or {})}
    la, ra = (left.get('attribution') or {}).get('confirmed_labels'), (right.get('attribution') or {}).get('confirmed_labels')
    if la or ra:
        merged['attribution'] = _merge_labels(left, right, text, shift)
    members = [m for m in book['members'] if m != right['id']]
    members = _members_after({'members': members}, left['id'], [new_id])
    names = {**{c['project_id']: c['title'] for c in book.get('chapters', [])}, new_id: merged['name']}
    assets = _assets(left, merged) + _assets(right, {**merged, 'segments': tail['segments'], 'voice_profiles': {}})
    return _finish(book, members, [merged], names, retired=[left['id'], right['id']], assets=assets, conflicts=conflicts, op='merge',
                   questions=[{'kind': 'segment_ids_remapped', 'map': remap}] if remap else [])


def _merge_labels(left, right, text, shift):
    a = _carry_labels(left, 0, len(left['source_script']), text, 0) or {'confirmed_labels': []}
    b = _carry_labels(right, 0, len(right['source_script']), text[shift:], 0) or {'confirmed_labels': []}
    # Units of the merged text: those from the left keep their ids; the right's are re-numbered by position.
    units = source_units(text, left.get('cut'))
    by_start = {}
    for u, l in zip(source_units(text[:shift], left.get('cut')), a['confirmed_labels']):
        by_start[u['start']] = l
    for u, l in zip(source_units(text[shift:], right.get('cut')), b['confirmed_labels']):
        by_start[u['start'] + shift] = l
    labels = [{**(by_start.get(u['start']) or _unmatched(u, text, left.get('cut'))), 'id': u['id']} for u in units]
    return {'confirmed_labels': labels, 'human_confirmed': all(l.get('confirmed', True) for l in labels), 'carried_from': [left['id'], right['id']]}


def plan_reorder(book, members):
    """The same members in a new order; nothing else changes but the indexes."""
    if sorted(members) != sorted(book['members']) or len(set(members)) != len(members):
        raise ValueError('排序只能改变顺序，不能增删章节。')
    names = {c['project_id']: c['title'] for c in book.get('chapters', [])}
    return {'op': 'reorder', 'book_id': book['id'], 'book_revision': book.get('revision', 0), 'members_after': list(members),
            'chapters_after': _chapters(members, names), 'new_projects': [], 'retired': [], 'assets': [], 'conflicts': [], 'questions': [],
            'reindex': {pid: n for n, pid in enumerate(members, 1)}}


def plan_attach(book, project, position=None, *, inherit=False, defaults=None):
    """A standalone project joins the book at `position` (0-based; end by
    default). Its effective settings stay as its own values unless `inherit`,
    in which case they are dropped and the book's apply. Names that already
    exist in the book's cast are questions, not merges."""
    if project.get('book', {}).get('id') == book['id'] and project['id'] in book['members']:
        raise ValueError('这个工程已经在这本书里。')
    if project.get('book') and project['book'].get('id') != book['id'] and project.get('processing_state'):
        raise ValueError('这个工程属于另一本书，先从那本书脱离。')
    if project['language'] != book['language']:
        raise ValueError('工程语言与主工程不同。')
    joined = deepcopy(project)
    joined.pop(VIEW_KEY, None)
    frozen = effective(project, None, defaults=defaults)
    if inherit:
        for key in SETTING_KEYS:
            joined.pop(key, None)
    else:
        for key in SETTING_KEYS:
            joined[key] = deepcopy(frozen[key])
    joined['settings_schema'] = 1
    joined['book'] = {'id': book['id'], 'title': book['title']}
    members = list(book['members'])
    at = len(members) if position is None else max(0, min(int(position), len(members)))
    members.insert(at, project['id'])
    names = {**{c['project_id']: c['title'] for c in book.get('chapters', [])}, project['id']: project['name']}
    book_names = {e['name'] for e in book.get('cast', [])} | set(book.get('aliases', {}))
    speakers = [s for s in dict.fromkeys(x['speaker'] for x in project['segments']) if s not in ('旁白', 'Narrator')]
    questions = [{'kind': 'same_name', 'name': n, 'note': '书里已有同名人物：是同一个人（关联）还是另一个人（改名）？不自动合并。'} for n in speakers if n in book_names]
    questions += [{'kind': 'new_name', 'name': n} for n in speakers if n not in book_names]
    plan = _finish(book, members, [joined], names, op='attach', questions=questions)
    plan['assets'] = [{'from': f"{project['id']}/references/{p['sha256']}.wav", 'to': f"{project['id']}/references/{p['sha256']}.wav", 'required': True, 'sha256': p['sha256'], 'keep': True}
                      for p in (joined.get('voice_profiles') or {}).values() if p.get('sha256')]
    return plan


def plan_detach(book, project, *, defaults=None):
    """A chapter leaves the book and keeps its voice: every effective setting is
    written into it as its own, the fixed voices it inherited are listed for
    copying, the book's members lose it."""
    _member_index(book, project['id'])
    view = effective(project, book, defaults=defaults)
    freed = deepcopy(project)
    freed.pop(VIEW_KEY, None)
    for key in SETTING_KEYS:
        freed[key] = deepcopy(view[key])
    freed.pop('book', None)
    freed['settings_schema'] = 1
    members = [m for m in book['members'] if m != project['id']]
    names = {c['project_id']: c['title'] for c in book.get('chapters', []) if c['project_id'] != project['id']}
    plan = {'op': 'detach', 'book_id': book['id'], 'book_revision': book.get('revision', 0), 'members_after': members,
            'chapters_after': _chapters(members, names), 'new_projects': [freed], 'retired': [], 'conflicts': [], 'questions': [],
            'assets': [{**r, 'to_project': project['id']} for r in reference_requirements(view)], 'snapshot': {'kept': [], 'note': '脱离只改成员关系；工程本身原地保留。'}}
    return plan


def plan_dissolve(book, projects, *, defaults=None):
    """Every member detached, in order; the book keeps nothing."""
    by_id = {p['id']: p for p in projects}
    missing = [m for m in book['members'] if m not in by_id]
    if missing:
        raise ValueError('缺少成员工程记录：' + ', '.join(missing))
    parts = [plan_detach(book, by_id[m], defaults=defaults) for m in book['members']]
    return {'op': 'dissolve', 'book_id': book['id'], 'book_revision': book.get('revision', 0), 'members_after': [], 'chapters_after': [],
            'new_projects': [p['new_projects'][0] for p in parts], 'retired': [], 'conflicts': [], 'questions': [],
            'assets': [a for p in parts for a in p['assets']], 'snapshot': {'kept': [], 'note': '解散只解除关系，不删任何声音。'}}


# 最后更新：2026-09-20 · Claude Hera
