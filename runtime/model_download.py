"""Controlled download worker. Only this subprocess enables Hub network access."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import time
from contextlib import nullcontext
import re
import httpx

from .model_catalog import CATALOG, signatures
from scripts.setup_model import REQUIRED, write_json


def report(**event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def safe_folder(root, relative):
    """Never publish or cache through a link into shared/external model storage."""
    path = root
    for part in Path(relative).parts:
        path = path/part
        if path.is_symlink():
            raise ValueError('共享模型链接只允许校验，不能下载或覆盖。')
    return path


def verify(folder, spec, emit=report):
    required = list(spec['sha256']) if spec.get('gguf') else REQUIRED + list(spec['sha256'])
    missing = [name for name in required if not (folder/name).is_file()]
    if missing:
        return missing
    total = sum((folder/name).stat().st_size for name in spec['sha256'])
    done, bad = 0, []
    for name, expected in spec['sha256'].items():
        h = hashlib.sha256()
        with (folder/name).open('rb') as stream:
            while block := stream.read(4*1024*1024):
                h.update(block)
                done += len(block)
                emit(status='verifying', completed=done, total=total, file=name)
        if h.hexdigest() != expected:
            bad.append(name)
    return bad


def register(kind, root, folder, spec):
    provenance = {key: spec[key] for key in ('repo', 'revision', 'sha256')}
    # Never write to a shared model link, including links in parent directories.
    shared = folder.is_symlink()
    for parent in folder.parents:
        if parent == root:
            break
        shared = shared or parent.is_symlink()
    if kind in ('preset', 'preset-large', 'design') and shared:
        try:
            existing = json.loads((folder/'voxstage-model.json').read_text())
        except (OSError, ValueError):
            existing = None
        if existing != provenance:
            raise ValueError('共享模型记录不匹配，请修复共享来源后再校验。')
    if kind in ('preset', 'preset-large', 'design') and not shared:
        write_json(folder/'voxstage-model.json', provenance)
    if kind == 'asr' and not shared:
        from scripts import setup_asr
        write_json(folder/'provenance.json', dict(repo=spec['repo'], revision=spec['revision'],
                                                 file=setup_asr.NAME, sha256=setup_asr.SHA))
        cli = os.environ.get('VOXSTAGE_WHISPER_CLI') or shutil.which('whisper-cli')
        if cli and Path(cli).is_file():
            result = __import__('subprocess').run([cli, '--version'], capture_output=True, timeout=15)
            if result.returncode == 0:
                with Path(cli).open('rb') as stream:
                    cli_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                write_json(root/'asr-settings.json', dict(cli=str(Path(cli).resolve()),
                           model=str((folder/setup_asr.NAME).resolve()), cli_sha256=cli_sha))
    write_json(root/'model-installations'/(kind+'.json'), dict(provenance,
               verified_files=signatures(folder, spec), verified_at=time.time()))


def matches(path, expected):
    if not path.is_file():
        return False
    algorithm = 'sha256' if len(expected) == 64 else 'sha1'
    digest = hashlib.new(algorithm)
    if algorithm == 'sha1':
        digest.update(('blob '+str(path.stat().st_size)+'\0').encode())
    with path.open('rb') as stream:
        while chunk := stream.read(4*1024*1024):
            digest.update(chunk)
    return digest.hexdigest() == expected


def fetch_file(client, url, target, partial, expected_size, expected_hash, progress):
    """Stable partial path and validated Range response; survives process termination."""
    if matches(target, expected_hash):
        progress(expected_size)
        return
    partial.parent.mkdir(parents=True, exist_ok=True)
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > expected_size:
        partial.unlink()
        offset = 0
    if offset != expected_size:
        headers = {'Accept-Encoding': 'identity'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
        with client.stream('GET', url, headers=headers, follow_redirects=True) as response:
            response.raise_for_status()
            if response.status_code == 206:
                value = response.headers.get('Content-Range', '')
                match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', value)
                if (not match or int(match[1]) != offset or int(match[3]) != expected_size
                        or int(match[2]) != expected_size-1):
                    raise ValueError('续传响应不匹配，已保留缓存并停止。')
            elif response.status_code == 200:
                offset = 0  # A server without Range support: start safely from zero.
            else:
                raise ValueError('续传响应不匹配，已保留缓存并停止。')
            progress(offset)
            with partial.open('ab' if offset else 'wb') as stream:
                for chunk in response.iter_bytes(chunk_size=1024*1024):
                    if offset+len(chunk) > expected_size:
                        raise ValueError('下载文件大小不匹配，已停止。')
                    stream.write(chunk)
                    offset += len(chunk)
                    progress(offset)
                stream.flush()
                os.fsync(stream.fileno())
    if offset != expected_size:
        raise ValueError('下载未完成，请检查网络后续传。')
    if not matches(partial, expected_hash):
        partial.unlink()  # Only damaged private cache; the original model remains untouched.
        raise ValueError('下载文件校验失败，未登记；再次下载将修复损坏文件。')
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(partial, target)
    progress(expected_size)


def install(kind, root, verify_only=False, hub=None, emit=report, http_client=None):
    spec = CATALOG[kind]
    folder = root/'models'/spec['folder']
    emit(status='verifying', completed=0, total=0, file='')
    if not verify(folder, spec, emit):
        register(kind, root, folder, spec)
        emit(status='ready', completed=1, total=1, file='')
        return
    if verify_only:
        raise ValueError('模型缺失或校验失败，请选择下载修复。')
    safe_folder(root, Path('models')/spec['folder'])
    staging = safe_folder(root, Path('model-downloads')/kind/'files')
    staging.mkdir(parents=True, exist_ok=True)
    if hub is None:
        import huggingface_hub as hub
    options = dict(repo_id=spec['repo'], revision=spec['revision'], local_dir=staging,
                   token=False, endpoint='https://huggingface.co')
    emit(status='preparing', completed=0, total=0, file='')
    files = hub.snapshot_download(**options, dry_run=True,
             **({'allow_patterns': list(spec['sha256'])} if spec.get('gguf') else
                {'ignore_patterns': ['*.md', '.gitattributes']}))
    entries = []
    needed = 0
    for info in files:
        name = PurePosixPath(info.filename)
        if (name.is_absolute() or '..' in name.parts or '\\' in info.filename
                or not name.parts or name.parts[0] in ('.cache', '.partials')):
            raise ValueError('模型文件列表无效。')
        target = safe_folder(root, Path('model-downloads')/kind/'files'/info.filename)
        partial = safe_folder(root, Path('model-downloads')/kind/'partials'/(info.filename+'.part'))
        if info.commit_hash != spec['revision']:
            raise ValueError('下载版本不匹配，已停止。')
        url = hub.hf_hub_url(spec['repo'], info.filename, revision=spec['revision'], endpoint='https://huggingface.co')
        metadata = hub.get_hf_file_metadata(url, token=False, endpoint='https://huggingface.co')
        if (metadata.commit_hash != spec['revision'] or metadata.size != info.file_size
                or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', metadata.etag or '')
                or not metadata.location.startswith('https://')
                or (info.filename in spec['sha256'] and metadata.etag != spec['sha256'][info.filename])):
            raise ValueError('下载版本或校验值不匹配，已停止。')
        if target.exists() and not matches(target, metadata.etag):
            target.unlink()
        if not target.exists():
            cached = min(partial.stat().st_size, info.file_size) if partial.exists() else 0
            needed += info.file_size-cached
        entries.append((info, metadata, target, partial))
    if shutil.disk_usage(root).free < needed + 512*1024**2:
        raise ValueError('磁盘空间不足，请释放空间后续传。')
    total = sum(info.file_size for info in files)
    done = 0
    # No account tokens, telemetry, project data or URLs supplied by the API caller.
    with (nullcontext(http_client) if http_client is not None else
          httpx.Client(timeout=httpx.Timeout(30, connect=15), trust_env=False)) as client:
        for info, metadata, target, partial in entries:
            fetch_file(client, metadata.location, target, partial, info.file_size, metadata.etag,
                      lambda count: emit(status='downloading', completed=done+count,
                                         total=total, file=info.filename))
            done += info.file_size
    bad = verify(staging, spec, emit)
    if bad:
        for name in bad:
            path = staging/name
            if path.is_file():
                path.unlink()
        raise ValueError('下载文件校验失败，未登记；再次下载将修复损坏文件。')
    emit(status='installing', completed=total, total=total, file='')
    for info in files:
        target = safe_folder(root, Path('models')/spec['folder']/info.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging/info.filename, target)
    register(kind, root, folder, spec)
    emit(status='ready', completed=total, total=total, file='')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=CATALOG, required=True)
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    try:
        install(args.model, Path(args.data_dir), args.verify_only)
    except Exception as exc:
        # Do not send download URLs, machine paths or tokens to the interface.
        message = str(exc) if isinstance(exc, ValueError) else '下载未完成，请检查网络后续传。'
        report(status='error', error=message)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
