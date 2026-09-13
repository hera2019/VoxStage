"""Keeping a voice: the gate on supplied audio, and what must invalidate audio."""
import base64
import io
import json

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine

HEADERS = {'X-VoxStage': '1'}


class LongFixtureEngine(FixtureEngine):
    """The stock fixture returns 0.2 s, below the minimum a reference may be.

    Keeping a voice needs a sample long enough to be one, so this fixture speaks
    for a plausible length instead.
    """
    def synthesize(self, text, voice, language, seed=260909):
        rate = 24000
        t = np.arange(int(rate*3.0), dtype=np.float32)/rate
        return (0.2*np.sin(2*np.pi*200*t)).astype(np.float32), rate, {}

    def synthesize_reference(self, text, language, reference_path, reference_text, seed,
                             *, consent_confirmed=False, expected_sha256=None):
        if not consent_confirmed or not expected_sha256:
            raise ValueError('固定声线需要已确认的合成参考声音。')
        return self.synthesize(text, 'reference', language, seed)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/'projects', LongFixtureEngine()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        yield c


def wav_b64(seconds=3.0, rate=24000):
    t = np.arange(int(rate*seconds), dtype=np.float32)/rate
    pcm = (0.2*np.sin(2*np.pi*180*t)).astype(np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, pcm, rate, format='WAV', subtype='PCM_16')
    return base64.b64encode(buffer.getvalue()).decode()


# ── the gate ─────────────────────────────────────────────────────────────────

def test_supplied_audio_is_refused_without_confirmation(client):
    r = client.post('/api/voices/custom', json={
        'name': '我的声音', 'language': 'zh', 'reference_text': '雨点敲着窗。',
        'audio_base64': wav_b64(), 'consent_confirmed': False})
    assert r.status_code >= 400
    assert '授权' in r.json()['detail'], r.text
    assert client.get('/api/voices/custom').json() == [], '被拒绝的音色不应留下痕迹'


def test_supplied_audio_records_that_consent_was_given(client):
    entry = client.post('/api/voices/custom', json={
        'name': '我的声音', 'language': 'zh', 'reference_text': '雨点敲着窗。',
        'audio_base64': wav_b64(), 'consent_confirmed': True}).json()
    assert entry['source'] == 'provided' and entry['consent_confirmed'] is True
    assert entry['synthetic_audio'] is False, '真人录音不得标为合成'


def test_a_voice_kept_from_the_model_needs_no_consent_and_is_marked_synthetic(client):
    entry = client.post('/api/voices/custom', json={
        'name': '稳定旁白', 'language': 'zh', 'reference_text': '雨点敲着窗。',
        'from_voice': 'Vivian'}).json()
    assert entry['source'] == 'generated' and entry['synthetic_audio'] is True
    assert entry['derived_from'] == 'Vivian'


@pytest.mark.parametrize('seconds', [0.4, 90.0])
def test_references_outside_the_usable_length_are_refused(client, seconds):
    assert client.post('/api/voices/custom', json={
        'name': 'x', 'language': 'zh', 'reference_text': '短', 'consent_confirmed': True,
        'audio_base64': wav_b64(seconds)}).status_code >= 400


def test_one_source_at_a_time(client):
    assert client.post('/api/voices/custom', json={
        'name': 'x', 'language': 'zh', 'reference_text': '文本',
        'from_voice': 'Vivian', 'audio_base64': wav_b64()}).status_code >= 400


# ── what must invalidate generated audio ─────────────────────────────────────

def make_project(client):
    p = client.post('/api/projects', json={'name': 't', 'language': 'zh',
                                           'script': '旁白：雨点敲着窗。'}).json()
    client.post(f"/api/projects/{p['id']}/render/start", json={'revision': p['revision']})
    for _ in range(200):
        p = client.get(f"/api/projects/{p['id']}").json()
        if p['job']['status'] != 'running':
            return p
    raise AssertionError('渲染未结束')


def test_switching_a_character_to_a_library_voice_invalidates_its_audio(client):
    project = make_project(client)
    assert project['segments'][0]['status'] == 'ready'
    voice = client.post('/api/voices/custom', json={
        'name': '稳定旁白', 'language': 'zh', 'reference_text': '雨点敲着窗。',
        'from_voice': 'Vivian'}).json()
    after = client.patch(f"/api/projects/{project['id']}", json={
        'revision': project['revision'], 'speaker': '旁白',
        'voice': 'custom:' + voice['id']})
    assert after.status_code == 200, after.text
    assert after.json()['segments'][0]['status'] != 'ready', '换成参考音色后必须重新生成'


def test_a_voice_in_use_cannot_be_deleted(client):
    project = make_project(client)
    voice = client.post('/api/voices/custom', json={
        'name': '稳定旁白', 'language': 'zh', 'reference_text': '雨点敲着窗。',
        'from_voice': 'Vivian'}).json()
    client.patch(f"/api/projects/{project['id']}", json={
        'revision': project['revision'], 'speaker': '旁白', 'voice': 'custom:'+voice['id']})
    refused = client.delete(f"/api/voices/custom/{voice['id']}")
    assert refused.status_code >= 400 and '工程' in refused.json()['detail']
    assert client.get('/api/voices/custom').json(), '拒绝删除后音色仍应在'


