"""Canonical contracts for governed Operations Copilot orchestration."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.scope import Scope
from operations.specialist_manifest import PageMapping

MAX_SNAPSHOT_EVIDENCE = 200
MAX_SNAPSHOT_BYTES = 128 * 1024
MAX_EVIDENCE_ROW_BYTES = 8 * 1024
MAX_SELECTED_ENTITIES = 50
MAX_MATERIAL_CLAIMS = 200
MAX_RETAINED_CITATIONS = 64
COVERAGE_CITATION_ID = "snapshot:coverage"
MAX_SNAPSHOT_FILTERS = 16
MAX_SNAPSHOT_FILTER_VALUES = 64


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


class AzureEntityRef(ContractModel):
    """An untrusted Azure observation identified only by its ARM resource ID."""

    type: Literal["azure"]
    resource_id: str = Field(min_length=1, max_length=512)

    @field_validator("resource_id")
    @classmethod
    def validate_resource_id(cls, value: str) -> str:
        if value.startswith(("http://", "https://")):
            raise ValueError("Azure entity resource IDs must not be URLs")
        parts = [part for part in value.split("/") if part]
        if (
            not value.startswith("/")
            or len(parts) < 2
            or parts[0].casefold() != "subscriptions"
            or not parts[1]
        ):
            raise ValueError("Azure entities require canonical ARM resource IDs")
        return value


class DomainEntityRef(ContractModel):
    """A typed non-Azure observation resolved to authority on the server."""

    type: Literal["domain"]
    namespace: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    kind: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    source_key: str = Field(min_length=1, max_length=256)


EntityRef = Annotated[
    AzureEntityRef | DomainEntityRef,
    Field(discriminator="type"),
]


class MaterialClaim(ContractModel):
    """A material result claim that must remain closed over retained evidence."""

    claim_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    evidence_refs: list[str] = Field(min_length=1, max_length=32)
    requires_complete_coverage: bool = False


class SnapshotEvidence(ContractModel):
    evidence_id: str = Field(
        min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    source: str = Field(min_length=1, max_length=128)
    status: Literal["ok", "empty", "partial", "unavailable", "denied"] = "ok"
    observed_at: str = Field(default="", max_length=128)
    resource_id: str = Field(default="", max_length=512)
    source_key: str = Field(default="", max_length=256)
    entity: EntityRef | None = None
    claim_type: str = Field(default="observation", min_length=1, max_length=128)
    citations: list[str] = Field(default_factory=list, max_length=32)
    selected: bool = False
    direct: bool = False
    actionable: bool = False
    severity: Literal["unknown", "low", "medium", "high", "critical"] = "unknown"
    quality: Literal["unknown", "low", "medium", "high"] = "unknown"
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("evidence_id")
    @classmethod
    def reserve_generated_citation_namespaces(cls, value: str) -> str:
        if value.casefold().startswith(("snapshot:", "tool:")):
            raise ValueError("snapshot evidence ID uses a reserved citation namespace")
        return value

    @field_validator("source_key")
    @classmethod
    def validate_source_key(cls, value: str) -> str:
        if any(character in value for character in ("\x00", "\r", "\n")):
            raise ValueError("snapshot evidence source key is invalid")
        return value

    @field_validator("citations")
    @classmethod
    def validate_citations(cls, value: list[str]) -> list[str]:
        normalized = []
        for citation in value:
            citation = str(citation).strip()
            if (
                not citation
                or len(citation) > 200
                or any(character in citation for character in ("\x00", "\r", "\n"))
            ):
                raise ValueError("snapshot evidence citation is invalid")
            normalized.append(citation)
        if len(normalized) != len(set(normalized)):
            raise ValueError("snapshot evidence citations must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_row_size(self) -> SnapshotEvidence:
        encoded = json.dumps(
            self.data,
            default=str,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > MAX_EVIDENCE_ROW_BYTES:
            raise ValueError("evidence row exceeds size limit")
        return self


class EvidenceSnapshotV2(ContractModel):
    """Bounded browser observations accepted by the canonical v2 pipeline."""

    version: Literal["2"] = "2"
    page_kind: PageMapping
    page_id: str = Field(min_length=1, max_length=128)
    filters: dict[str, list[str]] = Field(default_factory=dict)
    query: str = Field(default="", max_length=1024)
    generation_id: str = Field(
        default="",
        pattern=r"^(?:|generation:[a-f0-9]{64})$",
    )
    coverage: SnapshotCoverage
    freshness: list[SnapshotFreshness] = Field(default_factory=list, max_length=32)
    selected_entities: list[EntityRef] = Field(
        default_factory=list,
        max_length=MAX_SELECTED_ENTITIES,
    )
    evidence: list[SnapshotEvidence] = Field(
        default_factory=list,
        max_length=MAX_SNAPSHOT_EVIDENCE,
    )
    material_claims: list[MaterialClaim] = Field(
        default_factory=list,
        max_length=MAX_MATERIAL_CLAIMS,
    )

    @field_validator("filters")
    @classmethod
    def normalize_filters(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if len(value) > MAX_SNAPSHOT_FILTERS:
            raise ValueError("snapshot filters exceed size limit")
        normalized: dict[str, list[str]] = {}
        for raw_key, raw_values in value.items():
            key = " ".join(str(raw_key).strip().casefold().split())
            if not key or len(key) > 64:
                raise ValueError("snapshot filter name is invalid")
            if len(raw_values) > MAX_SNAPSHOT_FILTER_VALUES:
                raise ValueError("snapshot filter values exceed size limit")
            values = sorted(
                {
                    " ".join(str(item).strip().casefold().split())
                    for item in raw_values
                    if str(item).strip()
                }
            )
            if any(len(item) > 256 for item in values):
                raise ValueError("snapshot filter value is invalid")
            if values:
                normalized[key] = values
        return dict(sorted(normalized.items()))

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(value.strip().casefold().split())

    def content_generation_id(self) -> str:
        """Return the immutable digest of the evidence generation on this page."""

        payload = {
            "coverage": self.coverage.model_dump(mode="json"),
            "freshness": sorted(
                (
                    item.model_dump(mode="json")
                    for item in self.freshness
                ),
                key=lambda item: json.dumps(
                    item,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
            "evidence": sorted(
                (
                    item.model_dump(mode="json")
                    for item in self.evidence
                ),
                key=lambda item: str(item["evidence_id"]),
            ),
            "material_claims": sorted(
                (
                    item.model_dump(mode="json")
                    for item in self.material_claims
                ),
                key=lambda item: str(item["claim_id"]),
            ),
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        return f"generation:{hashlib.sha256(encoded).hexdigest()}"

    @model_validator(mode="after")
    def validate_snapshot(self) -> EvidenceSnapshotV2:
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("snapshot evidence ids must be unique")
        available = set(ids)
        for claim in self.material_claims:
            missing = sorted(set(claim.evidence_refs) - available)
            if missing:
                raise ValueError(
                    f"material claim {claim.claim_id!r} has missing evidence reference "
                    f"{missing[0]!r}"
                )
        # A browser-provided generation token is never authoritative. Recompute
        # it over the strict bounded content so the identity cannot be reused
        # after evidence, freshness, coverage, or claim closure changes.
        self.generation_id = self.content_generation_id()
        if len(self.model_dump_json().encode()) > MAX_SNAPSHOT_BYTES:
            raise ValueError("snapshot exceeds size limit")
        return self


class CanonicalCoverage(ContractModel):
    """Server-owned interpretation of page coverage."""

    visible_count: int = Field(ge=0, le=1_000_000)
    total_count: int = Field(ge=0, le=1_000_000)
    complete: bool
    state: Literal["complete", "partial"]


class CanonicalEvidence(ContractModel):
    """One authorized, deduplicated evidence variant retained by the server."""

    stable_id: str = Field(pattern=r"^evidence:[a-f0-9]{32}$")
    variant_id: str = Field(pattern=r"^variant:[a-f0-9]{32}$")
    entity_key: str = Field(min_length=1, max_length=640)
    source: str = Field(min_length=1, max_length=128)
    source_key: str = Field(min_length=1, max_length=256)
    claim_type: str = Field(min_length=1, max_length=128)
    status: Literal["ok", "empty", "partial", "unavailable", "denied"]
    freshness: Literal["fresh", "stale", "partial", "unavailable", "unknown"]
    observed_at: str = Field(default="", max_length=128)
    evidence_refs: list[str] = Field(
        min_length=1,
        max_length=MAX_SNAPSHOT_EVIDENCE,
    )
    citations: list[str] = Field(
        min_length=1,
        max_length=MAX_RETAINED_CITATIONS,
    )
    selected: bool
    direct: bool
    actionable: bool
    severity: Literal["unknown", "low", "medium", "high", "critical"]
    quality: Literal["unknown", "low", "medium", "high"]
    data: dict[str, Any] = Field(default_factory=dict)


class SnapshotConflict(ContractModel):
    """All contradictory retained variants for one stable evidence identity."""

    conflict_id: str = Field(pattern=r"^conflict:[a-f0-9]{32}$")
    stable_id: str = Field(pattern=r"^evidence:[a-f0-9]{32}$")
    variant_ids: list[str] = Field(min_length=2, max_length=MAX_SNAPSHOT_EVIDENCE)


class CanonicalEvidenceSnapshot(ContractModel):
    """Authorized server projection used for policy and citation decisions."""

    version: Literal["2"] = "2"
    page_kind: str = Field(min_length=1, max_length=64)
    page_id: str = Field(min_length=1, max_length=128)
    coverage: CanonicalCoverage
    evidence: list[CanonicalEvidence] = Field(
        default_factory=list,
        max_length=MAX_SNAPSHOT_EVIDENCE,
    )
    conflicts: list[SnapshotConflict] = Field(
        default_factory=list,
        max_length=MAX_SNAPSHOT_EVIDENCE,
    )
    uncertainty: list[str] = Field(default_factory=list, max_length=64)
    classification: Literal["ready", "empty", "insufficient_evidence"]
    insufficiency_reasons: list[str] = Field(default_factory=list, max_length=64)

    def snapshot_hash(self) -> str:
        """Return a deterministic hash of the canonical retained projection."""

        encoded = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


class ToolCallCandidate(ContractModel):
    tool: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    citation_ids: list[str] = Field(
        default_factory=list, max_length=MAX_SNAPSHOT_EVIDENCE
    )
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
    expected_thread_revision: int | None = Field(default=None, ge=1)

    @field_validator("requested_scope")
    @classmethod
    def validate_scope(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        Scope.from_mapping(value)
        return value

    @model_validator(mode="after")
    def validate_thread_revision(self) -> InvestigationRequest:
        if self.expected_thread_revision is not None and self.thread_id is None:
            raise ValueError("expected thread revision requires a thread ID")
        return self


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
    synthesis: dict[str, Any] | None = None
    mutation_authorized: Literal[False] = False


__all__ = [
    "COVERAGE_CITATION_ID",
    "AzureEntityRef",
    "CandidatePlan",
    "CanonicalCoverage",
    "CanonicalEvidence",
    "CanonicalEvidenceSnapshot",
    "Citation",
    "DomainEntityRef",
    "EntityRef",
    "EvidenceSnapshotV2",
    "InvestigationRequest",
    "MaterialClaim",
    "OrchestrationResult",
    "SnapshotConflict",
    "SnapshotCoverage",
    "SnapshotEvidence",
    "SnapshotFreshness",
    "SpecialistStep",
    "ToolCallCandidate",
]
