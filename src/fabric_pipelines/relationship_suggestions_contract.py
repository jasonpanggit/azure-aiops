"""Fabric/OneLake table contract for AI-suggested (advisory) relationships.

This is deliberately a **separate** Delta table contract from
``ontology_fabric_contracts.ONTOLOGY_RELATIONSHIPS_CONTRACT``. The
deterministic ``relationships`` table (``ontology_relationships``) is
ported field-for-field from Hermes's ``RelationshipBuilder`` and is the
sole authoritative graph -- nothing in this module ever writes to it.

``relationship_suggestions`` instead holds candidate edges proposed by a
Fabric Data Agent (see ``fabric.data_agent_manager``) analyzing the
``ontology_entities``/``ontology_relationships`` tables for patterns the
deterministic pipeline does not explicitly encode (co-tagging, naming
similarity, deployment correlation, ...). Each row is a *suggestion*,
carrying a confidence score and a human-readable rationale, and is meant
to be reviewed by a person before (if ever) being promoted into the real
``relationships`` graph -- this module provides no merge/promotion path,
by design (Security Domain / human-in-the-loop requirement)."""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa

from .ontology_fabric_contracts import OntologyFabricContract

#: Mirrors ``ONTOLOGY_RELATIONSHIPS_CONTRACT``'s subject/predicate/object
#: shape (Don't Hand-Roll -- same identity vocabulary as the deterministic
#: relationships table) plus ``confidence``/``rationale``/``suggested_by``
#: columns unique to advisory output, and a ``status`` column so a human
#: reviewer can record accept/reject without deleting the audit trail.
_RELATIONSHIP_SUGGESTIONS_SCHEMA = pa.schema(
    [
        pa.field("tenant_id", pa.string(), nullable=False),
        pa.field("subscription_id", pa.string(), nullable=False),
        pa.field("resource_id", pa.string(), nullable=False),
        pa.field("timestamp", pa.string(), nullable=False),
        pa.field("change_version", pa.string(), nullable=False),
        pa.field("ingestion_run_id", pa.string(), nullable=False),
        pa.field("suggestion_id", pa.string(), nullable=False),
        pa.field("subject_id", pa.string(), nullable=False),
        pa.field("subject_type", pa.string(), nullable=False),
        pa.field("predicate", pa.string(), nullable=False),
        pa.field("object_id", pa.string(), nullable=False),
        pa.field("object_type", pa.string(), nullable=False),
        pa.field("confidence", pa.float64(), nullable=False),
        pa.field("rationale", pa.string(), nullable=False),
        pa.field("suggested_by", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
    ]
)

RELATIONSHIP_SUGGESTIONS_CONTRACT = OntologyFabricContract(
    logical_name="ontology/relationship_suggestions",
    table_name="relationship_suggestions",
    schema=_RELATIONSHIP_SUGGESTIONS_SCHEMA,
    required_fields=(
        "tenant_id",
        "subscription_id",
        "resource_id",
        "timestamp",
        "change_version",
        "ingestion_run_id",
        "suggestion_id",
        "subject_id",
        "predicate",
        "object_id",
        "confidence",
    ),
    identity_fields=("resource_id",),
)

#: Every row written to the suggestions table starts in this state -- a
#: human reviewer (via the Fabric portal, a downstream app, whatever) is
#: expected to update ``status`` to "accepted"/"rejected" out of band. No
#: code in this repo transitions a suggestion's status automatically or
#: reads suggestions back into the authoritative relationships table.
DEFAULT_SUGGESTION_STATUS = "pending_review"


@dataclass(frozen=True)
class RelationshipSuggestion:
    """One AI-proposed candidate relationship, prior to Delta-row shaping.

    ``suggest_relationships()`` (in ``fabric.data_agent_manager``) returns a
    list of these; ``to_suggestion_row()`` below shapes each into the
    ``relationship_suggestions`` Delta schema."""

    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    confidence: float
    rationale: str
    suggested_by: str = "fabric_data_agent"


def to_suggestion_row(
    suggestion: RelationshipSuggestion,
    *,
    tenant_id: str,
    subscription_id: str,
    run_id: str,
    timestamp: str,
    change_version: str,
    suggestion_id: str,
) -> dict[str, object]:
    """Shapes one ``RelationshipSuggestion`` into a
    ``relationship_suggestions`` Delta row, mirroring how
    ``ontology_pipeline.derive_relationships`` shapes deterministic edges
    into ``ontology_relationships`` rows -- but landing in the separate
    advisory table, never the authoritative one."""

    return {
        "tenant_id": tenant_id,
        "subscription_id": subscription_id,
        "resource_id": suggestion.subject_id,
        "timestamp": timestamp,
        "change_version": change_version,
        "ingestion_run_id": run_id,
        "suggestion_id": suggestion_id,
        "subject_id": suggestion.subject_id,
        "subject_type": suggestion.subject_type,
        "predicate": suggestion.predicate,
        "object_id": suggestion.object_id,
        "object_type": suggestion.object_type,
        "confidence": float(suggestion.confidence),
        "rationale": suggestion.rationale,
        "suggested_by": suggestion.suggested_by,
        "status": DEFAULT_SUGGESTION_STATUS,
    }


__all__ = [
    "DEFAULT_SUGGESTION_STATUS",
    "RELATIONSHIP_SUGGESTIONS_CONTRACT",
    "RelationshipSuggestion",
    "to_suggestion_row",
]
