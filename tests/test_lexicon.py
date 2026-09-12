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


def test_a_project_can_choose_the_larger_preset_model(tmp_path):
    """The choice feeds the fingerprint: preset-voice lines need regenerating,
    cloned-voice lines do not, and undo puts the audio back untouched."""
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from runtime.core import fingerprint
    from tests.test_workflow import HEADERS
    class TwoSizes:
        ready = True; identity = 'small@1'; large_identity = 'large@1'; reference_ready = False; label = 'two sizes'
        def identity_for(self, size='0.6B'): return self.large_identity if size == '1.7B' else self.identity
        def synthesize(self, text, voice, language, seed=260909, size='0.6B'):
            import numpy as np
            return np.zeros(2400, dtype='float32') + .1, 24000, {'size': size, 'load_seconds': 0, 'generation_seconds': 0, 'mlx_peak_memory_bytes': 0, 'seed': seed, 'generation_parameters': {}}
    eng = TwoSizes()
    with TestClient(create_app(tmp_path / 'p', eng), base_url='http://127.0.0.1', headers=HEADERS) as c:
        p = c.post('/api/projects', json={'name': 'x', 'language': 'zh', 'script': '旁白：你好世界。\n旁白：再见。'}).json()
        assert c.get('/api/config').json()['preset_models'] == ['0.6B', '1.7B']
        small = {s['id']: fingerprint(p, s, eng) for s in p['segments']}
        p = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'preset_model': '1.7B'}).json()
        assert p['preset_model'] == '1.7B'
        large = {s['id']: fingerprint(p, s, eng) for s in p['segments']}
        assert all(small[k] != large[k] for k in small)
        p = c.post('/api/projects/' + p['id'] + '/undo', json={'revision': p['revision']}).json()
        assert p.get('preset_model', '0.6B') == '0.6B'
    class OneSize(TwoSizes):
        large_identity = None
    with TestClient(create_app(tmp_path / 'q', OneSize()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        p = c.post('/api/projects', json={'name': 'x', 'language': 'zh', 'script': '旁白：你好。'}).json()
        r = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'preset_model': '1.7B'})
        assert r.status_code == 400 and '未安装' in r.json()['detail']


def test_a_run_away_take_is_retried_once_with_the_next_seed(tmp_path):
    """The engine reads the line and keeps going. The first take is never kept;
    the second is, whatever it sounds like, and the take counter records it."""
    import numpy as np
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from tests.test_workflow import HEADERS, wait
    class RunsAwayOnce:
        ready = True; identity = 'runaway@1'; reference_ready = False; label = 'runaway'
        calls = []
        def synthesize(self, text, voice, language, seed=260909):
            self.calls.append(seed)
            seconds = 60.0 if len(self.calls) == 1 else 2.0       # first take: a minute for a short line
            n = int(24000 * seconds)
            tone = (0.2 * np.sin(np.arange(n) * 2 * np.pi * 440 / 24000)).astype('float32')
            return tone, 24000, {'load_seconds': 0, 'generation_seconds': 0, 'mlx_peak_memory_bytes': 0, 'seed': seed, 'generation_parameters': {}}
    eng = RunsAwayOnce()
    with TestClient(create_app(tmp_path / 'p', eng, checker=type('C', (), {'ready': False, 'identity': 'x'})()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        p = c.post('/api/projects', json={'name': 'x', 'language': 'zh', 'script': '旁白：你一定又偷了人家的东西了。'}).json()
        c.post('/api/projects/' + p['id'] + '/render/start', json={'revision': p['revision']})
        p = wait(c, p['id'])
        s = p['segments'][0]
        assert eng.calls == [260909, 260910]                        # retried once, next seed
        assert s['status'] == 'ready' and s['take'] == 1
        assert s['audio']['auto_retake'] is True and s['audio']['first_take_seconds'] > 30
        assert s['audio']['samples'] == 24000 * 2                   # the second take is what was kept
