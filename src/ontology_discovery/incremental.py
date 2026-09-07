"""Deterministic incremental classification and bounded evidence batching."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .contracts import (
    MAX_CANDIDATE_PAIRS,
    MAX_CHANGED_ENTITIES,
    MAX_EVIDENCE_RECORDS,
    EvidenceBatch,
)

_GRAPH_SECTIONS = ("entities", "relationships", "pending")


class BatchRejectionReason(str, Enum):
    """Stable failure classes for inputs that cannot become safe batches."""

    MALFORMED_RECORD = "malformed_record"
    CROSS_SCOPE = "cross_scope"
    INDIVISIBLE_RECORD = "indivisible_record"


class EvidenceBatchRejected(ValueError):
    """Raised before dispatch when an input record cannot be batched safely."""

    def __init__(
        self,
        reason: BatchRejectionReason,
        message: str,
        *,
        record_id: str = "",
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.record_id = record_id


@dataclass(frozen=True)
class IncrementalDelta:
    """Five-way diff plus the provenance needed to replay it durably."""

    added: tuple[str, ...]
    changed: tuple[str, ...]
    retired: tuple[str, ...]
    unresolved: tuple[str, ...]
    stale: tuple[str, ...]
    source_generation_id: str
    observed_at: datetime
    freshness: str
    coverage: str
    current_row_hashes: Mapping[str, str]
    authoritative: bool

    def apply_to(self, previous_row_hashes: Mapping[str, str]) -> dict[str, str]:
        """Apply the observation without inventing retirements for partial scans."""
        if self.authoritative:
            return dict(self.current_row_hashes)
        merged = dict(previous_row_hashes)
        merged.update(self.current_row_hashes)
        return merged

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-safe checkpoint payload."""
        return {
            "added": list(self.added),
            "changed": list(self.changed),
            "retired": list(self.retired),
            "unresolved": list(self.unresolved),
            "stale": list(self.stale),
            "source_generation_id": self.source_generation_id,
            "observed_at": self.observed_at.astimezone(UTC).isoformat(),
            "freshness": self.freshness,
            "coverage": self.coverage,
            "current_row_hashes": dict(sorted(self.current_row_hashes.items())),
            "authoritative": self.authoritative,
        }


def classify_incremental(
    *,
    previous_row_hashes: Mapping[str, str],
    current_row_hashes: Mapping[str, str],
    source_generation_id: str,
    observed_at: datetime,
    freshness: str,
    coverage: str,
    unresolved_ids: Iterable[str] = (),
    stale_ids: Iterable[str] = (),
) -> IncrementalDelta:
    """Classify a normalized snapshot without treating bounded scans as absence."""
    generation = str(source_generation_id or "").strip()
    if not generation:
        raise ValueError("source_generation_id must not be empty")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    normalized_freshness = str(freshness or "").strip().casefold()
    normalized_coverage = str(coverage or "").strip().casefold()
    if not normalized_freshness:
        raise ValueError("freshness must not be empty")
    if normalized_coverage not in {"complete", "partial", "degraded"}:
        raise ValueError("coverage must be complete, partial, or degraded")

    previous = _normalized_hashes(previous_row_hashes)
    current = _normalized_hashes(current_row_hashes)
    unresolved = {_identifier(value) for value in unresolved_ids if _identifier(value)}
    stale = {_identifier(value) for value in stale_ids if _identifier(value)}
    added = set(current) - set(previous)
    changed = {
        resource_id
        for resource_id in set(current) & set(previous)
        if current[resource_id] != previous[resource_id]
    }
    missing = set(previous) - set(current)
    authoritative = (
        normalized_coverage == "complete"
        and normalized_freshness not in {"degraded", "unknown"}
    )
    if authoritative:
        retired = missing - unresolved
    else:
        retired = set()
        unresolved |= missing

    return IncrementalDelta(
        added=tuple(sorted(added)),
        changed=tuple(sorted(changed)),
        retired=tuple(sorted(retired)),
        unresolved=tuple(sorted(unresolved)),
        stale=tuple(sorted(stale)),
        source_generation_id=generation,
        observed_at=observed_at,
        freshness=normalized_freshness,
        coverage=normalized_coverage,
        current_row_hashes=current,
        authoritative=authoritative,
    )


