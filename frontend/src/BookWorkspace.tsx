import {useState} from 'react';
import {ChapterSettings} from './ChapterSettings';
import {StructureDialog} from './StructureDialog';
import {BookExport} from './BookExport';
import type {Listed} from './BookList';
import {tr} from './i18n';

/** A master book opened in the middle of the screen (本人 2026-09-21: 点击主工程，
 *  直接把中间和右边的界面换掉): its title editable, its chapters with their state
 *  and a way in, and the book's settings, structure and export as pages of one
 *  view instead of three buttons squeezed beside the name. */

/** A master book opened in the middle of the screen (本人 2026-09-21: 点击主工程，
 *  直接把中间和右边的界面换掉): its title editable, its chapters with their state
 *  and a way in, and the book's settings, structure and export as pages of one
 *  view instead of three buttons squeezed beside the name. */
type Props={bookId:string;title:string;revision:number;chapters:Listed[];loose:Listed[];current?:string;busy?:boolean;request:(path:string,method?:string,data?:unknown)=>Promise<any>;
  presetModels?:string[];cloneModels?:string[];voiceName?:(id:string|undefined)=>string;onOpenChapter:(id:string)=>void;onContinue:(id:string)=>void;onChapterSettings:(id:string)=>void;onRenamed:(title:string,revision:number)=>void;onChanged:()=>void;onDelete?:(withChapters:boolean)=>void;onDeleteChapter?:(id:string,name:string)=>void;archived?:boolean;onArchive?:(archived:boolean)=>void;onNewChapter?:()=>void;onPackage?:()=>void};
const PAGES:[string,string][]=[['chapters',tr("章节")],['settings',tr("设置")],['structure',tr("结构")],['export',tr("导出")]];

