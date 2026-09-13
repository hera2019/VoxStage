import {useEffect,useState} from 'react';
type Unit={id:string;text:string;kind:'narration'|'dialogue';speaker:string;blank?:boolean;suggested?:string};
type Draft={draft_id:string;units:Unit[]};
type Props={request:(path:string,method?:string,data?:unknown)=>Promise<any>;onCreated:(project:any)=>Promise<void>;onClose:()=>void;seed?:{name:string;language:'zh'|'en';text:string;knownNames?:string[];book?:{id:string;index:number}}|null};
export function RoleImport({request,onCreated,onClose,seed}:Props){
 const [text,setText]=useState(seed?.text??'');const [name,setName]=useState(seed?.name??'新的故事');const [language,setLanguage]=useState<'zh'|'en'>(seed?.language??'zh');
 const [draft,setDraft]=useState<Draft|null>(null);const [waiting,setWaiting]=useState(false);const [error,setError]=useState('');
 const unknown=draft?.units.filter(u=>u.kind==='dialogue'&&(!u.speaker.trim()||u.speaker.trim().toUpperCase()==='UNKNOWN')).length??0;
 const names=[...new Set([...(seed?.knownNames??[]),...(draft?.units.filter(u=>u.kind==='dialogue').map(u=>u.speaker.trim()).filter(Boolean)??[])])].filter(n=>n.toUpperCase()!=='UNKNOWN');
 // Two people taking turns: once the reviewer has named the last two distinct
 // speakers, an unresolved line is suggested as the one who did not speak last.
 // A suggestion only -- it is shown in the field, never adopted on its own.
 const turnTaking:Record<string,string>={};{const known=(s:string)=>s.trim()&&s.trim().toUpperCase()!=='UNKNOWN';let recent:string[]=[];for(const u of draft?.units??[]){if(u.kind!=='dialogue'||u.blank)continue;if(known(u.speaker)){recent=[u.speaker.trim(),...recent.filter(n=>n!==u.speaker.trim())].slice(0,2);continue}if(recent.length===2){const s=recent[1];turnTaking[u.id]=s;recent=[s,recent[0]]}}}
 async function run(task:()=>Promise<void>){setWaiting(true);setError('');try{await task()}catch(e){setError((e as Error).message)}finally{setWaiting(false)}}
 function change(id:string,values:Partial<Unit>){setDraft(d=>d&&({...d,units:d.units.map(u=>u.id===id?{...u,...values}:u)}))}
 // Arriving from the new-project form with unlabelled text: start straight away.
 useEffect(()=>{if(seed?.text.trim()&&!draft&&!waiting)void run(async()=>setDraft(await request('/attribution/draft','POST',{script:seed.text,language:seed.language})))},[])  // eslint-disable-line react-hooks/exhaustive-deps
 return <div className="overlay"><section className="dialog role-import" role="dialog" aria-modal="true" aria-labelledby="role-import-title">
  <div className="dialog-title"><h2 id="role-import-title">{draft?'复核角色草稿':'从原文生成角色草稿'}</h2><button disabled={waiting} aria-label="关闭角色草稿" onClick={onClose}>✕</button></div>
  <label>工程名称<input value={name} maxLength={120} disabled={waiting} onChange={e=>setName(e.target.value)}/></label>
  {!draft?<><label>稿件语言<select value={language} disabled={waiting} onChange={e=>setLanguage(e.target.value as 'zh'|'en')}><option value="zh">中文</option><option value="en">English</option></select></label>
   <label>未标注角色的原文<textarea aria-label="未标注角色的原文" rows={10} maxLength={3000} disabled={waiting} value={text} onChange={e=>setText(e.target.value)}/></label>
   <p className="muted">每次最多 3000 字符。本机模型只填写标签，原文由程序保留。草稿需要人工复核。</p>
   <button className="primary wide" disabled={waiting||!text.trim()} onClick={()=>void run(async()=>setDraft(await request('/attribution/draft','POST',{script:text,language})))}>{waiting?'正在本机分角色，请稍候…':'生成角色草稿'}</button>
  </>:<><p>逐段核对旁白 / 对白和角色姓名。待指定：{unknown} 处。</p><div className="hint"><strong>这只是初步草稿，把说话人对上就够了。</strong>拆分、合并、改字、不朗读，进了工程之后在编辑页里都能做。<br/>人物称呼：{names.join('、')||'暂无对白角色'}。同一人物的不同称呼，请统一填写同一名字。</div>
   <div className="role-units">{draft.units.filter(u=>!u.blank).map((u,i)=><article className={'role-unit '+(u.kind==='dialogue'&&(!u.speaker.trim()||u.speaker.trim().toUpperCase()==='UNKNOWN')?'role-unknown':'')} key={u.id}>
    <p><small>片段 {i+1}</small><br/>{u.text}</p><div className="role-fields"><label>类型<select aria-label={`片段 ${i+1} 类型`} disabled={waiting} value={u.kind} onChange={e=>{const kind=e.target.value as Unit['kind'];change(u.id,{kind,speaker:kind==='narration'?'NARRATOR':u.speaker==='NARRATOR'?'UNKNOWN':u.speaker})}}><option value="narration">旁白</option><option value="dialogue">对白</option></select></label>
    {u.kind==='dialogue'?<label>说话人<input aria-label={`片段 ${i+1} 说话人`} disabled={waiting} value={u.speaker.trim().toUpperCase()==='UNKNOWN'?'':u.speaker} placeholder={turnTaking[u.id]?`一来一往，像是 ${turnTaking[u.id]}`:u.suggested?`模型写的是 ${u.suggested}，原文里没有这个名字，请填写`:"待指定，请填写"} maxLength={80} list="role-names" onChange={e=>change(u.id,{speaker:e.target.value||'UNKNOWN'})}/>{turnTaking[u.id]&&(!u.speaker.trim()||u.speaker.trim().toUpperCase()==='UNKNOWN')&&<button type="button" className="adopt" disabled={waiting} onClick={()=>change(u.id,{speaker:turnTaking[u.id]})}>用「{turnTaking[u.id]}」</button>}</label>:<span>旁白</span>}</div>
   </article>)}</div><datalist id="role-names">{names.filter(n=>n!=='UNKNOWN').map(n=><option key={n} value={n}/>)}</datalist>
   <div className="buttons"><button disabled={waiting} onClick={()=>{setDraft(null);setError('')}}>返回原文</button><button className="primary" disabled={waiting||unknown>0} onClick={()=>void run(async()=>{const project=await request('/attribution/confirm','POST',{name,draft_id:draft.draft_id,labels:draft.units.map(({id,kind,speaker})=>({id,kind,speaker})),book_id:seed?.book?.id,chapter_index:seed?.book?.index});await onCreated(project)})}>{waiting?'正在保存…':'已复核，创建工程'}</button></div>
  </>}{error&&<p role="alert" className="line-error">{error}</p>}
 </section></div>
}
// 最后更新：2026-09-10 · Astra
