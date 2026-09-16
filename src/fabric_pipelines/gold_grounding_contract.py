"""Fail-closed contracts for generation-bound Gold-grounding evidence."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

_LOGGER = logging.getLogger(__name__)


class GoldGroundingStatus(StrEnum):
    """Stable outcome taxonomy for one bounded Data Agent request."""

    SUCCESS = "success"
    HEALTHY_EMPTY = "healthy_empty"
    MALFORMED = "malformed"
    DENIED = "denied"
    TIMEOUT = "timeout"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class GoldGroundedCitation(BaseModel):
    """One Gold fact bound directly to its immutable resource identity."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(..., min_length=1)
    generation_id: str = Field(..., min_length=1)
    gold_table: str = Field(..., min_length=1)
    row_key: str = Field(..., min_length=1)
    as_of: datetime
    confidence: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_resource_identity(self) -> GoldGroundedCitation:
        if not self.resource_id.startswith("/subscriptions/"):
            raise ValueError("citation resource_id must be a full ARM resource ID")
        return self


class GoldGroundedFinding(BaseModel):
    """Structured, generation-pinned Gold evidence passed to narration."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(..., min_length=1)
    generation_id: str = Field(..., min_length=1)
    citations: list[GoldGroundedCitation] = Field(..., min_length=1)
    scope_ok: bool
    summary: str = Field(..., max_length=240)

    @model_validator(mode="after")
    def validate_generation_coupling(self) -> GoldGroundedFinding:
        if not self.scope_ok:
            raise ValueError("scope_ok must be true for usable Gold evidence")
        if any(
            citation.generation_id != self.generation_id for citation in self.citations
        ):
            raise ValueError("every citation must match the finding generation")
        return self

    @property
    def resource_ids(self) -> list[str]:
        """Return deduplicated resource identities in citation order."""
        return list(dict.fromkeys(citation.resource_id for citation in self.citations))


class GoldGroundingEmptyProof(BaseModel):
    """Generation-level proof that a scoped query is genuinely empty."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy_empty"]
    generation_id: str = Field(..., min_length=1)
    gold_table: Literal["metadata_exposure_gold_generations"]
    row_key: str = Field(..., min_length=1)
    as_of: datetime
    reconciliation_status: Literal["reconciled", "reconciled_clean", "passed"]
    scoped_row_count: Literal[0]
    scope_ok: Literal[True]

    @model_validator(mode="after")
    def row_key_matches_generation(self) -> GoldGroundingEmptyProof:
        if self.row_key != self.generation_id:
            raise ValueError("healthy-empty row_key must match generation_id")
        return self


@dataclass(frozen=True)
class GoldGroundingParseResult:
    """Classified parser result without fabricated degraded evidence."""

    status: GoldGroundingStatus
    findings: tuple[GoldGroundedFinding, ...] = ()
    empty_proof: GoldGroundingEmptyProof | None = None
    reason: str = ""


def parse_gold_grounded_findings(
    response_text: str,
    *,
    expected_generation_id: str,
    empty_manifest: Mapping[str, object] | None = None,
    tool_call_id: str = "",
) -> GoldGroundingParseResult:
    """Parse one response without sleeps or partial-success fallbacks."""
    generation_id = str(expected_generation_id or "").strip()
    if not generation_id:
        raise ValueError("expected_generation_id is required")
    if not response_text.strip():
        return GoldGroundingParseResult(
            GoldGroundingStatus.MALFORMED,
            reason="Gold evidence response was blank",
        )

    parsed: list[GoldGroundedFinding] = []
    empty_proofs: list[GoldGroundingEmptyProof] = []
    saw_candidate = False
    for raw_line in response_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```") or not line.startswith("{"):
            continue
        saw_candidate = True
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            _LOGGER.warning(
                "Gold finding validation failed for tool_call_id=%s error=%s",
                tool_call_id,
                exc.__class__.__name__,
            )
            return GoldGroundingParseResult(
                GoldGroundingStatus.MALFORMED,
                reason="unparseable Gold evidence",
            )
        if not isinstance(payload, dict):
            return GoldGroundingParseResult(
                GoldGroundingStatus.MALFORMED,
                reason="Gold evidence line must be a JSON object",
            )
        if payload.get("status") == GoldGroundingStatus.HEALTHY_EMPTY.value:
            try:
                proof = GoldGroundingEmptyProof.model_validate(payload)
            except ValidationError:
                return GoldGroundingParseResult(
                    GoldGroundingStatus.MALFORMED,
                    reason="invalid healthy-empty proof",
                )
            if proof.generation_id != generation_id:
                return GoldGroundingParseResult(
                    GoldGroundingStatus.STALE,
                    reason="Gold empty proof generation does not match the pinned ontology generation",
                )
            empty_proofs.append(proof)
            continue
        try:
            finding = GoldGroundedFinding.model_validate(payload)
        except ValidationError:
            return GoldGroundingParseResult(
                GoldGroundingStatus.MALFORMED,
                reason="unparseable Gold evidence",
            )
        if finding.generation_id != generation_id:
            return GoldGroundingParseResult(
                GoldGroundingStatus.STALE,
                reason="Gold evidence generation does not match the pinned ontology generation",
            )
        parsed.append(finding)

    if empty_proofs:
        if len(empty_proofs) != 1 or parsed:
            return GoldGroundingParseResult(
                GoldGroundingStatus.MALFORMED,
                reason="healthy-empty response must contain exactly one proof",
            )
        proof = empty_proofs[0]
        if not _empty_proof_matches_manifest(proof, empty_manifest):
            return GoldGroundingParseResult(
                GoldGroundingStatus.MALFORMED,
                reason="healthy-empty proof does not match authoritative manifest",
            )
        return GoldGroundingParseResult(
            GoldGroundingStatus.HEALTHY_EMPTY,
            empty_proof=proof,
        )
    if not saw_candidate or not parsed:
        return GoldGroundingParseResult(
            GoldGroundingStatus.MALFORMED,
            reason="unparseable Gold evidence",
        )
    return GoldGroundingParseResult(
        GoldGroundingStatus.SUCCESS,
        findings=tuple(parsed),
    )


def _empty_proof_matches_manifest(
    proof: GoldGroundingEmptyProof,
    manifest: Mapping[str, object] | None,
) -> bool:
    if not isinstance(manifest, Mapping):
        return False
    try:
        authoritative = GoldGroundingEmptyProof.model_validate(manifest)
    except ValidationError:
        return False
    return authoritative == proof


__all__ = [
    "GoldGroundedCitation",
    "GoldGroundedFinding",
    "GoldGroundingEmptyProof",
    "GoldGroundingParseResult",
    "GoldGroundingStatus",
    "parse_gold_grounded_findings",
]
