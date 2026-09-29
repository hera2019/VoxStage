"""LAN HTTP has getRandomValues but may not expose crypto.randomUUID."""
from pathlib import Path
import subprocess


def test_browser_id_fallback_without_random_uuid(tmp_path):
    root = Path(__file__).resolve().parent.parent
    compiled = subprocess.run([
        str(root / 'frontend/node_modules/.bin/tsc'),
        str(root / 'frontend/src/localId.ts'), '--target', 'ES2022',
        '--lib', 'ES2022,DOM', '--module', 'commonjs', '--outDir', str(tmp_path),
        '--skipLibCheck',
    ], capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    script = """
      const assert = require('node:assert/strict');
      const {randomUuid} = require('./localId.js');
      let seed = 0;
      Object.defineProperty(globalThis, 'crypto', {configurable:true, value:{
        getRandomValues(bytes) { for (let i=0; i<bytes.length; i++) bytes[i] = seed++ & 255; return bytes; }
      }});
      const first = randomUuid(), second = randomUuid();
      assert.match(first, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
      assert.notEqual(first, second);
      assert.match(first.replaceAll('-', ''), /^[a-f0-9]{32}$/);
    """
    checked = subprocess.run(['node', '-e', script], cwd=tmp_path, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stdout + checked.stderr
