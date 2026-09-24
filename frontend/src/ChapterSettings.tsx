import {useEffect,useState} from 'react';
import {tr} from './i18n';

/** Paged settings for a chapter (sub-project) or a master book, against the
 *  v1 contract (docs/api-book-project-v1.md): every value shown is the
 *  *effective* one with where it comes from; a change writes a local
 *  override; 恢复继承 deletes it. 0, an empty list and an empty map are values
 *  — only `inherit` removes an override. Opus 一, 2026-09-20. */

/** Paged settings for a chapter (sub-project) or a master book, against the
 *  v1 contract (docs/api-book-project-v1.md): every value shown is the
 *  *effective* one with where it comes from; a change writes a local
 *  override; 恢复继承 deletes it. 0, an empty list and an empty map are values
 *  — only `inherit` removes an override. Opus 一, 2026-09-20. */
type Source={level:string;id?:string;roles?:Record<string,{level:string;id?:string}>};
type Payload={project_id?:string;book_id?:string;project_revision?:number;book_revision?:number|null;revision?:number;
  overrides?:Record<string,unknown>;effective?:Record<string,unknown>;settings?:Record<string,unknown>;sources?:Record<string,Source>};
type Props={kind:'project'|'book';id:string;request:(path:string,method?:string,data?:unknown)=>Promise<any>;voiceName?:(id:string|undefined)=>string;
  presetModels?:string[];cloneModels?:string[];chapterIds?:string[];inline?:boolean;onClose:()=>void};

const PAGES:[string,string[]][]=[[tr("角色声音"),['voices','colors','sexes','muted_speakers']],[tr("朗读与停顿"),['preset_model','clone_model','speech_rate','pause_ms','ellipsis_pause_ms','color_scope']],[tr("发音"),['lexicon']],[tr("导出"),[]]];
const LABELS:Record<string,string>={voices:tr("角色声音"),colors:tr("角色颜色"),sexes:tr("角色性别"),muted_speakers:tr("不朗读的角色"),preset_model:tr("预设音色模型"),clone_model:tr("固定声线模型"),speech_rate:tr("语速"),pause_ms:tr("句间停顿（毫秒）"),ellipsis_pause_ms:tr("省略号、破折号处停顿"),color_scope:tr("颜色用在"),lexicon:tr("发音词典")};
const LEVEL:Record<string,string>={project:tr("本章"),local:tr("本章"),book:tr("主工程"),master:tr("主工程"),default:tr("应用默认"),app:tr("应用默认"),machine:tr("本机默认")};

// The same dictionary format as the project page (本人 2026-09-23: 两套格式，不能直接复制粘贴):
// one entry a line, 写法→读法 (-> and => accepted too).
export const lexiconToText=(lexicon:Record<string,string>|undefined)=>Object.entries(lexicon??{}).map(([a,b])=>a+'→'+b).join('\n');
export function textToLexicon(text:string){const out:Record<string,string>={};for(const line of text.split('\n')){const m=line.split(/→|->|=>/);if(m.length>=2&&m[0].trim()&&m[1].trim())out[m[0].trim()]=m[1].trim()}return out}

export function whereFrom(s?:Source|{level:string;id?:string}){return s?LEVEL[s.level]??s.level:'—'}

