"""A long text kept as a book: chapters found by their headings, or cut at
paragraph breaks when there are none.

The role draft takes at most a memory-sized number of characters and units at a time (capacity.py) —
the model's context, not a limit worth raising. Both caps bind: measured on
the texts on this machine, dialogue-heavy prose runs 100–220 units per 3,000
characters (阿Q正传 105, 王朔 185, 红楼梦 219), so a chapter cut by length alone
would be handed out and then refused. A novel arrives as one file.
The chapter headings a Chinese novel already carries are the natural unit, and
the rule for finding them is the one from the user's own TextToApp converter.
Each chapter then goes through the ordinary one-click flow as its own project;
names confirmed in one chapter are offered in the next.
"""
import json
import re
import uuid
from pathlib import Path

from evals.speaker_attribution.source_units import source_units, PAIRS

# From hera2019/TextToApp main.py:156 — 第三章, 第12回, 第一百零八回, 第二卷 …
# and the English equivalents: Chapter 1, CHAPTER XII, Chapter One, Book II.
HEADING = re.compile(r'^\s*(?:第[零一二三四五六七八九十百千万0-9０-９]+[章回节卷集部]|'
                     r'(?:CHAPTER|Chapter|BOOK|Book|PART|Part)\s+(?:[IVXLC]+|\d+|[A-Z][a-z]+)\b).*$')

from .capacity import draft_limits
_LIMITS = draft_limits()
CHAPTER_LIMIT = _LIMITS['chars']            # the draft's own limit, by this machine's memory (capacity.py); a chapter over it is cut like headingless text
PARAGRAPH_TARGET = CHAPTER_LIMIT - 400      # leave headroom under the limit when cutting at paragraphs
UNIT_LIMIT = _LIMITS['units']               # the draft's other limit: quoted units (attribution.annotate)
UNIT_TARGET = 70              # the same headroom, in units
MIN_TAIL = 300                # a final piece shorter than this joins the piece before it
PARAGRAPH_END = re.compile(r'(\n\s*\n|(?<=[。！？!?”』」…])\n)')


def _units(text):
    """Units the model has to label: blank ones (line breaks) are filled in by the program."""
    return sum(1 for u in source_units(text) if u['text'].strip())


def _fits(text):
    return len(text) <= CHAPTER_LIMIT and _units(text) <= UNIT_LIMIT


def split_chapters(text, headings=None):
    """Cut a text into chapters. Returns [{'title', 'text'}] covering the text
    exactly (concatenating the pieces gives the input back). `headings` may
    name the heading lines outright (0-based line numbers — a Markdown import
    knows its headings); otherwise they are found by their look.

    With headings, each heading line opens a chapter and stays in its text.
    Without any, the text is cut at blank-line paragraph breaks so no piece
    exceeds the draft limit; never inside a paragraph, never inside a sentence.
    """
    lines = text.split('\n')
    if headings is not None:
        heads = sorted({i for i in headings if 0 <= i < len(lines) and lines[i].strip()})
    else:
        heads = [i for i, line in enumerate(lines) if HEADING.match(line)]
    if heads:
        bounds = ([0] if heads[0] > 0 else []) + heads + [len(lines)]
        chapters = []
        for a, b in zip(bounds, bounds[1:]):
            body = '\n'.join(lines[a:b]) + ('\n' if b < len(lines) else '')
            if not body.strip():
                continue
            title = lines[a].strip() if a in heads else '（开头）'
            chapters += _fit(title, body)
        return _reassemble_exact(text, chapters)
    return _reassemble_exact(text, _fit('', text))


def _fit(title, body):
    """One chapter, or several pieces of it when it is more than the draft can take."""
    if _fits(body):
        return [{'title': title, 'text': body}]
    # A paragraph ends at a blank line, or at a line break that follows a
    # sentence end — Chinese web novels separate paragraphs with a single
    # newline, and a hard-wrapped line ending mid-sentence is not a boundary.
    # The separator stays with the paragraph before it so the pieces
    # concatenate back to the original.
    merged = []
    for i, chunk in enumerate(re.split(PARAGRAPH_END, body)):
        if merged and i % 2:
            merged[-1] += chunk
        else:
            merged.append(chunk)
    pieces, current, count = [], '', 0
    for para in merged:
        units = _units(para)          # summed per paragraph; the exact check comes below
        if current and (len(current) + len(para) > PARAGRAPH_TARGET or count + units > UNIT_TARGET):
            pieces.append(current); current, count = para, units
        else:
            current += para; count += units
    if current:
        if pieces and len(current) < MIN_TAIL and _fits(pieces[-1] + current):
            pieces[-1] += current
        else:
            pieces.append(current)
    out = []
    for n, piece in enumerate(pieces, 1):
        if not _fits(piece):
            out += _cut_sentences(title, piece, n)
        else:
            out.append({'title': f'{title} · {n}' if title and len(pieces) > 1 else (title or f'第 {n} 段'), 'text': piece})
    return out


