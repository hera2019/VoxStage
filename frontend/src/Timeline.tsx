import {useEffect,useMemo,useRef,useState,type RefObject} from 'react';
import {layoutClips,stretchClip,splitClip,type Clip,type Block} from './clipEditing';
import type {PlaybackContext,TimePiece} from './timeMapping';
export type Region={start:number;end:number;speed:number};export type Cut={start:number;end:number};
type Preview={url:string;duration:number;mapping:TimePiece[];processed_checks:{waveform:number[];markers:{start:number;end:number;label:string;basis:string}[];manual_checkpoints:string[]}};
type Props={text:string;speaker:string;projectId:string;revision:number;segmentId:string;fingerprint:string;regions:Region[];cuts:Cut[];stale:boolean;globalSpeed:number;disabled:boolean;speedReady:boolean;
 request:(path:string,method?:string,data?:unknown)=>Promise<any>;onSaved:(p:any)=>void;
 onPlay:(start?:number,end?:number,original?:boolean,outputTime?:boolean,loop?:boolean)=>Promise<void>;player:RefObject<HTMLAudioElement|null>;context:RefObject<PlaybackContext>;
 canUndo:boolean;canRedo:boolean;onHistory:(direction:'undo'|'redo')=>void};
type Drag={kind:string;id:string;anchor:number;base:Clip[];layout:Block[];next:Clip[];moved:boolean;span:number;origin:number};
export function Timeline(props:Props){
 const [expanded,setExpanded]=useState(false);const [clips,setClips]=useState<Clip[]>([]);const [preview,setPreview]=useState<Preview>();const [draft,setDraft]=useState<Clip[]|null>(null);
 const [selected,setSelected]=useState('');const [speedInput,setSpeedInput]=useState('1');const [looping,setLooping]=useState(false);const [cursor,setCursor]=useState(0);const [playing,setPlaying]=useState(false);const [original,setOriginal]=useState(false);
 const [zoom,setZoom]=useState(1);const [viewStart,setViewStart]=useState(0);const [loading,setLoading]=useState(false);const [saving,setSaving]=useState(false);const [error,setError]=useState('');const [message,setMessage]=useState('已保存到本机');
 const panel=useRef<HTMLElement>(null);const scroller=useRef<HTMLDivElement>(null);const saveLock=useRef(false);const preparedRevision=useRef<number|null>(null);const drag=useRef<Drag|null>(null);
 const apiBase=`/projects/${props.projectId}/segments/${props.segmentId}`;const blocked=props.disabled||loading||saving;
 const actual=useMemo(()=>layoutClips(clips,props.globalSpeed,preview?.mapping),[clips,props.globalSpeed,preview]);
 const blocks=useMemo(()=>draft?layoutClips(draft,props.globalSpeed):actual,[draft,props.globalSpeed,actual]);
 const duration=blocks.at(-1)?.end??0;const span=duration/zoom||1;const origin=Math.min(viewStart,Math.max(0,duration-span));const x=(v:number)=>(v-origin)/span*800;
 const chosen=blocks.find(b=>b.id===selected);const playbackBlock=blocks.find(b=>cursor>b.start+.001&&cursor<b.end-.001);
 useEffect(()=>{const open=()=>{if(!props.disabled){props.player.current?.pause();setExpanded(true)}};
 window.addEventListener('voxstage:open-editor',open);return()=>window.removeEventListener('voxstage:open-editor',open)},[props.disabled]);
 useEffect(()=>{if(!expanded)return;return()=>{if(props.context.current.loop){props.player.current?.pause();props.context.current.loop=false}}},[expanded]);
 useEffect(()=>{setSpeedInput(String(chosen?.effectiveSpeed??1))},[selected,chosen?.effectiveSpeed]);
 useEffect(()=>{if(!expanded||preparedRevision.current===props.revision)return;let ended=false;setLoading(true);setError('');props.player.current?.pause();
 Promise.all([props.request(apiBase+'/clips'),props.request(apiBase+'/preview','POST',{revision:props.revision})]).then(([plan,audio])=>{if(ended)return;if(plan.revision!==props.revision)throw new Error('工程已变化，请返回后重新打开。');preparedRevision.current=plan.revision;setClips(plan.clips);setPreview(audio);setMessage('已保存到本机，试听与导出使用当前版本');setDraft(null);setOriginal(false);setCursor(v=>Math.min(v,audio.duration));setSelected(v=>plan.clips.some((c:Clip)=>c.id===v)?v:plan.clips[0]?.id??'')}).catch(e=>{if(!ended)setError(e.message)}).finally(()=>{if(!ended)setLoading(false)});return()=>{ended=true}
 },[expanded,apiBase,props.revision]);
 useEffect(()=>{preparedRevision.current=null;setCursor(0);setPreview(undefined);setClips([]);setZoom(1);setViewStart(0)},[props.fingerprint]);
 useEffect(()=>{if(!expanded)return;const audio=props.player.current;if(!audio)return;let frame=0;const tick=()=>{const c=props.context.current;const active=c.segmentId===props.segmentId;setPlaying(active&&!audio.paused);setLooping(active&&!audio.paused&&!!c.loop);setOriginal(active&&c.original);if(active&&!audio.paused&&!c.original){const t=audio.currentTime;setCursor(t);if(t<origin||t>origin+span)setViewStart(Math.max(0,Math.min(duration-span,t-span*.15)))}frame=requestAnimationFrame(tick)};frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame)},[expanded,props.segmentId,duration,origin,span]);
 useEffect(()=>{if(!expanded)return;const before=document.activeElement as HTMLElement;const overflow=document.body.style.overflow;document.body.style.overflow='hidden';panel.current?.focus();
 const key=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!saving&&!loading)setExpanded(false);if(e.key==='Tab'){const elements=Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),[tabindex="0"]')??[]).filter(x=>x.getClientRects().length);const first=elements[0],last=elements.at(-1);if(e.shiftKey&&(document.activeElement===first||document.activeElement===panel.current)){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}};document.addEventListener('keydown',key);return()=>{document.body.style.overflow=overflow;document.removeEventListener('keydown',key);before?.focus()}
 },[expanded,saving,loading]);
 const paths=useMemo(()=>{if(!preview)return new Map<string,string>();const result=new Map<string,string>();for(const b of blocks){const old=actual.find(v=>v.id===b.id);if(!old)continue;const values=preview.processed_checks.waveform;let path='';for(let i=0;i<values.length;i++){const t=(i+.5)/values.length*preview.duration;if(t<old.start||t>=old.end)continue;const output=b.start+(t-old.start)/(old.end-old.start)*(b.end-b.start);if(output<origin||output>origin+span)continue;const at=(output-origin)/span*800,n=values[i];path+=`M${at.toFixed(2)},${68-n*33}V${68+n*33} `}result.set(b.id,path)}return result},[preview,actual,blocks,origin,span]);
 async function save(next:Clip[]){
  if(saveLock.current)return;saveLock.current=true;props.player.current?.pause();setSaving(true);setDraft(next);setError('');setMessage('正在处理并保存…');setOriginal(false);
  let committed=false;
  try{
   const p=await props.request(apiBase+'/clips','POST',{revision:props.revision,clips:next});committed=true;
   // Keep the draft until the new audio and its time mapping are ready together.
   const audio=await props.request(apiBase+'/preview','POST',{revision:p.revision});
   preparedRevision.current=p.revision;setClips(next);setPreview(audio);setDraft(null);setCursor(v=>Math.min(v,audio.duration));setSelected(v=>next.some(c=>c.id===v)?v:next[0]?.id??'');props.onSaved(p);
   setMessage('已保存到本机，试听与导出已更新');
  }catch(e){setDraft(null);setError((e as Error).message);setMessage(committed?'剪辑已保存，声音预览未更新，请重新载入':'保存失败，已保留之前的版本')}
  finally{saveLock.current=false;setSaving(false)}
 }
 async function refresh(){setLoading(true);setError('');try{const p=await props.request('/projects/'+props.projectId);const plan=await props.request(apiBase+'/clips');const audio=await props.request(apiBase+'/preview','POST',{revision:p.revision});if(plan.revision!==p.revision)throw new Error('工程再次变化，请重新载入。');preparedRevision.current=p.revision;setClips(plan.clips);setPreview(audio);setDraft(null);setSelected(plan.clips[0]?.id??'');setCursor(0);props.onSaved(p);setMessage('已重新载入本机保存的版本，请重试刚才的操作')}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
 useEffect(()=>{const el=scroller.current;if(!el)return;const update=()=>{const width=el.scrollWidth-el.clientWidth;const desired=duration>span?origin/(duration-span)*width:0;if(Math.abs(el.scrollLeft-desired)>.5)el.scrollLeft=desired};update();const observer=new ResizeObserver(update);observer.observe(el);return()=>observer.disconnect()},[origin,duration,span,expanded,zoom]);
 function point(e:React.PointerEvent<SVGSVGElement>){const rect=e.currentTarget.getBoundingClientRect();return Math.max(0,(drag.current?.origin??origin)+(e.clientX-rect.left)/rect.width*(drag.current?.span??span))}
 function down(e:React.PointerEvent<SVGSVGElement>){if(blocked||e.button!==0||!e.isPrimary)return;e.preventDefault();props.player.current?.pause();const target=e.target as Element;const id=target.closest('[data-clip-id]')?.getAttribute('data-clip-id');const time=Math.min(duration,point(e));setCursor(time);if(!id)return;setSelected(id);drag.current={kind:target.getAttribute('data-edge')??'move',id,anchor:point(e),base:clips.map(c=>({...c})),layout:actual,next:clips,moved:false,span,origin};e.currentTarget.setPointerCapture(e.pointerId)}
 function move(e:React.PointerEvent<SVGSVGElement>){const d=drag.current;if(!d)return;const time=point(e),delta=time-d.anchor;if(Math.abs(delta)<.025&&!d.moved)return;d.moved=true;const block=d.layout.find(b=>b.id===d.id)!;
 if(d.kind==='left'||d.kind==='right'){const desired=block.end-block.start+(d.kind==='right'?delta:-delta);d.next=d.base.map(c=>c.id===d.id?stretchClip(c,desired):c)}
 else{const others=d.base.filter(c=>c.id!==d.id);const index=d.layout.filter(b=>b.id!==d.id&&(b.start+b.end)/2<time).length;others.splice(index,0,d.base.find(c=>c.id===d.id)!);d.next=others}
 setDraft(d.next);setMessage(d.kind==='move'?'松开后保存新顺序':'松开后保存新时长（0.5–2.0 倍）')}
 function up(e:React.PointerEvent<SVGSVGElement>){const d=drag.current;drag.current=null;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);if(d?.moved&&JSON.stringify(d.next)!==JSON.stringify(d.base))void save(d.next);else{setDraft(null);setMessage('已保存到本机')}}
 async function toggle(){if(playing){props.player.current?.pause();return}if(!blocked)await props.onPlay(cursor>=duration-.02?0:cursor,undefined,false,true)}
 function split(){if(blocked||!playbackBlock||clips.length>=40)return;try{void save(splitClip(clips,playbackBlock,cursor,crypto.randomUUID()))}catch(e){setError((e as Error).message)}}
 function selectBlock(id:string){const b=actual.find(b=>b.id===id);if(!b)return;props.player.current?.pause();setSelected(id);setCursor(b.start);setViewStart(Math.max(0,b.start-span*.1))}
 function applySpeed(){const speed=Number(speedInput);if(!speedInput.trim()||!Number.isFinite(speed)||speed<.5||speed>2){setError('请输入 0.5–2.0 之间的速度。');return}if(chosen)void save(clips.map(c=>c.id===chosen.id?{...c,speed}:c))}
 function shortcut(e:React.KeyboardEvent<HTMLElement>){
  const target=e.target as HTMLElement;if(target.closest('input,textarea,select,[contenteditable="true"]')||e.repeat||blocked)return;
  const key=e.key.toLowerCase(),mod=e.metaKey||e.ctrlKey;
  if(mod&&key==='z'){e.preventDefault();if(e.shiftKey?props.canRedo:props.canUndo)props.onHistory(e.shiftKey?'redo':'undo');return}
  if(mod||e.altKey)return;
  if(key===' '&&!target.closest('button,summary')){e.preventDefault();void toggle()}
  else if(key==='s'&&playbackBlock&&clips.length<40){e.preventDefault();split()}
  else if((key==='delete'||key==='backspace')&&!target.closest('button,summary')&&chosen&&clips.length>1){e.preventDefault();void save(clips.filter(c=>c.id!==selected))}
  else if((key==='arrowleft'||key==='arrowright')&&!target.closest('button,summary')&&!target.closest('.timeline-scrollbar')){e.preventDefault();props.player.current?.pause();const t=Math.max(0,Math.min(duration,cursor+(key==='arrowright'?1:-1)*(e.shiftKey?1:.1)));setCursor(t);if(t<origin||t>origin+span)setViewStart(Math.max(0,t-span*.1))}
 }
 if(!expanded)return null;
 return <section ref={panel} tabIndex={-1} role="dialog" aria-modal="true" className="timeline-editor editor-expanded block-editor" aria-label="精细剪辑" onKeyDown={shortcut}>
 <div className="timeline-heading"><div><span className="section-label">VOXSTAGE / AUDIO EDITOR</span><h3>精细剪辑 <small>{props.speaker}</small></h3></div><button disabled={saving||loading} onClick={()=>setExpanded(false)}>返回工作台</button></div>
 <div className="editor-caption"><p title={props.text}>{props.text}</p><p role="status" className={'save-state '+(error?'failed':'')}>{loading?'正在准备时间线…':saving?'正在保存…':draft?'松手自动保存':error?message:'✓ 已保存到本机'}</p></div>
 {error&&<div className="editor-error"><p role="alert" className="line-error">{error}</p><button disabled={saving||loading} onClick={()=>void refresh()}>重新载入已保存版本</button></div>}
 <div className="timeline-surface"><div className="timeline-viewbar"><span>{clips.length} 个区块 · {original?'正在对照原音':'成品时间线'}</span>
 <div className="zoom-controls"><label>查看比例<select aria-label="波形查看比例" value={zoom} onChange={e=>{props.player.current?.pause();setZoom(Number(e.target.value));setViewStart(Math.max(0,cursor-.2))}}>{[1,2,4,8].map(n=><option value={n} key={n}>{n} 倍放大</option>)}</select></label><button onClick={()=>{setZoom(1);setViewStart(0)}}>查看全句</button></div> </div>
 <div className="time-ruler top-ruler" aria-label="时间刻度尺">{Array.from({length:21},(_,i)=><span className={i%5===0?'major':'minor'} style={{left:`${i*5}%`}} key={i}>{i%5===0?<b>{(origin+span*i/20).toFixed(2)} 秒</b>:null}</span>)}</div>
 <svg className="waveform block-waveform" role="img" tabIndex={0} aria-label="成品区块时间线，拖中间重排，拖两端变速" viewBox="0 0 800 120" preserveAspectRatio="none" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={()=>{drag.current=null;setDraft(null);setMessage('已取消拖动')}}>
 {blocks.map((b,i)=><g data-clip-id={b.id} key={b.id}>
 <rect className="clip-body" x={x(b.start)+1} y="1" width={Math.max(1,(b.end-b.start)/span*800-2)} height="118" rx="4" fill={b.id===selected?'#e1edf5':'#eaf0e4'} stroke={b.id===selected?'#5e8db1':'#c3cdbd'} strokeWidth="1"/>
 <text x={x(b.start)+9} y="18" fontSize="11" fill="#50646a" pointerEvents="none">{(b.end-b.start)/span*800>75?`${i+1} · ${b.effectiveSpeed.toFixed(2)}×`:(b.end-b.start)/span*800>14?i+1:''}</text>
 <path d={paths.get(b.id)??''} stroke="#6b8978" strokeWidth="1" fill="none" pointerEvents="none"/>
 <rect data-edge="left" className="clip-edge" x={x(b.start)} y="0" width="14" height="120" fill="transparent"/>
 <rect data-edge="right" className="clip-edge" x={x(b.end)-14} y="0" width="14" height="120" fill="transparent"/>
 <line x1={x(b.start)+1} x2={x(b.start)+1} y1="3" y2="117" stroke="#5597c6" strokeWidth="1.5" vectorEffect="non-scaling-stroke" pointerEvents="none"/>
 <line x1={x(b.end)-1} x2={x(b.end)-1} y1="3" y2="117" stroke="#5597c6" strokeWidth="1.5" vectorEffect="non-scaling-stroke" pointerEvents="none"/>
 </g>)}
 {preview?.processed_checks.markers.map((m,i)=><rect key={i} x={x(m.start)} width={(m.end-m.start)/span*800} y="25" height="90" fill="#dfa64e" opacity=".18" pointerEvents="none"/>)}
 {!original&&<line data-testid="playhead" x1={x(cursor)} x2={x(cursor)} y1="0" y2="120" stroke="#c4533b" strokeWidth="1.5" vectorEffect="non-scaling-stroke" pointerEvents="none"/>}
 </svg>

 <div ref={scroller} className="timeline-scrollbar" tabIndex={0} aria-label="时间线横向滚动条" onScroll={e=>{const el=e.currentTarget;const width=el.scrollWidth-el.clientWidth;if(width>0&&!drag.current)setViewStart(el.scrollLeft/width*Math.max(0,duration-span))}}><div style={{width:`${zoom*100}%`,height:1}}/></div>

 <div className="editor-transport" role="group" aria-label="播放控制"><button className="primary" disabled={blocked&&!playing} onClick={()=>void toggle()}>{playing?'暂停':'播放成品'}</button><button disabled={blocked} onClick={()=>{props.player.current?.pause();setCursor(0);setViewStart(0)}}>回到开头</button><output aria-label="成品播放位置">{cursor.toFixed(2)} / {duration.toFixed(2)} 秒</output><button disabled={blocked} onClick={()=>props.onPlay(0,undefined,true)}>对照原音</button><button disabled={blocked||!props.canUndo} onClick={()=>props.onHistory('undo')}>撤销剪辑</button><button disabled={blocked||!props.canRedo} onClick={()=>props.onHistory('redo')}>重做剪辑</button><a className="clip-download" href={!blocked&&!draft?preview?.url:undefined} aria-disabled={blocked||!!draft||!preview} download={`VoxStage-${props.speaker.replace(/[\\/:*?"<>|]/g,'_')}.wav`}>导出这句 WAV ↓</a></div>
 <p className="timeline-hint">{original?'正在播放未剪辑的原音。播放成品可试听修改后的声音。':draft?'正在调整，松手自动保存。':'拖中间重排，拖蓝色边缘变速；点击波形定位。'}</p></div>
 <div className="editor-lower"><div className="edit-controls">

 <div className="block-actions"><label>切割线（成品秒数）<input aria-label="切割线位置" type="number" min="0" max={duration} step=".01" value={Number(cursor.toFixed(3))} disabled={blocked} onChange={e=>{props.player.current?.pause();setCursor(Math.max(0,Math.min(duration,Number(e.target.value))))}}/></label><button className="primary" disabled={blocked||!playbackBlock||clips.length>=40} onClick={split}>在播放线切开</button><button disabled={blocked||!chosen} onClick={()=>chosen&&props.onPlay(chosen.start,chosen.end,false,true)}>试听选中区块</button><button className="cut-button" disabled={blocked||!chosen||clips.length<2} onClick={()=>void save(clips.filter(c=>c.id!==selected))}>删除选中区块</button></div>
 {chosen&&<div className="block-detail"><div className="block-selector"><label>选中区块<select aria-label="选中区块" disabled={blocked} value={selected} onChange={e=>selectBlock(e.target.value)}>{blocks.map((b,i)=><option key={b.id} value={b.id}>区块 {i+1} · {(b.end-b.start).toFixed(2)} 秒</option>)}</select></label><button disabled={blocked} onClick={()=>{if(chosen){setZoom(Math.min(8,Math.max(1,Math.floor(duration/(chosen.end-chosen.start)))));setViewStart(chosen.start)}}}>放大选中区块</button></div><strong>区块 {blocks.indexOf(chosen)+1} · {(chosen.end-chosen.start).toFixed(3)} 秒 · {chosen.effectiveSpeed.toFixed(2)} 倍</strong><p>原音 {chosen.source_start.toFixed(2)}–{chosen.source_end.toFixed(2)} 秒，拉伸保留这段声音的全部内容。</p><div className="speed-entry"><label>区块速度<input aria-label="区块速度" type="number" min=".5" max="2" step=".01" disabled={blocked} value={speedInput} onChange={e=>{setSpeedInput(e.target.value);if(error.startsWith('请输入'))setError('')}} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();applySpeed()}}}/><span>倍</span></label><button disabled={blocked||Number(speedInput)===chosen.effectiveSpeed} onClick={applySpeed}>应用速度</button><button aria-pressed={looping} disabled={blocked&&!looping} onClick={()=>{if(looping)props.player.current?.pause();else if(chosen)void props.onPlay(chosen.start,chosen.end,false,true,true)}}>{looping?'停止循环':'循环试听'}</button></div><div className="buttons"><button disabled={blocked||blocks.indexOf(chosen)===0} onClick={()=>{const index=clips.findIndex(c=>c.id===selected);if(index>0){const next=[...clips];[next[index-1],next[index]]=[next[index],next[index-1]];void save(next)}}}>前移一块</button><button disabled={blocked||blocks.indexOf(chosen)===blocks.length-1} onClick={()=>{const index=clips.findIndex(c=>c.id===selected);if(index<clips.length-1){const next=[...clips];[next[index],next[index+1]]=[next[index+1],next[index]];void save(next)}}}>后移一块</button><button disabled={blocked} onClick={()=>void save(clips.map(c=>c.id===selected?{...c,speed:null}:c))}>跟随整段语速</button></div></div>}
 </div><aside className="editor-notes">
 <details className="rhythm-cues"><summary>成品复核线索 · {preview?.processed_checks.markers.length??0} 处待试听</summary><p>橙色提示较长停顿，可能是正常断句，不能自动判为错误。</p>{preview?.processed_checks.markers.map((m,i)=><div className="rhythm-cue" key={i}><button disabled={blocked} onClick={()=>{setCursor(m.start);void props.onPlay(Math.max(0,m.start-.3),Math.min(duration,m.end+.4),false,true)}}>{m.start.toFixed(2)}–{m.end.toFixed(2)} 秒 · {m.label}</button><small>{m.basis}</small></div>)}<p>还需人工复核：{preview?.processed_checks.manual_checkpoints.join('；')}。语速起伏仍可能漏检。</p></details>
 <details className="editor-help"><summary>操作说明与保存方式</summary><p>时间线上：空格播放/暂停，← → 移动 0.1 秒，Shift + 方向键移动 1 秒，S 切开，Delete 删除。⌘Z 撤销，⌘⇧Z 重做（Windows 使用 Ctrl）。输入框内保留正常输入。</p><p>拖中间调整顺序，拖两端拉长或缩短。伸缩保留区块内容，速度范围 0.5–2.0 倍。</p><p>松手、切割、删除后自动保存；可撤销，原音保留。极端变速可能失真。</p>
 <p>剪切或重排后，请重新核对成品内容和字幕；原音文字检查不等于成品通过。{props.stale&&' 旧剪辑已因原音换版本停用。'}</p></details>
 </aside></div></section>
}
// 最后更新：2026-09-09 · Astra
