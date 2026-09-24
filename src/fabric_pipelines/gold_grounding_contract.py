"""Pydantic contracts and parser for Gold-grounded findings."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError, field_validator

_LOGGER = logging.getLogger(__name__)


class GoldGroundedCitation(BaseModel):
    """One curated Gold-layer fact backing a claim."""

    gold_table: str = Field(..., min_length=1)
    row_key: str = Field(..., min_length=1)
    as_of: datetime
    confidence: float = Field(..., ge=0.0, le=1.0)


class GoldGroundedFinding(BaseModel):
    """Structured Gold-grounding evidence passed to narration."""

    finding_id: str
    resource_ids: list[str]
    citations: list[GoldGroundedCitation] = Field(..., min_length=1)
    scope_ok: bool
    degraded: bool = False
    degraded_reason: str = ""
    summary: str = Field(..., max_length=240)

    @field_validator("resource_ids")
    @classmethod
    def _require_scoped_ids(cls, value: list[str]) -> list[str]:
        if any(not v.startswith("/subscriptions/") for v in value):
            raise ValueError("resource_ids must be full ARM resource IDs")
        return value


def parse_gold_grounded_findings(
    response_text: str,
    *,
    tool_call_id: str = "",
) -> list[GoldGroundedFinding]:
    """Parse validated line-delimited findings or fail closed on malformed evidence."""
    parsed: list[GoldGroundedFinding] = []
    for raw_line in response_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```"):
            continue
        if not line.startswith("{"):
            continue
        try:
            parsed.append(GoldGroundedFinding.model_validate_json(line))
            continue
        except ValidationError as exc:
            _LOGGER.warning(
                "Gold finding validation failed for tool_call_id=%s path=%s",
                tool_call_id,
                ".".join(str(part) for part in (exc.errors()[0].get("loc") or ()))
                or "unknown",
            )
        except json.JSONDecodeError:
            _LOGGER.warning(
                "Gold finding JSON parsing failed for tool_call_id=%s",
                tool_call_id,
            )
        return []

    return parsed


__all__ = [
    "GoldGroundedCitation",
    "GoldGroundedFinding",
    "parse_gold_grounded_findings",
]
