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


def quote_findings(text):
    """Quotation marks that will mislead the cutter (本人 2026-09-21: “……不好。“
    — the closing mark written as an opening one swallowed the rest of the
    chapter). Three shapes:
      quote_wrong_direction — an opening mark that ends a sentence, or a
        closing mark that opens a line: fixable, the mark is turned round;
      quote_run_on — a quote still open across a blank line or after 200
        characters: warned with where it opened, since the reason is usually
        a mark missing or turned round somewhere inside;
      quote_nested — the same marks opened again inside a quote: the cutter
        keeps the outer one whole, which is right for a quote within a speech
        and wrong if the inner “ was meant to close the outer."""
    out = []
    for m in re.finditer(r'(?<=[。！？…～?!])“(?=[ \t]*(?:\n|$))', text):
        out.append({'kind': 'quote_wrong_direction', 'level': 'warning', 'index': m.start(), 'excerpt': _excerpt(text, m.start()),
                    'message': '句末的引号写成了开引号 “，后面的话会被当成同一句；应是 ”。', 'replace': ['“', '”']})
    for m in re.finditer(r'(?m)^[ \t]*(”)(?=[^\s”])', text):
        out.append({'kind': 'quote_wrong_direction', 'level': 'warning', 'index': m.start(1), 'excerpt': _excerpt(text, m.start(1)),
                    'message': '行首的引号写成了闭引号 ”，这句话不会被当成对白；应是 “。', 'replace': ['”', '“']})
    depth, opened_at, run_on, nested = 0, -1, set(), set()
    for i, ch in enumerate(text):
        if ch == '“':
            if depth >= 1 and i > 0 and text[i - 1] in '。！？…～?!' and text[i + 1:i + 2] not in ('', '\n', '“', '”'):
                # Inside a quote, an opening mark right after a full stop with the
                # story going on (不好。“阿宁轻轻……) is the closing mark turned round.
                out.append({'kind': 'quote_wrong_direction', 'level': 'warning', 'index': i, 'excerpt': _excerpt(text, i),
                            'message': '这句话说完了，引号却写成了开引号 “，后面的叙述被吞进了对白；应是 ”。', 'replace': ['“', '”']})
                depth -= 1
                continue
            if depth == 0:
                opened_at = i
            elif depth >= 1:
                nested.add(opened_at)
            depth += 1
        elif ch == '”' and depth > 0:
            depth -= 1
        elif depth > 0 and opened_at >= 0 and (i - opened_at > 200 or (ch == '\n' and text[i + 1:i + 2] == '\n')):
            run_on.add(opened_at); depth = 0
    for at in sorted(run_on):
        out.append({'kind': 'quote_run_on', 'level': 'warning', 'index': at, 'excerpt': _excerpt(text, at),
                    'message': '这个引号开了很久都没关上（跨过了空行或超过 200 字）：多半是后面某个 ” 写成了 “，或漏了。切分会把这一大段当成一句。', 'replace': None})
    for at in sorted(nested - run_on):
        out.append({'kind': 'quote_nested', 'level': 'info', 'index': at, 'excerpt': _excerpt(text, at),
                    'message': '引号里面又开了同样的引号。话里引话时这样是对的；如果里面那个 “ 其实是上一句的结尾，请改成 ”。', 'replace': None})
    return out


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


ILLUSTRATION = re.compile(r'\[\s*Illustration\b', re.I)


def _illustration_spans(text):
    """Find balanced [Illustration: … ] blocks, which nest and span lines.

    Gutenberg wraps the caption and the plate's copyright line inside the same
    block, so removing only the brackets leaves the caption behind as a stray
    quoted line — which then has to be attributed to somebody.
    """
    spans = []
    for m in ILLUSTRATION.finditer(text):
        depth = 0
        for i in range(m.start(), len(text)):
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
                if depth == 0:
                    spans.append((m.start(), i + 1))
                    break
    return spans


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

    findings += quote_findings(text)
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
    for a, b in _illustration_spans(text):
        findings.append({
            'kind': 'illustration_block', 'level': 'warning', 'index': a,
            'excerpt': _excerpt(text, a, 26),
            'message': f'整段插图说明（{b - a} 个字符，含图注与版权行）不属于正文，'
                       f'会被逐字念出。建议整块删除。',
            'replace': ['[Illustration: …]', '']})
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

    # An illustration block already covers its own brackets; do not advise twice.
    covered = _illustration_spans(text)
    findings = [f for f in findings if not (f['kind'] == 'editorial_block'
                and any(a <= f['index'] < b for a, b in covered))]
    findings.sort(key=lambda f: (f['level'] != 'error', f['index']))
    return {'findings': findings, 'units': len(units), 'characters': len(text),
            'blocking': any(f['level'] == 'error' for f in findings)}


def apply_fix(text, kind):
    """Apply every safe replacement of one kind. Explicit, idempotent, reversible."""
    if kind == 'quote_wrong_direction':
        text = re.sub(r'(?<=[。！？…～?!])“(?=[ \t]*(?:\n|$))', '”', text)
        text = re.sub(r'(?m)^([ \t]*)”(?=[^\s”])', r'\1“', text)
        # The mid-line shape is found by replaying the quotes; turn each one found.
        marks = sorted((f['index'] for f in quote_findings(text) if f['kind'] == 'quote_wrong_direction' and text[f['index']] == '“'), reverse=True)
        for at in marks:
            text = text[:at] + '”' + text[at + 1:]
        return text
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
    if kind == 'illustration_block':
        for a, b in reversed(_illustration_spans(text)):
            text = text[:a].rstrip(' \t') + text[b:].lstrip(' \t')
        return re.sub(r'\n{3,}', '\n\n', text)
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
