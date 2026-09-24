"""Startup recovery and service ownership checks. Astra, 2026-09-09."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from runtime import launcher


@pytest.fixture(autouse=True)
def chinese_terminal(monkeypatch):
    """These checks read the Chinese report; the English one is tested below."""
    monkeypatch.setenv('VOXSTAGE_LANG', 'zh')
from runtime.app import ROOT, create_app
from runtime.engines import FixtureEngine


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(launcher.platform, 'machine', lambda: 'arm64')
    page = tmp_path/'frontend/dist/index.html'
    page.parent.mkdir(parents=True)
    page.write_text('<html></html>')
    return tmp_path


def test_missing_optional_models_allow_editing(prepared):
    report = launcher.inspect_environment(prepared, dependency_probe=False)
    assert report['ready']
    assert {x['name'] for x in report['checks'] if x['status'] == 'warning'} == {
        '预设声音', '固定角色声线', '文字检查'}


def test_missing_page_blocks_startup(prepared):
    (prepared/'frontend/dist/index.html').unlink()
    report = launcher.inspect_environment(prepared, dependency_probe=False)
    assert not report['ready']
    assert next(x for x in report['checks'] if x['name'] == '网页')['status'] == 'error'


@pytest.mark.parametrize('relative', ['user-data/asr-settings.json',
                                     'user-data/models/qwen-customvoice/voxstage-model.json'])
def test_corrupt_configuration_is_actionable(prepared, relative):
    path = prepared/relative
    path.parent.mkdir(parents=True)
    path.write_text('{broken')
    report = launcher.inspect_environment(prepared, dependency_probe=False)
    assert not report['ready']
    assert any('损坏' in x['detail'] for x in report['checks'])
    assert path.read_text() == '{broken'  # No destructive repair.


def test_broken_recognition_paths_are_optional(prepared):
    folder = prepared/'user-data'
    folder.mkdir()
    (folder/'asr-settings.json').write_text(json.dumps({'cli':str(folder/'missing-cli'),
                                                       'model':str(folder/'missing-model')}))
    report = launcher.inspect_environment(prepared, dependency_probe=False)
    assert report['ready']
    assert next(x for x in report['checks'] if x['name'] == '文字检查')['status'] == 'warning'


def test_broken_dependency_is_reported_without_install(prepared, monkeypatch):
    probe = Mock(return_value=SimpleNamespace(returncode=1, stderr='ImportError: missing lib', stdout=''))
    monkeypatch.setattr(launcher.subprocess, 'run', probe)
    report = launcher.inspect_environment(prepared)
    assert not report['ready']
    assert 'missing lib' in next(x for x in report['checks'] if x['name'] == '运行依赖')['diagnostic']
    assert probe.call_count == 1
    assert probe.call_args.args[0][1] == '-c'


@pytest.fixture
def local_server():
    state = {'data': {}, 'code': 200}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == '/api/health'
            self.send_response(state['code'])
            self.end_headers()
            self.wfile.write(json.dumps(state['data']).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port, state
    server.shutdown()
    server.server_close()
    thread.join()


def test_service_identity_and_process_ownership(local_server, tmp_path):
    port, state = local_server
    state['data'] = {'app':'VoxStage', 'workspace_id':launcher.workspace_id(tmp_path), 'ready':True, 'pid':77}
    assert launcher.service_state(port, tmp_path) == 'ours'
    assert launcher.service_state(port, tmp_path, expected_pid=77) == 'ours'
    assert launcher.service_state(port, tmp_path, expected_pid=78) == 'occupied'
    assert launcher.service_state(port, tmp_path/'different-checkout') == 'occupied'
    state['data'] = {'name':'some other app'}
    assert launcher.service_state(port, tmp_path) == 'occupied'
    state['code'] = 302
    assert launcher.service_state(port, tmp_path) == 'occupied'


def test_health_endpoint_has_no_paths_and_rejects_cross_origin(tmp_path):
    checker = SimpleNamespace(ready=False, identity='test-unconfigured')
    with TestClient(create_app(tmp_path, FixtureEngine(), checker=checker),
                    base_url='http://127.0.0.1:8765') as client:
        data = client.get('/api/health').json()
        assert data == {'app':'VoxStage', 'workspace_id':launcher.workspace_id(ROOT), 'ready':True, 'pid':os.getpid()}
        assert str(ROOT) not in json.dumps(data)
        assert client.get('/api/health', headers={'Origin':'https://example.com'}).status_code == 403


@pytest.mark.parametrize('state,expected,opens', [('ours',0,1), ('occupied',1,0)])
def test_repeated_launch_never_starts_or_stops_another_process(tmp_path, monkeypatch, state, expected, opens):
    monkeypatch.setattr(launcher, 'service_state', lambda *a, **kw: state)
    inspect = Mock(side_effect=AssertionError('Should reuse before checking'))
    spawn = Mock(side_effect=AssertionError('Must not spawn'))
    stop = Mock(side_effect=AssertionError('Must not stop existing service'))
    opener = Mock()
    monkeypatch.setattr(launcher, 'inspect_environment', inspect)
    monkeypatch.setattr(launcher.subprocess, 'Popen', spawn)
    monkeypatch.setattr(launcher, 'stop_child', stop)
    monkeypatch.setattr(launcher, 'open_page', opener)
    assert launcher.launch(root=tmp_path) == expected
    assert opener.call_count == opens


def test_failed_preflight_never_starts_server(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, 'service_state', lambda *a, **kw: 'free')
    monkeypatch.setattr(launcher, 'inspect_environment', lambda *a: {'ready':False, 'checks':[]})
    spawn = Mock(side_effect=AssertionError('Must not spawn'))
    monkeypatch.setattr(launcher.subprocess, 'Popen', spawn)
    assert launcher.launch(root=tmp_path) == 1
    assert len(list((tmp_path/'user-data').glob('environment-check-*.json'))) == 1


def test_startup_timeout_stops_only_owned_child(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, 'service_state', lambda *a, **kw: 'free')
    monkeypatch.setattr(launcher, 'inspect_environment', lambda *a: {'ready':True, 'checks':[]})
    child = Mock()
    child.poll.return_value = None
    monkeypatch.setattr(launcher.subprocess, 'Popen', Mock(return_value=child))
    opener = Mock()
    monkeypatch.setattr(launcher, 'open_page', opener)
    assert launcher.launch(root=tmp_path, startup_timeout=0) == 1
    child.terminate.assert_called_once()
    child.wait.assert_called_once()
    opener.assert_not_called()


def test_keyboard_interrupt_cleans_up_owned_child(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, 'service_state', Mock(side_effect=['free','ours']))
    monkeypatch.setattr(launcher, 'inspect_environment', lambda *a: {'ready':True, 'checks':[]})
    child = Mock(pid=123)
    child.poll.return_value = None
    child.wait.side_effect = [KeyboardInterrupt, 0]
    monkeypatch.setattr(launcher.subprocess, 'Popen', Mock(return_value=child))
    monkeypatch.setattr(launcher, 'open_page', Mock())
    assert launcher.launch(root=tmp_path, browser=False) == 0
    child.terminate.assert_called_once()


def test_the_terminal_speaks_english_on_an_english_mac(monkeypatch, capsys):
    monkeypatch.setenv('VOXSTAGE_LANG', 'en')
    launcher.print_report({'checks': [{'name': '网页', 'status': 'error', 'detail': launcher.L('缺少网页文件。', 'The web page is missing.')}]})
    assert capsys.readouterr().out.strip() == '[must fix] Web page: The web page is missing.'
    monkeypatch.delenv('VOXSTAGE_LANG'); monkeypatch.setenv('LANG', 'zh_CN.UTF-8')
    assert not launcher.english()
    monkeypatch.setenv('LANG', 'en_GB.UTF-8')
    assert launcher.english()
