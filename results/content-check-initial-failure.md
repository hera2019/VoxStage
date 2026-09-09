# Workflow checks

Status: FAIL

These tests use deterministic tones, not a model benchmark or voice-quality assessment.

```text
......................F...                                               [100%]
=================================== FAILURES ===================================
_ test_content_differences_keep_meaningful_words_and_numbers[\u589e\u957f10%\u3002-\u589e\u957f10\u3002-zh-False] _

expected = '增长10%。', actual = '增长10。', language = 'zh', matched = False

    @pytest.mark.parametrize('expected,actual,language,matched',[
        ('Hello, WORLD!','hello world','en',True),
        ("I can't go.",'I can go.','en',False),
        ('I am not ready.','I am ready.','en',False),
        ('There are 12.5 cups.','There are 125 cups.','en',False),
        ('Go home.','Go home now.','en',False),
        ('雨点轻轻敲着窗。','雨点轻轻敲着窗','zh',True),
        ('不是风。','是风。','zh',False),
        ('一共12.5元。','一共125元。','zh',False),
        ('增长10%。','增长10。','zh',False),
        ('Hello.','','en',False)])
    def test_content_differences_keep_meaningful_words_and_numbers(expected,actual,language,matched):
        from runtime.content_check import compare_text
        result=compare_text(expected,actual,language)
>       assert (result['status']=='match')==matched
E       AssertionError: assert ('match' == 'match'
E         
E           match) == False

tests/test_workflow.py:278: AssertionError
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  [project]/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv/lib/python3.12/site-packages/starlette/testclient.py:53
  [project]/.venv/lib/python3.12/site-packages/starlette/testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_workflow.py::test_content_differences_keep_meaningful_words_and_numbers[\u589e\u957f10%\u3002-\u589e\u957f10\u3002-zh-False]
1 failed, 25 passed, 2 warnings in 1.08s

```

最后更新：2026-09-09 · Astra
