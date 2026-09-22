"""群口 (本人 2026-09-22): several voices saying one line together — like a
crowd (群演) drawn from the same pool, but all at once instead of one a line.
A line's `voice` then names the pool, so the fingerprint, the cache and the
export treat the mix as one asset like any other take. Claude Hera."""
import numpy as np

PREFIX = 'chorus:'
OFFSET_MS = 35          # loose: each voice starts a little after the one before — a crowd never starts on the same sample
MODES = ('loose', 'tight')   # tight (本人 2026-09-22: 军队应答口令、群臣山呼万岁): every voice starts on the same sample, leading silence trimmed


LAYER_SEED_STEP = 7919   # each extra layer of the same voice is another take: a different seed, the same timbre


def chorus_voice(pool, mode='loose', layers=1):
    """`layers` > 1 (本人 2026-09-22: 同一个声音多次叠加): every voice in the pool
    is read that many times with different seeds and the takes are mixed."""
    return PREFIX + ('tight/' if mode == 'tight' else '') + (f'x{int(layers)}/' if int(layers) > 1 else '') + '+'.join(pool)


def is_chorus(voice):
    return isinstance(voice, str) and voice.startswith(PREFIX)


def _parts(voice):
    rest = voice[len(PREFIX):]
    mode, layers = 'loose', 1
    while True:
        if rest.startswith('tight/'):
            mode, rest = 'tight', rest[len('tight/'):]
        elif rest.startswith('x') and '/' in rest and rest[1:rest.index('/')].isdigit():
            layers, rest = int(rest[1:rest.index('/')]), rest[rest.index('/') + 1:]
        else:
            return mode, layers, [v for v in rest.split('+') if v]


def chorus_mode(voice):
    return _parts(voice)[0]


def chorus_layers(voice):
    return _parts(voice)[1]


def chorus_pool(voice):
    return _parts(voice)[2]


def _onset(pcm, rate, floor=0.02, keep_ms=15):
    """Where a take's sound begins: the first sample above the floor (relative to
    its own peak), a few milliseconds of run-in kept."""
    peak = float(np.max(np.abs(pcm))) or 1.0
    above = np.flatnonzero(np.abs(pcm) >= floor * peak)
    if not len(above):
        return 0
    return max(0, int(above[0]) - int(rate * keep_ms / 1000))


def mix(takes, mode='loose'):
    """takes: [(pcm, rate, metrics)] one per voice, mono float. Loose: each
    starts a little later than the one before. Tight: every take is cut to its
    onset and all start together. The sum is scaled so the mix peaks like a
    single voice; the metrics are the longest take's."""
    if not takes:
        raise ValueError('群口没有声音。')
    rate = takes[0][1]
    if any(t[1] != rate for t in takes):
        raise ValueError('群口的声音采样率不一致。')
    pcms = [np.asarray(t[0], dtype=np.float32) for t in takes]
    if mode == 'tight':
        pcms = [p[_onset(p, rate):] for p in pcms]
        starts = [0] * len(pcms)
    else:
        step = int(rate * OFFSET_MS / 1000)
        starts = [i * step for i in range(len(pcms))]
    total = max(len(p) + st for p, st in zip(pcms, starts))
    out = np.zeros(total, dtype=np.float32)
    for pcm, st in zip(pcms, starts):
        out[st:st + len(pcm)] += pcm
    peak_single = max(float(np.max(np.abs(np.asarray(t[0], dtype=np.float32)))) for t in takes) or 1.0
    peak_mix = float(np.max(np.abs(out))) or 1.0
    out *= peak_single / peak_mix
    longest = max(takes, key=lambda t: len(np.asarray(t[0])))
    metrics = dict(longest[2] or {})
    metrics['chorus_voices'] = len(takes); metrics['chorus_mode'] = mode
    return out, rate, metrics

# 最后更新：2026-09-22 · Claude Hera
