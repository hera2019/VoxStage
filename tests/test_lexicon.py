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
        cfg = c.get('/api/config').json()
        assert cfg['preset_models'] == ['0.6B', '1.7B'] and cfg['default_preset_model'] == '1.7B'
        assert p['preset_model'] == '1.7B'                        # new projects start on the larger model
        large = {s['id']: fingerprint(p, s, eng) for s in p['segments']}
        p = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'preset_model': '0.6B'}).json()
        assert p['preset_model'] == '0.6B'                        # smaller machines can step down
        small = {s['id']: fingerprint(p, s, eng) for s in p['segments']}
        assert all(small[k] != large[k] for k in small)
        p = c.post('/api/projects/' + p['id'] + '/undo', json={'revision': p['revision']}).json()
        assert p['preset_model'] == '1.7B'
    class OneSize(TwoSizes):
        large_identity = None
    with TestClient(create_app(tmp_path / 'q', OneSize()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        p = c.post('/api/projects', json={'name': 'x', 'language': 'zh', 'script': '旁白：你好。'}).json()
        assert p['preset_model'] == '0.6B'                        # without the larger model, the default stays
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


def test_a_designed_voice_is_heard_first_and_then_kept_exactly_as_heard(tmp_path):
    import numpy as np, soundfile as sf
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from tests.test_workflow import HEADERS
    class Designs:
        ready = True; identity = 'x@1'; reference_ready = False; label = 'design'; design_ready = True; design_identity = 'design@1'
        def synthesize(self, *a, **k): raise AssertionError('not used')
        def design_voice(self, text, description, language, seed=260909):
            n = 24000 * 2
            tone = (0.2 * np.sin(np.arange(n) * 2 * np.pi * (330 if '老' in description else 660) / 24000)).astype('float32')
            return tone, 24000, {'load_seconds': 0, 'generation_seconds': 1.0, 'mlx_peak_memory_bytes': 0, 'seed': seed, 'generation_mode': 'voice_design', 'design_identity': 'design@1', 'description': description}
    with TestClient(create_app(tmp_path / 'p', Designs()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        assert c.get('/api/config').json()['design_ready'] is True
        r = c.post('/api/voices/design', json={'description': '一位老先生', 'text': '你好。', 'language': 'zh'})
        assert r.status_code == 200, r.text
        heard = c.get(r.json()['url']).content
        # Clicking again with the same words gives another voice, not the same file.
        again = c.post('/api/voices/design', json={'description': '一位老先生', 'text': '你好。', 'language': 'zh'}).json()
        assert again['seed'] != r.json()['seed'] and again['file'] != r.json()['file']
        # A seed can be asked for by number, which is how a version is reproduced.
        fixed = c.post('/api/voices/design', json={'description': '一位老先生', 'text': '你好。', 'language': 'zh', 'seed': r.json()['seed']}).json()
        assert fixed['file'] == r.json()['file']
        saved = c.post('/api/voices/custom', json={'name': '老先生', 'language': 'zh', 'reference_text': '你好。', 'from_design': r.json()['file']})
        assert saved.status_code == 200, saved.text
        entry = saved.json()
        assert entry['source'] == 'generated' and entry['synthetic_audio'] is True
        assert entry['derived_from'] == f"design:一位老先生 · seed {r.json()['seed']}"
        kept = c.get(f"/api/voices/custom/{entry['id']}/audio").content
        assert sf.read(__import__('io').BytesIO(kept))[0].shape == sf.read(__import__('io').BytesIO(heard))[0].shape
        # A vanished audition cannot be saved, and a made-up file name is refused.
        assert c.post('/api/voices/custom', json={'name': 'x', 'language': 'zh', 'reference_text': '你好。', 'from_design': 'design-0000000000000000.wav'}).status_code == 400
        assert c.post('/api/voices/custom', json={'name': 'x', 'language': 'zh', 'reference_text': '你好。', 'from_design': '../../etc/passwd'}).status_code == 400


def test_an_audition_uses_the_model_a_new_project_would(tmp_path):
    """Hearing a preset on 0.6B and then getting 1.7B in the project would make the audition a lie."""
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from tests.test_workflow import HEADERS
    heard = []
    class TwoSizes:
        ready = True; identity = 'small@1'; large_identity = 'large@1'; reference_ready = False; label = 'two sizes'
        def identity_for(self, size='0.6B'): return self.large_identity if size == '1.7B' else self.identity
        def synthesize(self, text, voice, language, seed=260909, size='0.6B'):
            import numpy as np
            heard.append(size)
            return np.zeros(2400, dtype='float32') + .1, 24000, {}
    with TestClient(create_app(tmp_path / 'p', TwoSizes()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        r = c.post('/api/voices/audition', json={'voice': 'Vivian', 'text': '雨点敲着窗。', 'language': 'zh'})
        assert r.status_code == 200 and r.json()['preset_model'] == '1.7B'
        assert heard == ['1.7B']


def test_a_new_project_clones_with_the_larger_base_where_it_is_installed(tmp_path):
    """本人 2026-09-17, after the blind listening (ai-lab 实测 21): a project made
    where the 1.7B Base is installed reads its fixed and designed voices with
    it; without it, 0.6B; an older project without the entry stays on 0.6B."""
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from runtime.core import Store
    from tests.test_workflow import HEADERS
    class Cloners:
        ready = True; identity = 'small@1'; large_identity = None; reference_ready = True; large_reference_ready = True; label = 'cloners'
        reference_identity = 'base@1'
        def reference_identity_for(self, size='0.6B'): return 'large-base@1' if size == '1.7B' else 'base@1'
        def synthesize(self, text, voice, language, seed=260909, size='0.6B'):
            import numpy as np
            return np.zeros(2400, dtype='float32') + .1, 24000, {'load_seconds': 0, 'generation_seconds': 0, 'mlx_peak_memory_bytes': 0, 'seed': seed, 'generation_parameters': {}}
    with TestClient(create_app(tmp_path / 'p', Cloners()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        assert c.get('/api/config').json()['default_clone_model'] == '1.7B'
        p = c.post('/api/projects', json={'name': 'x', 'language': 'zh', 'script': '旁白：你好。'}).json()
        assert p['clone_model'] == '1.7B'
        p = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'clone_model': '0.6B'}).json()
        assert p['clone_model'] == '0.6B'
    class Small(Cloners):
        large_reference_ready = False
    with TestClient(create_app(tmp_path / 'q', Small()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        assert c.get('/api/config').json()['default_clone_model'] == '0.6B'
        p = c.post('/api/projects', json={'name': 'x', 'language': 'zh', 'script': '旁白：你好。'}).json()
        assert p['clone_model'] == '0.6B'
        r = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'clone_model': '1.7B'})
        assert r.status_code == 400 and '未安装' in r.json()['detail']
    old = Store(tmp_path / 'p').create('old', '旁白：你好。', 'zh')          # a project from before the setting existed
    assert 'clone_model' not in old
