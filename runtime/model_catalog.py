"""The installer only accepts these pinned models; never client-supplied URLs."""
from scripts.setup_model import MODELS
from scripts import setup_asr

# Decimal GB estimates for the offline picker; Hub metadata replaces them during download.
DETAILS = {
    'preset': ('Qwen3-TTS 0.6B CustomVoice', '内置音色朗读；最低套必需。', 1.8, 8),
    'base': ('Qwen3-TTS 0.6B Base', '固定声线与参考录音克隆。', 1.8, 8),
    'preset-large': ('Qwen3-TTS 1.7B CustomVoice', '较大的内置音色朗读模型。', 4.5, 16),
    'base-large': ('Qwen3-TTS 1.7B Base', '较大的固定声线与克隆模型。', 4.5, 16),
    'design': ('Qwen3-TTS 1.7B VoiceDesign', '用文字描述创建声线；可选。', 4.5, 16),
    'role-abliterated': ('Qwen3-4B Instruct-2507 · Q8 · huihui 微调', '轻量分角色；社区微调版。', 4.3, 8),
    'role-14b': ('Qwen3-14B · Q4_K_M', '分角色；推荐套的备用选择。', 9.0, 16),
    'role-30b-a3b': ('Qwen3-30B-A3B Instruct-2507 · Q4_K_M', '分角色；适合 32 GB 及以上。', 18.6, 24),
    'asr': ('Whisper large-v3-turbo · Q5', '检查合成文字；还需要本地识别程序。', 0.6, 8),
}
ROLE_IDS = {'role-abliterated': 'qwen3-4b-instruct-2507-abliterated-q8',
            'role-14b': 'qwen3-14b-q4km', 'role-30b-a3b': 'qwen3-30b-a3b-instruct-2507-q4km'}
CATALOG = {kind: dict(spec, title=DETAILS[kind][0], purpose=DETAILS[kind][1],
                      estimated_bytes=int(DETAILS[kind][2]*1e9), minimum_gb=DETAILS[kind][3])
           for kind, spec in MODELS.items()}
CATALOG['asr'] = dict(folder='asr', repo=setup_asr.REPO, revision=setup_asr.REVISION,
                      sha256={setup_asr.NAME: setup_asr.SHA}, gguf=True,
                      title=DETAILS['asr'][0], purpose=DETAILS['asr'][1],
                      estimated_bytes=int(0.6e9), minimum_gb=8)


def recommended(gb):
    minimum = ['preset', 'base', 'role-abliterated']
    return minimum + ['preset-large', 'base-large', 'role-30b-a3b'] if gb >= 31.5 else minimum


def signatures(folder, spec):
    """Cheap availability fingerprint, not a substitute for SHA-256 verification."""
    return {name: [p.stat().st_size, p.stat().st_mtime_ns]
            for name in spec['sha256'] if (p := folder/name).is_file()}
