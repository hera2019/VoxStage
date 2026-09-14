"""A crowd is one character in the script and many voices in the recording. Claude Hera, 2026-09-15."""
from runtime.core import fingerprint, voice_of
from runtime.engines import FixtureEngine
from tests.test_workflow import client, create  # noqa: F401


def test_a_crowd_draws_a_voice_per_line_never_the_same_twice_in_a_row(client):
    p = create(client, 'zh', script='\n'.join(f'众人：第{i}句。' for i in range(1, 13)) + '\n旁白：完。')
    url = '/api/projects/' + p['id']
    before = {s['id']: fingerprint(p, s, FixtureEngine()) for s in p['segments']}
    r = client.post(url + '/crowd', json={'revision': p['revision'], 'speaker': '众人', 'pool': ['Vivian', 'Dylan', 'Uncle_Fu']})
    assert r.status_code == 200, r.text
    p = r.json()
    voices = [voice_of(p, s) for s in p['segments'] if s['speaker'] == '众人']
    assert len(voices) == 12 and set(voices) <= {'Vivian', 'Dylan', 'Uncle_Fu'} and len(set(voices)) == 3
    assert all(a != b for a, b in zip(voices, voices[1:]))                     # never the same voice twice running
    assert p['crowds'] == {'众人': {'pool': ['Vivian', 'Dylan', 'Uncle_Fu'], 'seed': 260909}}
    assert all(fingerprint(p, s, FixtureEngine()) != before[s['id']] for s in p['segments'] if s['speaker'] == '众人' and voice_of(p, s) != p['voices']['众人'])
    assert voice_of(p, p['segments'][-1]) == p['voices']['旁白']                # the narrator is untouched
    # The same seed draws the same voices; another seed draws differently.
    again = client.post(url + '/crowd', json={'revision': p['revision'], 'speaker': '众人', 'pool': ['Vivian', 'Dylan', 'Uncle_Fu']}).json()
    assert [voice_of(again, s) for s in again['segments']] == [voice_of(p, s) for s in p['segments']]
    other = client.post(url + '/crowd', json={'revision': again['revision'], 'speaker': '众人', 'pool': ['Vivian', 'Dylan', 'Uncle_Fu'], 'seed': 7}).json()
    assert [voice_of(other, s) for s in other['segments']] != [voice_of(p, s) for s in p['segments']]
    # One line can be given a voice by hand, and returned to its character's.
    line = other['segments'][0]
    one = client.patch(url, json={'revision': other['revision'], 'segment_id': line['id'], 'voice': 'Serena'}).json()
    assert voice_of(one, one['segments'][0]) == 'Serena'
    back = client.patch(url, json={'revision': one['revision'], 'segment_id': line['id'], 'voice': 'auto'}).json()
    assert voice_of(back, back['segments'][0]) == back['voices']['众人']
    assert client.post(url + '/crowd', json={'revision': back['revision'], 'speaker': '众人', 'pool': ['Nobody']}).status_code == 400


def test_voice_tags_are_kept_in_settings(client):
    r = client.post('/api/settings', json={'voice_tags': {'Uncle_Fu': ['老人', '男性', '威严'], 'Nobody': ['x'], 'Vivian': [' 女性 ', '']}})
    assert r.status_code == 200, r.text
    assert client.get('/api/settings').json()['voice_tags'] == {'Uncle_Fu': ['老人', '男性', '威严'], 'Vivian': ['女性']}


def test_a_new_character_can_be_named_on_a_line_after_the_project_exists(client):
    p = create(client, 'zh', script='旁白：他走了进来。\n小雪：谁？')
    url = '/api/projects/' + p['id']
    r = client.patch(url, json={'revision': p['revision'], 'segment_id': p['segments'][0]['id'], 'speaker': '王伯'})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p['segments'][0]['speaker'] == '王伯' and '王伯' in p['voices']
    assert p['voices']['王伯'] not in {p['voices']['旁白'], p['voices']['小雪']}      # a preset nobody else uses
    assert client.patch(url, json={'revision': p['revision'], 'segment_id': p['segments'][0]['id'], 'speaker': '王伯：'}).status_code == 400
