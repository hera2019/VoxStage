"""A manuscript whose colours say who speaks (本人 2026-09-16: 颜色 = 人名).

Read straight from the .docx XML — no dependency, and the colour values
survive a Pages or Word export exactly, where an HTML or EPUB export shifts
them. What comes out is what the author put in: every paragraph with its
runs of text and their effective colour (the run's own, else its character
style's, else the paragraph style's), and the outline level of headings.

Nothing is decided here about who a colour is. The import shows the reviewer
each colour with samples and asks, colour by colour (本人: 导入时逐色问);
`compose` then turns the answers into a plain text plus hints — spans that
name their speaker — for the same draft and review page every manuscript
goes through. A paragraph with runs of two speakers' colours is not given
to the majority (Astra 2026-09-15): it is written out as one line per run,
so each keeps its own speaker; a colour the reviewer marks as emphasis is
folded into the text around it; one marked as not for the script is dropped.
Headings stay in the text, not read aloud by default, and open chapters.
"""
import re
import zipfile
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
NONE = 'none'                                       # the key for uncoloured (automatic / black) text
QUOTE_OPEN = '“"「『'


def read_docx(data):
    """bytes of a .docx -> {'paragraphs': [{'level', 'style', 'runs': [[text, colour]], 'text'}], 'title'}.
    `level` is 1–8 for a heading paragraph, None for body text; `colour` is
    '#rrggbb' or 'none'."""
    try:
        z = zipfile.ZipFile(__import__('io').BytesIO(data))
        document = z.read('word/document.xml')
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError('这不是一个 Word 文档（.docx）。') from exc
    styles = {}
    if 'word/styles.xml' in z.namelist():
        for st in ET.fromstring(z.read('word/styles.xml')).iter(W + 'style'):
            sid = st.get(W + 'styleId'); name = st.find(W + 'name'); lvl = st.find(f'{W}pPr/{W}outlineLvl')
            col = st.find(f'{W}rPr/{W}color'); based = st.find(W + 'basedOn')
            styles[sid] = {'name': name.get(W + 'val') if name is not None else sid,
                           'level': int(lvl.get(W + 'val')) if lvl is not None else None,
                           'colour': col.get(W + 'val') if col is not None else None,
                           'based': based.get(W + 'val') if based is not None else None}

    def style_colour(sid, depth=0):
        st = styles.get(sid)
        if not st or depth > 8:
            return None
        return st['colour'] or style_colour(st['based'], depth + 1)

    def heading_level(sid):
        st = styles.get(sid)
        if not st:
            return None
        if st['level'] is not None:
            return st['level'] + 1 if st['level'] < 9 else None        # 9 is body text
        return 1 if re.search(r'heading|标题|title', st['name'], re.I) else None

    def normalise(colour):
        if not colour or colour.lower() in ('auto', '000000'):
            return NONE
        return '#' + colour.lower()

    paragraphs = []
    for p in ET.fromstring(document).iter(W + 'p'):
        ps = p.find(f'{W}pPr/{W}pStyle'); sid = ps.get(W + 'val') if ps is not None else None
        runs = []
        for r in p.iter(W + 'r'):
            text = ''.join((t.text or '') if t.tag == W + 't' else '\t' for t in r if t.tag in (W + 't', W + 'tab'))
            if not text:
                continue
            col = r.find(f'{W}rPr/{W}color'); rs = r.find(f'{W}rPr/{W}rStyle')
            colour = normalise((col.get(W + 'val') if col is not None else None)
                               or style_colour(rs.get(W + 'val') if rs is not None else None) or style_colour(sid))
            if runs and runs[-1][1] == colour:
                runs[-1][0] += text
            else:
                runs.append([text, colour])
        text = ''.join(t for t, _ in runs)
        if not text.strip():
            continue
        paragraphs.append({'level': heading_level(sid), 'style': styles.get(sid, {}).get('name', sid or ''), 'runs': runs, 'text': text.strip()})
    title = next((p['text'] for p in paragraphs if p['level']), None)
    return {'paragraphs': paragraphs, 'title': title}


