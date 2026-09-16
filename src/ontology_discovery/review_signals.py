"""Deterministic ontology quality signals for advisory review narration."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from fabric.dataset_mapper import is_allowed_relationship_triple

_INACTIVE = {"deleted", "deleting", "retired", "terminated", "decommissioned"}


def build_review_signals(
    *,
    entities: Sequence[Mapping[str, Any]],
    relationships: Sequence[Mapping[str, Any]],
    source_generation_id: str,
) -> dict[str, Any]:
    """Summarize deterministic defects and distributions for an advisory agent."""
    generation_id = str(source_generation_id or "").strip()
    if not generation_id:
        raise ValueError("source_generation_id is required")

    entity_index = {
        str(row.get("resource_id") or "").casefold(): row
        for row in entities
        if str(row.get("resource_id") or "").strip()
    }
    active_ids = {
        entity_id
        for entity_id, row in entity_index.items()
        if str(row.get("lifecycle_status") or "active").casefold() not in _INACTIVE
    }
    connected: set[str] = set()
    dangling = 0
    stale_or_retired = 0
    vocabulary_drift = 0
    temporal_inconsistencies = 0
    missing_lineage = 0
    confidence = Counter[str]()
    provenance = Counter[str]()

    for row in relationships:
        subject_id = str(row.get("subject_id") or "").casefold()
        object_id = str(row.get("object_id") or "").casefold()
        subject = entity_index.get(subject_id)
        object_ = entity_index.get(object_id)
        if subject is None or object_ is None:
            dangling += 1
        else:
            connected.update((subject_id, object_id))
            if (
                str(subject.get("lifecycle_status") or "active").casefold() in _INACTIVE
                or str(object_.get("lifecycle_status") or "active").casefold()
                in _INACTIVE
            ):
                stale_or_retired += 1
        if str(row.get("lifecycle_status") or "active").casefold() in _INACTIVE:
            stale_or_retired += 1
        if not is_allowed_relationship_triple(
            str(row.get("subject_type") or ""),
            str(row.get("predicate") or ""),
            str(row.get("object_type") or ""),
        ):
            vocabulary_drift += 1
        if _retired_before_valid(row):
            temporal_inconsistencies += 1
        if not str(row.get("lineage_json") or "").strip():
            missing_lineage += 1
        score = float(row.get("confidence") or 0.0)
        confidence["high" if score >= 0.8 else "medium" if score >= 0.5 else "low"] += 1
        provenance[str(row.get("source") or "unknown")] += 1

    orphan_count = len(active_ids - connected)
    active_count = len(active_ids)
    return {
        "source_generation_id": generation_id,
        "verdict_owner": "deterministic_pipeline",
        "advisory_use": "explain_and_prioritize_only",
        "violations": {
            "dangling_relationships": dangling,
            "orphan_entities": orphan_count,
            "vocabulary_or_type_drift": vocabulary_drift,
            "stale_or_retired_links": stale_or_retired,
            "temporal_inconsistencies": temporal_inconsistencies,
        },
        "topology_completeness": {
            "active_entities": active_count,
            "connected_active_entities": len(active_ids & connected),
            "ratio": round(len(active_ids & connected) / active_count, 6)
            if active_count
            else 1.0,
        },
        "confidence_distribution": dict(sorted(confidence.items())),
        "provenance_distribution": dict(sorted(provenance.items())),
        "lineage_health": {
            "relationships": len(relationships),
            "missing_lineage": missing_lineage,
        },
        "medallion_health": {
            "generation_bound": True,
            "entity_count": len(entities),
            "relationship_count": len(relationships),
        },
    }


def _retired_before_valid(row: Mapping[str, Any]) -> bool:
    valid_from = str(row.get("valid_from") or "").strip()
    retired_at = str(row.get("retired_at") or "").strip()
    if not valid_from or not retired_at:
        return False
    try:
        return datetime.fromisoformat(retired_at) < datetime.fromisoformat(valid_from)
    except ValueError:
        return True


__all__ = ["build_review_signals"]
