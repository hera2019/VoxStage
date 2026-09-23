import {useEffect,useState} from 'react';
import {Help} from './Help';

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
type ProjectState={id:string;name:string;revision:number;source_script?:string;archived?:boolean;job?:Job;attribution_batch?:{draft_id?:string;batches?:{status:string}[]}|null;processing_state?:string;book?:{id:string;index?:number}|null};
type Props={projectId:string;request:(path:string,method?:string,data?:unknown)=>Promise<any>;onClose:()=>void;onReview:(draft:{draft_id:string;name:string;book?:{id:string;index:number}})=>void;onChanged:()=>void;inline?:boolean;onGone?:(message:string)=>void};

export function ChapterStart({projectId,request,onClose,onReview,onChanged,inline,onGone}:Props){
 const [p,setP]=useState<ProjectState|null>(null);const [cap,setCap]=useState<Capacity|null>(null);const [queue,setQueue]=useState<number|null>(null);
 const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 // The chapter's own text, always there to read and change before processing (本人 2026-09-23).
 const [text,setText]=useState<string|null>(null);const [note,setNote]=useState('');
 const load=async()=>{const proj:ProjectState=await request('/projects/'+projectId);setP(proj);setText(t=>t===null||t===(p?.source_script??null)?(proj.source_script??''):t);
  if(proj.processing_state==='unprocessed'){try{setCap(await request(`/projects/${projectId}/attribution/capacity`))}catch(e){setCap(null);setError((e as Error).message)}}
  if(proj.job?.status==='queued'){try{const t=await request('/model-tasks');setQueue(t.tasks?.find((x:{project_id:string})=>x.project_id===projectId)?.queue_position??null)}catch{setQueue(null)}}else setQueue(null)};
 useEffect(()=>{void load().catch(e=>setError((e as Error).message))},[projectId]);   // eslint-disable-line react-hooks/exhaustive-deps
 const running=p?.job?.status==='queued'||p?.job?.status==='running';
 useEffect(()=>{if(!running)return;const t=window.setInterval(()=>{void load().catch(()=>{})},3000);return()=>window.clearInterval(t)},[running,projectId]);   // eslint-disable-line react-hooks/exhaustive-deps
 const run=async(f:()=>Promise<void>)=>{setBusy(true);setError('');try{await f();await load();onChanged()}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 const done=(p?.attribution_batch?.batches??[]).filter(b=>b.status==='completed').length;
 const canResume=!running&&done>0&&!p?.attribution_batch?.draft_id;
 const edited=text!==null&&p!==null&&text!==(p.source_script??'');
 const saveText=()=>run(async()=>{const r=await request(`/projects/${projectId}/source`,'PATCH',{revision:p!.revision,source_script:text});setText(r.source_script);setNote(r.batches_dropped?'原稿已保存。之前处理到一半的批次按旧原稿做的，已作废，从头处理。':'原稿已保存。')});
 const draftReady=p?.job?.status==='completed'&&!!p?.attribution_batch?.draft_id;
 const wrap=inline?'structure-inline':'structure-wrap', box=inline?'structure-page chapter-start':'chapter-settings';
 if(!p)return <div className={wrap}><div className={box}><p className="muted">{error||'读取章节…'}</p><button onClick={onClose}>{inline?'返回':'关闭'}</button></div></div>;
 // 本人 2026-09-23: the actions at the top, the facts on one line (the rest behind ?), the text filling the page;
 // and a way out — a chapter can be discarded, a loose project archived and deleted, like any other.
 const discard=()=>run(async()=>{
  if(p.book?.id){if(!confirm(`舍弃「${p.name}」？\n\n这一章的原文会删除，不能撤销；主工程少一章。`))return;const b=await request('/books/'+p.book.id);await request(`/master-books/${p.book.id}/chapters/${p.id}?revision=${b.revision??0}`,'DELETE');onGone?.(`「${p.name}」已舍弃。`);return}
  if(!p.archived){await request('/projects/'+p.id,'PATCH',{revision:p.revision,archived:true});onGone?.(`「${p.name}」已归档，在「查看归档工程」里。`);return}
  if(!confirm(`删除「${p.name}」？\n\n原文会删除，不能撤销。`))return;await request(`/projects/${p.id}?revision=${p.revision}`,'DELETE');onGone?.(`「${p.name}」已删除。`)});
 const actions=<>
   {!running&&!draftReady&&!edited&&cap?.model.installed&&cap?.model.loadable&&cap.source.estimated_segments<=cap.source.segment_limit&&<button type="button" className="primary" disabled={busy} onClick={()=>void run(async()=>{await request(`/projects/${projectId}/attribution/start`,'POST',{revision:p.revision,resume:false})})}>{done?'从头重跑':'开始处理'}</button>}
   {canResume&&!edited&&<button type="button" className="primary" disabled={busy} onClick={()=>void run(async()=>{await request(`/projects/${projectId}/attribution/start`,'POST',{revision:p.revision,resume:true})})}>续接（已完成 {done} 批）</button>}
   {running&&<button type="button" disabled={busy} onClick={()=>void run(async()=>{await request(`/projects/${projectId}/attribution/cancel`,'POST',{})})}>取消（已完成的批次保留）</button>}
   {draftReady&&<button type="button" className="primary" onClick={()=>onReview({draft_id:p.attribution_batch!.draft_id!,name:p.name,book:p.book?.id&&p.book.index?{id:p.book.id,index:p.book.index}:undefined})}>去复核 ↗</button>}
   {onGone&&!running&&<button type="button" className="danger" disabled={busy} title={p.book?.id?'这一章不要了：原文删除，主工程少一章':p.archived?'删除这个工程':'收进「查看归档工程」'} onClick={()=>void discard()}>{p.book?.id?'舍弃':p.archived?'删除':'归档'}</button>}
  </>;
 return <div className={wrap}><div className={box} role={inline?undefined:'dialog'} aria-label={`处理「${p.name}」`}>
  <div className="start-head"><strong>处理「{p.name}」</strong><span className="start-actions">{actions}</span>{!inline&&<button type="button" aria-label="关闭" onClick={onClose}>✕</button>}</div>
  {cap&&<p className="start-facts">{cap.model.label.replace(/（本机推荐）$/,'')}{!cap.model.installed?' · 未安装':!cap.model.loadable?' · 这台电脑装不下，请在设置里换较小模型':''} · 本章 {cap.source.chars.toLocaleString()} 字、{cap.source.units} 个单元 → 分 {cap.batches} 批 · 预计至少 {cap.source.estimated_segments} 个片段{cap.source.estimated_segments>cap.source.segment_limit&&<strong className="line-error"> — 超过本机上限 {cap.source.segment_limit}，请先在「结构」里把这章拆成两章</strong>}<Help>本机内存 {cap.machine.memory_gb} GB · 单次上限 {cap.limits.chars.toLocaleString()} 字 / {cap.limits.units} 个单元{cap.batches>1?` · 每批 ${cap.batch_sizes.join(' / ')} 个`:''} · 本机工程上限 {cap.source.segment_limit} 个片段。{cap.explanation} 原稿保持完整；跑完进复核页，确认后这一章成为已处理章节。</Help></p>}
  {error&&<p role="alert" className="line-error">{error}</p>}
  {p.job?.status==='failed'&&<p role="alert" className="line-error">上次处理失败：{p.job.error??'未知原因'}{done?`；已完成 ${done} 批，可以续接。`:''}</p>}
  {running&&<p className="start-status">{p.job?.status==='queued'?`排队中${queue?`，前面还有 ${queue-1} 个任务`:''}`:`处理中：第 ${(p.job?.completed??0)+1} / ${p.job?.total??cap?.batches??'?'} 批`}</p>}
  {draftReady&&<p className="start-status">分角色草稿已就绪：点上面「去复核」核对、确认后，这一章就成为已处理章节。</p>}
  <div className="start-source-head"><span>原稿 · {(text??'').length.toLocaleString()} 字</span>{edited&&<><button type="button" className="primary" disabled={busy||running||!(text??'').trim()} onClick={()=>void saveText()}>保存原稿</button><button type="button" disabled={busy} onClick={()=>setText(p.source_script??'')}>放弃修改</button>{(done>0||draftReady)&&<small className="muted">保存后，按旧原稿做过的批次和草稿会作废</small>}</>}{!edited&&note&&<small className="muted">{note}</small>}<Help>处理前随时可以改；处理后请用「原稿编辑」，已有的句子和声音会尽量保留。原稿有没保存的修改时，先保存再开始处理。</Help></div>
  <textarea className="start-source" aria-label="这一章的原稿" value={text??''} disabled={busy||running} onChange={e=>{setText(e.target.value);setNote('')}}/>
 </div></div>;
}
