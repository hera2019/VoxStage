"""Project packages (本人 2026-09-25: 做一个工程打包功能，将一个主工程或子工程全部
内容打包。删掉这个工程后，如果导入这个包，可以重新恢复此工程).

A package is one `.voxstage` file — a zip — holding everything a project needs
to come back: its record with the undo history, every take in `audio/`, the
fixed voices' references, the latest export batch, an unfinished speaker
draft, and the library voices it reads with (so it comes back even when those
voices were deleted too). A book's package holds the book record, its asset
folder and every chapter. Previews and check work files are left out: they are
made again on use, and the cleanup already treats them as disposable.

Every file is listed in the manifest with its SHA-256 and checked on import;
paths are checked against a fixed shape, so a package cannot write outside the
places it restores. Import never overwrites: a project or book that is still
here is a conflict, and the person may restore a copy under new ids instead.
A chapter packaged alone carries its effective settings; when its book no
longer lists it, it comes back as a separate project with those settings
frozen, never half-attached. Claude Hera."""
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from .cleanup import latest_export_revision
from .project_settings import SETTING_KEYS, VIEW_KEY

FORMAT = 'voxstage-package'
VERSION = 1
SUFFIX = '.voxstage'
MAX_BYTES = 8 * 1024 ** 3                  # unpacked; a whole long book with its takes stays far below
HEX = '[0-9a-f]{32}'
SHA = '[0-9a-f]{64}'
STORED = ('.wav', '.mp3', '.flac', '.zip')   # already compressed or not worth it
FIXED = [re.compile(p) for p in (
    r'manifest\.json', r'book\.json', rf'book-assets/references/{SHA}\.wav',
    rf'projects/{HEX}/project\.json', rf'projects/{HEX}/audio/{SHA}\.(?:wav|json)',
    rf'projects/{HEX}/references/{SHA}\.wav', rf'voices/{HEX}\.(?:json|wav)', rf'drafts/{HEX}\.json')]
EXPORT = re.compile(rf'projects/{HEX}/exports/\d+/(.+)')


class Conflict(Exception):
    """The project or book is still here; `names` says which."""
    def __init__(self, names):
        super().__init__('、'.join(names))
        self.names = names


class NeedsConsent(Exception):
    """The package brings recordings a person supplied; `names` are those voices."""
    def __init__(self, names):
        super().__init__('、'.join(names))
        self.names = names


def _allowed(name):
    if any(p.fullmatch(name) for p in FIXED):
        return True
    match = EXPORT.fullmatch(name)
    if not match:
        return False
    parts = match.group(1).split('/')
    return all(part not in ('', '.', '..') and not part.startswith('.') and '\\' not in part
               and not any(ord(c) < 32 for c in part) and len(part.encode()) <= 255 for part in parts)


def _sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _voice_ids(*records):
    text = json.dumps(records, ensure_ascii=False)
    return sorted(set(re.findall(r'custom:(' + HEX + ')', text)))


def _draft_ids(project):
    ids = {(project.get('attribution') or {}).get('draft_id'), (project.get('attribution_batch') or {}).get('draft_id')}
    return sorted(i for i in ids if isinstance(i, str) and re.fullmatch(HEX, i))


def _project_files(directory):
    """(path inside the project folder, file) for what the package keeps."""
    directory = Path(directory)
    for folder in ('audio', 'references'):
        for f in sorted((directory / folder).glob('*')) if (directory / folder).is_dir() else []:
            if f.is_file() and not f.is_symlink():
                yield f'{folder}/{f.name}', f
    exports = directory / 'exports'
    keep = latest_export_revision(exports)
    if keep is not None:
        for f in sorted((exports / str(keep)).rglob('*')):
            if f.is_file() and not f.is_symlink():
                yield f'exports/{keep}/{f.relative_to(exports / str(keep)).as_posix()}', f


