# Workflow checks

Status: FAIL

These tests cover local workflow, startup and model preparation with fixtures; they are not a model benchmark or voice-quality assessment.

```text
..................................................F..................... [ 81%]
................                                                         [100%]
=================================== FAILURES ===================================
____________ test_local_tempo_save_preview_export_undo_and_new_take ____________

client = <starlette.testclient.TestClient object at 0x108f49d00>

    def test_local_tempo_save_preview_export_undo_and_new_take(client):
        c=client;p=generate(c,create(c,script='旁白：你好世界'))
        sid=p['segments'][0]['id'];url='/api/projects/'+p['id'];base=url+'/segments/'+sid
        root=c.app.state.store.directory(p['id']);fp=p['segments'][0]['audio']['fingerprint'];path=root/'audio'/(fp+'.wav');original=path.read_bytes()
        p=mark(c,p)
        p=c.patch(url,json={'revision':p['revision'],'speech_rate':1.2}).json()
        regions=[{'start':3.,'end':6.,'speed':1.5}]
        response=c.post(base+'/tempo',json={'revision':p['revision'],'regions':regions});assert response.status_code==200,response.text
        p=response.json();assert p['segments'][0]['tempo_status']=='current'
        assert p['segments'][0]['status']=='ready' and p['segments'][0]['listening_status']=='needs_listening'
        preview=c.post(base+'/preview',json={'revision':p['revision']}).json()
        assert [x['speed'] for x in preview['mapping']]==[1.2,1.5]  # absolute override, not 1.8
        assert abs(preview['duration']-(3/1.2+3/1.5))<.12
        links=c.post(url+'/export/create',json={'revision':p['revision']}).json()
        assert c.get(preview['url']).content==c.get(links['full.wav']).content
        timeline=c.get(links['timeline.json']).json()
        assert timeline['segments'][0]['tempo_mapping']==preview['mapping']
        report=c.get(links['content-check.json']).json()
        assert report['segments'][0]['tempo_status']=='current'
        assert 'rhythm_status' in report['segments'][0]
        assert path.read_bytes()==original
        p=c.post(url+'/undo',json={'revision':p['revision']}).json();assert p['segments'][0]['tempo_status']=='none'
        p=c.post(url+'/redo',json={'revision':p['revision']}).json();assert p['segments'][0]['tempo_status']=='current'
        p=generate(c,p,segment_id=sid,force=True);assert p['segments'][0]['tempo_status']=='stale'
        changed=c.post(base+'/preview',json={'revision':p['revision']}).json()
>       assert [x['speed'] for x in changed['mapping']]==[1.2]
E       assert [1.2, 1.5] == [1.2]
E         
E         Left contains one more item: 1.5
E         Use -v to get more diff

tests/test_timeline.py:89: AssertionError
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  [project]/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.12/site-packages/starlette/testclient.py:53
  [project]/.venv/lib/python3.12/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_timeline.py::test_local_tempo_save_preview_export_undo_and_new_take
1 failed, 87 passed, 2 warnings in 3.38s

```

最后更新：2026-09-09 · Astra
