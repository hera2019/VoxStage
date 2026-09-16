"""Preset voices and authorized fixed synthetic references; no human uploads. Astra, 2026-09-09."""
import gc
import hashlib
import json
import time
from pathlib import Path
import numpy as np

VOICES = {'Vivian':'中文 · 明亮女声', 'Serena':'中文 · 温暖女声', 'Uncle_Fu':'中文 · 低沉男声',
          'Dylan':'中文 · 青年男声', 'Ryan':'English · male', 'Aiden':'English · warm male',
          'Ono_Anna':'日本語 · female', 'Sohee':'한국어 · female', 'Eric':'中文 · 四川口音'}

def generation_parameters(language):
    # Same-speaker listening preference (D24): Chinese B candidate only.
    # English remains unchanged; broader voice-quality acceptance is pending.
    return {'max_tokens':2048, 'temperature':0.6 if language == 'zh' else 0.9,
            'top_k':50, 'top_p':1.0, 'repetition_penalty':1.05}

BASE_ID = 'mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16@1eccf1cb2519b5a4e8a95b5f0544f3303568164f'
BASE_SHA = {'model.safetensors':'d7c7ed3e3464e3e59de0f955b3755891fa8319ff061c3f0307fe2e1343bc122d',
            'speech_tokenizer/model.safetensors':'836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258'}
# The larger cloning model (2026-09-16): every fixed or designed voice was read
# by the 0.6B Base whatever the project chose; this one is chosen per project
# (clone_model) so a switch is deliberate and its fingerprint is its own.
LARGE_BASE_ID = 'mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16@a6eb4f68e4b056f1215157bb696209bc82a6db48'
LARGE_BASE_SHA = {'model.safetensors':'81fb76175ff74e69be25fef2cc3e54f016df3034f1514c8e1c89da06a3510cff',
                  'speech_tokenizer/model.safetensors':BASE_SHA['speech_tokenizer/model.safetensors']}

def reference_parameters():
    return {'max_tokens':2048,'temperature':0.6,'top_k':50,'top_p':1.0,'repetition_penalty':1.5}

