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
    # An apostrophe is part of the word, not decoration — the curly one too,
    # which is what real text uses. And a mark inside a number stays.
    assert screen_text('"Don\'t," she said.', 42) == "Don't she said"
    assert screen_text('“Don’t,” she said.', 42) == 'Don’t she said'
    assert screen_text('It’s 12:30, pay 1,000.', 42) == 'It’s 12:30 pay 1,000'


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
    assert len(found) == 1 and .6 < found[0] < .8      # middle of the 0.5–0.9 s silence
    assert pauses(speech([(1.0, True)]), 24000) == []  # nothing to break on
    assert pauses(np.zeros(10, dtype=np.float32), 24000) == []


def test_cues_break_on_the_pause_and_land_on_a_text_boundary():
    text = '门上贴着一张纸，写着今日盘点。'
    segment = {}
    pcm = speech([(1.65, True), (.38, False), (1.5, True)])
    out = cues(segment, text, 0, 24000 * 4, 'zh', pcm, 24000, None, 0)
    assert [c[2] for c in out] == ['门上贴着一张纸', '写着今日盘点']
    # The segment's own boundaries stay exact.
    assert out[0][0] == 0 and out[-1][1] == 24000 * 4
    assert all(a[1] <= b[0] for a, b in zip(out, out[1:]))


def test_a_pause_with_no_boundary_near_it_is_ignored_rather_than_honoured():
    """Character positions are interpolated, so a break can land mid-word."""
    text = '门上贴着一张纸写着今日盘点暂停营业林小雪把伞收起来'
    pcm = speech([(1.0, True), (.4, False), (1.0, True)])
    out = cues({}, text, 0, 24000 * 3, 'zh', pcm, 24000, None, 0)
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
    cues(segment, segment['text'], 0, 24000, language, speech([(1., True)]), 24000, None, 0)
    assert segment == before


def timed(chars, each=0.2):
    return [{'text': c, 'start': i * each, 'end': (i + 1) * each} for i, c in enumerate(chars)]


def test_timings_are_used_only_when_they_describe_this_very_audio():
    rate = 24000
    text = '门上贴着一张纸，写着今日盘点。'
    heard = timed('门上贴着一张纸写着今日盘点')
    fresh = {'audio': {'fingerprint': 'abc'},
             'content_check': {'source_fingerprint': 'abc', 'timed_text': heard}}
    stale = {'audio': {'fingerprint': 'abc'},
             'content_check': {'source_fingerprint': 'OLD', 'timed_text': heard}}
    out = cues(fresh, text, 0, rate * 3, 'zh', None, rate, None, 0)
    assert all(not c[3] for c in out)                      # trusted: not an estimate
    out = cues(stale, text, 0, rate * 3, 'zh', None, rate, None, 0)
    assert all(c[3] for c in out)                          # stale: marked estimated


def test_timings_follow_a_speed_change_and_give_up_inside_a_cut():
    rate = 24000
    text = '门上贴着一张纸，写着今日盘点。'
    heard = timed('门上贴着一张纸写着今日盘点')                 # 13 chars, 0–2.6 s
    segment = {'audio': {'fingerprint': 'abc'},
               'content_check': {'source_fingerprint': 'abc', 'timed_text': heard}}
    # The whole line played at half speed: every output time is doubled.
    slow = [{'source_start': 0.0, 'source_end': 2.6, 'output_start': 0.0, 'output_end': 5.2, 'speed': .5}]
    out = cues(segment, text, 0, rate * 5, 'zh', speech([(2.0, True), (.4, False), (2.8, True)]), rate, slow, 0)
    assert all(not c[3] for c in out)
    assert out[0][1] >= rate * 2                            # first cue reaches past 2 s, not 1 s
    # A cut removed 写着 from the middle: those timings no longer exist.
    cut = [{'source_start': 0.0, 'source_end': 1.4, 'output_start': 0.0, 'output_end': 1.4, 'speed': 1},
           {'source_start': 1.8, 'source_end': 2.6, 'output_start': 1.4, 'output_end': 2.2, 'speed': 1}]
    out = cues(segment, text, 0, rate * 2, 'zh', None, rate, cut, 0)
    assert all(c[3] for c in out)                          # fell back, and says so


def test_english_timings_fold_sub_word_tokens_back_into_their_word():
    from runtime.subtitles import _heard
    timed = [{'text': ' Nether', 'start': 0.0, 'end': 0.3}, {'text': 'field', 'start': 0.3, 'end': 0.5},
             {'text': ' Park', 'start': 0.5, 'end': 0.8}, {'text': '?', 'start': 0.8, 'end': 0.8}]
    assert _heard(timed, 'en') == [(0.0, 0.5), (0.5, 0.8)]


def test_a_break_prefers_the_comma_over_the_nearest_space():
    from runtime.subtitles import _snap
    text = 'on his first entering a neighbourhood, this truth is so well fixed'
    # The silence lands at the start of "truth": the comma four words back is
    # the real phrase boundary, and beats the space right there.
    at = text.index('truth')
    assert text[_snap(text, at, 12):].lstrip().startswith('this truth')


def test_a_few_character_tail_joins_the_cue_before_it():
    """但总觉有些单调 | 有些无聊 → one cue; the stub was a flash on screen."""
    text = '但总觉有些单调，有些无聊。'
    # Silence right before the tail, so the pause rule would cut it off.
    pcm = speech([(2.0, True), (.3, False), (.8, True)])
    out = cues({}, text, 0, 24000 * 3, 'zh', pcm, 24000, None, 0)
    assert [c[2] for c in out] == ['但总觉有些单调 有些无聊']


def test_a_stub_that_would_overflow_its_neighbour_is_left_alone():
    from runtime.subtitles import _absorb_stubs
    long = '一' * 18
    out = _absorb_stubs([(0, 10, long, False), (10, 20, '好的', False)], 'zh', 20)
    assert [c[2] for c in out] == [long, '好的']


def test_a_break_falls_before_a_conjunction_when_there_is_no_punctuation():
    from runtime.subtitles import _split, _snap
    text = '他站在门口看了很久然后转身走进了里屋'
    runs = [text[a:b] for a, b in _split(text, 12)]
    assert runs[0].endswith('很久') and runs[1].startswith('然后')
    at = text.index('转身')                       # a pause landing a word late
    assert text[_snap(text, at, 3):].startswith('然后')


def test_dashes_and_ellipses_break_before_commas():
    from runtime.subtitles import _split
    text = '这是二十多年前的事——现在每碗要涨到十文，靠柜外站着'
    runs = [text[a:b] for a, b in _split(text, 16)]
    assert runs[0].endswith('——')
