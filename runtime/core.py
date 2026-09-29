"""Atomic local projects, edit history and content-addressed audio. Astra, 2026-09-09."""
import copy
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from . import readings
from .project_settings import assert_raw, SETTING_KEYS, VIEW_KEY
from .pauses import split_at_pauses
from .capacity import draft_limits
from .audio import PROCESSING_VERSION
from .content_check import check_status, file_sha
from .listening import listening_status
from .tempo import edit_status
from .rhythm import VERSION as RHYTHM_VERSION
from .engines import VOICES, generation_parameters, reference_parameters
from .voices import custom_id

def uid():
    return uuid.uuid4().hex

def parse_script(script, language):
    if language not in ('zh','en'):
        raise ValueError('请选择中文或英文。')
    segments = []
    for number, line in enumerate(script.splitlines(), 1):
        if not line.strip():
            continue
        pieces = re.split('[:：]', line.strip(), maxsplit=1)
        if len(pieces) != 2 or not all(x.strip() for x in pieces):
            # Most people who land here pasted plain prose. Say so, and point
            # at the path that actually does what they wanted.
            raise ValueError(
                f'第 {number} 行没有角色名："{line.strip()[:20]}"。\n\n'
                '直接粘贴的原文需要每行写成「角色：台词」的形式。\n'
                '如果你手上是一段没有标注的小说或剧本，'
                '请改用「从原文生成角色草稿」，由程序先分好角色，再由你复核。')
        speaker, text = (x.strip() for x in pieces)
        limit = 60 if language == 'zh' else 240
        if len(speaker) > 80:
            raise ValueError(f'第 {number} 行的角色名太长（{len(speaker)} 字，上限 80 字）。'
                             '冒号前面只写角色名，台词写在冒号后面。')
        if len(text) > limit:
            raise ValueError(f'第 {number} 行太长（{len(text)} 字，上限 {limit} 字）。'
                             '请拆成几行，每行仍写成「角色：台词」。')
        segments.append({'id':uid(), 'speaker':speaker, 'text':text, 'spoken_as':'', 'audio':None, 'error':None})
    cap = draft_limits()['segments']
    if not 1 <= len(segments) <= cap:
        raise ValueError(f'一个工程需要 1–{cap} 行，当前 {len(segments)} 行。')
    return segments

def reads_aloud(segment, project=None):
    """Effective read state: a line may be silent itself, or its whole role may be muted."""
    if not segment.get('read_aloud', True):
        return False
    return project is None or segment.get('speaker') not in set(project.get('muted_speakers', []))


def split_segment(project, segment_id, at):
    """Cut one line in two at a code-point offset, in place, source untouched.

    The two halves take new ids and lose their audio (their text changed, so
    their fingerprints did). The right half keeps the pause that followed the
    original and is locked against being merged back; the left half gets no
    pause of its own, so splitting never inserts a gap that was not there.
    A replacement reading cannot be shared out between halves by position, so
    it is cleared and has to be typed again.
    """
    import unicodedata
    index = next((i for i, s in enumerate(project['segments']) if s['id'] == segment_id), None)
    if index is None:
        raise ValueError('找不到这一句。')
    original = project['segments'][index]
    text = original['text']
    if original.get('source_start') is None or original.get('source_end') is None:
        raise ValueError('这个工程没有记录原稿位置，无法原地拆分；可以在原稿编辑里重新切分。')
    if not 0 < at < len(text):
        raise ValueError('拆分位置必须在这一句内部。')
    if not text[:at].strip() or not text[at:].strip():
        raise ValueError('拆开的两半都要有文字。')
    # Never cut a character apart from a mark that belongs to it.
    if unicodedata.combining(text[at]) or text[at] in '\u200d\ufe0f' or text[at - 1] == '\u200d':
        raise ValueError('不能从一个字的中间拆开。')
    base = {k: v for k, v in original.items()
            if k not in ('id', 'text', 'source_start', 'source_end', 'audio', 'error', 'spoken_as',
                         'pause_after', 'lock_before', 'content_check', 'rhythm_check', 'tempo_edit',
                         'listening_issue', 'listening_status', 'take')}
    left = {**base, 'id': uid(), 'text': text[:at], 'spoken_as': '', 'audio': None, 'error': None,
            'source_start': original['source_start'], 'source_end': original['source_start'] + at,
            'lock_before': original.get('lock_before', False), 'pause_after': 0}
    right = {**base, 'id': uid(), 'text': text[at:], 'spoken_as': '', 'audio': None, 'error': None,
             'source_start': original['source_start'] + at, 'source_end': original['source_end'],
             'lock_before': True, 'pause_after': original.get('pause_after')}
    project['segments'][index:index + 1] = [left, right]
    return left, right


