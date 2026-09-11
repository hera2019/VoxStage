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
BREAKS = ('。！？!?；;\n', '，、,：:—–…', ' \u3000')

QUOTES = '“”‘’「」『』《》＂"'
# Dropped at the end of a cue: a full stop earns nothing on screen. ？ and ！
# stay, because losing them changes how the line reads.
TRAILING = '。．.，、,；;：:'
# Replaced by a space mid-cue, which is how Chinese subtitles are normally set.
SPACED = '，、；：,;:'

PUNCTUATION = set(QUOTES + '。，、；：？！…—．,.!?;:\'\n\r\t 　')


def _spoken(text):
    """Indices of the characters a voice actually utters."""
    return [i for i, c in enumerate(text) if c not in PUNCTUATION]


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
            # No punctuation to break on. Rather than cut mid-phrase at exactly
            # the limit, run on to the next break if one is close behind.
            nxt = next((i + 1 for i in range(end, min(len(text), end + limit // 8))
                        if text[i] in BREAKS[0] + BREAKS[1]), None)
            end = nxt or end
        runs.append((start, end))
        start = end
    return [r for r in runs if text[r[0]:r[1]].strip()]


def screen_text(raw, line_limit):
    """Strip what a screen does not need, then wrap to at most two lines."""
    text = ''.join(c for c in raw if c not in QUOTES).strip()
    text = re.sub(f'[{re.escape(SPACED)}]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip(' ').strip(TRAILING).strip()
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


def _fractions(segment, text):
    """Where each spoken character falls inside the segment, as 0..1.

    Uses the per-character timings the transcribe-back check already stored.
    They come from the recogniser, so they only line up when it heard the same
    number of characters that the line contains; when it did not, position by
    character count instead and say so.
    """
    spoken = _spoken(text)
    timed = ((segment.get('content_check') or {}).get('timed_text')) or []
    heard = [e for e in timed
             if any(c not in PUNCTUATION for c in (e.get('text') or ''))]
    if len(heard) != len(spoken) or not heard:
        n = max(1, len(spoken))
        return {index: (rank / n, (rank + 1) / n) for rank, index in enumerate(spoken)}, False
    span = max((e.get('end') or 0) for e in heard) or 1.0
    return {index: (heard[rank].get('start', 0) / span, (heard[rank].get('end', 0) or 0) / span)
            for rank, index in enumerate(spoken)}, True


def pauses(pcm, rate, minimum=PAUSE_SECONDS):
    """Where the voice stops inside a line, as fractions of its speech span.

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
    span = (active[-1] - active[0]) or 1
    found = []
    for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if a > active[0] and b <= active[-1] and (b - a) * frame / rate >= minimum:
            # Break at the middle of the silence, expressed against the spoken
            # span so it can be compared with character positions.
            found.append(float(((a + b) / 2 - active[0]) / span))
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
    def boundary(i):
        if not 0 < i < len(text):
            return False
        if text[i - 1] in BREAKS[0] + BREAKS[1] + QUOTES:
            return True                         # just after punctuation
        return text[i - 1].isspace() and not text[i].isspace()
    return next((i for offset in range(window + 1)
                 for i in (index - offset, index + offset) if boundary(i)), None)


def cues(segment, text, start_sample, end_sample, language, pcm=None, rate=None):
    """Subtitle cues for one segment, as (start_sample, end_sample, text, timed).

    start_sample/end_sample are the segment's speech boundaries in the finished
    file; cue boundaries are placed inside that span, so the first cue always
    begins and the last always ends exactly where the segment does.
    """
    limits = LIMITS.get(language, LIMITS['en'])
    position, timed = _fractions(segment, text)
    spoken = sorted(position)
    breaks, window = set(), 3 if language == 'zh' else 12
    for fraction in (pauses(pcm, rate) if pcm is not None and rate else []):
        # The first character that starts after the silence opens a new cue.
        after = [i for i in spoken if position[i][0] >= fraction]
        if after and after[0] != spoken[0]:
            at = _snap(text, after[0], window)
            if at is not None:
                breaks.add(at)
    runs = []
    for first, last in _runs(text, sorted(breaks)):
        runs += [(first + a, first + b) for a, b in _split(text[first:last], limits['cue'])]
    total = end_sample - start_sample
    out = []
    for first, last in runs:
        shown = screen_text(text[first:last], limits['line'])
        if not shown:
            continue
        inside = [i for i in range(first, last) if i in position]
        head = position[inside[0]][0] if inside else 0.0
        tail = position[inside[-1]][1] if inside else 1.0
        out.append((start_sample + round(total * head),
                    start_sample + round(total * min(1.0, tail)), shown, timed))
    if not out:
        return [(start_sample, end_sample, text.strip(), timed)]
    # Keep the segment's own boundaries exact and never let cues overlap.
    out[0] = (start_sample,) + out[0][1:]
    out[-1] = out[-1][:1] + (end_sample,) + out[-1][2:]
    for i in range(len(out) - 1):
        if out[i][1] > out[i + 1][0]:
            out[i] = out[i][:1] + (out[i + 1][0],) + out[i][2:]
    return [c for c in out if c[1] > c[0]]


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
    for i, (start, end, shown) in enumerate(out):
        if end - start >= want:
            continue
        ceiling = out[i + 1][0] if i + 1 < len(out) else start + want
        out[i] = (start, max(end, min(start + want, ceiling)), shown)
    return out


# 最后更新：2026-09-12 · Claude Hera（最短显示时长，只向后面的静音里延伸）
