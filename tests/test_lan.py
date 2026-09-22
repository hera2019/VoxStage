"""Reaching the service from another device on the same network (本人 2026-09-22):
off unless started with a key; with one, this Mac is unaffected and every other
address must sign in once. Claude Hera."""
from fastapi.testclient import TestClient

from runtime.app import create_app
from runtime.engines import FixtureEngine
from runtime import lan

HEADERS = {'x-voxstage': '1'}
ELSEWHERE = 'http://192.168.0.4:8765'


def test_without_a_key_another_address_is_refused(tmp_path):
    app = create_app(tmp_path / 'projects', FixtureEngine())
    with TestClient(app, base_url=ELSEWHERE, headers=HEADERS) as c:
        r = c.get('/api/health')
        assert r.status_code == 403 and r.json()['detail'] == 'Local access only'
    with TestClient(app, base_url='http://127.0.0.1:8765', headers=HEADERS) as c:
        assert c.get('/api/health').status_code == 200


def test_with_a_key_another_address_signs_in_once_and_then_works(tmp_path):
    app = create_app(tmp_path / 'projects', FixtureEngine(), lan_key='test-key-123')
    with TestClient(app, base_url='http://127.0.0.1:8765', headers=HEADERS) as c:
        assert c.get('/api/health').status_code == 200                      # this Mac never needs the key
    with TestClient(app, base_url=ELSEWHERE, headers=HEADERS) as c:
        r = c.get('/api/health')
        assert r.status_code == 401 and '口令' in r.json()['detail']
        page = c.get('/index.html')
        assert page.status_code == 401 and '访问口令' in page.text          # a page request gets the sign-in page
        assert c.get('/lan').status_code == 200
        bad = c.post('/lan', data={'key': 'wrong'})
        assert bad.status_code == 401 and '口令不对' in bad.text and not c.cookies.get(lan.COOKIE)
        ok = c.post('/lan', data={'key': 'test-key-123'}, follow_redirects=False)
        assert ok.status_code == 303 and ok.headers['location'] == '/'
        assert c.cookies.get(lan.COOKIE) == lan.cookie_value('test-key-123')
        assert c.get('/api/health').status_code == 200                      # signed in: the whole app, as on the Mac
        made = c.post('/api/projects', json={'name': '远程', 'language': 'zh', 'script': '旁白：雨停了。\n'})
        assert made.status_code == 200
        c.cookies.clear()
        assert c.get('/api/health').status_code == 401


def test_a_signed_in_device_still_needs_the_local_header_to_write(tmp_path):
    """The cookie says which device; the header is what keeps another page on
    that device from posting to the service."""
    app = create_app(tmp_path / 'projects', FixtureEngine(), lan_key='test-key-123')
    with TestClient(app, base_url=ELSEWHERE) as c:
        c.post('/lan', data={'key': 'test-key-123'}, follow_redirects=False)
        r = c.post('/api/projects', json={'name': '远程', 'language': 'zh', 'script': '旁白：雨停了。\n'})
        assert r.status_code == 403 and r.json()['detail'] == 'Missing local request header'
        r = c.post('/api/projects', json={'name': '远程', 'language': 'zh', 'script': '旁白：雨停了。\n'},
                   headers={**HEADERS, 'origin': 'http://evil.example'})
        assert r.status_code == 403 and r.json()['detail'] == 'Cross-origin access denied'


def test_the_key_is_kept_between_runs_and_can_be_replaced(tmp_path):
    first = lan.load_or_create_key(tmp_path)
    assert first and lan.load_or_create_key(tmp_path) == first
    assert (tmp_path / lan.KEY_FILE).stat().st_mode & 0o077 == 0             # nobody else on the machine reads it
    second = lan.load_or_create_key(tmp_path, new=True)
    assert second != first and lan.load_or_create_key(tmp_path) == second
    assert lan.accepts(lan.cookie_value(second), second) and not lan.accepts(lan.cookie_value(first), second)
    assert lan.is_loopback('127.0.0.1') and lan.is_loopback('localhost') and not lan.is_loopback('192.168.0.4')