def colour_groups(paragraphs):
    """Every colour in the body text, most text first: how many runs and
    paragraphs, and up to three sample runs — for the reviewer to say who it is."""
    groups = {}
    for p in paragraphs:
        if p['level']:
            continue
        for text, colour in p['runs']:
            if not text.strip():
                continue
            g = groups.setdefault(colour, {'colour': colour, 'runs': 0, 'chars': 0, 'paragraphs': set(), 'samples': []})
            g['runs'] += 1; g['chars'] += len(text.strip()); g['paragraphs'].add(id(p))
            if len(g['samples']) < 3 and text.strip() not in g['samples']:
                g['samples'].append(text.strip()[:60])
    out = []
    for g in sorted(groups.values(), key=lambda g: -g['chars']):
        out.append({**g, 'paragraphs': len(g['paragraphs']), 'average': round(g['chars'] / g['runs'])})
    return out


def has_quotes(paragraphs):
    return any(c in p['text'] for p in paragraphs for c in QUOTE_OPEN)


def compose(paragraphs, choices):
    """The reviewer's answers, one per colour — {'as': 'character', 'name': …} /
    {'as': 'narration'} / {'as': 'drop'} / {'as': 'ignore'} — into the text a
    project stores, with:
      headings: line numbers of heading lines (the book cutter opens chapters at level 1);
      silent:   line numbers not read aloud (every heading);
      hints:    [{'start', 'end', 'speaker'}] — spans of the text the colours
                settle: a character's name, 'NARRATOR' for narration, '' for a
                colour the reviewer left unnamed (speech, speaker unplaced).
    A colour with no answer is kept and hinted as unplaced (''). Only level-1
    headings open chapters; lower headings are lines of the chapter."""
    lines, hints, headings, silent = [], [], [], []
    pos = 0                                              # offset in the composed text
    heading_levels = sorted({p['level'] for p in paragraphs if p['level']})
    top = heading_levels[0] if heading_levels else None

    def emit(text, speaker=None):
        nonlocal pos
        lines.append(text)
        if speaker is not None:
            hints.append({'start': pos, 'end': pos + len(text), 'speaker': speaker})
        pos += len(text) + 1                             # the line break after it

    for p in paragraphs:
        if p['level']:
            if p['level'] == top:
                headings.append(len(lines))
            silent.append(len(lines))
            emit(p['text'])
            continue
        # Runs, with emphasis folded into its neighbours and dropped colours removed.
        runs = []
        for text, colour in p['runs']:
            choice = choices.get(colour, {})
            kind = choice.get('as', 'unassigned')
            if kind == 'drop':
                continue
            if kind == 'ignore':
                if runs:
                    runs[-1][0] += text
                else:
                    runs.append([text, None])           # decided by the next run
                continue
            if runs and runs[-1][1] is None:
                runs[-1] = [runs[-1][0] + text, colour]
            elif runs and runs[-1][1] == colour:
                runs[-1][0] += text
            else:
                runs.append([text, colour])
        runs = [[t, c] for t, c in runs if t.strip()]
        if not runs:
            continue
        speakers = []
        for text, colour in runs:
            choice = choices.get(colour, {}) if colour is not None else {}
            kind = choice.get('as', 'unassigned')
            speakers.append('NARRATOR' if kind == 'narration' else (choice.get('name', '').strip() if kind == 'character' else ''))
        if len(set(speakers)) == 1:
            emit(''.join(t for t, _ in runs).strip(), speakers[0])
            continue
        # Two speakers' colours in one paragraph: one line per run, each its own.
        for (text, _), speaker in zip(runs, speakers):
            emit(text.strip(), speaker)
    text = '\n'.join(lines) + ('\n' if lines else '')
    return {'text': text, 'headings': headings, 'silent': silent, 'hints': hints}


# 最后更新：2026-09-16 · Claude Hera
