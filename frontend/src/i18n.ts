// The interface language (本人 2026-09-24: 英文界面一定要做). The Chinese text is
// the key: the code reads as it did, and anything not yet in the English table
// shows in Chinese rather than breaking. Chosen per browser; switching reloads.
import en from './locales/en.json';
import server from './locales/en-server.json';

export type Lang = 'zh' | 'en';
const KEY = 'voxstage-ui-lang';

function initial(): Lang {
  try { const saved = localStorage.getItem(KEY); if (saved === 'zh' || saved === 'en') return saved } catch { /* private window */ }
  return (navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en';
}

export const lang: Lang = initial();
const table = en as Record<string, string>;

const said = server as Record<string, string>;
const CJK = /[\u3400-\u9fff]/;

// Messages the server sends are Chinese sentences, some with a name or a number
// filled in (「陈小雪」还有句子在用) or a name appended (按说话习惯，像是陈小雪).
// Each such message is a pattern: {0} takes anything; whatever follows the
// message is kept as it is — it is a name, not text to translate.
let patterns: [RegExp, string][] | null = null;
function fromServer(text: string): string | undefined {
  if (!CJK.test(text)) return undefined;
  if (!patterns) {
    const esc = (x: string) => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    patterns = Object.keys(said).filter(k => k.length >= 4)
      .sort((a, b) => b.length - a.length)
      .map(k => [new RegExp('^' + k.split(/\{\d+\}/).map(esc).join('([\\s\\S]+?)') + '([\\s\\S]*)$'), k]);
  }
  for (const [re, key] of patterns) {
    const m = text.match(re);
    if (!m) continue;
    const order = [...key.matchAll(/\{(\d+)\}/g)].map(x => +x[1]);
    const values: string[] = [];
    order.forEach((n, i) => { values[n] = m[i + 1] });
    const rest = m[order.length + 1] ?? '';
    return said[key].replace(/\{(\d+)\}/g, (_, n) => values[+n] ?? '') + (fromServer(rest) ?? rest);
  }
  return undefined;
}

/** The text in the interface language; {0}, {1} take the arguments in order.
 *  Also takes a message the server sent, as it came. */
export function tr(text: string, ...args: unknown[]): string {
  const s = lang === 'en' ? (table[text] ?? said[text] ?? fromServer(text) ?? text) : text;
  return args.length ? s.replace(/\{(\d+)\}/g, (m, i) => (+i < args.length ? String(args[+i]) : m)) : s;
}

/** A voice's name as shown: the default pack's voices have English names for the
 *  English interface (the roster, 本人 2026-09-23); everyone else's voices keep theirs. */
export function voiceTitle(v: { name: string; pack?: string | null }): string {
  return v.pack === 'default' ? tr(v.name) : v.name;
}

export function setLang(next: Lang) {
  try { localStorage.setItem(KEY, next) } catch { /* the choice lasts this page only */ }
  location.reload();
}

document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
document.title = tr('VoxStage · 让故事开口');
