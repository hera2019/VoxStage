"""Pin the reading of a polyphonic character: 干[gan4] or 干[gàn].

The engine takes characters, not pinyin, and a character like 干 is read by
context — gān in 干净, gàn in 干活 — with no way to insist. The notation is
resolved, in the spoken text only, to a character that has only the asked-for
reading, so the voice has nothing to choose. 干[gan4] becomes 赣, 干[gan1]
becomes 肝. The written text and the subtitles keep 干; the transcribe-back
check tolerates the difference because it compares pinyin with tone.

The stand-in is a common character (GB2312 level one, the 3,755 most used)
with exactly one reading; failing that, a common character whose first reading
matches; never a rare character, which the voice may not know either, and never
the annotated character itself while another exists. When nothing better
exists the character stays as written and the voice reads it by context, and
`explain` says so. The choice is deterministic for a pinned pypinyin, and it
feeds the fingerprint like any other spoken text.
"""
import re

from pypinyin import pinyin_dict
from pypinyin.contrib.tone_convert import to_tone

# A Chinese character followed by a bracketed syllable: letters (tone marks
# allowed) and an optional digit. Brackets holding anything else — [笑], [原样] —
# or standing after punctuation or on their own are not notation and are left
# alone.
NOTATION = re.compile(r'([\u3400-\u9fff])\[([a-zA-ZüÜ\u00e0-\u01dc]{1,7}[0-9]?)\]')

_table = None


def _common(char):
    try:
        raw = char.encode('gb2312')
    except UnicodeEncodeError:
        return False
    return len(raw) == 2 and 0xB0 <= raw[0] <= 0xD7


def _reverse():
    """reading -> (common single-reading, common first-reading, every character with that reading)."""
    global _table
    if _table is None:
        table = {}
        for code, readings in pinyin_dict.pinyin_dict.items():
            parts = [r.strip() for r in readings.split(',') if r.strip()]
            if not parts or not (0x4E00 <= code <= 0x9FFF):
                continue
            char, common = chr(code), _common(chr(code))
            for n, reading in enumerate(parts):
                tiers = table.setdefault(reading, ([], [], []))
                tiers[2].append(char)
                if common and n == 0:
                    (tiers[0] if len(parts) == 1 else tiers[1]).append(char)
        _table = table
    return _table


def _marked(pinyin):
    try:
        return to_tone(pinyin.replace('v', 'ü').replace('V', 'Ü').lower())
    except Exception:
        return None


def stand_in(char, pinyin):
    """The character that reads as asked, or None when no character does."""
    tiers = _reverse().get(_marked(pinyin) or '')
    if not tiers:
        return None
    for tier in tiers[:2]:
        others = sorted(c for c in tier if c != char)
        if others:
            return others[0]
    return char if char in tiers[2] else None


def resolve(text):
    """Replace every 字[拼音] with its stand-in. Raises ValueError naming the
    notation when a reading cannot be resolved."""
    def swap(match):
        char, pinyin = match.group(1), match.group(2)
        if re.search(r'[06-9]$', pinyin):
            raise ValueError(f'「{char}[{pinyin}]」的声调要写 1–5（轻声 5）。')
        if not re.search(r'[1-5]$', pinyin) and not re.search(r'[à-ǜ]', pinyin):
            raise ValueError(f'「{char}[{pinyin}]」缺声调；写成 {char}[{pinyin}4] 这样，轻声用 5。')
        found = stand_in(char, pinyin)
        if found is None:
            rare = [c for c in (_reverse().get(_marked(pinyin) or '') or ([], [], []))[2] if c != char]
            if rare:
                # A reading only rare or polyphonic characters have — cào is 肏 —
                # is not pinned by the program; the person can type such a
                # character into the reading themselves and listen.
                raise ValueError(f'「{char}[{pinyin}]」：没有常用字只读 {pinyin}；有这个音的字有 {"、".join(rare[:5])}'
                                 f'（生僻或多音），可以直接写进朗读文本试听。')
            raise ValueError(f'「{char}[{pinyin}]」：没有读 {pinyin} 的字，请检查拼音。')
        return found
    return NOTATION.sub(swap, text)


def explain(text):
    """[(字[拼音], 替身)] for every notation in the text — what the voice will read."""
    return [(m.group(0), stand_in(m.group(1), m.group(2))) for m in NOTATION.finditer(text)]


# 最后更新：2026-09-14 · Claude Hera（多音字读音标注；本人提出「加个符号写拼音」）
