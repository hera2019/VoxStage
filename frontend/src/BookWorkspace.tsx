import {useState} from 'react';
import {ChapterSettings} from './ChapterSettings';
import {StructureDialog} from './StructureDialog';
import {BookExport} from './BookExport';
import type {Listed} from './BookList';

/** A master book opened in the middle of the screen (本人 2026-09-21: 点击主工程，
 *  直接把中间和右边的界面换掉): its title editable, its chapters with their state
 *  and a way in, and the book's settings, structure and export as pages of one
 *  view instead of three buttons squeezed beside the name. */
type Props={bookId:string;title:string;revision:number;chapters:Listed[];loose:Listed[];current?:string;busy?:boolean;request:(path:string,method?:string,data?:unknown)=>Promise<any>;
  presetModels?:string[];cloneModels?:string[];onOpenChapter:(id:string)=>void;onContinue:(id:string)=>void;onChapterSettings:(id:string)=>void;onRenamed:(title:string,revision:number)=>void;onChanged:()=>void;onDelete?:(withChapters:boolean)=>void;onDeleteChapter?:(id:string,name:string)=>void;archived?:boolean;onArchive?:(archived:boolean)=>void};
const PAGES:[string,string][]=[['chapters','章节'],['settings','设置'],['structure','结构'],['export','导出']];

export function BookWorkspace({bookId,title,revision,chapters,loose,current,busy,request,presetModels,cloneModels,onOpenChapter,onContinue,onChapterSettings,onRenamed,onChanged,onDelete,onDeleteChapter,archived,onArchive}:Props){
 const [page,setPage]=useState('chapters');const [name,setName]=useState(title);const [error,setError]=useState('');
 const rename=async()=>{const t=name.trim();if(!t||t===title)return;try{const r=await request(`/master-books/${bookId}`,'PATCH',{revision,title:t});onRenamed(r.title,r.revision)}catch(e){setError((e as Error).message);setName(title)}};
 const done=chapters.filter(c=>c.processing_state!=='unprocessed').length;
 return <section className="book-workspace" aria-label={`主工程《${title}》`}>
  <div className="book-workspace-head"><small className="eyebrow">主工程 · {chapters.length} 章，已处理 {done} 章{busy?' · 处理中':''}</small>
   <input className="book-title" aria-label="主工程名称" value={name} maxLength={120} onChange={e=>setName(e.target.value)} onBlur={()=>void rename()} onKeyDown={e=>{if(e.key==='Enter')(e.target as HTMLInputElement).blur()}}/>
   {error&&<p role="alert" className="line-error">{error}</p>}</div>
  <div role="tablist" className="setting-tabs">{PAGES.map(([k,l])=><button key={k} role="tab" aria-selected={page===k} onClick={()=>setPage(k)}>{l}</button>)}</div>
  {page==='chapters'&&<ol className="book-workspace-chapters">{chapters.map(c=>{const fresh=c.processing_state==='unprocessed';return <li key={c.id} className={c.id===current?'current':''}>
    <span className="chapter-name">{c.book?.index?`${c.book.index}. `:''}{c.name}</span><small>{fresh?'未处理':'已处理'}</small>
    <button type="button" className={fresh?'primary':''} onClick={()=>fresh?onContinue(c.id):onOpenChapter(c.id)}>{fresh?'继续处理':'打开'}</button>
    <button type="button" title="本章设置" onClick={()=>onChapterSettings(c.id)}>⚙</button>{onDeleteChapter&&<button type="button" className="danger inline" title="舍弃这一章：原文、声音一起删，主工程少一章" onClick={()=>onDeleteChapter(c.id,c.name)}>舍弃</button>}</li>})}{chapters.length===0&&<li className="muted">还没有章节：到「结构 → 加入独立工程」加入已有工程，或新建工程时选「加入作一章」。</li>}</ol>}
  {page==='chapters'&&<p className="book-workspace-foot">{onArchive&&<><button type="button" onClick={()=>onArchive(!archived)}>{archived?'恢复整本到常用列表':'整本归档'}</button><small className="muted"> 做完不用了又舍不得删：整本连章节一起收进「查看归档工程」，随时可恢复。</small><br/></>}{onDelete&&<><button type="button" className="danger inline" onClick={()=>onDelete(false)}>{chapters.length?'解散并删除主工程':'删除主工程'}</button><small className="muted"> 章节会变回独立工程，声音和设置都保留；只删这本书的记录。</small>{chapters.length>0&&<> <button type="button" className="danger inline" onClick={()=>onDelete(true)}>连章节一起删除</button><small className="muted"> 全部章节的原文、声音一并删除，不能撤销。</small></>}</>}</p>}
  {page==='settings'&&<ChapterSettings kind="book" id={bookId} request={request} presetModels={presetModels} cloneModels={cloneModels} chapterIds={chapters.map(c=>c.id)} inline onClose={()=>setPage('chapters')}/>}
  {page==='structure'&&<StructureDialog bookId={bookId} title={title} chapters={chapters} loose={loose} request={request} inline onClose={()=>setPage('chapters')} onApplied={onChanged}/>}
  {page==='export'&&<BookExport bookId={bookId} title={title} chapters={chapters} request={request} inline onClose={()=>setPage('chapters')}/>}
 </section>;
}
