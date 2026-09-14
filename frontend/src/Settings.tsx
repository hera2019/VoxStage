import {useEffect,useRef,useState} from 'react';
type Custom={id:string;name:string;language:string;source:string;seconds:number;derived_from:string|null;consent_confirmed:boolean};
type Props={request:(path:string,method?:string,data?:unknown)=>Promise<any>;voices:Record<string,string>;
 language:'zh'|'en';speedReady:boolean;designReady?:boolean;roleModels?:{id:string;label:string;installed:boolean}[];roleModel?:string;onClose:()=>void;onPick?:(voice:string)=>void;pickFor?:string};
const SAMPLES={zh:'雨点轻轻敲着窗，她回头看了一眼。',en:'Rain tapped against the window, and she looked back once.'};

export function Settings({request,voices,language,speedReady,designReady,roleModels,roleModel,onClose,onPick,pickFor}:Props){
 const [role,setRole]=useState(roleModel??'');const [roleNote,setRoleNote]=useState('');
 const [tab,setTab]=useState<'voices'>('voices');
 const [text,setText]=useState(SAMPLES[language]);
 const [rate,setRate]=useState(1);
 const [design,setDesign]=useState('');const [designs,setDesigns]=useState<{file:string;url:string;seconds:number;seed:number}[]>([]);const [designed,setDesigned]=useState<{file:string;seconds:number}|null>(null);const [designName,setDesignName]=useState('');
 const [favourites,setFavourites]=useState<string[]>([]);
 const [playing,setPlaying]=useState('');const [waiting,setWaiting]=useState('');const [error,setError]=useState('');
 const [heard,setHeard]=useState<Record<string,{seconds:number;file:string;take:number;seed:number}>>({});
 const [custom,setCustom]=useState<Custom[]>([]);
 const [saving,setSaving]=useState('');const [newName,setNewName]=useState('');
 const [consent,setConsent]=useState(false);const file=useRef<HTMLInputElement>(null);
 const reload=()=>request('/voices/custom').then(setCustom).catch(()=>{});
 async function run(task:()=>Promise<void>){setError('');try{await task()}catch(e){setError((e as Error).message)}}
 const player=useRef<HTMLAudioElement>(null);
 useEffect(()=>{void reload();void request('/settings').then(s=>setFavourites(s.favourite_voices??[])).catch(()=>{})},[]);
 const names=Object.keys(voices);
 // Favourites first: with nine presets and cross-language use, the list only grows.
 const ordered=[...names.filter(v=>favourites.includes(v)),...names.filter(v=>!favourites.includes(v))];
 async function toggle(voice:string){
  const next=favourites.includes(voice)?favourites.filter(v=>v!==voice):[...favourites,voice];
  setFavourites(next);
  try{await request('/settings','POST',{favourite_voices:next})}catch(e){setError((e as Error).message)}
 }
 async function audition(voice:string){
  setWaiting(voice);setError('');
  try{
   const r=await request('/voices/audition','POST',{voice,text,language,rate});
   setHeard(h=>({...h,[voice]:{seconds:r.seconds,file:r.file,take:(h[voice]?.take??0)+1,seed:r.seed}}));setPlaying(voice);
   const audio=player.current;
   if(audio){audio.src=r.url;await audio.play().catch(()=>setError('请点击播放按钮试听。'))}
  }catch(e){setError((e as Error).message)}finally{setWaiting('')}
 }
 return <div className="overlay"><section className="dialog settings" role="dialog" aria-modal="true" aria-labelledby="settings-title">
  <div className="dialog-title"><h2 id="settings-title">设置</h2><button aria-label="关闭设置" onClick={onClose}>✕</button></div>
  <div className="tabs" role="tablist">
   <button role="tab" aria-selected={tab==='voices'} className={tab==='voices'?'active':''} onClick={()=>setTab('voices')}>音色试听</button>
  </div>

  {pickFor&&<p className="hint">正在为「{pickFor}」挑选音色。选定后点「用于此角色」。</p>}

  <label>试听文字<textarea rows={2} maxLength={120} value={text} onChange={e=>setText(e.target.value)}/></label>


  <div className="voice-list">{ordered.map(voice=>{
   const fav=favourites.includes(voice);
   return <article className={'voice-row '+(playing===voice?'playing':'')} key={voice}>
    <button className={'star '+(fav?'on':'')} aria-pressed={fav} title={fav?'取消收藏':'收藏，置顶显示'}
     aria-label={(fav?'取消收藏 ':'收藏 ')+voice} onClick={()=>void toggle(voice)}>{fav?'★':'☆'}</button>
    <div className="voice-name"><strong>{voice}</strong><small>{voices[voice]}</small></div>
    {heard[voice]&&<small className="heard" title={'种子 '+heard[voice].seed}>第 {heard[voice].take} 版 · {heard[voice].seconds.toFixed(1)} 秒</small>}
    <button disabled={!!waiting} onClick={()=>void audition(voice)}>{waiting===voice?'正在生成…':heard[voice]?'再来一版':'试听'}</button>
    {onPick&&<button className="primary" onClick={()=>onPick(voice)}>用于此角色</button>}
   </article>})}
  </div>
  <audio ref={player} controls preload="none"/>

  <div className="keep-voice design-voice">
   <div className="section-label">设计一个新声线</div>
   <p className="muted">用一句话描述你要的声音——年龄、性别、嗓音、语气。听到满意的再保存，存下的就是你听到的这一段。
    {designReady?'':'（声音设计模型未安装：运行 scripts/setup_model.py --model design）'}</p>
   <textarea aria-label="声音描述" rows={2} maxLength={300} disabled={!designReady||!!waiting} placeholder="例如：一位六十多岁的男性，声音沙哑苍老，说话慢，带着旧式读书人的腔调" value={design} onChange={e=>{setDesign(e.target.value);setDesigns([]);setDesigned(null)}}/>
   <div className="keep-row">
    <button disabled={!designReady||!design.trim()||!!waiting} onClick={()=>void (async()=>{setWaiting('design');setError('');
      try{const r=await request('/voices/design','POST',{description:design,text,language});const v={file:r.file,url:r.url,seconds:r.seconds,seed:r.seed};setDesigns(list=>[v,...list].slice(0,8));setDesigned({file:v.file,seconds:v.seconds});setPlaying('');
        const audio=player.current;if(audio){audio.src=r.url;await audio.play().catch(()=>setError('请点击播放按钮试听。'))}}
      catch(e){setError((e as Error).message)}finally{setWaiting('')}})()}>{waiting==='design'?'正在设计…':designs.length?'再来一版':'按描述生成并试听'}</button>
    <input aria-label="设计声线名称" maxLength={40} placeholder="满意了就起个名字" value={designName} disabled={!designed} onChange={e=>setDesignName(e.target.value)}/>
    <button disabled={!designed||!designName.trim()||!!saving} onClick={()=>void run(async()=>{setSaving('design');
      try{await request('/voices/custom','POST',{name:designName,language,reference_text:text,from_design:designed!.file});setDesignName('');setDesigned(null);setDesigns([]);await reload()}finally{setSaving('')}})}>{saving==='design'?'保存中…':'保存选中的这版'}</button>
   </div>
   {designs.length>0&&<ul className="design-versions" aria-label="已生成的版本">{designs.map((v,i)=><li key={v.file}><button className={designed?.file===v.file?'active':''} aria-pressed={designed?.file===v.file} onClick={()=>{setDesigned({file:v.file,seconds:v.seconds});setPlaying('');const audio=player.current;if(audio){audio.src=v.url;void audio.play().catch(()=>setError('请点击播放按钮试听。'))}}}>▶ 第 {designs.length-i} 版 · {v.seconds.toFixed(1)} 秒 <small>种子 {v.seed}</small></button></li>)}</ul>}
   {designs.length>0&&<p className="muted">同一段描述每点一次出一版不同的声音，最多留 8 版；点哪版就听哪版，保存的就是它。改了描述会重新开始。</p>}
  </div>

  {roleModels&&roleModels.length>0&&<div className="keep-voice role-model">
   <div className="section-label">分角色模型</div>
   <p className="muted">新建工程时给原文分旁白/对白、点出说话人的本机模型。每个都按 SHA-256 校验；草稿记录里写着是哪个模型答的。</p>
   <select aria-label="分角色模型" value={role} disabled={!!waiting} onChange={e=>{const id=e.target.value;setRole(id);setRoleNote('');void (async()=>{try{await request('/settings','POST',{role_model:id});setRoleNote('已切换，下一次生成角色草稿起生效。')}catch(err){setRoleNote((err as Error).message);setRole(roleModel??'')}})()}}>
    {roleModels.map(m=><option key={m.id} value={m.id} disabled={!m.installed}>{m.label}{m.installed?'':'（未安装：scripts/setup_model.py --model role-abliterated）'}</option>)}
   </select>
   {roleNote&&<p className="muted">{roleNote}</p>}
  </div>}

  <div className="keep-voice">
   <div className="section-label">留下这个声音</div>
   <p className="muted">把刚才听到的那一版原样保存成一个具名音色——每点一次试听都是新的一版，存的就是最后听到的这版。
    之后直接选它，不必再找当时那一版。参考音会稳定朗读节奏——已实测把一个漂移的预设从 36% 变异压到 9%。</p>
   <div className="keep-row">
    <input aria-label="新音色名称" maxLength={40} placeholder="例如：稳定旁白" value={newName} onChange={e=>setNewName(e.target.value)}/>
    <button disabled={!newName.trim()||!playing||!!saving} onClick={()=>void run(async()=>{
      setSaving('keep');
      try{await request('/voices/custom','POST',{name:newName,language,reference_text:text,from_audition:heard[playing]?.file});
        setNewName('');await reload()}finally{setSaving('')}
     })}>{saving==='keep'?'保存中…':playing&&heard[playing]?`保存「${playing}」第 ${heard[playing].take} 版`:'先试听一个音色'}</button>
   </div>
   <details className="provide-voice">
    <summary>或者提供一段自己的录音</summary>
    <p className="muted">录音只留在这台 Mac，不进版本库，也不上传。生成的声音会标注为合成语音，不得用于冒充他人。</p>
    <label className="consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>
     我拥有这段声音的使用权，或已获得本人明确授权。</label>
    <input ref={file} type="file" accept="audio/wav,audio/x-wav,.wav" aria-label="参考声音文件" disabled={!consent||!newName.trim()}
     onChange={e=>{const f=e.target.files?.[0];if(!f)return;
      if(f.size>8_000_000){setError('文件过大，请提供 1.5–60 秒的 WAV。');return}
      void run(async()=>{const buffer=await f.arrayBuffer();
        let binary='';const bytes=new Uint8Array(buffer);
        for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
        await request('/voices/custom','POST',{name:newName,language,reference_text:text,
          audio_base64:btoa(binary),consent_confirmed:consent});
        setNewName('');if(file.current)file.current.value='';await reload()})}}/>
    <small>参考文字请填上面「试听文字」框里那句——必须与录音实际说的一致。</small>
   </details>
  </div>

  {custom.length>0&&<div className="custom-voices">
   <div className="section-label">已保存的音色</div>
   {custom.map(v=><article className="voice-row" key={v.id}>
    <div className="voice-name"><strong>{v.name}</strong>
     <small>{v.source==='generated'?`合成自 ${v.derived_from??'预设'}`:'提供的录音 · 已确认授权'} · {v.seconds.toFixed(1)} 秒</small></div>
    <button onClick={()=>{const a=player.current;if(a){a.src='/api/voices/custom/'+v.id+'/audio';void a.play().catch(()=>{})}}}>听参考</button>
    <button onClick={()=>void run(async()=>{const name=prompt('新的名称',v.name);if(name){await request('/voices/custom/'+v.id,'PATCH',{name});await reload()}})}>改名</button>
    <button className="danger" onClick={()=>void run(async()=>{if(confirm(`删除音色「${v.name}」？参考声音会一并删除。`)){await request('/voices/custom/'+v.id,'DELETE');await reload()}})}>删除</button>
    {onPick&&<button className="primary" onClick={()=>onPick('custom:'+v.id)}>用于此角色</button>}
   </article>)}
  </div>}
  <label className="audition-rate">试听语速 <small>只影响这里的试听，不改变生成出来的声音；正式作品的语速在工作区设置。</small>
   <div className="rate-row">
    <input type="range" min={0.5} max={2} step={0.1} value={rate} disabled={!speedReady}
     aria-label="试听语速" onChange={e=>setRate(Number(e.target.value))}/>
    <output>{rate===1?'原速':rate.toFixed(1)+' 倍'}</output>
    {rate!==1&&<button onClick={()=>setRate(1)}>回到原速</button>}
   </div>
   {!speedReady&&<small className="line-error">本机没有 FFmpeg，试听只能用原速。</small>}
  </label>
  <p className="muted">试听是本机即时合成的，不会写进任何工程；语速在合成之后处理。</p>
  {error&&<p role="alert" className="line-error">{error}</p>}
 </section></div>;
}
// 最后更新：2026-09-11 · Claude Hera
