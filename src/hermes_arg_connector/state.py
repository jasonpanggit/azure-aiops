from __future__ import annotations

import json
from typing import Any

from storage.fs import resolve_fs


class StateStore:
    def __init__(self, root: str) -> None:
        self.fs, base = resolve_fs(str(root))
        self.path = f"{base}/state/state.json"

    def load(self) -> dict[str, Any]:
        if not self.fs.exists(self.path):
            return {}
        try:
            with self.fs.open(self.path, "rt") as handle:
                payload = json.loads(handle.read())
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def save(self, state: dict[str, Any]) -> None:
        content = json.dumps(state, indent=2, sort_keys=True) + "\n"
        parent = self.path.rsplit("/", 1)[0]
        self.fs.makedirs(parent, exist_ok=True)
        import uuid

        temporary = f"{parent}/.{self.path.rsplit('/', 1)[-1]}.{uuid.uuid4().hex}.tmp"
        with self.fs.open(temporary, "wt") as handle:
            handle.write(content)
        self.fs.mv(temporary, self.path)


def _atomic_text(path, content: str) -> None:
    """Local-disk atomic write helper, still used by callers that are
    guaranteed to operate on local paths only (e.g. the registry's file
    backend, run locks)."""
    import os
    import sys
    import uuid
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if sys.platform != "win32":
        path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
