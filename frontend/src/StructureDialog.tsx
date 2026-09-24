import {useEffect,useState} from 'react';
import {tr} from './i18n';

/** The large window for a master book's structure: split a chapter, merge two
 *  adjacent ones, reorder, attach a loose project, detach a chapter, dissolve.
 *  It asks the server for a plan first (`POST /master-books/{id}/structure/plan`),
 *  shows what would change — members after, settings conflicts to resolve,
 *  identity questions, files to copy — and only then applies the same request
 *  (`…/structure/apply`, with the book revision). Plans come from
 *  runtime/book_structure.py; the endpoints are Sol's to expose. Opus 二, 2026-09-20. */

/** The large window for a master book's structure: split a chapter, merge two
 *  adjacent ones, reorder, attach a loose project, detach a chapter, dissolve.
 *  It asks the server for a plan first (`POST /master-books/{id}/structure/plan`),
 *  shows what would change — members after, settings conflicts to resolve,
 *  identity questions, files to copy — and only then applies the same request
 *  (`…/structure/apply`, with the book revision). Plans come from
 *  runtime/book_structure.py; the endpoints are Sol's to expose. Opus 二, 2026-09-20. */
type Chapter={id:string;name:string;processing_state?:string|null;book?:{index?:number}|null};
type Segment={id:string;text:string;source_start:number};
type Conflict={key:string;role?:string;left:unknown;right:unknown};
type Plan={op:string;book_revision:number;members_after:string[];chapters_after:{index:number;title:string;project_id:string}[];
  new_projects:{id:string;name:string;segments?:unknown[]|number}[];retired:string[];assets:{from:string;to:string;required?:boolean}[];
  conflicts:Conflict[];unresolved?:Conflict[];questions:{kind:string;name?:string;note?:string;map?:Record<string,string>}[];snapshot?:{note?:string}};
type Props={bookId:string;title:string;chapters:Chapter[];loose:Chapter[];request:(path:string,method?:string,data?:unknown)=>Promise<any>;onClose:()=>void;onApplied:()=>void;inline?:boolean};

const OPS:[string,string][]=[['split',tr("拆分一章")],['merge',tr("合并相邻两章")],['reorder',tr("调整顺序")],['attach',tr("加入独立工程")],['detach',tr("脱离主工程")],['dissolve',tr("解散主工程")]];
const conflictKey=(c:Conflict)=>c.role?`${c.key}:${c.role}`:c.key;
const show=(v:unknown)=>v===null||v===undefined?tr("（继承）"):typeof v==='object'?JSON.stringify(v):String(v);

