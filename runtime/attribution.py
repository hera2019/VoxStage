"""Local role drafts; reuse evaluated prompt and source binding. Astra 2026-09-10."""
import hashlib
import json
import os
import re
from .capacity import draft_limits, estimate_role_tokens
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

# The models the role draft may run on. Each is a llama.cpp GGUF, pinned by
# SHA-256; the draft record says which one answered. The default is the one
# the attribution evaluation was run on. The second is a community
# "abliterated" fine-tune of the same base — its refusal behaviour removed,
# Apache-2.0 like the base — for manuscripts the base model answers with a
# draft of nothing (2026-09-14: 70 units, all NARRATOR). Its accuracy against
# the 20-scene evaluation is measured separately and recorded before it is
# recommended for anything.
# Two invented exchanges a person labelled, shown to the model as worked examples
# when it has no confirmed chapter of the same book to learn the convention from.
GENERIC_EXAMPLES = [
    {'units': [{'id': 'u0', 'text': '阿宁一进门，柜边的人都笑了，有的叫道：'}, {'id': 'u1', 'text': '“阿宁，你又来赖账？”'},
               {'id': 'u2', 'text': '阿宁涨红了脸，对柜里说：'}, {'id': 'u3', 'text': '“老板娘，我这就给。”'}, {'id': 'u4', 'text': '“给什么？上回的还没清。”'},
               {'id': 'u5', 'text': '“今天一起清。”'}, {'id': 'u6', 'text': '陈小雪头也不抬。他想：'}, {'id': 'u7', 'text': '“这老板娘，记性真好。”'}],
     'labels': [{'id': 'u0', 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True}, {'id': 'u1', 'kind': 'dialogue', 'speaker': 'UNKNOWN', 'certain': False},
                {'id': 'u2', 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True}, {'id': 'u3', 'kind': 'dialogue', 'speaker': '阿宁', 'certain': True},
                {'id': 'u4', 'kind': 'dialogue', 'speaker': '陈小雪', 'certain': True}, {'id': 'u5', 'kind': 'dialogue', 'speaker': '阿宁', 'certain': True},
                {'id': 'u6', 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True}, {'id': 'u7', 'kind': 'dialogue', 'speaker': '阿宁', 'certain': True}]},
    {'units': [{'id': 'u0', 'text': '王伯放下账本。'}, {'id': 'u1', 'text': '“小雪，这个月亏了。”'}, {'id': 'u2', 'text': '“亏多少？”'}, {'id': 'u3', 'text': '“三十块。”'},
               {'id': 'u4', 'text': '阿宁在旁边插嘴：'}, {'id': 'u5', 'text': '“王伯，猫吃掉的也算？”'}, {'id': 'u6', 'text': '“算，猫也是店里的。”'}, {'id': 'u7', 'text': '王伯说完，两个人都笑了。'}],
     'labels': [{'id': 'u0', 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True}, {'id': 'u1', 'kind': 'dialogue', 'speaker': '王伯', 'certain': True},
                {'id': 'u2', 'kind': 'dialogue', 'speaker': '陈小雪', 'certain': True}, {'id': 'u3', 'kind': 'dialogue', 'speaker': '王伯', 'certain': True},
                {'id': 'u4', 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True}, {'id': 'u5', 'kind': 'dialogue', 'speaker': '阿宁', 'certain': True},
                {'id': 'u6', 'kind': 'dialogue', 'speaker': '王伯', 'certain': True}, {'id': 'u7', 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True}]},
]


def book_examples(siblings, exclude_text, limit=2, max_chars=360):
    """Short confirmed exchanges from a book's other chapters — three or more
    lines of speech, two or more speakers, narration between — as worked
    examples. A sibling whose text is the passage being drafted is skipped."""
    out = []
    for p in siblings:
        if len(out) >= limit or p.get('source_script') == exclude_text:
            continue
        labels = {l['id']: l for l in (p.get('attribution') or {}).get('confirmed_labels') or []}
        units = [u for u in source_units(p['source_script'], p.get('cut')) if u['text'].strip()]
        for start in range(len(units)):
            window, chars, speakers, dialogue = [], 0, set(), 0
            for u in units[start:]:
                l = labels.get(u['id'])
                if not l or chars + len(u['text']) > max_chars:
                    break
                window.append((u, l)); chars += len(u['text'])
                if l['kind'] == 'dialogue' and l['speaker'].upper() not in ('', 'UNKNOWN'):
                    speakers.add(l['speaker']); dialogue += 1
                if dialogue >= 3 and len(speakers) >= 2 and any(x[1]['kind'] == 'narration' for x in window):
                    break
            if dialogue >= 3 and len(speakers) >= 2:
                out.append({'units': [{'id': f'u{i}', 'text': u['text'].strip()} for i, (u, l) in enumerate(window)],
                            'labels': [{'id': f'u{i}', 'kind': l['kind'], 'speaker': l['speaker'] if l['kind'] == 'dialogue' else 'NARRATOR', 'certain': True}
                                       for i, (u, l) in enumerate(window)]})
                break
    return out