def _cut_sentences(title, piece, n):
    """A single paragraph that is more than the draft can take: cut after
    sentence ends only, never inside a quotation, and within both caps."""
    out, start = [], 0
    while start < len(piece):
        end = min(start + PARAGRAPH_TARGET, len(piece))
        if end < len(piece) or _units(piece[start:end]) > UNIT_TARGET:
            stops = [x for x in _stops(piece, start, end) if _units(piece[start:x]) <= UNIT_TARGET]
            end = stops[-1] if stops else (_stops(piece, start, len(piece)) or [end])[0]
        out.append({'title': f'{title or "第 %d 段" % n} · {len(out) + 1}', 'text': piece[start:end]})
        start = end
    return out


def _stops(piece, start, end):
    """Positions in (start, end] where a cut lands after a sentence end and
    outside any quotation; a sentence end just before a closing quote yields
    the position after the quote, so 。” stays together."""
    stops, close = [], None
    for i in range(start, end):
        char = piece[i]
        if close is None and char in PAIRS:
            close = PAIRS[char]
        elif close is not None and char == close:
            close = None
            if i > start and piece[i - 1] in '。！？!?':
                stops.append(i + 1)
        elif close is None and char in '。！？!?\n':
            stops.append(i + 1)
    return [x for x in stops if start < x <= end]


def _reassemble_exact(text, chapters):
    joined = ''.join(c['text'] for c in chapters)
    if joined != text:
        raise ValueError('分章后无法逐字还原原文，已放弃分章。')
    return chapters


class Books:
    """Books are kept beside projects, as plain JSON, never inside a project."""
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def create(self, title, text, language, headings=None, hints=None, silent=None):
        """`hints` are spans of `text` whose speaker a coloured manuscript settles,
        `silent` line numbers not read aloud; both are kept per chapter, rebased."""
        chapters = split_chapters(text, headings)
        records, offset, line = [], 0, 0
        for i, c in enumerate(chapters):
            end = offset + len(c['text']); lines = c['text'].count('\n') + (0 if c['text'].endswith('\n') else 1)
            record = {'index': i + 1, 'title': c['title'], 'chars': len(c['text']), 'text': c['text']}
            if hints:
                record['hints'] = [{'start': h['start'] - offset, 'end': h['end'] - offset, 'speaker': h['speaker']}
                                   for h in hints if h['start'] >= offset and h['end'] <= end]
            if silent:
                record['silent'] = [n - line for n in silent if line <= n < line + lines]
            records.append(record); offset = end; line += lines
        book = {'id': uuid.uuid4().hex, 'title': title.strip()[:120] or '未命名', 'language': language, 'chapters': records}
        (self.root / (book['id'] + '.json')).write_text(json.dumps(book, ensure_ascii=False), encoding='utf-8')
        return book

    def get(self, book_id):
        path = self.root / (book_id + '.json')
        if not re.fullmatch(r'[0-9a-f]{32}', book_id) or not path.is_file():
            raise ValueError('找不到这本书。')
        return json.loads(path.read_text(encoding='utf-8'))

    def delete(self, book_id):
        """Forget a book. Projects made from its chapters are their own files and stay."""
        path = self.root / (book_id + '.json')
        if not re.fullmatch(r'[0-9a-f]{32}', book_id) or not path.is_file():
            raise ValueError('找不到这本书。')
        path.unlink()

    def remember_aliases(self, book_id, aliases, speakers=()):
        """老板娘 → 陈小雪, learned when a reviewer renamed one and carried the rest along.
        Kept with the book; applied to every later draft of it. `speakers` are the
        names the reviewer confirmed this time: a pair both of whose names are
        in use is two people, and the pair is dropped at once (本人 2026-09-16),
        from the table and from what is being remembered. Returns the table and
        the pairs split."""
        book = self.get(book_id)
        table = book.setdefault('aliases', {})
        used = {sp.strip() for sp in speakers}
        split = {a: n for a, n in table.items() if a in used and n in used}
        for alias, name in aliases.items():
            alias, name = alias.strip(), name.strip()
            if not (alias and name and alias != name and len(alias) <= 40 and len(name) <= 40):
                continue
            if alias in used and name in used:
                split[alias] = name
                continue
            table[alias] = name
        for alias in split:
            table.pop(alias, None)
        (self.root / (book_id + '.json')).write_text(json.dumps(book, ensure_ascii=False), encoding='utf-8')
        return table, split

    def list(self):
        out = []
        for path in sorted(self.root.glob('*.json')):
            b = json.loads(path.read_text(encoding='utf-8'))
            out.append({'id': b['id'], 'title': b['title'], 'language': b['language'], 'chapters': len(b['chapters'])})
        return out

    @staticmethod
    def public(book):
        return {**book, 'chapters': [{k: v for k, v in c.items() if k != 'text'} for c in book['chapters']]}


# 最后更新：2026-09-13 · Claude Hera（长文本按章节切分；规则来自本人的 TextToApp）
