"""Safe exact-evidence handoff to advisory review, never generated change authority."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .gaps import NetworkGap
from .service import NetworkIntelligenceService
from .tightening import RuleFinding

ReviewKind = Literal["gap", "rule"]
DIGEST_PATTERN = r"^[0-9a-f]{64}$"


class NetworkReviewReference(BaseModel):
    """Only a server-issued exact finding reference, never submitted evidence text."""

    model_config = ConfigDict(extra="forbid", strict=True)
    kind: ReviewKind
    finding_id: str = Field(min_length=1, max_length=256)
    reviewed_digest: str = Field(pattern=DIGEST_PATTERN)


def _digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def finding_review(
    finding: NetworkGap | RuleFinding,
    kind: ReviewKind,
    service: NetworkIntelligenceService,
    scope: dict[str, list[str]],
) -> dict:
    """Project safe fields and bind the complete source finding, policy and scope by digest."""
    raw = finding.to_dict()
    resource_ids = (
        [finding.resource_id]
        if isinstance(finding, NetworkGap)
        else [finding.control_id, finding.rule_id, *finding.affected_resource_ids]
    )
    projection = {
        "kind": kind,
        "finding_id": raw["gap_id" if kind == "gap" else "finding_id"],
        "title": finding.title,
        "severity": finding.severity,
        "category": finding.category,
        "detail": finding.detail,
        "recommendation": finding.recommendation,
        "resource_ids": sorted({value for value in resource_ids if value}),
        "basis": finding.basis
        if isinstance(finding, NetworkGap)
        else "Source rule analysis",
        "flow_log_state": service.flow_log_provenance["state"],
        "source_observed_at": service.snapshot.observed_at,
        "scope": scope,
        "policy_digest": _digest(service.policy.to_dict()),
        "source_finding_digest": _digest(raw),
    }
    if len(json.dumps(projection).encode()) > 64 * 1024:
        raise ValueError("Network review context exceeds its 64 KiB limit")
    return {**projection, "reviewed_digest": _digest(projection)}
