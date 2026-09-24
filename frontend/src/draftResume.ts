
import {tr} from './i18n';export type DraftResume={draft_id:string;name:string;book?:{id:string;index:number};silent?:number[]};
const KEY='voxstage-latest-draft';
export function rememberDraft(value:DraftResume){try{localStorage.setItem(KEY,JSON.stringify(value))}catch{}}
export function forgetDraft(id:string){try{const v=JSON.parse(localStorage.getItem(KEY)??'null');if(v?.draft_id===id)localStorage.removeItem(KEY)}catch{}}
/** Forget a draft everywhere it is remembered: the latest-draft entry and every per-text or per-chapter key that points at it. */
/** Forget a draft everywhere it is remembered: the latest-draft entry and every per-text or per-chapter key that points at it. */
export function abandonDraft(id:string){forgetDraft(id);try{for(let i=localStorage.length-1;i>=0;i--){const key=localStorage.key(i)??'';if(key.startsWith('voxstage-draft-')&&localStorage.getItem(key)===id)localStorage.removeItem(key)}}catch{}}
export function draftCandidates():DraftResume[]{
 try{const found:DraftResume[]=[];const v=JSON.parse(localStorage.getItem(KEY)??'null');if(v&&/^[a-f0-9]{32}$/.test(v.draft_id))found.push(v);
 for(let i=localStorage.length-1;i>=0;i--){const key=localStorage.key(i)??'';if(!key.startsWith('voxstage-draft-'))continue;const id=localStorage.getItem(key)??'';if(!/^[a-f0-9]{32}$/.test(id)||found.some(x=>x.draft_id===id))continue;
 const book=key.match(/^voxstage-draft-([a-f0-9]{32})-(\d+)$/);found.push({draft_id:id,name:tr("未完成的角色复核"),...(book?{book:{id:book[1],index:Number(book[2])}}:{})})}return found;
 }catch{return []}
}

export function silentLines(units:{text:string;silent?:boolean}[]):number[]{const out:number[]=[];let line=0;for(const u of units){const parts=u.text.split('\n');parts.forEach((part,i)=>{if(u.silent&&part.trim())out.push(line);if(i<parts.length-1)line++})}return [...new Set(out)]}
