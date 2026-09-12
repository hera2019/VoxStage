"""A project-wide table of written form -> read-as form."""
from runtime.core import spoken_text, fingerprint
from tests.test_workflow import client, create, generate  # noqa: F401


def test_the_lexicon_rewrites_what_is_read_not_what_is_written():
    project = {'lexicon': {'偸': '偷', '儍': '傻', '偸儿': '小偷'}, 'voices': {'旁白': 'Vivian'}, 'language': 'zh'}
    seg = {'text': '你一定又偸了人家的东西了！那个偸儿。', 'spoken_as': '', 'speaker': '旁白'}
    assert spoken_text(project, seg) == '你一定又偷了人家的东西了！那个小偷。'   # longest entry first
    assert seg['text'].count('偸') == 2                                          # the line itself is untouched
    # A per-line replacement reading is still applied, and the lexicon on top of it.
    seg['spoken_as'] = '偸书不能算偸'
    assert spoken_text(project, seg) == '偷书不能算偷'


def test_changing_an_entry_invalidates_only_the_lines_it_touches(client):
    p = generate(client, create(client, 'zh'))
    base = '/api/projects/' + p['id']
    target = p['segments'][0]
    before = {s['id']: s['audio']['fingerprint'] for s in p['segments']}
    p = client.patch(base, json={'revision': p['revision'], 'lexicon': {target['text'][0]: '某'}}).json()
    assert p['lexicon'] == {target['text'][0]: '某'}
    touched = [s['id'] for s in p['segments'] if target['text'][0] in s['text']]
    for s in p['segments']:
        assert (s['status'] == 'pending') == (s['id'] in touched), s['text']
    # Undo puts every line back to ready without generating anything.
    p = client.post(base + '/undo', json={'revision': p['revision']}).json()
    assert all(s['status'] == 'ready' for s in p['segments'])
    assert {s['id']: s['audio']['fingerprint'] for s in p['segments']} == before


def test_the_lexicon_is_bounded_and_cleaned(client):
    p = create(client, 'zh')
    base = '/api/projects/' + p['id']
    p = client.patch(base, json={'revision': p['revision'], 'lexicon': {' 偸 ': ' 偷 ', '': '甲', '乙': '', '同': '同'}}).json()
    assert p['lexicon'] == {'偸': '偷'}
    r = client.patch(base, json={'revision': p['revision'], 'lexicon': {str(i): '甲' for i in range(201)}})
    assert r.status_code == 400 and '200' in r.json()['detail']
