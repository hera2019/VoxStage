"""Installer checks use tiny synthetic weights; no model/network/UI is opened."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from runtime import model_download as worker
from runtime.model_manager import ModelManager
from runtime.model_catalog import CATALOG, recommended

PAYLOAD = b'installer test weight\n'*100
SHA = hashlib.sha256(PAYLOAD).hexdigest()
REV = 'a'*40


@pytest.fixture
def tiny(monkeypatch):
    spec = dict(CATALOG['role-14b'], folder='tiny', repo='test/tiny', revision=REV,
                sha256={'tiny.gguf': SHA}, estimated_bytes=len(PAYLOAD))
    monkeypatch.setitem(CATALOG, 'role-14b', spec)
    return spec


class Hub:
    def __init__(self, payload=PAYLOAD):
        self.payload = payload
        self.calls = []

    def snapshot_download(self, **kw):
        self.calls.append(kw)
        return [SimpleNamespace(filename='tiny.gguf', commit_hash=REV,
                                file_size=len(self.payload), is_cached=False)]

    def hf_hub_url(self,repo,filename,**kw):
        return 'https://huggingface.co/test/tiny/resolve/'+REV+'/'+filename

    def get_hf_file_metadata(self,url,**kw):
        self.calls.append(dict(url=url,**kw))
        return SimpleNamespace(commit_hash=REV,size=len(self.payload),etag=SHA,location=url)

    def handler(self,request):
        start=int(request.headers.get('range','bytes=0-').split('=')[1].split('-')[0])
        return httpx.Response(206 if start else 200,
               headers={'Content-Range':f'bytes {start}-{len(self.payload)-1}/{len(self.payload)}'},
               content=self.payload[start:])


def run_install(kind,root,hub=None,**kwargs):
    hub=hub or Hub()
    with httpx.Client(transport=httpx.MockTransport(hub.handler)) as client:
        worker.install(kind,root,hub=hub,http_client=client,**kwargs)


def test_recommendation_and_offline_catalog(tmp_path):
    assert recommended(16) == ['preset', 'base', 'role-abliterated']
    assert 'role-30b-a3b' in recommended(32)
    assert 'preset-large' in recommended(31.9)
    assert 'role-30b-a3b' not in recommended(16)
    root=tmp_path/'not-created'
    result=ModelManager(root).snapshot(16)
    assert not root.exists()
    assert result['first_run'] and result['free_bytes'] > 0
    assert result['models'] and all(m['estimated_bytes'] for m in result['models'])
    assert ModelManager(root).snapshot(8)['below_minimum']


def test_install_checks_then_registers_without_loading(tmp_path, tiny):
    events=[];hub=Hub()
    run_install('role-14b',tmp_path,hub=hub,emit=lambda **v:events.append(v))
    assert (tmp_path/'models/tiny/tiny.gguf').read_bytes()==PAYLOAD
    assert events[-1]['status']=='ready'
    assert any(e['status']=='downloading' and e['completed']==len(PAYLOAD) for e in events)
    assert any(e['status']=='verifying' and e['completed']==len(PAYLOAD) for e in events)
    assert hub.calls[0]['revision']==REV and all(c['token'] is False for c in hub.calls)
    result=ModelManager(tmp_path).snapshot(32)
    assert next(m for m in result['models'] if m['id']=='role-14b')['verified']
    hub=Hub()
    run_install('role-14b',tmp_path,verify_only=True,hub=hub)
    assert not hub.calls


def test_corruption_is_not_registered_and_retry_repairs(tmp_path,tiny):
    with pytest.raises(ValueError,match='校验失败'):
        run_install('role-14b',tmp_path,hub=Hub(b'corrupt'))
    assert not (tmp_path/'model-installations/role-14b.json').exists()
    assert not (tmp_path/'models/tiny/tiny.gguf').exists()
    assert not (tmp_path/'model-downloads/role-14b/files/tiny.gguf').exists()
    run_install('role-14b',tmp_path,hub=Hub())
    file=tmp_path/'models/tiny/tiny.gguf'
    file.write_bytes(b'broken')
    assert not next(m for m in ModelManager(tmp_path).snapshot(32)['models'] if m['id']=='role-14b')['verified']
    with pytest.raises(ValueError,match='缺失或校验失败'):
        run_install('role-14b',tmp_path,verify_only=True,hub=Hub())


def test_insufficient_disk_and_unexpected_revision(tmp_path,tiny,monkeypatch):
    monkeypatch.setattr(worker.shutil,'disk_usage',lambda _:SimpleNamespace(free=1))
    with pytest.raises(ValueError,match='空间不足'):
        run_install('role-14b',tmp_path,hub=Hub())
    class WrongHub(Hub):
        def snapshot_download(self,**kw):
            return [SimpleNamespace(filename='tiny.gguf',commit_hash='b'*40,file_size=3,is_cached=False)]
    with pytest.raises(ValueError,match='版本不匹配'):
        run_install('role-14b',tmp_path,hub=WrongHub())


def test_metadata_sha_must_match_pinned_weight(tmp_path,tiny):
    class WrongHash(Hub):
        def get_hf_file_metadata(self,url,**kw):
            data=super().get_hf_file_metadata(url,**kw);data.etag='0'*64;return data
        def handler(self,request):
            raise AssertionError('Weight transfer must not start')
    with pytest.raises(ValueError,match='校验值不匹配'):
        run_install('role-14b',tmp_path,hub=WrongHash())


@pytest.mark.parametrize('name',['../outside','/outside','a\\b'])
def test_rejects_manifest_paths(tmp_path,tiny,name):
    class BadHub(Hub):
        def snapshot_download(self,**kw):
            return [SimpleNamespace(filename=name,commit_hash=REV,file_size=3,is_cached=False)]
    with pytest.raises(ValueError,match='列表无效'):
        run_install('role-14b',tmp_path,hub=BadHub())


@pytest.mark.parametrize('link_parent',[False,True])
def test_shared_links_are_read_only(tmp_path,tiny,link_parent):
    external=tmp_path/'external';external.mkdir()
    root=tmp_path/'data';root.mkdir()
    if link_parent:
        (root/'models').symlink_to(external,target_is_directory=True)
        (external/'tiny').mkdir()
    else:
        (root/'models').mkdir()
        (root/'models/tiny').symlink_to(external,target_is_directory=True)
    with pytest.raises(ValueError,match='共享模型'):
        run_install('role-14b',root,hub=Hub())
    folder=root/'models/tiny'
    (folder/'tiny.gguf').write_bytes(PAYLOAD)
    run_install('role-14b',root,verify_only=True)
    assert sorted(p.name for p in folder.iterdir())==['tiny.gguf']
    assert (root/'model-installations/role-14b.json').exists()


def test_shared_preset_requires_existing_matching_registration(tmp_path,tiny,monkeypatch):
    monkeypatch.setitem(CATALOG,'preset',tiny)
    root=tmp_path/'data';(root/'models').mkdir(parents=True)
    external=tmp_path/'external';external.mkdir();(external/'tiny.gguf').write_bytes(PAYLOAD)
    (root/'models/tiny').symlink_to(external,target_is_directory=True)
    with pytest.raises(ValueError,match='共享模型记录不匹配'):
        run_install('preset',root,verify_only=True)
    assert sorted(p.name for p in external.iterdir())==['tiny.gguf']
    assert not (root/'model-installations/preset.json').exists()
    (external/'voxstage-model.json').write_text(json.dumps({k:tiny[k] for k in ('repo','revision','sha256')}))
    run_install('preset',root,verify_only=True)
    assert (root/'model-installations/preset.json').exists()


def test_controlled_http_range_resume(tmp_path,tiny):
    partial=tmp_path/'model-downloads/role-14b/partials/tiny.gguf.part'
    partial.parent.mkdir(parents=True)
    offset=len(PAYLOAD)//2;partial.write_bytes(PAYLOAD[:offset])
    requests=[]
    class ResumingHub(Hub):
        def handler(self,request):
            requests.append(request)
            return super().handler(request)
    events=[]
    run_install('role-14b',tmp_path,hub=ResumingHub(),emit=lambda **v:events.append(v))
    assert any(r.headers.get('range')==f'bytes={offset}-' for r in requests)
    assert all('authorization' not in r.headers for r in requests)
    assert (tmp_path/'models/tiny/tiny.gguf').read_bytes()==PAYLOAD
    assert any(e['status']=='downloading' and e['completed']>=offset for e in events)
    assert not partial.exists()


def test_connection_drop_keeps_bytes_then_resumes(tmp_path):
    payload=b'x'*(2*1024*1024)
    expected=hashlib.sha256(payload).hexdigest()
    target=tmp_path/'file';partial=tmp_path/'file.part';requests=[]
    class Dropped(httpx.SyncByteStream):
        def __iter__(self):
            yield payload[:1024*1024]
            raise httpx.ReadError('simulated interruption')
    def dropping(request):return httpx.Response(200,stream=Dropped())
    with httpx.Client(transport=httpx.MockTransport(dropping)) as client:
        with pytest.raises(httpx.ReadError):
            worker.fetch_file(client,'https://huggingface.co/test',target,partial,len(payload),expected,lambda _:None)
    assert partial.stat().st_size==1024*1024 and not target.exists()
    def resumed(request):
        requests.append(request)
        return httpx.Response(206,headers={'Content-Range':f'bytes 1048576-{len(payload)-1}/{len(payload)}'},content=payload[1048576:])
    with httpx.Client(transport=httpx.MockTransport(resumed)) as client:
        worker.fetch_file(client,'https://huggingface.co/test',target,partial,len(payload),expected,lambda _:None)
    assert requests[0].headers['range']=='bytes=1048576-'
    assert target.read_bytes()==payload and not partial.exists()


@pytest.mark.parametrize('code,header',[(200,''),(206,'bytes 0-99/100')])
def test_range_ignored_or_wrong_response(tmp_path,code,header):
    partial=tmp_path/'partial';partial.write_bytes(PAYLOAD[:10]);target=tmp_path/'target'
    def handler(request):return httpx.Response(code,headers={'Content-Range':header},content=PAYLOAD)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        if code==200:
            worker.fetch_file(client,'https://huggingface.co/test',target,partial,len(PAYLOAD),SHA,lambda _:None)
            assert target.read_bytes()==PAYLOAD
        else:
            with pytest.raises(ValueError,match='续传响应不匹配'):
                worker.fetch_file(client,'https://huggingface.co/test',target,partial,len(PAYLOAD),SHA,lambda _:None)
            assert partial.read_bytes()==PAYLOAD[:10] and not target.exists()


class Process:
    def __init__(self):
        self.stdout=io.StringIO('{"status":"ready","completed":1,"total":1}\n')
    def wait(self,timeout=None):return 0


def test_download_env_separate_and_unknown_ids(tmp_path,monkeypatch):
    monkeypatch.setenv('HF_HUB_OFFLINE','1');monkeypatch.setenv('HF_TOKEN','secret-test')
    seen=[]
    def popen(command,**kw):seen.append((command,kw));return Process()
    manager=ModelManager(tmp_path,popen=popen)
    manager.start('preset');manager.thread.join(5)
    assert manager.process is None and manager.jobs['preset']['status']=='ready'
    assert seen[0][1]['env']['HF_HUB_OFFLINE']=='0'
    assert 'HF_TOKEN' not in seen[0][1]['env']
    assert seen[0][1]['env']['HF_HUB_DISABLE_TELEMETRY']=='1'
    assert os.environ['HF_HUB_OFFLINE']=='1'
    manager.start('preset',verify_only=True);manager.thread.join(5)
    assert seen[1][1]['env']['HF_HUB_OFFLINE']=='1'
    with pytest.raises(ValueError):manager.start('../../bad')


def test_pause_reaps_child_and_restores_job(tmp_path):
    child=None
    def popen(command,**kw):
        nonlocal child
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],
                               stdout=subprocess.PIPE,text=True)
        return child
    manager=ModelManager(tmp_path,popen=popen)
    manager.start('base')
    with pytest.raises(RuntimeError):manager.start('preset')
    manager.close()
    assert child.poll() is not None and manager.process is None
    assert manager.jobs['base']['status']=='paused'
    restored=ModelManager(tmp_path)
    assert restored.jobs['base']['status']=='paused'
    path=restored.state_path('base');path.write_text('{"status":"downloading","completed":5}')
    assert ModelManager(tmp_path).jobs['base']['status']=='paused'


def test_api_local_only_first_run_and_activation(tmp_path,monkeypatch):
    from runtime.app import create_app
    monkeypatch.setenv('VOXSTAGE_DATA_DIR',str(tmp_path))
    app=create_app(data_root=tmp_path/'projects')
    local=TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',12345))
    with local:
        result=local.get('/api/models');assert result.status_code==200
        assert result.json()['first_run']
        assert local.post('/api/models/preset/download').status_code==403
        assert local.post('/api/models/bad/download',headers={'X-VoxStage':'1'}).status_code==400
        before=local.get('/api/config').json()
        assert not before['ready']
        config=local.post('/api/models/activate',headers={'X-VoxStage':'1'})
        assert config.status_code==200 and not config.json()['ready']
        # Tiny files are enough to test metadata activation; synthesis is never invoked.
        folder=tmp_path/'models/qwen-customvoice';folder.mkdir(parents=True)
        (folder/'model.safetensors').write_bytes(PAYLOAD)
        (folder/'voxstage-model.json').write_text(json.dumps({'repo':'test/tiny','revision':REV}))
        activated=local.post('/api/models/activate',headers={'X-VoxStage':'1'})
        assert activated.status_code==200 and activated.json()['ready']
        assert app.state.engine.model is None
        assert local.get('/api/config').json()['engine_id']=='test/tiny@'+REV
        assert local.post('/api/models/pause',headers={'X-VoxStage':'1'}).status_code==200
        assert local.post('/api/models/activate',headers={'X-VoxStage':'1','Origin':'http://evil.test'}).status_code==403
        app.state.models.process=object()
        assert local.post('/api/models/activate',headers={'X-VoxStage':'1'}).status_code==409
        app.state.models.process=None
    with TestClient(app,base_url='http://127.0.0.1',client=('192.168.1.12',12345)) as remote:
        assert remote.get('/api/models',headers={'Host':'127.0.0.1'}).status_code==403