def merge_segments(project, segment_id, direction, language):
    """Join one line with its neighbour, in place, source untouched. The mirror
    of split_segment: the result takes a new id, loses its audio, keeps the
    earlier line's lock and the later line's pause, and clears a replacement
    reading that can no longer be trusted to cover both halves.
    """
    segments = project['segments']
    index = next((i for i, s in enumerate(segments) if s['id'] == segment_id), None)
    if index is None:
        raise ValueError('找不到这一句。')
    other = index + 1 if direction == 'next' else index - 1
    if not 0 <= other < len(segments):
        raise ValueError('这已经是最后一句，没有下一句可合并。' if direction == 'next' else '这已经是第一句，没有上一句可合并。')
    first, second = (segments[index], segments[other]) if direction == 'next' else (segments[other], segments[index])
    for s in (first, second):
        if s.get('source_start') is None or s.get('source_end') is None:
            raise ValueError('这个工程没有记录原稿位置，无法合并；可以在原稿编辑里重新切分。')
    if first['source_end'] != second['source_start']:
        raise ValueError('这两句在原稿里不相邻，不能合并。')
    if first['speaker'] != second['speaker']:
        raise ValueError(f'两句的说话人不同（{first["speaker"]} / {second["speaker"]}），先改成同一个人再合并。')
    if first.get('read_aloud', True) != second.get('read_aloud', True):
        raise ValueError('一句朗读、一句不朗读，不能合并。先把两句设成一样。')
    text = first['text'] + second['text']
    limit = 60 if language == 'zh' else 240
    if len(text) > limit:
        raise ValueError(f'合并后 {len(text)} 字，超过单句上限 {limit} 字。')
    base = {k: v for k, v in first.items()
            if k not in ('id', 'text', 'source_start', 'source_end', 'audio', 'error', 'spoken_as',
                         'pause_after', 'lock_before', 'content_check', 'rhythm_check', 'tempo_edit',
                         'listening_issue', 'listening_status', 'take')}
    merged = {**base, 'id': uid(), 'text': text, 'spoken_as': '', 'audio': None, 'error': None,
              'source_start': first['source_start'], 'source_end': second['source_end'],
              'lock_before': first.get('lock_before', False), 'pause_after': second.get('pause_after')}
    lo = min(index, other)
    segments[lo:lo + 2] = [merged]
    return merged


def spoken_source(project, segment):
    """The spoken text with the lexicon applied but readings still as notation —
    what the caveats are about."""
    text = segment.get('spoken_as') or segment['text']
    lexicon = {k: v for k, v in (project.get('lexicon') or {}).items() if k}
    if lexicon:
        pattern = re.compile('|'.join(re.escape(k) for k in sorted(lexicon, key=len, reverse=True)))
        text = pattern.sub(lambda m: lexicon[m.group(0)], text)
    return text


def spoken_text(project, segment):
    """What the voice is asked to read: the line, or its replacement reading,
    with the project's pronunciation lexicon applied.

    The lexicon is a project-wide table of written form -> read-as form, for
    the cases a per-line replacement handled one line at a time: the 1938
    edition's 偸 that the engine cannot read, eight times in Kong Yiji.
    Longest entries apply first so 偸儿 wins over 偸. Because this feeds the
    fingerprint, changing an entry invalidates exactly the lines it touches.

    A pinned reading — 干[gan4] in the replacement or in a lexicon entry —
    is resolved last, to a character that reads only that way (runtime/readings).
    """
    # The lexicon is one pass, longest match first at each position, and a
    # replacement is never scanned again: with 干净→干[gan1]净 and 干→干[gan4],
    # the 干 that the first entry wrote must not be rewritten by the second —
    # 擦拭干净 read as gàn gān 净 was the result of replacing in sequence.
    text = spoken_source(project, segment)
    try:
        return readings.resolve(text)
    except ValueError:
        return text                       # saving refuses bad notation; anything older is read as written


def voice_of(project, segment):
    """The voice a line is read in: its own, when a line carries one — a crowd
    line drawn from a pool — else its character's."""
    return segment.get('voice') or project['voices'][segment['speaker']]


