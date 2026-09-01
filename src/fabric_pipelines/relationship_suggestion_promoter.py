"""Confidence/known-entity gate for promoting Fabric Data Agent suggestions.

``relationship_suggestions_contract`` intentionally provides no merge path
into the authoritative graph -- by design, every suggestion is meant to be
reviewed by a human before being promoted (see that module's docstring and
``docs/fabric-data-agent-relationship-suggestions.md``).

This module does not weaken that guarantee. It adds a *triage* step that
runs **before** the human review queue: a suggestion is only auto-promoted
when it clears both of:

1. ``confidence >= auto_accept_threshold`` -- the Data Agent itself is
   confident in the relationship.
2. Both ``subject_id`` and ``object_id`` are already known entities in the
   current ontology graph -- promoting a relationship whose endpoint
   doesn't exist yet would just become another dangling edge (see
   ``ontology.pending_relationships`` for the deferred-edge alternative
   used for deterministic relationships).

Everything else -- low confidence, or referencing an entity the graph
hasn't discovered yet -- is left untouched in the suggestions list, meant
for the human-review queue exactly as before. This module does not build
that UI/queue; it only produces the split.
"""

from __future__ import annotations

import json

from ontology.entity_builder import stable_version
from ontology.relationship_builder import _relationship_id

from .relationship_suggestions_contract import RelationshipSuggestion

#: Distinct provenance ``source`` for auto-promoted (above-threshold,
#: both-endpoints-known) suggestions, so a reader of ``ontology_relationships``
#: can tell these apart from both deterministic ``RelationshipBuilder`` rows
#: and from ``APPROVED_SUGGESTION_RELATIONSHIP_SOURCE`` (human-approved via
#: the existing feedback loop) -- three provenance states, three sources.
AUTO_PROMOTED_SUGGESTION_SOURCE = "fabric_data_agent_llm"

DEFAULT_AUTO_ACCEPT_THRESHOLD = 0.85


def _promoted_row(suggestion: RelationshipSuggestion, *, run_id: str) -> dict[str, object]:
    """Shapes one auto-promoted suggestion into an ``ontology_relationships``-shaped
    row, mirroring ``RelationshipBuilder.connect()``'s row shape and reusing its
    ``_relationship_id``/``stable_version`` content-addressing (Don't Hand-Roll)
    so a promoted suggestion and a deterministically-derived edge for the same
    subject/predicate/object collide on the same ``resource_id`` rather than
    silently coexisting as two different rows."""
    relationship_id = _relationship_id(suggestion.subject_id, suggestion.predicate, suggestion.object_id)
    row: dict[str, object] = {
        "tenant_id": "",
        "subscription_id": "",
        "resource_id": relationship_id,
        "timestamp": "",
        "change_version": "",
        "ingestion_run_id": run_id,
        "subject_id": suggestion.subject_id,
        "subject_type": suggestion.subject_type,
        "predicate": suggestion.predicate,
        "object_id": suggestion.object_id,
        "object_type": suggestion.object_type,
        "confidence": float(suggestion.confidence),
        "source": AUTO_PROMOTED_SUGGESTION_SOURCE,
        "payload_json": json.dumps(
            {"rationale": suggestion.rationale, "suggested_by": suggestion.suggested_by},
            sort_keys=True,
        ),
        "lineage_json": json.dumps(
            {"source_entity_ids": [suggestion.subject_id, suggestion.object_id]},
            sort_keys=True,
        ),
        "lifecycle_status": "active",
        "valid_from": "",
        "retired_at": "",
        "ontology_version": "1",
    }
    row["change_version"] = stable_version(
        {
            key: value
            for key, value in row.items()
            if key
            not in {
                "timestamp",
                "ingestion_run_id",
                "change_version",
                "valid_from",
                "retired_at",
                "ontology_version",
            }
        }
    )
    return row


def promote_suggestions(
    suggestions: list[RelationshipSuggestion],
    *,
    known_entity_ids: set[str],
    auto_accept_threshold: float = DEFAULT_AUTO_ACCEPT_THRESHOLD,
    run_id: str = "",
) -> tuple[list[dict[str, object]], list[RelationshipSuggestion]]:
    """Splits ``suggestions`` into (auto-promoted rows, still-for-review suggestions).

    Args:
        suggestions: candidate relationships from a Fabric Data Agent.
        known_entity_ids: casefolded resource ids already present in the
            current ontology entity graph (mirrors
            ``ontology_sync._canonical_id``'s casefolding convention).
        auto_accept_threshold: minimum ``suggestion.confidence`` required to
            auto-promote (still gated on both endpoints being known).
        run_id: stamped onto each promoted row's ``ingestion_run_id``.

    Returns:
        A ``(promoted_rows, held_for_review)`` tuple. ``promoted_rows`` are
        shaped like ``ontology_relationships`` rows with
        ``source="fabric_data_agent_llm"``. ``held_for_review`` preserves the
        original ``RelationshipSuggestion`` objects, unchanged, in their
        original order, for the human-review queue.
    """
    known = {str(entity_id).casefold() for entity_id in known_entity_ids}
    promoted: list[dict[str, object]] = []
    held_for_review: list[RelationshipSuggestion] = []
    for suggestion in suggestions:
        subject_known = str(suggestion.subject_id).casefold() in known
        object_known = str(suggestion.object_id).casefold() in known
        if suggestion.confidence >= auto_accept_threshold and subject_known and object_known:
            promoted.append(_promoted_row(suggestion, run_id=run_id))
        else:
            held_for_review.append(suggestion)
    return promoted, held_for_review


__all__ = [
    "AUTO_PROMOTED_SUGGESTION_SOURCE",
    "DEFAULT_AUTO_ACCEPT_THRESHOLD",
    "promote_suggestions",
]
