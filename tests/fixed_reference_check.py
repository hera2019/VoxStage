"""Authorized synthetic-reference experiment; no live engine changes. Astra, 2026-09-09.

Hypothesis (D27): a fixed audio+transcript condition may stabilize cross-line identity.
This compares complete generation routes, not an isolated causal reference-only intervention.
"""
import argparse,hashlib,json,os,sys,time,traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--synthetic-reference-consent-confirmed',action='store_true')
    args=parser.parse_args()
    if not args.synthetic_reference_consent_confirmed:
        parser.error('Explicit consent for the fixed synthetic reference experiment is required.')
    # No arbitrary reference input: only the known self-written, preset-generated sample.
    source_id='42a023049d9546e0a3ba84278a3d6c07'
    existing=json.loads((ROOT/'results/real-model-check.json').read_text())
    source=next(r for r in existing['results'] if r['project_id']==source_id)
    ref=source['segments'][0]
    original_last=source['segments'][-1]
    reference_path=ROOT/'user-data/projects'/source_id/'audio'/(ref['audio']['fingerprint']+'.wav')
    with_params=json.loads((ROOT/'results/english-voice-comparison.json').read_text())
    assert existing['synthetic_audio'] and ref['audio']['synthetic_audio']
    assert ref['speaker']=='Narrator' and ref['text']=='Rain tapped against the window.'
    assert original_last['speaker']=='Narrator'
    # Independently recorded original comparison metadata establishes reference sample provenance.
    assert ref['audio']['fingerprint']==with_params['groups'][0]['segments'][0]['source_fingerprint']
    expected={
      'model.safetensors':'d7c7ed3e3464e3e59de0f955b3755891fa8319ff061c3f0307fe2e1343bc122d',
      'speech_tokenizer/model.safetensors':'836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258'}
    actual={name:sha(args.model/name) for name in expected}
    assert actual==expected,'Base model weights differ from pinned provenance'
    config=json.loads((args.model/'config.json').read_text())
    assert config['tts_model_type']=='base'
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['HF_HOME']=str(ROOT/'user-data/hf-cache')
    import numpy as np
    import soundfile as sf
    import mlx.core as mx
    from mlx_audio.tts.utils import load_model
    sys.path.insert(0,str(ROOT))
    from runtime.audio import process_audio

    folder=ROOT/'user-data/fixed-reference-check'
    folder.mkdir(parents=True,exist_ok=True)
    # Prevent accidental overwriting of an earlier experiment or user feedback.
    if (ROOT/'results/fixed-reference-check.json').exists():
        raise RuntimeError('An experiment already exists; preserve it before an intentional rerun.')
    reference,rate=sf.read(reference_path,dtype='float32')
    assert rate==24000 and reference.ndim==1 and np.isfinite(reference).all()
    # Reuse the exact original PCM reference; do not build a chain from newly generated outputs.
    ref_array=mx.array(reference)
    report={'date':'2026-09-09','synthetic_audio':True,
      'consent':{'confirmed':True,'scope':'fixed preset-generated synthetic reference only','basis':'user accepted proposed experiment: 好的，你再试试看'},
      'runtime':'mlx-audio-0.5.1',
      'model':{'repo':'mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16','revision':'1eccf1cb2519b5a4e8a95b5f0544f3303568164f','sha256':actual},
      'reference':{'synthetic_audio':True,'text':ref['text'],'source_model':ref['audio']['engine'],
        'source_fingerprint':ref['audio']['fingerprint'],'sha256':sha(reference_path),'samples':len(reference),'sample_rate':rate,
        'duration_seconds':len(reference)/rate,'transcript_status':'source input text; no independent ASR verification'},
      'parameters':{'temperature':.6,'top_k':50,'top_p':1.0,'repetition_penalty':1.5,'max_tokens':2048},
      'comparison_limit':'Base+fixed reference vs CustomVoice; checkpoint and effective repetition penalty also differ, so any improvement cannot be attributed to reference alone.',
      'quality_acceptance':'pending human listening; generation is not a quality pass',
      'cases':[],'comparisons':[]}
    (folder/'reference-provenance.json').write_text(json.dumps(report['reference'],ensure_ascii=False,indent=2))

    def save(name,pcm,meta):
        file=folder/(name+'.wav')
        sf.write(file,pcm,rate,subtype='PCM_16')
        info=sf.info(file)
        assert info.frames==len(pcm) and info.samplerate==rate
        meta.update({'synthetic_audio':True,'path':str(file.relative_to(ROOT)),'sha256':sha(file)})
        file.with_suffix('.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
        return meta

    # Original narration pair, without Leo; preserve both earlier parameter baselines.
    old_clips=[]
    for s in (ref,original_last):
        pcm,sr=sf.read(ROOT/'user-data/projects'/source_id/'audio'/(s['audio']['fingerprint']+'.wav'),dtype='float32')
        assert sr==rate
        old_clips.append(pcm)
    report['comparisons'].append(save('A-original-narrator',np.concatenate([old_clips[0],np.zeros(rate//2),old_clips[1]]),{'type':'original CustomVoice 0.9 pair'}))
    group=with_params['groups'][1]
    baseline_path=ROOT/group['path']
    assert sha(baseline_path)==group['sha256']
    previous,sr=sf.read(baseline_path,dtype='float32')
    assert sr==rate
    first_len=group['segments'][0]['samples']
    last_start=first_len+rate//2+group['segments'][1]['samples']+rate//2
    assert len(previous)-last_start==group['segments'][2]['samples']
    report['comparisons'].append(save('B-lower-randomness-narrator',np.concatenate([previous[:first_len],np.zeros(rate//2),previous[last_start:]]),{'type':'previous CustomVoice 0.6 pair'}))

    try:
        start=time.perf_counter()
        model=load_model(str(args.model))
        report['load_seconds']=time.perf_counter()-start
        assert model.speech_tokenizer.has_encoder
        cases=[('opening',ref['text'],260909),('closing',original_last['text'],260909),
               ('new-line','Later that evening, the house was quiet again.',260909),
               ('closing-retake',original_last['text'],260910)]
        clips={}
        for name,text,seed in cases:
            try:
                mx.random.seed(seed);mx.reset_peak_memory()
                start=time.perf_counter()
                generated=list(model.generate(text=text,lang_code='English',ref_audio=ref_array,
                   ref_text=ref['text'],stream=False,verbose=False,**report['parameters']))
                elapsed=time.perf_counter()-start
                assert generated and all(int(x.sample_rate)==rate for x in generated)
                pcm=np.concatenate([np.asarray(x.audio,dtype=np.float32).reshape(-1) for x in generated])
                pcm,meta=process_audio(pcm,rate)
                # Broad abnormal-output check, not word accuracy or quality acceptance.
                assert .3<len(pcm)/rate<20,'Unexpected length for a short test line'
                meta.update({'name':name,'text':text,'seed':seed,'generation_seconds':elapsed,
                    'mlx_peak_memory_bytes':mx.get_peak_memory(),'reference_sha256':report['reference']['sha256'],
                    'reference_cache_entries':len(model._icl_cache),'status':'generated'})
                record=save(name,pcm,meta)
                report['cases'].append(record);clips[name]=pcm
                print(name,'generated',round(len(pcm)/rate,2),'seconds',flush=True)
            except Exception as exc:
                report['cases'].append({'name':name,'text':text,'status':'failed','error':type(exc).__name__+': '+str(exc)})
                traceback.print_exc()
        if 'opening' in clips and 'closing' in clips:
            report['comparisons'].append(save('C-fixed-reference-narrator',np.concatenate([clips['opening'],np.zeros(rate//2),clips['closing']]),{'type':'Base fixed-reference pair'}))
        if 'new-line' in clips and 'closing-retake' in clips:
            report['comparisons'].append(save('D-new-line-and-retake',np.concatenate([clips['new-line'],np.zeros(rate//2),clips['closing-retake']]),{'type':'Base held-out line then alternate-seed closing retake'}))
        report['technical_status']='PASS' if len(clips)==4 else 'FAIL'
    except Exception as exc:
        report['technical_status']='FAIL';report['error']=type(exc).__name__+': '+str(exc)
        traceback.print_exc()
    (ROOT/'results/fixed-reference-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (ROOT/'results/fixed-reference-check.md').write_text('''# 固定合成参考声音：英文旁白一致性实验

技术执行：'''+report['technical_status']+'''。声音身份、自然度、读字正确性：待本人试听，未通过质量验收。

本人已明确同意本实验。参考只使用原英文开头旁白的预设合成音频，固定同一文件及其源输入文本；无真人参考录音，不修改正式工程。实验入口有显式合成参考声音授权开关，没有它会在加载模型前拒绝运行。

复用本机已有 0.6B Base 权重，两份权重文件的 SHA-256 与已记录固定提交一致。无需再下载模型。当前 MLX 实现以参考音频和文本作为条件，内部缓存参考编码；记录了缓存项数，不据此宣称每个参考处理步骤都已缓存。每句始终使用最初参考，不把新生成声音反复用作下一句参考。

对照文件位于 user-data/fixed-reference-check/：

- A-original-narrator：原版 0.9 的首尾旁白。
- B-lower-randomness-narrator：此前 0.6 的首尾旁白。
- C-fixed-reference-narrator：固定参考方案生成的首尾旁白。
- D-new-line-and-retake：新台词，然后更换随机种子重做的结尾旁白。

参考是开头旁白本身，因此重做同一句不能独立证明跨文本泛化；结尾与新台词未出现在参考文本中。还需比较重做后的声音是否保持。参考文本来自原始生成输入，尚未用 ASR 独立核对。

本轮同时更换了 CustomVoice 为 Base，Base 的参考模式有效重复惩罚为 1.5，原 CustomVoice 为 1.05；温度选择 0.6。比较的是整条候选生成路线，不能将改善单独归因于参考声音。样本短小，仅测英文单一男声，不等于所有语言或角色已通过。

自动检查覆盖模型权重、参考来源记录、授权开关、有效音频、短句异常时长、保存后采样数与文件校验和。具体输出及实测时间/MLX 峰值见同名 JSON；日志保留于 user-data/fixed-reference-check.log。正式生成参数与用户音频均未改变。

官方路线依据：https://github.com/QwenLM/Qwen3-TTS#voice-clone 。本次直接复用已有 CustomVoice 合成参考，未下载或执行 VoiceDesign。

最后更新：2026-09-09 · Astra
''')
    print('Technical:',report['technical_status'],'; human voice quality pending.',flush=True)
    return 0 if report['technical_status']=='PASS' else 1

if __name__=='__main__':
    sys.exit(main())
