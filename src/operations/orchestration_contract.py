"""Canonical contracts for governed Operations Copilot orchestration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.scope import Scope

MAX_SNAPSHOT_EVIDENCE = 200
MAX_SNAPSHOT_BYTES = 128 * 1024
COVERAGE_CITATION_ID = "snapshot:coverage"


class ContractModel(BaseModel):
    """Strict base model for every externally supplied orchestration value."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SnapshotCoverage(ContractModel):
    visible_count: int = Field(ge=0, le=1_000_000)
    total_count: int = Field(ge=0, le=1_000_000)
    complete: bool

    @model_validator(mode="after")
    def validate_counts(self) -> SnapshotCoverage:
        if self.visible_count > self.total_count:
            raise ValueError("visible coverage cannot exceed total coverage")
        if self.complete and self.visible_count != self.total_count:
            raise ValueError("complete coverage must include the total result set")
        return self


class SnapshotFreshness(ContractModel):
    source: str = Field(min_length=1, max_length=128)
    observed_at: str = Field(min_length=1, max_length=128)
    status: Literal["fresh", "stale", "partial", "unavailable"] = "fresh"


class SnapshotEvidence(ContractModel):
    evidence_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$")
    source: str = Field(min_length=1, max_length=128)
    status: Literal["ok", "empty", "partial", "unavailable", "denied"] = "ok"
    observed_at: str = Field(default="", max_length=128)
    resource_id: str = Field(default="", max_length=512)
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_id")
    @classmethod
    def reserve_generated_citation_namespaces(cls, value: str) -> str:
        if value.casefold().startswith(("snapshot:", "tool:")):
            raise ValueError("snapshot evidence ID uses a reserved citation namespace")
        return value


class EvidenceSnapshotV2(ContractModel):
    """Minimal v2 snapshot seam used by the Inventory tracer."""

    version: Literal["2"] = "2"
    page_kind: Literal["inventory", "connections", "connections_fabric"]
    page_id: str = Field(min_length=1, max_length=128)
    coverage: SnapshotCoverage
    freshness: list[SnapshotFreshness] = Field(default_factory=list, max_length=32)
    evidence: list[SnapshotEvidence] = Field(
        default_factory=list,
        max_length=MAX_SNAPSHOT_EVIDENCE,
    )

    @model_validator(mode="after")
    def validate_snapshot(self) -> EvidenceSnapshotV2:
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("snapshot evidence ids must be unique")
        if len(self.model_dump_json().encode()) > MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot exceeds size limit")
        return self


class ToolCallCandidate(ContractModel):
    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    citation_ids: list[str] = Field(default_factory=list, max_length=MAX_SNAPSHOT_EVIDENCE)
    mutation: bool = False


class SpecialistStep(ContractModel):
    specialist_id: str = Field(min_length=1, max_length=80)
    tool_calls: list[ToolCallCandidate] = Field(min_length=1, max_length=16)
    depends_on: list[str] = Field(default_factory=list, max_length=8)


class CandidatePlan(ContractModel):
    """Untrusted coordinator proposal validated before any tool I/O."""

    steps: list[SpecialistStep] = Field(min_length=1, max_length=32)
    estimated_tokens: int = Field(default=0, ge=0, le=1_000_000)
    max_wall_seconds: float = Field(default=5, gt=0, le=10_000)
    mutation_intent: bool = False


class InvestigationRequest(ContractModel):
    """Canonical request shared by all Operations Copilot surfaces."""

    contract_version: Literal["1"] = "1"
    question: str = Field(min_length=1, max_length=1024)
    requested_scope: dict[str, list[str]]
    snapshot: EvidenceSnapshotV2
    thread_id: str | None = Field(
        default=None,
        min_length=16,
        max_length=80,
        pattern=r"^thr-[a-f0-9]{32}$",
    )

    @field_validator("requested_scope")
    @classmethod
    def validate_scope(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        Scope.from_mapping(value)
        return value


class Citation(ContractModel):
    citation_id: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=32)
    observed_at: str = Field(default="", max_length=128)
    resource_id: str = Field(default="", max_length=512)


class OrchestrationResult(ContractModel):
    """Canonical, citation-retaining result without hidden reasoning."""

    contract_version: Literal["1"] = "1"
    status: Literal["ok", "empty", "partial", "unavailable", "denied"]
    policy_status: Literal["accepted", "fallback"]
    fallback_reason: str = Field(default="", max_length=160)
    selected_specialists: list[str] = Field(default_factory=list, max_length=8)
    selected_tools: list[str] = Field(default_factory=list, max_length=16)
    tool_results: list[dict[str, Any]] = Field(default_factory=list, max_length=16)
    uncertainty: list[str] = Field(default_factory=list, max_length=32)
    coverage: SnapshotCoverage
    citations: list[Citation] = Field(default_factory=list, max_length=256)
    thread_id: str = Field(pattern=r"^thr-[a-f0-9]{32}$")
    thread_revision: int = Field(ge=1)
    mutation_authorized: Literal[False] = False


__all__ = [
    "COVERAGE_CITATION_ID",
    "CandidatePlan",
    "Citation",
    "EvidenceSnapshotV2",
    "InvestigationRequest",
    "OrchestrationResult",
    "SnapshotCoverage",
    "SnapshotEvidence",
    "SnapshotFreshness",
    "SpecialistStep",
    "ToolCallCandidate",
]
