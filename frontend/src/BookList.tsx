import {useState} from 'react';

/** The compact master/sub-project list: one accordion per master book, its
 *  chapters underneath in book order, unprocessed ones marked and given
 *  their continue entry (disabled until Sol 二 opens processing). Expanding
 *  a book only changes the navigation; the editor keeps the last project
 *  really opened, and a collapsed book carries a ● when that project lives
 *  in it. Opus 一, 2026-09-20. */
export type Listed={id:string;name:string;archived?:boolean;processing_state?:string|null;book?:{id:string;title?:string;index?:number;chapters?:number}|null};
type Props={projects:Listed[];current?:string;busyBooks?:Set<string>;disabled?:boolean;onOpen:(id:string)=>void;onSettings:(kind:'project'|'book',id:string)=>void;onContinue?:(id:string)=>void;onOpenBook?:(bookId:string)=>void;openBook?:string|null};

export function groupByBook<T extends Listed>(projects:T[]){
 const books=new Map<string,{title:string;chapters:T[]}>();const loose:T[]=[];
 for(const p of projects){
  if(p.processing_state&&p.book?.id){const b=books.get(p.book.id)??{title:p.book.title??'未命名',chapters:[]};b.chapters.push(p);books.set(p.book.id,b)}
  else loose.push(p);
 }
 for(const b of books.values())b.chapters.sort((a,c)=>(a.book?.index??0)-(c.book?.index??0));
 return {books,loose};
}

export function BookList({projects,current,busyBooks,disabled,onOpen,onSettings,onContinue,onOpenBook,openBook}:Props){
 const {books}=groupByBook(projects);
 const [open,setOpen]=useState<string|null>(()=>{try{return localStorage.getItem('voxstage-open-book')}catch{return null}});
 if(books.size===0)return null;
 const toggle=(id:string)=>{const next=open===id?null:id;setOpen(next);try{if(next)localStorage.setItem('voxstage-open-book',next);else localStorage.removeItem('voxstage-open-book')}catch{}};
 return <div className="book-list"><div className="section-label">主工程</div>
  {[...books.entries()].map(([id,b])=>{const here=b.chapters.some(c=>c.id===current);const expanded=open===id;const busy=busyBooks?.has(id);
   return <div key={id} className={'book-master '+(expanded?'expanded':'')}>
    <div className="book-master-row"><button type="button" className="book-master-fold" aria-label={expanded?'折叠':'展开'} onClick={()=>toggle(id)}>{expanded?'▾':'▸'}</button><button type="button" className={'book-master-title '+(openBook===id?'active':'')} title="打开主工程：章节、设置、结构、导出" onClick={()=>{onOpenBook?.(id);if(!expanded)toggle(id)}}>《{b.title}》 <small>{b.chapters.length} 章{busy?' · 处理中':''}</small>{!expanded&&here&&<span className="book-here" title="当前打开的工程在这里">●</span>}</button></div>
    {expanded&&<ol className="book-chapters">{b.chapters.map(c=>{const done=c.processing_state!=='unprocessed';
     return <li key={c.id} className={(c.id===current?'current ':'')+(done?'':'unprocessed')}>
      <button type="button" disabled={disabled||(!done&&!onContinue)} title={done?'打开':'还没处理：分批处理接口接入后从这里继续'} onClick={()=>done?onOpen(c.id):onContinue?.(c.id)}>{c.book?.index?`${c.book.index}. `:''}{c.name}{!done&&<small> · 未处理{onContinue?' · 继续':''}</small>}</button>
      <button type="button" className="book-chapter-settings" aria-label={c.name+' 的设置'} title="本章设置" disabled={disabled} onClick={()=>onSettings('project',c.id)}>⚙</button></li>})}</ol>}
   </div>})}
 </div>;
}
