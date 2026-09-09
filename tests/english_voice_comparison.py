"""English same-voice comparison, synthetic samples only. Astra, 2026-09-09.
Lower sampling temperature is an experimental candidate, not an adopted English default.
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

p=json.loads((ROOT/'user-data/projects/42a023049d9546e0a3ba84278a3d6c07/project.json').read_text())
segments=[s for s in p['segments'] if p['voices'][s['speaker']]=='Ryan']
assert len(segments)==3
out=ROOT/'user-data/english-voice-comparison'
out.mkdir(parents=True,exist_ok=True)
provenance=json.loads((ROOT/'user-data/models/qwen-customvoice/voxstage-model.json').read_text())
report={'synthetic_audio':True,'language':'en','voice':'Ryan','model':{k:provenance[k] for k in ('repo','revision')},
 'runtime':'mlx-audio-0.5.1','seed':260909,'parameters':{'top_k':50,'top_p':1.0,'max_tokens':2048,'repetition_penalty':1.05},
 'order':[{'speaker':s['speaker'],'text':s['text']} for s in segments],
 'quality_acceptance':'pending user listening; no English default change','groups':[]}
def save(label,clips,records):
    pcm=np.concatenate([piece for i,clip in enumerate(clips) for piece in ((clip,np.zeros(12000,dtype=np.float32)) if i<len(clips)-1 else (clip,))])
    file=out/(label+'.wav')
    sf.write(file,pcm,24000,subtype='PCM_16')
    info=sf.info(file)
    assert info.frames==len(pcm) and info.samplerate==24000
    meta={'label':label,'synthetic_audio':True,'path':str(file.relative_to(ROOT)),
          'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'samples':len(pcm),'sample_rate':24000,'segments':records}
    file.with_suffix('.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    report['groups'].append(meta)
clips=[];records=[]
for s in segments:
    a=s['audio']
    pcm,rate=sf.read(ROOT/'user-data/projects'/p['id']/'audio'/(a['fingerprint']+'.wav'),dtype='float32')
    assert rate==24000 and a['seed']==260909
    clips.append(pcm);records.append({'speaker':s['speaker'],'text':s['text'],'temperature':.9,'source_fingerprint':a['fingerprint'],'synthetic_audio':True})
save('A-original',clips,records)
model=load_model(str(ROOT/'user-data/models/qwen-customvoice'))
clips=[];records=[]
for s in segments:
    mx.random.seed(260909)
    start=time.perf_counter()
    results=list(model.generate_custom_voice(text=s['text'],speaker='Ryan',language='English',temperature=.6,**report['parameters']))
    elapsed=time.perf_counter()-start
    assert results and all(int(r.sample_rate)==24000 for r in results)
    pcm=np.concatenate([np.asarray(r.audio,dtype=np.float32).reshape(-1) for r in results])
    pcm,meta=process_audio(pcm,24000)
    clips.append(pcm);records.append({'speaker':s['speaker'],'text':s['text'],'temperature':.6,'generation_seconds':elapsed,**meta})
save('B-lower-randomness',clips,records)
(ROOT/'results/english-voice-comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
(ROOT/'results/english-voice-comparison.md').write_text('''# 英文同音色的口气一致性对照

本人反馈当前中文没问题，英文同一个男声的口气差距较大。中文反馈仅对应本轮试听，不代表所有语料通过。

检查实际工程发现 Narrator 和 Leo 都使用 Ryan；Mira 使用 Aiden。当前导入逻辑在三个角色间循环分配两个英文默认音色，确实存在不同角色共用男声的情况。它和同一旁白前后口气跳变是两件事；本人具体指哪一组仍待澄清，不擅自判断为切错角色。

为覆盖两种情况，对照均保留三句 Ryan，顺序为：

1. Narrator: Rain tapped against the window.
2. Leo: Just the wind. We are safe here.
3. Narrator: They smiled and went back to their books.

A 为原有温度 0.9 的音频；B 用温度 0.6 重新生成，其它参数、文本、音色与后处理保持一致，每两句之间额外加入半秒间隔。全部为现有自写样例和预设合成音，无真人参考录音。

实际结果：两组文件生成/拼接与读回检查成功，参数及校验和见同名 JSON，音频保存在 user-data/english-voice-comparison/。没有计算相似度或把生成成功当成听感改善。英文默认与用户工程仍保持原样，等待本人试听判断。若不同角色需可辨认，另选音色；调整随机性不能使同一音色自动变为不同人物。

最后更新：2026-09-09 · Astra
''')
print('English original and lower-randomness comparison ready; three Ryan lines each. Default unchanged.')
