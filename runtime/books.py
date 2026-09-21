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

from .capacity import draft_limits, estimate_role_tokens
_LIMITS = draft_limits()
CHAPTER_LIMIT = _LIMITS['chars']            # hard ceiling for this machine (capacity.py)
UNIT_LIMIT = _LIMITS['units']               # hard ceiling for model-labelled source units
MIN_TAIL = 300                # a final piece shorter than this joins the piece before it
PARAGRAPH_END = re.compile(r'(\n\s*\n|(?<=[。！？!?”』」…])\n)')


def _units(text, cut=None):
    """Units the model has to label: blank ones (line breaks) are filled in by the program."""
    return sum(1 for u in source_units(text, cut) if u['text'].strip())


def _token_estimate(text, cut, token_budget):
    return estimate_role_tokens(len(text), _units(text, cut), token_budget['context'], token_budget['max_tokens'])


def _fits(text, cut=None, chapter_limit=CHAPTER_LIMIT, unit_limit=UNIT_LIMIT, token_budget=None):
    if token_budget is not None:
        return _token_estimate(text, cut, token_budget)['fits']
    return len(text) <= chapter_limit and _units(text, cut) <= unit_limit


def split_chapters(text, headings=None, cut=None, chapter_chars=None, token_budget=None):
    """Cut a text into chapters. Returns [{'title', 'text'}] covering the text
    exactly (concatenating the pieces gives the input back). `headings` may
    name the heading lines outright (0-based line numbers — a Markdown import
    knows its headings); otherwise they are found by their look.

    With headings, each heading line is a preferred boundary and stays in the
    text. With no explicit chapter size, headings retain the old one-heading-
    per-piece behaviour. When a size is explicitly selected in the UI, adjacent
    short heading sections are packed together up to that size/model-unit limit;
    an individual overlong section is still split at paragraphs/sentences.
    Without headings, the text is cut at paragraph/sentence boundaries.
    """
    explicit_size = chapter_chars is not None or token_budget is not None
    chapter_limit = CHAPTER_LIMIT if chapter_chars is None else int(chapter_chars)
    if chapter_chars is not None and not 1 <= chapter_limit <= 12000:
        raise ValueError('每章字数必须在 1 到 12000 之间。')
    unit_limit = UNIT_LIMIT
    lines = text.split('\n')
    if headings is not None:
        heads = sorted({i for i in headings if 0 <= i < len(lines) and lines[i].strip()})
    else:
        heads = [i for i, line in enumerate(lines) if HEADING.match(line)]
    if heads:
        bounds = ([0] if heads[0] > 0 else []) + heads + [len(lines)]
        sections = []
        for a, b in zip(bounds, bounds[1:]):
            body = '\n'.join(lines[a:b]) + ('\n' if b < len(lines) else '')
            if not body.strip():
                continue
            title = lines[a].strip() if a in heads else '（开头）'
            sections.append((title, body))
        if not explicit_size:
            chapters = []
            for title, body in sections:
                chapters += _fit(title, body, cut, chapter_limit, unit_limit, token_budget)
            return _reassemble_exact(text, chapters)

        chapters, current, titles = [], '', []
        def flush():
            nonlocal current, titles
            if current:
                chapters.append({'title': _packed_title(titles), 'text': current})
                current, titles = '', []
        for title, body in sections:
            if not _fits(body, cut, chapter_limit, unit_limit, token_budget):
                flush()
                chapters += _fit(title, body, cut, chapter_limit, unit_limit, token_budget)
                continue
            if current and not _fits(current + body, cut, chapter_limit, unit_limit, token_budget):
                flush()
            current += body
            titles.append(title)
        flush()
        return _reassemble_exact(text, chapters)
    return _reassemble_exact(text, _fit('', text, cut, chapter_limit, unit_limit, token_budget))


def author_chapters(text, headings=None):
    """Return the author's chapters without capacity-driven processing cuts.

    A headingless manuscript is one chapter. Long chapters remain whole here;
    model-sized windows are a later processing concern and never become extra
    Projects merely because one model has a smaller context window.
    """
    lines = text.split('\n')
    if headings is not None:
        heads = sorted({i for i in headings if 0 <= i < len(lines) and lines[i].strip()})
    else:
        heads = [i for i, line in enumerate(lines) if HEADING.match(line)]
    if not heads:
        return [{'title': '', 'text': text}]
    bounds = ([0] if heads[0] > 0 else []) + heads + [len(lines)]
    chapters = []
    for start, end in zip(bounds, bounds[1:]):
        body = '\n'.join(lines[start:end]) + ('\n' if end < len(lines) else '')
        if not body.strip():
            continue
        chapters.append({'title': lines[start].strip() if start in heads else '（开头）',
                         'text': body})
    return _reassemble_exact(text, chapters)


