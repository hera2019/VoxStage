"""Hearing a voice before committing a character to it, and keeping favourites."""
import pytest
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.engines import FixtureEngine

HEADERS = {'X-VoxStage': '1'}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path/'projects', FixtureEngine()),
                    base_url='http://127.0.0.1', headers=HEADERS) as c:
        yield c


def test_a_voice_can_be_heard_without_creating_a_project(client, tmp_path):
    r = client.post('/api/voices/audition', json={'voice': 'Vivian', 'text': '雨点敲着窗。', 'language': 'zh'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['synthetic_audio'] is True and body['seconds'] > 0
    assert client.get(body['url']).status_code == 200
    assert not list((tmp_path/'projects').glob('*/project.json')), '试听不应建立工程'


def test_auditions_live_beside_the_projects_not_inside_them(client, tmp_path):
    client.post('/api/voices/audition', json={'voice': 'Ryan', 'text': 'Hello there.', 'language': 'en'})
    assert (tmp_path/'auditions').is_dir()
    assert not (tmp_path/'projects'/'auditions').exists(), '工程目录会被扫描，临时文件不能放进去'


def test_an_unknown_voice_is_refused(client):
    assert client.post('/api/voices/audition',
                       json={'voice': 'Nobody', 'text': 'x', 'language': 'zh'}).status_code >= 400


def test_a_bad_audition_filename_is_refused(client):
    assert client.get('/api/voices/audition/../../project.json').status_code >= 400
    assert client.get('/api/voices/audition/zzzz.wav').status_code >= 400


def test_favourites_survive_a_reload_and_reject_unknown_names(client):
    saved = client.post('/api/settings', json={'favourite_voices': ['Vivian', 'Nobody', 'Vivian']})
    assert saved.json()['favourite_voices'] == ['Vivian'], '未知音色应被丢弃，重复应去重'
    assert client.get('/api/settings').json()['favourite_voices'] == ['Vivian']


def test_settings_are_not_stored_where_projects_are_scanned(client, tmp_path):
    client.post('/api/settings', json={'favourite_voices': ['Ryan']})
    assert (tmp_path/'settings.json').is_file()
    assert not (tmp_path/'projects'/'settings.json').exists()


@pytest.mark.parametrize('rate', [0.4, 2.1])
def test_the_audition_rate_stays_within_the_supported_range(client, rate):
    assert client.post('/api/voices/audition',
                       json={'voice': 'Vivian', 'text': '测试', 'language': 'zh',
                             'rate': rate}).status_code >= 400
