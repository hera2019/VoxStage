"""Heuristic listening cues, never a voice-quality verdict. Astra, 2026-09-09."""
import numpy as np
import soundfile as sf
from .content_check import text_units

VERSION='listening-cues-v1'
MANUAL=['尾音是否自然、是否拖音','同一角色声线是否一致','停顿是否符合句意、前后语速是否合适']


def analyze(pcm, rate, timed_text=None, language='zh'):
    pcm=np.asarray(pcm,dtype=np.float32)
    if pcm.ndim!=1 or not len(pcm) or not np.isfinite(pcm).all():raise ValueError('声音无法分析。')
    duration=len(pcm)/rate;frame=max(1,round(rate*.01))
    padded=np.pad(pcm,(0,(-len(pcm))%frame)).reshape(-1,frame)
    rms=np.sqrt(np.mean(padded*padded,axis=1));threshold=max(.0005,float(rms.max())*.015)
    active=np.flatnonzero(rms>=threshold);markers=[]
    if len(active):
        quiet=rms<threshold;edges=np.diff(np.r_[False,quiet,False].astype(int))
        for a,b in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)):
            if a>active[0] and b<=active[-1] and (b-a)*frame/rate>=.35:
                markers.append({'kind':'pause','start':a*frame/rate,'end':min(duration,b*frame/rate),
                    'label':'较长停顿 · 请试听','basis':'低能量持续至少 0.35 秒，可能是正常断句。'})
    else:
        markers.append({'kind':'quiet','start':0.,'end':duration,'label':'声音过轻或无声','basis':'没有检测到足够的音频能量。'})
    # Hypothesis D37: compare sufficiently long halves using coarse ASR text timing.
    # These timings include pauses and are NOT forced alignment or syllable truth.
    valid=[]
    for item in timed_text or []:
        a,b=item.get('start',-1),item.get('end',-1)
        units=text_units(item.get('text',''),language)
        if units and 0<=a<b<=duration+.05:valid.append((a,min(b,duration),len(units)))
    valid.sort();pace={'status':'unavailable','reason':'文字时间信息不足，语速起伏请人工试听。'}
    if valid:
        a,b=valid[0][0],max(t[1] for t in valid);mid=(a+b)/2
        counts=[0.,0.]
        for start,end,n in valid:
            counts[0]+=n*max(0,min(end,mid)-start)/(end-start)
            counts[1]+=n*max(0,end-max(start,mid))/(end-start)
        if b-a>=4 and min(counts)>=6:
            rates=[n/((b-a)/2) for n in counts];ratio=max(rates)/min(rates)
            pace={'status':'estimated','first_units_per_second':rates[0],'second_units_per_second':rates[1],
                  'ratio':ratio,'basis':'ASR 粗略时间分布，包含停顿，非精确发音速度。'}
            if ratio>=1.5:
                markers.append({'kind':'pace','start':a,'end':b,'label':'前快后慢 · 请试听' if rates[0]>rates[1] else '前慢后快 · 请试听',
                    'basis':f'前后半段文字密度相差约 {ratio:.1f} 倍；识别时间可能有误。'})
    bins=np.array_split(pcm,min(3200,len(pcm)))
    peaks=[float(np.max(np.abs(part))) for part in bins];maximum=max(peaks) or 1
    return {'version':VERSION,'duration':duration,'markers':markers,'pace':pace,
            'waveform':[round(x/maximum,4) for x in peaks], 'manual_checkpoints':MANUAL,
            'notice':'自动标记是试听线索；没有标记不代表声音无误。时间位置为原音秒数。'}


def analyze_file(path, timed_text=None, language='zh'):
    pcm,rate=sf.read(path,dtype='float32');return analyze(pcm,rate,timed_text,language)

# 最后更新：2026-09-09 · Astra
