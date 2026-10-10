"""Configured storage and development compatibility. GPT, 2026-09-30.

Tiny fixtures only: no downloads, model loading, or existing user-data writes.
"""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from runtime import app, attribution, launcher, paths
from runtime.engines import FixtureEngine
from scripts import setup_model, setup_asr


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.setenv('VOXSTAGE_LANG', 'en')
    for key in ('VOXSTAGE_DATA_DIR', 'VOXSTAGE_MODEL', 'VOXSTAGE_ROLE_MODEL'):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize('value', [None, ''])
def test_development_default_is_unchanged_and_does_not_create(tmp_path, monkeypatch, value):
    if value is not None:
        monkeypatch.setenv('VOXSTAGE_DATA_DIR', value)
    assert paths.data_dir(tmp_path) == tmp_path/'user-data'
    assert not list(tmp_path.iterdir())
    assert launcher.workspace_id(tmp_path) == hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest()


def test_override_expands_home_and_relative_path_is_cwd_independent(tmp_path, monkeypatch):
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', '~/Library/Application Support/VoxStage')
    assert paths.data_dir(tmp_path) == Path.home()/'Library/Application Support/VoxStage'
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', 'writable data')
    monkeypatch.chdir(tmp_path.parent)
    assert paths.data_dir(tmp_path) == tmp_path/'writable data'
    assert not list(tmp_path.iterdir())


def test_configured_projects_settings_templates_and_voices_survive_restart(tmp_path, monkeypatch):
    data = tmp_path/'Application Support/VoxStage'
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', str(data))
    checker = SimpleNamespace(ready=False, identity='unconfigured')
    headers = {'X-VoxStage': '1'}
    pack = app.ROOT/'voicepack/default'
    # Use bundled resources but write only to the configured temporary folder.
    def fresh():
        return app.create_app(engine=FixtureEngine(), checker=checker, voicepack_dir=pack)
    first = fresh()
    assert first.state.store.root == data/'projects'
    with TestClient(first, base_url='http://127.0.0.1', headers=headers) as c:
        made = c.post('/api/projects', json={'name': 'Storage test', 'language': 'en',
                                           'script': 'Narrator: The rain stopped.'})
        assert made.status_code == 200, made.text
        pid = made.json()['id']
        result = c.post('/api/settings', json={'favourite_voices': ['Ryan']})
        assert result.status_code == 200, result.text
        template = c.post('/api/templates', json={'name': 'Test template', 'project_id': pid})
        assert template.status_code == 200, template.text
        voices = c.get('/api/voices/custom').json()
    assert (data/'projects'/pid/'project.json').is_file()
    assert (data/'settings.json').is_file()
    assert (data/'templates').is_dir() and (data/'books').is_dir()
    with TestClient(fresh(), base_url='http://127.0.0.1', headers=headers) as c:
        assert c.get('/api/projects/'+pid).json()['name'] == 'Storage test'
        assert c.get('/api/settings').json()['favourite_voices'] == ['Ryan']
        assert c.get('/api/templates').json()[0]['name'] == 'Test template'
        assert c.get('/api/voices/custom').json() == voices


def test_model_and_checker_defaults_and_explicit_overrides(tmp_path, monkeypatch):
    data = tmp_path/'configured'
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', str(data))
    engine = Mock(return_value=FixtureEngine())
    checker = Mock(return_value=SimpleNamespace(ready=False, identity='unconfigured'))
    monkeypatch.setattr(app, 'MlxEngine', engine)
    monkeypatch.setattr(app, 'WhisperChecker', checker)
    made = app.create_app(role_engine=SimpleNamespace(model_id=None))
    assert made.state.store.root == data/'projects'
    engine.assert_called_once_with(data/'models/qwen-customvoice')
    checker.assert_called_once_with(data/'asr-settings.json')
    engine.reset_mock()
    monkeypatch.setenv('VOXSTAGE_MODEL', str(tmp_path/'explicit-model'))
    made = app.create_app(tmp_path/'explicit-projects', role_engine=SimpleNamespace(model_id=None))
    assert made.state.store.root == tmp_path/'explicit-projects'
    engine.assert_called_once_with(str(tmp_path/'explicit-model'))


def test_role_models_follow_environment_even_after_import(tmp_path, monkeypatch):
    model_id = attribution.DEFAULT_ROLE_MODEL
    data = tmp_path/'configured'
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', str(data))
    model = data/attribution.ROLE_MODELS[model_id]['paths'][0]
    model.parent.mkdir(parents=True)
    model.write_bytes(b'fixture')
    assert attribution.RoleDraftEngine.path_for(model_id) == model
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', str(tmp_path/'other'))
    assert attribution.RoleDraftEngine.path_for(model_id) is None
    monkeypatch.setenv('VOXSTAGE_ROLE_MODEL', str(model))
    assert attribution.RoleDraftEngine.path_for(model_id) == model


