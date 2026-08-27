"""Parses a Fabric Data Agent's free-text/line-delimited-JSON response (per
``RELATIONSHIP_SUGGESTION_INSTRUCTIONS`` in ``data_agent_manager``) into
``RelationshipSuggestion`` objects, and writes them to the advisory
``relationship_suggestions`` Delta table.

Honesty note (see ``docs/fabric-data-agent-relationship-suggestions.md``
for the full write-up): this module has NOT been exercised against a real
Data Agent invocation in this session -- Data Agent querying happens over
its MCP/OpenAI-compatible runtime endpoint (a separate surface from the
Items-management REST API that ``data_agent_manager.DataAgentManager``
uses), and this repo cannot import the official ``fabric-data-agent-sdk``
client (namespace collision with this repo's own ``src/fabric`` package --
see ``data_agent_manager``'s module docstring). The parser below is
deliberately defensive (tolerates prose before/after the JSON lines, skips
malformed lines rather than raising) because a live LLM response is not
guaranteed to be clean line-delimited JSON even when explicitly asked for
it. It is unit-tested against representative fixture text, not against a
live agent response."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable

from .relationship_suggestions_contract import (
    RELATIONSHIP_SUGGESTIONS_CONTRACT,
    RelationshipSuggestion,
    to_suggestion_row,
)

_REQUIRED_KEYS = (
    "subject_id",
    "subject_type",
    "predicate",
    "object_id",
    "object_type",
    "confidence",
    "rationale",
)


def parse_suggestions(response_text: str) -> list[RelationshipSuggestion]:
    """Extracts ``RelationshipSuggestion`` rows from a Data Agent response
    that is expected (per ``RELATIONSHIP_SUGGESTION_INSTRUCTIONS``) to
    contain one JSON object per line, but may also contain prose,
    markdown code fences, or blank lines around/between those objects --
    all tolerated by scanning line-by-line and skipping anything that
    doesn't parse as a JSON object with the required keys."""
    suggestions: list[RelationshipSuggestion] = []
    for raw_line in response_text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            continue
        if not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if not all(key in payload for key in _REQUIRED_KEYS):
            continue
        try:
            confidence = float(payload["confidence"])
        except (TypeError, ValueError):
            continue
        suggestions.append(
            RelationshipSuggestion(
                subject_id=str(payload["subject_id"]),
                subject_type=str(payload["subject_type"]),
                predicate=str(payload["predicate"]),
                object_id=str(payload["object_id"]),
                object_type=str(payload["object_type"]),
                confidence=confidence,
                rationale=str(payload["rationale"]),
                suggested_by=str(payload.get("suggested_by") or "fabric_data_agent"),
            )
        )
    return suggestions


def suggestions_to_rows(
    suggestions: Iterable[RelationshipSuggestion],
    *,
    tenant_id: str,
    subscription_id: str,
    run_id: str,
) -> list[dict[str, object]]:
    """Shapes parsed suggestions into ``relationship_suggestions`` Delta
    rows, mirroring how ``ontology_pipeline`` shapes deterministic edges
    into ``ontology_relationships`` rows for ``DeltaWriter.write()``."""
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    change_version = timestamp
    rows: list[dict[str, object]] = []
    for suggestion in suggestions:
        rows.append(
            to_suggestion_row(
                suggestion,
                tenant_id=tenant_id,
                subscription_id=subscription_id,
                run_id=run_id,
                timestamp=timestamp,
                change_version=change_version,
                suggestion_id=str(uuid.uuid4()),
            )
        )
    return rows


__all__ = [
    "RELATIONSHIP_SUGGESTIONS_CONTRACT",
    "parse_suggestions",
    "suggestions_to_rows",
]
