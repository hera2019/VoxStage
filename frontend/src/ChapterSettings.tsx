import {useEffect,useState} from 'react';

/** Paged settings for a chapter (sub-project) or a master book, against the
 *  v1 contract (docs/api-book-project-v1.md): every value shown is the
 *  *effective* one with where it comes from; a change writes a local
 *  override; 恢复继承 deletes it. 0, an empty list and an empty map are values
 *  — only `inherit` removes an override. Opus 一, 2026-09-20. */
type Source={level:string;id?:string;roles?:Record<string,{level:string;id?:string}>};
type Payload={project_id?:string;book_id?:string;project_revision?:number;book_revision?:number|null;revision?:number;
  overrides?:Record<string,unknown>;effective?:Record<string,unknown>;settings?:Record<string,unknown>;sources?:Record<string,Source>};
type Props={kind:'project'|'book';id:string;request:(path:string,method?:string,data?:unknown)=>Promise<any>;
  presetModels?:string[];cloneModels?:string[];chapterIds?:string[];onClose:()=>void};

const PAGES:[string,string[]][]=[['角色声音',['voices','colors','sexes','muted_speakers']],['朗读与停顿',['preset_model','clone_model','speech_rate','pause_ms','ellipsis_pause_ms','color_scope']],['发音',['lexicon']],['导出',[]]];
const LABELS:Record<string,string>={voices:'角色声音',colors:'角色颜色',sexes:'角色性别',muted_speakers:'不朗读的角色',preset_model:'预设音色模型',clone_model:'固定声线模型',speech_rate:'语速',pause_ms:'句间停顿（毫秒）',ellipsis_pause_ms:'省略号、破折号处停顿',color_scope:'颜色用在',lexicon:'发音词典'};
const LEVEL:Record<string,string>={project:'本章',local:'本章',book:'主工程',master:'主工程',default:'应用默认',app:'应用默认',machine:'本机默认'};

export function whereFrom(s?:Source|{level:string;id?:string}){return s?LEVEL[s.level]??s.level:'—'}