export function StructureDialog({bookId,title,chapters,loose,request,onClose,onApplied,inline}:Props){
 const [op,setOp]=useState('split');const [target,setTarget]=useState(chapters[0]?.id??'');const [second,setSecond]=useState(chapters[1]?.id??'');
 const [segments,setSegments]=useState<Segment[]>([]);const [at,setAt]=useState<number|''>('');const [order,setOrder]=useState(chapters.map(c=>c.id));
 const [looseId,setLooseId]=useState(loose[0]?.id??'');const [position,setPosition]=useState(chapters.length);const [inherit,setInherit]=useState(false);
 const [resolutions,setResolutions]=useState<Record<string,string>>({});const [identities,setIdentities]=useState<Record<string,{action:'link'|'rename';name?:string}>>({});const [plan,setPlan]=useState<Plan|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const names=Object.fromEntries([...chapters,...loose].map(c=>[c.id,c.name]));
 useEffect(()=>{if(op!=='split'||!target)return;let stop=false;void request('/projects/'+target).then((p:{segments?:Segment[]})=>{if(!stop)setSegments((p.segments??[]).filter(s=>s.text.trim()))}).catch(()=>setSegments([]));return()=>{stop=true}},[op,target]);   // eslint-disable-line react-hooks/exhaustive-deps
 const body=()=>{
  if(op==='split')return {op,project_id:target,at};
  if(op==='merge'){const i=chapters.findIndex(c=>c.id===target);return {op,left_id:target,right_id:chapters[i+1]?.id??second,resolutions:Object.fromEntries(Object.entries(resolutions).map(([k,v])=>[k,v.startsWith('value:')?{value:JSON.parse(v.slice(6))}:v]))}}
  if(op==='reorder')return {op,members:order};
  if(op==='attach')return {op,project_id:looseId,position,inherit,identities};
  if(op==='detach')return {op,project_id:target};
  return {op};
 };
 const preview=async()=>{setBusy(true);setError('');try{setPlan(await request(`/master-books/${bookId}/structure/plan`,'POST',body()))}catch(e){setPlan(null);setError((e as Error).message)}finally{setBusy(false)}};
 const apply=async()=>{if(!plan)return;if(op==='dissolve'&&!confirm(tr("解散《{0}》？\n\n{1} 章都变成独立工程，这本书的记录删除（快照保留）。还没处理的章以后只能一章一章单独处理，书级的设置、人物表和整本导出都没有了。\n\n只是想删掉这本书？请用「章节」页底下的删除按钮。",title,chapters.length)))return;setBusy(true);setError('');try{await request(`/master-books/${bookId}/structure/apply`,'POST',{...body(),revision:plan.book_revision});onApplied();onClose()}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 const move=(i:number,d:number)=>{const j=i+d;if(j<0||j>=order.length)return;const next=order.slice();[next[i],next[j]]=[next[j],next[i]];setOrder(next);setPlan(null)};
 const identitiesReady=!plan||plan.questions.every(q=>q.kind!=='same_name'||(identities[q.name!]?.action==='link')||(identities[q.name!]?.action==='rename'&&(identities[q.name!]?.name??'').trim()));
 const ready=op==='split'?!!target&&at!=='':op==='merge'?!!target&&chapters.findIndex(c=>c.id===target)<chapters.length-1:op==='attach'?!!looseId:op==='detach'?!!target:true;
 return <div className={inline?'structure-inline':'structure-wrap'}><div className={inline?'structure-page':'structure-dialog'} role={inline?undefined:'dialog'} aria-label={tr("《{0}》的结构",title)}>
  <div className="setting-head"><strong>{tr("《{0}》的结构",title)}</strong><small>{tr("先看方案，再执行；原工程保留为恢复快照，声音不重生成。")}</small>{!inline&&<button type="button" aria-label={tr("关闭结构窗口")} onClick={onClose}>✕</button>}</div>
  <div role="tablist" className="setting-tabs">{OPS.map(([k,l])=><button key={k} role="tab" aria-selected={op===k} onClick={()=>{setOp(k);setPlan(null);setResolutions({})}}>{l}</button>)}</div>
  <div className="structure-form">
   {(op==='split'||op==='merge'||op==='detach')&&<label>{op==='merge'?tr("前一章"):tr("哪一章")}<select value={target} onChange={e=>{setTarget(e.target.value);setPlan(null);setAt('')}}>{chapters.map(c=><option key={c.id} value={c.id}>{c.book?.index?`${c.book.index}. `:''}{c.name}</option>)}</select></label>}
   {op==='merge'&&<p className="muted">{tr("与它后面的一章「{0}」合并；切句方式不同的两章不能合并。",names[chapters[chapters.findIndex(c=>c.id===target)+1]?.id]??'—')}</p>}
   {op==='split'&&<label>{tr("从哪一句前面分开")}<select value={String(at)} onChange={e=>{setAt(e.target.value===''?'':Number(e.target.value));setPlan(null)}}><option value="">{tr("— 选一句 —")}</option>{segments.slice(1).map((s,i)=><option key={s.id} value={s.source_start}>{String(i+2).padStart(2,'0')} {s.text.slice(0,24)}</option>)}</select><small>{tr("还没处理的章按行分；要从一句中间分，先在句子面板拆句。")}</small></label>}
   {op==='reorder'&&<ol className="structure-order">{order.map((id,i)=><li key={id}><span>{names[id]}</span><button type="button" disabled={i===0} onClick={()=>move(i,-1)}>↑</button><button type="button" disabled={i===order.length-1} onClick={()=>move(i,1)}>↓</button></li>)}</ol>}
   {op==='attach'&&<><label>{tr("独立工程")}<select value={looseId} onChange={e=>{setLooseId(e.target.value);setPlan(null)}}>{loose.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}{loose.length===0&&<option value="">{tr("（没有可加入的独立工程）")}</option>}</select></label>
     <label>{tr("插到第几章之前")}<select value={position} onChange={e=>{setPosition(Number(e.target.value));setPlan(null)}}>{chapters.map((c,i)=><option key={c.id} value={i}>{tr("{0}. {1} 之前",i+1,c.name)}</option>)}<option value={chapters.length}>{tr("放在最后")}</option></select></label>
     <label className="attach-row"><input type="checkbox" checked={inherit} onChange={e=>{setInherit(e.target.checked);setPlan(null)}}/>{tr("改为继承主工程的设置（不勾则保留它现在的有效设置）")}</label></>}
   {op==='dissolve'&&<p className="muted">{tr("全部章节变成独立工程，各自固化现在的有效设置；不删任何声音。")}</p>}
  </div>
  {error&&<p role="alert" className="line-error">{error}</p>}
  <div className="buttons"><button type="button" className="primary" disabled={busy||!ready} onClick={()=>void preview()}>{busy?'…':tr("看方案")}</button>{plan&&!plan.unresolved?.length&&<button type="button" className="primary" disabled={busy||!identitiesReady} title={identitiesReady?'':tr("先回答同名人物的问题")} onClick={()=>void apply()}>{tr("执行")}</button>}</div>
  {plan&&<div className="structure-plan">
   {plan.conflicts.length>0&&<section><strong>{tr("设置冲突（{0} 项待定）",plan.unresolved?.length??0)}</strong>{plan.conflicts.map(c=><label key={conflictKey(c)} className="setting-row"><span className="setting-name">{c.key}{c.role?` · ${c.role}`:''}<small className="setting-source">{tr("前 {0} · 后 {1}",show(c.left),show(c.right))}</small></span><select value={resolutions[conflictKey(c)]??''} onChange={e=>{setResolutions(x=>({...x,[conflictKey(c)]:e.target.value}));setPlan(null)}}><option value="">{tr("— 选 —")}</option><option value="left">{tr("用前一章的")}</option><option value="right">{tr("用后一章的")}</option><option value="inherit">{tr("改为继承")}</option></select></label>)}<p className="muted">{tr("选完再点「看方案」。")}</p></section>}
   {plan.questions.length>0&&<section><strong>{tr("要你定的")}</strong><ul>{plan.questions.map((q,i)=><li key={i}>{q.kind==='same_name'?<span className="attach-row">{tr("「")}{q.name}{tr("」书里已有同名人物：")}<select value={identities[q.name!]?.action??''} onChange={e=>{const v=e.target.value as ''|'link'|'rename';setIdentities(x=>{const y={...x};if(!v)delete y[q.name!];else y[q.name!]={action:v,name:v==='rename'?(x[q.name!]?.name??''):undefined};return y})}}><option value="">{tr("— 选 —")}</option><option value="link">{tr("是同一个人（关联）")}</option><option value="rename">{tr("另一个人，改名为…")}</option></select>{identities[q.name!]?.action==='rename'&&<input placeholder={tr("新名字")} value={identities[q.name!]?.name??''} onChange={e=>setIdentities(x=>({...x,[q.name!]:{action:'rename',name:e.target.value}}))}/>}</span>:q.kind==='new_name'?tr("「{0}」是新人物，会加进人物表",q.name):q.kind==='segment_ids_remapped'?tr("有 {0} 句编号撞了，会换新编号",Object.keys(q.map??{}).length):q.kind}</li>)}</ul></section>}
   {(plan.new_projects.length>0||plan.op==='reorder'||plan.op==='detach')&&<section><strong>{tr("之后的章节")}</strong><ol>{plan.chapters_after.map(c=><li key={c.project_id}>{c.title}{plan.new_projects.some(p=>p.id===c.project_id)?<small>{tr(" · 新")}</small>:null}</li>)}</ol></section>}
   {plan.retired.length>0&&<p className="muted">{tr("原工程 {0} 个保留为恢复快照，不再列在成员里。{1}",plan.retired.length,plan.snapshot?.note??'')}</p>}
   {plan.assets.length>0&&<p className="muted">{tr("要复制 {0} 个声音/参考文件到新工程（不删原文件）。",plan.assets.filter(a=>a.required!==false).length)}</p>}
  </div>}
 </div></div>;
}
