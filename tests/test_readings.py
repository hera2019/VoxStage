"""A polyphonic character can be told how to read: 干[gan4]. Claude Hera, 2026-09-14."""
import pytest
from runtime.readings import resolve, explain, stand_in
from runtime.core import spoken_text, fingerprint
from runtime.engines import FixtureEngine
from tests.test_workflow import client, create  # noqa: F401


def test_a_pinned_reading_becomes_a_character_that_reads_only_that_way():
    assert resolve('他要干[gan4]活，衣服晾干[gan1]了。') == '他要赣活，衣服晾肝了。'
    assert resolve('干[gàn]活') == '赣活'                      # tone marks work too
    assert resolve('绿[lv4]') == '律'                          # v for ü
    assert stand_in('还', 'hai2') == '孩' and stand_in('觉', 'jiao4') == '叫'


def test_brackets_that_are_not_pinyin_are_left_alone():
    assert resolve('[笑] 这句[原样]念。') == '[笑] 这句[原样]念。'
    assert resolve('擦拭干净，[cao4]') == '擦拭干净，[cao4]'          # after punctuation: not a pinned character
    assert resolve('[eng4]！干[gan4]活') == '[eng4]！赣活'             # a stray bracket does not block the real one


def test_when_no_common_character_fits_the_original_stays_and_explain_says_so():
    assert resolve('乐[le4]呵呵') == '乐呵呵'
    assert explain('乐[le4] 干[gan4]') == [('乐[le4]', '乐'), ('干[gan4]', '赣')]


@pytest.mark.parametrize('bad, message', [('干[gan]', '缺声调'), ('干[gan9]', '1–5'), ('干[xyz4]', '没有读'), ('干[gan2]', '没有读')])
def test_bad_notation_is_refused_by_name(bad, message):
    with pytest.raises(ValueError, match=message):
        resolve(bad)


def test_the_notation_reaches_the_voice_through_the_replacement_and_the_lexicon(client):
    p = create(client, 'zh', script='旁白：他要干活。')
    s = p['segments'][0]; url = '/api/projects/' + p['id']
    before = fingerprint(p, s, FixtureEngine())
    p = client.patch(url, json={'revision': p['revision'], 'segment_id': s['id'], 'spoken_as': '他要干[gan4]活。'}).json()
    s = p['segments'][0]
    assert spoken_text(p, s) == '他要赣活。' and s['text'] == '他要干活。'     # the text and subtitles keep 干
    assert fingerprint(p, s, FixtureEngine()) != before                       # the line needs regenerating
    # A bad notation is refused when saved, not read aloud as letters.
    r = client.patch(url, json={'revision': p['revision'], 'segment_id': s['id'], 'spoken_as': '他要干[gan]活。'})
    assert r.status_code == 400 and '缺声调' in r.json()['detail']
    r = client.patch(url, json={'revision': p['revision'], 'lexicon': {'干活': '干[gan9]活'}})
    assert r.status_code == 400
    p = client.patch(url, json={'revision': p['revision'], 'segment_id': s['id'], 'spoken_as': ''}).json()
    p = client.patch(url, json={'revision': p['revision'], 'lexicon': {'干活': '干[gan4]活'}}).json()
    assert spoken_text(p, p['segments'][0]) == '他要赣活。'


def test_a_line_may_contain_a_line_break(client):
    p = create(client, 'zh', script='旁白：他不再问。')
    s = p['segments'][0]
    r = client.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'segment_id': s['id'], 'text': '他不再问。\n中秋过后，天凉了。'})
    assert r.status_code == 200, r.text
    assert r.json()['segments'][0]['text'] == '他不再问。\n中秋过后，天凉了。'


def test_lexicon_entries_apply_once_each_longest_match_first():
    """本人 2026-09-14: with 干净→干[gan1]净 and 干→干[gan4], 擦拭干净 came out gàn gān 净 —
    the second entry had rewritten the 干 the first one produced."""
    project = {'lexicon': {'干净': '干[gan1]净', '干': '干[gan4]'}}
    assert spoken_text(project, {'text': '擦拭干净，再去干活。'}) == '擦拭肝净，再去赣活。'
    project = {'lexicon': {'干': '干[gan4]', '干净': '干[gan1]净'}}          # order of entry does not matter
    assert spoken_text(project, {'text': '擦拭干净，再去干活。'}) == '擦拭肝净，再去赣活。'
    assert spoken_text({'lexicon': {'偸': '偷', '偷': '偸'}}, {'text': '偸偷'}) == '偷偸'   # no cascade either way
