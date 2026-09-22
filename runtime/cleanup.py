"""What a project folder holds that nothing needs any more, and how to drop it
(本人 2026-09-22: 工程会残留一些没用的垃圾文件 — the takes left behind when a
voice was changed, the audition previews, old export batches, the check
work-dirs). Nothing here touches the lines, the audio they use, the fixed
voices' references or the latest export. Claude Hera."""
import json
import re
import shutil
from pathlib import Path

STRAY = re.compile(r'^project\.json\.(?!tmp$).+|.*\.tmp$|.*\.adopt$|.*\.rollback$')


def _size(path):
    return sum(f.stat().st_size for f in path.rglob('*') if f.is_file()) if path.is_dir() else (path.stat().st_size if path.is_file() else 0)


def _fingerprints(segments):
    return {(s.get('audio') or {}).get('fingerprint') for s in segments or [] if s.get('audio')} - {None}


def latest_export_revision(folder):
    """The newest export batch that still has files: kept, the rest go."""
    revisions = [int(p.name) for p in folder.iterdir() if p.is_dir() and p.name.isdigit() and any(p.iterdir())] if folder.is_dir() else []
    return max(revisions) if revisions else None


def plan(project, directory):
    """Counts and bytes per kind, without deleting anything."""
    directory = Path(directory)
    used = _fingerprints(project.get('segments'))
    undo = set()
    for state in (project.get('history') or []) + (project.get('future') or []):
        undo |= _fingerprints(state.get('segments'))
    undo -= used
    out = {'audio': {'files': 0, 'bytes': 0}, 'undo_audio': {'files': 0, 'bytes': 0}, 'previews': {'files': 0, 'bytes': 0},
           'exports': {'files': 0, 'bytes': 0, 'keeps': None}, 'checks': {'files': 0, 'bytes': 0}, 'stray': {'files': 0, 'bytes': 0}}
    audio = directory / 'audio'
    if audio.is_dir():
        for f in audio.iterdir():
            if not f.is_file():
                continue
            stem = f.name.split('.')[0]
            if stem in used:
                continue
            kind = 'undo_audio' if stem in undo else 'audio'
            out[kind]['files'] += 1; out[kind]['bytes'] += f.stat().st_size
    previews = directory / 'previews'
    if previews.is_dir():
        files = [f for f in previews.rglob('*') if f.is_file()]
        out['previews'] = {'files': len(files), 'bytes': sum(f.stat().st_size for f in files)}
    exports = directory / 'exports'
    keep = latest_export_revision(exports)
    out['exports']['keeps'] = keep
    if exports.is_dir():
        for p in exports.iterdir():
            if p.is_dir() and p.name.isdigit() and int(p.name) != keep:
                files = [f for f in p.rglob('*') if f.is_file()]
                out['exports']['files'] += len(files); out['exports']['bytes'] += sum(f.stat().st_size for f in files)
    checks = directory / 'checks'
    if checks.is_dir():
        files = [f for f in checks.rglob('*') if f.is_file()]
        out['checks'] = {'files': len(files), 'bytes': sum(f.stat().st_size for f in files)}
    for f in directory.iterdir():
        if f.is_file() and STRAY.match(f.name):
            out['stray']['files'] += 1; out['stray']['bytes'] += f.stat().st_size
    out['total_bytes'] = sum(v['bytes'] for k, v in out.items() if isinstance(v, dict))
    out['total_files'] = sum(v['files'] for k, v in out.items() if isinstance(v, dict))
    return out


def apply(project, directory, *, include_undo=False):
    """Delete what `plan` counted. With `include_undo` the takes only the undo
    stack still points at go too, and the stack is cleared so nothing points
    at a missing file. Returns what was freed and the project (changed only
    when the undo stack was cleared)."""
    directory = Path(directory)
    before = plan(project, directory)
    used = _fingerprints(project.get('segments'))
    undo = set()
    for state in (project.get('history') or []) + (project.get('future') or []):
        undo |= _fingerprints(state.get('segments'))
    undo -= used
    freed = 0
    audio = directory / 'audio'
    if audio.is_dir():
        for f in list(audio.iterdir()):
            stem = f.name.split('.')[0]
            if not f.is_file() or stem in used or (stem in undo and not include_undo):
                continue
            freed += f.stat().st_size; f.unlink()
    changed = False
    if include_undo and (project.get('history') or project.get('future')):
        project['history'] = []; project['future'] = []; changed = True
    previews = directory / 'previews'
    if previews.is_dir():
        freed += _size(previews); shutil.rmtree(previews, ignore_errors=True)
    exports = directory / 'exports'
    keep = latest_export_revision(exports)
    if exports.is_dir():
        for p in list(exports.iterdir()):
            if p.is_dir() and p.name.isdigit() and int(p.name) != keep:
                freed += _size(p); shutil.rmtree(p, ignore_errors=True)
    checks = directory / 'checks'
    if checks.is_dir():
        freed += _size(checks); shutil.rmtree(checks, ignore_errors=True)
    for f in list(directory.iterdir()):
        if f.is_file() and STRAY.match(f.name):
            freed += f.stat().st_size; f.unlink()
    return {'freed_bytes': freed, 'planned': before, 'undo_cleared': changed}

# 最后更新：2026-09-22 · Claude Hera