export function BookWorkspace({bookId,title,revision,chapters,loose,current,busy,request,presetModels,cloneModels,voiceName,onOpenChapter,onContinue,onChapterSettings,onRenamed,onChanged,onDelete,onDeleteChapter,archived,onArchive,onNewChapter,onPackage}:Props){
 // A long book (本人 2026-09-23: 网络小说 169 章): find a chapter by its number or words of its title, or show only what is left to process.
 const [query,setQuery]=useState('');const [onlyTodo,setOnlyTodo]=useState(false);
 const [page,setPage]=useState('chapters');const [name,setName]=useState(title);const [error,setError]=useState('');
 const rename=async()=>{const t=name.trim();if(!t||t===title)return;try{const r=await request(`/master-books/${bookId}`,'PATCH',{revision,title:t});onRenamed(r.title,r.revision)}catch(e){setError((e as Error).message);setName(title)}};
 const done=chapters.filter(c=>c.processing_state!=='unprocessed').length;
 return <section className="book-workspace" aria-label={tr("主工程《{0}》",title)}>
  <div className="book-workspace-head"><small className="eyebrow">{tr("主工程 · {0} 章，已处理 {1} 章{2}",chapters.length,done,busy?tr(" · 处理中"):'')}</small>
   <input className="book-title" aria-label={tr("主工程名称")} value={name} maxLength={120} onChange={e=>setName(e.target.value)} onBlur={()=>void rename()} onKeyDown={e=>{if(e.key==='Enter')(e.target as HTMLInputElement).blur()}}/>
   {error&&<p role="alert" className="line-error">{error}</p>}</div>
  <div role="tablist" className="setting-tabs">{PAGES.map(([k,l])=><button key={k} role="tab" aria-selected={page===k} onClick={()=>setPage(k)}>{l}</button>)}</div>
  {page==='chapters'&&chapters.length>12&&<div className="chapter-filter"><input type="search" aria-label={tr("找章节")} placeholder={tr("找章节：输入章号或标题里的字")} value={query} onChange={e=>setQuery(e.target.value)}/><label><input type="checkbox" checked={onlyTodo} onChange={e=>setOnlyTodo(e.target.checked)}/>{tr("只看未处理（")}{chapters.filter(c=>c.processing_state==='unprocessed').length}{tr("）")}</label></div>}
  {page==='chapters'&&<ol className="book-workspace-chapters">{chapters.filter(c=>(!onlyTodo||c.processing_state==='unprocessed')&&(!query.trim()||(/^\d+$/.test(query.trim())?String(c.book?.index??'')===query.trim():c.name.includes(query.trim())))).map(c=>{const fresh=c.processing_state==='unprocessed';return <li key={c.id} className={c.id===current?'current':''}>
    <span className="chapter-name">{c.book?.index?`${c.book.index}. `:''}{c.name}</span><small>{fresh?tr("未处理"):tr("已处理")}</small>
    <button type="button" className={fresh?'primary':''} onClick={()=>fresh?onContinue(c.id):onOpenChapter(c.id)}>{fresh?tr("继续处理"):tr("打开")}</button>
    <button type="button" title={tr("本章设置")} onClick={()=>onChapterSettings(c.id)}>⚙</button>{onDeleteChapter&&<button type="button" className="danger inline" title={tr("舍弃这一章：原文、声音一起删，主工程少一章")} onClick={()=>onDeleteChapter(c.id,c.name)}>{tr("舍弃")}</button>}</li>})}{chapters.length===0&&<li className="muted">{tr("还没有章节：点下面「＋ 新章」贴原稿或选文件——整本书也可以，有「第X章」这样的标题会按标题分成多章；或到「结构 → 加入独立工程」加入已有工程。")}</li>}</ol>}
  {page==='chapters'&&onNewChapter&&<p className="book-workspace-add"><button type="button" className="primary" disabled={busy} title={tr("贴一章原稿，作为这本书的下一章：继承这本书的声线、模型和停顿设置")} onClick={onNewChapter}>{tr("＋ 新章")}</button><small className="muted">{tr(" 贴一章或整本都行（整本按章节标题分成多章）；新章继承这本书的设置，也可以在表单里改成复制某一章的。")}</small></p>}
  {page==='chapters'&&<p className="book-workspace-foot">{onPackage&&<><button type="button" disabled={busy} onClick={onPackage}>{tr("打包整本")}</button><small className="muted">{tr(" 整本连章节、声音和用到的声线打成一个文件；删掉以后，导入这个文件就能恢复。")}</small><br/></>}{onArchive&&<><button type="button" onClick={()=>onArchive(!archived)}>{archived?tr("恢复整本到常用列表"):tr("整本归档")}</button><small className="muted">{tr(" 做完不用了又舍不得删：整本连章节一起收进「查看归档工程」，随时可恢复。")}</small><br/></>}{onDelete&&<><button type="button" className="danger inline" onClick={()=>onDelete(false)}>{chapters.length?tr("解散并删除主工程"):tr("删除主工程")}</button><small className="muted">{tr(" 章节会变回独立工程，声音和设置都保留；只删这本书的记录。")}</small>{chapters.length>0&&<> <button type="button" className="danger inline" onClick={()=>onDelete(true)}>{tr("连章节一起删除")}</button><small className="muted">{tr(" 全部章节的原文、声音一并删除，不能撤销。")}</small></>}</>}</p>}
  {page==='settings'&&<ChapterSettings kind="book" id={bookId} request={request} voiceName={voiceName} presetModels={presetModels} cloneModels={cloneModels} chapterIds={chapters.map(c=>c.id)} inline onClose={()=>setPage('chapters')}/>}
  {page==='structure'&&<StructureDialog bookId={bookId} title={title} chapters={chapters} loose={loose} request={request} inline onClose={()=>setPage('chapters')} onApplied={onChanged}/>}
  {page==='export'&&<BookExport bookId={bookId} title={title} chapters={chapters} request={request} inline onClose={()=>setPage('chapters')}/>}
 </section>;
}