ROLE_MODELS = {
    'qwen3-4b-instruct-2507-q8': {
        'label': 'Qwen3-4B-Instruct-2507 · Q8（评测过）',
        'sha256': MODEL_SHA, 'minimum_memory_gb': 8,
        'paths': [ROOT/'user-data/models/role-qwen3-4b/qwen3-4b-instruct-2507-q8_0.gguf',
                  ROOT.parent/'AI-Models/generators/qwen3-4b-instruct-2507/qwen3-4b-instruct-2507-q8_0.gguf']},
    'qwen3-4b-instruct-2507-abliterated-q8': {
        'label': 'Qwen3-4B-Instruct-2507 去审查版 · Q8（huihui-ai 微调）',
        'sha256': 'f3b6a790d226efadd863152415713d4d177a22e80eb37bc54537dab110062f31', 'minimum_memory_gb': 8,
        'paths': [ROOT/'user-data/models/role-qwen3-4b-abliterated/Huihui-Qwen3-4B-Instruct-2507-abliterated.Q8_0.gguf']},
    # Removed 2026-09-17 with the author's consent (「鸡肋」): the two Qwen3.5-9B
    # (slow, balked), the abliterated 14B (worse than the plain), the abliterated
    # 30B-A3B (worse both ways). Their measurements stay in the ai-lab notes.
    'qwen3-14b-q4km': {
        # Best of six on the fixed set (2026-09-16, ai-lab 实测 17): 16 lines to
        # fix across 215 against 28 for the next; twice the 4B's time. Recommended
        # where the memory allows it (32 GB: 9 GB weights + 5 GB of context).
        'label': 'Qwen3-14B 普通版 · Q4_K_M（Qwen 官方 GGUF）',
        'sha256': '500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0',
        'paths': [ROOT/'user-data/models/role-qwen3-14b/Qwen3-14B-Q4_K_M.gguf'],
        'recommended_gb': 32, 'minimum_memory_gb': 16},
    'qwen3-30b-a3b-instruct-2507-q4km': {
        # Attribution plan step 5 (Fable's suggestion, 2026-09-16): a mixture of
        # experts with 3B active — the speed of a small model with the knowledge
        # of a 30B. 18.6 GB of weights: on a 32 GB machine the context is capped
        # (推算: ~100 KB of cache per token; 20k tokens ≈ 2 GB). Measured
        # 2026-09-17 (ai-lab 实测 22): best and fastest on the public texts,
        # balks on a web-novel chapter with sensitive content — hence the fallback chain.
        'label': 'Qwen3-30B-A3B Instruct-2507 · Q4_K_M（unsloth GGUF）',
        'sha256': '6c997b8af17debdfb01d890214400ccbab00db6acc0ba8da5de1cc906c4774d0',
        'paths': [ROOT/'user-data/models/role-qwen3-30b-a3b/Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf'],
        # Conservative batch policy after the reported 151-unit ID mismatch.
        # Consumed by the upcoming batch adapter; not a measured accuracy guarantee.
        'max_units': 100, 'max_context': 20480, 'recommended_gb': 32, 'minimum_memory_gb': 24},
}
DEFAULT_ROLE_MODEL = 'qwen3-14b-q4km'          # the floor a machine of 32 GB starts on; VOXSTAGE_ROLE_MODEL points at its file
# The best model a machine can hold, of those installed, is what it starts
# on (本人 2026-09-17: 如果电脑配置够，30B 作默认 — ai-lab 实测 22: best and
# fastest on the public texts). A choice saved in settings overrides this.
PREFERRED_ROLE_MODELS = ('qwen3-30b-a3b-instruct-2507-q4km', 'qwen3-14b-q4km', 'qwen3-4b-instruct-2507-q8')
# When the chosen model hands in a draft of nothing, these are asked in turn
# (the first installed): the 14B answers the author's own manuscripts where
# the 30B balks (实测 22); the 4B abliteration never balked on the fixed set.
FALLBACK_ROLE_MODELS = ('qwen3-14b-q4km', 'qwen3-4b-instruct-2507-abliterated-q8')
FALLBACK_ROLE_MODEL = FALLBACK_ROLE_MODELS[-1]


