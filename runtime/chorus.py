"""群口 (本人 2026-09-22): several voices saying one line together — like a
crowd (群演) drawn from the same pool, but all at once instead of one a line.
A line's `voice` then names the pool, so the fingerprint, the cache and the
export treat the mix as one asset like any other take. Claude Hera."""
import numpy as np
from scipy.signal import istft, resample, stft

PREFIX = 'chorus:'
OFFSET_MS = 35          # loose: at least this much stagger between successive voices
MODES = ('loose', 'tight')


LAYER_SEED_STEP = 7919   # loose mode and mixed voice pools still render separate takes
SHARED_TAKE_VERSION = 'shared-take-v2'
LOOSE_MIX_VERSION = 'centered-v1'


def chorus_voice(pool, mode='loose', layers=1):
    """Encode the pool and its layering policy in the segment's voice id.

    A single voice in tight mode shares one reading across its layers. Other
    combinations render separate takes, as before.
    """
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


def _speech_window(pcm, rate):
    """Keep a little pre/post-roll while excluding long TTS edge silences."""
    peak = float(np.max(np.abs(pcm))) or 1.0
    audible = np.flatnonzero(np.abs(pcm) >= .01 * peak)
    if not len(audible):
        return pcm
    start = max(0, int(audible[0]) - round(rate * .015))
    end = min(len(pcm), int(audible[-1]) + 1 + round(rate * .04))
    return pcm[start:end]


def mix(takes, mode='loose'):
    """Mix independent takes. Loose: longest speech starts first; shorter takes
    start near the middle of its span, at least 35 ms apart. Tight is retained
    for legacy multi-voice projects; new tight mixes use synchronized_layers.
    The sum peaks like a single voice; metrics come from the longest take."""
    if not takes:
        raise ValueError('群口没有声音。')
    rate = takes[0][1]
    if any(t[1] != rate for t in takes):
        raise ValueError('群口的声音采样率不一致。')
    pcms = [np.asarray(t[0], dtype=np.float32) for t in takes]
    if mode == 'tight':
        pcms = [p[_onset(p, rate):] for p in pcms]
        starts = [0] * len(pcms)
        longest_take = max(takes, key=lambda t: len(np.asarray(t[0])))
    else:
        ordered = sorted(((_speech_window(p, rate), take) for p, take in zip(pcms, takes)),
                         key=lambda pair: len(pair[0]), reverse=True)
        pcms = [pcm for pcm, _ in ordered]
        longest_take = ordered[0][1]
        step = int(rate * OFFSET_MS / 1000)
        longest_length = len(pcms[0])
        starts = [max(i * step, (longest_length - len(p)) // 2) for i, p in enumerate(pcms)]
    total = max(len(p) + st for p, st in zip(pcms, starts))
    out = np.zeros(total, dtype=np.float32)
    for pcm, st in zip(pcms, starts):
        out[st:st + len(pcm)] += pcm
    peak_single = max(float(np.max(np.abs(np.asarray(t[0], dtype=np.float32)))) for t in takes) or 1.0
    peak_mix = float(np.max(np.abs(out))) or 1.0
    out *= peak_single / peak_mix
    metrics = dict(longest_take[2] or {})
    metrics['chorus_voices'] = len(takes); metrics['chorus_mode'] = mode
    if mode == 'loose':
        metrics['chorus_alignment'] = LOOSE_MIX_VERSION
    return out, rate, metrics


def _pitch_shift_same_length(pcm, rate, semitones):
    """Change a copy's pitch without changing its word and pause positions."""
    n_fft = min(1024, len(pcm))
    hop = max(1, n_fft // 4)
    _, _, spectrum = stft(pcm, fs=rate, nperseg=n_fft,
                          noverlap=n_fft - hop, boundary='zeros', padded=True)
    speed = 2 ** (-semitones / 12)
    steps = np.arange(0, spectrum.shape[1] - 1, speed)
    phases = np.angle(spectrum[:, 0])
    advance = 2 * np.pi * hop * np.arange(spectrum.shape[0]) / n_fft
    shifted = np.empty((spectrum.shape[0], len(steps)), dtype=np.complex64)
    for column, step in enumerate(steps):
        left = int(step)
        fraction = step - left
        first, second = spectrum[:, left], spectrum[:, left + 1]
        magnitude = (1 - fraction) * np.abs(first) + fraction * np.abs(second)
        shifted[:, column] = magnitude * np.exp(1j * phases)
        delta = np.angle(second) - np.angle(first) - advance
        phases += advance + (delta + np.pi) % (2 * np.pi) - np.pi
    _, stretched = istft(shifted, fs=rate, nperseg=n_fft,
                          noverlap=n_fft - hop, input_onesided=True, boundary=True)
    return resample(stretched, len(pcm)).astype(np.float32)


def synchronized_layers(take, layers):
    """Layer one reading on a shared timeline for a drill-style unison.

    Independent TTS seeds vary the pace *inside* a sentence. Aligning only the
    first sound cannot fix that. Here every layer has exactly the same words and
    pauses. Different pitches and small delays make the copies distinguishable
    without letting one voice finish a syllable ahead of the others.
    """
    if not 2 <= layers <= 4:
        raise ValueError('整齐群口需要同一声音叠 2–4 层。')
    pcm, rate, source_metrics = take
    original = np.asarray(pcm, dtype=np.float32)
    if original.ndim != 1 or not len(original) or not np.isfinite(original).all():
        raise ValueError('群口原音无效。')
    base = original[_onset(original, rate):]
    if not len(base):
        raise ValueError('群口原音为空。')
    voices = [base]
    pitches = (0, -.7, .55, 1.0)
    base_rms = float(np.sqrt(np.mean(base.astype(np.float64) ** 2)))
    for index in range(1, layers):
        varied = _pitch_shift_same_length(base, rate, pitches[index])
        varied_rms = float(np.sqrt(np.mean(varied.astype(np.float64) ** 2)))
        if varied_rms > 0:
            varied *= base_rms / varied_rms
        fixed = rate * (2.5 * index) / 1000
        depth = rate * .45 / 1000
        tail = int(np.ceil(fixed + depth)) + 2
        timeline = np.arange(len(base) + tail, dtype=np.float64)
        # A slow fractional delay softens phase locking; the maximum offset
        # between layers remains under ten milliseconds.
        delay = fixed + depth * np.sin(2 * np.pi * (.55 + .13 * index)
                                       * timeline / rate + index)
        shifted = np.interp(timeline - delay, np.arange(len(base)), varied,
                            left=0.0, right=0.0).astype(np.float32)
        voices.append(shifted)
    output = np.zeros(max(map(len, voices)), dtype=np.float32)
    for voice in voices:
        output[:len(voice)] += voice
    peak = float(np.max(np.abs(output))) or 1.0
    output *= (float(np.max(np.abs(base))) or 1.0) / peak
    metrics = dict(source_metrics or {})
    metrics.update(chorus_voices=layers, chorus_mode='tight',
                   chorus_alignment=SHARED_TAKE_VERSION, chorus_synthesis_takes=1)
    return output, rate, metrics

# 最后更新：2026-09-22 · Claude Hera
