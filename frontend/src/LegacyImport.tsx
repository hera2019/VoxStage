import {useEffect,useState} from 'react';
import {tr} from './i18n';

type Preview={import_id:string;projects:{id:string;name:string}[];books:number;bytes:number;voices:number;provided_recordings:string[];conflicts:string[];skipped?:string[]};
type NativeWindow=Window&{webkit?:{messageHandlers?:{voxstage?:{postMessage:(value:unknown)=>void}}}};
export function LegacyImport({request,blocked}:{request:(path:string,method?:string,data?:unknown)=>Promise<any>;blocked:boolean}){
 const [preview,setPreview]=useState<Preview>();const [error,setError]=useState('');
 const [consent,setConsent]=useState(false);const [copy,setCopy]=useState(false);const [working,setWorking]=useState(false);
 const bridge=(window as NativeWindow).webkit?.messageHandlers?.voxstage;
 useEffect(()=>{
  const choose=()=>{if(blocked){setError(tr("请先保存编辑并等待本机任务结束，再导入旧数据。"));return}setError('');bridge?.postMessage({action:'chooseImportFolder'})};
  const toggle=()=>{if(blocked){setError(tr("请先保存编辑并等待本机任务结束，再切换局域网访问。"));return}bridge?.postMessage({action:'toggleLAN'})};
  const receive=(event:Event)=>{const data=(event as CustomEvent).detail;if(data?.error){setError(tr(data.error));return}setPreview(data);setConsent(false);setCopy(false);setError('')};
  window.addEventListener('voxstage-request-network-toggle',toggle);window.addEventListener('voxstage-request-import',choose);window.addEventListener('voxstage-import-preview',receive);
  return()=>{window.removeEventListener('voxstage-request-network-toggle',toggle);window.removeEventListener('voxstage-request-import',choose);window.removeEventListener('voxstage-import-preview',receive)};
 },[blocked,bridge]);
 const commit=async()=>{if(!preview)return;setWorking(true);setError('');try{await request('/legacy-import/'+preview.import_id+'/commit','POST',{copy,consent});window.location.reload()}catch(e){setError((e as Error).message)}finally{setWorking(false)}};
 return <>{bridge&&<button className="archive-toggle" disabled={blocked||working} onClick={()=>{setError('');bridge.postMessage({action:'chooseImportFolder'})}}>{tr("从旧数据文件夹导入…")}</button>}
 {error&&!preview&&<p role="alert">{error}</p>}
 {preview&&<div className="model-manager-backdrop"><section className="model-manager" role="dialog" aria-modal="true" aria-labelledby="legacy-import-title">
  <header><h2 id="legacy-import-title">{tr("导入旧数据")}</h2><button disabled={working} onClick={()=>setPreview(undefined)}>{tr("取消")}</button></header>
  <p>{tr("发现 {0} 个工程、{1} 个主工程、{2} 个相关音色。",preview.projects.length,preview.books,preview.voices)}</p>
  <p>{tr("导入工程、原音、固定声线和最新导出；模型、日志、访问口令和全局设置不导入。旧文件保持不变。")}</p>
  <ul>{preview.projects.map(p=><li key={p.id}>{p.name||p.id}</li>)}</ul>
  {(preview.skipped?.length??0)>0&&<p>{tr("不导入：{0}。这些工程用到的音色已从旧音色库删除，开发版也无法打开。",preview.skipped!.join('、'))}</p>}
  {preview.conflicts.length>0&&<><p>{tr("部分工程已经存在，导入副本可保留两份。")}</p><label><input type="checkbox" checked={copy} disabled={working} onChange={e=>setCopy(e.target.checked)}/>{tr("全部作为副本导入，不覆盖已有工程")}</label></>}
  {preview.provided_recordings.length>0&&<><p>{tr("包含参考录音：{0}",preview.provided_recordings.join('、'))}</p><label><input type="checkbox" checked={consent} disabled={working} onChange={e=>setConsent(e.target.checked)}/>{tr("我拥有这些录音的声音使用权，或已获得本人明确授权。")}</label></>}
  {error&&<p role="alert">{error}</p>}<footer><button disabled={working||blocked||(preview.conflicts.length>0&&!copy)||(preview.provided_recordings.length>0&&!consent)} onClick={()=>void commit()}>{working?tr("正在导入…"):tr("确认导入")}</button><button disabled={working} onClick={()=>setPreview(undefined)}>{tr("取消")}</button></footer>
 </section></div>}</>
}