def _packed_title(titles):
    """Readable label for one processing piece containing one or more source chapters."""
    names = [t for t in titles if t]
    if not names:
        return ''
    if len(names) == 1:
        return names[0]
    return f'{names[0]} ～ {names[-1]}'


def _fit(title, body, cut=None, chapter_limit=CHAPTER_LIMIT, unit_limit=UNIT_LIMIT, token_budget=None):
    """One source chapter, or several pieces when the selected budget cannot take it."""
    if _fits(body, cut, chapter_limit, unit_limit, token_budget):
        return [{'title': title, 'text': body}]
    # A paragraph ends at a blank line, or at a line break that follows a
    # sentence end. Test the whole candidate against the same budget used by
    # the model instead of summing a separate character/unit heuristic.
    merged = []
    for i, chunk in enumerate(re.split(PARAGRAPH_END, body)):
        if merged and i % 2:
            merged[-1] += chunk
        else:
            merged.append(chunk)
    pieces, current = [], ''
    for para in merged:
        candidate = current + para
        if current and not _fits(candidate, cut, chapter_limit, unit_limit, token_budget):
            pieces.append(current)
            current = para
        else:
            current = candidate
    if current:
        if pieces and len(current) < MIN_TAIL and _fits(pieces[-1] + current, cut, chapter_limit, unit_limit, token_budget):
            pieces[-1] += current
        else:
            pieces.append(current)
    out = []
    for n, piece in enumerate(pieces, 1):
        if not _fits(piece, cut, chapter_limit, unit_limit, token_budget):
            out += _cut_sentences(title, piece, n, cut, chapter_limit, unit_limit, token_budget)
        else:
            out.append({'title': f'{title} · {n}' if title and len(pieces) > 1 else (title or f'第 {n} 段'), 'text': piece})
    return out


