import {useState} from 'react';
type Finding={kind:string;level:'error'|'warning';index:number;excerpt:string;message:string;replace:[string,string]|null};
type Report={findings:Finding[];units:number;characters:number;blocking:boolean};
type Unit={id:string;text:string;kind:'narration'|'dialogue';speaker:string};
type Preview={preview:true;labels:{id:string;kind:string;speaker:string}[];unresolved:Unit[];report:Report;segments:number;kept:number;kept_audio:number;fresh:number};
type Props={project:{id:string;revision:number;source_script:string;language:'zh'|'en';voices:Record<string,string>;segments:{text:string}[]};request:(path:string,method?:string,data?:unknown)=>Promise<any>;onUpdated:(project:any)=>void;onClose:()=>void};

const fixable:Record<string,string>={ellipsis_dots:'改为 ……',dash_ascii:'改为 ——',ideographic_space:'删除全角空格',repeated_space:'合并空格',trailing_space:'删除行尾空白',decoration:'删除装饰符号'};

export function ScriptEditor({project,request,onUpdated,onClose}:Props){
 const [text,setText]=useState(project.source_script??'');
 const [report,setReport]=useState<Report|null>(null);
 const [preview,setPreview]=useState<Preview|null>(null);
 const [waiting,setWaiting]=useState(false);const [error,setError]=useState('');
 const joined=project.segments.map(s=>s.text).join('');
 // Projects edited before the script was kept in sync can show stale prose.
 const stale=joined!==project.source_script;
 const edited=text!==project.source_script;
 const unresolved=preview?.unresolved??[];
 const blocked=unresolved.some(u=>!u.speaker.trim()||u.speaker.trim().toUpperCase()==='UNKNOWN');
 const base='/projects/'+project.id+'/script';
 const narrator=project.language==='zh'?'旁白':'Narrator';
 // Known speakers are almost always the answer; the narrator covers written
 // notices the model mistook for speech. No value is pre-filled: a guess shown
 // as an answer is the one thing review is supposed to prevent.
 const known=[narrator,...Object.keys(project.voices).filter(x=>x!==narrator)];
 function assign(id:string,speaker:string){setPreview(p=>p&&({...p,
  unresolved:p.unresolved.map(x=>x.id===id?{...x,speaker,kind:speaker===narrator?'narration':'dialogue'}:x),
  labels:p.labels.map(l=>l.id===id?{...l,speaker,kind:speaker===narrator?'narration':'dialogue'}:l)}))}
 async function run(task:()=>Promise<void>){setWaiting(true);setError('');try{await task()}catch(e){setError((e as Error).message)}finally{setWaiting(false)}}
 // Any edit invalidates a preview: never let someone apply a plan they cannot see.
 function edit(value:string){setText(value);setPreview(null);setReport(null)}
 function close(){if(edited&&!confirm('原稿改动尚未应用，关闭后会丢失。仍要关闭吗？'))return;onClose()}
 return <div className="overlay"><section className="dialog role-import" role="dialog" aria-modal="true" aria-labelledby="script-title">
  <div className="dialog-title"><h2 id="script-title">原稿编辑</h2><button disabled={waiting} aria-label="关闭原稿编辑" onClick={close}>✕</button></div>
  <label>剧本原文<textarea aria-label="剧本原文" rows={12} maxLength={3000} disabled={waiting} value={text} onChange={e=>edit(e.target.value)}/></label>
  {stale&&<p className="line-error">这份原稿与当前句子不一致（可能是较早版本留下的）。直接应用会覆盖你后来的逐句修改。
   <button disabled={waiting} onClick={()=>edit(joined)}>改用当前句子的文字</button></p>}
  <p className="muted">改完先看改动影响，再决定是否应用。没有变化的句子会保留已生成的声音。</p>

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
   {unresolved.length>0&&<><div className="hint">新出现的这几句需要指定说话人，其余会自动沿用。如果它其实是念出来的文字（告示、纸条、书上的话），选「{narrator}」。</div>
    <div className="role-units">{unresolved.map(u=>{const named=u.speaker.trim()&&u.speaker.trim().toUpperCase()!=='UNKNOWN';
     return <article className={'role-unit '+(named?'':'role-unknown')} key={u.id}>
     <p><small>{named?(u.kind==='narration'?'已设为'+narrator:'说话人：'+u.speaker):'待指定'}</small><br/>{u.text}</p>
     <div className="speaker-choices">{known.map(name=><button key={name} type="button" disabled={waiting}
       className={u.speaker.trim()===name?'chosen':''} onClick={()=>assign(u.id,name)}>{name}</button>)}</div>
     <div className="role-fields"><label>或填写新角色<input aria-label={`${u.text.slice(0,10)} 的说话人`}
      value={u.speaker.toUpperCase()==='UNKNOWN'?'':u.speaker} maxLength={80} disabled={waiting}
      placeholder="新角色名称" onChange={e=>assign(u.id,e.target.value)}/></label></div>
    </article>})}</div></>}
  </>}

  <div className="buttons script-actions">
   <button disabled={waiting} onClick={close}>取消</button>
   <button disabled={waiting||!text.trim()} onClick={()=>void run(async()=>setReport(await request(base+'/check','POST',{source_script:text,kind:'check'})))}>检查原稿</button>
   <button disabled={waiting||!text.trim()} onClick={()=>void run(async()=>{const p=await request(base,'POST',{revision:project.revision,source_script:text});setPreview(p);setReport(p.report)})}>{waiting?'正在比对…':'查看改动影响'}</button>
   <button className="primary" disabled={waiting||!preview||blocked||report?.blocking} onClick={()=>void run(async()=>{
    onUpdated(await request(base,'POST',{revision:project.revision,source_script:text,labels:preview!.labels}));onClose()})}>
    {waiting?'正在应用…':'应用改动'}</button>
  </div>
  {error&&<p role="alert" className="line-error">{error}</p>}
 </section></div>;
}
// 最后更新：2026-09-10 · Claude Hera
