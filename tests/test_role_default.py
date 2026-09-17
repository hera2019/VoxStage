"""The chosen default must not overwrite a user's saved model preference."""
import json
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.attribution import RoleDraftEngine
from runtime.engines import FixtureEngine


def test_the_default_is_the_best_model_the_machine_holds_of_those_installed(monkeypatch):
    """本人 2026-09-17: 如果电脑配置够，30B 作默认. A machine starts on the first of
    30B-A3B, 14B, 4B that fits its memory and is installed; the 14B is the floor
    the constant names; a saved preference (below) wins over all of this."""
    from runtime import attribution as A
    monkeypatch.setattr(A, 'draft_limits', lambda: {'memory_gb': 32, 'chars': 6000, 'units': 280, 'context': 32768, 'max_tokens': 8192, 'segments': 1000})
    installed = {'qwen3-30b-a3b-instruct-2507-q4km', 'qwen3-14b-q4km', 'qwen3-4b-instruct-2507-q8'}
    monkeypatch.setattr(A.RoleDraftEngine, 'path_for', staticmethod(lambda m: A.ROLE_MODELS[m]['paths'][0] if m in installed else None))
    assert A.default_role_model() == 'qwen3-30b-a3b-instruct-2507-q4km'
    installed.discard('qwen3-30b-a3b-instruct-2507-q4km')
    assert A.default_role_model() == 'qwen3-14b-q4km'
    monkeypatch.setattr(A, 'draft_limits', lambda: {'memory_gb': 16, 'chars': 3000, 'units': 140, 'context': 16384, 'max_tokens': 4096, 'segments': 500})
    installed.add('qwen3-30b-a3b-instruct-2507-q4km')
    assert A.default_role_model() == 'qwen3-4b-instruct-2507-q8'         # 16 GB: neither large model fits
    installed.clear()
    assert A.default_role_model() == 'qwen3-14b-q4km'                    # nothing installed: the constant, whose file VOXSTAGE_ROLE_MODEL may name
    engine = RoleDraftEngine('qwen3-14b-q4km')
    assert engine.sha256 == '500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0'


def test_saved_model_preference_survives_default_change(tmp_path):
    selected = 'qwen3-4b-instruct-2507-q8'
    (tmp_path/'settings.json').write_text(json.dumps({'role_model': selected}))
    with TestClient(create_app(tmp_path/'projects', FixtureEngine(), role_engine=RoleDraftEngine()), base_url='http://127.0.0.1') as client:
        assert client.get('/api/config').json()['role_model'] == selected