def build(out_path, *, kind, projects, book=None, book_assets=None, directory_of, library, drafts_root,
          views=None, reference_file=None):
    """Write a package of `projects` (raw records, as stored) and, for a book, the
    book record. `views` gives a chapter packaged alone its effective settings;
    `reference_file(project, sha)` finds a fixed voice's reference the chapter
    never held itself (it came from the book). Returns the manifest."""
    out_path = Path(out_path)
    files, entries = {}, []

    def add(name, path=None, data=None):
        if not _allowed(name):
            raise ValueError(f'打包时遇到无法放进工程包的文件：{name}')
        entries.append((name, path, data))
        files[name] = _sha(path) if path is not None else hashlib.sha256(data).hexdigest()

    listed = []
    for project in projects:
        pid = project['id']
        record = dict(project)
        entry = {'id': pid, 'name': project.get('name', ''), 'book': project.get('book')}
        view = (views or {}).get(pid)
        if view is not None:
            entry['settings'] = {key: view[key] for key in SETTING_KEYS if key in view}
        add(f'projects/{pid}/project.json', data=json.dumps(record, ensure_ascii=False, indent=1).encode('utf-8'))
        held = set()
        for inner, path in _project_files(directory_of(pid)):
            add(f'projects/{pid}/{inner}', path)
            if inner.startswith('references/'):
                held.add(inner.split('/')[1][:-4])
        for profile in (view or {}).get('voice_profiles', {}).values() if view else []:
            sha = (profile or {}).get('sha256')
            if sha and sha not in held and reference_file:
                found = reference_file(project, sha)
                if found and Path(found).is_file() and _sha(found) == sha:
                    add(f'projects/{pid}/references/{sha}.wav', Path(found)); held.add(sha)
        listed.append(entry)
    if book is not None:
        add('book.json', data=json.dumps(book, ensure_ascii=False, indent=1).encode('utf-8'))
        refs = Path(book_assets or '') / 'references'
        for f in sorted(refs.glob('*.wav')) if book_assets and refs.is_dir() else []:
            add(f'book-assets/references/{f.name}', f)
    voices, provided = [], []
    for vid in _voice_ids(projects, book):
        try:
            entry = library.get(vid)
        except (ValueError, OSError):
            continue                                   # a voice the library no longer has cannot travel
        add(f'voices/{vid}.json', data=json.dumps(entry, ensure_ascii=False, indent=1).encode('utf-8'))
        add(f'voices/{vid}.wav', library.audio_path(vid))
        voices.append({'id': vid, 'name': entry['name'], 'source': entry['source']})
        if entry['source'] == 'provided':
            provided.append(entry['name'])
    drafts = []
    for project in projects:
        for did in _draft_ids(project):
            path = Path(drafts_root) / f'{did}.json'
            if path.is_file() and did not in drafts:
                add(f'drafts/{did}.json', path); drafts.append(did)
    manifest = {'format': FORMAT, 'version': VERSION, 'kind': kind, 'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                'title': (book or {}).get('title') if kind == 'book' else projects[0].get('name', ''),
                'book_id': (book or {}).get('id'), 'projects': listed, 'voices': voices, 'drafts': drafts,
                'provided_recordings': provided, 'files': files,
                'note': 'Previews and check work files are not included; they are made again when needed.'}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_name(out_path.name + '.partial')
    try:
        with zipfile.ZipFile(partial, 'w', allowZip64=True) as archive:
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=1), compress_type=zipfile.ZIP_DEFLATED)
            for name, path, data in entries:
                method = zipfile.ZIP_STORED if name.lower().endswith(STORED) else zipfile.ZIP_DEFLATED
                if path is not None:
                    archive.write(path, name, compress_type=method)
                else:
                    archive.writestr(name, data, compress_type=method)
        os.replace(partial, out_path)
    finally:
        partial.unlink(missing_ok=True)
    return manifest


