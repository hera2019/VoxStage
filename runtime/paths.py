"""Writable data location, separate from bundled resources. GPT, 2026-09-30."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def data_dir(root=ROOT):
    """Environment override first; development defaults to <checkout>/user-data.

    Relative overrides are anchored to the checkout, independent of cwd. This
    function only resolves a path: it never creates or migrates user data.
    """
    root = Path(root)
    configured = os.environ.get('VOXSTAGE_DATA_DIR')
    if not configured:
        return root / 'user-data'
    path = Path(configured).expanduser()
    return (path if path.is_absolute() else root / path).resolve()
