"""The chosen default must not overwrite a user's saved model preference."""
import json
from fastapi.testclient import TestClient
from runtime.app import create_app
from runtime.attribution import RoleDraftEngine
from runtime.engines import FixtureEngine


def test_default_uses_official_14b_without_inference():
    engine = RoleDraftEngine()
    assert engine.model_id == 'qwen3-14b-q4km'
    assert engine.sha256 == '500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0'


def test_saved_model_preference_survives_default_change(tmp_path):
    selected = 'qwen3-4b-instruct-2507-q8'
    (tmp_path/'settings.json').write_text(json.dumps({'role_model': selected}))
    with TestClient(create_app(tmp_path/'projects', FixtureEngine(), role_engine=RoleDraftEngine()), base_url='http://127.0.0.1') as client:
        assert client.get('/api/config').json()['role_model'] == selected
