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

import json
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

#: The one status value ``ontology_pipeline.run()``'s optional feedback-loop
#: step (see its ``approved_suggestion_rows`` parameter) looks for when
#: deciding which suggestion rows to fold into the next run's authoritative
#: relationships output. A human (or a defined confidence-threshold policy)
#: is expected to set a suggestion row's ``status`` to this value out of
#: band -- nothing in this repo does so automatically.
ACCEPTED_SUGGESTION_STATUS = "accepted"

#: ``source`` value stamped onto a relationship row that originated from an
#: approved Data Agent suggestion (as opposed to ``RelationshipBuilder``'s
#: own deterministic ``source`` values, e.g. ``"tag_membership"``,
#: ``"lineage"``, etc.) -- this is the provenance tag that lets a reader of
#: ``ontology_relationships`` distinguish "Hermes/ontology_pipeline derived
#: this deterministically" from "a human approved an AI suggestion into
#: this" without losing either lineage.
APPROVED_SUGGESTION_RELATIONSHIP_SOURCE = "data_agent_suggested_approved"


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


def accepted_suggestion_to_relationship_row(
    suggestion_row: dict[str, object],
    *,
    run_id: str,
) -> dict[str, object]:
    """Converts one **already-accepted** ``relationship_suggestions`` row
    into a row shaped exactly like ``RelationshipBuilder.build``'s own
    output (``ontology_relationships`` schema), so it can be unioned
    straight into the deterministic pipeline's relationships output by
    ``ontology_pipeline.run()``'s feedback-loop step.

    This is the "approved suggestions become part of the graph going
    forward" half of the feedback loop described in
    ``docs/fabric-data-agent-relationship-suggestions.md``: promotion is a
    pure, deterministic, idempotent function of the input row (same
    ``relationship_id``/``change_version`` content-addressing scheme
    ``RelationshipBuilder._relationship_id``/``stable_version`` already use)
    -- calling this twice on the same accepted suggestion always yields the
    same row, so re-running the sync never duplicates or drifts a
    previously-approved edge.

    Deliberately reuses ``RelationshipBuilder``'s own private
    ``_relationship_id``/``stable_version`` helpers (Don't Hand-Roll --
    identical content-addressing to every deterministic relationship, so an
    approved suggestion and a deterministically-derived edge for the same
    subject/predicate/object collide on the same ``resource_id`` and can be
    conflict-detected by ``ontology_pipeline``'s merge step, rather than
    silently coexisting as two different rows)."""
    from ontology.entity_builder import stable_version
    from ontology.relationship_builder import _relationship_id

    subject_id = str(suggestion_row["subject_id"])
    predicate = str(suggestion_row["predicate"])
    object_id = str(suggestion_row["object_id"])
    relationship_id = _relationship_id(subject_id, predicate, object_id)

    row: dict[str, object] = {
        "tenant_id": str(suggestion_row.get("tenant_id") or ""),
        "subscription_id": str(suggestion_row.get("subscription_id") or ""),
        "resource_id": relationship_id,
        "timestamp": str(suggestion_row.get("timestamp") or ""),
        "change_version": "",
        "ingestion_run_id": run_id,
        "subject_id": subject_id,
        "subject_type": str(suggestion_row.get("subject_type") or ""),
        "predicate": predicate,
        "object_id": object_id,
        "object_type": str(suggestion_row.get("object_type") or ""),
        "confidence": float(suggestion_row.get("confidence") or 0.0),
        "source": APPROVED_SUGGESTION_RELATIONSHIP_SOURCE,
        "payload_json": json.dumps(
            {
                "rationale": str(suggestion_row.get("rationale") or ""),
                "suggested_by": str(suggestion_row.get("suggested_by") or ""),
                "suggestion_id": str(suggestion_row.get("suggestion_id") or ""),
            },
            sort_keys=True,
        ),
        "lineage_json": json.dumps(
            {"source_entity_ids": [subject_id, object_id]}, sort_keys=True
        ),
        "lifecycle_status": "active",
        "valid_from": str(suggestion_row.get("timestamp") or ""),
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


__all__ = [
    "ACCEPTED_SUGGESTION_STATUS",
    "APPROVED_SUGGESTION_RELATIONSHIP_SOURCE",
    "DEFAULT_SUGGESTION_STATUS",
    "RELATIONSHIP_SUGGESTIONS_CONTRACT",
    "RelationshipSuggestion",
    "accepted_suggestion_to_relationship_row",
    "to_suggestion_row",
]
