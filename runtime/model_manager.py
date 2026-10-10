"""Local model picker and one resumable subprocess, isolated from offline inference."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from .capacity import memory_gb
from .model_catalog import CATALOG, recommended, signatures
from scripts.setup_model import write_json, REQUIRED

ACTIVE = {'preparing', 'downloading', 'verifying', 'installing'}


class ModelManager:
    def __init__(self, root, popen=subprocess.Popen):
        self.root = Path(root)
        self.popen = popen
        self.lock = threading.RLock()
        self.process = None
        self.thread = None
        self.stopping = False
        self.jobs = {}
        for kind in CATALOG:
            try:
                job = json.loads(self.state_path(kind).read_text())
                if not isinstance(job, dict):
                    continue
                if job.get('status') in ACTIVE:
                    job['status'] = 'paused'
                self.jobs[kind] = job
            except (OSError, ValueError):
                pass

    def state_path(self, kind):
        return self.root/'model-downloads'/kind/'state.json'

    def snapshot(self, gb=None):
        gb = memory_gb() if gb is None else gb
        cursor = self.root
        while not cursor.exists():
            cursor = cursor.parent
        free = shutil.disk_usage(cursor).free
        selected = recommended(gb)
        models = []
        with self.lock:
            for kind, spec in CATALOG.items():
                folder = self.root/'models'/spec['folder']
                required = list(spec['sha256']) if spec.get('gguf') else REQUIRED+list(spec['sha256'])
                present = all((folder/name).is_file() for name in required)
                verified = False
                try:
                    record = json.loads((self.root/'model-installations'/(kind+'.json')).read_text())
                    if not isinstance(record, dict):
                        raise ValueError('Invalid model registry')
                    verified = (present and all(record.get(k) == spec[k] for k in ('repo', 'revision', 'sha256'))
                                and record.get('verified_files') == signatures(folder, spec))
                except (OSError, ValueError):
                    pass
                models.append(dict(id=kind, title=spec['title'], purpose=spec['purpose'],
                     repo=spec['repo'], revision=spec['revision'], estimated_bytes=spec['estimated_bytes'],
                     minimum_gb=spec['minimum_gb'], recommended=kind in selected,
                     compatible=gb >= spec['minimum_gb']-0.5,
                     present=present, verified=verified, job=dict(self.jobs.get(kind, {})),
                     license='MIT' if kind == 'asr' else 'Apache-2.0',
                     license_url='https://huggingface.co/'+spec['repo']+'/blob/'+spec['revision']+'/README.md'))
            return dict(memory_gb=round(gb, 1), free_bytes=free, models=models,
                        recommendation='recommended' if gb >= 31.5 else 'minimum',
                        below_minimum=gb < 15.5, active=bool(self.process),
                        first_run=not next(m for m in models if m['id']=='preset')['present'])

    def start(self, kind, verify_only=False):
        if kind not in CATALOG:
            raise ValueError('没有这个可下载模型。')
        with self.lock:
            if self.process:
                raise RuntimeError('已有模型任务，请先暂停或等待完成。')
            self.root.mkdir(parents=True, exist_ok=True)
            job = dict(model=kind, status='preparing', completed=0, total=0, file='', error=None)
            write_json(self.state_path(kind), job)
            env = dict(os.environ, VOXSTAGE_DATA_DIR=str(self.root), HF_HUB_OFFLINE='1' if verify_only else '0',
                       HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                       HF_HUB_DISABLE_XET='1', HF_HOME=str(self.root/'hf-cache'),
                       PYTHONUNBUFFERED='1')
            env.pop('HF_TOKEN', None)
            env.pop('HUGGING_FACE_HUB_TOKEN', None)
            command = [sys.executable, '-m', 'runtime.model_download', '--model', kind,
                       '--data-dir', str(self.root)] + (['--verify-only'] if verify_only else [])
            try:
                self.process = self.popen(command, cwd=Path(__file__).resolve().parents[1],
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           text=True, start_new_session=not bool(os.environ.get('VOXSTAGE_NATIVE_TOKEN')))
            except OSError:
                job.update(status='error', error='无法启动模型任务，请重试。')
                write_json(self.state_path(kind), job)
                self.jobs[kind] = job
                raise RuntimeError(job['error'])
            self.jobs[kind] = job
            self.stopping = False
            self.thread = threading.Thread(target=self._observe, args=(kind, self.process), daemon=True)
            self.thread.start()
            return dict(job)

    def _observe(self, kind, process):
        last_write = 0
        try:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get('status') not in ACTIVE | {'ready', 'error'}:
                    continue
                with self.lock:
                    self.jobs[kind].update(event)
                    now = time.monotonic()
                    if now-last_write >= 0.25 or event['status'] in {'ready', 'error'}:
                        write_json(self.state_path(kind), self.jobs[kind])
                        last_write = now
            code = process.wait()
            with self.lock:
                job = self.jobs[kind]
                if job['status'] != 'ready':
                    job['status'] = 'paused' if self.stopping else 'error'
                    if not self.stopping and not job.get('error'):
                        job['error'] = '模型任务中断，请续传或重新校验。'
                job['exit_code'] = code
                write_json(self.state_path(kind), job)
        finally:
            process.stdout.close()
            with self.lock:
                if self.process is process:
                    self.process = None

    def pause(self):
        with self.lock:
            process, thread = self.process, self.thread
            if not process:
                return
            self.stopping = True
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        thread.join(timeout=5)

    def close(self):
        self.pause()
