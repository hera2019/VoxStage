import {useEffect,useState} from 'react';
import {Help} from './Help';
import {tr} from './i18n';

/** An unprocessed chapter's way into the pipeline (Opus 一, last piece,
 *  2026-09-21): what this machine and the chosen model can take
 *  (`GET /projects/{id}/attribution/capacity`), start or resume the batched
 *  attribution (`POST …/attribution/start`), watch the queue and the batches,
 *  cancel, and when the draft is ready hand it to the review page; confirming
 *  there turns this same project into a processed chapter. */

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
 const saveText=()=>run(async()=>{const r=await request(`/projects/${projectId}/source`,'PATCH',{revision:p!.revision,source_script:text});setText(r.source_script);setNote(r.batches_dropped?tr("原稿已保存。之前处理到一半的批次按旧原稿做的，已作废，从头处理。"):tr("原稿已保存。"))});
 const draftReady=p?.job?.status==='completed'&&!!p?.attribution_batch?.draft_id;
 const wrap=inline?'structure-inline':'structure-wrap', box=inline?'structure-page chapter-start':'chapter-settings';
 if(!p)return <div className={wrap}><div className={box}><p className="muted">{error||tr("读取章节…")}</p><button onClick={onClose}>{inline?tr("返回"):tr("关闭")}</button></div></div>;
 // 本人 2026-09-23: the actions at the top, the facts on one line (the rest behind ?), the text filling the page;
 // and a way out — a chapter can be discarded, a loose project archived and deleted, like any other.
 const discard=()=>run(async()=>{
  if(p.book?.id){if(!confirm(tr("舍弃「{0}」？\n\n这一章的原文会删除，不能撤销；主工程少一章。",p.name)))return;const b=await request('/books/'+p.book.id);await request(`/master-books/${p.book.id}/chapters/${p.id}?revision=${b.revision??0}`,'DELETE');onGone?.(tr("「{0}」已舍弃。",p.name));return}
  if(!p.archived){await request('/projects/'+p.id,'PATCH',{revision:p.revision,archived:true});onGone?.(tr("「{0}」已归档，在「查看归档工程」里。",p.name));return}
  if(!confirm(tr("删除「{0}」？\n\n原文会删除，不能撤销。",p.name)))return;await request(`/projects/${p.id}?revision=${p.revision}`,'DELETE');onGone?.(tr("「{0}」已删除。",p.name))});
 const actions=<>
   {!running&&!draftReady&&!edited&&cap?.model.installed&&cap?.model.loadable&&cap.source.estimated_segments<=cap.source.segment_limit&&<button type="button" className="primary" disabled={busy} onClick={()=>void run(async()=>{await request(`/projects/${projectId}/attribution/start`,'POST',{revision:p.revision,resume:false})})}>{done?tr("从头重跑"):tr("开始处理")}</button>}
   {canResume&&!edited&&<button type="button" className="primary" disabled={busy} onClick={()=>void run(async()=>{await request(`/projects/${projectId}/attribution/start`,'POST',{revision:p.revision,resume:true})})}>{tr("续接（已完成 {0} 批）",done)}</button>}
   {running&&<button type="button" disabled={busy} onClick={()=>void run(async()=>{await request(`/projects/${projectId}/attribution/cancel`,'POST',{})})}>{tr("取消（已完成的批次保留）")}</button>}
   {draftReady&&<button type="button" className="primary" onClick={()=>onReview({draft_id:p.attribution_batch!.draft_id!,name:p.name,book:p.book?.id&&p.book.index?{id:p.book.id,index:p.book.index}:undefined})}>{tr("去复核 ↗")}</button>}
   {onGone&&!running&&<button type="button" className="danger" disabled={busy} title={p.book?.id?tr("这一章不要了：原文删除，主工程少一章"):p.archived?tr("删除这个工程"):tr("收进「查看归档工程」")} onClick={()=>void discard()}>{p.book?.id?tr("舍弃"):p.archived?tr("删除"):tr("归档")}</button>}
  </>;
 return <div className={wrap}><div className={box} role={inline?undefined:'dialog'} aria-label={tr("处理「{0}」",p.name)}>
  <div className="start-head"><strong>{tr("处理「{0}」",p.name)}</strong><span className="start-actions">{actions}</span>{!inline&&<button type="button" aria-label={tr("关闭")} onClick={onClose}>✕</button>}</div>
  {cap&&<p className="start-facts">{cap.model.label.replace(/（本机推荐）$/,'')}{!cap.model.installed?tr(" · 未安装"):!cap.model.loadable?tr(" · 这台电脑装不下，请在设置里换较小模型"):''}{tr(" · 本章 ")}{cap.source.chars.toLocaleString()}{tr(" 字、")}{cap.source.units}{tr(" 个单元 → 分 ")}{cap.batches}{tr(" 批 · 预计至少 ")}{cap.source.estimated_segments}{tr(" 个片段")}{cap.source.estimated_segments>cap.source.segment_limit&&<strong className="line-error">{tr(" — 超过本机上限 {0}，请先在「结构」里把这章拆成两章",cap.source.segment_limit)}</strong>}<Help>{tr("本机内存 {0} GB · 单次上限 {1} 字 / {2} 个单元{3} · 本机工程上限 {4} 个片段。{5} 原稿保持完整；跑完进复核页，确认后这一章成为已处理章节。",cap.machine.memory_gb,cap.limits.chars.toLocaleString(),cap.limits.units,cap.batches>1?tr(" · 每批 {0} 个",cap.batch_sizes.join(' / ')):'',cap.source.segment_limit,cap.explanation)}</Help></p>}
  {error&&<p role="alert" className="line-error">{error}</p>}
  {p.job?.status==='failed'&&<p role="alert" className="line-error">{tr("上次处理失败：{0}{1}",p.job.error??tr("未知原因"),done?tr("；已完成 {0} 批，可以续接。",done):'')}</p>}
  {running&&<p className="start-status">{p.job?.status==='queued'?tr("排队中{0}",queue?tr("，前面还有 {0} 个任务",queue-1):''):tr("处理中：第 {0} / {1} 批",(p.job?.completed??0)+1,p.job?.total??cap?.batches??'?')}</p>}
  {draftReady&&<p className="start-status">{tr("分角色草稿已就绪：点上面「去复核」核对、确认后，这一章就成为已处理章节。")}</p>}
  <div className="start-source-head"><span>{tr("原稿 · {0} 字",(text??'').length.toLocaleString())}</span>{edited&&<><button type="button" className="primary" disabled={busy||running||!(text??'').trim()} onClick={()=>void saveText()}>{tr("保存原稿")}</button><button type="button" disabled={busy} onClick={()=>setText(p.source_script??'')}>{tr("放弃修改")}</button>{(done>0||draftReady)&&<small className="muted">{tr("保存后，按旧原稿做过的批次和草稿会作废")}</small>}</>}{!edited&&note&&<small className="muted">{note}</small>}<Help>{tr("处理前随时可以改；处理后请用「原稿编辑」，已有的句子和声音会尽量保留。原稿有没保存的修改时，先保存再开始处理。")}</Help></div>
  <textarea className="start-source" aria-label={tr("这一章的原稿")} value={text??''} disabled={busy||running} onChange={e=>{setText(e.target.value);setNote('')}}/>
 </div></div>;
}
