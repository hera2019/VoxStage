import {useEffect,useState} from 'react';
import {tr} from './i18n';

/** Export of a master book (Opus 三, 2026-09-21): pick chapters and outputs,
 *  see the estimate (length, sizes, warnings, what blocks), set the chapter
 *  pause, start a batch; the last successful batch stays downloadable and is
 *  labelled 最新 or 上次导出·工程已有改动. Against Sol 四's endpoints. */

/** Export of a master book (Opus 三, 2026-09-21): pick chapters and outputs,
 *  see the estimate (length, sizes, warnings, what blocks), set the chapter
 *  pause, start a batch; the last successful batch stays downloadable and is
 *  labelled 最新 or 上次导出·工程已有改动. Against Sol 四's endpoints. */
type Chapter={id:string;name:string;processing_state?:string|null;book?:{index?:number}|null};
type Estimate={seconds:number;estimated:boolean;chapters:{project_id:string;name:string;seconds:number;estimated:boolean;waiting:number}[];waiting:{project_id:string;segment_id:string;text:string}[];
  silent_chapters:{project_id:string;name:string}[];estimated_sizes?:Record<string,number>;estimated_final_bytes?:number;estimated_temporary_bytes?:number;estimated_required_bytes?:number;free_bytes?:number;
  warnings:string[];blocked:string[];can_export:boolean;implicit_outputs?:string[];chapter_pause_ms:number};
type Current={status:'none'|'latest'|'stale';batch_id?:string;links:Record<string,string>;stale_reasons?:string[];created_at_local?:string;seconds?:number;selected_chapters?:string[];outputs_requested?:string[]};
type Props={bookId:string;title:string;chapters:Chapter[];request:(path:string,method?:string,data?:unknown)=>Promise<any>;onClose:()=>void;inline?:boolean};

const OUTPUTS:[string,string][]=[['mp3',tr("完整音频（MP3）")],['wav',tr("完整音频（WAV）")],['srt',tr("句级字幕")],['zip',tr("剪辑交付包（ZIP）")],['timeline',tr("时间轴（JSON）")],['xml',tr("剪辑时间轴（XML）")],['report',tr("检查 / 听稿报告")]];
const clock=(s:number)=>{const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=Math.round(s%60);return h?tr("{0} 小时 {1} 分",h,m):tr("{0} 分 {1} 秒",m,x)};
const mb=(b?:number)=>b===undefined?'—':b>=1e9?(b/1e9).toFixed(2)+' GB':Math.round(b/1e6)+' MB';

