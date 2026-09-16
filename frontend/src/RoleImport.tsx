import {useEffect,useRef,useState} from 'react';
type Unit={id:string;text:string;kind:'narration'|'dialogue';speaker:string;blank?:boolean;suggested?:string;tier?:'suggested';basis?:string;hint?:string;edited?:boolean;certain?:boolean;typing?:boolean;stand_in?:boolean;block?:number;para?:number;source?:'tag'|'model'|'mark';silent?:boolean;cast_id?:string;decided?:{edited:boolean;confirmed:boolean;source:string}};
type Cast={id:string;name:string;aliases:string[];colours:string[];sex:string;source:string;introduced?:{draft_id?:string;unit_id?:string}|null;split_from?:string};
type Decision={speaker:string;kind:'narration'|'dialogue';cast_id?:string|null;edited:boolean;confirmed:boolean;source:string};
type Draft={draft_id:string;units:Unit[];notice?:string|null;revision?:number;decisions?:Record<string,Decision>;cast?:Cast[];model?:{id:string|null;note:string}};
type Props={request:(path:string,method?:string,data?:unknown)=>Promise<any>;onCreated:(project:any)=>Promise<void>;onClose:()=>void;limit?:number;seed?:{name:string;language:'zh'|'en';text:string;knownNames?:string[];book?:{id:string;index:number};hints?:{start:number;end:number;speaker:string}[];silent?:number[]}|null};
export function RoleImport({request,onCreated,onClose,seed,limit=3000}:Props){
 const [text,setText]=useState(seed?.text??'');const [name,setName]=useState(seed?.name??'新的故事');const [language,setLanguage]=useState<'zh'|'en'>(seed?.language??'zh');
 const [draft,setDraft]=useState<Draft|null>(null);const [aliases,setAliases]=useState<Record<string,string>>({});
 const [pending,setPending]=useState<{old:string;speaker:string;ids:string[]}|null>(null);
 // Every decision the reviewer makes is saved with the draft as it is made,
 // in order, each save naming the revision it saw; the server refuses a
 // stale one with its current state and the page takes that state (Astra
 // 2026-09-16: 人工决定保存，刷新与重算保护). The draft can be resumed later.
 const revision=useRef(1);const queue=useRef<Promise<void>>(Promise.resolve());const [saving,setSaving]=useState(0);const [unsaved,setUnsaved]=useState(false);const [saveNote,setSaveNote]=useState('');
 const resumeKey=seed?(seed.book?`voxstage-draft-${seed.book.id}-${seed.book.index}`:`voxstage-draft-${seed.text.length}-${seed.text.slice(0,40)}`):'voxstage-draft-standalone';
 const [resumable,setResumable]=useState<{draft_id:string;revision:number}|null>(null);
 useEffect(()=>{try{const id=localStorage.getItem(resumeKey);if(id&&!draft)void request('/attribution/draft/'+id).then((g:{revision:number;confirmed_project_id?:string})=>{if(!g.confirmed_project_id&&g.revision>1)setResumable({draft_id:id,revision:g.revision})}).catch(()=>{})}catch{}},[]);  // eslint-disable-line react-hooks/exhaustive-deps
 function takeDraft(d:Draft){revision.current=d.revision??1;try{localStorage.setItem(resumeKey,d.draft_id)}catch{}setDraft({...d,units:d.units.map(u=>u.decided?{...u,edited:true}:u)})}
 function applyServer(r:{revision:number;decisions?:Record<string,Decision>;cast?:Cast[];units?:Unit[]}){revision.current=r.revision;setDraft(d=>d&&({...d,revision:r.revision,decisions:r.decisions??d.decisions,cast:r.cast??d.cast,units:r.units?r.units.map(u=>{const mine=d.units.find(x=>x.id===u.id);return u.decided?{...u,edited:true}:(mine?{...mine,cast_id:u.cast_id,speaker:mine.edited?mine.speaker:u.speaker}:u)}):d.units}))}
 function save(patch:Record<string,unknown>){const d=latest.current;if(!d)return;setUnsaved(true);setSaving(n=>n+1);queue.current=queue.current.then(async()=>{try{const r=await request('/attribution/draft/'+d.draft_id,'PATCH',{expected_revision:revision.current,...patch});applyServer(r);setSaveNote('')}catch(e){const err=e as Error&{status?:number;detail?:{revision:number;decisions:Record<string,Decision>}};if(err.status===409&&err.detail){applyServer({revision:err.detail.revision,decisions:err.detail.decisions});try{const g=await request('/attribution/draft/'+d.draft_id);applyServer(g)}catch{}setSaveNote('这份草稿在别处改过了，页面已按最新状态更新；刚才这一步请再做一次。')}else setSaveNote('没保存上：'+err.message+'。可以继续改，稍后会再试。')}finally{setSaving(n=>n-1)}});void queue.current.then(()=>setUnsaved(false))}
 function decide(ids:string[],speaker:string|null,kind?:Unit['kind']){save({decisions:ids.map(id=>({unit_id:id,speaker,kind,edited:true,confirmed:true}))})}
 function carryAll(){const pd=pending;if(!pd)return;setDraft(d2=>d2&&({...d2,units:d2.units.map(u=>pd.ids.includes(u.id)?{...u,speaker:pd.speaker,edited:true}:u)}));setAliases(a=>({...a,[pd.old]:pd.speaker}));const target=latest.current?.cast?.find(c=>c.name===pd.speaker||c.aliases.includes(pd.speaker));save({decisions:pd.ids.map(id=>({unit_id:id,speaker:pd.speaker,edited:true,confirmed:true})),...(target?{alias:{cast_id:target.id,alias:pd.old}}:{})});setPending(null)}
 function carryNone(){if(pending)declined.current.add(pending.old+'→'+pending.speaker);setPending(null)}
 // A back-and-forth the model got reversed (本人 2026-09-16): the reviewer moves
 // one line from A to B, and the other lines of the same exchange that the
 // program gave to A or B are offered for swapping, in one go. Only lines
 // the reviewer has not touched; only when there are at least two of them.
 const [swap,setSwap]=useState<{a:string;b:string;ids:string[]}|null>(null);
 function offerSwap(id:string,oldName:string,newName:string){const d=latest.current;if(!d||!oldName||!newName||oldName===newName)return;const me=d.units.find(u=>u.id===id);if(!me||me.block===undefined)return;const ids=d.units.filter(u=>u.id!==id&&!u.blank&&u.kind==='dialogue'&&u.block===me.block&&!u.edited&&(effective(u)===oldName||effective(u)===newName)).map(u=>u.id);if(ids.length>=2)setSwap({a:oldName,b:newName,ids});else setSwap(null)}
 function swapAll(){const sw=swap;if(!sw)return;const d=latest.current;if(!d)return;const flipped=d.units.filter(u=>sw.ids.includes(u.id)).map(u=>({id:u.id,to:effective(u)===sw.a?sw.b:sw.a}));setDraft(d2=>d2&&({...d2,units:d2.units.map(u=>{const f=flipped.find(x=>x.id===u.id);return f?{...u,speaker:f.to,edited:true}:u})}));save({decisions:flipped.map(f=>({unit_id:f.id,speaker:f.to,edited:true,confirmed:true}))});setSwap(null)}
 function renameCast(c:Cast,newName:string){const nn=newName.trim();if(!nn||nn===c.name)return;setDraft(d=>d&&({...d,units:d.units.map(u=>u.cast_id===c.id||(!u.cast_id&&u.speaker===c.name)?{...u,speaker:nn}:u),cast:d.cast?.map(x=>x.id===c.id?{...x,name:nn,aliases:[...x.aliases.filter(a=>a!==nn),c.name]}:x)}));save({rename:{cast_id:c.id,name:nn}})}
 // Review effort, recorded with the project: what the page showed when the draft arrived
 // and what the person changed, so the automation can be measured run by run.
 const started=useRef<{at:number;dialogue:number;orange:number;yellow:number;initial:Record<string,{tier:string;speaker:string}>}|null>(null);const [waiting,setWaiting]=useState(false);const [error,setError]=useState('');
 const unresolved=(s:string)=>!s.trim()||s.trim().toUpperCase()==='UNKNOWN';
 const names=[...new Set([...(seed?.knownNames??[]),...(draft?.units.filter(u=>u.kind==='dialogue').map(u=>u.speaker.trim()).filter(Boolean)??[])])].filter(n=>n.toUpperCase()!=='UNKNOWN'&&n.toUpperCase()!=='NARRATOR');
 // Two people taking turns: once the reviewer has named the last two distinct
 // speakers, an unresolved line is suggested as the one who did not speak last.
 // A suggestion only -- it is shown in the field, never adopted on its own.
 // Three tiers on the review page. A speaker the model named, or the person
 // typed: plain. A line the program filled itself — two people taking turns,
 // so the unresolved line goes to the one who did not speak last — yellow: it
 // stands unless changed, and confirming adopts it. A line nobody can place:
 // orange, and it must be chosen before the project is created.
 // Yellow comes from three places, in this order of trust: the model's own
 // judgement when it said the passage did not settle it, the way the character
 // talks in chapters a person confirmed (both filled by the server), and two
 // people taking turns (filled here). Anything the person types is plain.
 // Turn-taking stays inside one exchange (the server numbers them; a long
 // stretch of narration or a change of time or place starts a new one) and
 // anchors only on lines that are settled — by the person, the model with
 // certainty, a tag or a stand-in — never on another guess (Astra 2026-09-15).
 const turnTaking:Record<string,string>={};{let recent:string[]=[];let block:number|undefined;for(const u of draft?.units??[]){if(u.kind!=='dialogue'||u.blank)continue;if(u.block!==block){recent=[];block=u.block}if(!unresolved(u.speaker)){const anchor=u.edited||u.tier!=='suggested'||u.stand_in;if(anchor)recent=[u.speaker.trim(),...recent.filter(n=>n!==u.speaker.trim())].slice(0,2);continue}if(recent.length===2){const s=recent[1];turnTaking[u.id]=s;recent=[s,recent[0]]}}}
 const effective=(u:Unit)=>u.edited?(unresolved(u.speaker)?'':u.speaker.trim()):unresolved(u.speaker)?(turnTaking[u.id]??''):u.speaker.trim();
 const tier=(u:Unit)=>u.kind!=='dialogue'?'':u.edited?(unresolved(u.speaker)?'unknown':'named'):unresolved(u.speaker)?(turnTaking[u.id]?'suggested':'unknown'):(u.tier==='suggested'?'suggested':'named');
 const basis=(u:Unit)=>u.tier==='suggested'&&!u.edited&&!unresolved(u.speaker)?(u.basis??'程序填的'):turnTaking[u.id]&&unresolved(u.speaker)?'按一来一往填的'+(u.hint&&u.hint!==turnTaking[u.id]?`（说话习惯倒像 ${u.hint}）`:''):'';
 const unknown=draft?.units.filter(u=>!u.blank&&tier(u)==='unknown').length??0;const suggestedCount=draft?.units.filter(u=>!u.blank&&tier(u)==='suggested').length??0;
 async function run(task:()=>Promise<void>){setWaiting(true);setError('');try{await task()}catch(e){setError((e as Error).message)}finally{setWaiting(false)}}
 function change(id:string,values:Partial<Unit>){setDraft(d=>d&&({...d,units:d.units.map(u=>u.id===id?{...u,...values}:u)}))}
 // Learn as the reviewer works: once a name is settled by hand, every line still
 // yellow or orange is scored again against the settled ones (plus the book's
 // confirmed chapters) — the same habits that filled the first suggestions.
 const resuggest=useRef<ReturnType<typeof setTimeout>|null>(null);const declined=useRef<Set<string>>(new Set());const latest=useRef<Draft|null>(null);latest.current=draft;
 function settle(id:string,speaker:string){
  const d=latest.current;const was=d?.units.find(u=>u.id===id);const old=was?effective(was):'';
  change(id,{speaker:speaker||'UNKNOWN',edited:true});decide([id],speaker||'UNKNOWN');offerSwap(id,old,speaker);
  // 老板娘 and 陈小雪 are one person: renaming one line's 老板娘 to 陈小雪 offers to
  // carry every other 老板娘 on the page along, and the pair is remembered as an alias
  // for the book (applied to later drafts) when the project is created.
  // Asked only when the change looks like one name for the same person — the old
  // name is not an established character, and it is a short title (姐, 娘), or
  // shares a character with the new one (老板娘 → 娘), or is used on several
  // lines and the new name is established. A single line moved from one real
  // character to another is a correction, and nobody is asked.
  if(old&&speaker&&old!==speaker&&d&&!declined.current.has(old+'→'+speaker)){
   const established=new Set([...(seed?.knownNames??[]),...d.units.filter(u=>u.edited&&u.id!==id&&!unresolved(u.speaker)).map(u=>u.speaker.trim())]);
   const others=d.units.filter(u=>u.id!==id&&u.kind==='dialogue'&&!u.blank&&effective(u)===old);
   const shares=[...old].some(ch=>speaker.includes(ch));
   const aliasLike=!established.has(old)&&(old.length<=2||shares||(others.length>=3&&established.has(speaker)));
   // Not a popup: the offer waits in a bar at the foot of the list, so the
   // reviewer can scroll down and look at those lines first (本人 2026-09-16).
   if(others.length&&aliasLike)setPending({old,speaker,ids:others.map(o=>o.id)});
  }
  if(resuggest.current)clearTimeout(resuggest.current);
  resuggest.current=setTimeout(()=>{
   const d=latest.current;if(!d)return;
   const units=d.units.filter(u=>!u.blank&&u.kind==='dialogue').map(u=>({id:u.id,text:u.text,kind:u.kind,speaker:u.edited?u.speaker:(u.tier==='suggested'&&!u.stand_in?'':u.speaker),fixed:u.edited?!unresolved(u.speaker):(u.tier!=='suggested'&&!unresolved(u.speaker)),turn:(!u.edited&&unresolved(u.speaker)&&turnTaking[u.id])||'',source:u.edited?'person':(u.source==='tag'?'tag':(u.tier!=='suggested'&&!unresolved(u.speaker)?'model':'guess'))}));
   const asked=revision.current;request('/attribution/suggest','POST',{book_id:seed?.book?.id,units,draft_id:d.draft_id,revision:asked}).then((r:{suggestions:Record<string,{speaker:string;fill:boolean;basis?:string;hint?:string}>;revision?:number|null})=>{if(revision.current!==asked)return;
    setDraft(d2=>d2&&({...d2,units:d2.units.map(u=>{
     if(u.edited||u.kind!=='dialogue'||u.blank||u.stand_in)return u;   // a stand-in (众人/某人) stays until renamed by hand
     const sg=r.suggestions[u.id];if(!sg)return u;
     if(u.tier==='suggested'||unresolved(u.speaker)){
      if(sg.fill&&sg.basis!=='按一来一往填的')return {...u,speaker:sg.speaker,tier:'suggested' as const,basis:sg.basis??'按已确认的说话习惯，像是',hint:undefined};
      if(sg.basis==='按一来一往填的')return {...u,speaker:unresolved(u.speaker)?'UNKNOWN':u.speaker,hint:sg.hint};   // the page's own guess stands; habits only hint
      return {...u,speaker:unresolved(u.speaker)?'UNKNOWN':u.speaker,hint:sg.speaker};
     }
     return u;
    })}));
   }).catch(()=>{});
  },400);
 }
 // Arriving from the new-project form with unlabelled text: start straight away.
 useEffect(()=>{let stop=false;try{if(localStorage.getItem(resumeKey))stop=true}catch{}if(!stop&&seed?.text.trim()&&!draft&&!waiting)void run(async()=>takeDraft(await request('/attribution/draft','POST',{script:seed.text,language:seed.language,book_id:seed.book?.id,hints:seed.hints,silent:seed.silent})))},[])  // eslint-disable-line react-hooks/exhaustive-deps
 return <div className="overlay"><section className="dialog role-import" role="dialog" aria-modal="true" aria-labelledby="role-import-title">
  <div className="dialog-title"><h2 id="role-import-title">{draft?'复核角色草稿':'从原文生成角色草稿'}</h2><button disabled={waiting} aria-label="关闭角色草稿" onClick={onClose}>✕</button></div>
  <label>工程名称<input value={name} maxLength={120} disabled={waiting} onChange={e=>setName(e.target.value)}/></label>
  {!draft&&resumable&&<div className="carry-bar" role="status"><span>上次的复核还没做完（第 {resumable.revision} 版，改动已保存）。</span><button type="button" className="primary" disabled={waiting} onClick={()=>void run(async()=>{takeDraft(await request('/attribution/draft/'+resumable.draft_id));setResumable(null)})}>继续上次的复核</button><button type="button" disabled={waiting} onClick={()=>{try{localStorage.removeItem(resumeKey)}catch{}setResumable(null)}}>重新开始</button></div>}
  {!draft?<><label>稿件语言<select value={language} disabled={waiting} onChange={e=>setLanguage(e.target.value as 'zh'|'en')}><option value="zh">中文</option><option value="en">English</option></select></label>
   <label>未标注角色的原文<textarea aria-label="未标注角色的原文" rows={10} maxLength={limit} disabled={waiting} value={text} onChange={e=>setText(e.target.value)}/></label>
   <p className="muted">每次最多 {limit} 字符（按这台机器的内存定）。本机模型只填写标签，原文由程序保留。草稿需要人工复核。</p>
   <button className="primary wide" disabled={waiting||!text.trim()} onClick={()=>void run(async()=>takeDraft(await request('/attribution/draft','POST',{script:text,language,book_id:seed?.book?.id,hints:seed?.text===text?seed?.hints:undefined,silent:seed?.text===text?seed?.silent:undefined})))}>{waiting?'正在本机分角色，请稍候…':'生成角色草稿'}</button>
  </>:<>{(()=>{if(!started.current){const ds=draft.units.filter(u=>!u.blank&&u.kind==='dialogue');started.current={at:Date.now(),dialogue:ds.length,orange:ds.filter(u=>tier(u)==='unknown').length,yellow:ds.filter(u=>tier(u)==='suggested').length,initial:Object.fromEntries(draft.units.map(u=>[u.id,{tier:tier(u),speaker:effective(u)}]))}}return null})()}<p>逐段核对旁白 / 对白和角色姓名。<span className="tier-orange">橙色 {unknown} 处</span>要你选人；<span className="tier-yellow">黄色 {suggestedCount} 处</span>是程序按一来一往填的，不改就照它。</p>{draft.notice&&<p role="alert" className="line-error">{draft.notice}</p>}{draft.model&&<p className="muted">分角色：{draft.model.note}</p>}<div className="hint"><strong>这只是初步草稿，把说话人对上就够了。</strong>拆分、合并、改字、不朗读，进了工程之后在编辑页里都能做。<br/>人物称呼：{names.join('、')||'暂无对白角色'}。同一人物的不同称呼，请统一填写同一名字。</div>
   {draft.cast&&draft.cast.length>0&&<section className="cast-table" aria-label="人物表"><div className="cast-head"><strong>人物表</strong><small>名字可以改，改了这个人的句子都跟着改；别名是原文里的其他称呼。</small><span className={'save-state '+(saving||unsaved?'busy':'')}>{saving||unsaved?'保存中…':'已保存'}</span></div>
    <table><thead><tr><th>名字</th><th>别名</th><th>出处</th><th>来源</th>{draft.cast.some(c=>c.colours.length)&&<th>颜色</th>}</tr></thead><tbody>{draft.cast.map(c=>{const first=draft.units.findIndex(u=>!u.blank&&(u.cast_id===c.id||u.speaker===c.name));const index=draft.units.filter(u=>!u.blank).findIndex(u=>u.cast_id===c.id||u.speaker===c.name);return <tr key={c.id}><td><input aria-label={'人物 '+c.name+' 的名字'} defaultValue={c.name} maxLength={80} disabled={waiting} onBlur={e=>renameCast(c,e.target.value)} onKeyDown={e=>{if(e.key==='Enter')(e.target as HTMLInputElement).blur()}}/></td><td>{c.aliases.join('、')||'—'}</td><td>{index>=0?`片段 ${index+1}`:(c.introduced?.unit_id?'本书前面的章节':'—')}</td><td>{({person:'你定的',mark:'原稿里标的',tag:'叙述点名',model:'模型',rule:'程序推断',alias:'别名',template:'模板'} as Record<string,string>)[c.source]??c.source}</td>{draft.cast!.some(x=>x.colours.length)&&<td>{c.colours.map(col=><span key={col} className="colour-chip" style={{background:col==='none'?'#000':col}} title={col}/>)}</td>}{first<0&&null}</tr>})}</tbody></table>
    {saveNote&&<p role="alert" className="line-error">{saveNote}</p>}</section>}
   <div className="role-units">{draft.units.filter(u=>!u.blank).map((u,i,list)=><article className={'role-unit '+(tier(u)==='unknown'?'role-unknown':tier(u)==='suggested'?'role-suggested':'')+(pending?.ids.includes(u.id)?' role-carry':'')+(i>0&&list[i-1].para===u.para?' same-para':' para-first')} key={u.id}>
    <p><small>片段 {i+1}{u.silent&&<span className="unit-tag">不朗读（标题）</span>}{u.source==='mark'&&<span className="unit-tag">原稿里标的</span>}</small><br/>{u.text}</p><div className="role-fields"><label>类型<select aria-label={`片段 ${i+1} 类型`} disabled={waiting} value={u.kind} onChange={e=>{const kind=e.target.value as Unit['kind'];const sp=kind==='narration'?'NARRATOR':u.speaker==='NARRATOR'?'UNKNOWN':u.speaker;change(u.id,{kind,speaker:sp,edited:true});decide([u.id],kind==='dialogue'?sp:null,kind)}}><option value="narration">旁白</option><option value="dialogue">对白</option></select></label>
    {u.kind==='dialogue'?<label>说话人{tier(u)==='suggested'&&<small>{basis(u)}，不确定也可以照它；改了就按你的</small>}{tier(u)==='unknown'&&<small>{u.hint?`像是 ${u.hint}，但把握不大——请选一个人物`:u.suggested?`模型写的是 ${u.suggested}，原文里没有这个名字——请选一个人物`:'待指定，请选一个人物'}</small>}
     {u.typing?<input autoFocus aria-label={`片段 ${i+1} 新人名`} disabled={waiting} placeholder="输入新人名，回车确定" maxLength={80} onKeyDown={e=>{if(e.key==='Enter'){const v=(e.target as HTMLInputElement).value.trim();change(u.id,{typing:false});if(v)settle(u.id,v)}if(e.key==='Escape')change(u.id,{typing:false})}} onBlur={e=>{const v=e.target.value.trim();change(u.id,{typing:false});if(v)settle(u.id,v)}}/>
     :<select aria-label={`片段 ${i+1} 说话人`} disabled={waiting} value={effective(u)} onChange={e=>{if(e.target.value==='__new__')change(u.id,{typing:true});else settle(u.id,e.target.value)}}><option value="">— 待指定 —</option>{[...new Set([...names,effective(u)].filter(Boolean))].map(n=><option key={n} value={n}>{n}</option>)}<option value="__new__">＋ 新人名…</option></select>}</label>:<span>旁白</span>}</div>
   </article>)}</div>
   {swap&&<div className="carry-bar" role="status"><span>这一场里程序给「{swap.a}」和「{swap.b}」的其余 {swap.ids.length} 句也对调吗？（一来一往搞反了，常见。）</span><button type="button" className="primary" disabled={waiting} onClick={swapAll}>对调</button><button type="button" disabled={waiting} onClick={()=>setSwap(null)}>不用</button></div>}
   {pending&&<div className="carry-bar" role="status"><span>其余 {pending.ids.length} 处「{pending.old}」也改成「{pending.speaker}」吗？可以先翻下去看看那些句子。同意的话，以后这本书的草稿里「{pending.old}」会自动当作「{pending.speaker}」。</span><button type="button" className="primary" disabled={waiting} onClick={carryAll}>都改</button><button type="button" disabled={waiting} onClick={carryNone}>不改</button></div>}
   <div className="buttons"><button disabled={waiting} onClick={()=>{setDraft(null);setError('')}}>返回原文</button><button className="primary" disabled={waiting||unknown>0||saving>0} onClick={()=>void run(async()=>{await queue.current;const st=started.current;const changed=draft.units.filter(u=>!u.blank&&st&&st.initial[u.id]&&(st.initial[u.id].speaker!==(u.kind==='dialogue'?effective(u):u.speaker)||(st.initial[u.id].tier===''?'narration':'dialogue')!==u.kind));const review=st?{seconds:Math.round((Date.now()-st.at)/1000),dialogue:st.dialogue,orange:st.orange,yellow:st.yellow,changed:changed.length,named_changed:changed.filter(u=>st.initial[u.id].tier==='named').length,yellow_changed:changed.filter(u=>st.initial[u.id].tier==='suggested').length,orange_filled:changed.filter(u=>st.initial[u.id].tier==='unknown').length}:undefined;const project=await request('/attribution/confirm','POST',{name,draft_id:draft.draft_id,labels:draft.units.map(u=>({id:u.id,kind:u.kind,speaker:u.kind==='dialogue'?(effective(u)||'UNKNOWN'):u.speaker})),book_id:seed?.book?.id,chapter_index:seed?.book?.index,aliases,review,silent:seed?.text===text?seed?.silent:undefined,expected_revision:revision.current});try{localStorage.removeItem(resumeKey)}catch{}await onCreated({...project,review})})}>{waiting?'正在保存…':'已复核，创建工程'}</button></div>
  </>}{error&&<p role="alert" className="line-error">{error}</p>}
 </section></div>
}
// 最后更新：2026-09-10 · Astra
