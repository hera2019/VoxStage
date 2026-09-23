import {useEffect,useRef,useState} from 'react';
type Custom={id:string;name:string;language:string;source:string;seconds:number;derived_from:string|null;consent_confirmed:boolean;reference_text?:string};
// Where a library voice was designed: its description, seed and the line it was designed on,
// following one copy step (a voice re-read from a designed one). Older designs kept no seed.
function designOrigin(v:Custom,all:Custom[]):{description:string;seed:number;text?:string}|null{
 const from=v.derived_from??'';
 const m=/^design:(.*) · seed (\d+)$/.exec(from);
 if(m)return {description:m[1],seed:Number(m[2]),text:v.reference_text};
 const source=from.startsWith('custom:')?all.find(x=>x.id===from.slice(7)):undefined;
 return source&&source!==v&&!source.derived_from?.startsWith('custom:')?designOrigin(source,all):null}
type Props={request:(path:string,method?:string,data?:unknown)=>Promise<any>;voices:Record<string,string>;
 language:'zh'|'en';speedReady:boolean;designReady?:boolean;roleModels?:{id:string;label:string;installed:boolean}[];roleModel?:string;onClose:()=>void;onPick?:(voice:string)=>void;pickFor?:string};
const SAMPLES={zh:'雨点轻轻敲着窗，她回头看了一眼。',en:'Rain tapped against the window, and she looked back once.'};
// 本人 2026-09-22: 试听框里再放几组有针对性的演示文字，5–10 秒。All written for this
// project — a calm narration, a quiet line, an urgent one, names and numbers, an
// old voice, a young one — so one voice can be judged on what it will actually read.
const DEMOS:Record<'zh'|'en',[string,string][]>={zh:[
 ['旁白 · 平缓','雨点敲着窗子，屋里只剩下钟摆的声音。她把信折好，放回抽屉最里面，像是从没拿出来过。'],
 ['旁白 · 写景长句','那年的雪下得早，镇口的桥面结了一层薄冰，走在上面能听见细细的裂声，像有人在远处低声说话。'],
 ['对白 · 温和','「你先坐，茶还烫着。」他把杯子推过去，又补了一句，「路上冷吧？手都红了。」'],
 ['对白 · 急切','「别动它！」她一把按住我的手腕，声音压得很低，「再往前一步，谁也救不了你。」'],
 ['名字与数字','三月十七日，第二十九号房的客人退了房，只留下一封写着「陈小雪亲启」的信和四百二十块钱。'],
 ['老人','「我今年七十三了，眼睛不中用，耳朵也背，可这屋里少了什么，我一进门就知道。」'],
 ['少年','「你看你看！它真的飞起来了！」他举着风筝跑过整条街，笑声比风还响。'],
],en:[
 ['Narration · calm','Rain tapped at the window, and the house held nothing but the sound of the clock. She folded the letter and put it back.'],
 ['Narration · long','The snow came early that year. A thin sheet of ice lay over the bridge, and it cracked softly underfoot, like someone talking far away.'],
 ['Dialogue · warm','"Sit down, the tea is still hot." He pushed the cup across the table. "Cold out there? Your hands are red."'],
 ['Dialogue · urgent','"Don\u2019t touch it!" She caught my wrist and lowered her voice. "One step further and nobody can help you."'],
 ['Names and numbers','On the seventeenth of March the guest in room twenty-nine checked out, leaving a letter for Miss Chen and four hundred pounds.'],
 ['Old','"I am seventy-three. My eyes are no good and my ears are worse, but I know the moment I walk in when something is missing."'],
 ['Young','"Look, look! It is really flying!" He ran the whole length of the street with the kite, laughing louder than the wind.'],
]};

