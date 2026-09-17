"""A pause where a line trails off: read in parts at …… / ——, joined with
silence (本人 2026-09-17, chosen by ear). Claude Hera, 2026-09-17."""
import numpy as np
from runtime.pauses import split_at_pauses, join_with_silence


def test_a_line_is_cut_after_its_ellipses_and_dashes_but_never_at_the_edges():
    assert split_at_pauses('“窃书不能算偸……窃书！……读书人的事，能算偸么？”') == ['“窃书不能算偸……', '窃书！……', '读书人的事，能算偸么？”']
    assert split_at_pauses('“跌断，跌，跌……”') == ['“跌断，跌，跌……”']                 # trails off at the end: whole
    assert split_at_pauses('“……你说什么？”') == ['“……你说什么？”']                     # opens with one: whole
    assert split_at_pauses('“一个……”“两个……”') == ['“一个……”', '“两个……”']            # the closing mark stays with its line
    assert split_at_pauses('他说：“好——好罢。”') == ['他说：“好——', '好罢。”']
    assert split_at_pauses('没有停顿的句子。') == ['没有停顿的句子。'] and split_at_pauses('……') == ['……']
    assert split_at_pauses('He paused... then spoke.') == ['He paused...', ' then spoke.']


def test_parts_are_joined_with_the_silence_asked_for():
    rate = 1000
    a = np.ones(300, dtype='float32'); b = np.ones(200, dtype='float32')
    pcm, silence = join_with_silence([(a, 50, 250), (b, 0, 200)], rate, 500, pad_ms=100)
    assert silence == 0.5 and len(pcm) == 100 + 200 + 500 + 200 + 100
    assert not pcm[300:800].any() and pcm[100:300].all() and pcm[800:1000].all()


def test_the_project_setting_reads_such_lines_in_parts_and_only_those_lines_change(tmp_path):
    from fastapi.testclient import TestClient
    from runtime.app import create_app
    from runtime.core import fingerprint
    from tests.test_workflow import HEADERS, wait
    class Counts:
        ready = True; identity = 'x@1'; reference_ready = False; label = 'counts'
        texts = []
        def synthesize(self, text, voice, language, seed=260909):
            self.texts.append(text)
            n = 24000
            return (0.2 * np.sin(np.arange(n) * 2 * np.pi * 440 / 24000)).astype('float32'), 24000, {'load_seconds': 0, 'generation_seconds': 1, 'mlx_peak_memory_bytes': 0, 'seed': seed, 'generation_parameters': {}}
    eng = Counts()
    with TestClient(create_app(tmp_path / 'p', eng, checker=type('C', (), {'ready': False, 'identity': 'x'})()), base_url='http://127.0.0.1', headers=HEADERS) as c:
        p = c.post('/api/projects', json={'name': 'x', 'language': 'zh', 'script': '孔乙己：窃书不能算偸……窃书！……读书人的事，能算偸么？\n旁白：他不回答。'}).json()
        assert p['ellipsis_pause_ms'] == 500                            # new projects pause a beat
        c.post('/api/projects/' + p['id'] + '/render/start', json={'revision': p['revision']})
        p = wait(c, p['id'])
        assert eng.texts == ['窃书不能算偸……', '窃书！……', '读书人的事，能算偸么？', '他不回答。']
        line = p['segments'][0]
        assert line['status'] == 'ready' and line['audio']['parts'] == 3 and line['audio']['pause_seconds'] == 1.0
        assert line['audio']['samples'] > 3 * 24000 + 24000                # three parts plus a second of silence (and pads)
        with_pause = {s['id']: fingerprint(p, s, eng) for s in p['segments']}
        p = c.patch('/api/projects/' + p['id'], json={'revision': p['revision'], 'ellipsis_pause_ms': 0}).json()
        without = {s['id']: fingerprint(p, s, eng) for s in p['segments']}
        first, second = p['segments'][0]['id'], p['segments'][1]['id']
        assert with_pause[first] != without[first] and with_pause[second] == without[second]   # only the line with a pause mark regenerates
        eng.texts.clear()
        c.post('/api/projects/' + p['id'] + '/render/start', json={'revision': p['revision']})
        p = wait(c, p['id'])
        assert eng.texts == ['窃书不能算偸……窃书！……读书人的事，能算偸么？']   # whole again; the narration was kept
