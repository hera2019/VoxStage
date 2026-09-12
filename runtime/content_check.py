"""Local transcription and conservative text differences. Astra, 2026-09-09."""
import difflib
import hashlib
import json
import math
import re
import subprocess
import time
import unicodedata
import uuid
from pathlib import Path

NORMALIZATION_VERSION = 'spoken-units-v6-period-particles'
from .phonetics import chinese_keys
from .numbers import numeric_spans, BASIS as NUMBER_BASIS, NOTICE as NUMBER_NOTICE
DECODING = {'beam_size':5,'best_of':5,'temperature':0,'temperature_inc':0,'max_context':0,'no_fallback':True,'threads':4,'timing':'max-len-1-full-json-v1'}

def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

def text_units(text, language):
    text=unicodedata.normalize('NFKC',text).casefold().replace('’',"'")
    if language=='en':
        # Retain negations, decimal numbers and meaningful symbols; ignore layout/punctuation.
        return re.findall(r"\d+(?:[.,]\d+)*|[^\W\d_]+(?:'[^\W\d_]+)*|[%$€¥+−=\-]",text)
    return [c for i,c in enumerate(text) if unicodedata.category(c)[0] in 'LNMS' or c in '%-'
            or (c in '.,:/' and i>0 and i+1<len(text) and text[i-1].isdigit() and text[i+1].isdigit())]

def comparison_side(text, language):
    units=text_units(text,language)
    if language!='zh':return units,units
    keys=chinese_keys(units)
    normalized=unicodedata.normalize('NFKC',text).casefold().replace('’',"'")
    # ASR timed chunks may split a digit run across whitespace (3\n20).
    # Chinese text_units already ignores whitespace; keep the same comparison view.
    normalized=re.sub(r'\s+','',normalized)
    spans={}
    for start,end,value in numeric_spans(normalized):
        a=len(text_units(normalized[:start],language))
        b=a+len(text_units(normalized[start:end],language))
        spans[a]=(b,value)
    grouped,grouped_keys=[],[]
    i=0
    while i<len(units):
        if i in spans:
            end,value=spans[i]
            grouped.append(''.join(units[i:end]));grouped_keys.append((NUMBER_BASIS,value));i=end
        else:
            grouped.append(units[i]);grouped_keys.append(keys[i]);i+=1
    return grouped,grouped_keys


NAME_BASIS = '人名'
PERIOD_BASIS = '旧白话'
# Sentence particles as written a century ago and as a recogniser writes them
# today. The voice reads the meaning either way; only the spelling differs.
PERIOD_PARTICLES = {'么': '吗', '罢': '吧', '麽': '吗'}


def _toneless(text):
    from pypinyin import lazy_pinyin, Style
    return ''.join(lazy_pinyin(text, style=Style.NORMAL, errors=lambda v: list(v)))


def _is_name_slip(expected_span, recognized_span, names):
    """A recogniser cannot know a character's name; it writes whatever common
    characters share the sound. When the differing text lies inside a known name
    and the recognised text reads the same without tones, that is what happened.
    Tones are ignored because 乙 (yǐ) comes back as 一 (yī) every time; a
    different syllable altogether — 己 (jǐ) heard as 姐 (jiě) — still reports.
    """
    span = expected_span.strip()
    if not span or not any(span in name for name in names if name):
        return False
    return _toneless(span) == _toneless(recognized_span.strip())


def compare_text(expected, recognized, language, names=()):
    left,keys_left=comparison_side(expected,language)
    right,keys_right=comparison_side(recognized,language)
    joiner=' ' if language=='en' else ''
    changes=[];equivalences=[]
    for kind,a,b,c,d in difflib.SequenceMatcher(a=keys_left,b=keys_right,autojunk=False).get_opcodes():
        if kind=='equal':
            for i,j in zip(range(a,b),range(c,d)):
                if left[i]!=right[j]:equivalences.append({'expected':left[i],'recognized':right[j],'basis':keys_left[i][0]})
        if kind!='equal':
            # Recognisers split and join English words unpredictably ("Netherfield"
            # comes back as "Nether field"). Identical letters in a different
            # arrangement of words is a segmentation artefact, not a misreading.
            if language=='en' and ''.join(left[a:b])==''.join(right[c:d]) and left[a:b]:
                equivalences.append({'expected':joiner.join(left[a:b]),
                                     'recognized':joiner.join(right[c:d]),'basis':'word-boundary'})
            elif language=='zh' and kind=='replace' and _is_name_slip(joiner.join(left[a:b]),joiner.join(right[c:d]),names):
                equivalences.append({'expected':joiner.join(left[a:b]),
                                     'recognized':joiner.join(right[c:d]),'basis':NAME_BASIS})
            elif (language=='zh' and kind=='replace' and b-a==1 and d-c==1
                  and PERIOD_PARTICLES.get(left[a])==right[c]):
                equivalences.append({'expected':left[a],'recognized':right[c],'basis':PERIOD_BASIS})
            else:
                changes.append({'kind':kind,'expected':joiner.join(left[a:b]),'recognized':joiner.join(right[c:d])})
    return {'status':'match' if left and not changes else 'review','expected_text':expected,
            'recognized_text':recognized,'differences':changes,'equivalences':equivalences,'normalization':NORMALIZATION_VERSION,
            'compatibility_notices':[NUMBER_NOTICE] if any(e['basis']==NUMBER_BASIS for e in equivalences) else []}

