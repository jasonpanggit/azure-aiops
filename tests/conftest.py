"""Pytest configuration and fixtures."""

import sys
from pathlib import Path

import pytest


def pytest_addoption(parser):
    """Register optional CI partitioning without changing ordinary pytest runs."""
    group = parser.getgroup("ci sharding")
    group.addoption("--ci-shard-index", type=int, default=None)
    group.addoption("--ci-shard-count", type=int, default=None)


def pytest_configure(config):
    """Reject incomplete or invalid shard settings before collecting tests."""
    index = config.getoption("--ci-shard-index")
    count = config.getoption("--ci-shard-count")
    if index is None and count is None:
        return
    if index is None or count is None or count < 1 or not 0 <= index < count:
        raise pytest.UsageError(
            "--ci-shard-index and --ci-shard-count must both be provided, "
            "with count >= 1 and 0 <= index < count"
        )


def pytest_collection_modifyitems(config, items):
    """Partition collected cases exactly once, preserving each shard's order."""
    index = config.getoption("--ci-shard-index")
    count = config.getoption("--ci-shard-count")
    if index is None:
        return
    selected = [item for position, item in enumerate(items) if position % count == index]
    deselected = [item for position, item in enumerate(items) if position % count != index]
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected


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