class FixtureEngine:
    identity = 'test-tone-fixture-v1'
    label = '测试音（不是语音）'
    ready = True
    def synthesize(self, text, voice, language, seed=260909):
        rate = 24000
        t = np.arange(rate//5, dtype=np.float32)/rate
        return np.r_[np.zeros(rate//20), .1*np.sin(t*2*np.pi*440), np.zeros(rate//20)], rate, {}

class MlxEngine:
    label = 'Qwen3 · 本地预设音色'
    reference_identity = BASE_ID
    def __init__(self, path, base_path=None, large_path=None, design_path=None):
        self.path = Path(path)
        self.model = None
        self.reference_model = None
        # An optional larger preset model beside the default, chosen per project.
        # Same nine voices, same code path; a different identity in the fingerprint.
        self.large_path = Path(large_path) if large_path else self.path.parent/'qwen-customvoice-1.7b'
        self.large_model = None
        self.large_identity = None
        if (self.large_path/'model.safetensors').is_file() and (self.large_path/'voxstage-model.json').is_file():
            provenance = json.loads((self.large_path/'voxstage-model.json').read_text())
            self.large_identity = provenance['repo'] + '@' + provenance['revision']
        # Voice design: a voice from a written description. Used to make a
        # reference that the library then keeps; never to read lines directly.
        self.design_path = Path(design_path) if design_path else self.path.parent/'qwen-voicedesign-1.7b'
        self.design_model = None
        self.design_identity = None
        if (self.design_path/'model.safetensors').is_file() and (self.design_path/'voxstage-model.json').is_file():
            provenance = json.loads((self.design_path/'voxstage-model.json').read_text())
            self.design_identity = provenance['repo'] + '@' + provenance['revision']

        self.base_path = Path(base_path or self.path.parent/'qwen-base')
        self.reference_ready = all((self.base_path/name).is_file() for name in BASE_SHA)
        self.base_verified = False
        self.large_base_path = self.path.parent/'qwen-base-1.7b'
        self.large_reference_ready = all((self.large_base_path/name).is_file() for name in LARGE_BASE_SHA)
        self.large_base_verified = False
        self.large_reference_model = None
        self.ready = (self.path/'model.safetensors').is_file() and (self.path/'voxstage-model.json').is_file()
        self.identity = 'qwen3-customvoice-unconfigured'
        if self.ready:
            provenance = json.loads((self.path/'voxstage-model.json').read_text())
            self.identity = provenance['repo'] + '@' + provenance['revision']

    @property
    def design_ready(self):
        return bool(self.design_identity)

    def design_voice(self, text, description, language, seed=260909):
        """Render one sample of a voice described in words."""
        if not self.design_identity:
            raise ValueError('声音设计模型未安装。')
        if not description.strip():
            raise ValueError('请先描述这个声音。')
        import mlx.core as mx
        from mlx_audio.tts.utils import load_model
        start = time.perf_counter()
        if self.design_model is None:
            gc.collect(); mx.clear_cache()
            self.design_model = load_model(str(self.design_path))
        loaded = time.perf_counter()
        mx.random.seed(seed); mx.reset_peak_memory()
        results = list(self.design_model.generate(text=text, lang_code={'zh':'Chinese','en':'English'}[language],
                                                  instruct=description.strip(), stream=False))
        if not results or len({int(x.sample_rate) for x in results}) != 1:
            raise ValueError('声音设计没有产生有效音频，请换一种描述再试。')
        pcm = np.concatenate([np.asarray(x.audio, dtype=np.float32).reshape(-1) for x in results])
        return pcm, int(results[0].sample_rate), {'load_seconds':loaded-start, 'generation_seconds':time.perf_counter()-loaded,
                'mlx_peak_memory_bytes':mx.get_peak_memory(), 'seed':seed, 'generation_mode':'voice_design',
                'design_identity':self.design_identity, 'description':description.strip()}
    def identity_for(self, size='0.6B'):
        return self.large_identity if size == '1.7B' and self.large_identity else self.identity

    def synthesize(self, text, voice, language, seed=260909, size='0.6B'):
        if not self.ready:
            raise ValueError('Preset-voice model is not installed. Run the model setup command first.')
        if size == '1.7B' and not self.large_identity:
            raise ValueError('1.7B 预设模型未安装。')
        import mlx.core as mx
        from mlx_audio.tts.utils import load_model
        start = time.perf_counter()
        # Every variant stays resident once loaded. Evicting one to load
        # another cost 25 reloads across the 92 lines of Kong Yiji, because
        # preset and cloned voices alternate line by line; weights are 1.5 GB
        # (0.6B) and 3.4 GB (1.7B).
        if size == '1.7B':
            if self.large_model is None:
                gc.collect(); mx.clear_cache()
                self.large_model = load_model(str(self.large_path))
            model = self.large_model
        else:
            if self.model is None:
                gc.collect(); mx.clear_cache()
                self.model = load_model(str(self.path))
            model = self.model
        loaded = time.perf_counter()
        mx.random.seed(seed)
        mx.reset_peak_memory()
        parameters = generation_parameters(language)
        results = list(model.generate_custom_voice(text=text, speaker=voice,
                       language={'zh':'Chinese','en':'English'}[language], **parameters))
        if not results:
            raise ValueError('Model returned no audio')
        rates = {int(x.sample_rate) for x in results}
        if len(rates) != 1:
            raise ValueError('Model returned mixed sample rates')
        audio = np.concatenate([np.asarray(x.audio, dtype=np.float32).reshape(-1) for x in results])
        return audio, rates.pop(), {'load_seconds':loaded-start,
                'generation_seconds':time.perf_counter()-loaded,
                'mlx_peak_memory_bytes':mx.get_peak_memory(), 'seed':seed,
                'generation_parameters':parameters}


    def reference_identity_for(self, size='0.6B'):
        return LARGE_BASE_ID if size == '1.7B' else BASE_ID

    def synthesize_reference(self, text, language, reference_path, reference_text, seed,
                             *, consent_confirmed=False, expected_sha256=None, size='0.6B'):
        """Only server-selected, preserved synthetic references; D29. Astra 2026-09-09.
        `size` picks the cloning model: 0.6B (the default) or the 1.7B Base."""
        if not consent_confirmed or not expected_sha256:
            raise ValueError('固定声线需要已确认的合成参考声音。')
        with Path(reference_path).open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=expected_sha256:
                raise ValueError('固定声线参考文件已改变，请恢复原文件或重新选择声线。')
        large = size == '1.7B'
        if large and not self.large_reference_ready:
            raise ValueError('1.7B 固定声线模型未安装（scripts/setup_model.py --model base-large）。')
        if not large and not self.reference_ready:
            raise ValueError('固定声线模型未安装。')
        path = self.large_base_path if large else self.base_path
        if not (self.large_base_verified if large else self.base_verified):
            for name,expected in (LARGE_BASE_SHA if large else BASE_SHA).items():
                with (path/name).open('rb') as f:
                    if hashlib.file_digest(f,'sha256').hexdigest()!=expected:
                        raise ValueError('固定声线模型校验失败。')
            if large: self.large_base_verified=True
            else: self.base_verified=True
        import mlx.core as mx
        from mlx_audio.tts.utils import load_model
        start=time.perf_counter()
        if large and self.large_reference_model is None:
            gc.collect(); mx.clear_cache()
            self.large_reference_model=load_model(str(path))
        if not large and self.reference_model is None:
            gc.collect(); mx.clear_cache()
            self.reference_model=load_model(str(path))
        model = self.large_reference_model if large else self.reference_model
        loaded=time.perf_counter()
        # Bound reference-code cache; authoritative identity is the SHA-256 in the project.
        model._icl_cache.clear()
        mx.random.seed(seed);mx.reset_peak_memory()
        parameters=reference_parameters()
        results=list(model.generate(text=text,lang_code={'zh':'Chinese','en':'English'}[language],
            ref_audio=str(reference_path),ref_text=reference_text,stream=False,**parameters))
        if not results or len({int(x.sample_rate) for x in results})!=1:
            raise ValueError('固定声线生成结果无效。')
        pcm=np.concatenate([np.asarray(x.audio,dtype=np.float32).reshape(-1) for x in results])
        return pcm,int(results[0].sample_rate),{'load_seconds':loaded-start,
            'generation_seconds':time.perf_counter()-loaded,'mlx_peak_memory_bytes':mx.get_peak_memory(),
            'seed':seed,'generation_parameters':parameters,'reference_sha256':expected_sha256,
            'generation_mode':'fixed_synthetic_reference'}


    def unload(self):
        """Release synthesis models before the serial transcription job. Astra, 2026-09-09."""
        if self.model is not None or self.reference_model is not None or self.large_model is not None or self.design_model is not None or self.large_reference_model is not None:
            self.model=None;self.reference_model=None;self.large_model=None;self.design_model=None;self.large_reference_model=None
            gc.collect()
            import mlx.core as mx
            mx.clear_cache()
