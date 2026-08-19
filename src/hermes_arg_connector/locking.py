from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Self


class RunLock:
    """Cross-process, non-blocking writer lock for one connector data root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "state" / "run.lock"
        self._handle = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if sys.platform != "win32":
            self.path.parent.chmod(0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        self._handle = os.fdopen(descriptor, "r+")
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._handle.close()
            self._handle = None
            raise RuntimeError(f"Azure Resource Graph ingestion is already running for {self.root}") from exc
        return self

    def __exit__(self, *_args) -> None:
        if self._handle is None:
            return
        if sys.platform == "win32":
            import msvcrt

            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None
