import {sourceToOutput,type TimePiece} from './timeMapping';
export type Clip={id:string;source_start:number;source_end:number;speed:number|null};
export type Block=Clip&{start:number;end:number;effectiveSpeed:number};
export function layoutClips(clips:Clip[],globalSpeed:number,mapping:TimePiece[]=[]):Block[]{let position=0;return clips.map(c=>{
 const match=mapping.find(m=>m.clip_id===c.id);const speed=c.speed??globalSpeed;
 let duration=(c.source_end-c.source_start)/speed;
 if(match&&Math.abs(match.speed-speed)<1e-8&&Math.abs(match.source_start-c.source_start)<.0001&&Math.abs(match.source_end-c.source_end)<.0001)duration=match.output_end-match.output_start;
 else if(mapping.length&&!mapping.some(m=>m.clip_id))duration=sourceToOutput(c.source_end,mapping)-sourceToOutput(c.source_start,mapping);
 const result={...c,start:position,end:position+duration,effectiveSpeed:speed};position+=duration;return result;
})}
export function stretchClip(clip:Clip,outputDuration:number):Clip{const speed=Math.max(.5,Math.min(2,(clip.source_end-clip.source_start)/Math.max(.01,outputDuration)));return {...clip,speed:Math.round(speed*10000)/10000}}
export function splitClip(clips:Clip[],block:Block,time:number,newId:string):Clip[]{const fraction=(time-block.start)/(block.end-block.start);const source=block.source_start+fraction*(block.source_end-block.source_start);
 if(source-block.source_start<.02||block.source_end-source<.02)throw new Error('切割线离边缘太近，每块至少保留 0.02 秒。');
 return clips.flatMap(c=>c.id===block.id?[{...c,source_end:source},{...c,id:newId,source_start:source}]:[c]);}
// 最后更新：2026-09-09 · Astra