def fingerprint(project, segment, engine, library=None):
    voice = voice_of(project, segment)
    data = {'text':spoken_text(project, segment), 'voice':voice,
            'language':project['language'], 'engine':(engine.identity_for(project.get('preset_model','0.6B')) if hasattr(engine,'identity_for') else engine.identity), 'seed':260909+segment.get('take',0),
            **generation_parameters(project['language']),
            'runtime':'mlx-audio-0.5.1', 'processing':PROCESSING_VERSION}
    from .chorus import is_chorus, chorus_mode, chorus_pool, chorus_layers, SHARED_TAKE_VERSION, LOOSE_MIX_VERSION
    if (is_chorus(voice) and chorus_mode(voice) == 'tight'
            and len(chorus_pool(voice)) == 1 and chorus_layers(voice) > 1):
        data['chorus_alignment'] = SHARED_TAKE_VERSION
    elif is_chorus(voice) and chorus_mode(voice) == 'loose':
        data['chorus_alignment'] = LOOSE_MIX_VERSION
    # The ellipsis pause reaches the fingerprint only where it changes the
    # reading — a line with a pause mark inside it — so switching it on
    # regenerates those lines and no others.
    gap = int(project.get('ellipsis_pause_ms') or 0)
    if gap and len(split_at_pauses(data['text'])) > 1:
        data['ellipsis_pause_ms'] = gap
    if segment.get('tone') and not custom_id(voice_of(project, segment)) and not (project.get('voice_profiles') or {}).get(segment['speaker']):
        data['tone'] = segment['tone']            # 语气 changes a preset take; a cloned voice ignores it, so its take is unchanged
    # A library voice is a reference like a fixed profile is, so its identity has
    # to reach the fingerprint: renaming may not invalidate audio, but pointing a
    # character at different reference audio must.
    voice_ref = custom_id(voice_of(project, segment))
    if voice_ref and library:
        entry = library.get(voice_ref)
        data.update(reference_parameters())
        data.update({'engine':(engine.reference_identity_for(project.get('clone_model','0.6B')) if hasattr(engine,'reference_identity_for') else getattr(engine,'reference_identity','unavailable')),
                     'reference_sha256':entry['sha256'],'reference_text':entry['reference_text'],
                     'mode':'library_reference-v1'})
    profile = project.get('voice_profiles',{}).get(segment['speaker'])
    if profile:
        data.update(reference_parameters())
        data.update({'engine':(engine.reference_identity_for(project.get('clone_model','0.6B')) if hasattr(engine,'reference_identity_for') else getattr(engine,'reference_identity','unavailable')),
                     'reference_sha256':profile['sha256'],'reference_text':profile['text'],
                     'mode':'fixed_synthetic_reference-v1'})
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

def drop_waveforms(project):
    """Strip the per-line waveform envelope that earlier versions stored with
    each rhythm check — in the live lines and in every undo snapshot. Returns
    whether anything was removed. The envelope is derived from the audio file
    and is recomputed by the preview endpoint when the timeline needs it."""
    removed = False
    states = [project] + list(project.get('history', [])) + list(project.get('future', []))
    for state in states:
        for segment in state.get('segments', []):
            check = segment.get('rhythm_check')
            if isinstance(check, dict) and 'waveform' in check:
                del check['waveform']; removed = True
    return removed


SETTINGS = ('lexicon', 'preset_model', 'clone_model', 'pause_ms', 'speech_rate', 'color_scope', 'ellipsis_pause_ms')


def inherit_settings(target, source, source_dir, target_dir):
    """Carry one project's configuration into another: the voice of every
    character both have, the fixed-voice references for those characters (the
    reference file is copied), the lexicon, the preset model, the pause and the
    speed. Characters the source does not have keep what they had. Returns
    what was carried, for the notice. Mutates target; the caller records the edit."""
    carried = {'voices': [], 'profiles': [], 'settings': []}
    for speaker in target['voices']:
        if speaker in source.get('voices', {}):
            target['voices'][speaker] = source['voices'][speaker]; carried['voices'].append(speaker)
        profile = (source.get('voice_profiles') or {}).get(speaker)
        if profile and source_dir and speaker in source.get('voices', {}):
            reference = Path(source_dir)/'references'/(profile['sha256'] + '.wav')
            if reference.is_file():
                folder = Path(target_dir)/'references'; folder.mkdir(exist_ok=True)
                if not (folder/reference.name).exists():
                    shutil.copyfile(reference, folder/reference.name)
                target.setdefault('voice_profiles', {})[speaker] = copy.deepcopy(profile); carried['profiles'].append(speaker)
    for key in SETTINGS:
        if key in source and source[key] != target.get(key):
            target[key] = copy.deepcopy(source[key]); carried['settings'].append(key)
    for speaker, color in (source.get('colors') or {}).items():
        if speaker in target['voices']:
            target.setdefault('colors', {})[speaker] = color
    for speaker, sex in (source.get('sexes') or {}).items():
        if speaker in target['voices']:
            target.setdefault('sexes', {})[speaker] = sex
    return carried


