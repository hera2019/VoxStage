"""Ordered, non-destructive single-track clips. Astra, 2026-09-09."""
import re
import numpy as np
from .tempo import change_tempo


def clip_plan(edit,duration):
    if edit and 'clips' in edit:return edit['clips']
    regions=(edit or {}).get('regions',[]);cuts=(edit or {}).get('cuts',[])
    bounds=sorted({0.,duration,*[x[k] for x in [*regions,*cuts] for k in ('start','end')]})
    clips=[]
    for a,b in zip(bounds,bounds[1:]):
        if b<=a:continue
        mid=(a+b)/2
        if any(x['start']<=mid<x['end'] for x in cuts):continue
        speed=next((x['speed'] for x in regions if x['start']<=mid<x['end']),None)
        clips.append({'id':f'part-{len(clips)+1}','source_start':a,'source_end':b,'speed':speed})
    # Old region boundaries can leave a sub-20 ms sliver beside a cut.
    # Preserve every retained source sample; only merge touching spans.
    merged=[]
    for c in clips:
        if merged and abs(merged[-1]['source_end']-c['source_start'])<1e-9 and merged[-1]['speed']==c['speed']:
            merged[-1]['source_end']=c['source_end']
        else:merged.append(dict(c))
    index=0
    while index<len(merged):
        c=merged[index]
        if c['source_end']-c['source_start']<.02:
            if index and abs(merged[index-1]['source_end']-c['source_start'])<1e-9:
                merged[index-1]['source_end']=c['source_end'];merged.pop(index);continue
            if index+1<len(merged) and abs(c['source_end']-merged[index+1]['source_start'])<1e-9:
                merged[index+1]['source_start']=c['source_start'];merged.pop(index);continue
        index+=1
    for i,c in enumerate(merged):c['id']=f'part-{i+1}'
    return merged


def validate_clips(clips,duration):
    if not 1<=len(clips)<=40:raise ValueError('每句保留 1–40 个区块，不能删空整句。')
    ids=set();total=0
    for c in clips:
        a,b=c['source_start'],c['source_end'];speed=c.get('speed')
        if not re.fullmatch('[A-Za-z0-9_-]{1,80}',c['id']) or c['id'] in ids:raise ValueError('区块标识重复或无效。')
        ids.add(c['id'])
        if not np.isfinite(a) or not np.isfinite(b) or a<0 or b>duration+1e-6 or b-a<.02-1e-6:raise ValueError('区块至少 0.02 秒，不能超过原音范围。')
        if speed is not None and (not np.isfinite(speed) or not .5<=speed<=2):raise ValueError('区块速度范围为 0.5–2.0 倍。')
        total+=b-a
    if total<.2-1e-6:raise ValueError('整句至少保留 0.2 秒原音。')
    # Reorder/split preserve unique source spans; duplication is outside this editor's scope.
    spans=sorted((c['source_start'],c['source_end']) for c in clips)
    if any(a<last-1e-6 for (_,last),(a,_) in zip(spans,spans[1:])):raise ValueError('原音范围重复，请撤销后重试。')
    return clips


def render_clips(pcm,rate,clips,global_speed):
    validate_clips(clips,len(pcm)/rate)
    output=[];mapping=[];position=0
    for c in clips:
        a,b=round(c['source_start']*rate),round(c['source_end']*rate);speed=c.get('speed') or global_speed
        part=change_tempo(pcm[a:b],rate,speed).copy()
        fade=min(round(rate*.003),len(part)//2)
        if fade and (len(clips)>1 or a>0 or b<len(pcm)):
            part[:fade]*=np.linspace(0,1,fade);part[-fade:]*=np.linspace(1,0,fade)
        mapping.append({'clip_id':c['id'],'source_start':a/rate,'source_end':b/rate,'output_start':position/rate,'output_end':(position+len(part))/rate,'speed':speed})
        output.append(part);position+=len(part)
    return np.concatenate(output),mapping

# 最后更新：2026-09-09 · Astra
