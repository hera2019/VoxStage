"""Bounded same-speaker listening comparison. Astra, 2026-09-09.

Assumption: lower sampling temperature is a candidate, not an accepted fix.
Uses only existing synthetic samples and preset voices; leaves user projects unchanged.
"""
import hashlib,json,sys,time
from pathlib import Path
import numpy as np
import soundfile as sf
import mlx.core as mx
from mlx_audio.tts.utils import load_model

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime.audio import process_audio

out=ROOT/'user-data/voice-consistency-check'
out.mkdir(parents=True,exist_ok=True)
project=json.loads((ROOT/'user-data/projects/c138d1570f40447fa65e4a0b7f1d00bc/project.json').read_text())
segments=[project['segments'][0],project['segments'][-1]]
model_path=ROOT/'user-data/models/qwen-customvoice'
provenance=json.loads((model_path/'voxstage-model.json').read_text())
report={'synthetic_audio':True,'date':'2026-09-09','model':{k:provenance[k] for k in ('repo','revision')},
 'runtime':'mlx-audio-0.5.1','speaker':'Vivian','language':'Chinese','seed':260909,
 'other_parameters':{'top_k':50,'top_p':1.0,'max_tokens':2048,'repetition_penalty':1.05},
 'human_feedback':'User reports two narrator lines sound substantially different in speaker/environment; not accepted for continuity.',
 'quality_acceptance':'pending human comparison; no similarity metric or improvement claim',
 'groups':[]}
def save_pair(label,clips,records):
    rate=24000
    pcm=np.concatenate([clips[0],np.zeros(rate//2,dtype=np.float32),clips[1]])
    path=out/(label+'.wav')
    sf.write(path,pcm,rate,subtype='PCM_16')
    meta={'label':label,'synthetic_audio':True,'path':str(path.relative_to(ROOT)),
          'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'samples':len(pcm),'sample_rate':rate,'segments':records}
    path.with_suffix('.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    report['groups'].append(meta)

clips=[];records=[]
for s in segments:
    path=ROOT/'user-data/projects'/project['id']/'audio'/(s['audio']['fingerprint']+'.wav')
    pcm,rate=sf.read(path,dtype='float32')
    assert rate==24000
    clips.append(pcm);records.append({'text':s['text'],'temperature':.9,'source_fingerprint':s['audio']['fingerprint'],'synthetic_audio':True})
save_pair('A-original',clips,records)
model=load_model(str(model_path))
for label,temp in [('B-lower-randomness',.6),('C-greedy',0.0)]:
    clips=[];records=[]
    for s in segments:
        mx.random.seed(260909)
        started=time.perf_counter()
        results=list(model.generate_custom_voice(text=s['text'],speaker='Vivian',language='Chinese',temperature=temp,
                     max_tokens=2048,top_k=50,top_p=1.0,repetition_penalty=1.05))
        elapsed=time.perf_counter()-started
        assert results and all(int(x.sample_rate)==24000 for x in results)
        pcm=np.concatenate([np.asarray(x.audio,dtype=np.float32).reshape(-1) for x in results])
        pcm,meta=process_audio(pcm,24000)
        clips.append(pcm);records.append({'text':s['text'],'temperature':temp,'generation_seconds':elapsed,**meta})
    save_pair(label,clips,records)
(ROOT/'results/voice-consistency-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
(ROOT/'results/voice-consistency-check.md').write_text('''# 同一旁白的跨句声音一致性

本人试听反馈：前后旁白差异较大，不像同一个人在同一个环境中说话。当前不能将跨句声音一致性标为通过。

检查中文实测工程：首尾两句均为 Vivian、相同模型提交、相同随机种子 260909；逐句独立生成，没有共享前句声音作为条件。处理仅为峰值音量调整，没有混响效果。以上排除了已记录配置中切错音色的情况，不能单独证明差异的具体成因。

已生成三组对照，每组顺序均为“雨点轻轻敲着窗。”、半秒额外间隔、“两个人相视一笑。”：

- A-original.wav：原有两句生成文件，temperature 0.9。
- B-lower-randomness.wav：温度 0.6，减少采样随机性。
- C-greedy.wav：温度 0，当前 MLX 实现使用贪心解码（每步选最高分结果）。

文件位于 user-data/voice-consistency-check/，忽略入库；JSON 记录参数、处理信息、文件校验和与实测耗时。两组候选沿用相同模型、音色、文本、种子、其它采样参数和后处理。原版只取已有音频，没有重新采样；未加入语音克隆或真人参考录音。只测试这两个中文短句，不能推广为英文或长篇已通过。

**结果：三组音频准备完成，改善效果未判定。** 请比较同一人感、录音距离/空间感、响度/语气，以及读字完整性；降低随机性也可能牺牲自然度。没有改动应用默认参数、替换工程音频或推断相似度百分比。

官方模型说明区分预设音色与指令控制；当前 0.6B CustomVoice 不列为支持指令控制，不能靠加一句“同一录音棚”就承诺解决。来源：https://github.com/QwenLM/Qwen3-TTS#released-models-description-and-download 。当前接口及温度行为另已检查本地 mlx-audio 0.5.1 实现。

最后更新：2026-09-09 · Astra
''')
print('Prepared original + two candidate pairs. Human continuity acceptance remains pending.')
