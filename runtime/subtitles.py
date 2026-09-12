"""Subtitle cues derived from segments, never the segment text itself.

Cues break where the voice actually stops. Films do it that way — one thing
said, one cue, then a pause — and a break placed by counting characters lands
mid-thought however carefully the count is chosen. Punctuation and a character
limit stay as fallbacks for when the silence is not there to be found.

A segment is a synthesis unit: it keeps the script verbatim, punctuation and
all, because the source has to be reconstructible from it and because the
punctuation is what the voice reads. A subtitle is a different object with
different rules — it has to be read off a screen in a couple of seconds, so it
gets split, stripped and wrapped. Nothing here writes back into a segment.
"""
import re

import numpy as np

# A gap this long reads as a break between two things said. The listening cues
# use 0.35 s to flag a pause worth reviewing; a subtitle should break on the
# shorter breaths too, so this is lower.
PAUSE_SECONDS = 0.18

# Per language: how many characters a cue may hold, and how many fit on one
# line on screen. Chinese characters are wide, so both numbers are far lower
# than the 60-character synthesis limit.
LIMITS = {'zh': {'cue': 20, 'line': 20}, 'en': {'cue': 84, 'line': 42}}

# Sentence-final marks a cue may be split after, strongest first. Question and
# exclamation marks carry tone, so they are split points but never removed.
BREAKS = ('。！？!?；;\n—–…', '，、,：:', ' \u3000')
# Where a sentence ends. A cue is always cut here; a dash or an ellipsis is a
# strong place to cut but not a compulsory one, and a run of …… stays whole.
SENTENCE_END = '。！？!?'

# A break may also fall just before one of these: where the sentence turns,
# a reader expects a new cue. Two-character forms only, so 但 inside 不但
# cannot match. Used after punctuation and before a mere space.
CONJUNCTIONS = ('但是', '可是', '然而', '于是', '然后', '接着', '因为', '所以', '如果',
                '虽然', '只是', '不过', '而且', '并且', '因此', '结果', '后来', '这时')

# A cue shorter than this is a flash and is folded into its neighbour when
# the pair still fits on the screen.
MIN_UNITS = {'zh': 5, 'en': 3}

QUOTES = '“”‘’「」『』《》＂"'
# Dropped at the end of a cue: a full stop earns nothing on screen. ？ and ！
# stay, because losing them changes how the line reads.
TRAILING = '。．.，、,；;：:'
# Replaced by a space mid-cue, which is how Chinese subtitles are normally set.
SPACED = '，、；：,;:'

PUNCTUATION = set(QUOTES + '。，、；：？！…—．,.!?;:\'\n\r\t 　')


_WORD = re.compile(r"[^\W_]+(?:[’'][^\W_]+)*")


def _spoken(text, language='zh'):
    """Start index of each unit a voice utters: a character in Chinese, a word
    in English. This is the unit the recogniser reports timings for, so the two
    sides can be counted against each other."""
    if language == 'en':
        return [m.start() for m in _WORD.finditer(text)]
    return [i for i, c in enumerate(text) if c not in PUNCTUATION]


def _heard(timed, language):
    """The recogniser's timings, one per spoken unit.

    Chinese recognition sometimes returns two characters as one entry (今日,
    就是); its span is shared evenly between them so the count matches the
    line's. English entries are already words.
    """
    out = []
    for entry in timed:
        raw = entry.get('text') or ''
        chars = [c for c in raw if c not in PUNCTUATION]
        if not chars:
            continue
        a, b = entry.get('start') or 0.0, entry.get('end') or 0.0
        if language == 'en':
            # The recogniser marks a word start with a leading space; an entry
            # without one continues the previous word (Nether + field,
            # impatient + ly), so its time is folded into that word.
            if out and not raw[:1].isspace():
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
            continue
        step = (b - a) / len(chars)
        out += [(a + k * step, a + (k + 1) * step) for k in range(len(chars))]
    return out


