"""Immutable personal assessment receipts, not raw artifacts or release authority."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

MAX_RECEIPTS = 20
MAX_RECEIPT_BYTES = 256 * 1024
MAX_HISTORY_BYTES = 4 * 1024 * 1024
MAX_REVISION = 9_007_199_254_740_991
Identifier = Annotated[str, Field(min_length=1, max_length=4096)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
AssessmentId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
ChangeSource = Literal[
    "terraform_plan", "bicep_what_if", "arm_diff", "github_pull_request", "azure_devops"
]


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Retained assessment times must be timezone-aware")
    return parsed


def _bytes(payload: dict) -> int:
    return len(
        (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    )


class RetainedChangeRow(BaseModel):
    """Normalized declared identity/action/property names; never before/after values."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    address: Identifier
    action: Literal["create", "update", "delete", "replace", "no-op", "unknown"]
    resource_type: str = Field(max_length=4096)
    resource_id: str = Field(max_length=4096)
    name: str = Field(max_length=4096)
    provider: str = Field(max_length=512)
    changed_properties: list[Annotated[str, Field(max_length=256)]] = Field(
        max_length=512
    )
    is_destructive: bool
    source_ref: str = Field(max_length=256)


class AssessmentReceipt(BaseModel):
    """A bounded historical analysis summary, not the full analysis or source artifact."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    assessment_id: AssessmentId
    artifact_sha256: Digest
    source: ChangeSource
    change_id: str = Field(min_length=1, max_length=512)
    title: str = Field(max_length=512)
    assessed_at: str = Field(max_length=40)
    retained_at: str = Field(max_length=40)
    risk_score: int = Field(ge=0, le=100)
    risk_level: Literal["Low", "Moderate", "High", "Critical"]
    confidence: Literal["high", "medium", "low", "unknown"]
    verdict: Literal["approve", "approve_with_conditions", "require_review"]
    unknowns: list[Annotated[str, Field(max_length=8192)]] = Field(max_length=2000)
    changes: list[RetainedChangeRow] = Field(max_length=500)
    impacted_resource_ids: list[Identifier] = Field(max_length=1000)
    business_services: list[Annotated[str, Field(max_length=512)]] = Field(
        max_length=1000
    )
    traversal_truncated: bool
    network_review_digest: Digest | None

    @model_validator(mode="after")
    def coherent_receipt(self):
        """Retention is later than analysis; duplicate impact IDs do not inflate counts."""
        if _aware(self.assessed_at) > _aware(self.retained_at):
            raise ValueError("Assessment retention time precedes its analysis")
        if len(set(self.impacted_resource_ids)) != len(self.impacted_resource_ids):
            raise ValueError("Assessment impact identities must be unique")
        if _bytes(self.model_dump()) > MAX_RECEIPT_BYTES:
            raise ValueError("Assessment receipt exceeds its 256 KiB limit")
        return self


class RetentionRequest(BaseModel):
    """References only; the server retrieves the owned exact-scope assessment."""

    model_config = ConfigDict(extra="forbid", strict=True)
    assessment_id: AssessmentId
    artifact_sha256: Digest
    expected_revision: int = Field(ge=0, lt=MAX_REVISION)


class ReceiptRemoval(BaseModel):
    """Explicit removal from a reviewed collection, never automatic eviction."""

    model_config = ConfigDict(extra="forbid", strict=True)
    assessment_id: AssessmentId
    expected_revision: int = Field(ge=0, lt=MAX_REVISION)


class AssessmentHistory(BaseModel):
    """One exact subject/scope CAS document; individual receipts cannot be replaced."""

    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int = Field(ge=1, le=1)
    actor: str
    scope: dict[str, list[str]]
    revision: int = Field(ge=0, le=MAX_REVISION)
    updated_at: str = Field(max_length=40)
    receipts: list[AssessmentReceipt] = Field(max_length=MAX_RECEIPTS)

    @model_validator(mode="after")
    def coherent_history(self):
        """Reject duplicate identities, invalid initial state and corrupt update times."""
        ids = [receipt.assessment_id for receipt in self.receipts]
        if len(set(ids)) != len(ids) or len(ids) > self.revision:
            raise ValueError("Assessment receipt identities must be unique")
        if self.revision == 0:
            if self.receipts or self.updated_at:
                raise ValueError("Unsaved assessment history must be empty")
        elif not self.updated_at or _aware(self.updated_at) < max(
            (_aware(row.retained_at) for row in self.receipts),
            default=datetime.min.replace(tzinfo=UTC),
        ):
            raise ValueError("Assessment history update time is invalid")
        return self


class PredeployHistoryStore:
    """Retain explicit review receipts on the existing local/OneLake atomic CAS."""

    def __init__(self, documents: OneLakeDocumentStore):
        self.documents = documents

    @staticmethod
    def _name(actor: str, scope: dict[str, list[str]]) -> str:
        identity = json.dumps([actor, scope], sort_keys=True, separators=(",", ":"))
        return f"state/predeploy-history/{hashlib.sha256(identity.encode()).hexdigest()}.json"

    def _read(self, actor: str, scope: dict[str, list[str]]):
        name = self._name(actor, scope)
        snapshot = self.documents.read_snapshot(name)
        if snapshot.exists:
            try:
                size = _bytes(snapshot.payload)
            except (TypeError, ValueError, RecursionError) as exc:
                raise RuntimeError("Stored assessment history JSON is invalid") from exc
            if size > MAX_HISTORY_BYTES:
                raise RuntimeError(
                    "Stored assessment history exceeds its document limit"
                )
        try:
            state = (
                AssessmentHistory.model_validate(snapshot.payload)
                if snapshot.exists
                else AssessmentHistory(
                    schema_version=1,
                    actor=actor,
                    scope=scope,
                    revision=0,
                    updated_at="",
                    receipts=[],
                )
            )
        except ValidationError as exc:
            raise RuntimeError("Stored assessment history schema is invalid") from exc
        if (state.actor, state.scope) != (actor, scope):
            raise RuntimeError("Stored assessment history identity is invalid")
        return name, snapshot, state

    def read(self, actor: str, scope: dict[str, list[str]]) -> dict:
        """Recover exact owned receipts without acquiring any current provider."""
        return self._read(actor, scope)[2].model_dump()

    def _update(
        self,
        actor: str,
        scope: dict[str, list[str]],
        expected_revision: int,
        *,
        receipt: AssessmentReceipt | None = None,
        remove: str | None = None,
    ) -> dict:
        name, snapshot, state = self._read(actor, scope)
        if state.revision != expected_revision or state.revision >= MAX_REVISION:
            raise DocumentConflictError(
                "Assessment history changed; reload before continuing"
            )
        rows = state.receipts
        if receipt is not None:
            if any(row.assessment_id == receipt.assessment_id for row in rows):
                raise DocumentConflictError(
                    "Assessment is already retained; reload history"
                )
            if len(rows) >= MAX_RECEIPTS:
                raise ValueError(
                    "Assessment history is full; explicitly delete a receipt before retaining another"
                )
            rows = [*rows, receipt]
        else:
            if not any(row.assessment_id == remove for row in rows):
                raise KeyError("Retained assessment was not found")
            rows = [row for row in rows if row.assessment_id != remove]
        updated = AssessmentHistory(
            schema_version=1,
            actor=actor,
            scope=scope,
            revision=state.revision + 1,
            updated_at=datetime.now(UTC).isoformat(),
            receipts=rows,
        ).model_dump()
        if _bytes(updated) > MAX_HISTORY_BYTES:
            raise ValueError("Assessment history exceeds its 4 MiB document limit")
        if snapshot.exists:
            self.documents.replace_if_match(name, updated, expected_etag=snapshot.etag)
        else:
            self.documents.create_only(name, updated)
        return updated

    def append(
        self,
        actor: str,
        scope: dict[str, list[str]],
        expected_revision: int,
        receipt: AssessmentReceipt,
    ) -> dict:
        """Append an already validated server receipt without replacing prior evidence."""
        return self._update(actor, scope, expected_revision, receipt=receipt)

    def remove(
        self,
        actor: str,
        scope: dict[str, list[str]],
        expected_revision: int,
        assessment_id: str,
    ) -> dict:
        """Remove only an explicitly identified receipt from the reviewed revision."""
        return self._update(actor, scope, expected_revision, remove=assessment_id)


def assessment_receipt(assessment: dict[str, Any]) -> AssessmentReceipt:
    """Project only safe server analysis fields; never copy raw artifact/property bags."""
    change, artifact = assessment["change"], assessment["artifact"]
    if (
        assessment["confirmed_cause"] is not False
        or artifact["source"] != change["source"]
    ):
        raise ValueError("Assessment advisory provenance is invalid")
    return AssessmentReceipt(
        assessment_id=assessment["assessment_id"],
        artifact_sha256=artifact["sha256"],
        source=change["source"],
        change_id=change["change_id"],
        title=change["title"],
        assessed_at=assessment["assessed_at"],
        retained_at=datetime.now(UTC).isoformat(),
        risk_score=assessment["risk"]["score"],
        risk_level=assessment["risk"]["level"],
        confidence=assessment["risk"]["confidence"],
        verdict=assessment["cab_recommendation"]["verdict"],
        unknowns=assessment["risk"]["unknowns"],
        changes=[
            RetainedChangeRow.model_validate(row) for row in change["resource_changes"]
        ],
        impacted_resource_ids=sorted(
            {
                row["resource_id"]
                for row in assessment["blast_radius"]["impacted_resources"]
            }
        ),
        business_services=assessment["blast_radius"]["business_services"],
        traversal_truncated=assessment["blast_radius"]["truncated"],
        network_review_digest=(assessment.get("network_review") or {}).get(
            "reviewed_digest"
        ),
    )


def compare_receipts(baseline: AssessmentReceipt, candidate: AssessmentReceipt) -> dict:
    """Compare declared analysis summaries, not applied changes or verified lineage."""
    if baseline.assessment_id == candidate.assessment_id:
        raise ValueError("Select two different retained assessments")
    if baseline.source != candidate.source:
        raise ValueError("Retained comparisons require the same artifact source format")

    def signature(row: RetainedChangeRow) -> str:
        data = row.model_dump(exclude={"source_ref"})
        data["changed_properties"] = sorted(data["changed_properties"])
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def rows(receipt: AssessmentReceipt) -> Counter[str]:
        return Counter(signature(row) for row in receipt.changes)

    def difference(receipt: AssessmentReceipt, counts: Counter[str]) -> list[dict]:
        result = []
        for row in receipt.changes:
            key = signature(row)
            if counts[key]:
                counts[key] -= 1
                result.append(row.model_dump())
        return result

    before, after = rows(baseline), rows(candidate)
    before_ids, after_ids = (
        set(baseline.impacted_resource_ids),
        set(candidate.impacted_resource_ids),
    )
    return {
        "baseline": baseline.model_dump(),
        "candidate": candidate.model_dump(),
        "same_artifact": baseline.artifact_sha256 == candidate.artifact_sha256,
        "risk_score_delta": candidate.risk_score - baseline.risk_score,
        "added_declared_rows": difference(candidate, after - before),
        "removed_declared_rows": difference(baseline, before - after),
        "added_impacted_resource_ids": sorted(after_ids - before_ids),
        "removed_impacted_resource_ids": sorted(before_ids - after_ids),
        "interpretation": (
            "Historical declared analysis only. Different artifact digests do not prove revision lineage; "
            "risk and impact differences may reflect observation times or analysis changes, not applied fixes, "
            "runtime outcomes or deployment authority. Raw artifacts and full analysis are not retained."
        ),
    }
