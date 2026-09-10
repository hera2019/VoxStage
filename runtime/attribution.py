"""Local role drafts; reuse evaluated prompt and source binding. Astra 2026-09-10."""
import hashlib
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from evals.speaker_attribution.source_units import source_units, bind_labels, PAIRS

ROOT = Path(__file__).resolve().parents[1]
MODEL_SHA = 'ae916ede1c010a26955ee8ae2e908bf8815a3f135ec860439ab924701c69d5f1'


def project_segments(source, labels, language):
    # Validate IDs against preserved source, including duplicate/missing labels.
    bind_labels(source, json.dumps({'labels': labels}))
    by_id = {x['id']: x for x in labels}
    segments = []
    limit = 60 if language == 'zh' else 240
    for unit in source_units(source):
        label = by_id[unit['id']]
        speaker = label['speaker'].strip()
        if label['kind'] == 'narration':
            speaker = '旁白' if language == 'zh' else 'Narrator'
        if not speaker or speaker.upper() == 'UNKNOWN' or len(speaker) > 80 or '\n' in speaker:
            raise ValueError('请为所有未识别片段填写角色名称。')
        start = unit['start']
        while start < unit['end']:
            end = min(start + limit, unit['end'])
            # Prefer an existing sentence boundary; never ask the model to rewrite.
            if end < unit['end']:
                boundaries = [i+1 for i in range(start, end) if source[i] in '。！？；.!?;\n']
                if boundaries:
                    end = boundaries[-1]
            text = source[start:end]
            if text.strip():
                segments.append({'id': uuid.uuid4().hex, 'speaker': speaker, 'text': text,
                    'spoken_as': '', 'audio': None, 'error': None, 'kind': label['kind'],
                    'source_start': start, 'source_end': end})
            start = end
    if not 1 <= len(segments) <= 500:
        raise ValueError('原稿切片数量超出范围。')
    return segments


class RoleDraftEngine:
    def __init__(self):
        self.model = Path(os.environ.get('VOXSTAGE_ROLE_MODEL', ROOT.parent/'AI-Models/generators/qwen3-4b-instruct-2507/qwen3-4b-instruct-2507-q8_0.gguf'))
        self.server = Path(os.environ.get('VOXSTAGE_ROLE_SERVER', ROOT.parent/'AI-Lab/qwen3-14b-llamacpp/worktrees/llama.cpp/build-release-metal/bin/llama-server'))
        self.ready = self.model.is_file() and self.server.is_file()

    def annotate(self, text, log_path):
        if not self.ready:
            raise ValueError('本地分角色模型未就绪；仍可使用已标注剧本导入。')
        units = source_units(text)
        if not text.strip() or len(units) > 80:
            raise ValueError('请选取更短的原稿（最多 80 个引号切片）。')
        with self.model.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != MODEL_SHA:
                raise ValueError('分角色模型校验不一致。')
        prompt = (ROOT/'evals/speaker_attribution/prompt-anchored.txt').read_text()
        schema = {'type':'object', 'properties': {'labels': {'type':'array', 'minItems':len(units), 'maxItems':len(units),
            'items': {'type':'object','properties': {'id': {'type':'string','enum':[u['id'] for u in units]},
                'kind': {'type':'string','enum':['narration','dialogue']}, 'speaker': {'type':'string'}},
                'required':['id','kind','speaker'],'additionalProperties':False}}}, 'required':['labels'],'additionalProperties':False}
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
        key = uuid.uuid4().hex
        settings = {'temperature':0,'seed':260909,'max_tokens':2048,'top_p':1,'frequency_penalty':0,'presence_penalty':0}
        def request(path, payload=None, timeout=180):
            req = urllib.request.Request(f'http://127.0.0.1:{port}'+path,
                data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        started = time.monotonic()
        with Path(log_path).open('w') as log:
            proc = subprocess.Popen([str(self.server),'-m',str(self.model),'--alias','role-draft','-ngl','all',
                '-c','8192','-np','1','--jinja','--reasoning','off','--host','127.0.0.1','--port',str(port),
                '--no-webui','--api-key',key],stdout=log,stderr=subprocess.STDOUT)
            try:
                for _ in range(300):
                    if proc.poll() is not None:
                        raise ValueError('本地分角色模型启动失败。')
                    try:
                        request('/health',timeout=1); break
                    except (OSError, urllib.error.URLError):
                        time.sleep(.2)
                else:
                    raise ValueError('本地分角色模型启动超时。')
                response = request('/v1/chat/completions', {**settings,'model':'role-draft',
                    'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps(
                        [{'id':u['id'],'text':u['text']} for u in units],ensure_ascii=False)}],
                    'response_format':{'type':'json_schema','json_schema':{'name':'speaker_segments','schema':schema}}})
                raw = response['choices'][0]['message']['content'] or ''
                bind_labels(text, raw)
                return {'labels':json.loads(raw)['labels'], 'raw_response':response, 'model_sha256':MODEL_SHA,
                        'settings':settings,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
                        'seconds_measured':time.monotonic()-started}
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()


def narration_name(language):
    return '旁白' if language == 'zh' else 'Narrator'


def carry_labels(segments, source, language):
    """Infer each new unit's kind and speaker from the segments already reviewed.

    Old segment texts are slices of old units, so a segment whose text still sits
    inside a new unit describes that unit. Anything genuinely new is left for the
    person: new narration resolves itself, new dialogue asks.
    """
    narrator = narration_name(language)
    known = [s for s in segments if s.get('text', '').strip()]
    labels = []
    for unit in source_units(source):
        speaker, kind = '', ''
        for old in known:
            text = old['text'].strip()
            if text and text in unit['text']:
                speaker = old['speaker']
                kind = old.get('kind') or ('narration' if speaker == narrator else 'dialogue')
                break
        if not kind:
            # Unseen text: a quoted unit needs a person, prose does not.
            kind = 'dialogue' if unit['text'][:1] in PAIRS else 'narration'
            speaker = 'UNKNOWN' if kind == 'dialogue' else narrator
        labels.append({'id': unit['id'], 'kind': kind, 'speaker': speaker})
    return labels


def carry_state(old_segments, new_segments):
    """Move generated audio and review state onto identical lines after a reslice.

    Matching is by (speaker, text) because that is what the audio fingerprint is
    built from: an unchanged line keeps its identity, its audio file and every
    check already performed on it. Nothing is deleted; unmatched audio simply
    stops being referenced and remains on disk.
    """
    pools = {}
    for old in old_segments:
        pools.setdefault((old['speaker'], old['text']), []).append(old)
    kept = kept_audio = fresh = 0
    for new in new_segments:
        pool = pools.get((new['speaker'], new['text']))
        if pool:
            old = pool.pop(0)
            carried = {k: v for k, v in old.items() if k not in ('source_start', 'source_end', 'kind')}
            new.update(carried)
            kept += 1
            kept_audio += bool(old.get('audio'))
        else:
            fresh += 1
    return new_segments, {'kept': kept, 'kept_audio': kept_audio, 'fresh': fresh}

# 最后更新：2026-09-10 · Astra／2026-09-10 · Claude Hera（新增重新切分的标签与状态承接）
