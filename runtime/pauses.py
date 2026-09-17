"""A pause where the text trails off or breaks: a line read in parts at its
ellipses and dashes, the parts joined with silence.

本人 2026-09-17, listening to “窃书不能算偸……窃书！……读书人的事，能算偸么？”:
neither cloning model paused at the ellipsis; the line cut into three, each
read on its own and joined with half a second of silence, was the version
chosen. The engines have no way to draw a syllable out (拖音); a pause is
what can be done here. Claude Hera, 2026-09-17."""
import re

import numpy as np

# A run of ellipsis marks, or a dash (Chinese ——, or an em dash), anywhere
# but at the very start or end of the line.
PAUSE_MARK = re.compile(r'(?:…+|\.{3,}|——+|—)')
_TRAILING = re.compile(r'^[\s”"」』’\'）)]*$')      # only closing marks after the pause: no part of its own
PAUSE_CHOICES = (0, 300, 500)                      # milliseconds; 0 = leave the line whole


def split_at_pauses(text):
    """The line cut after each pause mark. A cut only happens when speech
    follows the mark: a mark that ends the line, or is followed by nothing but
    closing quotation marks, keeps the line whole there. A line with no mark
    comes back as itself."""
    parts, start = [], 0
    for m in PAUSE_MARK.finditer(text):
        end = m.end()
        while end < len(text) and text[end] in '”"」』’\')）':   # a closing mark stays with what it closes
            end += 1
        rest = text[end:]
        if not rest or _TRAILING.match(rest):
            continue
        head = text[start:end]
        if not re.search(r'[\w\u4e00-\u9fff]', head):    # nothing to say before the mark: keep it with what follows
            continue
        parts.append(head); start = end
    parts.append(text[start:])
    return [x for x in parts if x.strip()] or [text]


def join_with_silence(parts, rate, gap_ms, pad_ms=100):
    """parts: [(pcm, speech_start_sample, speech_end_sample)] — each part's
    spoken region, joined with gap_ms of silence, a short pad at both ends.
    Returns the pcm and the seconds of silence inserted."""
    silence = np.zeros(int(rate * gap_ms / 1000), dtype=np.float32)
    pad = np.zeros(int(rate * pad_ms / 1000), dtype=np.float32)
    pieces = [pad]
    for n, (pcm, a, b) in enumerate(parts):
        pieces.append(np.asarray(pcm, dtype=np.float32)[a:b])
        pieces.append(silence if n < len(parts) - 1 else pad)
    return np.concatenate(pieces), gap_ms / 1000 * (len(parts) - 1)
