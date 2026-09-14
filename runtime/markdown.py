"""Markdown in, prose out. Many manuscripts are written in Markdown (本人
2026-09-15); read aloud as they are, the voice would say the pound signs and
asterisks. The import keeps the words and the structure that matters to a
recording — headings become chapter headings, paragraphs stay paragraphs,
scene breaks stay as blank lines — and drops the rest: emphasis marks, links
(the link text stays), images, code fences, HTML, front matter, footnote
marks, tables (their cells become lines).

Headings: any ATX (#) or setext (underlined) heading of level 1–2 is a
chapter heading, whatever it says; the returned `headings` are line numbers
in the converted text so the book cutter does not have to guess from 第X章.
"""
import re

FRONT_MATTER = re.compile(r'\A---\n.*?\n---\n', re.S)
FENCE = re.compile(r'^(```|~~~).*?^\1[^\n]*$', re.S | re.M)
HTML_BLOCK = re.compile(r'<!--.*?-->|<[^>\n]+>', re.S)
IMAGE = re.compile(r'!\[[^\]]*\]\([^)]*\)')
LINK = re.compile(r'\[([^\]]+)\]\([^)]*\)')
REF_LINK = re.compile(r'\[([^\]]+)\]\[[^\]]*\]')
FOOTNOTE = re.compile(r'\[\^[^\]]+\]')
EMPHASIS = re.compile(r'(\*\*\*|___|\*\*|__|\*|_|~~|`)(?=\S)(.+?)(?<=\S)\1')
SETEXT = re.compile(r'^(?P<text>[^\n]+)\n(?P<line>=+|-+)[ \t]*$', re.M)


def to_text(markdown):
    """Returns (text, headings) — plain prose and the 0-based line numbers of
    its chapter headings. The text is what a project stores as its source;
    the Markdown file itself is not kept."""
    s = markdown.replace('\r\n', '\n').replace('\r', '\n')
    s = FRONT_MATTER.sub('', s)
    s = FENCE.sub('', s)
    s = HTML_BLOCK.sub('', s)
    s = IMAGE.sub('', s)
    s = LINK.sub(r'\1', s)
    s = REF_LINK.sub(r'\1', s)
    s = FOOTNOTE.sub('', s)
    # Setext headings (text underlined with === or ---) become ATX ones first.
    s = SETEXT.sub(lambda m: ('# ' if m.group('line').startswith('=') else '## ') + m.group('text').strip(), s)
    out, headings = [], []
    for raw in s.split('\n'):
        line = raw.rstrip()
        m = re.match(r'^(#{1,6})\s+(.*?)\s*#*\s*$', line)
        if m:
            title = EMPHASIS.sub(r'\2', m.group(2)).strip()
            if not title:
                continue
            if len(m.group(1)) <= 2:
                headings.append(len(out))
            out.append(title)
            continue
        if re.match(r'^\s*([-*_]\s*){3,}$', line):      # a rule is a scene break
            out.append('')
            continue
        if re.match(r'^\s*\|.*\|\s*$', line):           # a table row: its cells, one line each
            cells = [EMPHASIS.sub(r'\2', c).strip() for c in line.strip().strip('|').split('|')]
            if all(re.fullmatch(r':?-{2,}:?', c) for c in cells if c):
                continue
            out.extend(c for c in cells if c)
            continue
        line = re.sub(r'^\s*>\s?', '', line)             # blockquote marker
        line = re.sub(r'^\s*(?:[-*+]|\d+[.)])\s+', '', line)   # list marker
        line = EMPHASIS.sub(r'\2', line)
        line = line.replace('\\*', '*').replace('\\_', '_').replace('\\#', '#')
        out.append(line.strip())
    # Collapse runs of blank lines to one, keep single line breaks.
    text_lines, blank = [], False
    for line in out:
        if line == '':
            if not blank and text_lines:
                text_lines.append('')
            blank = True
        else:
            text_lines.append(line); blank = False
    # Heading line numbers refer to the collapsed text.
    kept = []
    j = 0
    for i, line in enumerate(out):
        if line == '':
            if i and out[i - 1] != '' and text_lines[j:j + 1] == ['']:
                j += 1
            continue
        if i in headings:
            kept.append(j)
        j += 1
    text = '\n'.join(text_lines).strip('\n') + ('\n' if text_lines else '')
    return text, [h for h in kept if h < len(text_lines)]


# 最后更新：2026-09-15 · Claude Hera（Markdown 导入；本人 2026-09-15 提出）