TEMPLATE_KEYS = ('voices', 'colors', 'sexes', 'color_scope', 'lexicon', 'preset_model', 'clone_model', 'pause_ms', 'speech_rate', 'ellipsis_pause_ms')


class Templates:
    """A project's configuration kept under a name, to apply to other projects:
    the voice of each character by name, colours, the lexicon, the model, the
    pause and the speed. Fixed-voice references belong to a project's own
    files and are not part of a template. Stored beside projects and books."""
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def create(self, name, project):
        name = (name or '').strip()[:60]
        if not name:
            raise ValueError('给模板起个名字。')
        template = {'id': uid(), 'name': name, 'created_at': time.time(), 'from_project': project['name'],
                    **{k: copy.deepcopy(project.get(k)) for k in TEMPLATE_KEYS if project.get(k) is not None}}
        (self.root/(template['id'] + '.json')).write_text(json.dumps(template, ensure_ascii=False, indent=1), encoding='utf-8')
        return template

    def get(self, template_id):
        path = self.root/(template_id + '.json')
        if not re.fullmatch(r'[0-9a-f]{32}', template_id) or not path.is_file():
            raise ValueError('找不到这个模板。')
        return json.loads(path.read_text(encoding='utf-8'))

    def list(self):
        out = []
        for path in sorted(self.root.glob('*.json'), key=lambda x: x.stat().st_mtime):
            t = json.loads(path.read_text(encoding='utf-8'))
            out.append({'id': t['id'], 'name': t['name'], 'from_project': t.get('from_project'),
                        'speakers': sorted(t.get('voices', {})), 'created_at': t.get('created_at')})
        return out

    def delete(self, template_id):
        self.get(template_id)
        (self.root/(template_id + '.json')).unlink()