export function ChapterSettings({kind,id,request,presetModels=['0.6B'],cloneModels=['0.6B'],chapterIds=[],inline,voiceName=(v:string|undefined)=>String(v??''),onClose}:Props){
 const base=kind==='project'?`/projects/${id}/settings`:`/master-books/${id}/settings`;
 const [data,setData]=useState<Payload|null>(null);const [page,setPage]=useState(0);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const [lexiconText,setLexiconText]=useState('');const [pending,setPending]=useState<Record<string,string>>({});
 // 整书应用预览：主工程改一项会影响多少章（仍在继承的）、多少章有自己的设置不受影响。
 const [overridden,setOverridden]=useState<Record<string,number>|null>(null);
 const [cast,setCast]=useState<{id:string;name:string;aliases?:string[]}[]>([]);const [bookRevision,setBookRevision]=useState(0);const [spoken,setSpoken]=useState<Record<string,number>>({});
 const [bookId,setBookId]=useState<string|null>(null);
 useEffect(()=>{if(kind!=='project'){setBookId(null);return}void request('/projects/'+id).then((p:{book?:{id?:string}|null;settings_schema?:number})=>setBookId(p.settings_schema===1&&p.book?.id?p.book.id:null)).catch(()=>setBookId(null))},[kind,id]);   // eslint-disable-line react-hooks/exhaustive-deps
 // 本人 2026-09-22: 改了一个子工程里的角色音色，怎么应用到其它章节 —— 一个角色的声音写进主工程，各章对这个角色的覆盖清掉，其它角色不动。
 const unifyRole=async(name:string,voice:string)=>{if(!bookId)return;if(!confirm(tr("把「{0}」的声音 {1} 用到整本书？\n\n各章对「{2}」自己设的声音会被清掉，改为跟随主工程；其它角色不受影响。以后某一章要换（比如人老了），在那一章再单独改就行。",name,voice,name)))return;setBusy(true);setError('');try{const b:{revision?:number}=await request('/books/'+bookId);await request(`/master-books/${bookId}/settings/unify-role`,'POST',{revision:b.revision??0,key:'voices',name,value:voice});await load()}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 const loadCast=()=>{if(kind!=='book')return;void request('/books/'+id).then((b:{cast?:{id:string;name:string;aliases?:string[]}[];revision?:number})=>{setCast(b.cast??[]);setBookRevision(b.revision??0)}).catch(()=>{});void request(`/master-books/${id}/cast/usage`).then((u:{lines:Record<string,number>})=>setSpoken(u.lines)).catch(()=>setSpoken({}))};
 // A name no line uses any more (a misspelling corrected line by line) can leave the cast (本人 2026-09-24).
 const removeCast=async(c:{id:string;name:string})=>{if(!confirm(tr("从人物表删除「{0}」？没有句子在用它；它的声音、颜色设置一并删除。之后的章节不会再把这个名字告诉模型。",c.name)))return;setBusy(true);setError('');try{await request(`/master-books/${id}/cast/${c.id}?revision=${bookRevision}`,'DELETE');loadCast();await load()}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 useEffect(()=>{loadCast()},[kind,id]);   // eslint-disable-line react-hooks/exhaustive-deps
 useEffect(()=>{if(kind!=='book'||!chapterIds.length){setOverridden(null);return}let stop=false;void Promise.all(chapterIds.map(c=>request(`/projects/${c}/settings`).catch(()=>null))).then(list=>{if(stop)return;const n:Record<string,number>={};for(const d of list)for(const k of Object.keys(d?.overrides??{}))n[k]=(n[k]??0)+1;setOverridden(n)});return()=>{stop=true}},[kind,id,chapterIds.join(',')]);   // eslint-disable-line react-hooks/exhaustive-deps
 const load=async()=>{const d=await request(base);setData(d);setLexiconText(lexiconToText((kind==='project'?d.effective?.lexicon:d.settings?.lexicon)??{}))};
 useEffect(()=>{void load().catch(e=>setError((e as Error).message))},[id,kind]);   // eslint-disable-line react-hooks/exhaustive-deps
 if(error&&!data)return <div className="chapter-settings"><p role="alert" className="line-error">{error}</p><button onClick={onClose}>{tr("关闭")}</button></div>;
 if(!data)return <div className="chapter-settings"><p className="muted">{tr("读取设置…")}</p></div>;
 const revision=kind==='project'?(data.project_revision??0):(data.revision??0);
 const effective=(kind==='project'?data.effective:data.settings)??{};
 const overrides=(kind==='project'?data.overrides:data.settings)??{};
 const sources=data.sources??{};
 const save=async(values:Record<string,unknown>,inherit:string[]=[])=>{setBusy(true);setError('');try{await request(base,'PATCH',{revision,values,inherit});await load()}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 const owned=(key:string)=>key in overrides;
 const origin=(key:string)=>kind==='book'?tr("应用默认（主工程没设）"):whereFrom(sources[key]);
 const reach=(key:string)=>{if(kind!=='book'||!overridden)return null;const kept=overridden[key]??0;return tr("改动影响 {0} 章{1}",chapterIds.length-kept,kept?tr("；{0} 章有自己的设置，不受影响",kept):'')};
 // 整部作品统一此项：写进主工程并清掉各章对这一项的覆盖（Sol 三的 /settings/unify）；先说清会清掉几章。
 const unify=async(k:string)=>{const kept=overridden?.[k]??0;if(!confirm(tr("把「{0}」统一成主工程的值？\n\n{1}\n可从主工程快照恢复。",LABELS[k]??k,kept?tr("{0} 章自己设的这一项会被清掉，改为跟随主工程。",kept):tr("现在没有章节自己设过这一项。"))))return;setBusy(true);setError('');try{await request(`/master-books/${id}/settings/unify`,'POST',owned(k)?{revision,values:{[k]:effective[k]},inherit:[]}:{revision,values:{},inherit:[k]});await load();setOverridden(x=>x?{...x,[k]:0}:x)}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 const Row=({k,children}:{k:string;children:React.ReactNode})=><label className="setting-row"><span className="setting-name">{LABELS[k]??k}<small className={'setting-source '+(owned(k)?'own':'inherited')}>{owned(k)?(kind==='book'?tr("主工程默认"):tr("本章设置")):(kind==='book'?origin(k):tr("继承 · 来自{0}",origin(k)))}{reach(k)&&<> · {reach(k)}</>}</small></span>{children}{kind==='project'&&owned(k)&&<button type="button" className="setting-inherit" disabled={busy} title={tr("删掉本章的这一项，回到主工程或应用默认")} onClick={()=>void save({},[k])}>{tr("恢复继承")}</button>}{kind==='book'&&(overridden?.[k]??0)>0&&<button type="button" className="setting-inherit" disabled={busy} title={tr("各章对这一项的自设都清掉，整部作品用主工程的值")} onClick={()=>void unify(k)}>{tr("整部作品统一")}</button>}</label>;
 // A number is saved when the field is left (or Enter), not on every keystroke.
 const num=(k:string,step:number,min:number,max:number)=><Row k={k}><input type="number" step={step} min={min} max={max} disabled={busy} value={pending[k]??String(effective[k]??'')} onChange={e=>setPending(x=>({...x,[k]:e.target.value}))} onKeyDown={e=>{if(e.key==='Enter')(e.target as HTMLInputElement).blur()}} onBlur={e=>{const v=Number(e.target.value);setPending(x=>{const y={...x};delete y[k];return y});if(Number.isFinite(v)&&v!==Number(effective[k]))void save({[k]:v})}}/></Row>;
 const sel=(k:string,options:[string,string][])=><Row k={k}><select disabled={busy} value={String(effective[k]??'')} onChange={e=>void save({[k]:isNaN(Number(e.target.value))||k==='preset_model'||k==='clone_model'||k==='color_scope'?e.target.value:Number(e.target.value)})}>{options.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></Row>;
 const roles=Object.keys((effective.voices as Record<string,string>)??{});
 const rename=async(c:{id:string;name:string})=>{const name=(prompt(tr("「{0}」改成什么名字？全书各章一起改。",c.name),c.name)??'').trim();if(!name||name===c.name)return;setBusy(true);setError('');try{const plan=await request(`/master-books/${id}/cast/rename/plan`,'POST',{revision:bookRevision,cast_id:c.id,name});const conflicts=(plan.conflicts??[]) as {message?:string;kind?:string}[];if(conflicts.length){setError(tr("改名有冲突：")+conflicts.map(x=>tr(x.message??x.kind??'')).join(tr("；")));return}if(!confirm(tr("「{0}」→「{1}」：影响 {2} 章，声音不重生成，旧名字保留为别名。确定？",c.name,name,(plan.affected_projects??[]).length)))return;await request(`/master-books/${id}/cast/rename`,'POST',{revision:bookRevision,cast_id:c.id,name});loadCast();await load()}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 const roleSource=(k:string,name:string)=>{const s=sources[k];const r=s?.roles?.[name];return r?whereFrom(r):whereFrom(s)};
 const keys=PAGES[page][1];
 return <div className="chapter-settings" role="dialog" aria-label={tr("设置")}>
  <div className="setting-head"><strong>{kind==='book'?tr("主工程默认设置"):tr("本章设置")}</strong><small>{kind==='book'?tr("改这里会影响仍在「继承」的章节；各章自己改过的项保留。"):tr("继承的项跟着主工程走；改过就只属于本章。")}</small>{!inline&&<button type="button" aria-label={tr("关闭设置")} onClick={onClose}>✕</button>}</div>
  <div role="tablist" className="setting-tabs">{PAGES.map(([t],i)=><button key={t} role="tab" aria-selected={page===i} onClick={()=>setPage(i)}>{t}</button>)}</div>
  {error&&<p role="alert" className="line-error">{error}</p>}
  {page===0&&<div className="setting-page">
   {kind==='book'&&cast.length>0&&<div className="setting-cast"><strong>{tr("人物表")}</strong>{cast.map(c=><span key={c.id} className="setting-cast-row">{c.name}{c.aliases?.length?<small>{tr("（又称 {0}）",c.aliases.join(tr("、")))}</small>:null}{c.id in spoken&&<small className={spoken[c.id]?'':'cast-unused'}>{spoken[c.id]?tr(" · {0} 句",spoken[c.id]):tr(" · 没有句子在用")}</small>}<button type="button" disabled={busy} title={tr("全书改名：各章的句子、设置和标签一起改，声音不重生成")} onClick={()=>void rename(c)}>{tr("改名…")}</button>{spoken[c.id]===0&&<button type="button" className="danger" disabled={busy} onClick={()=>void removeCast(c)}>{tr("删除")}</button>}</span>)}</div>}
   {roles.length===0&&cast.length===0&&<p className="muted">{tr("还没有角色：处理过章节后角色会出现在这里。")}</p>}
   {roles.map(name=><div key={name} className="setting-role"><strong>{name}</strong><small>{tr("声音 ")}{voiceName((effective.voices as Record<string,string>)[name])}{tr(" · 来自")}{roleSource('voices',name)}{kind==='project'&&bookId&&sources.voices?.roles?.[name]?.level!=='book'&&<> <button type="button" className="see-lines" disabled={busy} title={tr("这个角色的声音写进主工程，每一章都用它")} onClick={()=>void unifyRole(name,String((effective.voices as Record<string,string>)[name]))}>{tr("整本都用这个声音")}</button></>}</small>
     <span className="dot" style={{background:((effective.colors as Record<string,string>)??{})[name]??'#ccc'}}/><small>{tr("性别 {0} · 来自{1}",({m:tr("男"),f:tr("女")} as Record<string,string>)[((effective.sexes as Record<string,string>)??{})[name]]??tr("按音色"),roleSource('sexes',name))}</small>
     <label><input type="checkbox" disabled={busy} checked={((effective.muted_speakers as string[])??[]).includes(name)} onChange={e=>{const cur=((effective.muted_speakers as string[])??[]).filter(x=>x!==name);void save({muted_speakers:e.target.checked?[...cur,name]:cur})}}/>{tr("不朗读")}</label></div>)}
   {keys.filter(k=>k!=='voices'&&k!=='colors'&&k!=='sexes').map(k=><p key={k} className="muted">{tr("{0}：{1}",LABELS[k],owned(k)?tr("本章设置"):tr("继承 · 来自{0}",origin(k)))}</p>)}
  </div>}
  {page===1&&<div className="setting-page">
   {sel('preset_model',presetModels.map(m=>[m,m+(m==='1.7B'?tr(" · 更大"):'')] as [string,string]))}
   {sel('clone_model',cloneModels.map(m=>[m,m+(m==='1.7B'?tr(" · 更大的克隆模型"):tr(" · 原来的克隆模型"))] as [string,string]))}
   {num('speech_rate',0.05,0.5,2)}{num('pause_ms',10,0,5000)}
   {sel('ellipsis_pause_ms',[['500',tr("停一拍（半秒）")],['300',tr("短停（0.3 秒）")],['0',tr("不处理")]])}
   {sel('color_scope',[['name',tr("角色名")],['text',tr("说话的文字")],['both',tr("角色名和文字")]])}
  </div>}
  {page===2&&<div className="setting-page"><Row k="lexicon"><textarea rows={8} disabled={busy} placeholder={tr("偸→偷\n儍→傻\n干活→干[gan4]活")} value={lexiconText} onChange={e=>setLexiconText(e.target.value)} onBlur={()=>{const v=textToLexicon(lexiconText);if(JSON.stringify(v)!==JSON.stringify(effective.lexicon??{}))void save({lexicon:v})}}/></Row><p className="muted">{tr("每行一条：写法→读法，和工程页的发音词典同一个格式，可以直接复制粘贴。多音字写成 干活→干[gan4]活。整项替换：本章设了词典就不再用主工程的；清空表示本章不用词典。")}</p></div>}
  {page===3&&<div className="setting-page"><p className="muted">{tr("导出选项（选章、输出格式、批次）在 Sol 四 / Opus 三 接入后出现在这里。")}</p></div>}
 </div>;
}
