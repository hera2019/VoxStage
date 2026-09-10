"""Rule-based source inspection before slicing. Suggests, never rewrites.

Mirrors evals.speaker_attribution.source_units so a warning here means the real
slicer would behave the same way. Findings carry an optional safe replacement;
applying one is always an explicit user action.
"""
import re
from evals.speaker_attribution.source_units import PAIRS, source_units

MODEL_UNIT_LIMIT = 80          # RoleDraftEngine.annotate rejects more than this
DECORATION = '※★☆◇◆●○▲△■□§¶'


def _quote_scan(text):
    """Replay the slicer's state machine and report an unclosed opening quote."""
    close = None
    opened_at = -1
    opened = ''
    escaped = False
    styles = set()
    for i, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == '\\':
            escaped = True
            continue
        if close is None and char in PAIRS:
            close, opened_at, opened = PAIRS[char], i, char
            styles.add(char if char != '"' else '"')
        elif close is not None and char == close:
            close = None
    return (opened_at, opened) if close is not None else (-1, ''), styles


def _excerpt(text, index, span=14):
    start = max(0, index - span // 2)
    piece = text[start:index + span].replace('\n', '⏎')
    return ('…' if start else '') + piece + ('…' if index + span < len(text) else '')


def _finds(text, kind, pattern, level, message, replace=None):
    out = []
    for m in re.finditer(pattern, text):
        out.append({'kind': kind, 'level': level, 'index': m.start(),
                    'excerpt': _excerpt(text, m.start()), 'message': message,
                    'replace': replace})
    return out


def inspect(text, language='zh'):
    """Return findings plus the numbers that decide whether slicing will work."""
    findings = []
    (opened_at, opened), styles = _quote_scan(text)

    if opened_at >= 0:
        findings.append({
            'kind': 'unclosed_quote', 'level': 'error', 'index': opened_at,
            'excerpt': _excerpt(text, opened_at),
            'message': f'引号 {opened} 没有闭合。切分会把这里到文末当成同一段，'
                       f'后面所有角色都会判错。请补上 {PAIRS[opened]}。',
            'replace': None})

    if len(styles) > 1:
        findings.append({
            'kind': 'mixed_quotes', 'level': 'warning', 'index': 0,
            'excerpt': '、'.join(sorted(styles)),
            'message': '同一篇里混用了多种引号。切分能处理，但容易漏配对；'
                       '建议统一成一种。',
            'replace': None})

    findings += _finds(text, 'ellipsis_dots', r'(?<!\.)\.{3,6}(?!\.)', 'warning',
                       '连续句点可能被逐个念出。中文建议改为 ……', ['...', '……'])
    findings += _finds(text, 'dash_ascii', r'(?<!-)-{2,3}(?!-)', 'warning',
                       '两个减号不是破折号，可能被念出。建议改为 ——', ['--', '——'])
    findings += _finds(text, 'ideographic_space', '　', 'warning',
                       '全角空格在朗读中不发音，但会影响切分位置。建议删除。',
                       ['　', ''])
    findings += _finds(text, 'repeated_space', '  +', 'warning',
                       '连续空格。建议合并为一个。', None)
    findings += _finds(text, 'trailing_space', r'[ \t]+$', 'warning',
                       '行尾多余空白。建议删除。', None)
    # Public-domain sources are overwhelmingly Project Gutenberg, and its plain
    # text carries typographic apparatus that a reader would never speak.
    findings += _finds(text, 'markup_emphasis', r'_[^_\n]{1,60}_', 'warning',
                       '下划线是排版强调标记（常见于 Project Gutenberg），会被逐个念出。建议删除。',
                       ['_', ''])
    findings += _finds(text, 'editorial_block', r'\[[^\[\]\n]{0,200}\]', 'warning',
                       '方括号内容通常是插图、注释或版权说明，不属于正文，会被念出来。建议删除。',
                       None)
    findings += _finds(text, 'decoration', f'[{re.escape(DECORATION)}]', 'warning',
                       '装饰符号通常会被念出来。建议删除或换成文字。', None)

    units = source_units(text)
    if len(units) > MODEL_UNIT_LIMIT:
        findings.append({
            'kind': 'too_many_units', 'level': 'error', 'index': 0,
            'excerpt': f'{len(units)} 个切片',
            'message': f'切片数超过 {MODEL_UNIT_LIMIT}，本机分角色会拒绝。'
                       f'请分几次导入，或缩短原稿。',
            'replace': None})

    findings.sort(key=lambda f: (f['level'] != 'error', f['index']))
    return {'findings': findings, 'units': len(units), 'characters': len(text),
            'blocking': any(f['level'] == 'error' for f in findings)}


def apply_fix(text, kind):
    """Apply every safe replacement of one kind. Explicit, idempotent, reversible."""
    if kind == 'ellipsis_dots':
        return re.sub(r'(?<!\.)\.{3,6}(?!\.)', '……', text)
    if kind == 'dash_ascii':
        return re.sub(r'(?<!-)-{2,3}(?!-)', '——', text)
    if kind == 'ideographic_space':
        return text.replace('　', '')
    if kind == 'repeated_space':
        return re.sub('  +', ' ', text)
    if kind == 'trailing_space':
        return re.sub(r'[ \t]+$', '', text, flags=re.M)
    if kind == 'markup_emphasis':
        return re.sub(r'_([^_\n]{1,60})_', r'\1', text)
    if kind == 'editorial_block':
        # Blocks nest ([Illustration: … [_Copyright …_]]); peel from the inside.
        while True:
            stripped = re.sub(r'[ \t]*\[[^\[\]\n]{0,200}\][ \t]*', '', text)
            if stripped == text:
                return text
            text = stripped
    if kind == 'decoration':
        return re.sub(f'[{re.escape(DECORATION)}]', '', text)
    raise ValueError('这一项需要人工修改，没有可自动套用的替换。')

# 最后更新：2026-09-10 · Claude Hera
