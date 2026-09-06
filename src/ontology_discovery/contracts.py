"""Contracts for restart-safe, proposal-only ontology discovery.

The coordinator intentionally depends on a single ``RunProcessor`` protocol.
The narrower protocols below describe future evidence, curator, policy,
validation, publication-status, and evaluation seams without granting the
coordinator a Fabric stage or active-pointer mutation primitive.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_CHANGED_ENTITIES = 50
MAX_CANDIDATE_PAIRS = 200
MAX_EVIDENCE_RECORDS = 40


class RelationshipProposal(BaseModel):
    """One untrusted relationship proposal returned by the prompt agent."""

    model_config = ConfigDict(extra="forbid", strict=True)

    subject_id: str = Field(min_length=1, max_length=512)
    subject_type: str = Field(min_length=1, max_length=128)
    predicate: str = Field(min_length=1, max_length=128)
    object_id: str = Field(min_length=1, max_length=512)
    object_type: str = Field(min_length=1, max_length=128)
    evidence_refs: list[str] = Field(min_length=1, max_length=20)
    observed_at: datetime
    rationale: str = Field(min_length=1, max_length=1_000)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: list[str] = Field(max_length=10)
    disposition: Literal["propose", "needs_review"]


class ProposalBatch(BaseModel):
    """Strict whole-document contract for proposal-only curator output."""

    model_config = ConfigDict(extra="forbid", strict=True)

    batch_id: str = Field(min_length=1, max_length=128)
    status: Literal["proposals", "insufficient_evidence"]
    proposals: list[RelationshipProposal] = Field(max_length=100)
    missing_evidence: list[str] = Field(max_length=20)

    @model_validator(mode="after")
    def status_matches_content(self) -> Self:
        if self.status == "insufficient_evidence" and self.proposals:
            raise ValueError("insufficient_evidence cannot contain proposals")
        if self.status == "proposals" and not self.proposals:
            raise ValueError("proposals status requires at least one proposal")
        return self


def proposal_content_id(
    *,
    proposal: Mapping[str, Any],
    scope: str,
    source_generation_id: str,
    schema_version: str,
    policy_version: str,
) -> str:
    """Hash every governed proposal identity input, independent of list order."""

    payload = {
        "scope": _required_text(scope, "scope").casefold(),
        "source_generation_id": _required_text(
            source_generation_id, "source_generation_id"
        ),
        "edge": {
            "subject_id": _required_text(
                proposal.get("subject_id"), "subject_id"
            ).casefold(),
            "subject_type": _required_text(
                proposal.get("subject_type"), "subject_type"
            ),
            "predicate": _required_text(proposal.get("predicate"), "predicate"),
            "object_id": _required_text(
                proposal.get("object_id"), "object_id"
            ).casefold(),
            "object_type": _required_text(
                proposal.get("object_type"), "object_type"
            ),
        },
        "evidence_refs": sorted(
            {
                _required_text(value, "evidence_ref")
                for value in proposal.get("evidence_refs", ())
            }
        ),
        "schema_version": _required_text(schema_version, "schema_version"),
        "policy_version": _required_text(policy_version, "policy_version"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"ODP-{digest.upper()}"


class AdmissionEvaluationSnapshot(BaseModel):
    """Immutable evidence for exactly one directional predicate/type pair."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )

    snapshot_id: str = Field(pattern=r"^AES-[A-F0-9]{64}$")
    subject_type: str = Field(min_length=1, max_length=128)
    predicate: str = Field(min_length=1, max_length=128)
    object_type: str = Field(min_length=1, max_length=128)
    shadow_started_at: datetime
    evaluated_at: datetime
    expert_adjudicated_eligible_count: int = Field(ge=0)
    critical_failures: tuple[str, ...] = ()
    escalation_recall: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    recall: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    precision_true_positives: int = Field(ge=0)
    precision_total: int = Field(gt=0)
    approvals: tuple[str, ...] = ()
    ai_spec_gates_passed: bool

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        for value in (self.shadow_started_at, self.evaluated_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("release snapshot timestamps must be timezone-aware")
        if self.evaluated_at < self.shadow_started_at:
            raise ValueError("evaluated_at must not precede shadow_started_at")
        if self.precision_true_positives > self.precision_total:
            raise ValueError("precision true positives cannot exceed total")
        if len(self.approvals) != len(set(self.approvals)):
            raise ValueError("release approvals must be unique")
        if len(self.critical_failures) != len(set(self.critical_failures)):
            raise ValueError("critical failures must be unique")
        if self.snapshot_id != self._derived_id(self._identity_payload()):
            raise ValueError("snapshot identity does not match its content")
        return self

    @property
    def pair(self) -> tuple[str, str, str]:
        return (self.subject_type, self.predicate, self.object_type)

    @property
    def pair_key(self) -> str:
        return "|".join(self.pair)

    def _identity_payload(self) -> dict[str, object]:
        return self._canonical_identity_payload(
            self.model_dump(mode="python", exclude={"snapshot_id"})
        )

    @staticmethod
    def _derived_id(payload: Mapping[str, object]) -> str:
        digest = hashlib.sha256(
            json.dumps(
                dict(payload),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return f"AES-{digest.upper()}"

    @classmethod
    def create(
        cls,
        *,
        subject_type: str,
        predicate: str,
        object_type: str,
        shadow_started_at: datetime,
        evaluated_at: datetime,
        expert_adjudicated_eligible_count: int,
        critical_failures: tuple[str, ...],
        escalation_recall: float,
        recall: float,
        precision_true_positives: int,
        precision_total: int,
        approvals: tuple[str, ...],
        ai_spec_gates_passed: bool,
    ) -> Self:
        values: dict[str, object] = {
            "subject_type": subject_type,
            "predicate": predicate,
            "object_type": object_type,
            "shadow_started_at": shadow_started_at,
            "evaluated_at": evaluated_at,
            "expert_adjudicated_eligible_count": (
                expert_adjudicated_eligible_count
            ),
            "critical_failures": tuple(sorted(critical_failures)),
            "escalation_recall": escalation_recall,
            "recall": recall,
            "precision_true_positives": precision_true_positives,
            "precision_total": precision_total,
            "approvals": tuple(sorted(approvals)),
            "ai_spec_gates_passed": ai_spec_gates_passed,
        }
        identity_payload = cls._canonical_identity_payload(values)
        return cls(
            snapshot_id=cls._derived_id(identity_payload),
            **values,
        )

    @classmethod
    def _canonical_identity_payload(
        cls, values: Mapping[str, object]
    ) -> dict[str, object]:
        return {
            key: (
                value.isoformat()
                if isinstance(value, datetime)
                else list(value)
                if isinstance(value, tuple)
                else value
            )
            for key, value in values.items()
        }


def _bounded_records(
    value: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    *,
    name: str,
    limit: int,
    scope: str,
) -> tuple[dict[str, Any], ...]:
    records = tuple(copy.deepcopy(dict(item)) for item in value)
    if len(records) > limit:
        raise ValueError(f"{name} exceeds hard limit {limit}")
    for record in records:
        if str(record.get("scope") or "").strip() != scope:
            raise ValueError(f"{name} contains a record outside batch scope")
    return records


def _required_text(value: object, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


@dataclass(frozen=True)
class EvidenceBatch:
    """One scope-isolated evidence package that is safe to send to a curator."""

    batch_id: str
    scope: str
    source_generation_id: str
    observed_at: datetime
    freshness: str
    coverage: str
    changed_entities: tuple[Mapping[str, Any], ...] = ()
    candidate_pairs: tuple[Mapping[str, Any], ...] = ()
    evidence_records: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        for name in ("batch_id", "scope", "source_generation_id", "freshness", "coverage"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must not be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        scope = self.scope.strip()
        object.__setattr__(self, "scope", scope)
        object.__setattr__(
            self,
            "changed_entities",
            _bounded_records(
                self.changed_entities,
                name="changed_entities",
                limit=MAX_CHANGED_ENTITIES,
                scope=scope,
            ),
        )
        object.__setattr__(
            self,
            "candidate_pairs",
            _bounded_records(
                self.candidate_pairs,
                name="candidate_pairs",
                limit=MAX_CANDIDATE_PAIRS,
                scope=scope,
            ),
        )
        object.__setattr__(
            self,
            "evidence_records",
            _bounded_records(
                self.evidence_records,
                name="evidence_records",
                limit=MAX_EVIDENCE_RECORDS,
                scope=scope,
            ),
        )

    def all_records(self) -> tuple[Mapping[str, Any], ...]:
        """Return every complete record in deterministic category order."""
        return self.changed_entities + self.candidate_pairs + self.evidence_records

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe durable checkpoint representation."""
        return {
            "batch_id": self.batch_id,
            "scope": self.scope,
            "source_generation_id": self.source_generation_id,
            "observed_at": self.observed_at.astimezone(UTC).isoformat(),
            "freshness": self.freshness,
            "coverage": self.coverage,
            "changed_entities": copy.deepcopy(list(self.changed_entities)),
            "candidate_pairs": copy.deepcopy(list(self.candidate_pairs)),
            "evidence_records": copy.deepcopy(list(self.evidence_records)),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvidenceBatch:
        """Rehydrate a batch previously emitted by :meth:`to_dict`."""
        observed_at = datetime.fromisoformat(str(value.get("observed_at") or ""))
        return cls(
            batch_id=str(value.get("batch_id") or ""),
            scope=str(value.get("scope") or ""),
            source_generation_id=str(value.get("source_generation_id") or ""),
            observed_at=observed_at,
            freshness=str(value.get("freshness") or ""),
            coverage=str(value.get("coverage") or ""),
            changed_entities=tuple(value.get("changed_entities") or ()),
            candidate_pairs=tuple(value.get("candidate_pairs") or ()),
            evidence_records=tuple(value.get("evidence_records") or ()),
        )


@dataclass(frozen=True)
class CheckpointResult:
    """One durable result returned by a bounded processor invocation."""

    checkpoint: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    complete: bool = False

    def __post_init__(self) -> None:
        if not self.checkpoint.strip():
            raise ValueError("checkpoint must not be empty")


class RunProcessingFailure(RuntimeError):
    """A bounded, safe failure with a durable checkpoint classification."""

    def __init__(
        self,
        *,
        failure_class: str,
        checkpoint: str,
        payload: Mapping[str, Any] | None = None,
        message: str = "",
    ) -> None:
        normalized_failure = str(failure_class or "").strip()
        normalized_checkpoint = str(checkpoint or "").strip()
        if not normalized_failure or not normalized_checkpoint:
            raise ValueError("failure_class and checkpoint must not be empty")
        super().__init__(message or normalized_failure)
        self.failure_class = normalized_failure
        self.checkpoint = normalized_checkpoint
        self.payload = copy.deepcopy(dict(payload or {}))


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
    "MAX_CANDIDATE_PAIRS",
    "MAX_CHANGED_ENTITIES",
    "MAX_EVIDENCE_RECORDS",
    "AdmissionEvaluationSnapshot",
    "CandidateValidator",
    "CheckpointResult",
    "Curator",
    "EvaluationSnapshotProvider",
    "EvidenceBatch",
    "EvidenceProvider",
    "PolicyEvaluator",
    "ProposalBatch",
    "Publisher",
    "RelationshipProposal",
    "RunProcessingFailure",
    "RunProcessor",
    "proposal_content_id",
]
