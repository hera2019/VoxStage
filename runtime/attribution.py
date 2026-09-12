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


def project_segments(source, labels, language, locks=()):
    # Validate IDs against preserved source, including duplicate/missing labels.
    bind_labels(source, json.dumps({'labels': labels}))
    by_id = {x['id']: x for x in labels}
    pieces = []
    limit = 60 if language == 'zh' else 240
    for unit in source_units(source):
        label = by_id[unit['id']]
        speaker = label['speaker'].strip()
        if label['kind'] == 'narration':
            speaker = '旁白' if language == 'zh' else 'Narrator'
        if not speaker or speaker.upper() == 'UNKNOWN' or len(speaker) > 80 or '\n' in speaker:
            raise ValueError('请为所有未识别片段填写角色名称。')
        start = unit['start']
        locked = sorted(x for x in locks if unit['start'] < x < unit['end'])
        while start < unit['end']:
            end = min(start + limit, unit['end'])
            # A boundary someone cut by hand is honoured before any other rule.
            ahead = [x for x in locked if start < x <= end]
            if ahead:
                end = ahead[0]
            # Prefer an existing sentence boundary; never ask the model to rewrite.
            elif end < unit['end']:
                # Prefer a sentence break; fall back to a clause, then a space.
                # A cut at the character limit lands mid-phrase, which both reads
                # badly and leaves a stranded fragment to synthesise on its own.
                for marks in ('。！？；.!?;\n', '，、,:—–', ' \u3000'):
                    boundaries = [i+1 for i in range(start, end) if source[i] in marks]
                    if boundaries:
                        end = boundaries[-1]
                        break
            pieces.append({'speaker': speaker, 'kind': label['kind'], 'start': start, 'end': end})
            start = end
    # Merging is capped below the slicing limit on purpose. A segment is two
    # things at once: a synthesis unit, which wants to be long enough to read
    # naturally, and a subtitle cue, which has to be short enough to read on
    # screen. Merging up to the full slicing limit produced a 58-character cue
    # held for 12 seconds. Two thirds of the limit still repairs a stranded
    # quoted fragment without building a cue nobody can read.
    segments = merge_adjacent(_tidy(source, pieces, locks), limit * 2 // 3, locks)
    for s in segments:
        s['lock_before'] = s['source_start'] in locks
    if not 1 <= len(segments) <= 500:
        raise ValueError('原稿切片数量超出范围。')
    return segments


def merge_adjacent(segments, limit, locks=()):
    """Only during explicit import/reslicing; retain exact source spans.

    A boundary in `locks` was cut by hand and is never merged across.
    """
    merged=[]
    for segment in segments:
        previous=merged[-1] if merged else None
        if (previous and previous['speaker']==segment['speaker'] and previous['kind']==segment['kind']
            and previous['source_end']==segment['source_start']
            and segment['source_start'] not in locks
            and len(previous['text'])+len(segment['text'])<=limit):
            previous['text']+=segment['text']
            previous['source_end']=segment['source_end']
        else:
            merged.append(dict(segment))
    return merged


# Punctuation that closes the sentence before it, plus whitespace. A slice must
# never begin with these: after a closing quote the following comma or full stop
# belongs to the line just spoken, and a subtitle should not open with it.
TRAILING = '。！？，、；：…·．!?,;:. \t\n\r\u3000'


def _tidy(source, pieces, locks=()):
    """Attach orphaned punctuation and blank runs to the line they belong to.

    Character coverage is unchanged: every index in the source still appears in
    exactly one segment, so the project keeps reconstructing the script exactly.
    A boundary in `locks` was cut by hand: nothing moves across it.
    """
    kept = []
    for piece in pieces:
        text = source[piece['start']:piece['end']]
        moved = len(text) - len(text.lstrip(TRAILING))
        if moved and kept and piece['start'] not in locks:
            kept[-1]['end'] = piece['start'] + moved
            piece = {**piece, 'start': piece['start'] + moved}
        if source[piece['start']:piece['end']].strip() or piece['start'] in locks:
            kept.append(dict(piece))
        elif kept:
            kept[-1]['end'] = piece['end']          # blank run joins the line before
        elif piece['end'] > piece['start']:
            kept.append(dict(piece))                # nothing before it yet; keep as is
    for a, b in zip(kept, kept[1:]):
        b['start'] = a['end']                       # no gaps, no overlaps
    return [{'id': uuid.uuid4().hex, 'speaker': x['speaker'], 'text': source[x['start']:x['end']],
             'spoken_as': '', 'audio': None, 'error': None, 'kind': x['kind'],
             'source_start': x['start'], 'source_end': x['end']} for x in kept]


# Speech verbs the draft model sometimes keeps attached to a name: it returned
# 众人都道 for a line introduced by 众人都道：. Longest first, and only trimmed
# when at least two characters remain, so a character actually called 张道 or
# 老问 keeps their name. The reviewer sees and can override the result either way.
SPEECH_VERBS = ('都笑道', '都笑说', '接口道', '连忙道', '忙笑道', '都道', '笑道', '说道',
                '答道', '问道', '回道', '叹道', '喝道', '骂道', '因说', '因道', '笑说',
                '道', '说', '问', '答')


def tidy_speaker(name):
    """Drop a trailing speech verb from a drafted character name."""
    name = (name or '').strip()
    for verb in SPEECH_VERBS:
        if name.endswith(verb) and len(name) - len(verb) >= 2:
            return name[:-len(verb)].strip()
    return name


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
                labels = [{**x, 'speaker': tidy_speaker(x['speaker'])} for x in json.loads(raw)['labels']]
                return {'labels':labels, 'raw_response':response, 'model_sha256':MODEL_SHA,
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
            start,end=old.get('source_start'),old.get('source_end')
            if (isinstance(start,int) and isinstance(end,int) and start<=unit['start']<unit['end']<=end
                and source[start:end]==old['text']):
                speaker=old['speaker']
                kind=old.get('kind') or ('narration' if speaker==narrator else 'dialogue')
                break
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


def carry_locks(segments, source):
    """Where the boundaries someone cut by hand fall in a possibly edited source.

    A lock belongs to the segment that starts at it. If that segment's text is
    still in the source, in order, the lock moves with it; if the text is gone,
    so is the lock. Never guessed from offsets alone, which shift under edits.
    """
    locks, cursor = set(), 0
    for s in segments:
        if not s.get('lock_before'):
            continue
        text = s.get('text', '')
        if not text.strip():
            continue
        at = source.find(text, cursor)
        if at < 0:
            continue
        locks.add(at)
        cursor = at + len(text)
    return locks


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
            carried = {k: v for k, v in old.items() if k not in ('source_start', 'source_end', 'kind', 'lock_before')}
            new.update(carried)
            kept += 1
            kept_audio += bool(old.get('audio'))
        else:
            fresh += 1
    return new_segments, {'kept': kept, 'kept_audio': kept_audio, 'fresh': fresh}

# 最后更新：2026-09-10 · Astra／2026-09-10 · Claude Hera（新增重新切分的标签与状态承接）

# 最后更新：2026-09-11 · Astra（显式导入与重新切分时合并同角色同类型片段）