def normalize_graph_state(
    *,
    entities: Iterable[Mapping[str, Any]],
    relationships: Iterable[Mapping[str, Any]],
    pending_relationships: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Canonicalize a graph so full rebuild and replay have one parity contract."""

    return {
        "entities": _canonical_records(entities, ("resource_id", "entity_id", "id")),
        "relationships": _canonical_records(
            relationships, ("resource_id", "relationship_id", "pair_id")
        ),
        "pending": _canonical_records(
            pending_relationships, ("pending_id", "resource_id", "relationship_id")
        ),
    }


def canonical_graph_hash(graph: Mapping[str, Any]) -> str:
    """Hash a normalized graph independent of input order and duplicate delivery."""

    normalized = normalize_graph_state(
        entities=_graph_rows(graph, "entities"),
        relationships=_graph_rows(graph, "relationships"),
        pending_relationships=_graph_rows(graph, "pending"),
    )
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def compare_graph_parity(
    full_graph: Mapping[str, Any],
    incremental_graph: Mapping[str, Any],
) -> dict[str, Any]:
    """Return opaque parity evidence; the full graph is always repair authority."""

    normalized_full = normalize_graph_state(
        entities=_graph_rows(full_graph, "entities"),
        relationships=_graph_rows(full_graph, "relationships"),
        pending_relationships=_graph_rows(full_graph, "pending"),
    )
    normalized_incremental = normalize_graph_state(
        entities=_graph_rows(incremental_graph, "entities"),
        relationships=_graph_rows(incremental_graph, "relationships"),
        pending_relationships=_graph_rows(incremental_graph, "pending"),
    )
    full_hash = canonical_graph_hash(normalized_full)
    incremental_hash = canonical_graph_hash(normalized_incremental)
    counts = {
        section: abs(
            len(normalized_full[section]) - len(normalized_incremental[section])
        )
        for section in _GRAPH_SECTIONS
    }
    drift_count = sum(counts.values())
    if full_hash != incremental_hash and drift_count == 0:
        drift_count = 1
    drift_hash = hashlib.sha256(
        f"{full_hash}|{incremental_hash}|{drift_count}".encode()
    ).hexdigest()
    return {
        "status": "in_sync" if full_hash == incremental_hash else "drift_detected",
        "full_graph_hash": full_hash,
        "incremental_graph_hash": incremental_hash,
        "drift_count": drift_count,
        "drift_hash": drift_hash,
        "repair_authority": "full",
    }


def split_evidence_batches(
    *,
    changed_entities: Iterable[Mapping[str, Any]],
    candidate_pairs: Iterable[Mapping[str, Any]],
    evidence_records: Iterable[Mapping[str, Any]],
    source_generation_id: str,
    observed_at: datetime,
    freshness: str,
    coverage: str,
) -> list[EvidenceBatch]:
    """Split complete records by scope and connected component under hard caps."""
    generation = str(source_generation_id or "").strip()
    if not generation:
        raise ValueError("source_generation_id must not be empty")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")

    typed_records = {
        "entity": _validated_records(changed_entities, "entity"),
        "pair": _validated_records(candidate_pairs, "pair"),
        "evidence": _validated_records(evidence_records, "evidence"),
    }
    scopes = sorted(
        {
            str(record["scope"])
            for records in typed_records.values()
            for record in records
        }
    )
    batches: list[EvidenceBatch] = []
    for scope in scopes:
        scoped = {
            kind: [record for record in records if record["scope"] == scope]
            for kind, records in typed_records.items()
        }
        components = _connected_components(scoped)
        for component_key in sorted(components):
            component = components[component_key]
            chunks = max(
                _chunk_count(len(component["entity"]), MAX_CHANGED_ENTITIES),
                _chunk_count(len(component["pair"]), MAX_CANDIDATE_PAIRS),
                _chunk_count(len(component["evidence"]), MAX_EVIDENCE_RECORDS),
            )
            for index in range(chunks):
                entities = _slice(component["entity"], index, MAX_CHANGED_ENTITIES)
                pairs = _slice(component["pair"], index, MAX_CANDIDATE_PAIRS)
                evidence = _slice(component["evidence"], index, MAX_EVIDENCE_RECORDS)
                record_ids = [
                    _record_identifier(record, kind)
                    for kind, records in (
                        ("entity", entities),
                        ("pair", pairs),
                        ("evidence", evidence),
                    )
                    for record in records
                ]
                identity = json.dumps(
                    {
                        "source_generation_id": generation,
                        "scope": scope,
                        "component": component_key,
                        "index": index,
                        "record_ids": record_ids,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                batch_id = "OEB-" + hashlib.sha256(identity.encode()).hexdigest()[:20].upper()
                batches.append(
                    EvidenceBatch(
                        batch_id=batch_id,
                        scope=scope,
                        source_generation_id=generation,
                        observed_at=observed_at,
                        freshness=freshness,
                        coverage=coverage,
                        changed_entities=tuple(entities),
                        candidate_pairs=tuple(pairs),
                        evidence_records=tuple(evidence),
                    )
                )
    return batches


def _normalized_hashes(values: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_id, raw_hash in values.items():
        resource_id = _identifier(raw_id)
        value = str(raw_hash or "").strip()
        if not resource_id or not value:
            raise ValueError("row hashes require non-empty resource IDs and hashes")
        if resource_id in normalized and normalized[resource_id] != value:
            raise ValueError("row hash identifiers collide after normalization")
        normalized[resource_id] = value
    return normalized


def _graph_rows(graph: Mapping[str, Any], section: str) -> list[Mapping[str, Any]]:
    value = graph.get(section, ())
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(row, Mapping) for row in value
    ):
        raise TypeError(f"graph {section} must be a list of records")
    return list(value)


def _canonical_records(
    values: Iterable[Mapping[str, Any]],
    identity_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for value in values:
        record = copy.deepcopy(dict(value))
        identity = next(
            (
                _identifier(record.get(field))
                for field in identity_fields
                if _identifier(record.get(field))
            ),
            "",
        )
        if not identity:
            raise ValueError("canonical graph record has no stable identity")
        for key in (
            "resource_id",
            "entity_id",
            "relationship_id",
            "pending_id",
            "subject_id",
            "object_id",
        ):
            if key in record:
                record[key] = _identifier(record[key])
        existing = records.get(identity)
        if existing is not None and existing != record:
            raise ValueError("canonical graph identity has conflicting content")
        records[identity] = record
    return [records[key] for key in sorted(records)]


def _identifier(value: object) -> str:
    return str(value or "").strip().casefold()


def _validated_records(
    values: Iterable[Mapping[str, Any]], kind: str
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, Mapping):
            raise EvidenceBatchRejected(
                BatchRejectionReason.MALFORMED_RECORD,
                f"{kind} record must be a mapping",
            )
        record = copy.deepcopy(dict(value))
        record_id = _record_identifier(record, kind)
        scope = str(record.get("scope") or "").strip()
        if not record_id or not scope:
            raise EvidenceBatchRejected(
                BatchRejectionReason.MALFORMED_RECORD,
                f"{kind} record requires an identity and scope",
                record_id=record_id,
            )
        if record_id in seen:
            raise EvidenceBatchRejected(
                BatchRejectionReason.MALFORMED_RECORD,
                f"duplicate {kind} record identity",
                record_id=record_id,
            )
        seen.add(record_id)
        record["scope"] = scope
        if kind == "pair" and (
            not _identifier(record.get("subject_id"))
            or not _identifier(record.get("object_id"))
        ):
            raise EvidenceBatchRejected(
                BatchRejectionReason.MALFORMED_RECORD,
                "candidate pair requires both endpoints",
                record_id=record_id,
            )
        for endpoint_scope in ("subject_scope", "object_scope"):
            supplied_scope = str(record.get(endpoint_scope) or "").strip()
            if supplied_scope and supplied_scope != scope:
                raise EvidenceBatchRejected(
                    BatchRejectionReason.CROSS_SCOPE,
                    f"{kind} record crosses its authorized scope",
                    record_id=record_id,
                )
        if len(record.get("changed_entity_ids") or ()) > MAX_CHANGED_ENTITIES or len(
            record.get("candidate_pair_ids") or ()
        ) > MAX_CANDIDATE_PAIRS or len(
            record.get("evidence_ids") or ()
        ) > MAX_EVIDENCE_RECORDS:
            raise EvidenceBatchRejected(
                BatchRejectionReason.INDIVISIBLE_RECORD,
                f"{kind} record contains an indivisible over-limit reference set",
                record_id=record_id,
            )
        records.append(record)
    return sorted(records, key=lambda record: _priority_key(record, kind))


def _record_identifier(record: Mapping[str, Any], kind: str) -> str:
    fields = {
        "entity": ("resource_id", "entity_id", "id"),
        "pair": ("pair_id", "resource_id", "id"),
        "evidence": ("evidence_id", "resource_id", "id"),
    }[kind]
    return next((_identifier(record.get(field)) for field in fields if record.get(field)), "")


def _priority_key(record: Mapping[str, Any], kind: str) -> tuple[Any, ...]:
    authority = record.get("authority", 0)
    try:
        authority_score = float(authority)
    except (TypeError, ValueError):
        authority_score = {
            "authoritative": 4.0,
            "high": 3.0,
            "medium": 2.0,
            "low": 1.0,
        }.get(str(authority).casefold(), 0.0)
    freshness = {
        "fresh": 0,
        "current": 1,
        "unknown": 2,
        "stale": 3,
        "degraded": 4,
    }.get(str(record.get("freshness") or "").casefold(), 5)
    corroboration = record.get("corroboration", 0)
    try:
        corroboration_score = float(corroboration)
    except (TypeError, ValueError):
        corroboration_score = 0.0
    return (
        0 if record.get("endpoint_match") is True else 1,
        -authority_score,
        freshness,
        -corroboration_score,
        _record_identifier(record, kind),
    )


class _DisjointSet:
    def __init__(self) -> None:
        self.parents: dict[str, str] = {}

    def add(self, value: str) -> None:
        self.parents.setdefault(value, value)

    def find(self, value: str) -> str:
        self.add(value)
        parent = self.parents[value]
        if parent != value:
            self.parents[value] = self.find(parent)
        return self.parents[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        first, second = sorted((left_root, right_root))
        self.parents[second] = first


def _record_endpoints(record: Mapping[str, Any], kind: str) -> list[str]:
    if kind == "entity":
        return [_record_identifier(record, kind)]
    values: list[object] = [
        record.get("subject_id"),
        record.get("object_id"),
        *(record.get("entity_ids") or ()),
        *(record.get("changed_entity_ids") or ()),
    ]
    return sorted({_identifier(value) for value in values if _identifier(value)})


def _connected_components(
    scoped: Mapping[str, list[dict[str, Any]]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    disjoint = _DisjointSet()
    for kind, records in scoped.items():
        for record in records:
            endpoints = _record_endpoints(record, kind)
            if endpoints:
                disjoint.add(endpoints[0])
                for endpoint in endpoints[1:]:
                    disjoint.union(endpoints[0], endpoint)

    components: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"entity": [], "pair": [], "evidence": []}
    )
    for kind, records in scoped.items():
        for record in records:
            endpoints = _record_endpoints(record, kind)
            component = (
                disjoint.find(endpoints[0])
                if endpoints
                else f"{kind}:{_record_identifier(record, kind)}"
            )
            components[component][kind].append(record)
    for records in components.values():
        for kind in records:
            records[kind].sort(key=lambda record: _priority_key(record, kind))
    return dict(components)


def _chunk_count(size: int, limit: int) -> int:
    return (size + limit - 1) // limit


def _slice(records: list[dict[str, Any]], index: int, limit: int) -> list[dict[str, Any]]:
    return records[index * limit : (index + 1) * limit]


__all__ = [
    "BatchRejectionReason",
    "EvidenceBatchRejected",
    "IncrementalDelta",
    "classify_incremental",
    "split_evidence_batches",
]