def _cut_sentences(title, piece, n, cut=None, chapter_limit=CHAPTER_LIMIT, unit_limit=UNIT_LIMIT, token_budget=None):
    """Cut an over-budget paragraph at the furthest sentence end that still fits."""
    out, start = [], 0
    while start < len(piece):
        if _fits(piece[start:], cut, chapter_limit, unit_limit, token_budget):
            end = len(piece)
        else:
            stops = _stops(piece, start, len(piece))
            fitting = [x for x in stops if _fits(piece[start:x], cut, chapter_limit, unit_limit, token_budget)]
            if fitting:
                end = fitting[-1]
            else:
                # A single sentence itself is over budget. Find the largest safe
                # prefix rather than refusing the whole book; this is only the
                # emergency path for pathological paragraphs.
                lo, hi = start + 1, len(piece)
                end = start + 1
                while lo <= hi:
                    mid = (lo + hi) // 2
                    if _fits(piece[start:mid], cut, chapter_limit, unit_limit, token_budget):
                        end = mid; lo = mid + 1
                    else:
                        hi = mid - 1
                if end <= start:
                    raise ValueError('单个片段超过模型预算，无法安全分段。')
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

    def create(self, title, text, language, headings=None, hints=None, silent=None, cut=None, chapter_chars=None, token_budget=None):
        """`hints` are spans of `text` whose speaker a coloured manuscript settles,
        `silent` line numbers not read aloud; both are kept per chapter, rebased."""
        chapters = split_chapters(text, headings, cut, chapter_chars, token_budget)
        records, offset, line = [], 0, 0
        for i, c in enumerate(chapters):
            end = offset + len(c['text']); lines = c['text'].count('\n') + (0 if c['text'].endswith('\n') else 1)
            record = {'index': i + 1, 'title': c['title'], 'chars': len(c['text']), 'units': _units(c['text'], cut), 'text': c['text']}
            if token_budget is not None:
                estimate = _token_estimate(c['text'], cut, token_budget)
                record['estimated_prompt_tokens'] = estimate['prompt']
                record['estimated_completion_tokens'] = estimate['completion']
                record['estimated_total_tokens'] = estimate['total']
                record['token_budget'] = estimate['safe_total']
            if hints:
                record['hints'] = [{**h, 'start': h['start'] - offset, 'end': h['end'] - offset}
                                   for h in hints if h['start'] >= offset and h['end'] <= end]
            if silent:
                record['silent'] = [n - line for n in silent if line <= n < line + lines]
            records.append(record); offset = end; line += lines
        book = {'id': uuid.uuid4().hex, 'title': title.strip()[:120] or '未命名', 'language': language,
                'chapter_chars': (None if token_budget is not None else (CHAPTER_LIMIT if chapter_chars is None else int(chapter_chars))),
                'split_mode': ('tokens' if token_budget is not None else 'chars'), 'chapters': records}
        if token_budget is not None:
            book['token_context'] = token_budget['context']
            book['token_max_tokens'] = token_budget['max_tokens']
        if cut:
            book['cut'] = cut              # 'lines': the manuscript's colours, not its quotation marks, cut the lines
        narration = next((h.get('colour') for h in (hints or []) if h.get('speaker') == 'NARRATOR' and h.get('colour')), None)
        if narration:
            book['narration_colour'] = narration          # the author's colour for narration, for every chapter's narrator
        (self.root / (book['id'] + '.json')).write_text(json.dumps(book, ensure_ascii=False), encoding='utf-8')
        return book

    def get(self, book_id):
        path = self.root / (book_id + '.json')
        if not re.fullmatch(r'[0-9a-f]{32}', book_id) or not path.is_file():
            raise ValueError('找不到这本书。')
        return json.loads(path.read_text(encoding='utf-8'))

    def delete(self, book_id):
        """Forget a book. Projects made from its chapters are their own files and stay."""
        guard = getattr(self, 'write_guard', None)
        if guard is not None:
            guard(book_id)
        path = self.root / (book_id + '.json')
        if not re.fullmatch(r'[0-9a-f]{32}', book_id) or not path.is_file():
            raise ValueError('找不到这本书。')
        path.unlink()

    def save(self, book):
        guard = getattr(self, 'write_guard', None)
        if guard is not None:
            guard(book['id'])
        (self.root / (book['id'] + '.json')).write_text(json.dumps(book, ensure_ascii=False), encoding='utf-8')

    def cast_of(self, book, names=()):
        """The book's cast, made on first use from what it already knew — its
        alias table and the names of its chapters' projects (source person: a
        reviewer confirmed them) — and kept in step with the alias table the
        draft rules read. `names` are extra names to make sure of."""
        from . import cast as C
        changed = False
        if 'cast' not in book:
            book['cast'] = []
            for name in names:
                C.ensure(book['cast'], name, 'person')
            for alias, name in (book.get('aliases') or {}).items():
                entry, _ = C.ensure(book['cast'], name, 'person')
                C.add_alias(book['cast'], entry['id'], alias, 'person')
            changed = True
        for name in names:
            _, created = C.ensure(book['cast'], name, 'person')
            changed = changed or created
        table = C.alias_table(book['cast'])
        if table != (book.get('aliases') or {}):
            book['aliases'] = table; changed = True
        if changed:
            self.save(book)
        return book['cast']

    def remember_aliases(self, book_id, aliases, speakers=()):
        """老板娘 → 陈小雪, learned when a reviewer renamed one and carried the rest along.
        Kept with the book; applied to every later draft of it. `speakers` are the
        names the reviewer confirmed this time: a pair both of whose names are
        in use is two people, and the pair is dropped at once (本人 2026-09-16),
        from the table and from what is being remembered. Returns the table and
        the pairs split."""
        from . import cast as C
        book = self.get(book_id)
        cast = self.cast_of(book)
        table = dict(book.get('aliases') or {})
        used = {sp.strip() for sp in speakers}
        split = {a: n for a, n in table.items() if a in used and n in used}
        for alias, name in aliases.items():
            alias, name = alias.strip(), name.strip()
            if not (alias and name and alias != name and len(alias) <= 40 and len(name) <= 40):
                continue
            if alias in used and name in used:
                split[alias] = name
                continue
            entry, _ = C.ensure(cast, name, 'person')
            C.add_alias(cast, entry['id'], alias, 'person')
        for alias in split:
            C.split(cast, alias)
        book['aliases'] = C.alias_table(cast)
        self.save(book)
        return book['aliases'], split

    def list(self):
        out = []
        for path in sorted(self.root.glob('*.json')):
            b = json.loads(path.read_text(encoding='utf-8'))
            out.append({'id': b['id'], 'title': b['title'], 'language': b['language'], 'chapters': len(b['chapters']), 'archived': bool(b.get('archived'))})
        return out

    @staticmethod
    def public(book):
        return {**book, 'chapters': [{k: v for k, v in c.items() if k != 'text'} for c in book['chapters']]}


# 最后更新：2026-09-13 · Claude Hera（长文本按章节切分；规则来自本人的 TextToApp）
