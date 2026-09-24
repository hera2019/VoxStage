
import {tr} from './i18n';/** Text files that are not UTF-8 (本人 2026-09-22: a GB-coded TXT came in as
 *  mojibake; 香港台湾繁体、日文的老格式 likewise). The bytes are tried as
 *  UTF-8 first — strictly, so a GB file cannot pass — then as the old East
 *  Asian encodings, and the reading with the most everyday characters and the
 *  fewest impossible ones wins. The choice is shown and can be overridden. *//** Text files that are not UTF-8 (本人 2026-09-22: a GB-coded TXT came in as
 *  mojibake; 香港台湾繁体、日文的老格式 likewise). The bytes are tried as
 *  UTF-8 first — strictly, so a GB file cannot pass — then as the old East
 *  Asian encodings, and the reading with the most everyday characters and the
 *  fewest impossible ones wins. The choice is shown and can be overridden. */
export const ENCODINGS: [string, string][] = [
  ['utf-8', 'UTF-8'], ['gb18030', tr("GB18030（简体 GB2312 / GBK）")], ['big5', tr("Big5（港台繁体）")],
  ['shift_jis', tr("Shift_JIS（日文）")], ['euc-jp', tr("EUC-JP（日文）")], ['euc-kr', tr("EUC-KR（韩文）")], ['utf-16le', 'UTF-16 LE'], ['utf-16be', 'UTF-16 BE']];

// Everyday characters: the wrong decoder of a GB / Big5 / Shift_JIS file still
// yields CJK characters, but rarely these.
const COMMON = new Set('的一是不了在人有我他这个们中来上大为和国地到以说时要就出会可也你对生能而子那得于着下自之年过发后作里用道行所然家种事成方多经么去法学如都同现当没动面起看定天分还进好小部其些主样理心她本前开但因只从想实日军者意无力它与长把机十民第公此已工使情明性知全三又关点正业外将两高间由问很最重并物手应战向头文体政美相见被利什二等产或新己制身果加西斯月话合回特代内信表化老给世位次度门任常先海通教儿原东声提立及比员解水名真论处走义各入几口认条平系气题活尔更别打女变四神总何电数安少报才结反受目太量再感建务做接必场件计管期市直德资命山金指克许统区保至队形社便空决治展马科司五基眼书非则听白却界达光放强即像难且权思王象完设式色路记南品住告类求据程北边死张该交规万取拉格望觉术领共确传师观清今切院让识候带导争运笑飞风步改收根干造言联持组每济车亲极林服快办议往元英士证近失转夫令准布始怎呢存未远叫台单影具罗字爱击流备兵连调深商算质团集百需价花党华城石级整府离况亚请技际约示复病息究线似官火断精满支视消越器容照须九增研写称企八功吗包片史委乎查轻易早曾除农找装广显吧阿李标谈吃图念六引历首医局突专费号尽另周较注语仅考落青随选奇曲怕' +
  '們來這個時說會對於後過發還進沒動開從現當經麼點著頭無關間長機為與問學國體應該將處實種樣讓聽見話兩門電數車馬東業產務員總結聲場報決極書則觀親變離氣區愛華條紀線論運議專費醫較據顯記讀寫買賣錢請謝邊裡麗風飛鳥島陽陰雲龍鳳歲時間開關們說話' +
  'あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽっゃゅょアイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンー' +
  '，。、！？：；“”‘’（）《》…—');

function score(text: string): number {
  let good = 0, bad = 0;
  for (const ch of text) {
    const c = ch.codePointAt(0)!;
    if (c === 0xfffd) bad += 10;
    else if (c < 0x20 && ch !== '\n' && ch !== '\r' && ch !== '\t') bad += 5;
    else if (c >= 0xe000 && c <= 0xf8ff) bad += 3;            // private use: nothing anyone writes
    else if (COMMON.has(ch)) good += 3;
    else if ((c >= 0x4e00 && c <= 0x9fff) || (c >= 0x3040 && c <= 0x30ff) || (c >= 0xac00 && c <= 0xd7af)) good += 1;
    else if ((c >= 0x3000 && c <= 0x303f) || (c >= 0xff00 && c <= 0xffef)) good += 1;
  }
  return good - bad;
}

export function decodeBytes(buffer: ArrayBuffer, encoding: string): string {
  const bytes = new Uint8Array(buffer);
  return new TextDecoder(encoding).decode(bytes);                // BOMs of that encoding are stripped by the decoder
}

/** The text and the encoding it was read in; `sure` when a BOM or strict UTF-8 settled it. */

/** The text and the encoding it was read in; `sure` when a BOM or strict UTF-8 settled it. */
export function decodeText(buffer: ArrayBuffer): { text: string; encoding: string; sure: boolean } {
  const b = new Uint8Array(buffer);
  if (b.length >= 2 && b[0] === 0xff && b[1] === 0xfe) return { text: decodeBytes(buffer, 'utf-16le'), encoding: 'utf-16le', sure: true };
  if (b.length >= 2 && b[0] === 0xfe && b[1] === 0xff) return { text: decodeBytes(buffer, 'utf-16be'), encoding: 'utf-16be', sure: true };
  try {
    return { text: new TextDecoder('utf-8', { fatal: true }).decode(b), encoding: 'utf-8', sure: true };
  } catch { /* not UTF-8: an old East Asian encoding */ }
  let best = { text: '', encoding: 'gb18030', score: -Infinity };
  for (const enc of ['gb18030', 'big5', 'shift_jis', 'euc-jp', 'euc-kr']) {
    let text: string;
    try { text = decodeBytes(buffer, enc); } catch { continue; }
    const s = score(text);
    if (s > best.score) best = { text, encoding: enc, score: s };
  }
  return { text: best.text, encoding: best.encoding, sure: false };
}
