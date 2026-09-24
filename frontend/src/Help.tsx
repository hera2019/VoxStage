import {useState,type ReactNode} from 'react';
import {tr} from './i18n';

/** Explanations that used to sit under every control, folded behind a small「?」
 *  (本人 2026-09-23: 不是很重要的文字，收起来，点击才出现). The text opens in
 *  place under the control and closes with the same button. */

/** Explanations that used to sit under every control, folded behind a small「?」
 *  (本人 2026-09-23: 不是很重要的文字，收起来，点击才出现). The text opens in
 *  place under the control and closes with the same button. */
export function Help({children,label=tr("说明")}:{children:ReactNode;label?:string}){
 const [open,setOpen]=useState(false);
 return <span className={'help'+(open?' open':'')}><button type="button" className="help-btn" aria-label={label} aria-expanded={open} title={open?tr("收起说明"):tr("看说明")} onClick={e=>{e.preventDefault();e.stopPropagation();setOpen(!open)}}>?</button>{open&&<span className="help-pop" role="note">{children}</span>}</span>;
}
