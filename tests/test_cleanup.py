"""Leftovers in a project folder — takes of a voice since changed, audition
previews, old export batches, check work-dirs — counted and removed without
touching what the lines use (本人 2026-09-22). Claude Hera."""
import json
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine
from tests.test_workflow import create, generate, HEADERS


def test_cleanup_counts_and_removes_only_what_nothing_uses(tmp_path):
    with TestClient(create_app(tmp_path, FixtureEngine()), base_url='http://127.0.0.1:8765', headers=HEADERS) as c:
        p = generate(c, create(c, 'zh'))
        used = {s['audio']['fingerprint'] for s in p['segments'] if s.get('audio')}
        folder = tmp_path / p['id']
        # a changed voice leaves the old takes behind; previews, an old export batch, a check dir, a stray file
        (folder / 'audio' / 'deadbeef.wav').write_bytes(b'x' * 1000); (folder / 'audio' / 'deadbeef.json').write_text('{}')
        (folder / 'previews').mkdir(); (folder / 'previews' / 'a.wav').write_bytes(b'x' * 500)
        (folder / 'exports' / '3').mkdir(parents=True); (folder / 'exports' / '3' / 'full.wav').write_bytes(b'x' * 700)
        (folder / 'exports' / '9').mkdir(parents=True); (folder / 'exports' / '9' / 'full.wav').write_bytes(b'x' * 800)
        (folder / 'checks' / 'abc').mkdir(parents=True); (folder / 'checks' / 'abc' / 'input.wav').write_bytes(b'x' * 300)
        (folder / 'project.json.before-repair').write_text('{}')
        plan = c.get('/api/projects/' + p['id'] + '/cleanup').json()
        assert plan['audio']['files'] == 2 and plan['previews']['files'] == 1 and plan['exports'] == {'files': 1, 'bytes': 700, 'keeps': 9}
        assert plan['checks']['files'] == 1 and plan['stray']['files'] == 1 and plan['total_bytes'] == 1000 + 2 + 500 + 700 + 300 + 2
        r = c.post('/api/projects/' + p['id'] + '/cleanup', json={'revision': p['revision']}).json()
        assert r['freed_bytes'] == plan['total_bytes'] and r['undo_cleared'] is False
        left = {f.name.split('.')[0] for f in (folder / 'audio').iterdir()}
        assert left == used and not (folder / 'previews').exists() and (folder / 'exports' / '9' / 'full.wav').exists() and not (folder / 'exports' / '3').exists()
        assert not (folder / 'checks').exists() and not (folder / 'project.json.before-repair').exists()
        assert c.get('/api/projects/' + p['id'] + '/cleanup').json()['total_bytes'] == 0
        assert all(s['status'] == 'ready' for s in c.get('/api/projects/' + p['id']).json()['segments'])   # the lines' own audio untouched


def test_takes_only_undo_points_at_go_with_include_undo_and_the_stack_is_cleared(tmp_path):
    with TestClient(create_app(tmp_path, FixtureEngine()), base_url='http://127.0.0.1:8765', headers=HEADERS) as c:
        p = generate(c, create(c, 'zh'))
        first = p['segments'][0]
        old = first['audio']['fingerprint']
        p = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'segment_id': first['id'], 'text': first['text'] + '呀'}).json()
        p = generate(c, p)
        plan = c.get('/api/projects/' + p['id'] + '/cleanup').json()
        assert plan['undo_audio']['files'] == 2 and plan['audio']['files'] == 0        # the old take: undo still points at it
        r = c.post('/api/projects/' + p['id'] + '/cleanup', json={'revision': p['revision']}).json()
        assert r['freed_bytes'] == 0 and (tmp_path / p['id'] / 'audio' / (old + '.wav')).exists()
        r = c.post('/api/projects/' + p['id'] + '/cleanup', json={'revision': p['revision'], 'include_undo': True}).json()
        assert r['undo_cleared'] is True and not (tmp_path / p['id'] / 'audio' / (old + '.wav')).exists()
        q = c.get('/api/projects/' + p['id']).json()
        assert q['revision'] == r['revision'] and not q['can_undo'] and all(s['status'] == 'ready' for s in q['segments'])