def test_renaming_keeps_the_same_reference(client):
    voice = client.post('/api/voices/custom', json={
        'name': '旧名', 'language': 'zh', 'reference_text': '雨点敲着窗。',
        'from_voice': 'Vivian'}).json()
    renamed = client.patch(f"/api/voices/custom/{voice['id']}", json={'name': '新名'}).json()
    assert renamed['name'] == '新名' and renamed['sha256'] == voice['sha256']


def test_a_tampered_reference_is_detected(client, tmp_path):
    voice = client.post('/api/voices/custom', json={
        'name': '稳定旁白', 'language': 'zh', 'reference_text': '雨点敲着窗。',
        'from_voice': 'Vivian'}).json()
    path = tmp_path/'voices'/(voice['id']+'.wav')
    pcm, rate = sf.read(path, dtype='float32')
    sf.write(path, pcm*0.5, rate, subtype='PCM_16')
    assert client.get(f"/api/voices/custom/{voice['id']}/audio").status_code >= 400


@pytest.mark.parametrize('name', ['', 'a'*41, 'bad/name', 'line\nbreak'])
def test_unusable_names_are_refused(client, name):
    assert client.post('/api/voices/custom', json={
        'name': name, 'language': 'zh', 'reference_text': '文本',
        'from_voice': 'Vivian'}).status_code >= 400


def test_reference_audio_stays_out_of_version_control(client, tmp_path):
    client.post('/api/voices/custom', json={
        'name': '我的声音', 'language': 'zh', 'reference_text': '雨点敲着窗。',
        'audio_base64': wav_b64(), 'consent_confirmed': True})
    import subprocess
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    ignored = subprocess.run(['git', 'check-ignore', '-q', 'user-data/voices/x.wav'],
                             cwd=repo).returncode
    assert ignored == 0, 'user-data/voices 必须被忽略；参考声音不进版本库'


def test_audio_made_with_a_library_voice_is_recognised_as_ready(client):
    """Generation and display must compute the same fingerprint.

    They did not: only one side knew about the library, so freshly generated
    audio came back as still pending and would have been regenerated forever.
    """
    voice = client.post('/api/voices/custom', json={
        'name': '稳定旁白', 'language': 'zh', 'reference_text': '雨点敲着窗。',
        'from_voice': 'Vivian'}).json()
    p = client.post('/api/projects', json={'name': 't', 'language': 'zh',
                                           'script': '旁白：雨点敲着窗。'}).json()
    p = client.patch(f"/api/projects/{p['id']}", json={
        'revision': p['revision'], 'speaker': '旁白', 'voice': 'custom:'+voice['id']}).json()
    client.post(f"/api/projects/{p['id']}/render/start", json={'revision': p['revision']})
    for _ in range(200):
        p = client.get(f"/api/projects/{p['id']}").json()
        if p['job']['status'] != 'running':
            break
    assert p['segments'][0]['status'] == 'ready', p['segments'][0]
    assert client.get(f"/api/projects/{p['id']}").json()['segments'][0]['status'] == 'ready', \
        '重新载入后仍应是已生成，否则指纹每次都在变'


def test_each_audition_is_a_new_take_and_keeping_one_keeps_exactly_the_take_heard(client, tmp_path):
    """The kept reference must be the bytes the person chose among several, at
    the take's own speed — not a re-render on another seed or another model."""
    import io, soundfile as sf
    first = client.post('/api/voices/audition', json={'voice': 'Vivian', 'text': '雨点敲着窗。', 'language': 'zh'}).json()
    second = client.post('/api/voices/audition', json={'voice': 'Vivian', 'text': '雨点敲着窗。', 'language': 'zh'}).json()
    assert first['seed'] != second['seed'] and first['file'] != second['file']
    named = client.post('/api/voices/audition', json={'voice': 'Vivian', 'text': '雨点敲着窗。', 'language': 'zh', 'seed': first['seed']}).json()
    assert named['file'] == first['file']                                   # a seed reproduces a take
    # A faster listening copy is a separate file; the take itself is what 'file' names.
    fast = client.post('/api/voices/audition', json={'voice': 'Vivian', 'text': '雨点敲着窗。', 'language': 'zh', 'rate': 1.3, 'seed': first['seed']}).json()
    assert fast['file'] == first['file'] and fast['url'].endswith('x130.wav')
    heard = client.get('/api/voices/audition/' + first['file']).content
    entry = client.post('/api/voices/custom', json={'name': '挑中的一版', 'language': 'zh', 'reference_text': '雨点敲着窗。',
                                                    'from_audition': first['file']}).json()
    assert entry['source'] == 'generated' and entry['synthetic_audio'] is True
    assert entry['derived_from'] == f"Vivian · seed {first['seed']} · 0.6B"
    kept = client.get(f"/api/voices/custom/{entry['id']}/audio").content
    assert sf.read(io.BytesIO(kept))[0].tolist() == sf.read(io.BytesIO(heard))[0].tolist()
    assert client.post('/api/voices/custom', json={'name': 'x', 'language': 'zh', 'reference_text': '雨', 'from_audition': '0000000000000000.wav'}).status_code == 400
    assert client.post('/api/voices/custom', json={'name': 'x', 'language': 'zh', 'reference_text': '雨', 'from_audition': '../project.json'}).status_code == 400
