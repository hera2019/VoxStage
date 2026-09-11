"""Final-PCM timeline and explicitly estimated speech boundaries. Astra, 2026-09-09."""
from pathlib import Path
import numpy as np
import soundfile as sf
from .tempo import render_tempo, edit_status
from .content_check import file_sha
from .rhythm import analyze
from .clips import render_clips

PROCESSING_VERSION = 'pcm-peak-rms-v1'

def process_audio(audio, rate):
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if not 8000 <= rate <= 96000 or len(audio) == 0 or not np.isfinite(audio).all():
        raise ValueError('Invalid audio output')
    peak = float(np.max(np.abs(audio)))
    if peak < 1e-5:
        raise ValueError('No audible output; please retry')
    # Conservative initial peak normalization, deliberately not labelled LUFS.
    audio = audio * min(0.89 / peak, 4.0)
    frame = max(1, round(rate * .01))
    rms = np.array([np.sqrt(np.mean(x*x)) for x in np.array_split(
        np.pad(audio, (0, (-len(audio)) % frame)), (len(audio)+frame-1)//frame)])
    indices = np.flatnonzero(rms >= max(0.001, float(rms.max()) * .035))
    if not len(indices):
        raise ValueError('Speech region could not be estimated')
    start = max(0, int(indices[0] * frame))
    end = min(len(audio), int((indices[-1]+1)*frame))
    return audio, {'samples': len(audio), 'sample_rate': int(rate),
                   'speech_start_sample': start, 'speech_end_sample': end,
                   'speech_boundary_method': 'estimated_rms_10ms',
                   'processing_version': PROCESSING_VERSION, 'synthetic_audio': True}

def timestamp(sample, rate):
    ms = round(sample * 1000 / rate)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'

def prepare_segment(project, segment, directory):
    meta=segment['audio'];path=directory/'audio'/(meta['fingerprint']+'.wav')
    pcm,rate=sf.read(path,dtype='float32');stat=path.stat()
    if pcm.ndim!=1 or len(pcm)!=meta['samples'] or rate!=meta['sample_rate']:
        raise ValueError('Audio asset is inconsistent; regenerate it')
    regions=[];cuts=[];clips=None
    if edit_status(segment,[stat.st_size,stat.st_mtime_ns])=='current':
        edit=segment['tempo_edit']
        if file_sha(path)!=edit['audio_sha256']:raise ValueError('原音文件已改变，请重新设置局部语速。')
        regions=edit.get('regions',[]);cuts=edit.get('cuts',[]);clips=edit.get('clips')
    if clips is not None:pcm,mapping=render_clips(pcm,rate,clips,project.get('speech_rate',1.0))
    else:pcm,mapping=render_tempo(pcm,rate,project.get('speech_rate',1.0),regions,cuts)
    if clips is not None or regions or cuts or project.get('speech_rate',1.0)!=1.0:pcm,meta=process_audio(pcm,rate)
    return pcm,rate,meta,mapping


def export_audio(project, directory: Path, output: Path, *, delivery=False):
    parts, entries, cues, rendered = [], [], [], []
    position, rate = 0, None
    for index, segment in enumerate(project['segments']):
        pcm,current_rate,meta,mapping=prepare_segment(project,segment,directory)
        if rate is not None and current_rate!=rate:raise ValueError('Mixed sample rates cannot be exported')
        rate=current_rate;speed=project.get('speech_rate',1.0)
        start = position + meta['speech_start_sample']
        end = position + meta['speech_end_sample']
        entries.append({'id':segment['id'], 'speaker':segment['speaker'], 'text':segment['text'],
                        'file_start_sample':position, 'file_end_sample':position+len(pcm),
                        'speech_start_sample':start, 'speech_end_sample':end,
                        'speech_boundary_method':meta['speech_boundary_method'],
                        'synthetic_audio':True,'speech_rate':speed,'tempo_mapping':mapping,
                        'processed_checks':{**{k:v for k,v in analyze(pcm,rate).items() if k!='waveform'},'notice':'成品低能量检查；时间为该句成品秒数，不代表自然度通过。'},
                        'processed_check_scope':'final_segment_audio; pace requires original ASR timings'})
        cues.append(f'{index+1}\n{timestamp(start, rate)} --> {timestamp(end, rate)}\n{segment["text"]}\n')
        parts.append(pcm)
        if delivery:rendered.append(pcm)
        position += len(pcm)
        if index < len(project['segments'])-1:
            pause_ms = segment.get('pause_after')
            if pause_ms is None:
                pause_ms = project['pause_ms']
            pause = np.zeros(round(rate * pause_ms/1000), dtype=np.float32)
            parts.append(pause)
            position += len(pause)
    output.mkdir(parents=True, exist_ok=True)
    sf.write(output / 'full.wav', np.concatenate(parts), rate, subtype='PCM_16')
    (output / 'subtitles.srt').write_text('\n'.join(cues), encoding='utf-8')
    if delivery:
        from .delivery import write_delivery
        write_delivery(output,entries,rendered,rate,position)
    return {'synthetic_audio':True, 'speech_rate':project.get('speech_rate',1.0), 'sample_rate':rate, 'total_samples':position, 'segments':entries}

# 最后更新：2026-09-09 · Astra

# 最后更新：2026-09-11 · Astra（交付包复用成品 PCM）

# 最后更新：2026-09-11 · Astra（逐句停顿只用于句间拼接，末句不插静音）
