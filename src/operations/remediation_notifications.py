"""Read-only latest recorded outcomes, not provider polling or notification delivery."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_INT = 9_007_199_254_740_991


class _RecordedExecution(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    execution_id: str = Field(min_length=1, max_length=2048)
    plan_id: str = Field(min_length=1, max_length=2048)
    revision: int = Field(ge=0, le=MAX_INT)
    status: Literal["queued", "running", "retrying", "failed", "cancelled", "succeeded"]
    updated_at: str = Field(default="", max_length=40)
    failure_class: str = Field(default="", max_length=128)
    execution_snapshot: dict = Field(default_factory=dict)
    evidence_reconciliation: dict = Field(default_factory=dict)

    @field_validator("updated_at")
    @classmethod
    def aware_timestamp(cls, value: str) -> str:
        if value:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                raise ValueError("Execution observation requires an aware timestamp")
            try:
                return parsed.astimezone(UTC).isoformat()
            except OverflowError as exc:
                raise ValueError("Execution observation exceeds the supported UTC range") from exc
        return value


def verification_notifications(records: list[dict]) -> list[dict]:
    """Project already-authorized stored records without acquiring or changing sources.

    One latest outcome per execution is returned, not a reconstructed immutable
    transition history, delivery log, personal unread count or current estate health.
    """
    rows, identities = [], set()
    for payload in records:
        record = _RecordedExecution.model_validate(payload)
        if record.execution_id in identities:
            raise ValueError("Execution identities must be unique")
        identities.add(record.execution_id)
        ambiguous = record.failure_class == "submission_ambiguous"
        if record.status in {"queued", "running", "retrying"} and not ambiguous:
            continue
        reconciliation = record.evidence_reconciliation.get("status", "")
        reconciliation = reconciliation if reconciliation in {
            "", "reconciled_clean", "reconciled_incomplete", "unreconciled",
            "unreconciled_manual_resolution", "unreconciled_timed_out",
        } else "unknown"
        if ambiguous:
            kind, title = "attention", "Provider submission is ambiguous; manual review required"
        elif record.status == "failed":
            kind, title = "attention", "Execution recorded as failed"
        elif record.status == "cancelled":
            kind, title = "cancelled", "Execution recorded as cancelled"
        elif reconciliation == "reconciled_clean":
            kind, title = "complete", "Execution succeeded; recorded evidence reconciliation is clean"
        elif reconciliation in {"reconciled_incomplete", "unreconciled", "unreconciled_manual_resolution", "unreconciled_timed_out"}:
            kind, title = "attention", "Execution succeeded; evidence reconciliation still requires review"
        else:
            kind, title = "attention", "Execution succeeded; evidence reconciliation is unconfirmed"
        target = record.execution_snapshot.get("target_id", "")
        if not isinstance(target, str) or len(target) > 2048:
            raise ValueError("Execution target identity is invalid")
        rows.append({
            "notification_id": hashlib.sha256(json.dumps(
                [record.execution_id, record.revision], separators=(",", ":"),
            ).encode()).hexdigest(),
            "execution_id": record.execution_id, "plan_id": record.plan_id,
            "revision": record.revision, "kind": kind, "title": title,
            "execution_status": record.status, "reconciliation_status": reconciliation or "unreported",
            "recorded_at": record.updated_at or None, "target_id": target,
            "authority": "none",
        })
    return sorted(rows, key=lambda row: (
        row["recorded_at"] is None,
        -datetime.fromisoformat(row["recorded_at"]).timestamp() if row["recorded_at"] else 0,
        row["execution_id"],
    ))
