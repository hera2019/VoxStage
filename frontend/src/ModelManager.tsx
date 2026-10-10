import {useEffect,useRef,useState} from 'react';
import {tr} from './i18n';

type Job={status?:string;completed?:number;total?:number;file?:string;error?:string};
type Model={id:string;title:string;purpose:string;repo:string;revision:string;estimated_bytes:number;minimum_gb:number;recommended:boolean;compatible:boolean;present:boolean;verified:boolean;license:string;license_url:string;job:Job};
type Catalog={memory_gb:number;free_bytes:number;recommendation:string;below_minimum:boolean;active:boolean;first_run:boolean;models:Model[]};
type Request=(path:string,method?:string,data?:unknown)=>Promise<any>;
const size=(n:number)=>n>=1e9?(n/1e9).toFixed(1)+' GB':Math.round(n/1e6)+' MB';
const state=(s?:string)=>({preparing:tr("准备下载"),downloading:tr("下载中"),verifying:tr("校验中"),installing:tr("登记中"),paused:tr("已暂停"),ready:tr("校验完成"),error:tr("任务未完成")} as Record<string,string>)[s??'']??'';

export function ModelManager({open,request,onClose,onActivated}:{open:boolean;request:Request;onClose:()=>void;onActivated:()=>void}){
 const [catalog,setCatalog]=useState<Catalog>();const [selected,setSelected]=useState<string[]>([]);
 const [error,setError]=useState('');const [working,setWorking]=useState(false);
 const [queue,setQueue]=useState<string[]>([]);const initialized=useRef(false);const driving=useRef(false);const lastStarted=useRef('');
 const [message,setMessage]=useState('');
 useEffect(()=>{if(!open&&!queue.length&&!catalog?.active)return;let alive=true;const poll=async()=>{try{const value:Catalog=await request('/models');if(!alive)return;setCatalog(value);if(!initialized.current){initialized.current=true;setSelected(value.models.filter(m=>m.recommended&&!m.verified&&m.compatible).map(m=>m.id))}}catch(e){if(alive)setError(String((e as Error).message))}};void poll();const timer=window.setInterval(()=>void poll(),750);return()=>{alive=false;window.clearInterval(timer)}},[request,open,queue.length,catalog?.active]);
 useEffect(()=>{if(!catalog||catalog.active||!queue.length||driving.current)return;
   // A paused/error job stops the queue until the user explicitly resumes.
   const failed=catalog.models.find(m=>m.id===lastStarted.current&&['paused','error'].includes(m.job.status??''));
   if(failed){setQueue([]);return}
   const remaining=queue.filter(id=>!catalog.models.find(m=>m.id===id)?.verified);
   if(!remaining.length){setQueue([]);setMessage(tr("所选模型已完成校验，可以启用。"));return}
   driving.current=true;lastStarted.current=remaining[0];void request('/models/'+remaining[0]+'/download','POST',{}).then(()=>request('/models')).then(value=>setCatalog(value)).catch(e=>{setError(e.message);setQueue([])}).finally(()=>{driving.current=false});
 },[catalog,queue,request]);
 const act=async(task:()=>Promise<unknown>)=>{setWorking(true);setError('');setMessage('');try{await task();setCatalog(await request('/models'))}catch(e){setError((e as Error).message)}finally{setWorking(false)}};
 const pick=(id:string,on:boolean)=>setSelected(s=>on?[...s,id]:s.filter(x=>x!==id));
 const bytes=catalog?.models.filter(m=>selected.includes(m.id)&&!m.verified).reduce((n,m)=>n+m.estimated_bytes,0)??0;
 return <div className="model-manager-backdrop" hidden={!open}><section className="model-manager" role="dialog" aria-modal="true" aria-labelledby="model-manager-title">
   <header><div><h2 id="model-manager-title">{tr("模型管理")}</h2><p>{tr("首次使用先选模型，再下载到这台 Mac。工程内容不会上传。")}</p></div><button aria-label={tr("关闭")} onClick={onClose}>✕</button></header>
   {!catalog?<p>{tr("正在读取本机配置…")}</p>:<>
   <p className="model-summary">{tr("内存 {0} GB · 磁盘剩余 {1}",catalog.memory_gb,size(catalog.free_bytes))} · {catalog.recommendation==='recommended'?tr("32 GB 推荐套"):tr("16 GB 最低套")}</p>
   {catalog.below_minimum&&<p role="alert">{tr("本机内存低于 16 GB，模型运行尚未验证；可以先编辑工程。")}</p>}
   <p>{tr("下列大小为估算；下载时显示实际字节数。模型不会同时装入内存。")}</p>
   <div className="model-selection"><button disabled={catalog.active||working} onClick={()=>setSelected(catalog.models.filter(m=>m.recommended&&!m.verified&&m.compatible).map(m=>m.id))}>{tr("选择本机推荐")}</button><span>{tr("所选约 {0}",size(bytes))}</span></div>
   {bytes>catalog.free_bytes&&<p role="alert">{tr("所选模型的估算大小超过磁盘余量，请减少选择或释放空间。")}</p>}
   <div className="model-list">{catalog.models.map(m=>{
     const job=m.job;const pct=job.total?Math.min(100,Math.round((job.completed??0)/job.total*100)):0;
     const active=['preparing','downloading','verifying','installing'].includes(job.status??'');
     return <article className="model-card" key={m.id}>
       <label><input type="checkbox" checked={selected.includes(m.id)} disabled={m.verified||!m.compatible||catalog.active||working} onChange={e=>pick(m.id,e.target.checked)}/><strong>{m.title}</strong>{m.recommended&&<small>{tr("本机推荐")}</small>}</label>
       <p>{tr(m.purpose)}</p><small>{tr("约 {0} · 至少 {1} GB 内存",size(m.estimated_bytes),m.minimum_gb)} · <a href={m.license_url} target="_blank" rel="noreferrer">{m.license}</a></small>
       {!m.compatible&&<p>{tr("本机内存不足以使用这个模型。")}</p>}
       <div className="model-status" aria-live="polite">{m.verified?tr("已校验 · 可用"):state(job.status==='ready'?undefined:job.status)||(m.present?tr("已有文件 · 请校验"):tr("未下载"))}</div>
       {active&&<><progress value={job.total?job.completed:undefined} max={job.total||1}/><small>{job.total?size(job.completed??0)+' / '+size(job.total)+' · '+pct+'%':tr("正在读取文件信息…")}{job.file?' · '+job.file:''}</small></>}
       {job.error&&<p role="alert">{tr(job.error)}</p>}
       <div className="model-actions">{!m.verified&&<button disabled={catalog.active||working||!m.compatible} onClick={()=>void act(async()=>{setQueue([]);await request('/models/'+m.id+'/download','POST',{})})}>{['paused','error'].includes(job.status??'')?tr("续传 / 修复"):tr("下载")}</button>}
       {m.present&&<button disabled={catalog.active||working} onClick={()=>void act(()=>request('/models/'+m.id+'/verify','POST',{}))}>{tr("校验已有文件")}</button>}
       {active&&<button disabled={working} onClick={()=>void act(async()=>{setQueue([]);await request('/models/pause','POST',{})})}>{tr("暂停")}</button>}</div>
     </article>})}</div>
   <footer><button disabled={catalog.active||working||!selected.some(id=>!catalog.models.find(m=>m.id===id)?.verified)} onClick={()=>{setError('');setMessage('');void act(async()=>{setQueue([]);const ids=selected.filter(id=>!catalog.models.find(m=>m.id===id)?.verified);lastStarted.current=ids[0];await request('/models/'+ids[0]+'/download','POST',{});setQueue(ids)})}}>{tr("下载所选模型")}</button>
   <button disabled={catalog.active||working||!catalog.models.some(m=>m.verified)} onClick={()=>void act(async()=>{await request('/models/activate','POST',{});onActivated();setMessage(tr("已启用完成校验的模型。"))})}>{tr("启用已下载模型")}</button><button onClick={onClose}>{tr("先编辑工程")}</button></footer>
   <p className="muted">{tr("暂停或退出后保留下载缓存，下次可续传。识别和分角色还需要安装版自带的运行程序。")}</p>
   </>}{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
 </section></div>
}
