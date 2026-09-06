"""Contracts for restart-safe, proposal-only ontology discovery.

The coordinator intentionally depends on a single ``RunProcessor`` protocol.
The narrower protocols below describe future evidence, curator, policy,
validation, publication-status, and evaluation seams without granting the
coordinator a Fabric stage or active-pointer mutation primitive.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class CheckpointResult:
    """One durable result returned by a bounded processor invocation."""

    checkpoint: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    complete: bool = False

    def __post_init__(self) -> None:
        if not self.checkpoint.strip():
            raise ValueError("checkpoint must not be empty")


class RunProcessor(Protocol):
    """Advance one claimed run without owning scheduling or persistence."""

    async def advance(self, run: Mapping[str, Any]) -> CheckpointResult: ...


class EvidenceProvider(Protocol):
    """Return bounded, server-scoped evidence for a durable run."""

    async def collect(self, run: Mapping[str, Any]) -> Mapping[str, Any]: ...


class Curator(Protocol):
    """Produce advisory proposals only; no publication operation is exposed."""

    async def propose(
        self, run: Mapping[str, Any], evidence: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


class PolicyEvaluator(Protocol):
    """Evaluate proposals under server-owned policy."""

    async def evaluate(
        self, run: Mapping[str, Any], proposals: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


class CandidateValidator(Protocol):
    """Validate a candidate snapshot without making it visible."""

    async def validate(
        self, run: Mapping[str, Any], candidate: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


class Publisher(Protocol):
    """Read the separately-authorized publisher's durable status only."""

    async def publication_status(self, run_id: str) -> Mapping[str, Any]: ...


class EvaluationSnapshotProvider(Protocol):
    """Capture an immutable evaluation reference for a run."""

    async def snapshot(self, run: Mapping[str, Any]) -> Mapping[str, Any]: ...


__all__ = [
    "CandidateValidator",
    "CheckpointResult",
    "Curator",
    "EvaluationSnapshotProvider",
    "EvidenceProvider",
    "PolicyEvaluator",
    "Publisher",
    "RunProcessor",
]

