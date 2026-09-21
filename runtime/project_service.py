"""Transactional adapter for Book/Project v1 raw records and effective views."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from .book_master import plan_book, plan_chapter
from .project_settings import (ROLE_MAPS, SETTING_KEYS, VIEW_KEY, effective,
                               reference_requirements, _settings)


class ProjectService:
    def __init__(self, store, books, defaults):
        self.store = store
        self.books = books
        self.defaults = defaults

    def application_defaults(self):
        return deepcopy(self.defaults())

    def parent(self, raw):
        book_id = (raw.get('book') or {}).get('id')
        return self.books.get(book_id) if book_id else None

    def view(self, raw):
        return effective(raw, self.parent(raw), defaults=self.application_defaults())

    def setting_payload(self, raw):
        view = self.view(raw)
        metadata = view[VIEW_KEY]
        return {
            'project_id': raw['id'],
            'project_revision': raw.get('revision', 0),
            'book_revision': metadata.get('book_revision'),
            'settings_schema': raw.get('settings_schema'),
            'overrides': {key: deepcopy(raw[key]) for key in SETTING_KEYS if key in raw},
            'effective': {key: deepcopy(view[key]) for key in SETTING_KEYS},
            'sources': deepcopy(metadata['sources']),
        }

    def public_project(self, raw, engine, checker=None):
        view = self.view(raw)
        result = self.store.public(view, engine, checker)
        result.pop(VIEW_KEY, None)
        result['settings_state'] = self.setting_payload(raw)
        return result

    def _write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

    def _asset_path(self, requirement):
        owner = requirement['owner']
        digest = requirement['profile']['sha256']
        if owner.get('level') in ('project', 'legacy_default') and owner.get('id'):
            return self.store.directory(owner['id']) / 'references' / (digest + '.wav')
        if owner.get('level') == 'book' and owner.get('id'):
            return self.books.root / (owner['id'] + '.assets') / 'references' / (digest + '.wav')
        raise ValueError(f"角色 {requirement['speaker']} 的固定声线没有可保留的本地来源。")

    def _copy_references(self, requirements, target):
        for requirement in requirements:
            source = self._asset_path(requirement)
            digest = requirement['profile']['sha256']
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                raise ValueError(f"角色 {requirement['speaker']} 的固定声线文件缺失或校验失败。")
            folder = target / 'references'
            folder.mkdir(exist_ok=True)
            shutil.copy2(source, folder / (digest + '.wav'))

    def create_book(self, title, language, chapters):
        plan = plan_book(title, language, chapters, defaults=self.application_defaults())
        book, projects = plan['book'], plan['projects']
        staging = Path(tempfile.mkdtemp(prefix='.master-', dir=self.store.root))
        moved = []
        book_tmp = self.books.root / ('.' + book['id'] + '.json.tmp')
        try:
            for project in projects:
                folder = staging / project['id']
                self._write_json(folder / 'project.json', project)
            self._write_json(book_tmp, book)
            for project in projects:
                target = self.store.directory(project['id'])
                if target.exists():
                    raise RuntimeError('新工程编号冲突，主工程没有写入。')
                os.replace(staging / project['id'], target)
                moved.append(target)
            os.replace(book_tmp, self.books.root / (book['id'] + '.json'))
        except BaseException:
            book_tmp.unlink(missing_ok=True)
            for target in moved:
                shutil.rmtree(target, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return book, projects

    def create_standalone(self, title, text, language, *, cut=None, hints=None, silent=None):
        plan = plan_chapter(title, text, language, defaults=self.application_defaults(),
                            cut=cut, hints=hints, silent=silent)
        project = plan['project']
        staging = Path(tempfile.mkdtemp(prefix='.project-', dir=self.store.root))
        target = self.store.directory(project['id'])
        try:
            folder = staging / project['id']
            self._write_json(folder / 'project.json', project)
            os.replace(folder, target)
        except BaseException:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return project

    def create_chapter(self, book_id, revision, title, text, *, cut=None,
                       hints=None, silent=None, copy_from_id=None):
        book = self.books.get(book_id)
        if book.get('master_schema') != 1:
            raise ValueError('旧版书目不能直接加入新版子工程。')
        if book.get('revision', 0) != revision:
            raise RuntimeError('主工程已改变，请刷新后再加入章节。')
        source_view = None
        if copy_from_id:
            source = self.store.read(copy_from_id)
            if (source.get('book') or {}).get('id') != book_id:
                raise ValueError('只能复制同一主工程中子工程的设置。')
            source_view = self.view(source)
        plan = plan_chapter(title, text, book['language'], book=book, copy_from=source_view,
                            cut=cut, hints=hints, silent=silent)
        project = plan['project']
        updated = deepcopy(book)
        updated['revision'] = book.get('revision', 0) + 1
        updated['members'].append(project['id'])
        updated['chapters'].append({'index': len(updated['members']), 'title': project['name'],
                                    'project_id': project['id'], 'chars': len(text)})
        project['book'].update(index=len(updated['members']), chapters=len(updated['members']))
        existing = []
        backups = {}
        for index, member_id in enumerate(book['members'], 1):
            member = self.store.read(member_id)
            if (member.get('book') or {}).get('id') != book_id:
                raise ValueError('主工程成员记录不一致，未加入新章节。')
            if member.get('job', {}).get('status') == 'running':
                raise RuntimeError('主工程中有子工程正在处理，请完成后再加入章节。')
            changed = deepcopy(member)
            changed['book'].update(index=index, chapters=len(updated['members']), title=updated['title'])
            changed['revision'] = member.get('revision', 0) + 1
            existing.append(changed)
            path = self.store.directory(member_id) / 'project.json'
            backups[path] = path.read_bytes()
        staging = Path(tempfile.mkdtemp(prefix='.chapter-', dir=self.store.root))
        target = self.store.directory(project['id'])
        book_tmp = self.books.root / ('.' + book_id + '.json.tmp')
        try:
            folder = staging / project['id']
            self._write_json(folder / 'project.json', project)
            self._copy_references(plan['reference_copies'], folder)
            self._write_json(book_tmp, updated)
            os.replace(folder, target)
            for member in existing:
                self.store.write(member)
            os.replace(book_tmp, self.books.root / (book_id + '.json'))
        except BaseException:
            book_tmp.unlink(missing_ok=True)
            for path, content in backups.items():
                temporary = path.with_suffix('.json.rollback')
                temporary.write_bytes(content)
                os.replace(temporary, path)
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return updated, project

    def append_chapters(self, book_id, revision, chapters, *, copy_from_id=None):
        """Several chapters at the end of a master book in one transaction —
        a whole novel pasted as a 'new chapter' (本人 2026-09-22: a novel came in
        as one 769,000-character chapter). `chapters` are author_chapters()
        pieces with their marks rebased; every existing member is rewritten
        once with the new count, not once per chapter. Claude Hera."""
        book = self.books.get(book_id)
        if book.get('master_schema') != 1:
            raise ValueError('旧版书目不能直接加入新版子工程。')
        if book.get('revision', 0) != revision:
            raise RuntimeError('主工程已改变，请刷新后再加入章节。')
        if not chapters:
            raise ValueError('没有可加入的章节。')
        source_view = None
        if copy_from_id:
            source = self.store.read(copy_from_id)
            if (source.get('book') or {}).get('id') != book_id:
                raise ValueError('只能复制同一主工程中子工程的设置。')
            source_view = self.view(source)
        updated = deepcopy(book)
        updated['revision'] = book.get('revision', 0) + 1
        plans = []
        for piece in chapters:
            plan = plan_chapter(piece.get('title') or f"第 {len(updated['members']) + 1} 章", piece['text'], book['language'], book=book,
                                copy_from=source_view, cut=piece.get('cut'), hints=piece.get('hints'), silent=piece.get('silent'))
            project = plan['project']
            updated['members'].append(project['id'])
            updated['chapters'].append({'index': len(updated['members']), 'title': project['name'],
                                        'project_id': project['id'], 'chars': len(piece['text'])})
            plans.append(plan)
        total = len(updated['members'])
        for n, plan in enumerate(plans, len(book['members']) + 1):
            plan['project']['book'].update(index=n, chapters=total)
        existing, backups = [], {}
        for index, member_id in enumerate(book['members'], 1):
            member = self.store.read(member_id)
            if (member.get('book') or {}).get('id') != book_id:
                raise ValueError('主工程成员记录不一致，未加入新章节。')
            if member.get('job', {}).get('status') == 'running':
                raise RuntimeError('主工程中有子工程正在处理，请完成后再加入章节。')
            changed = deepcopy(member)
            changed['book'].update(index=index, chapters=total, title=updated['title'])
            changed['revision'] = member.get('revision', 0) + 1
            existing.append(changed)
            path = self.store.directory(member_id) / 'project.json'
            backups[path] = path.read_bytes()
        staging = Path(tempfile.mkdtemp(prefix='.chapters-', dir=self.store.root))
        book_tmp = self.books.root / ('.' + book_id + '.json.tmp')
        moved = []
        try:
            for plan in plans:
                folder = staging / plan['project']['id']
                self._write_json(folder / 'project.json', plan['project'])
                self._copy_references(plan['reference_copies'], folder)
            self._write_json(book_tmp, updated)
            for plan in plans:
                target = self.store.directory(plan['project']['id'])
                if target.exists():
                    raise RuntimeError('新工程编号冲突，章节没有写入。')
                os.replace(staging / plan['project']['id'], target)
                moved.append(target)
            for member in existing:
                self.store.write(member)
            os.replace(book_tmp, self.books.root / (book_id + '.json'))
        except BaseException:
            book_tmp.unlink(missing_ok=True)
            for path, content in backups.items():
                temporary = path.with_suffix('.json.rollback')
                temporary.write_bytes(content)
                os.replace(temporary, path)
            for target in moved:
                shutil.rmtree(target, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return updated, [plan['project'] for plan in plans]

    @staticmethod
    def _validate_patch(values, inherit):
        values = _settings(values)
        unknown = set(inherit) - set(SETTING_KEYS)
        if unknown:
            raise ValueError('未知设置项：' + ', '.join(sorted(unknown)))
        if set(values) & set(inherit):
            raise ValueError('同一设置不能同时覆盖和恢复继承。')
        if 'voice_profiles' in values:
            raise ValueError('固定声线需要连同本地参考音频一起保存，不能用通用设置接口修改。')
        for key in ('pause_ms', 'ellipsis_pause_ms'):
            if key in values and (not isinstance(values[key], int) or isinstance(values[key], bool)):
                raise ValueError(f'{key} 必须是整数。')
        if 'pause_ms' in values and not 0 <= values['pause_ms'] <= 2000:
            raise ValueError('pause_ms 必须在 0 到 2000 之间。')
        if 'ellipsis_pause_ms' in values and values['ellipsis_pause_ms'] not in (0, 300, 500):
            raise ValueError('ellipsis_pause_ms 只能是 0、300 或 500。')
        if 'speech_rate' in values and (isinstance(values['speech_rate'], bool)
                                        or not isinstance(values['speech_rate'], (int, float))
                                        or not .5 <= values['speech_rate'] <= 2):
            raise ValueError('speech_rate 必须在 0.5 到 2.0 之间。')
        if 'color_scope' in values and values['color_scope'] not in ('name', 'text', 'both'):
            raise ValueError('color_scope 无效。')
        if 'preset_model' in values and values['preset_model'] not in ('0.6B', '1.7B'):
            raise ValueError('preset_model 无效。')
        if 'clone_model' in values and values['clone_model'] not in ('0.6B', '1.7B'):
            raise ValueError('clone_model 无效。')
        for key in ROLE_MAPS:
            for name in values.get(key, {}):
                if not isinstance(name, str) or not name.strip():
                    raise ValueError(f'{key} 的角色名不能为空。')
        if 'muted_speakers' in values and (not isinstance(values['muted_speakers'], list)
                                            or any(not isinstance(name, str) or not name.strip()
                                                   for name in values['muted_speakers'])):
            raise ValueError('muted_speakers 必须是角色名列表。')
        if 'voices' in values and any(not isinstance(voice, str) or not voice
                                      for voice in values['voices'].values()):
            raise ValueError('voices 的音色编号不能为空。')
        if 'colors' in values and any(not isinstance(color, str)
                                      or not re.fullmatch(r'#[0-9a-fA-F]{6}', color)
                                      for color in values['colors'].values()):
            raise ValueError('colors 必须是六位十六进制颜色。')
        if 'sexes' in values and any(sex not in ('m', 'f') for sex in values['sexes'].values()):
            raise ValueError('sexes 只能使用 m 或 f。')
        if 'lexicon' in values:
            lexicon = values['lexicon']
            if len(lexicon) > 200 or any(not isinstance(written, str) or not isinstance(read, str)
                                         or not written.strip() or not read.strip()
                                         or len(written) > 40 or len(read) > 40
                                         for written, read in lexicon.items()):
                raise ValueError('发音词典最多 200 条，文字和读法均为 1–40 个字符。')
        return values

    def update_project_settings(self, project_id, revision, values, inherit=()):
        with self.store.lock:
            raw = self.store.read(project_id)
            if raw.get('settings_schema') != 1:
                raise ValueError('旧工程继续使用原设置接口，不自动迁移。')
            if raw.get('revision', 0) != revision or raw.get('job', {}).get('status') == 'running':
                raise RuntimeError('工程已改变或正在处理，请刷新后再保存设置。')
            clean = self._validate_patch(values, inherit)
            updated = deepcopy(raw)
            for key in inherit:
                updated.pop(key, None)
            updated.update(clean)
            updated['revision'] = revision + 1
            self.store.write(updated)
            return updated

    def update_book_settings(self, book_id, revision, values, inherit=()):
        with self.store.lock:
            book = self.books.get(book_id)
            if book.get('master_schema') != 1:
                raise ValueError('旧版书目没有主工程设置。')
            if book.get('revision', 0) != revision:
                raise RuntimeError('主工程已改变，请刷新后再保存设置。')
            clean = self._validate_patch(values, inherit)
            updated = deepcopy(book)
            settings = updated.setdefault('settings', {})
            for key in inherit:
                settings.pop(key, None)
            settings.update(clean)
            updated['revision'] = revision + 1
            temporary = self.books.root / ('.' + book_id + '.json.tmp')
            self._write_json(temporary, updated)
            os.replace(temporary, self.books.root / (book_id + '.json'))
            return updated