def _split(text, limit):
    """Cut text into runs no longer than limit, preferring sentence ends.

    Returns character ranges into the original text so timing can be looked up
    against the untouched string.
    """
    runs, start = [], 0
    while start < len(text):
        if len(text) - start <= limit:
            runs.append((start, len(text)))
            break
        end = start + limit
        for marks in BREAKS:
            found = [i + 1 for i in range(start, end) if text[i] in marks]
            if found:
                end = found[-1]
                break
        else:
            # No punctuation to break on. A conjunction inside the window is the
            # next best place; failing that, rather than cut mid-phrase at
            # exactly the limit, run on to the next break if one is close behind.
            turns = [i for i in range(start + 1, end) if text.startswith(CONJUNCTIONS, i)]
            if turns:
                end = turns[-1]
            else:
                nxt = next((i + 1 for i in range(end, min(len(text), end + limit // 8))
                            if text[i] in BREAKS[0] + BREAKS[1]), None)
                end = nxt or end
        runs.append((start, end))
        start = end
    return [r for r in runs if text[r[0]:r[1]].strip()]


# A mark inside a word or a number is part of it, not decoration: the curly
# apostrophe in don’t, the colon in 12:30, the comma in 1,000. Guard them before
# the stripping below, and put them back after.
_INSIDE = re.compile(r'(?<=[^\W\d_])[’\'](?=[^\W\d_])|(?<=\d)[:,.](?=\d)')
_HOLD = '\x00'


def screen_text(raw, line_limit):
    """Strip what a screen does not need, then wrap to at most two lines."""
    kept = _INSIDE.findall(raw)
    text = _INSIDE.sub(_HOLD, raw)
    text = ''.join(c for c in text if c not in QUOTES).strip()
    text = re.sub(f'[{re.escape(SPACED)}]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip(' ').strip(TRAILING).strip()
    text = re.sub(r' (?=[…—–])', '', text)       # 读过书，…… → 读过书……, not 读过书 ……
    for mark in kept:
        text = text.replace(_HOLD, mark, 1)
    if len(text) <= line_limit:
        return text
    # Break near the middle so the lines are balanced, at a space when one is
    # available there. A line over the limit is wrapped again rather than left
    # to run off the side of the frame.
    def wrap(part):
        if len(part) <= line_limit:
            return [part]
        middle = len(part) // 2
        spaces = [i for i, c in enumerate(part) if c == ' ']
        cut = min(spaces, key=lambda i: abs(i - middle)) if spaces else middle
        return wrap(part[:cut].strip()) + wrap(part[cut:].strip())
    return '\n'.join(wrap(text))


def _through(mapping, seconds):
    """Original-audio seconds -> finished-audio seconds, or None inside a cut."""
    if not mapping:
        return seconds
    for m in mapping:
        if m['source_start'] <= seconds <= m['source_end']:
            width = m['source_end'] - m['source_start']
            share = (seconds - m['source_start']) / width if width else 0.0
            return m['output_start'] + share * (m['output_end'] - m['output_start'])
    return None


def _positions(segment, text, start_sample, end_sample, rate, file_start, mapping, language='zh'):
    """Where each spoken character sits in the finished file, in samples.

    The per-character timings the transcribe-back check stored are used only
    when they demonstrably describe this audio: the check ran on the same
    fingerprint, and it heard as many characters as the line holds. They are
    then carried through whatever speed and cut edits produced the exported
    audio. Anything that fails those tests is positioned by character count
    instead, and the cue is marked as an estimate.
    """
    spoken = _spoken(text, language)
    n = max(1, len(spoken))
    by_count = {i: (start_sample + round((end_sample - start_sample) * r / n),
                    start_sample + round((end_sample - start_sample) * (r + 1) / n))
                for r, i in enumerate(spoken)}
    check = segment.get('content_check') or {}
    fingerprint = (segment.get('audio') or {}).get('fingerprint')
    heard = _heard(check.get('timed_text') or [], language)
    if (not fingerprint or check.get('source_fingerprint') != fingerprint
            or len(heard) != len(spoken) or not heard or rate is None or file_start is None):
        return by_count, False
    out = {}
    for r, i in enumerate(spoken):
        a, b = _through(mapping, heard[r][0]), _through(mapping, heard[r][1])
        if a is None or b is None or b < a:
            return by_count, False              # a cut removed it: do not guess
        out[i] = (file_start + round(a * rate), file_start + round(b * rate))
    return out, True


def pauses(pcm, rate, minimum=PAUSE_SECONDS):
    """Where the voice stops inside a line, in seconds from the audio's start.

    Same low-energy test the listening cues use, at a lower threshold: this
    decides where a subtitle breaks, not whether a human should re-listen.
    """
    pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
    frame = max(1, round(rate * .01))
    if len(pcm) < frame * 2 or not np.isfinite(pcm).all():
        return []
    padded = np.pad(pcm, (0, (-len(pcm)) % frame)).reshape(-1, frame)
    rms = np.sqrt(np.mean(padded * padded, axis=1))
    threshold = max(.0005, float(rms.max()) * .015)
    active = np.flatnonzero(rms >= threshold)
    if not len(active):
        return []
    quiet = rms < threshold
    edges = np.diff(np.r_[False, quiet, False].astype(int))
    found = []
    for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if a > active[0] and b <= active[-1] and (b - a) * frame / rate >= minimum:
            found.append((a + b) / 2 * frame / rate)   # middle of the silence, seconds
    return found


def _snap(text, index, window):
    """Move a break found in the audio onto a boundary in the text.

    The silence says roughly where the voice stopped, but the character
    positions it is compared against are interpolated across the recogniser's
    phrases, so the index lands a character or two out and cuts 写着 or a word
    in half. Search outward for a real boundary and give up if there is none —
    a pause with no boundary near it is better ignored than honoured.
    """
    if not 0 < index < len(text):
        return None
    def after_sentence_end(i):
        return 0 < i < len(text) and (text[i - 1] in BREAKS[0] or (text[i - 1] in QUOTES and i > 1 and text[i - 2] in BREAKS[0])) and text[i] not in PUNCTUATION
    def after_comma(i):
        return 0 < i < len(text) and text[i - 1] in BREAKS[1] + QUOTES
    def before_conjunction(i):
        return 0 < i < len(text) and text.startswith(CONJUNCTIONS, i)
    def after_space(i):
        return 0 < i < len(text) and text[i - 1].isspace() and not text[i].isspace()
    # The end of a sentence within reach beats a comma, a comma beats a
    # conjunction, and any of them beats the nearest space: a pause that lands
    # a word late would otherwise drag that word onto the wrong cue.
    for test in (after_sentence_end, after_comma, before_conjunction, after_space):
        found = next((i for offset in range(window + 1)
                      for i in (index - offset, index + offset) if test(i)), None)
        if found is not None:
            return found
    return None


def cues(segment, text, start_sample, end_sample, language,
         pcm=None, rate=None, mapping=None, file_start=None):
    """Subtitle cues for one segment: (start_sample, end_sample, text, estimated).

    start_sample/end_sample are the segment's speech boundaries in the finished
    file and file_start is where its audio begins there. The first cue always
    opens and the last always closes exactly on the speech boundaries; `estimated`
    is True when the inner boundaries were placed by character count rather than
    by timings known to describe this audio.
    """
    limits = LIMITS.get(language, LIMITS['en'])
    position, trusted = _positions(segment, text, start_sample, end_sample, rate, file_start, mapping, language)
    spoken = sorted(position)
    breaks, window = set(), 3 if language == 'zh' else 12
    # A cue never runs across the end of a sentence. Where the text puts a full
    # stop, question mark or exclamation mark, the cue ends there whether or not
    # the voice paused; a fragment left too short is folded back afterwards.
    for i in range(1, len(text)):
        if text[i - 1] in SENTENCE_END or (text[i - 1] in QUOTES and i > 1 and text[i - 2] in SENTENCE_END):
            if text[i:].strip() and text[i] not in PUNCTUATION:
                breaks.add(i)
    if pcm is not None and rate and file_start is not None:
        for seconds in pauses(pcm, rate):
            at_sample = file_start + round(seconds * rate)
            # The first character that starts after the silence opens a new cue.
            after = [i for i in spoken if position[i][0] >= at_sample]
            if after and after[0] != spoken[0]:
                at = _snap(text, after[0], window)
                if at is not None:
                    breaks.add(at)
    runs = []
    for first, last in _runs(text, sorted(breaks)):
        runs += [(first + a, first + b) for a, b in _split(text[first:last], limits['cue'])]
    out = []
    for first, last in runs:
        shown = screen_text(text[first:last], limits['line'])
        if not shown:
            continue
        inside = [i for i in range(first, last) if i in position]
        head = position[inside[0]][0] if inside else start_sample
        tail = position[inside[-1]][1] if inside else end_sample
        out.append((max(start_sample, head), min(end_sample, tail), shown, not trusted))
    if not out:
        return [(start_sample, end_sample, text.strip(), not trusted)]
    out = _absorb_stubs(out, language, limits['line'])
    # Keep the segment's own boundaries exact and never let cues overlap.
    out[0] = (start_sample,) + out[0][1:]
    out[-1] = out[-1][:1] + (end_sample,) + out[-1][2:]
    for i in range(len(out) - 1):
        if out[i][1] > out[i + 1][0]:
            out[i] = out[i][:1] + (out[i + 1][0],) + out[i][2:]
    return [c for c in out if c[1] > c[0]]


def _absorb_stubs(out, language, line_limit):
    """Fold a cue of a few characters into its neighbour when the pair fits.

    A four-character tail left over at the end of a sentence — 有些无聊 after
    但总觉有些单调 — is a flash on screen, not a cue. It joins the cue before
    it (or after it, for a leading stub) as long as the result stays within one
    line; a stub that would push its neighbour over the limit is left alone.
    """
    minimum = MIN_UNITS.get(language, MIN_UNITS['en'])
    def units(shown):
        return len(shown.replace('\n', '')) if language == 'zh' else len(shown.split())
    def joined(a, b):
        # The seam almost always had a comma, which the screen shows as a
        # space; a stub with nothing before it gets the same space.
        return a.replace('\n', ' ') + ' ' + b.replace('\n', ' ')
    cues = list(out)
    i = 0
    while i < len(cues) and len(cues) > 1:
        start, end, shown, estimated = cues[i]
        if units(shown) >= minimum:
            i += 1
            continue
        j = i - 1 if i > 0 else i + 1
        text = joined(cues[j][2], shown) if j < i else joined(shown, cues[j][2])
        if len(text) > line_limit:
            i += 1
            continue
        a, b = (cues[j], cues[i]) if j < i else (cues[i], cues[j])
        merged = (a[0], b[1], screen_text(text, line_limit), a[3] or b[3])
        cues[min(i, j):max(i, j) + 1] = [merged]
        i = max(0, min(i, j))
    return cues


def _runs(text, breaks):
    """Character ranges between the given break points."""
    edges = [0] + [b for b in breaks if 0 < b < len(text)] + [len(text)]
    return [(a, b) for a, b in zip(edges, edges[1:]) if b > a]


# 最后更新：2026-09-12 · Claude Hera（字幕条独立于音频片段：拆分、去标点、折行）


MINIMUM_SECONDS = 1.0


def hold_briefest(cues, rate, minimum=MINIMUM_SECONDS):
    """Let a very short cue stay on screen into the silence that follows it.

    A one-word reply is spoken in half a second, and a subtitle shown for half
    a second is a flash nobody reads. Extending the end runs into the gap before
    the next line, which is silence, so nothing is covered up — and a cue is
    never pushed into the one after it.
    """
    out = list(cues)
    want = round(rate * minimum)
    for i, (start, end, *rest) in enumerate(out):
        if end - start >= want:
            continue
        ceiling = out[i + 1][0] if i + 1 < len(out) else start + want
        out[i] = (start, max(end, min(start + want, ceiling)), *rest)
    return out


# 最后更新：2026-09-12 · Claude Hera（最短显示时长，只向后面的静音里延伸）