def edit_state(project):
    if 'settings_schema' not in project:
        return copy.deepcopy({**{k:project[k] for k in ('name','language','voices','segments','pause_ms')},'lexicon':project.get('lexicon',{}),'preset_model':project.get('preset_model','0.6B'),'clone_model':project.get('clone_model','0.6B'),'voice_profiles':project.get('voice_profiles',{}), 'archived':project.get('archived',False), 'speech_rate':project.get('speech_rate',1.0), 'colors':project.get('colors',{}), 'color_scope':project.get('color_scope','both'), 'crowds':project.get('crowds',{}), 'sexes':project.get('sexes',{}), 'muted_speakers':project.get('muted_speakers',[]), 'ellipsis_pause_ms':project.get('ellipsis_pause_ms',0)})
    # New inherited projects retain only their explicit local overrides in an
    # undo snapshot. Parent values are resolved at request time and must never
    # be frozen into a chapter merely because its content was edited.
    keys = ('name', 'language', 'segments', 'source_script', 'archived', *SETTING_KEYS)
    state = {key: project[key] for key in keys if key in project}
    state['_settings_snapshot'] = [key for key in SETTING_KEYS if key in project]
    return copy.deepcopy(state)

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.library = None          # set by create_app; see runtime/voices.py
        self.resolver = None         # app supplies raw Project -> one effective read view
        for path in self.root.glob('*/project.json'):
            data = json.loads(path.read_text())
            if self.settle(data):
                self.write(data)

    @staticmethod
    def settle(data):
        """What every stored project goes through when it is loaded — older
        records brought to the current shape, a job cut off mid-run marked as
        such. The same for a project restored from a package, so an old package
        comes back like an old project on disk. Returns whether it changed."""
        changed = drop_waveforms(data)
        if data.get('job',{}).get('status') in ('queued', 'running'):
            data['job']['status'] = 'interrupted'; changed = True
        return changed

    def directory(self, project_id):
        if not re.fullmatch('[a-f0-9]{32}', project_id):
            raise ValueError('Invalid project ID')
        return self.root / project_id

    def read(self, project_id):
        p=json.loads((self.directory(project_id)/'project.json').read_text())
        p.setdefault('archived',False)
        # New inherited records stay raw: defaults here would become accidental
        # local overrides. The service adapter resolves an effective view.
        if 'settings_schema' not in p:
            p.setdefault('voice_profiles',{})
            p.setdefault('speech_rate',1.0)
            p.setdefault('muted_speakers',[])
        return p

    def write(self, data):
        assert_raw(data)
        # A chapter's empty role map of its own — `voices: {}` left behind by a
        # confirm that added nobody, a mute or a colour reset — would stand as an
        # explicit override and hide the book's whole map (本人 2026-09-22: the
        # narrator's voice set for the whole book never reached chapter 3). No
        # one asks for that; the empty map goes, the book's shows through.
        if data.get('settings_schema') == 1 and data.get('book'):
            for key in ('voices', 'colors', 'sexes', 'crowds', 'voice_profiles'):
                if key in data and data[key] == {}:
                    data.pop(key)
        guard = getattr(self, 'write_guard', None)
        if guard is not None:
            guard(data)
        path = self.directory(data['id'])
        path.mkdir(exist_ok=True)
        temporary = path / 'project.json.tmp'
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path / 'project.json')

    def create(self, name, script, language, *, segments=None, preset_model='0.6B', clone_model=None):
        if segments is None:
            segments = parse_script(script, language)
        presets = ['Vivian','Uncle_Fu','Serena','Dylan'] if language == 'zh' else ['Ryan','Aiden']
        voices = {s:presets[i%len(presets)] for i,s in enumerate(dict.fromkeys(x['speaker'] for x in segments))}
        data = {'schema_version':1, 'id':uid(), 'name':name.strip() or 'Untitled', 'language':language,
                'revision':0, 'source_script':script, 'voices':voices, 'segments':segments, 'pause_ms':250, 'preset_model':preset_model,
                'history':[], 'future':[], 'job':{'status':'idle'}, 'synthetic_audio':True}
        if clone_model:
            # The cloning model is written down at birth: a project made where the
            # 1.7B Base is installed keeps reading its cloned lines with it, and an
            # older project (no entry) stays on 0.6B, its audio still valid.
            data['clone_model'] = clone_model
        # A pause of a beat where a line trails off (本人 2026-09-17, chosen by
        # ear); older projects have no entry and read as before.
        data['ellipsis_pause_ms'] = 500
        self.write(data)
        return data

    def duplicate(self, project_id, revision):
        with self.lock:
            original=self.read(project_id)
            if original['revision']!=revision or original['job']['status']=='running':
                raise RuntimeError('工程已改变或正在处理，请重新载入后再复制。')
            source=self.directory(project_id)
            if source.is_symlink():raise ValueError('不能复制链接形式的工程目录。')
            data=copy.deepcopy(original)
            data.update(id=uid(),name=original['name'][:114]+' · 副本',revision=0,history=[],future=[],job={'status':'idle'},archived=False)
            target=self.directory(data['id']);target.mkdir()
            try:
                for folder in ('audio','references'):
                    src=source/folder
                    if not src.exists() and not src.is_symlink():continue
                    if src.is_symlink() or any(p.is_symlink() for p in src.rglob('*')):
                        raise ValueError('声音目录含链接，无法直接复制；请先使用普通本地文件。')
                    shutil.copytree(src,target/folder,copy_function=shutil.copy2)
                self.write(data)
            except BaseException:
                shutil.rmtree(target)
                raise
            return data

    def edit(self, project_id, revision, change, action='edit'):
        with self.lock:
            p = self.read(project_id)
            if p['revision'] != revision or p['job']['status'] == 'running':
                raise RuntimeError('工程已在其他窗口改变，或正在处理。请重新载入已保存版本后再编辑。')
            if action in ('undo','redo'):
                source, target = ('history','future') if action == 'undo' else ('future','history')
                if not p[source]:
                    return p
                p[target].append(edit_state(p))
                restored=p[source].pop()
                local_settings = restored.pop('_settings_snapshot', None)
                if local_settings is not None:
                    for key in SETTING_KEYS:
                        p.pop(key, None)
                else:
                    restored.setdefault('voice_profiles',{})
                    restored.setdefault('archived',False)
                    restored.setdefault('speech_rate',1.0)
                p.update(restored)
            else:
                before = edit_state(p)
                change(p)
                p['history'].append(before)
                p['history'] = p['history'][-40:]
                p['future'] = []
            p['revision'] += 1
            self.write(p)
            return p

    def delete(self, project_id, revision):
        """Remove an archived project for good: its lines, generated audio,
        exports and the references it fixed for its own characters. Library
        voices and books are kept elsewhere and are untouched. Archiving first
        is the deliberate step; deletion is the second one."""
        with self.lock:
            p = self.read(project_id)
            if p['revision'] != revision or p['job']['status'] == 'running':
                raise RuntimeError('工程已改变或正在处理，请重新载入后再删除。')
            if not p.get('archived'):
                raise ValueError('只能删除已归档的工程：先归档，确认不再需要，再删除。')
            guard = getattr(self, 'write_guard', None)
            if guard is not None:
                guard(p)
            directory = self.directory(project_id)
            if directory.is_symlink() or any(x.is_symlink() for x in directory.rglob('*')):
                raise ValueError('工程目录含有链接，为了不误删链接指向的文件，请手动处理。')
            shutil.rmtree(directory)

    def public(self, p, engine, checker=None, library=None):
        if p.get('settings_schema') is not None and VIEW_KEY not in p:
            if self.resolver is None:
                raise ValueError('新版工程读取前必须解析有效设置。')
            p = self.resolver(p)
        library = library or self.library
        # The undo stacks are the bulk of a long project and never leave the
        # server; copy everything else.
        result = copy.deepcopy({k: v for k, v in p.items() if k not in ('history', 'future')})
        result.setdefault('voice_profiles',{})
        result.setdefault('archived',False)
        result.setdefault('speech_rate',1.0)
        result.setdefault('muted_speakers',[])
        result['can_undo'], result['can_redo'] = bool(p['history']), bool(p['future'])
        result.pop('history', None); result.pop('future', None)
        for s in result['segments']:
            current = fingerprint(p, s, engine, library)
            audio = s.get('audio')
            s['status'] = 'failed' if s.get('error') else 'pending'
            if audio and audio['fingerprint'] == current and (self.directory(p['id'])/'audio'/(current+'.wav')).exists():
                s['status'] = 'ready'
            s.setdefault('read_aloud', True); s.setdefault('lock_before', False)
            if not reads_aloud(s, p):
                # A line kept in the script but not in the recording. Whatever
                # audio it had stays on disk for when the line or role is switched back on.
                s['status'] = 'silent'
            spoken = spoken_text(p,s)
            s['check_status']=check_status(s,current,getattr(checker,'identity',None),spoken)
            # What the voice is actually asked to read when that differs from
            # the field the person typed — a lexicon entry or 干[gan4] at work.
            s['reads_as'] = spoken if spoken != (s.get('spoken_as') or s['text']) else None
            s['reads_note'] = readings.caveats(spoken_source(p, s)) or None
            audio_stat=None
            if s['status']=='ready':
                stat=(self.directory(p['id'])/'audio'/(current+'.wav')).stat()
                audio_stat=[stat.st_size,stat.st_mtime_ns]
                if s.get('content_check') and s['content_check'].get('audio_stat')!=audio_stat:s['check_status']='stale'
            s['tempo_status']=edit_status(s,audio_stat) if s['status']=='ready' else ('stale' if s.get('tempo_edit') else 'none')
            rhythm=s.get('rhythm_check')
            s['rhythm_status']='not_checked'
            if rhythm:
                if (s['status']!='ready' or rhythm.get('source_fingerprint')!=current or rhythm.get('audio_stat')!=audio_stat
                    or rhythm.get('version')!=RHYTHM_VERSION or rhythm.get('expected_text')!=spoken_text(p,s)):s['rhythm_status']='stale'
                elif rhythm.get('error'):s['rhythm_status']='error'
                else:s['rhythm_status']=('confirmed' if rhythm.get('reviewed') else 'review') if rhythm.get('markers') else 'checked'
            # A replaced file can retain its size and mtime; confirmed checks bind bytes too.
            if s['status']=='ready' and any(s[key+'_status']=='confirmed' for key in ('check','rhythm')):
                digest=file_sha(self.directory(p['id'])/'audio'/(current+'.wav'))
                for status_key,check_key in (('check_status','content_check'),('rhythm_status','rhythm_check')):
                    if s[status_key]=='confirmed' and s[check_key].get('audio_sha256')!=digest:
                        s[status_key]='stale'
            s['listening_status']=listening_status(s,current,audio_stat,p.get('speech_rate',1.0),expected=spoken_text(p,s))
        return result

# 最后更新：2026-09-09 · Astra

# 最后更新：2026-09-11 · Astra（试听确认的节奏状态与文件绑定）
