// The interface language (本人 2026-09-24: 英文界面一定要做). The Chinese text is
// the key: the code reads as it did, and anything not yet in the English table
// shows in Chinese rather than breaking. Chosen per browser; switching reloads.
import en from './locales/en.json';

export type Lang = 'zh' | 'en';
const KEY = 'voxstage-ui-lang';

function initial(): Lang {
  try { const saved = localStorage.getItem(KEY); if (saved === 'zh' || saved === 'en') return saved } catch { /* private window */ }
  return (navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en';
}

export const lang: Lang = initial();
const table = en as Record<string, string>;

/** The text in the interface language; {0}, {1} take the arguments in order. */
export function tr(text: string, ...args: unknown[]): string {
  const s = lang === 'en' ? (table[text] ?? text) : text;
  return args.length ? s.replace(/\{(\d+)\}/g, (m, i) => (+i < args.length ? String(args[+i]) : m)) : s;
}

export function setLang(next: Lang) {
  try { localStorage.setItem(KEY, next) } catch { /* the choice lasts this page only */ }
  location.reload();
}