def check_status(segment, current_fingerprint, checker_id):
    check=segment.get('content_check')
    if not check:return 'not_checked'
    if (segment.get('status')!='ready' or check.get('source_fingerprint')!=current_fingerprint
        or check.get('expected_text')!=(segment.get('spoken_as') or segment['text'])
        or check.get('checker_id')!=checker_id):return 'stale'
    if check['status']=='review' and check.get('reviewed'):return 'confirmed'
    return check['status']

class WhisperChecker:
    def __init__(self, settings_file):
        self.ready=False;self.identity='whisper-not-configured';self.verified_signature=None
        path=Path(settings_file)
        if not path.exists():return
        settings=json.loads(path.read_text())
        self.cli=Path(settings['cli']);self.model=Path(settings['model'])
        provenance_path=self.model.parent/'provenance.json'
        if not self.cli.is_file() or not self.model.is_file() or not provenance_path.is_file():return
        self.provenance=json.loads(provenance_path.read_text())
        self.identity='whisper.cpp:'+file_sha(self.cli)+':'+self.provenance['sha256']+':'+hashlib.sha256(json.dumps(DECODING,sort_keys=True).encode()).hexdigest()+':'+NORMALIZATION_VERSION
        self.ready=True

    def transcribe(self, audio_file, language, work_root):
        if not self.ready:raise ValueError('本地文字检查模型未就绪。')
        signature=(self.model.stat().st_size,self.model.stat().st_mtime_ns)
        if signature!=self.verified_signature:
            if file_sha(self.model)!=self.provenance['sha256']:raise ValueError('识别模型校验失败。')
            self.verified_signature=signature
        import numpy as np
        import soundfile as sf
        from scipy.signal import resample_poly
        pcm,rate=sf.read(audio_file,dtype='float32')
        if pcm.ndim!=1 or not len(pcm) or not np.isfinite(pcm).all():raise ValueError('音频无法检查。')
        folder=Path(work_root)/uuid.uuid4().hex;folder.mkdir(parents=True)
        divisor=math.gcd(rate,16000)
        pcm=resample_poly(pcm,16000//divisor,rate//divisor)
        source=folder/'input.wav';sf.write(source,pcm,16000,subtype='PCM_16')
        out=folder/'transcript'
        # Deliberately do not supply expected script text or carry context between sentences.
        command=[str(self.cli),'--model',str(self.model),'--file',str(source),'--language',language,
                 '--threads','4','--best-of','5','--beam-size','5','--max-context','0','--temperature','0','--temperature-inc','0',
                 '--no-fallback','--max-len','1','--output-txt','--output-json-full','--output-file',str(out)]
        started=time.perf_counter()
        try:
            process=subprocess.run(command,capture_output=True,text=True,timeout=120)
        except subprocess.TimeoutExpired as exc:
            (folder/'run.log').write_text('Transcription timed out after 120 seconds.')
            raise ValueError('本句文字检查超时，可以重试。') from exc
        (folder/'run.log').write_text(process.stdout+process.stderr)
        if process.returncode or not out.with_suffix('.txt').exists():raise ValueError('本句识别失败，请重试；详细信息已保存在本地。')
        timing=[]
        if out.with_suffix('.json').exists():
            for part in json.loads(out.with_suffix('.json').read_text()).get('transcription',[]):
                offsets=part.get('offsets',{})
                if part.get('text','').strip() and 'from' in offsets and 'to' in offsets:
                    timing.append({'text':part['text'],'start':offsets['from']/1000,'end':offsets['to']/1000})
        return {'timed_text':timing,'recognized_text':out.with_suffix('.txt').read_text().strip(),
                'seconds':time.perf_counter()-started,'model':self.provenance,'decoding':DECODING,
                'log_id':folder.name,'audio_sha256':file_sha(audio_file)}

# 最后更新：2026-09-09 · Astra

# 最后更新：2026-09-11 · Astra（可见的中文数字写法兼容）