def read(path):
    """The manifest, after checking the whole package: its shape, the paths,
    the sizes, and that every listed file is there with its SHA-256."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise ValueError('这不是 VoxStage 工程包（.voxstage）。')
    with archive:
        names = archive.namelist()
        if 'manifest.json' not in names:
            raise ValueError('这不是 VoxStage 工程包（.voxstage）。')
        try:
            manifest = json.loads(archive.read('manifest.json'))
        except ValueError:
            raise ValueError('工程包的清单无法读取。')
        if manifest.get('format') != FORMAT or manifest.get('kind') not in ('project', 'book'):
            raise ValueError('这不是 VoxStage 工程包（.voxstage）。')
        if manifest.get('version') != VERSION:
            raise ValueError('这个工程包来自更新的 VoxStage 版本，请先更新再导入。')
        total = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            if not _allowed(info.filename) or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f'工程包里有不该出现的文件：{info.filename[:80]}')
            total += info.file_size
        if total > MAX_BYTES:
            raise ValueError('工程包解开后超过 8 GB，拒绝导入。')
        files = manifest.get('files') or {}
        present = set(names) - {'manifest.json'}
        if present != set(files):
            raise ValueError('工程包的内容和清单对不上，可能不完整。')
        for name, sha in files.items():
            digest = hashlib.sha256()
            with archive.open(name) as stream:
                for block in iter(lambda: stream.read(1 << 20), b''):
                    digest.update(block)
            if digest.hexdigest() != sha:
                raise ValueError(f'工程包里的文件校验不一致：{name[:80]}')
        ids = [p.get('id') for p in manifest.get('projects') or []]
        if not ids or any(not isinstance(i, str) or not re.fullmatch(HEX, i) for i in ids):
            raise ValueError('工程包的清单无法读取。')
        if manifest['kind'] == 'book' and not (isinstance(manifest.get('book_id'), str) and re.fullmatch(HEX, manifest['book_id']) and 'book.json' in files):
            raise ValueError('工程包的清单无法读取。')
        return manifest


def restore(path, *, store, books, library, drafts_root, as_copy=False, consent=False):
    """Put a package's work back. Returns what came back; raises Conflict when
    it is still here (unless `as_copy`), NeedsConsent when it brings recordings
    a person supplied and `consent` was not given."""
    manifest = read(path)
    kind = manifest['kind']
    pids = [p['id'] for p in manifest['projects']]
    book_id = manifest.get('book_id') if kind == 'book' else None
    with store.lock:
        if not as_copy:
            here = [p['name'] or p['id'] for p in manifest['projects'] if (store.root / p['id']).exists()]
            if book_id and (books.root / f'{book_id}.json').exists():
                here.insert(0, manifest.get('title') or book_id)
            if here:
                raise Conflict(here)
        needing = [v['name'] for v in manifest.get('voices') or [] if v['source'] == 'provided' and not (library.root / f"{v['id']}.json").exists()]
        if needing and not consent:
            raise NeedsConsent(needing)
        remap = {old: uuid.uuid4().hex for old in pids + ([book_id] if book_id else [])} if as_copy else {}

        def swap(text):
            for old, new in remap.items():
                text = text.replace(old, new)
            return text

        staging = Path(tempfile.mkdtemp(prefix='.package-', dir=store.root))
        placed, book_path, assets_path = [], None, None
        try:
            with zipfile.ZipFile(path) as archive:
                book = None
                if book_id:
                    book = json.loads(swap(archive.read('book.json').decode('utf-8')))
                    if as_copy:
                        book['title'] = book.get('title', '') + ('（副本）' if book.get('language') != 'en' else ' (copy)')
                loose, names = [], []
                for entry in manifest['projects']:
                    old = entry['id']; new = remap.get(old, old)
                    folder = staging / new
                    for name in manifest['files']:
                        if not name.startswith(f'projects/{old}/') or name.endswith('/project.json'):
                            continue
                        target = folder / name[len(f'projects/{old}/'):]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(name) as src, open(target, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                    record = json.loads(swap(archive.read(f'projects/{old}/project.json').decode('utf-8')))
                    record['archived'] = False
                    if (record.get('job') or {}).get('status') in ('queued', 'running'):
                        record['job']['status'] = 'interrupted'
                    link = record.get('book') or {}
                    if kind == 'project' and link.get('id'):
                        parent = books.root / f"{link['id']}.json"
                        listed = parent.is_file() and new in json.loads(parent.read_text(encoding='utf-8')).get('members', [])
                        if as_copy or not listed:
                            # Its book no longer lists it (or it is a copy): a separate
                            # project, with the settings it had in the book frozen in.
                            record.pop('book', None)
                            for key, value in (entry.get('settings') or {}).items():
                                record[key] = value
                            record.pop(VIEW_KEY, None)
                            loose.append(new)
                    if as_copy and kind == 'project':
                        record['name'] = record.get('name', '') + ('（副本）' if record.get('language') != 'en' else ' (copy)')
                    names.append(record.get('name', ''))
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / 'project.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
                for entry in manifest['projects']:
                    new = remap.get(entry['id'], entry['id'])
                    os.rename(staging / new, store.root / new)
                    placed.append(store.root / new)
                if book is not None:
                    assets = [n for n in manifest['files'] if n.startswith('book-assets/')]
                    if assets:
                        assets_path = books.root / f"{book['id']}.assets"
                        for name in assets:
                            target = assets_path / name[len('book-assets/'):]
                            target.parent.mkdir(parents=True, exist_ok=True)
                            if not target.exists():
                                with archive.open(name) as src, open(target, 'wb') as dst:
                                    shutil.copyfileobj(src, dst)
                    book_path = books.root / f"{book['id']}.json"
                    book_path.write_text(json.dumps(book, ensure_ascii=False), encoding='utf-8')
                added = 0
                for voice in manifest.get('voices') or []:
                    entry = json.loads(archive.read(f"voices/{voice['id']}.json"))
                    if library.adopt(entry, archive.read(f"voices/{voice['id']}.wav"), consent_confirmed=consent):
                        added += 1
                Path(drafts_root).mkdir(parents=True, exist_ok=True)
                for did in manifest.get('drafts') or []:
                    target = Path(drafts_root) / f'{did}.json'
                    if not target.exists():
                        target.write_bytes(archive.read(f'drafts/{did}.json'))
        except BaseException:
            for folder in placed:
                shutil.rmtree(folder, ignore_errors=True)
            if book_path is not None:
                book_path.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return {'kind': kind, 'title': (book or {}).get('title') if kind == 'book' else names[0],
            'book_id': book['id'] if book is not None else None,
            'projects': [remap.get(p, p) for p in pids], 'loose': loose, 'voices_added': added, 'copy': bool(as_copy)}

# 最后更新：2026-09-25 · Claude Hera