export function BookExport({bookId,title,chapters,request,onClose,inline}:Props){
 const [selected,setSelected]=useState<string[]>(chapters.filter(c=>c.processing_state!=='unprocessed').map(c=>c.id));
 const [outputs,setOutputs]=useState<string[]>(['mp3','srt']);const [pause,setPause]=useState(0);const [revision,setRevision]=useState(0);
 const [estimate,setEstimate]=useState<Estimate|null>(null);const [current,setCurrent]=useState<Current|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const reload=async()=>{const s=await request(`/master-books/${bookId}/export/settings`);setPause(s.chapter_pause_ms??0);setRevision(s.revision??0);try{setCurrent(await request(`/master-books/${bookId}/export/current`))}catch{setCurrent(null)}};
 useEffect(()=>{void reload().catch(e=>setError((e as Error).message))},[bookId]);   // eslint-disable-line react-hooks/exhaustive-deps
 const toggle=(list:string[],set:(v:string[])=>void,id:string)=>{set(list.includes(id)?list.filter(x=>x!==id):[...list,id]);setEstimate(null)};
 const run=async(f:()=>Promise<void>)=>{setBusy(true);setError('');try{await f()}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 const doEstimate=()=>run(async()=>setEstimate(await request(`/master-books/${bookId}/export/estimate`,'POST',{revision,chapters:selected,outputs})));
 const doExport=()=>run(async()=>{await request(`/master-books/${bookId}/export/create`,'POST',{revision,chapters:selected,outputs});await reload();setEstimate(null)});
 const savePause=(v:number)=>run(async()=>{const r=await request(`/master-books/${bookId}/export/settings`,'PATCH',{revision,chapter_pause_ms:v});setPause(r.chapter_pause_ms??v);setRevision(r.revision??revision);setEstimate(null)});
 const label=(n:string)=>OUTPUTS.find(([k])=>n.startsWith(k)||n.includes(k))?.[1]??n;
 return <div className={inline?'structure-inline':'structure-wrap'}><div className={inline?'structure-page':'structure-dialog'} role={inline?undefined:'dialog'} aria-label={tr("导出《{0}》",title)}>
  <div className="setting-head"><strong>{tr("导出《{0}》",title)}</strong><small>{tr("章节按书的顺序拼接；每批有编号，成功后替换上一批的下载项。")}</small>{!inline&&<button type="button" aria-label={tr("关闭导出窗口")} onClick={onClose}>✕</button>}</div>
  {error&&<p role="alert" className="line-error">{error}</p>}
  <div className="export-grid">
   <section><strong>{tr("导出章节")}</strong><div className="attach-row"><button type="button" onClick={()=>{setSelected(chapters.map(c=>c.id));setEstimate(null)}}>{tr("全选")}</button><button type="button" onClick={()=>{setSelected([]);setEstimate(null)}}>{tr("全不选")}</button></div>
    <ul className="export-list">{chapters.map(c=><li key={c.id}><label><input type="checkbox" checked={selected.includes(c.id)} onChange={()=>toggle(selected,setSelected,c.id)}/>{c.book?.index?`${c.book.index}. `:''}{c.name}{c.processing_state==='unprocessed'&&<small>{tr(" · 未处理")}</small>}</label></li>)}</ul></section>
   <section><strong>{tr("输出内容")}</strong><ul className="export-list">{OUTPUTS.map(([k,l])=><li key={k}><label><input type="checkbox" checked={outputs.includes(k)} onChange={()=>toggle(outputs,setOutputs,k)}/>{l}</label></li>)}</ul>
    <label className="attach-row">{tr("章节之间停顿（毫秒）")}<input type="number" min={0} max={10000} step={50} defaultValue={pause} key={pause} onBlur={e=>{const v=Number(e.target.value);if(Number.isFinite(v)&&v!==pause)void savePause(v)}}/></label><small className="muted">{tr("上一章末句自己的停顿之外再加这么多；最后一章后面不加。")}</small></section>
  </div>
  <div className="buttons"><button type="button" className="primary" disabled={busy||!selected.length||!outputs.length} onClick={()=>void doEstimate()}>{busy?'…':tr("估算")}</button>{estimate&&<button type="button" className="primary" disabled={busy||!estimate.can_export} title={estimate.blocked.join(tr("；"))} onClick={()=>{if(confirm(tr("开始导出 {0} 章，预计 {1}？成功后会替换上一批的下载项。",selected.length,clock(estimate.seconds))))void doExport()}}>{tr("导出")}</button>}</div>
  {estimate&&<div className="structure-plan">
   <p>{tr("所选 ")}{estimate.chapters.length}{tr(" 章 · ")}{estimate.estimated?tr("预计"):tr("实际")} {clock(estimate.seconds)}{estimate.estimated_final_bytes!==undefined&&<>{tr(" · 成品约 {0}，临时空间约 {1}，磁盘剩余 {2}",mb(estimate.estimated_final_bytes),mb(estimate.estimated_temporary_bytes),mb(estimate.free_bytes))}</>}</p>
   {estimate.estimated_sizes&&<p className="muted">{Object.entries(estimate.estimated_sizes).map(([k,v])=>`${label(k)} ≈ ${mb(v)}`).join(' · ')}</p>}
   {estimate.warnings.map((w,i)=><p key={i} className="line-warning">⚠ {w}</p>)}
   {estimate.blocked.map((w,i)=><p key={i} role="alert" className="line-error">✕ {w}</p>)}
   {estimate.waiting.length>0&&<p className="muted">{tr("还有 {0} 句没有生成声音（{1}）。",estimate.waiting.length,[...new Set(estimate.waiting.map(w=>w.project_id))].map(id=>chapters.find(c=>c.id===id)?.name).filter(Boolean).join(tr("、")))}</p>}
   {estimate.silent_chapters.length>0&&<p className="muted">{tr("没有可朗读内容的章：{0}。",estimate.silent_chapters.map(c=>c.name).join(tr("、")))}</p>}
   <ul className="export-list">{estimate.chapters.map(c=><li key={c.project_id}>{c.name} · {c.estimated?tr("预计"):''}{clock(c.seconds)}{c.waiting?tr(" · {0} 句待生成",c.waiting):''}</li>)}</ul>
  </div>}
  {current&&current.status!=='none'&&<div className="structure-plan"><strong>{current.status==='latest'?tr("最新导出 · 与当前工程一致"):tr("上次导出 · 导出后工程已有改动")}</strong><small className="muted">{tr(" 批次 {0}{1}",current.batch_id,current.created_at_local?` · ${current.created_at_local}`:'')}</small>
   {current.status==='stale'&&<p className="line-warning">{tr("⚠ 这是上次导出的版本，导出后工程已有改动：{0}。仍可下载；要当前内容请重新导出。",(current.stale_reasons??[]).join(tr("；")))}</p>}
   <div className="export-links">{Object.entries(current.links).map(([name,url])=><a key={name} href={url} download>↓ {label(name)}</a>)}</div></div>}
 </div></div>;
}
