export type TimePiece={clip_id?:string;source_start:number;source_end:number;output_start:number;output_end:number;speed:number};
export type PlaybackContext={segmentId:string;original:boolean;loop?:boolean;mapping:TimePiece[]};
export function sourceToOutput(time:number,mapping:TimePiece[]){
 for(const x of mapping){if(time<x.source_start)return x.output_start;if(time<x.source_end)return x.output_start+(time-x.source_start)/(x.source_end-x.source_start)*(x.output_end-x.output_start)}
 return mapping.at(-1)?.output_end??0;
}
export function outputToSource(time:number,mapping:TimePiece[]){
 for(const x of mapping){if(time<x.output_end)return x.source_start+Math.max(0,time-x.output_start)/(x.output_end-x.output_start)*(x.source_end-x.source_start)}
 return mapping.at(-1)?.source_end??0;
}
// 最后更新：2026-09-09 · Astra