def test_launcher_reports_logs_key_and_child_environment_use_override(tmp_path, monkeypatch):
    checkout = tmp_path/'readonly-checkout'
    data = tmp_path/'configured'
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', str(data))
    monkeypatch.setattr(launcher, 'service_state', lambda *a, **kw: 'free')
    monkeypatch.setattr(launcher, 'inspect_environment', lambda *a: {'ready': True, 'checks': []})
    spawn = Mock(return_value=Mock())
    monkeypatch.setattr(launcher.subprocess, 'Popen', spawn)
    assert launcher.launch(root=checkout, browser=False, startup_timeout=0) == 1
    assert list(data.glob('environment-check-*.json'))
    assert list((data/'logs').glob('startup-*.log'))
    assert spawn.call_args.kwargs['env']['VOXSTAGE_DATA_DIR'] == str(data)
    assert spawn.call_args.kwargs['env']['HF_HUB_OFFLINE'] == '1'
    monkeypatch.setattr(launcher, 'english', lambda: True)
    from runtime import lan
    monkeypatch.setattr(lan, 'addresses', lambda: [])
    launcher.print_lan(8765, checkout)
    key = data/'lan-key.txt'
    assert key.is_file() and key.stat().st_mode & 0o777 == 0o600
    assert not checkout.exists()
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', str(tmp_path/'other'))
    other_id = launcher.workspace_id(checkout)
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', str(data))
    assert launcher.workspace_id(checkout) != other_id


def test_launcher_preflight_reads_only_configured_settings(tmp_path, monkeypatch):
    data = tmp_path/'configured'
    data.mkdir()
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', str(data))
    (data/'asr-settings.json').write_text('{broken')
    model = data/'models/qwen-customvoice'
    model.mkdir(parents=True)
    (model/'voxstage-model.json').write_text('{broken')
    report = launcher.inspect_environment(tmp_path, dependency_probe=False)
    states = {item['name']: item['status'] for item in report['checks']}
    assert states['文字检查'] == 'error' and states['预设声音'] == 'error'


def test_model_setup_download_registry_and_cache_use_override(tmp_path, monkeypatch):
    data = tmp_path/'configured'
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', str(data))
    monkeypatch.setenv('HF_HOME', 'unused')  # Restore after this fixture mutates it.
    spec = {'folder': 'tiny', 'repo': 'fixture', 'revision': 'fixed',
            'sha256': {'model.safetensors': hashlib.sha256(b'weights').hexdigest()}}
    monkeypatch.setattr(setup_model, 'MODELS', {'preset': spec})
    monkeypatch.setattr(setup_model, 'REQUIRED', ['config.json'])
    def download(repo, **kwargs):
        folder = kwargs['local_dir']
        assert folder == data/'models/tiny' and kwargs['revision'] == 'fixed'
        folder.mkdir(parents=True)
        (folder/'model.safetensors').write_bytes(b'weights')
        (folder/'config.json').write_text('{}')
    assert setup_model.prepare('preset', tmp_path/'checkout', downloader=download)['ready']
    assert (data/'model-installations/preset.json').is_file()
    assert os.environ['HF_HOME'] == str(data/'hf-cache')
    assert not (tmp_path/'checkout').exists()


def test_asr_setup_config_and_provenance_use_override(tmp_path, monkeypatch):
    data = tmp_path/'configured'
    monkeypatch.setenv('VOXSTAGE_DATA_DIR', str(data))
    cli = tmp_path/'whisper-cli'
    cli.write_bytes(b'fixture cli')
    cli.chmod(0o700)
    model = data/'models/whisper'/setup_asr.NAME
    model.parent.mkdir(parents=True)
    model.write_bytes(b'fixture weights')
    monkeypatch.setattr(setup_asr, 'SHA', hashlib.sha256(model.read_bytes()).hexdigest())
    monkeypatch.setattr(setup_asr.sys, 'argv', ['setup_asr.py', '--cli', str(cli)])
    monkeypatch.setattr(setup_asr.subprocess, 'run', Mock(return_value=SimpleNamespace(returncode=0, stdout='fixture', stderr='')))
    setup_asr.main()
    assert Path(json.loads((data/'asr-settings.json').read_text())['model']) == model
    assert (model.parent/'provenance.json').is_file()
