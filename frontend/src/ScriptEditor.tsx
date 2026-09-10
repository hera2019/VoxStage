import {useState} from 'react';
type Finding={kind:string;level:'error'|'warning';index:number;excerpt:string;message:string;replace:[string,string]|null};
type Report={findings:Finding[];units:number;characters:number;blocking:boolean};
type Unit={id:string;text:string;kind:'narration'|'dialogue';speaker:string};
type Preview={preview:true;labels:{id:string;kind:string;speaker:string}[];unresolved:Unit[];report:Report;segments:number;kept:number;kept_audio:number;fresh:number};
type Props={project:{id:string;revision:number;source_script:string};request:(path:string,method?:string,data?:unknown)=>Promise<any>;onUpdated:(project:any)=>void;onClose:()=>void};

const fixable:Record<string,string>={ellipsis_dots:'改为 ……',dash_ascii:'改为 ——',ideographic_space:'删除全角空格',repeated_space:'合并空格',trailing_space:'删除行尾空白',decoration:'删除装饰符号'};

export function ScriptEditor({project,request,onUpdated,onClose}:Props){
 const [text,setText]=useState(project.source_script??'');
 const [report,setReport]=useState<Report|null>(null);
 const [preview,setPreview]=useState<Preview|null>(null);
 const [waiting,setWaiting]=useState(false);const [error,setError]=useState('');
 const edited=text!==project.source_script;
 const unresolved=preview?.unresolved??[];
 const blocked=unresolved.some(u=>!u.speaker.trim()||u.speaker.trim().toUpperCase()==='UNKNOWN');
 const base='/projects/'+project.id+'/script';
 async function run(task:()=>Promise<void>){setWaiting(true);setError('');try{await task()}catch(e){setError((e as Error).message)}finally{setWaiting(false)}}
 // Any edit invalidates a preview: never let someone apply a plan they cannot see.
 function edit(value:string){setText(value);setPreview(null);setReport(null)}
 function close(){if(edited&&!confirm('原稿改动尚未应用，关闭后会丢失。仍要关闭吗？'))return;onClose()}
 return <div className="overlay"><section className="dialog role-import" role="dialog" aria-modal="true" aria-labelledby="script-title">
  <div className="dialog-title"><h2 id="script-title">原稿</h2><button disabled={waiting} aria-label="关闭原稿" onClick={close}>✕</button></div>
  <label>剧本原文<textarea aria-label="剧本原文" rows={12} maxLength={3000} disabled={waiting} value={text} onChange={e=>edit(e.target.value)}/></label>
  <p className="muted">改完先看改动影响，再决定是否应用。没有变化的句子会保留已生成的声音。</p>
  <div className="buttons">
   <button disabled={waiting||!text.trim()} onClick={()=>void run(async()=>setReport(await request(base+'/check','POST',{source_script:text,kind:'check'})))}>检查原稿</button>
   <button disabled={waiting||!text.trim()} onClick={()=>void run(async()=>{const p=await request(base,'POST',{revision:project.revision,source_script:text});setPreview(p);setReport(p.report)})}>{waiting?'正在比对…':'查看改动影响'}</button>
  </div>

  {report&&<div className={report.findings.length?'hint':'hint'}>
   {report.characters} 字 · 预计 {report.units} 个切片
   {!report.findings.length&&' · 未发现问题'}
   {report.findings.map((f,i)=><p key={i} className={f.level==='error'?'line-error':'muted'}>
    {f.level==='error'?'必须处理：':'建议：'}{f.message}<br/><code>{f.excerpt}</code>
    {f.replace&&fixable[f.kind]&&<> <button disabled={waiting} onClick={()=>void run(async()=>{const r=await request(base+'/fix','POST',{source_script:text,kind:f.kind});edit(r.source_script)})}>{fixable[f.kind]}</button></>}
   </p>)}
  </div>}

  {preview&&<>
   <p>保留 {preview.kept} 句，其中 {preview.kept_audio} 句可直接沿用已生成的声音；需要重新生成 {preview.fresh} 句。共 {preview.segments} 句。</p>
   {unresolved.length>0&&<><div className="hint">新出现的对白需要指定角色，其余会自动沿用。</div>
    <div className="role-units">{unresolved.map(u=><article className={'role-unit '+(!u.speaker.trim()||u.speaker.trim().toUpperCase()==='UNKNOWN'?'role-unknown':'')} key={u.id}>
     <p><small>新增对白</small><br/>{u.text}</p>
     <div className="role-fields"><label>说话人<input aria-label={`${u.text.slice(0,10)} 的说话人`} value={u.speaker.toUpperCase()==='UNKNOWN'?'':u.speaker} maxLength={80} disabled={waiting}
      onChange={e=>setPreview(p=>p&&({...p,unresolved:p.unresolved.map(x=>x.id===u.id?{...x,speaker:e.target.value}:x),
       labels:p.labels.map(l=>l.id===u.id?{...l,speaker:e.target.value}:l)}))}/></label></div>
    </article>)}</div></>}
  </>}

  <div className="buttons">
   <button disabled={waiting} onClick={close}>取消</button>
   <button className="primary" disabled={waiting||!preview||blocked||report?.blocking} onClick={()=>void run(async()=>{
    onUpdated(await request(base,'POST',{revision:project.revision,source_script:text,labels:preview!.labels}));onClose()})}>
    {waiting?'正在应用…':'应用改动'}</button>
  </div>
  {error&&<p role="alert" className="line-error">{error}</p>}
 </section></div>;
}
// 最后更新：2026-09-10 · Claude Hera