def test_a_chorus_reads_a_line_with_the_whole_pool_at_once_as_one_asset(tmp_path):
    """本人 2026-09-22: 群口 — several voices saying one line together, unlike a
    crowd that draws one voice a line. The line's voice names the pool, the
    takes are mixed with small offsets into one asset, and the mix peaks like
    a single voice."""
    import numpy as np, soundfile as sf
    from runtime.chorus import mix, chorus_voice, chorus_pool, is_chorus
    a = (np.r_[np.zeros(100), np.full(1000, .5, dtype=np.float32)], 24000, {'x': 1})
    b = (np.r_[np.zeros(100), np.full(500, .5, dtype=np.float32)], 24000, {'x': 2})
    pcm, rate, metrics = mix([a, b])
    assert rate == 24000 and len(pcm) == max(1100, 600 + int(24000 * .035))     # the second voice starts 35 ms later
    assert abs(float(np.max(np.abs(pcm))) - .5) < 1e-5 and metrics == {'x': 1, 'chorus_voices': 2, 'chorus_mode': 'loose'}
    assert is_chorus(chorus_voice(['Vivian', 'Dylan'])) and chorus_pool('chorus:Vivian+Dylan') == ['Vivian', 'Dylan']
    # 本人 2026-09-22: tight — an answered order, 万岁 in unison: each take cut to its onset, all on the same beat
    from runtime.chorus import chorus_mode
    late = (np.r_[np.zeros(2400), np.full(500, .5, dtype=np.float32)], 24000, {})
    pcm, _, m = mix([a, late], 'tight')
    assert m['chorus_mode'] == 'tight' and len(pcm) < 1100 + 2400 and int(np.flatnonzero(np.abs(pcm) > 0)[0]) <= 100 + 15 * 24
    tight = chorus_voice(['Vivian', 'Dylan'], 'tight')
    assert tight == 'chorus:tight/Vivian+Dylan' and chorus_mode(tight) == 'tight' and chorus_pool(tight) == ['Vivian', 'Dylan'] and chorus_mode('chorus:Vivian+Dylan') == 'loose'
    with TestClient(create_app(tmp_path, FixtureEngine()), base_url='http://127.0.0.1:8765', headers=HEADERS) as c:
        p = create(c, 'zh')
        speaker = p['segments'][0]['speaker']
        p = c.post('/api/projects/' + p['id'] + '/crowd', json={'revision': p['revision'], 'speaker': speaker, 'pool': ['Vivian', 'Dylan', 'Serena'], 'together': True}).json()
        assert p['crowds'][speaker] == {'pool': ['Vivian', 'Dylan', 'Serena'], 'seed': 260909, 'together': True, 'sync': 'loose', 'layers': 1}
        assert all(s['voice'] == 'chorus:Vivian+Dylan+Serena' for s in p['segments'] if s['speaker'] == speaker)
        p = generate(c, p)
        line = next(s for s in p['segments'] if s['speaker'] == speaker)
        assert line['status'] == 'ready'
        info = sf.info(tmp_path / p['id'] / 'audio' / (line['audio']['fingerprint'] + '.wav'))
        single = next(s for s in p['segments'] if s['speaker'] != speaker)
        solo = sf.info(tmp_path / p['id'] / 'audio' / (single['audio']['fingerprint'] + '.wav'))
        assert info.frames > solo.frames                      # two extra voices start 35 ms later each: longer than one voice's take


def test_a_lines_tone_reaches_the_preset_engine_and_the_fingerprint_but_not_a_cloned_voice(tmp_path):
    """本人 2026-09-22: 语气 — a free-text instruction per line for the preset
    models (实测 2: effective, run-aways caught by the duration check). Setting
    it changes the take; clearing it returns to the plain take; a cloned voice
    ignores it, so its take is unchanged."""
    from runtime.core import fingerprint
    class Listening(FixtureEngine):
        identity_for = lambda self, size='0.6B': 'fixture-' + size
        seen = []
        def synthesize(self, text, voice, language, seed=260909, size='0.6B', instruct=None):
            self.seen.append(instruct); return FixtureEngine.synthesize(self, text, voice, language, seed)
    engine = Listening()
    with TestClient(create_app(tmp_path, engine), base_url='http://127.0.0.1:8765', headers=HEADERS) as c:
        p = generate(c, create(c, 'zh'))
        line = p['segments'][0]; plain = line['audio']['fingerprint']
        q = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'segment_id': line['id'], 'tone': '愤怒，语速快'}).json()
        assert q['segments'][0]['tone'] == '愤怒，语速快' and q['segments'][0]['status'] == 'pending'
        q = generate(c, q)
        assert q['segments'][0]['audio']['fingerprint'] != plain and engine.seen[-1] == '愤怒，语速快'
        q = c.patch('/api/projects/' + p['id'], json={'revision': q['revision'], 'segment_id': line['id'], 'tone': ''}).json()
        assert 'tone' not in q['segments'][0] and q['segments'][0]['status'] == 'pending'
        assert generate(c, q)['segments'][0]['audio']['fingerprint'] == plain                   # the plain take comes back from the cache
        raw = json.loads((tmp_path / p['id'] / 'project.json').read_text())
        seg = raw['segments'][0]; seg['tone'] = '低声'
        assert fingerprint(raw, seg, engine) != fingerprint({**raw}, {**seg, 'tone': ''}, engine)
        raw['voice_profiles'] = {seg['speaker']: {'sha256': 'a' * 64, 'text': 'x', 'synthetic_audio': True, 'consent_confirmed': True}}
        assert fingerprint(raw, seg, engine) == fingerprint(raw, {**seg, 'tone': ''}, engine)     # a fixed voice: the tone is not in the take


