"""Pytest configuration and fixtures."""

import sys
from pathlib import Path

# Put src/ at the FRONT of sys.path so the repo's own packages win.
#
# This is not merely convenience: the installed `openai-agents` distribution
# also provides a top-level `agents` package. If site-packages is searched
# first, `import agents.operations` resolves to that third-party package and
# fails, taking down collection for every test module that touches the API
# layer. Removing any existing entry before inserting guarantees priority
# even when something else has already appended src/ further down the path.
repo_root = Path(__file__).parent.parent
src_path = str(repo_root / "src")
while src_path in sys.path:
    sys.path.remove(src_path)
sys.path.insert(0, src_path)

# Several test modules share helpers via `from tests.foundry_test_fixtures import ...`.
# That absolute form only resolves if the repo root is importable, so add it too.
root_path = str(repo_root)
if root_path not in sys.path:
    sys.path.insert(1, root_path)
