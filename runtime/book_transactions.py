"""Book-wide transactions for settings, names, and structure.

Sol 三 owns the commit boundary. Pure structure plans live in book_structure;
this adapter validates revisions, records a persistent JSON snapshot, stages
new projects/assets, and either commits the whole change or restores old data.
Audio is never regenerated here.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid

from . import book_structure
from . import cast as cast_model
from .project_settings import ROLE_MAPS, SETTING_KEYS


RUNNING = ('queued', 'running')


class BookTransactions:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.books = service.books
        self._previews = {}

    def _book(self, book_id):
        book = self.books.get(book_id)
        if book.get('master_schema') != 1:
            raise ValueError('旧版书目不能使用主工程事务。')
        return book

    def _members(self, book):
        rows = []
        for project_id in book.get('members', []):
            raw = self.store.read(project_id)
            if (raw.get('book') or {}).get('id') != book['id']:
                raise ValueError('主工程成员记录不一致，请先修复关联。')
            rows.append(raw)
        return rows

    @staticmethod
    def _assert_idle(projects):
        busy = [p['name'] for p in projects if (p.get('job') or {}).get('status') in RUNNING]
        if busy:
            raise RuntimeError(f"主工程中有章节正在处理：{'、'.join(busy[:5])}。请完成或取消后再操作。")

    def _snapshot(self, book, projects, reason, *, created=()):
        stamp = time.strftime('%Y%m%d-%H%M%S')
        sid = stamp + '-' + uuid.uuid4().hex[:8]
        root = self.books.root / (book['id'] + '.snapshots') / sid
        root.mkdir(parents=True, exist_ok=False)
        self.service._write_json(root / 'book.json', book)
        project_dir = root / 'projects'
        project_dir.mkdir()
        for raw in projects:
            self.service._write_json(project_dir / (raw['id'] + '.json'), raw)
        self.service._write_json(root / 'meta.json', {
            'id': sid, 'book_id': book['id'], 'reason': reason,
            'created_at': time.time(), 'status': 'prepared',
            'book_revision': book.get('revision', 0),
            'project_revisions': {p['id']: p.get('revision', 0) for p in projects},
            'created_projects': list(created),
        })
        return sid, root

    def _snapshot_status(self, root, status):
        path = root / 'meta.json'
        meta = json.loads(path.read_text())
        meta['status'] = status
        meta['finished_at'] = time.time()
        self.service._write_json(path, meta)

    @staticmethod
    def _copy_asset(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)

    def _commit(self, book_before, book_after, updates, creates, *, reason,
                delete_book=False, staged_assets=None):
        existing_before = {pid: self.store.read(pid) for pid in updates}
        sid, snapshot = self._snapshot(book_before, existing_before.values(), reason,
                                       created=creates)
        staging = Path(tempfile.mkdtemp(prefix='.book-txn-', dir=self.store.root))
        created_targets = []
        added_assets = []
        book_path = self.books.root / (book_before['id'] + '.json')
        try:
            for pid, raw in creates.items():
                folder = staging / pid
                folder.mkdir(parents=True)
                self.service._write_json(folder / 'project.json', raw)

            for source, relative, required, sha256 in staged_assets or []:
                if source is None:
                    if required:
                        raise ValueError('事务需要的声音文件不存在。')
                    continue
                if sha256 and source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() != sha256:
                    raise ValueError('事务需要的声音文件校验失败。')
                parts = Path(relative).parts
                pid = parts[0] if parts else ''
                rest = Path(*parts[1:]) if len(parts) > 1 else Path()
                if pid in creates:
                    self._copy_asset(source, staging / pid / rest)
                else:
                    target = self.store.root / relative
                    if target.exists():
                        if sha256 and target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
                            raise ValueError('目标固定声线文件已存在但校验不一致。')
                        # Content-addressed references and retained project assets
                        # need no overwrite when the target already exists.
                        continue
                    hold = staging / '_assets' / str(len(added_assets))
                    self._copy_asset(source, hold)
                    added_assets.append((hold, target, False))

            book_tmp = staging / 'book.json'
            if not delete_book:
                self.service._write_json(book_tmp, book_after)

            for pid in creates:
                target = self.store.directory(pid)
                if target.exists():
                    raise RuntimeError('新工程编号冲突，事务没有写入。')
                os.replace(staging / pid, target)
                created_targets.append(target)

            for raw in updates.values():
                self.store.write(raw)

            for hold, target, existed in added_assets:
                if existed:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(hold, target)

            if delete_book:
                book_path.unlink(missing_ok=True)
            else:
                os.replace(book_tmp, book_path)
            self._snapshot_status(snapshot, 'committed')
            return sid
        except BaseException:
            for raw in existing_before.values():
                self.store.write(raw)
            for target in created_targets:
                shutil.rmtree(target, ignore_errors=True)
            self.service._write_json(book_path, book_before)
            for _, target, existed in added_assets:
                if not existed:
                    if target.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        target.unlink(missing_ok=True)
            self._snapshot_status(snapshot, 'rolled_back')
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _strip_revision(spec):
        return {k: deepcopy(v) for k, v in spec.items() if k != 'revision'}

    @staticmethod
    def _preview_key(book_id, spec):
        return book_id + ':' + json.dumps(BookTransactions._strip_revision(spec),
                                          ensure_ascii=False, sort_keys=True,
                                          separators=(',', ':'))

    def _structure_plan(self, book, spec):
        op = spec.get('op')
        if op == 'split':
            if spec.get('at') is None:
                raise ValueError('拆分需要选择章节内的边界。')
            return book_structure.plan_split(
                book, self.store.read(spec.get('project_id', '')), int(spec['at']))
        if op == 'merge':
            left = self.store.read(spec.get('left_id', ''))
            right = self.store.read(spec.get('right_id', ''))
            plan = book_structure.plan_merge(
                book, left, right, resolutions=spec.get('resolutions') or {})
            conflicts = self._cast_id_conflicts(left, right)
            if conflicts:
                plan.setdefault('questions', []).extend(conflicts)
                plan['identity_conflicts'] = conflicts
            return plan
        if op == 'reorder':
            return book_structure.plan_reorder(book, spec.get('members') or [])
        if op == 'attach':
            project = self.store.read(spec.get('project_id', ''))
            plan = book_structure.plan_attach(
                book, project, spec.get('position'), inherit=bool(spec.get('inherit')),
                defaults=self.service.application_defaults())
            for question in plan.get('questions', []):
                if question.get('kind') == 'same_name':
                    entry = cast_model.find(book.get('cast', []), question['name'])
                    if entry:
                        question['cast_id'] = entry['id']
            return plan
        if op == 'detach':
            return book_structure.plan_detach(
                book, self.store.read(spec.get('project_id', '')),
                defaults=self.service.application_defaults())
        if op == 'dissolve':
            return book_structure.plan_dissolve(
                book, self._members(book), defaults=self.service.application_defaults())
        raise ValueError('未知的主工程结构操作。')

    @staticmethod
    def _cast_id_conflicts(left, right):
        a, b = left.get('cast_ids') or {}, right.get('cast_ids') or {}
        return [{'kind': 'identity_conflict', 'name': name,
                 'left_cast_id': a[name], 'right_cast_id': b[name],
                 'note': '同名人物在两章绑定了不同身份，不能在合并时自动选一个。'}
                for name in sorted(set(a) & set(b)) if a[name] != b[name]]

    def preview_structure(self, book_id, spec):
        with self.store.lock:
            book = self._book(book_id)
            members = self._members(book)
            extra = [self.store.read(spec.get('project_id', ''))] if spec.get('op') == 'attach' else []
            self._assert_idle(members + extra)
            plan = self._structure_plan(book, spec)
            watched = {p['id']: p.get('revision', 0) for p in members + extra}
            plan['project_revisions'] = watched
            self._previews[self._preview_key(book_id, spec)] = {
                'book_revision': book.get('revision', 0), 'projects': watched,
            }
            public = deepcopy(plan)
            # Opus's pure merge planner intentionally returns a minimal shape
            # while conflicts are unresolved.  The browser dialog expects the
            # common plan collections to exist on every preview response.
            for field, empty in (
                ('members_after', list(book.get('members', []))),
                ('chapters_after', []), ('new_projects', []), ('retired', []),
                ('assets', []), ('conflicts', []), ('questions', [])):
                public.setdefault(field, deepcopy(empty))
            public['new_projects'] = [
                {'id': p['id'], 'name': p['name'], 'segments': len(p.get('segments', [])),
                 'processing_state': p.get('processing_state')}
                for p in public.get('new_projects', [])]
            return public

    def apply_structure(self, book_id, spec):
        with self.store.lock:
            book = self._book(book_id)
            if book.get('revision', 0) != spec.get('revision'):
                raise RuntimeError('主工程已改变，请重新看方案。')
            key = self._preview_key(book_id, spec)
            receipt = self._previews.get(key)
            if not receipt:
                raise RuntimeError('这个结构方案还没有预览，或服务已经重启；请先点“看方案”。')
            ids = list(book.get('members', []))
            if spec.get('op') == 'attach':
                ids.append(spec.get('project_id'))
            current_revisions = {pid: self.store.read(pid).get('revision', 0) for pid in ids}
            if receipt['book_revision'] != book.get('revision', 0) or current_revisions != receipt['projects']:
                raise RuntimeError('看方案后有章节被修改，请重新看方案再执行。')
            members = [self.store.read(pid) for pid in book.get('members', [])]
            extra = [self.store.read(spec.get('project_id'))] if spec.get('op') == 'attach' else []
            self._assert_idle(members + extra)
            plan = self._structure_plan(book, spec)
            if plan.get('unresolved'):
                raise ValueError('合并设置还有未处理的冲突，请先完成选择并重新看方案。')
            if plan.get('identity_conflicts'):
                raise ValueError('同名人物绑定了不同身份，请先处理人物映射再合并。')

            book_after = deepcopy(book)
            new_records = [deepcopy(p) for p in plan.get('new_projects', [])]
            if spec.get('op') == 'attach':
                self._resolve_attach_identities(
                    book_after, new_records[0], plan, spec.get('identities') or {})

            final_by_id = {p['id']: p for p in members}
            for raw in new_records:
                final_by_id[raw['id']] = raw
            updates, creates = {}, {}
            total = len(plan.get('members_after', []))
            titles = {row['project_id']: row['title'] for row in plan.get('chapters_after', [])}

            for retired_id in plan.get('retired', []):
                old = self.store.read(retired_id)
                hidden = deepcopy(old)
                hidden.pop('book', None)
                hidden['archived'] = True
                hidden['structure_retired'] = {
                    'book_id': book_id, 'book_revision': book.get('revision', 0),
                    'op': plan.get('op'), 'retired_at': time.time(),
                }
                hidden['revision'] = old.get('revision', 0) + 1
                updates[retired_id] = hidden

            for index, pid in enumerate(plan.get('members_after', []), 1):
                raw = deepcopy(final_by_id[pid])
                raw.setdefault('book', {})
                raw['book'].update(id=book_id, title=book['title'], index=index, chapters=total)
                if self.store.directory(pid).exists():
                    before = self.store.read(pid)
                    raw['revision'] = before.get('revision', 0) + 1
                    updates[pid] = raw
                else:
                    raw['revision'] = 0
                    creates[pid] = raw
                final_by_id[pid] = raw

            for raw in new_records:
                if raw['id'] not in plan.get('members_after', []) and self.store.directory(raw['id']).exists():
                    before = self.store.read(raw['id'])
                    raw['revision'] = before.get('revision', 0) + 1
                    updates[raw['id']] = raw

            book_after['members'] = list(plan.get('members_after', []))
            book_after['chapters'] = [
                {'index': i, 'title': titles[pid], 'project_id': pid,
                 'chars': len(final_by_id[pid].get('source_script', ''))}
                for i, pid in enumerate(book_after['members'], 1)]
            book_after['revision'] = book.get('revision', 0) + 1
            book_after['aliases'] = cast_model.alias_table(book_after.get('cast', []))

            sid = self._commit(
                book, book_after, updates, creates,
                reason='structure:' + str(plan.get('op')),
                delete_book=plan.get('op') == 'dissolve',
                staged_assets=self._structure_assets(plan))
            self._previews.pop(key, None)
            return {
                'op': plan.get('op'), 'snapshot_id': sid,
                'book_revision': None if plan.get('op') == 'dissolve' else book_after['revision'],
                'members': book_after['members'], 'dissolved': plan.get('op') == 'dissolve',
                'created': list(creates), 'retired': list(plan.get('retired', [])),
            }

    def _structure_assets(self, plan):
        assets = []
        for item in plan.get('assets', []):
            if 'from' in item and 'to' in item:
                source = self.store.root / item['from']
                if item.get('keep') and item['from'] == item['to']:
                    if item.get('required') and not source.exists():
                        raise ValueError('结构操作需要的参考声音不存在。')
                    continue
                if not source.exists():
                    if item.get('required'):
                        raise ValueError('结构操作需要的声音或参考文件不存在：' + item['from'])
                    continue
                assets.append((source, item['to'], bool(item.get('required')), item.get('sha256')))
            elif item.get('to_project') and item.get('profile'):
                source = self.service._asset_path(item)
                digest = item['profile']['sha256']
                if not source.exists():
                    raise ValueError('脱离主工程所需的固定声线参考不存在。')
                assets.append((source, f"{item['to_project']}/references/{digest}.wav", True, digest))
        return assets

    def _resolve_attach_identities(self, book, project, plan, identities):
        cast = book.setdefault('cast', [])
        for question in plan.get('questions', []):
            if question.get('kind') == 'same_name':
                name = question['name']
                answer = identities.get(name)
                if not answer:
                    raise ValueError(f'「{name}」与书中人物同名：请明确选择关联已有角色，或给加入工程的人物改名。')
                if answer.get('action') == 'link':
                    entry = cast_model.find(cast, name)
                    if not entry or (answer.get('cast_id') and answer['cast_id'] != entry['id']):
                        raise ValueError(f'「{name}」要关联的角色已经变化，请重新看方案。')
                    project.setdefault('cast_ids', {})[name] = entry['id']
                elif answer.get('action') == 'rename':
                    new_name = str(answer.get('name') or '').strip()
                    self._assert_rename_available(book, project, name, new_name)
                    self._rename_project_refs(project, name, new_name)
                    entry = cast_model.ensure(cast, new_name, 'person')[0]
                    project.setdefault('cast_ids', {})[new_name] = entry['id']
                else:
                    raise ValueError(f'「{name}」的人物映射选择无效。')
            elif question.get('kind') == 'new_name':
                name = question['name']
                entry, _ = cast_model.ensure(cast, name, 'person')
                project.setdefault('cast_ids', {})[name] = entry['id']
        book['aliases'] = cast_model.alias_table(cast)

    @staticmethod
    def _assert_rename_available(book, project, old, new):
        if not new or new in ('旁白', 'Narrator', 'NARRATOR', 'UNKNOWN'):
            raise ValueError('新角色名无效。')
        if cast_model.find(book.get('cast', []), new):
            raise ValueError(f'主工程已经有「{new}」，不能静默合并人物。')
        names = {s.get('speaker') for s in project.get('segments', [])}
        if new != old and new in names:
            raise ValueError(f'加入工程里已经有「{new}」，请先在原工程处理人物名字。')

    def unify_settings(self, book_id, revision, values, inherit=()):
        with self.store.lock:
            book = self._book(book_id)
            if book.get('revision', 0) != revision:
                raise RuntimeError('主工程已改变，请刷新后再统一设置。')
            members = self._members(book)
            self._assert_idle(members)
            clean = self.service._validate_patch(values, inherit)
            selected = set(clean) | set(inherit)
            if not selected:
                raise ValueError('请选择至少一项要统一的设置。')
            updated_book = deepcopy(book)
            settings = updated_book.setdefault('settings', {})
            for key in inherit:
                settings.pop(key, None)
            settings.update(clean)
            updated_book['revision'] = revision + 1

            updates, cleared = {}, {}
            for raw in members:
                changed = deepcopy(raw)
                local = [key for key in selected if key in changed]
                history_changed = self._remove_settings_from_history(changed, selected)
                for key in selected:
                    changed.pop(key, None)
                if local or history_changed:
                    changed['revision'] = raw.get('revision', 0) + 1
                    updates[raw['id']] = changed
                cleared[raw['id']] = local
            sid = self._commit(book, updated_book, updates, {}, reason='settings:unify')
            return {
                'book_id': book_id, 'revision': updated_book['revision'],
                'settings': updated_book['settings'], 'snapshot_id': sid,
                'cleared_overrides': cleared, 'updated_projects': list(updates),
            }

    def unify_role(self, book_id, revision, key, name, value):
        """One character's entry in a role map — 阿宁's voice — for the whole
        book (本人 2026-09-22: 改了一个子工程里的角色音色，怎么应用到其它章节):
        the book's map takes it, every chapter's own entry for that name goes,
        the rest of each chapter's map stays. A chapter that wants its own —
        the character grown old — sets it again afterwards. Claude Hera."""
        from .project_settings import ROLE_MAPS
        if key not in ROLE_MAPS or key == 'voice_profiles':
            raise ValueError('只能统一角色声音、颜色、性别或群口。')
        name = (name or '').strip()
        if not name:
            raise ValueError('请说明是哪个角色。')
        with self.store.lock:
            book = self._book(book_id)
            if book.get('revision', 0) != revision:
                raise RuntimeError('主工程已改变，请刷新后再统一设置。')
            members = self._members(book)
            self._assert_idle(members)
            updated_book = deepcopy(book)
            settings = updated_book.setdefault('settings', {})
            role_map = dict(settings.get(key) or {})
            if value is None:
                role_map.pop(name, None)
            else:
                role_map[name] = deepcopy(value)
            settings[key] = role_map
            updated_book['revision'] = revision + 1
            updates, cleared = {}, {}
            for raw in members:
                own = raw.get(key)
                if isinstance(own, dict) and name in own:
                    changed = deepcopy(raw)
                    changed[key] = {n: v for n, v in own.items() if n != name}
                    if not changed[key]:
                        changed.pop(key, None)
                    changed['revision'] = raw.get('revision', 0) + 1
                    updates[raw['id']] = changed
                    cleared[raw['id']] = [name]
            sid = self._commit(book, updated_book, updates, {}, reason=f'settings:unify-role:{key}')
            return {'book_id': book_id, 'revision': updated_book['revision'], 'settings': updated_book['settings'],
                    'snapshot_id': sid, 'cleared_overrides': cleared, 'updated_projects': list(updates)}

    @staticmethod
    def _remove_settings_from_history(project, keys):
        changed = False
        for stack_name in ('history', 'future'):
            for state in project.get(stack_name, []):
                for key in keys:
                    if key in state:
                        state.pop(key, None)
                        changed = True
                marker = state.get('_settings_snapshot')
                if isinstance(marker, list):
                    next_marker = [key for key in marker if key not in keys]
                    if next_marker != marker:
                        state['_settings_snapshot'] = next_marker
                        changed = True
        return changed

    def rename_plan(self, book_id, revision, cast_id, name):
        with self.store.lock:
            book = self._book(book_id)
            if book.get('revision', 0) != revision:
                raise RuntimeError('主工程已改变，请刷新后再改名。')
            members = self._members(book)
            self._assert_idle(members)
            entry = cast_model.by_id(book.get('cast', []), cast_id)
            if not entry:
                raise ValueError('找不到这个全书角色。')
            new_name = (name or '').strip()
            conflicts = self._rename_conflicts(book, members, entry['name'], new_name, cast_id)
            affected = []
            for raw in members:
                refs = self._count_role_refs(raw, entry['name'])
                if refs:
                    affected.append({'project_id': raw['id'], 'name': raw['name'],
                                     'references': refs, 'revision': raw.get('revision', 0)})
            return {
                'book_id': book_id, 'book_revision': revision, 'cast_id': cast_id,
                'old_name': entry['name'], 'new_name': new_name,
                'affected_projects': affected, 'conflicts': conflicts,
                'keeps_audio': True,
            }

    def rename_cast(self, book_id, revision, cast_id, name):
        with self.store.lock:
            plan = self.rename_plan(book_id, revision, cast_id, name)
            if plan['conflicts']:
                raise ValueError(plan['conflicts'][0]['message'])
            book = self._book(book_id)
            members = self._members(book)
            old, new = plan['old_name'], plan['new_name']
            updated_book = deepcopy(book)
            cast_model.rename(updated_book.setdefault('cast', []), cast_id, new)
            self._rename_setting_refs(updated_book.setdefault('settings', {}), old, new)
            updated_book['aliases'] = cast_model.alias_table(updated_book['cast'])
            updated_book['revision'] = revision + 1
            updates = {}
            for raw in members:
                if not self._count_role_refs(raw, old):
                    continue
                changed = deepcopy(raw)
                self._rename_project_refs(changed, old, new, cast_id=cast_id)
                for stack in ('history', 'future'):
                    for state in changed.get(stack, []):
                        self._rename_project_refs(state, old, new, cast_id=cast_id,
                                                  history=True)
                changed['revision'] = raw.get('revision', 0) + 1
                updates[raw['id']] = changed
            sid = self._commit(book, updated_book, updates, {},
                               reason=f'cast:rename:{old}->{new}')
            return {
                **plan, 'book_revision': updated_book['revision'],
                'snapshot_id': sid, 'updated_projects': list(updates),
            }

    def cast_usage(self, book_id):
        """How many lines each character of the book's cast speaks, over every chapter."""
        with self.store.lock:
            book = self._book(book_id)
            spoken = {}
            for raw in self._members(book):
                for segment in raw.get('segments', []):
                    spoken[segment.get('speaker')] = spoken.get(segment.get('speaker'), 0) + 1
            return {'revision': book.get('revision', 0),
                    'lines': {c['id']: spoken.get(c['name'], 0) for c in book.get('cast', [])}}

    def remove_cast(self, book_id, revision, cast_id):
        """Drop a character no chapter's lines use any more — a name the model
        misspelled and the reviewer corrected line by line stays in the cast
        otherwise (本人 2026-09-24), and is offered to the model for every later
        chapter. Voice and colour settings kept for the name go with it; the
        review records of what was confirmed at the time are left as they were."""
        with self.store.lock:
            book = self._book(book_id)
            if book.get('revision', 0) != revision:
                raise RuntimeError('主工程已改变，请刷新后再删除。')
            members = self._members(book)
            self._assert_idle(members)
            entry = cast_model.by_id(book.get('cast', []), cast_id)
            if not entry:
                raise ValueError('找不到这个全书角色。')
            name = entry['name']
            using = [raw['name'] for raw in members if any(s.get('speaker') == name for s in raw.get('segments', []))]
            if using:
                raise ValueError(f'「{name}」还有句子在用（{"、".join(using[:3])}），不能删除；可以改名或把句子改给别人。')
            updated_book = deepcopy(book)
            updated_book['cast'] = [c for c in updated_book.get('cast', []) if c['id'] != cast_id]
            self._drop_setting_refs(updated_book.setdefault('settings', {}), name)
            updated_book['aliases'] = cast_model.alias_table(updated_book['cast'])
            updated_book['revision'] = revision + 1
            updates = {}
            for raw in members:
                changed = deepcopy(raw)
                self._drop_setting_refs(changed, name)
                if (changed.get('cast_ids') or {}).get(name) == cast_id:
                    del changed['cast_ids'][name]
                if changed != raw:
                    changed['revision'] = raw.get('revision', 0) + 1
                    updates[raw['id']] = changed
            sid = self._commit(book, updated_book, updates, {}, reason=f'cast:remove:{name}')
            return {'book_revision': updated_book['revision'], 'snapshot_id': sid, 'removed': name,
                    'updated_projects': list(updates)}

    @staticmethod
    def _drop_setting_refs(settings, name):
        for key in ROLE_MAPS:
            mapping = settings.get(key)
            if isinstance(mapping, dict):
                mapping.pop(name, None)
        muted = settings.get('muted_speakers')
        if isinstance(muted, list) and name in muted:
            settings['muted_speakers'] = [x for x in muted if x != name]

    def _rename_conflicts(self, book, projects, old, new, cast_id):
        conflicts = []
        if not new or new in ('旁白', 'Narrator', 'NARRATOR', 'UNKNOWN'):
            return [{'kind': 'invalid_name', 'message': '新角色名无效。'}]
        other = cast_model.find(book.get('cast', []), new)
        if other and other['id'] != cast_id:
            conflicts.append({'kind': 'cast_name', 'cast_id': other['id'],
                              'message': f'主工程已经有另一个角色叫「{new}」，不能自动合并。'})
        if new != old:
            for raw in projects:
                if self._count_role_refs(raw, old) and self._count_role_refs(raw, new):
                    conflicts.append({'kind': 'project_name', 'project_id': raw['id'],
                                      'message': f'《{raw["name"]}》同时使用「{old}」和「{new}」，请先确认人物关系。'})
            for key in ROLE_MAPS:
                mapping = (book.get('settings') or {}).get(key) or {}
                if old in mapping and new in mapping:
                    conflicts.append({'kind': 'book_setting', 'key': key,
                                      'message': f'主工程设置 {key} 同时有「{old}」和「{new}」，不能自动覆盖。'})
        if not conflicts:
            probe = deepcopy(book.get('cast', []))
            try:
                cast_model.rename(probe, cast_id, new)
            except ValueError as exc:
                conflicts.append({'kind': 'cast', 'message': str(exc)})
        return conflicts

    @staticmethod
    def _count_role_refs(mapping, name):
        count = sum(1 for s in mapping.get('segments', []) if s.get('speaker') == name)
        count += sum(1 for key in ROLE_MAPS if name in (mapping.get(key) or {}))
        count += int(name in (mapping.get('muted_speakers') or []))
        count += int(name in (mapping.get('cast_ids') or {}))
        attribution = mapping.get('attribution') or {}
        count += sum(1 for row in attribution.get('confirmed_labels') or [] if row.get('speaker') == name)
        # Whole-book renames must protect content undo/redo too: an old snapshot
        # is still an active future state and must not be allowed to resurrect
        # the retired canonical name.
        for stack in ('history', 'future'):
            for state in mapping.get(stack, []):
                count += BookTransactions._count_role_refs(state, name)
        return count

    @staticmethod
    def _rename_setting_refs(settings, old, new):
        for key in ROLE_MAPS:
            mapping = settings.get(key)
            if isinstance(mapping, dict) and old in mapping:
                if new in mapping and new != old:
                    raise ValueError(f'{key} 同时存在新旧角色名，不能自动覆盖。')
                mapping[new] = mapping.pop(old)
        muted = settings.get('muted_speakers')
        if isinstance(muted, list) and old in muted:
            settings['muted_speakers'] = list(dict.fromkeys(new if x == old else x for x in muted))

    @classmethod
    def _rename_project_refs(cls, project, old, new, *, cast_id=None, history=False):
        for segment in project.get('segments', []):
            if segment.get('speaker') == old:
                segment['speaker'] = new
        cls._rename_setting_refs(project, old, new)
        cast_ids = project.get('cast_ids')
        if isinstance(cast_ids, dict) and old in cast_ids:
            if new in cast_ids and new != old and cast_ids[new] != cast_ids[old]:
                raise ValueError('工程中的角色身份映射发生同名冲突。')
            cast_ids[new] = cast_ids.pop(old)
            if cast_id:
                cast_ids[new] = cast_id
        if history:
            return
        attribution = project.get('attribution') or {}
        for row in attribution.get('confirmed_labels') or []:
            if row.get('speaker') == old:
                row['speaker'] = new
        for row in attribution.get('cast') or []:
            if row.get('id') == cast_id or row.get('name') == old:
                if row.get('name') == old:
                    aliases = row.setdefault('aliases', [])
                    if old not in aliases:
                        aliases.append(old)
                    row['name'] = new

