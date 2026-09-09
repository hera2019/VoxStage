# Workflow checks

Status: FAIL

These tests cover local workflow, startup and model preparation with fixtures; they are not a model benchmark or voice-quality assessment.

```text
............F........................................................... [ 62%]
............................................                             [100%]
=================================== FAILURES ===================================
_________ test_duplicate_retains_audio_settings_and_independent_edits __________

client = <starlette.testclient.TestClient object at 0x108665bb0>

    def test_duplicate_retains_audio_settings_and_independent_edits(client):
        p=generate(client,create(client));url='/api/projects/'+p['id'];s=p['segments'][0]
        p=client.post(url+'/voice/fix',json={'revision':p['revision'],'segment_id':s['id']}).json()
>       store=client.app.state.store;source=store.directory(p['id']);snapshot=(source/'project.json').read_bytes()
                                                            ^^^^^^^
E       KeyError: 'id'

tests/test_duplicate.py:10: KeyError
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  [project]/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.12/site-packages/starlette/testclient.py:53
  [project]/.venv/lib/python3.12/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_duplicate.py::test_duplicate_retains_audio_settings_and_independent_edits
1 failed, 115 passed, 2 warnings in 7.23s

```

最后更新：2026-09-09 · Astra
