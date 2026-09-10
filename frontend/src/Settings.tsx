import {useEffect,useRef,useState} from 'react';
type Props={request:(path:string,method?:string,data?:unknown)=>Promise<any>;voices:Record<string,string>;
 language:'zh'|'en';speedReady:boolean;onClose:()=>void;onPick?:(voice:string)=>void;pickFor?:string};
const SAMPLES={zh:'雨点轻轻敲着窗，她回头看了一眼。',en:'Rain tapped against the window, and she looked back once.'};

export function Settings({request,voices,language,speedReady,onClose,onPick,pickFor}:Props){
 const [tab,setTab]=useState<'voices'>('voices');
 const [text,setText]=useState(SAMPLES[language]);
 const [rate,setRate]=useState(1);
 const [favourites,setFavourites]=useState<string[]>([]);
 const [playing,setPlaying]=useState('');const [waiting,setWaiting]=useState('');const [error,setError]=useState('');
 const [heard,setHeard]=useState<Record<string,number>>({});
 const player=useRef<HTMLAudioElement>(null);
 useEffect(()=>{void request('/settings').then(s=>setFavourites(s.favourite_voices??[])).catch(()=>{})},[]);
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
   setHeard(h=>({...h,[voice]:r.seconds}));setPlaying(voice);
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
    {heard[voice]&&<small className="heard">{heard[voice].toFixed(1)} 秒</small>}
    <button disabled={!!waiting} onClick={()=>void audition(voice)}>{waiting===voice?'正在生成…':'试听'}</button>
    {onPick&&<button className="primary" onClick={()=>onPick(voice)}>用于此角色</button>}
   </article>})}
  </div>
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
  <p className="muted">试听是本机即时合成的，不会写进任何工程；语速在合成之后处理。</p>
  {error&&<p role="alert" className="line-error">{error}</p>}
 </section></div>;
}
// 最后更新：2026-09-11 · Claude Hera