def test_one_voice_layered_is_a_chorus_of_its_own_takes(tmp_path):
    """本人 2026-09-22: 同一个声音多次叠加 — one voice read three times with
    different seeds and layered; a pool of one with one layer is refused."""
    class Seeds(FixtureEngine):
        seen = []
        def synthesize(self, text, voice, language, seed=260909):
            self.seen.append((voice, seed)); return FixtureEngine.synthesize(self, text, voice, language, seed)
    engine = Seeds()
    with TestClient(create_app(tmp_path, engine), base_url='http://127.0.0.1:8765', headers=HEADERS) as c:
        p = create(c, 'zh'); speaker = p['segments'][0]['speaker']
        bad = c.post('/api/projects/' + p['id'] + '/crowd', json={'revision': p['revision'], 'speaker': speaker, 'pool': ['Vivian'], 'together': True})
        assert bad.status_code == 400
        p = c.post('/api/projects/' + p['id'] + '/crowd', json={'revision': p['revision'], 'speaker': speaker, 'pool': ['Vivian'], 'together': True, 'layers': 3}).json()
        assert p['crowds'][speaker]['layers'] == 3 and all(s['voice'] == 'chorus:x3/Vivian' for s in p['segments'] if s['speaker'] == speaker)
        engine.seen.clear(); p = generate(c, p)
        line = next(s for s in p['segments'] if s['speaker'] == speaker)
        assert line['status'] == 'ready'
        seeds = [sd for v, sd in engine.seen if v == 'Vivian']
        assert len(set(seeds)) >= 3 and len(seeds) % 3 == 0                # three different seeds a line


def test_tight_one_voice_layers_keep_every_syllable_on_one_timeline(tmp_path):
    import numpy as np
    from runtime.chorus import _pitch_shift_same_length, synchronized_layers
    from runtime.core import fingerprint

    rate = 24000
    source = np.zeros(rate * 2, dtype=np.float32)
    for second in (.1, .42, .81, 1.31):
        start = round(second * rate)
        t = np.arange(rate // 25) / rate
        source[start:start + len(t)] = .4 * np.sin(2 * np.pi * 190 * t)
    mixed, actual_rate, metrics = synchronized_layers((source, rate, {'seed': 1}), 4)
    assert actual_rate == rate and metrics['chorus_voices'] == 4
    assert metrics['chorus_alignment'] == 'shared-take-v2' and metrics['chorus_synthesis_takes'] == 1
    assert len(mixed) - len(source) < rate * .01
    assert np.isfinite(mixed).all() and np.max(np.abs(mixed)) <= .401
    # Every word stays near the source's time, including the last one.
    for second in (.1, .42, .81, 1.31):
        center = round((second - .1 + .015) * rate)
        assert np.max(np.abs(mixed[center:center + rate // 13])) > .15
    assert not np.array_equal(mixed[:len(source)], source)
    steady = np.sin(2 * np.pi * 220 * np.arange(rate * 2) / rate).astype(np.float32)
    lowered = _pitch_shift_same_length(steady, rate, -.7)
    assert len(lowered) == len(steady)
    center = lowered[rate // 2:rate * 3 // 2]
    spectrum = np.abs(np.fft.rfft(center))
    frequency = np.fft.rfftfreq(len(center), 1 / rate)[np.argmax(spectrum)]
    assert abs(frequency - 220 * 2 ** (-.7 / 12)) < 2

    class Counting(FixtureEngine):
        calls = []
        def synthesize(self, text, voice, language, seed=260909):
            self.calls.append((text, voice, seed))
            return super().synthesize(text, voice, language, seed)

    engine = Counting()
    with TestClient(create_app(tmp_path, engine), base_url='http://127.0.0.1:8765', headers=HEADERS) as c:
        p = create(c, 'zh')
        speaker = p['segments'][0]['speaker']
        p = c.post('/api/projects/' + p['id'] + '/crowd', json={
            'revision': p['revision'], 'speaker': speaker, 'pool': ['Vivian'],
            'together': True, 'sync': 'tight', 'layers': 4,
        }).json()
        line = next(s for s in p['segments'] if s['speaker'] == speaker)
        assert fingerprint(p, line, engine) != fingerprint(p, {**line, 'voice': 'chorus:x4/Vivian'}, engine)
        from unittest.mock import patch
        with patch('runtime.chorus.SHARED_TAKE_VERSION', 'previous-algorithm'):
            previous = fingerprint(p, line, engine)
        assert fingerprint(p, line, engine) != previous   # an old cached mix becomes pending
        p = generate(c, p)
        line = next(s for s in p['segments'] if s['id'] == line['id'])
        assert line['audio']['chorus_alignment'] == 'shared-take-v2'
        assert line['audio']['chorus_synthesis_takes'] == 1
        assert len([call for call in engine.calls if call[0] == line['text']]) == 1
