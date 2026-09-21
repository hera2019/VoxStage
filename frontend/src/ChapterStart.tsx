import {useEffect,useState} from 'react';

/** An unprocessed chapter's way into the pipeline (Opus 一, last piece,
 *  2026-09-21): what this machine and the chosen model can take
 *  (`GET /projects/{id}/attribution/capacity`), start or resume the batched
 *  attribution (`POST …/attribution/start`), watch the queue and the batches,
 *  cancel, and when the draft is ready hand it to the review page; confirming
 *  there turns this same project into a processed chapter. */
type Capacity={model:{id:string;label:string;installed:boolean;loadable:boolean;recommended_for_machine:boolean};machine:{memory_gb:number};
  limits:{chars:number;units:number;context:number;max_tokens:number};source:{chars:number;units:number;estimated_segments:number;segment_limit:number};
  batches:number;batch_sizes:number[];explanation:string};
type Job={kind?:string;status?:string;completed?:number;total?:number;current_batch?:number|null;error?:string|null};
type ProjectState={id:string;name:string;revision:number;job?:Job;attribution_batch?:{draft_id?:string;batches?:{status:string}[]}|null;processing_state?:string;book?:{id:string;index?:number}|null};
type Props={projectId:string;request:(path:string,method?:string,data?:unknown)=>Promise<any>;onClose:()=>void;onReview:(draft:{draft_id:string;name:string;book?:{id:string;index:number}})=>void;onChanged:()=>void};

export function ChapterStart({projectId,request,onClose,onReview,onChanged}:Props){
 const [p,setP]=useState<ProjectState|null>(null);const [cap,setCap]=useState<Capacity|null>(null);const [queue,setQueue]=useState<number|null>(null);
 const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const load=async()=>{const proj:ProjectState=await request('/projects/'+projectId);setP(proj);
  if(proj.processing_state==='unprocessed'){try{setCap(await request(`/projects/${projectId}/attribution/capacity`))}catch(e){setCap(null);setError((e as Error).message)}}
  if(proj.job?.status==='queued'){try{const t=await request('/model-tasks');setQueue(t.tasks?.find((x:{project_id:string})=>x.project_id===projectId)?.queue_position??null)}catch{setQueue(null)}}else setQueue(null)};
 useEffect(()=>{void load().catch(e=>setError((e as Error).message))},[projectId]);   // eslint-disable-line react-hooks/exhaustive-deps
 const running=p?.job?.status==='queued'||p?.job?.status==='running';
 useEffect(()=>{if(!running)return;const t=window.setInterval(()=>{void load().catch(()=>{})},3000);return()=>window.clearInterval(t)},[running,projectId]);   // eslint-disable-line react-hooks/exhaustive-deps
 const run=async(f:()=>Promise<void>)=>{setBusy(true);setError('');try{await f();await load();onChanged()}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 const done=(p?.attribution_batch?.batches??[]).filter(b=>b.status==='completed').length;
 const canResume=!running&&done>0&&!p?.attribution_batch?.draft_id;
 const draftReady=p?.job?.status==='completed'&&!!p?.attribution_batch?.draft_id;
 if(!p)return <div className="structure-wrap"><div className="chapter-settings"><p className="muted">{error||'读取章节…'}</p><button onClick={onClose}>关闭</button></div></div>;
 return <div className="structure-wrap"><div className="chapter-settings" role="dialog" aria-label={`处理「${p.name}」`}>
  <div className="setting-head"><strong>处理「{p.name}」</strong><small>原稿保持完整；分角色按本机与模型的上限分批跑，跑完进复核页。</small><button type="button" aria-label="关闭" onClick={onClose}>✕</button></div>
  {error&&<p role="alert" className="line-error">{error}</p>}
  {cap&&<div className="setting-page">
   <p><strong>模型</strong> {cap.model.label}{cap.model.recommended_for_machine?'（本机推荐）':''}{!cap.model.installed?' · 未安装':!cap.model.loadable?' · 这台电脑装不下，请在设置里换较小模型':''}</p>
   <p className="muted">本机内存 {cap.machine.memory_gb} GB · 单次上限 {cap.limits.chars.toLocaleString()} 字 / {cap.limits.units} 个单元 · 本章 {cap.source.chars.toLocaleString()} 字、{cap.source.units} 个单元 → 分 {cap.batches} 批{cap.batches>1?`（每批 ${cap.batch_sizes.join(' / ')} 个）`:''}</p>
   <p className="muted">预计至少 {cap.source.estimated_segments} 个片段，本机工程上限 {cap.source.segment_limit}{cap.source.estimated_segments>cap.source.segment_limit?' — 超了，请先在结构窗口把这章拆成两章':''}。</p>
   <p className="muted">{cap.explanation}</p>
  </div>}
  {p.job?.status==='failed'&&<p role="alert" className="line-error">上次处理失败：{p.job.error??'未知原因'}{done?`；已完成 ${done} 批，可以续接。`:''}</p>}
  {running&&<p>{p.job?.status==='queued'?`排队中${queue?`，前面还有 ${queue-1} 个任务`:''}`:`处理中：第 ${(p.job?.completed??0)+1} / ${p.job?.total??cap?.batches??'?'} 批`}</p>}
  {draftReady&&<p>分角色草稿已就绪：去复核页核对、确认后，这一章就成为已处理章节。</p>}
  <div className="buttons">
   {!running&&!draftReady&&cap?.model.installed&&cap?.model.loadable&&cap.source.estimated_segments<=cap.source.segment_limit&&<button type="button" className="primary" disabled={busy} onClick={()=>void run(async()=>{await request(`/projects/${projectId}/attribution/start`,'POST',{revision:p.revision,resume:false})})}>{done?'从头重跑':'开始处理'}</button>}
   {canResume&&<button type="button" className="primary" disabled={busy} onClick={()=>void run(async()=>{await request(`/projects/${projectId}/attribution/start`,'POST',{revision:p.revision,resume:true})})}>续接（已完成 {done} 批）</button>}
   {running&&<button type="button" disabled={busy} onClick={()=>void run(async()=>{await request(`/projects/${projectId}/attribution/cancel`,'POST',{})})}>取消（已完成的批次保留）</button>}
   {draftReady&&<button type="button" className="primary" onClick={()=>onReview({draft_id:p.attribution_batch!.draft_id!,name:p.name,book:p.book?.id&&p.book.index?{id:p.book.id,index:p.book.index}:undefined})}>去复核 ↗</button>}
  </div>
 </div></div>;
}
