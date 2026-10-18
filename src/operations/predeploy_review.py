"""Digest-bound advisory CI contracts; no execution or deployment authority."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from operations.predeploy_history import AssessmentReceipt, Digest

INTERPRETATION = (
    "Point-in-time declared analysis only. Advisory-clear means only that this summary "
    "does not trigger this contract's escalation rules; omitted conditions or approvals "
    "are neither evaluated nor satisfied. It is never deployment approval. Digests identify JSON "
    "values, not signatures, source authenticity, verified revision lineage, runtime "
    "outcomes or a complete evidence archive. A later policy or source change can "
    "invalidate this review; deployment authorization is always separate."
)


def review_digest(payload: dict) -> str:
    """Hash a canonical ASCII JSON value, independent of formatting/key order."""
    raw = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def _disposition(receipt: AssessmentReceipt) -> str:
    return (
        "advisory_clear"
        if (
            receipt.verdict == "approve"
            and receipt.confidence == "high"
            and not receipt.unknowns
            and not receipt.traversal_truncated
            and receipt.risk_level == "Low"
            and not receipt.business_services
            and not any(
                row.is_destructive or row.action in ("delete", "replace")
                for row in receipt.changes
            )
        )
        else "review_required"
    )


class CIReviewContract(BaseModel):
    """Strict immutable receipt binding; self-hashes are integrity checks, not signatures."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: int = Field(ge=1, le=1)
    purpose: Literal["predeploy-advisory-ci-review"]
    scope: dict[str, list[str]]
    receipt: AssessmentReceipt
    receipt_sha256: Digest
    disposition: Literal["review_required", "advisory_clear"]
    deployment_authority: Literal["none"]
    interpretation: Literal[INTERPRETATION]
    review_sha256: Digest

    @model_validator(mode="after")
    def coherent_contract(self):
        """Reject altered evidence, derived disposition or contract bindings."""
        if self.receipt_sha256 != review_digest(self.receipt.model_dump()):
            raise ValueError("Review receipt digest does not match")
        if self.disposition != _disposition(self.receipt):
            raise ValueError("Review disposition does not match the retained analysis")
        if self.review_sha256 != review_digest(
            self.model_dump(exclude={"review_sha256"})
        ):
            raise ValueError("Review contract digest does not match")
        return self


def review_contract(receipt: AssessmentReceipt, scope: dict[str, list[str]]) -> dict:
    """Export an authorized retained summary; do not acquire providers or retain raw input."""
    data = {
        "schema_version": 1,
        "purpose": "predeploy-advisory-ci-review",
        "scope": scope,
        "receipt": receipt.model_dump(),
        "receipt_sha256": review_digest(receipt.model_dump()),
        "disposition": _disposition(receipt),
        "deployment_authority": "none",
        "interpretation": INTERPRETATION,
    }
    return CIReviewContract.model_validate(
        {**data, "review_sha256": review_digest(data)}
    ).model_dump()
