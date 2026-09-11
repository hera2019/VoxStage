"""Subtitles are a view of a segment, with a screen's rules rather than a voice's."""
import numpy as np
import pytest

from runtime.subtitles import LIMITS, cues, hold_briefest, pauses, screen_text


def speech(pattern, rate=24000):
    """Audio built from spoken/silent runs given in seconds."""
    parts = []
    for seconds, loud in pattern:
        n = round(rate * seconds)
        parts.append(np.random.RandomState(0).randn(n).astype(np.float32) * .2 if loud
                     else np.zeros(n, dtype=np.float32))
    return np.concatenate(parts)


def test_screen_text_drops_what_a_screen_does_not_need():
    assert screen_text('“应该就是这儿。”', 20) == '应该就是这儿'
    assert screen_text('押金三百二，机器一千零八十。', 20) == '押金三百二 机器一千零八十'
    # Tone survives: losing these changes how the line reads.
    assert screen_text('“是你吗？”', 20) == '是你吗？'
    assert screen_text('别动！', 20) == '别动！'
    # An English apostrophe is part of the word, not decoration.
    assert screen_text('"Don\'t," she said.', 42) == "Don't she said"


def test_a_long_line_is_wrapped_not_left_to_run_off_the_frame():
    long_zh = '林小雪把伞收起来抖了抖水她抬头看了看招牌又低头核对手机上的地址'
    shown = screen_text(long_zh, LIMITS['zh']['line'])
    assert all(len(line) <= LIMITS['zh']['line'] for line in shown.split('\n'))
    assert shown.replace('\n', '') == long_zh
    long_en = 'However little known the feelings or views of such a man may be on his first entering a neighbourhood'
    shown = screen_text(long_en, LIMITS['en']['line'])
    assert all(len(line) <= LIMITS['en']['line'] for line in shown.split('\n'))


def test_pauses_are_found_where_the_voice_stops():
    found = pauses(speech([(.5, True), (.4, False), (.5, True)]), 24000)
    assert len(found) == 1 and .4 < found[0] < .6      # roughly halfway through
    assert pauses(speech([(1.0, True)]), 24000) == []  # nothing to break on
    assert pauses(np.zeros(10, dtype=np.float32), 24000) == []


def test_cues_break_on_the_pause_and_land_on_a_text_boundary():
    text = '门上贴着一张纸，写着今日盘点。'
    segment = {}
    pcm = speech([(1.65, True), (.38, False), (1.5, True)])
    out = cues(segment, text, 0, 24000 * 4, 'zh', pcm, 24000)
    assert [c[2] for c in out] == ['门上贴着一张纸', '写着今日盘点']
    # The segment's own boundaries stay exact.
    assert out[0][0] == 0 and out[-1][1] == 24000 * 4
    assert all(a[1] <= b[0] for a, b in zip(out, out[1:]))


def test_a_pause_with_no_boundary_near_it_is_ignored_rather_than_honoured():
    """Character positions are interpolated, so a break can land mid-word."""
    text = '门上贴着一张纸写着今日盘点暂停营业林小雪把伞收起来'
    pcm = speech([(1.0, True), (.4, False), (1.0, True)])
    out = cues({}, text, 0, 24000 * 3, 'zh', pcm, 24000)
    assert all(c[2] for c in out)
    assert ''.join(c[2] for c in out).replace(' ', '') == text


def test_without_audio_it_still_splits_on_punctuation():
    text = '门上贴着一张纸，写着今日盘点，暂停营业，她抬头看了看招牌，又低头核对地址。'
    out = cues({}, text, 0, 24000 * 8, 'zh')
    assert len(out) > 1
    assert all(len(line) <= LIMITS['zh']['line']
               for c in out for line in c[2].split('\n'))


def test_a_flash_of_a_cue_is_held_into_the_silence_but_never_over_the_next():
    rate = 24000
    held = hold_briefest([(0, rate // 4, '是'), (rate * 3, rate * 4, '下一句')], rate)
    assert held[0][1] == rate                       # extended to one second
    tight = hold_briefest([(0, rate // 4, '是'), (rate // 2, rate, '下一句')], rate)
    assert tight[0][1] == rate // 2                 # stops at the next cue
    assert tight[0][1] <= tight[1][0]


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_the_segment_text_is_never_written_back_to(language):
    segment = {'text': '“应该就是这儿。”'}
    before = dict(segment)
    cues(segment, segment['text'], 0, 24000, language, speech([(1., True)]), 24000)
    assert segment == before