export function ChapterSettings({kind,id,request,presetModels=['0.6B'],cloneModels=['0.6B'],chapterIds=[],onClose}:Props){
 const base=kind==='project'?`/projects/${id}/settings`:`/master-books/${id}/settings`;
 const [data,setData]=useState<Payload|null>(null);const [page,setPage]=useState(0);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const [lexiconText,setLexiconText]=useState('');const [pending,setPending]=useState<Record<string,string>>({});
 // 整书应用预览：主工程改一项会影响多少章（仍在继承的）、多少章有自己的设置不受影响。
 const [overridden,setOverridden]=useState<Record<string,number>|null>(null);
 useEffect(()=>{if(kind!=='book'||!chapterIds.length){setOverridden(null);return}let stop=false;void Promise.all(chapterIds.map(c=>request(`/projects/${c}/settings`).catch(()=>null))).then(list=>{if(stop)return;const n:Record<string,number>={};for(const d of list)for(const k of Object.keys(d?.overrides??{}))n[k]=(n[k]??0)+1;setOverridden(n)});return()=>{stop=true}},[kind,id,chapterIds.join(',')]);   // eslint-disable-line react-hooks/exhaustive-deps
 const load=async()=>{const d=await request(base);setData(d);setLexiconText(JSON.stringify((kind==='project'?d.effective?.lexicon:d.settings?.lexicon)??{},null,1))};
 useEffect(()=>{void load().catch(e=>setError((e as Error).message))},[id,kind]);   // eslint-disable-line react-hooks/exhaustive-deps
 if(error&&!data)return <div className="chapter-settings"><p role="alert" className="line-error">{error}</p><button onClick={onClose}>关闭</button></div>;
 if(!data)return <div className="chapter-settings"><p className="muted">读取设置…</p></div>;
 const revision=kind==='project'?(data.project_revision??0):(data.revision??0);
 const effective=(kind==='project'?data.effective:data.settings)??{};
 const overrides=(kind==='project'?data.overrides:data.settings)??{};
 const sources=data.sources??{};
 const save=async(values:Record<string,unknown>,inherit:string[]=[])=>{setBusy(true);setError('');try{await request(base,'PATCH',{revision,values,inherit});await load()}catch(e){setError((e as Error).message)}finally{setBusy(false)}};
 const owned=(key:string)=>key in overrides;
 const origin=(key:string)=>kind==='book'?'应用默认（主工程没设）':whereFrom(sources[key]);
 const reach=(key:string)=>{if(kind!=='book'||!overridden)return null;const kept=overridden[key]??0;return `改动影响 ${chapterIds.length-kept} 章${kept?`；${kept} 章有自己的设置，不受影响`:''}`};
 const Row=({k,children}:{k:string;children:React.ReactNode})=><label className="setting-row"><span className="setting-name">{LABELS[k]??k}<small className={'setting-source '+(owned(k)?'own':'inherited')}>{owned(k)?(kind==='book'?'主工程默认':'本章设置'):(kind==='book'?origin(k):`继承 · 来自${origin(k)}`)}{reach(k)&&<> · {reach(k)}</>}</small></span>{children}{kind==='project'&&owned(k)&&<button type="button" className="setting-inherit" disabled={busy} title="删掉本章的这一项，回到主工程或应用默认" onClick={()=>void save({},[k])}>恢复继承</button>}</label>;
 // A number is saved when the field is left (or Enter), not on every keystroke.
 const num=(k:string,step:number,min:number,max:number)=><Row k={k}><input type="number" step={step} min={min} max={max} disabled={busy} value={pending[k]??String(effective[k]??'')} onChange={e=>setPending(x=>({...x,[k]:e.target.value}))} onKeyDown={e=>{if(e.key==='Enter')(e.target as HTMLInputElement).blur()}} onBlur={e=>{const v=Number(e.target.value);setPending(x=>{const y={...x};delete y[k];return y});if(Number.isFinite(v)&&v!==Number(effective[k]))void save({[k]:v})}}/></Row>;
 const sel=(k:string,options:[string,string][])=><Row k={k}><select disabled={busy} value={String(effective[k]??'')} onChange={e=>void save({[k]:isNaN(Number(e.target.value))||k==='preset_model'||k==='clone_model'||k==='color_scope'?e.target.value:Number(e.target.value)})}>{options.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></Row>;
 const roles=Object.keys((effective.voices as Record<string,string>)??{});
 const roleSource=(k:string,name:string)=>{const s=sources[k];const r=s?.roles?.[name];return r?whereFrom(r):whereFrom(s)};
 const keys=PAGES[page][1];
 return <div className="chapter-settings" role="dialog" aria-label="设置">
  <div className="setting-head"><strong>{kind==='book'?'主工程默认设置':'本章设置'}</strong><small>{kind==='book'?'改这里会影响仍在「继承」的章节；各章自己改过的项保留。':'继承的项跟着主工程走；改过就只属于本章。'}</small><button type="button" aria-label="关闭设置" onClick={onClose}>✕</button></div>
  <div role="tablist" className="setting-tabs">{PAGES.map(([t],i)=><button key={t} role="tab" aria-selected={page===i} onClick={()=>setPage(i)}>{t}</button>)}</div>
  {error&&<p role="alert" className="line-error">{error}</p>}
  {page===0&&<div className="setting-page">
   {roles.length===0&&<p className="muted">还没有角色：处理过章节后角色会出现在这里。</p>}
   {roles.map(name=><div key={name} className="setting-role"><strong>{name}</strong><small>声音 {String((effective.voices as Record<string,string>)[name])} · 来自{roleSource('voices',name)}</small>
     <span className="dot" style={{background:((effective.colors as Record<string,string>)??{})[name]??'#ccc'}}/><small>性别 {({m:'男',f:'女'} as Record<string,string>)[((effective.sexes as Record<string,string>)??{})[name]]??'按音色'} · 来自{roleSource('sexes',name)}</small>
     <label><input type="checkbox" disabled={busy} checked={((effective.muted_speakers as string[])??[]).includes(name)} onChange={e=>{const cur=((effective.muted_speakers as string[])??[]).filter(x=>x!==name);void save({muted_speakers:e.target.checked?[...cur,name]:cur})}}/>不朗读</label></div>)}
   {keys.filter(k=>k!=='voices'&&k!=='colors'&&k!=='sexes').map(k=><p key={k} className="muted">{LABELS[k]}：{owned(k)?'本章设置':`继承 · 来自${origin(k)}`}</p>)}
  </div>}
  {page===1&&<div className="setting-page">
   {sel('preset_model',presetModels.map(m=>[m,m+(m==='1.7B'?' · 更大':'')] as [string,string]))}
   {sel('clone_model',cloneModels.map(m=>[m,m+(m==='1.7B'?' · 更大的克隆模型':' · 原来的克隆模型')] as [string,string]))}
   {num('speech_rate',0.05,0.5,2)}{num('pause_ms',10,0,5000)}
   {sel('ellipsis_pause_ms',[['500','停一拍（半秒）'],['300','短停（0.3 秒）'],['0','不处理']])}
   {sel('color_scope',[['name','角色名'],['text','说话的文字'],['both','角色名和文字']])}
  </div>}
  {page===2&&<div className="setting-page"><Row k="lexicon"><textarea rows={8} disabled={busy} value={lexiconText} onChange={e=>setLexiconText(e.target.value)} onBlur={()=>{try{const v=JSON.parse(lexiconText||'{}');if(JSON.stringify(v)!==JSON.stringify(effective.lexicon??{}))void save({lexicon:v})}catch{setError('词典要写成 {"原词":"读法"} 的 JSON。')}}}/></Row><p className="muted">整项替换：本章设了词典就不再用主工程的；空的 {'{}'} 表示本章不用词典。</p></div>}
  {page===3&&<div className="setting-page"><p className="muted">导出选项（选章、输出格式、批次）在 Sol 四 / Opus 三 接入后出现在这里。</p></div>}
 </div>;
}