export function Settings({request,voices,language,speedReady,designReady,roleModels,roleModel,onClose,onPick,pickFor}:Props){
 const [role,setRole]=useState(roleModel??'');const [roleNote,setRoleNote]=useState('');const [autoplay,setAutoplay]=useState(()=>{try{return localStorage.getItem('voxstage-autoplay')!=='0'}catch{return true}});
 const [tab,setTab]=useState<'voices'|'design'|'library'|'models'>('voices');
 const [text,setText]=useState(SAMPLES[language]);
 const [rate,setRate]=useState(1);
 const [design,setDesign]=useState('');const [designs,setDesigns]=useState<{file:string;url:string;seconds:number;seed:number;description:string}[]>([]);const [designed,setDesigned]=useState<{file:string;seconds:number;seed:number}|null>(null);
 // Keep the voice, change the words (本人 2026-09-23: 差一点点，下次生成又偏到很远): the seed stays,
 // so the description tweaks a voice instead of drawing a new one (ai-lab 实测 32).
 const [lock,setLock]=useState<{seed:number;from:string}|null>(null);const [designName,setDesignName]=useState('');
 const [favourites,setFavourites]=useState<string[]>([]);const [tags,setTags]=useState<Record<string,string[]>>({});const [tagEditing,setTagEditing]=useState<string|null>(null);
 // Tags describe a voice for choosing and for drawing a crowd from a pool: 老人、男性、威严.
 // Presets start from what their label says; anything can be edited.
 const defaultTags=(voice:string,label:string)=>{const t:string[]=[];const l=label.toLowerCase();if(/女|female/.test(l))t.push('女性');if(/男|male/.test(l)&&!/female/.test(l))t.push('男性');if(/青年|young/.test(l))t.push('青年');if(/低沉/.test(l))t.push('低沉');if(/明亮/.test(l))t.push('明亮');if(/温暖|warm/.test(l))t.push('温暖');if(/四川/.test(l))t.push('四川口音');if(/english/.test(l))t.push('英语');if(/日本/.test(l))t.push('日语');if(/한국/.test(l))t.push('韩语');return t};
 const tagsOf=(voice:string,label:string)=>tags[voice]??defaultTags(voice,label);
 async function saveTags(voice:string,text:string,label:string){const words=text.split(/[,，、\s]+/).map(w=>w.trim()).filter(Boolean);const next={...tags,[voice]:words.length?words:defaultTags(voice,label)};setTags(next);setTagEditing(null);try{await request('/settings','POST',{voice_tags:next})}catch(e){setError((e as Error).message)}}
 const [playing,setPlaying]=useState('');const [waiting,setWaiting]=useState('');const [error,setError]=useState('');
 const [heard,setHeard]=useState<Record<string,{seconds:number;file:string;take:number;seed:number}>>({});
 const [custom,setCustom]=useState<Custom[]>([]);
 const [saving,setSaving]=useState('');const [newName,setNewName]=useState('');
 const [consent,setConsent]=useState(false);const file=useRef<HTMLInputElement>(null);
 const reload=()=>request('/voices/custom').then(setCustom).catch(()=>{});
 async function run(task:()=>Promise<void>){setError('');try{await task()}catch(e){setError((e as Error).message)}}
 const player=useRef<HTMLAudioElement>(null);
 useEffect(()=>{void reload();void request('/settings').then(s=>{setFavourites(s.favourite_voices??[]);setTags(s.voice_tags??{})}).catch(()=>{})},[]);
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
   <button role="tab" aria-selected={tab==='voices'} className={tab==='voices'?'active':''} onClick={()=>setTab('voices')}>自带音色</button>
   <button role="tab" aria-selected={tab==='design'} className={tab==='design'?'active':''} onClick={()=>setTab('design')}>声线设计</button>
   <button role="tab" aria-selected={tab==='library'} className={tab==='library'?'active':''} onClick={()=>setTab('library')}>已保存的音色{custom.length?` · ${custom.length}`:''}</button>
   <button role="tab" aria-selected={tab==='models'} className={tab==='models'?'active':''} onClick={()=>setTab('models')}>模型与选项</button>
  </div>

  {tab!=='models'&&<>  {pickFor&&<p className="hint">正在为「{pickFor}」挑选音色。选定后点「用于此角色」。</p>}

  <label>试听文字 <small>换一段：不同类型的句子最能听出一个声线合不合适（每段 5–10 秒）</small>
   <select aria-label="换一段试听文字" value={DEMOS[language].find(([,line])=>line===text)?.[0]??''} onChange={e=>{const found=DEMOS[language].find(([name])=>name===e.target.value);if(found)setText(found[1])}}>
    <option value="">{DEMOS[language].some(([,line])=>line===text)?'— 换一段 —':'（自己写的）'}</option>
    {DEMOS[language].map(([name])=><option key={name} value={name}>{name}</option>)}
   </select>
   <textarea rows={2} maxLength={200} value={text} onChange={e=>setText(e.target.value)}/></label>
  <audio ref={player} controls preload="none"/>
  <label className="audition-rate">试听语速 <small>只影响这里的试听，不改变生成出来的声音；正式作品的语速在工作区设置。</small>
   <div className="rate-row">
    <input type="range" min={0.5} max={2} step={0.1} value={rate} disabled={!speedReady}
     aria-label="试听语速" onChange={e=>setRate(Number(e.target.value))}/>
    <output>{rate===1?'原速':rate.toFixed(1)+' 倍'}</output>
    {rate!==1&&<button onClick={()=>setRate(1)}>回到原速</button>}
   </div>
   {!speedReady&&<small className="line-error">本机没有 FFmpeg，试听只能用原速。</small>}
  </label>
  </>}

  {tab==='voices'&&<>  <div className="voice-list">{ordered.map(voice=>{
   const fav=favourites.includes(voice);
   return <article className={'voice-row '+(playing===voice?'playing':'')} key={voice}>
    <button className={'star '+(fav?'on':'')} aria-pressed={fav} title={fav?'取消收藏':'收藏，置顶显示'}
     aria-label={(fav?'取消收藏 ':'收藏 ')+voice} onClick={()=>void toggle(voice)}>{fav?'★':'☆'}</button>
    <div className="voice-name"><strong>{voice}</strong><small>{voices[voice]}</small>{tagEditing===voice?<input autoFocus className="tag-input" aria-label={voice+' 的标签'} defaultValue={tagsOf(voice,voices[voice]).join('、')} placeholder="标签，顿号分隔：老人、男性、威严" onBlur={e=>void saveTags(voice,e.target.value,voices[voice])} onKeyDown={e=>{if(e.key==='Enter')void saveTags(voice,(e.target as HTMLInputElement).value,voices[voice]);if(e.key==='Escape')setTagEditing(null)}}/>:<button type="button" className="tags" title="改标签" onClick={()=>setTagEditing(voice)}>{tagsOf(voice,voices[voice]).map(t=><span key={t}>{t}</span>)}<span className="tag-edit">✎</span></button>}</div>
    {heard[voice]&&<small className="heard" title={'种子 '+heard[voice].seed}>第 {heard[voice].take} 版 · {heard[voice].seconds.toFixed(1)} 秒</small>}
    <button disabled={!!waiting} onClick={()=>void audition(voice)}>{waiting===voice?'正在生成…':heard[voice]?'再来一版':'试听'}</button>
    {onPick&&<button className="primary" onClick={()=>onPick(voice)}>用于此角色</button>}
   </article>})}
  </div>
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
    <input ref={file} type="file" accept="audio/*,.wav,.m4a,.mp3,.aac,.caf,.flac,.ogg" aria-label="参考声音文件" disabled={!consent||!newName.trim()}
     onChange={e=>{const f=e.target.files?.[0];if(!f)return;
      if(f.size>8_000_000){setError('文件过大，请提供 1.5–60 秒的录音。');return}
      void run(async()=>{const buffer=await f.arrayBuffer();
        let binary='';const bytes=new Uint8Array(buffer);
        for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
        await request('/voices/custom','POST',{name:newName,language,reference_text:text,
          audio_base64:btoa(binary),consent_confirmed:consent});
        setNewName('');if(file.current)file.current.value='';await reload()})}}/>
    <small>参考文字请填上面「试听文字」框里那句——必须与录音实际说的一致。手机录的 m4a、mp3 也可以，程序会转成 WAV（需要本机装了 FFmpeg）。</small>
   </details>
  </div>

  </>}
  {tab==='design'&&<>  <div className="keep-voice design-voice">
   <div className="section-label">设计一个新声线</div>
   <p className="muted">用一句话描述你要的声音——年龄、性别、嗓音、语气。听到满意的再保存，存下的就是你听到的这一段。
    {designReady?'':'（声音设计模型未安装：运行 scripts/setup_model.py --model design）'}</p>
   <textarea aria-label="声音描述" rows={2} maxLength={300} disabled={!designReady||!!waiting} placeholder="例如：一位六十多岁的男性，声音沙哑苍老，说话慢，带着旧式读书人的腔调" value={design} onChange={e=>setDesign(e.target.value)}/>
   <div className="keep-row">
    <button disabled={!designReady||!design.trim()||!!waiting} onClick={()=>void (async()=>{setWaiting('design');setError('');
      try{const r=await request('/voices/design','POST',{description:design,text,language,...(lock?{seed:lock.seed}:{})});const v={file:r.file,url:r.url,seconds:r.seconds,seed:r.seed,description:design.trim()};setDesigns(list=>[v,...list.filter(x=>x.file!==v.file)].slice(0,8));setDesigned({file:v.file,seconds:v.seconds,seed:v.seed});setPlaying('');
        const audio=player.current;if(audio){audio.src=r.url;await audio.play().catch(()=>setError('请点击播放按钮试听。'))}}
      catch(e){setError((e as Error).message)}finally{setWaiting('')}})()}>{waiting==='design'?'正在设计…':lock?'按描述生成（保持声音）':designs.length?'再来一版':'按描述生成并试听'}</button>
    <input aria-label="设计声线名称" maxLength={40} placeholder="满意了就起个名字" value={designName} disabled={!designed} onChange={e=>setDesignName(e.target.value)}/>
    <button disabled={!designed||!designName.trim()||!!saving} onClick={()=>void run(async()=>{setSaving('design');
      try{await request('/voices/custom','POST',{name:designName,language,reference_text:text,from_design:designed!.file});setDesignName('');setDesigned(null);setDesigns([]);setLock(null);await reload()}finally{setSaving('')}})}>{saving==='design'?'保存中…':'保存选中的这版'}</button>
   </div>
   {designs.length>0&&<ul className="design-versions" aria-label="已生成的版本">{designs.map((v,i)=><li key={v.file}><button className={designed?.file===v.file?'active':''} aria-pressed={designed?.file===v.file} onClick={()=>{setDesigned({file:v.file,seconds:v.seconds,seed:v.seed});setPlaying('');const audio=player.current;if(audio){audio.src=v.url;void audio.play().catch(()=>setError('请点击播放按钮试听。'))}}}>▶ 第 {designs.length-i} 版 · {v.seconds.toFixed(1)} 秒 <small>{v.description} · 种子 {v.seed}</small></button></li>)}</ul>}
   {lock?<p className="design-lock">保持声音：以「{lock.from}」为底（种子 {lock.seed}）。改描述再生成，声音会接近它；加「，语气严厉」之类可做语气版本，嗓音粗细可能跟着变一点。<button type="button" className="see-lines" onClick={()=>setLock(null)}>不再保持</button></p>
    :designed&&<p className="design-lock"><button type="button" onClick={()=>{const i=designs.findIndex(x=>x.file===designed.file);setLock({seed:designed.seed,from:'第 '+(designs.length-i)+' 版'})}}>以选中的这版为底微调</button> <small className="muted">差一点点就合适时用：保持这个声音，只改描述。</small></p>}
   {designs.length>0&&<p className="muted">不保持声音时，每点一次出一版不同的声音；最多留 8 版，点哪版就听哪版，保存的就是它。</p>}
  </div>

  </>}
  {tab==='library'&&<>  <p className="hint">默认音色库 14 个声线随程序附带（第一次启动自动装入）。删掉了又想要回来：<button type="button" className="see-lines" disabled={!!waiting} onClick={()=>void run(async()=>{const r=await request('/voices/pack/install','POST',{});await reload();setError(r.installed?.length?'':'默认音色都在，没有需要装回的。')})}>装回默认音色</button></p>
  {custom.length>0&&<div className="custom-voices">
   <div className="section-label">已保存的音色</div>
   {custom.map(v=><article className="voice-row" key={v.id}>
    <div className="voice-name"><strong>{v.name}</strong>
     <small>{v.source==='generated'?`合成自 ${v.derived_from??'预设'}`:'提供的录音 · 已确认授权'} · {v.seconds.toFixed(1)} 秒</small>{tagEditing==='custom:'+v.id?<input autoFocus className="tag-input" aria-label={v.name+' 的标签'} defaultValue={tagsOf('custom:'+v.id,v.derived_from??'').join('、')} placeholder="标签，顿号分隔：老人、男性、威严" onBlur={e=>void saveTags('custom:'+v.id,e.target.value,v.derived_from??'')} onKeyDown={e=>{if(e.key==='Enter')void saveTags('custom:'+v.id,(e.target as HTMLInputElement).value,v.derived_from??'');if(e.key==='Escape')setTagEditing(null)}}/>:<button type="button" className="tags" title="改标签" onClick={()=>setTagEditing('custom:'+v.id)}>{tagsOf('custom:'+v.id,v.derived_from??'').map(t=><span key={t}>{t}</span>)}<span className="tag-edit">✎</span></button>}</div>
    <button onClick={()=>{const a=player.current;if(a){a.src='/api/voices/custom/'+v.id+'/audio';void a.play().catch(()=>{})}}}>听参考</button>
    {designReady&&(()=>{const o=designOrigin(v,custom);return o&&<button title={'以它为底改描述：'+o.description} onClick={()=>{setTab('design');setDesign(o.description);if(o.text)setText(o.text);setDesigns([]);setDesigned(null);setLock({seed:o.seed,from:v.name})}}>微调</button>})()}
    <button onClick={()=>void run(async()=>{const name=prompt('新的名称',v.name);if(name){await request('/voices/custom/'+v.id,'PATCH',{name});await reload()}})}>改名</button>
    <button className="danger" onClick={()=>void run(async()=>{if(confirm(`删除音色「${v.name}」？参考声音会一并删除。`)){await request('/voices/custom/'+v.id,'DELETE');await reload()}})}>删除</button>
    {onPick&&<button className="primary" onClick={()=>onPick('custom:'+v.id)}>用于此角色</button>}
   </article>)}
  </div>}
   {custom.length===0&&<p className="muted">还没有保存的音色。在「自带音色」里试听后「留下这个声音」，或在「声线设计」里设计一个。</p>}
  </>}
  {tab==='models'&&<><div className="keep-voice"><div className="section-label">选项</div>
   <label className="consent"><input type="checkbox" checked={autoplay} onChange={e=>{setAutoplay(e.target.checked);try{localStorage.setItem('voxstage-autoplay',e.target.checked?'1':'0')}catch{}}}/>生成语音后自动播放新声音（单句重做播那一句；批量生成播第一句）</label>
   <p className="muted">只是这台浏览器的偏好，不进工程。</p></div>  {roleModels&&roleModels.length>0&&<div className="keep-voice role-model" id="role-model-setting">
   <div className="section-label">分角色模型</div>
   <p className="muted">新建工程时给原文分旁白/对白、点出说话人的本机模型。每个都按 SHA-256 校验；草稿记录里写着是哪个模型答的。</p>
   <select aria-label="分角色模型" value={role} disabled={!!waiting} onChange={e=>{const id=e.target.value;setRole(id);setRoleNote('');void (async()=>{try{await request('/settings','POST',{role_model:id});setRoleNote('已切换，下一次生成角色草稿起生效。')}catch(err){setRoleNote((err as Error).message);setRole(roleModel??'')}})()}}>
    {roleModels.map(m=><option key={m.id} value={m.id} disabled={!m.installed}>{m.label}{m.installed?'':'（未安装：scripts/setup_model.py --model role-abliterated）'}</option>)}
   </select>
   {roleNote&&<p className="muted">{roleNote}</p>}
  </div>}
  </>}
  <p className="muted">试听是本机即时合成的，不会写进任何工程；语速在合成之后处理。</p>
  {error&&<p role="alert" className="line-error">{error}</p>}

 </section></div>;
}
// 最后更新：2026-09-11 · Claude Hera
