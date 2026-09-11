"""Bounded Chinese integer spelling equivalence, not pronunciation verification."""
import re

BASIS = '数字写法'
NOTICE = '按数值兼容可能掩盖漏读“零”等读音差异，请试听确认。'
DIGITS = {c:i for i,c in enumerate('零一二三四五六七八九')}
DIGITS.update({'〇':0,'两':2})
UNITS = {'十':10,'百':100,'千':1000}
# Include unsupported magnitudes/decimal markers so they are rejected as a whole.
CANDIDATES = re.compile(r'[零〇一二两三四五六七八九十百千万亿兆点0-9]+')


def integer_value(text):
    if not text:return None
    if re.fullmatch(r'0|[1-9][0-9]{0,3}',text):return int(text)
    if any(c not in DIGITS and c not in UNITS for c in text):return None
    if len(text)==1 and text in DIGITS:return DIGITS[text]
    total, previous, pending, zero_gap = 0, 10000, None, False
    seen_unit = False
    for char in text:
        if char in DIGITS:
            digit = DIGITS[char]
            if digit==0:
                if not seen_unit or pending is not None or zero_gap:return None
                zero_gap=True
            else:
                if pending is not None:return None
                pending=digit
        else:
            unit=UNITS[char]
            if unit>=previous:return None
            if pending is None:
                if not seen_unit and unit==10 and not zero_gap:pending=1
                else:return None
            total+=pending*unit
            pending=None;previous=unit;seen_unit=True;zero_gap=False
    if pending is not None:
        total+=pending*(previous//10 if seen_unit and previous>=100 and not zero_gap else 1)
    elif zero_gap:return None
    return total if seen_unit and total<=9999 else None


def numeric_spans(text):
    for match in CANDIDATES.finditer(text):
        before=text[:match.start()].rstrip()
        after=text[match.end():].lstrip()
        # Ordinals, decimal/fraction/sign notation are outside this bounded rule.
        if before[-1:] and before[-1] in '第+−-':continue
        if after.startswith('%'):continue
        if before[-1:] and before[-1] in '.,:/' and before[:-1].rstrip()[-1:] and CANDIDATES.fullmatch(before[:-1].rstrip()[-1]):continue
        if after[:1] and after[0] in '.,:/' and CANDIDATES.match(after[1:].lstrip()):continue
        value=integer_value(match.group())
        if value is not None:yield match.start(),match.end(),value

# 最后更新：2026-09-11 · Astra
