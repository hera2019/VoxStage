import {useState} from 'react';

/** The compact master/sub-project list: one accordion per master book, its
 *  chapters underneath in book order, unprocessed ones marked and given
 *  their continue entry (disabled until Sol 二 opens processing). Expanding
 *  a book only changes the navigation; the editor keeps the last project
 *  really opened, and a collapsed book carries a ● when that project lives
 *  in it. Opus 一, 2026-09-20. */
export type Listed={id:string;name:string;archived?:boolean;processing_state?:string|null;settings_schema?:number|null;book?:{id:string;title?:string;index?:number;chapters?:number}|null};
type Props={projects:Listed[];emptyBooks?:{id:string;title:string}[];archivedBooks?:Set<string>;showArchived?:boolean;current?:string;busyBooks?:Set<string>;disabled?:boolean;onOpen:(id:string)=>void;onSettings:(kind:'project'|'book',id:string)=>void;onContinue?:(id:string)=>void;onOpenBook?:(bookId:string)=>void;openBook?:string|null;onNewBook?:()=>void};

export function groupByBook<T extends Listed>(projects:T[]){
 const books=new Map<string,{title:string;chapters:T[]}>();const loose:T[]=[];
 for(const p of projects){
  if((p.processing_state||p.settings_schema===1)&&p.book?.id){const b=books.get(p.book.id)??{title:p.book.title??'未命名',chapters:[]};b.chapters.push(p);books.set(p.book.id,b)}
  else loose.push(p);
 }
 for(const b of books.values())b.chapters.sort((a,c)=>(a.book?.index??0)-(c.book?.index??0));
 return {books,loose};
}

export function BookList({projects,emptyBooks=[],archivedBooks,showArchived,current,busyBooks,disabled,onOpen,onSettings,onContinue,onOpenBook,openBook,onNewBook}:Props){
 const {books}=groupByBook(projects);
 for(const b of emptyBooks)if(!books.has(b.id))books.set(b.id,{title:b.title,chapters:[]});
 // 本人 2026-09-21: books in the order of their latest activity — the newest chapter change, or the last time the book was opened here.
 const opened=(id:string)=>{try{return Number(localStorage.getItem('voxstage-book-opened-'+id))||0}catch{return 0}};
 // A book is archived when the book says so or every chapter is; it then lives under 查看归档工程 (本人 2026-09-21).
 const isArchived=(id:string,chapters:Listed[])=>!!archivedBooks?.has(id)||(chapters.length>0&&chapters.every(c=>c.archived));
 const entries=[...books.entries()].filter(([id,b])=>!!showArchived===isArchived(id,b.chapters)).sort((a,b)=>Math.max(opened(b[0]),...b[1].chapters.map(c=>((c as Listed&{updated_at?:number}).updated_at??0)*1000))-Math.max(opened(a[0]),...a[1].chapters.map(c=>((c as Listed&{updated_at?:number}).updated_at??0)*1000)));
 const [open,setOpen]=useState<string|null>(()=>{try{return localStorage.getItem('voxstage-open-book')}catch{return null}});
 if(entries.length===0&&!(onNewBook&&!showArchived))return null;
 const toggle=(id:string)=>{const next=open===id?null:id;setOpen(next);try{if(next)localStorage.setItem('voxstage-open-book',next);else localStorage.removeItem('voxstage-open-book')}catch{}};
 return <div className="book-list"><div className="section-label">{showArchived?'已归档的主工程':'主工程'}{onNewBook&&!showArchived&&<button type="button" className="see-lines" title="新建一个空的主工程，再把已有的工程加进来" disabled={disabled} onClick={onNewBook}>＋ 新建</button>}</div>
  {entries.map(([id,b])=>{const here=b.chapters.some(c=>c.id===current);const expanded=open===id;const busy=busyBooks?.has(id);
   return <div key={id} className={'book-master '+(expanded?'expanded':'')}>
    <div className="book-master-row"><button type="button" className="book-master-fold" aria-label={expanded?'折叠':'展开'} onClick={()=>toggle(id)}>{expanded?'▾':'▸'}</button><button type="button" className={'book-master-title '+(openBook===id?'active':'')} title="打开主工程：章节、设置、结构、导出" onClick={()=>{try{localStorage.setItem('voxstage-book-opened-'+id,String(Date.now()))}catch{}onOpenBook?.(id);if(!expanded)toggle(id)}}>《{b.title}》{isArchived(id,b.chapters)&&<small> · 已归档</small>} <small>{b.chapters.length} 章{busy?' · 处理中':''}</small>{!expanded&&here&&<span className="book-here" title="当前打开的工程在这里">●</span>}</button></div>
    {expanded&&<ol className="book-chapters">{b.chapters.map(c=>{const done=c.processing_state!=='unprocessed';
     return <li key={c.id} className={(c.id===current?'current ':'')+(done?'':'unprocessed')}>
      <button type="button" disabled={disabled||(!done&&!onContinue)} title={done?'打开':'还没处理：从这里继续'} onClick={()=>done?onOpen(c.id):onContinue?.(c.id)}>{c.book?.index?`${c.book.index}. `:''}{c.name}{!done&&<small> · 未处理{onContinue?' · 继续':''}</small>}</button>
      <button type="button" className="book-chapter-settings" aria-label={c.name+' 的设置'} title="本章设置" disabled={disabled} onClick={()=>onSettings('project',c.id)}>⚙</button></li>})}</ol>}
   </div>})}
 </div>;
}
