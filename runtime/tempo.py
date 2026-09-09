"""Local pitch-preserving export tempo; originals are never modified. Astra, 2026-09-09."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import numpy as np
import soundfile as sf

RATES=tuple(round(.5+i*.1,1) for i in range(16))
VERSION="ordered-clips-v4"


def ffmpeg_path():
    candidates=[os.environ.get('VOXSTAGE_FFMPEG'),shutil.which('ffmpeg'),'/opt/homebrew/bin/ffmpeg','/usr/local/bin/ffmpeg']
    return next((p for p in candidates if p and Path(p).is_file() and os.access(p,os.X_OK)),None)


def change_tempo(pcm,rate,speed):
    if not isinstance(speed,(int,float)) or not np.isfinite(speed) or not .5<=speed<=2:raise ValueError('语速范围为 0.5–2.0 倍。')
    if speed==1.0:return pcm
    executable=ffmpeg_path()
    if not executable:raise ValueError('语速调节需要本机 FFmpeg；可以先恢复原速导出。')
    with tempfile.TemporaryDirectory(prefix='voxstage-tempo-') as directory:
        source,target=Path(directory)/'source.wav',Path(directory)/'tempo.wav'
        sf.write(source,pcm,rate,subtype='FLOAT')
        try:
            result=subprocess.run([executable,'-nostdin','-hide_banner','-loglevel','error','-y',
                '-i',str(source),'-af',f'atempo={speed}','-ac','1','-ar',str(rate),'-c:a','pcm_f32le',str(target)],
                capture_output=True,text=True,timeout=60)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('变速处理超时，请重试或恢复原速。') from exc
        if result.returncode or not target.is_file():raise ValueError('变速处理失败，请检查本机 FFmpeg。')
        output,actual_rate=sf.read(target,dtype='float32')
        if actual_rate!=rate or output.ndim!=1 or not len(output) or not np.isfinite(output).all():
            raise ValueError('变速输出无效，请恢复原速或重试。')
        return output


def edit_status(segment, audio_stat=None):
    edit=segment.get('tempo_edit')
    if not edit or not (edit.get('regions') or edit.get('cuts') or edit.get('clips')):return 'none'
    if (segment.get('audio') and edit.get('source_fingerprint')==segment['audio']['fingerprint']
        and (audio_stat is None or edit.get('audio_stat')==audio_stat)):
        return 'current'
    return 'stale'


def valid_regions(regions, duration):
    if len(regions)>20:raise ValueError('每句最多保留 20 个调速片段。')
    previous=0.
    for item in regions:
        a,b,speed=item['start'],item['end'],item['speed']
        if not all(np.isfinite(v) for v in (a,b,speed)) or not .5<=speed<=2:
            raise ValueError('语速范围为 0.5–2.0 倍。')
        if a<previous or a<0 or b>duration+1e-6 or b-a<.2:
            raise ValueError('选区至少 0.2 秒、不可重叠或超出原音；请先移除重叠选区。')
        previous=b
    return regions


def valid_cuts(cuts, duration):
    if len(cuts)>40:raise ValueError('每句最多保留 40 个剪切范围。')
    previous=0.;remaining=duration
    for item in cuts:
        a,b=item['start'],item['end']
        if not all(np.isfinite(x) for x in (a,b)) or a<previous or a<0 or b>duration+1e-6 or b-a<.02-1e-6:
            raise ValueError('剪切至少 0.02 秒，不可重叠或超出原音。')
        remaining-=b-a;previous=b
    if remaining<.2-1e-6:raise ValueError('至少保留 0.2 秒声音，不能剪空整句。')
    return cuts


def render_tempo(pcm, rate, speed, regions=(), cuts=()):
    duration=len(pcm)/rate
    valid_regions(regions,duration);valid_cuts(cuts,duration)
    bounds=sorted({0,len(pcm),*[round(x[k]*rate) for x in [*regions,*cuts] for k in ('start','end')]})
    merged=[]
    for a,b in zip(bounds,bounds[1:]):
        middle=(a+b)/2/rate
        if any(x['start']<=middle<x['end'] for x in cuts):continue
        v=next((x['speed'] for x in regions if x['start']<=middle<x['end']),speed)
        if merged and merged[-1][1]==a and merged[-1][2]==v:merged[-1]=(merged[-1][0],b,v)
        else:merged.append((a,b,v))
    if any((b-a)/rate<.02-1e-6 for a,b,_ in merged):
        raise ValueError('边界留下不足 0.02 秒的碎片，请合并或移动边界。')
    outputs=[];mapping=[];position=0
    for a,b,v in merged:
        output=change_tempo(pcm[a:b],rate,v).copy()
        # Tiny edge ramps reduce discontinuities without deleting speech samples.
        if len(merged)>1 or cuts:
            fade=min(round(rate*.003),len(output)//2)
            if fade:
                if a>0:output[:fade]*=np.linspace(0,1,fade)
                if b<len(pcm):output[-fade:]*=np.linspace(1,0,fade)
        mapping.append({'source_start':a/rate,'source_end':b/rate,'output_start':position/rate,
                        'output_end':(position+len(output))/rate,'speed':v})
        outputs.append(output);position+=len(output)
    return np.concatenate(outputs),mapping

# 最后更新：2026-09-09 · Astra
