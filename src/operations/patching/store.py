"""Persistence for patch runs.

Patch runs are user-submitted mutations that must survive a provider rebuild,
so they follow the same store-handle pattern as risk exceptions rather than
being derived from a snapshot.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import PatchRun


@runtime_checkable
class PatchRunStore(Protocol):
    def add(self, run: PatchRun) -> None: ...

    def get(self, run_id: str) -> PatchRun | None: ...

    def list(self) -> list[PatchRun]: ...

    def update(self, run: PatchRun) -> None: ...


class InMemoryPatchRunStore:
    """Single-process store, sufficient for a local/development home."""

    def __init__(self, seed: Any = None) -> None:
        self._runs: dict[str, PatchRun] = {}
        for row in seed or []:
            run = row if isinstance(row, PatchRun) else PatchRun.from_mapping(dict(row))
            self._runs[run.run_id] = run

    def add(self, run: PatchRun) -> None:
        self._runs[run.run_id] = run

    def get(self, run_id: str) -> PatchRun | None:
        return self._runs.get(run_id)

    def list(self) -> list[PatchRun]:
        return sorted(
            self._runs.values(), key=lambda run: (run.created_at, run.run_id), reverse=True
        )

    def update(self, run: PatchRun) -> None:
        self._runs[run.run_id] = run
