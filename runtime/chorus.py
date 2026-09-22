"""群口 (本人 2026-09-22): several voices saying one line together — like a
crowd (群演) drawn from the same pool, but all at once instead of one a line.
A line's `voice` then names the pool, so the fingerprint, the cache and the
export treat the mix as one asset like any other take. Claude Hera."""
import numpy as np

PREFIX = 'chorus:'
OFFSET_MS = 35          # each voice starts a little after the one before — people never start on the same sample


def chorus_voice(pool):
    return PREFIX + '+'.join(pool)


def is_chorus(voice):
    return isinstance(voice, str) and voice.startswith(PREFIX)


def chorus_pool(voice):
    return [v for v in voice[len(PREFIX):].split('+') if v]


def mix(takes):
    """takes: [(pcm, rate, metrics)] one per voice, mono float. Each starts a
    little later than the one before, the sum is scaled so the mix peaks
    like a single voice, and the metrics are the longest take's."""
    if not takes:
        raise ValueError('群口没有声音。')
    rate = takes[0][1]
    if any(t[1] != rate for t in takes):
        raise ValueError('群口的声音采样率不一致。')
    step = int(rate * OFFSET_MS / 1000)
    total = max(len(np.asarray(t[0])) + i * step for i, t in enumerate(takes))
    out = np.zeros(total, dtype=np.float32)
    for i, (pcm, _, _) in enumerate(takes):
        pcm = np.asarray(pcm, dtype=np.float32)
        out[i * step:i * step + len(pcm)] += pcm
    peak_single = max(float(np.max(np.abs(np.asarray(t[0], dtype=np.float32)))) for t in takes) or 1.0
    peak_mix = float(np.max(np.abs(out))) or 1.0
    out *= peak_single / peak_mix
    longest = max(takes, key=lambda t: len(np.asarray(t[0])))
    metrics = dict(longest[2] or {})
    metrics['chorus_voices'] = len(takes)
    return out, rate, metrics

# 最后更新：2026-09-22 · Claude Hera