def default_role_model():
    gb = draft_limits()['memory_gb']
    for m in PREFERRED_ROLE_MODELS:
        spec = ROLE_MODELS[m]
        if gb >= spec.get('recommended_gb', 0) - 0.5 and RoleDraftEngine.path_for(m):
            return m
    return DEFAULT_ROLE_MODEL


def project_segments(source, labels, language, locks=(), cut=None):
    # Validate IDs against preserved source, including duplicate/missing labels.
    bind_labels(source, json.dumps({'labels': labels}), cut)
    by_id = {x['id']: x for x in labels}
    pieces = []
    limit = 60 if language == 'zh' else 240
    for unit in source_units(source, cut):
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
                end = _cut_point(source, start, end, unit['end'], limit)
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
    if not 1 <= len(segments) <= draft_limits()['segments']:
        raise ValueError('原稿切片数量超出范围。')
    return segments


# Where a line may be cut, strongest first: the end of a sentence, then a
# semicolon / dash / ellipsis, then a clause, then a space.
CUT_TIERS = ('。！？.!?\n', '；;—–…', '，、,:：', ' \u3000')


def _cut_point(source, start, end, unit_end, limit):
    """Choose where a line longer than the limit is cut.

    Taking the last sentence end in the window, whatever its position, cut
    热热的喝了休息； off as an eight-character line because it was the only
    full stop in reach. A cut is chosen so that both the line it closes and
    what is left after it are of a reasonable length; among those, the
    strongest punctuation wins, and the later position breaks ties. Only when
    nothing satisfies the length rule does the old preference apply.
    """
    minimum = max(4, limit // 4)                       # 15 characters for Chinese
    candidates = []                                    # (tier, position)
    for tier, marks in enumerate(CUT_TIERS):
        candidates += [(tier, i + 1) for i in range(start, end) if source[i] in marks]
    if not candidates:
        return end
    def sound(position):
        remainder = unit_end - position
        return position - start >= minimum and (remainder == 0 or remainder >= minimum)
    good = [c for c in candidates if sound(c[1])]
    pool = good or candidates
    best_tier = min(tier for tier, _ in pool)
    return max(position for tier, position in pool if tier == best_tier)


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
        if piece['end'] <= piece['start']:
            continue                                    # nothing left of it (a lock landed on a line break)
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


def speaker_pattern(text):
    """What a speaker field may hold, enforced by the grammar llama-server builds
    from the schema: a name in the text's own script, or UNKNOWN / NARRATOR.
    Both models, told the cast in an English sentence, answered Kong Yiji in
    English (KONG YIJI, CHEEPA, SHORT-CLOTHED CUSTOMERS) and every name was
    refused; asking in the prompt did not hold, the grammar does. A Chinese
    text's name must contain a Chinese character (阿Q keeps its Q)."""
    if re.search('[一-鿿]', text):
        # At most one Latin character before the first Chinese one (A君, 阿Q
        # keeps its Q after): three let a model write CRO众 for "crowd".
        return '^([A-Za-z0-9·]?[一-鿿][一-鿿A-Za-z0-9·]{0,7}|UNKNOWN|NARRATOR)$'
    return "^([A-Za-z][A-Za-z .'\\-]{0,30}|UNKNOWN|NARRATOR)$"


class RoleDraftEngine:
    def __init__(self, model_id=None):
        self.server = Path(os.environ.get('VOXSTAGE_ROLE_SERVER', ROOT.parent/'AI-Lab/qwen3-14b-llamacpp/worktrees/llama.cpp/build-release-metal/bin/llama-server'))
        self.select(model_id or default_role_model())

    @staticmethod
    def path_for(model_id):
        """The installed file for a registered model, or None. VOXSTAGE_ROLE_MODEL
        overrides the default model's location, as it always has."""
        spec = ROLE_MODELS[model_id]
        candidates = list(spec['paths'])
        if model_id == DEFAULT_ROLE_MODEL and os.environ.get('VOXSTAGE_ROLE_MODEL'):
            candidates.insert(0, Path(os.environ['VOXSTAGE_ROLE_MODEL']))
        return next((p for p in candidates if p.is_file()), None)

    def installed(self):
        gb = draft_limits()['memory_gb']
        return [{'id': k, 'label': v['label'] + ('（本机推荐）' if v.get('recommended_gb') and gb >= v['recommended_gb'] - 0.5 else ''),
                 'installed': self.path_for(k) is not None,
                 'loadable': self.path_for(k) is not None and gb >= v.get('minimum_memory_gb', 0) - 0.5,
                 'minimum_memory_gb': v.get('minimum_memory_gb', 0),
                 'recommended': bool(v.get('recommended_gb') and gb >= v['recommended_gb'] - 0.5)} for k, v in ROLE_MODELS.items()]

    def select(self, model_id):
        if model_id not in ROLE_MODELS:
            raise ValueError('没有这个分角色模型。')
        self.model_id = model_id
        self.model = self.path_for(model_id) or ROLE_MODELS[model_id]['paths'][0]
        self.sha256 = ROLE_MODELS[model_id]['sha256']
        self.ready = self.model.is_file() and self.server.is_file()

    def annotate(self, text, log_path, known_names=(), examples=(), cut=None,
                 units_override=None, strict_ids=False, limits_override=None):
        if not self.ready:
            raise ValueError('本地分角色模型未就绪；仍可使用已标注剧本导入。')
        units = source_units(text, cut) if units_override is None else list(units_override)
        # Blank units — the line breaks between lines — are not the model's to
        # label; they are narration and are filled in below. Only the rest are
        # sent, counted against the limit, and required in the answer.
        spoken = [u for u in units if u['text'].strip()]
        limits = dict(limits_override or draft_limits())
        effective_context = min(limits['context'], ROLE_MODELS.get(self.model_id, {}).get('max_context', limits['context']))
        sent_chars = len(text) if units_override is None else sum(len(unit['text']) for unit in spoken)
        estimate = estimate_role_tokens(sent_chars, len(spoken), effective_context, limits['max_tokens'])
        if not spoken:
            raise ValueError('原稿里没有可以分析的片段。')
        if not estimate['fits']:
            raise ValueError(f"这段原稿预计需要约 {estimate['total']} tokens，当前安全预算是 {estimate['safe_total']}（{len(spoken)} 个片段）。请让自动分段先切开。")
        with self.model.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != self.sha256:
                raise ValueError('分角色模型校验不一致。')
        # Since 2026-09-14 the model gives its best judgement of every speaker
        # and says whether the passage settles it; an uncertain name reaches the
        # reviewer as a yellow, pre-filled suggestion rather than an empty field.
        # (The first prompt said "never guess", and on a chapter with almost no
        # speech tags that meant 37 empty fields out of 37.)
        prompt = (ROOT/'evals/speaker_attribution/prompt-anchored-guess.txt').read_text()
        if known_names:
            # A chapter that never spells a name still has the cast of the
            # earlier chapters; without this the model answers with descriptions
            # (姐姐, 男孩) instead of names.
            prompt += '\nCharacters already known from earlier chapters of this book: ' + '、'.join(known_names) + '. When one of them is the speaker, use that exact name.'
        if examples:
            # Worked examples — a person's own labels — show the convention better
            # than any rule in words: a tag names its speaker, an exchange
            # alternates, a crowd is UNKNOWN, a thought is its thinker's
            # (few-shot experiment, 2026-09-16).
            prompt += '\n\nWorked examples, labelled by a person. Same format as your answer:'
            for ex in examples:
                prompt += ('\nUnits: ' + json.dumps(ex['units'], ensure_ascii=False)
                           + '\nLabels: ' + json.dumps({'labels': ex['labels']}, ensure_ascii=False))
        schema = {'type':'object', 'properties': {'labels': {'type':'array', 'minItems':len(spoken), 'maxItems':len(spoken),
            'items': {'type':'object','properties': {'id': {'type':'string','enum':[u['id'] for u in spoken]},
                'kind': {'type':'string','enum':['narration','dialogue']}, 'speaker': {'type':'string', 'pattern': speaker_pattern(text)}, 'certain': {'type':'boolean'}},
                'required':['id','kind','speaker','certain'],'additionalProperties':False}}}, 'required':['labels'],'additionalProperties':False}
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
        key = uuid.uuid4().hex
        # 80 units × ~26 tokens each once the certain flag is in the answer:
        # 2,048 cut Kong Yiji's 68-unit answer off mid-JSON (本人 2026-09-15).
        settings = {'temperature':0,'seed':260909,'max_tokens':limits['max_tokens'],'top_p':1,'frequency_penalty':0,'presence_penalty':0}
        def request(path, payload=None, timeout=180):
            req = urllib.request.Request(f'http://127.0.0.1:{port}'+path,
                data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        started = time.monotonic()
        with Path(log_path).open('w') as log:
            launch = ROLE_MODELS.get(self.model_id, {}).get('launch') or ['--reasoning', 'off']   # a plain instruct model answers at once
            log.write(f'[VoxStage] model={self.model_id}\n')
            log.write(f'[VoxStage] chars={sent_chars} units={len(spoken)} context={effective_context} max_tokens={limits["max_tokens"]}\n')
            log.write(f'[VoxStage] estimated_prompt={estimate["prompt"]} estimated_completion={estimate["completion"]} estimated_total={estimate["total"]} safe_total={estimate["safe_total"]}\n')
            log.write(f'[VoxStage] model_file={self.model.name}\n')
            log.flush()
            proc = subprocess.Popen([str(self.server),'-m',str(self.model),'--alias','role-draft','-ngl','all',
                '-c',str(effective_context),'-np','1','--jinja',*launch,'--host','127.0.0.1','--port',str(port),
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
                        [{'id':u['id'],'text':u['text']} for u in spoken],ensure_ascii=False)}],
                    'response_format':{'type':'json_schema','json_schema':{'name':'speaker_segments','schema':schema}}})
                raw = response['choices'][0]['message']['content'] or ''
                usage = response.get('usage') or {}
                log.write(f'\n[VoxStage] finish_reason={response["choices"][0].get("finish_reason")} '
                          f'prompt_tokens={usage.get("prompt_tokens", "?")} completion_tokens={usage.get("completion_tokens", "?")} '
                          f'total_tokens={usage.get("total_tokens", "?")} elapsed={time.monotonic()-started:.2f}s\n')
                log.write('[VoxStage] model_response:\n' + raw + '\n')
                log.flush()
                if response['choices'][0].get('finish_reason') == 'length':
                    raise ValueError('模型的回答被截断了（超过输出上限）。请把原文分成两段再试。')
                # The answer covers the units that were sent; blank units are
                # narration. The schema fixes count and vocabulary but not
                # uniqueness: a long list sometimes comes back with an id repeated
                # and its neighbour skipped (seen 2026-09-14). The ids it wrote
                # are right; keep the first label per id and give a skipped unit
                # a label of its own — narration for an unquoted one, an unplaced
                # line for a quoted one — and say the answer was mended.
                parsed = json.loads(raw).get('labels') if raw else None
                if not isinstance(parsed, list):
                    raise ValueError('模型没有给出标签。')
                expected_ids = [unit['id'] for unit in spoken]
                parsed_ids = [row.get('id') for row in parsed if isinstance(row, dict)]
                if strict_ids and (len(parsed_ids) != len(parsed) or parsed_ids != expected_ids
                                   or len(parsed_ids) != len(set(parsed_ids))):
                    raise ValueError('本批标签缺号、重号或顺序与全局单元不一致。')
                first = {}
                for x in parsed:
                    if isinstance(x, dict):
                        first.setdefault(x.get('id'), x)
                repaired = None
                full = []
                for u in units:
                    if not u['text'].strip():
                        full.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True})
                    elif u['id'] in first:
                        full.append(first[u['id']])
                    elif u['text'].strip()[0] in '“"「『':
                        full.append({'id': u['id'], 'kind': 'dialogue', 'speaker': 'UNKNOWN', 'certain': False}); repaired = 'skipped_units_filled'
                    else:
                        full.append({'id': u['id'], 'kind': 'narration', 'speaker': 'NARRATOR', 'certain': True}); repaired = 'skipped_units_filled'
                if len(first) != len(parsed):
                    repaired = 'skipped_units_filled'
                raw = json.dumps({'labels': full}, ensure_ascii=False)
                if units_override is None:
                    bind_labels(text, raw, cut)
                elif [row.get('id') for row in full] != [unit['id'] for unit in units]:
                    raise ValueError('本批标签没有逐个绑定到请求单元。')
                labels = [{**x, 'speaker': tidy_speaker(x['speaker']), 'certain': bool(x.get('certain', True))} for x in json.loads(raw)['labels']]
                return {'labels':labels, 'raw_response':response, 'model_sha256':self.sha256, 'model_id':self.model_id,
                        'settings':settings,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
                        'repaired':repaired, 'seconds_measured':time.monotonic()-started}
            except Exception as exc:
                log.write(f'\n[VoxStage] ERROR {type(exc).__name__}: {exc}\n')
                log.flush()
                raise
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()


def narration_name(language):
    return '旁白' if language == 'zh' else 'Narrator'


def carry_labels(segments, source, language, cut=None):
    """Infer each new unit's kind and speaker from the segments already reviewed.

    Old segment texts are slices of old units, so a segment whose text still sits
    inside a new unit describes that unit. Anything genuinely new is left for the
    person: new narration resolves itself, new dialogue asks.
    """
    narrator = narration_name(language)
    known = [s for s in segments if s.get('text', '').strip()]
    labels = []
    for unit in source_units(source, cut):
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
