"""Write reproducible test status and raw output. Astra, 2026-09-09."""
import json
import subprocess
import sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
result=subprocess.run([sys.executable,'-m','pytest','tests','-q'],cwd=root,text=True,capture_output=True)
payload={'suite':'local-preview-regression','engine':'deterministic audio/transcript/model-file fixtures, not real inference','exit_code':result.returncode,
         'output':(result.stdout+result.stderr).replace(str(root),'[project]'),
         'path_redaction':'Only the absolute project root is replaced with [project].',
         'judge':'pytest assertions; no human quality acceptance'}
(root/'results').mkdir(exist_ok=True)
(root/'results/workflow-checks.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False))
(root/'results/workflow-checks.md').write_text('# Workflow checks\n\nStatus: '+('PASS' if result.returncode==0 else 'FAIL')+'\n\nThese tests cover local workflow, startup and model preparation with fixtures; they are not a model benchmark or voice-quality assessment.\n\n```text\n'+payload['output']+'\n```\n\n最后更新：2026-09-09 · Astra\n')
print(payload['output']);sys.exit(result.returncode)
