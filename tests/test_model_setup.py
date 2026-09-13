"""Model preparation uses fixtures; no network or real weights. Astra, 2026-09-09."""
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from scripts import setup_model as setup


@pytest.fixture
def tiny(monkeypatch):
    spec={'folder':'test-model','repo':'fixture/model','revision':'pinned-test-revision',
          'sha256':{'model.safetensors':hashlib.sha256(b'valid weights').hexdigest()}}
    monkeypatch.setattr(setup,'MODELS',{'preset':spec,'base':spec})
    monkeypatch.setattr(setup,'REQUIRED',['config.json'])
    return spec


def place(root,spec,registered=False):
    folder=root/'user-data/models'/spec['folder'];folder.mkdir(parents=True)
    (folder/'config.json').write_text('{}')
    (folder/'model.safetensors').write_bytes(b'valid weights')
    if registered:
        (folder/'voxstage-model.json').write_text(json.dumps({k:spec[k] for k in ('repo','revision','sha256')}))
    return folder


def test_verify_only_never_downloads_or_writes(tmp_path,tiny):
    download=Mock(side_effect=AssertionError('Network forbidden'))
    result=setup.prepare('preset',tmp_path,verify_only=True,downloader=download)
    assert not result['ready'] and not list(tmp_path.iterdir())
    folder=place(tmp_path,tiny,registered=True)
    before={p:p.read_bytes() for p in folder.iterdir()}
    assert setup.prepare('preset',tmp_path,verify_only=True,downloader=download)['ready']
    assert all(p.read_bytes()==b for p,b in before.items())
    assert not (tmp_path/'user-data/model-installations').exists()


def test_existing_weights_reused_and_provenance_repaired(tmp_path,tiny):
    folder=place(tmp_path,tiny)
    download=Mock(side_effect=AssertionError('Network forbidden'))
    result=setup.prepare('preset',tmp_path,downloader=download)
    assert result['ready'] and not result['downloaded']
    assert json.loads((folder/'voxstage-model.json').read_text())['revision']==tiny['revision']
    assert (tmp_path/'user-data/model-installations/preset.json').is_file()


def test_download_is_pinned_and_registered_only_after_verification(tmp_path,tiny):
    def download(repo,**kwargs):
        assert repo==tiny['repo'] and kwargs['revision']==tiny['revision']
        assert kwargs['local_dir']==tmp_path/'user-data/models/test-model'
        place(tmp_path,tiny)
    result=setup.prepare('preset',tmp_path,downloader=download)
    assert result['ready'] and result['downloaded']


def test_bad_download_is_not_registered(tmp_path,tiny):
    def download(*args,**kwargs):
        folder=place(tmp_path,tiny)
        (folder/'model.safetensors').write_bytes(b'corrupt weights')
    with pytest.raises(ValueError,match='未通过校验'):
        setup.prepare('preset',tmp_path,downloader=download)
    assert not (tmp_path/'user-data/models/test-model/voxstage-model.json').exists()
    assert not (tmp_path/'user-data/model-installations').exists()


def test_shared_base_weights_are_not_modified(tmp_path,tiny):
    shared=tmp_path/'shared';folder=place(shared,tiny)
    root=tmp_path/'checkout';dest=root/'user-data/models/test-model';dest.parent.mkdir(parents=True)
    dest.symlink_to(folder,target_is_directory=True)
    before={p.name:p.read_bytes() for p in folder.iterdir()}
    assert setup.prepare('base',root,downloader=Mock())['ready']
    assert {p.name:p.read_bytes() for p in folder.iterdir()}==before
    assert dest.is_symlink()


def test_broken_shared_link_is_not_replaced(tmp_path,tiny):
    dest=tmp_path/'user-data/models/test-model';dest.parent.mkdir(parents=True)
    dest.symlink_to(tmp_path/'missing')
    download=Mock(side_effect=AssertionError('Network forbidden'))
    with pytest.raises(ValueError,match='共享模型链接'):
        setup.prepare('base',tmp_path,downloader=download)
    assert dest.is_symlink() and not (tmp_path/'missing').exists()


def test_fixed_model_pins_match_runtime():
    from runtime.engines import BASE_ID,BASE_SHA
    assert setup.MODELS['base']['repo']+'@'+setup.MODELS['base']['revision']==BASE_ID
    assert setup.MODELS['base']['sha256']==BASE_SHA


def test_corrupt_local_weights_request_fresh_download(tmp_path,tiny):
    folder=place(tmp_path,tiny)
    (folder/'model.safetensors').write_bytes(b'damaged local file')
    def download(repo,**kwargs):
        assert kwargs['force_download'] is True
        (folder/'model.safetensors').write_bytes(b'valid weights')
    assert setup.prepare('preset',tmp_path,downloader=download)['ready']


def test_the_real_engine_class_reports_what_is_installed(tmp_path):
    """Constructing MlxEngine must set every attribute the app reads, with or
    without the optional models. A structural slip once put half of __init__
    inside another method and only the live server noticed."""
    import json
    from runtime.engines import MlxEngine
    def fake(folder, repo):
        folder.mkdir(parents=True); (folder / 'model.safetensors').write_bytes(b'x')
        (folder / 'voxstage-model.json').write_text(json.dumps({'repo': repo, 'revision': 'r1', 'sha256': {}}))
    fake(tmp_path / 'qwen-customvoice', 'small')
    e = MlxEngine(tmp_path / 'qwen-customvoice')
    assert e.ready and e.identity == 'small@r1'
    assert e.large_identity is None and not e.design_ready and e.identity_for('1.7B') == 'small@r1'
    fake(tmp_path / 'qwen-customvoice-1.7b', 'large'); fake(tmp_path / 'qwen-voicedesign-1.7b', 'design')
    e = MlxEngine(tmp_path / 'qwen-customvoice')
    assert e.large_identity == 'large@r1' and e.identity_for('1.7B') == 'large@r1' and e.design_ready
