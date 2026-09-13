"""A long text kept as a book: chapters found by their headings, or cut at
paragraph breaks when there are none.

The role draft takes at most 3,000 characters and 80 quoted units at a time —
the model's context, not a limit worth raising. A novel arrives as one file.
The chapter headings a Chinese novel already carries are the natural unit, and
the rule for finding them is the one from the user's own TextToApp converter.
Each chapter then goes through the ordinary one-click flow as its own project;
names confirmed in one chapter are offered in the next.
"""
import json
import re
import uuid
from pathlib import Path

# From hera2019/TextToApp main.py:156 — 第三章, 第12回, 第一百零八回, 第二卷 …
# and the English equivalents: Chapter 1, CHAPTER XII, Chapter One, Book II.
HEADING = re.compile(r'^\s*(?:第[零一二三四五六七八九十百千万0-9０-９]+[章回节卷集部]|'
                     r'(?:CHAPTER|Chapter|BOOK|Book|PART|Part)\s+(?:[IVXLC]+|\d+|[A-Z][a-z]+)\b).*$')

CHAPTER_LIMIT = 3000          # the draft's own limit; a chapter over it is cut like headingless text
PARAGRAPH_TARGET = 2600       # leave headroom under the limit when cutting at paragraphs
MIN_TAIL = 300                # a final piece shorter than this joins the piece before it


def split_chapters(text):
    """Cut a text into chapters. Returns [{'title', 'text'}] covering the text
    exactly (concatenating the pieces gives the input back).

    With headings, each heading line opens a chapter and stays in its text.
    Without any, the text is cut at blank-line paragraph breaks so no piece
    exceeds the draft limit; never inside a paragraph, never inside a sentence.
    """
    lines = text.split('\n')
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
    """One chapter, or several pieces of it when it is longer than the draft can take."""
    if len(body) <= CHAPTER_LIMIT:
        return [{'title': title, 'text': body}]
    # Paragraphs are runs separated by a blank line; the separator stays with
    # the paragraph before it so the pieces concatenate back to the original.
    merged = []
    for chunk in re.split(r'(\n\s*\n)', body):
        if merged and re.fullmatch(r'\n\s*\n', chunk):
            merged[-1] += chunk
        else:
            merged.append(chunk)
    pieces, current = [], ''
    for para in merged:
        if len(current) + len(para) > PARAGRAPH_TARGET and current:
            pieces.append(current); current = para
        else:
            current += para
    if current:
        if pieces and len(current) < MIN_TAIL and len(pieces[-1]) + len(current) <= CHAPTER_LIMIT:
            pieces[-1] += current
        else:
            pieces.append(current)
    out = []
    for n, piece in enumerate(pieces, 1):
        if len(piece) > CHAPTER_LIMIT:
            out += _cut_sentences(title, piece, n)
        else:
            out.append({'title': f'{title} · {n}' if title and len(pieces) > 1 else (title or f'第 {n} 段'), 'text': piece})
    return out


def _cut_sentences(title, piece, n):
    """A single paragraph longer than the limit: cut after sentence ends only."""
    out, start = [], 0
    while start < len(piece):
        end = min(start + PARAGRAPH_TARGET, len(piece))
        if end < len(piece):
            stops = [i + 1 for i in range(start, end) if piece[i] in '。！？!?\n']
            end = stops[-1] if stops else end
        out.append({'title': f'{title or "第 %d 段" % n} · {len(out) + 1}', 'text': piece[start:end]})
        start = end
    return out


def _reassemble_exact(text, chapters):
    joined = ''.join(c['text'] for c in chapters)
    if joined != text:
        raise ValueError('分章后无法逐字还原原文，已放弃分章。')
    return chapters


class Books:
    """Books are kept beside projects, as plain JSON, never inside a project."""
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def create(self, title, text, language):
        chapters = split_chapters(text)
        book = {'id': uuid.uuid4().hex, 'title': title.strip()[:120] or '未命名', 'language': language,
                'chapters': [{'index': i + 1, 'title': c['title'], 'chars': len(c['text']), 'text': c['text']}
                             for i, c in enumerate(chapters)]}
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
