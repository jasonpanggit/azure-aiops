from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from api.scope import Scope, scope_attributes
from hermes_arg_connector.ontology import generate_ontology_metadata
from storage.datasets import DatasetStore

from .materializer import materialize_graph
from .models import AuditEvent, stable_id


class SituationStore:
    """Publishes the situation collections through the existing immutable generation store."""

    def __init__(self, root: Path | str | DatasetStore) -> None:
        self.datasets = root if isinstance(root, DatasetStore) else DatasetStore(root)

    def publish(self, graph: Any, query_results: dict[str, list[dict[str, Any]]], run_metadata: dict[str, Any]) -> dict[str, Any]:
        generated = (
            {
                "situations": list(getattr(graph, "situations", [])),
                "evidence": list(getattr(graph, "evidence", [])),
                "links": list(getattr(graph, "links", [])),
                "audit_events": list(getattr(graph, "audit_events", [])),
                "source_status": list(getattr(graph, "source_status", [])),
            }
            if getattr(graph, "evidence", None) and getattr(graph, "source_status", None)
            else materialize_graph(
                graph,
                str(run_metadata.get("runId") or "unknown"),
                ingested_at=run_metadata.get("startedAt"),
            )
        )
        for name, rows in generated.items():
            setattr(graph, name, rows)
        datasets = {
            f"situations/{name}": list(rows)
            for name, rows in generated.items()
        }
        entities = getattr(graph, "entities", {})
        return self.datasets.publish(
            datasets,
            query_results,
            run_metadata,
            ontology=generate_ontology_metadata(entities),
        )

    def provider(self) -> SituationReadProvider:
        return SituationReadProvider(self.datasets)


class SituationReadProvider:
    def __init__(
        self,
        datasets: DatasetStore | None,
        *,
        situations: Iterable[dict[str, Any]] | None = None,
        evidence: Iterable[dict[str, Any]] | None = None,
        links: Iterable[dict[str, Any]] | None = None,
        audits: Iterable[dict[str, Any]] | None = None,
        source_status: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        self.datasets = datasets
        self._situations = list(situations) if situations is not None else None
        self._evidence = list(evidence) if evidence is not None else None
        self._links = list(links) if links is not None else None
        self._audits = list(audits) if audits is not None else None
        self._source_status = list(source_status) if source_status is not None else None

    def _rows(self, kind: str) -> list[dict[str, Any]]:
        override = getattr(self, f"_{kind}")
        if override is not None:
            return override
        return (
            self.datasets.read_dataset(f"situations/{kind}")
            if self.datasets is not None
            else []
        )

    def list(self, scope: Scope, *, query: str = "", priority: str = "") -> list[dict[str, Any]]:
        rows = self._rows("situations")
        query = query.casefold().strip()
        return [
            row for row in rows
            if scope.matches(_scope_attributes(row)) or scope.is_unrestricted()
            if not query or query in " ".join(str(value) for value in row.values()).casefold()
            if not priority or str(row.get("priority", "")).casefold() == priority.casefold()
        ]

    def get(self, situation_id: str, scope: Scope) -> dict[str, Any] | None:
        row = next((item for item in self._rows("situations") if item.get("situation_id") == situation_id), None)
        if row is None or (not scope.is_unrestricted() and not scope.matches(_scope_attributes(row))):
            return None
        evidence = [
            item
            for item in self._rows("evidence")
            if item.get("situation_id") == situation_id and _nested_matches(item, scope, row)
        ]
        links = [
            item
            for item in self._rows("links")
            if item.get("situation_id") == situation_id and _nested_matches(item, scope, row)
        ]
        statuses = [
            item
            for item in self._rows("source_status")
            if _nested_matches(item, scope, row)
        ]
        return {
            **row,
            "evidence": evidence,
            "links": links,
            "source_status": statuses,
        }

    def evidence(self, evidence_id: str, scope: Scope) -> dict[str, Any] | None:
        row = next((item for item in self._rows("evidence") if item.get("evidence_id") == evidence_id), None)
        if row is None:
            return None
        situation_id = str(row.get("situation_id") or "")
        visible = self.get(situation_id, scope)
        if visible is None:
            return None
        return (
            row
            if any(item.get("evidence_id") == evidence_id for item in visible["evidence"])
            else None
        )

    def audit(self, situation_id: str, scope: Scope) -> list[dict[str, Any]] | None:
        visible = self.get(situation_id, scope)
        if visible is None:
            return None
        evidence_ids = {
            str(item.get("evidence_id") or "") for item in visible.get("evidence", [])
        }
        source_ids = {
            str(item.get("source_object_id") or "") for item in visible.get("evidence", [])
        }
        source_ids = {
            str(item.get("source_object_id") or "") for item in visible.get("evidence", [])
        }
        rows = []
        for row in self._rows("audits"):
            if row.get("situation_id") != situation_id:
                continue
            if not _nested_matches(row, scope, visible):
                continue
            event = dict(row)
            event["evidence_ids"] = [
                value for value in event.get("evidence_ids") or [] if value in evidence_ids
            ]
            event["source_references"] = [
                value
                for value in event.get("source_references") or []
                if value in source_ids
            ]
            rows.append(event)
        return sorted(rows, key=lambda row: str(row.get("timestamp", "")), reverse=True)


def _scope_attributes(row: dict[str, Any]) -> dict[str, str]:
    attributes = scope_attributes(row)
    nested = row.get("scope")
    if isinstance(nested, dict):
        for dimension, values in nested.items():
            if values and dimension not in attributes:
                attributes[dimension] = str(values[0])
    return attributes


def _nested_matches(row: dict[str, Any], scope: Scope, parent: dict[str, Any]) -> bool:
    if scope.is_unrestricted():
        return True
    attributes = _scope_attributes(row)
    for scope_key in ("requested_scope", "scope_snapshot"):
        requested = row.get(scope_key)
        if isinstance(requested, dict):
            for dimension, values in requested.items():
                allowed = scope.values(dimension)
                if allowed and values and not allowed.intersection(
                    str(value).casefold() for value in values
                ):
                    return False
    parent_scope = parent.get("scope") if isinstance(parent.get("scope"), dict) else {}
    for value in _referenced_ids(row):
        match = re.search(r"/subscriptions/([^/]+)", value, re.IGNORECASE)
        if match:
            attributes.setdefault("subscription", match.group(1).casefold())
    for dimension, values in parent_scope.items():
        if values:
            attributes.setdefault(dimension, str(values[0]).casefold())
    return scope.matches(attributes)


def _referenced_ids(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("resource_id", "entity_id", "source_object_id"):
        value = row.get(key)
        if value:
            values.append(str(value))
    for key in ("resource_ids", "entity_ids", "source_references"):
        value = row.get(key) or []
        values.extend(str(item) for item in value if item)
    return values


class AppendOnlyAuditLog:
    """Small pre-Delta guard that rejects mutation of an immutable event key."""

    def __init__(self) -> None:
        self._events: dict[str, AuditEvent] = {}

    def append(self, event: AuditEvent) -> AuditEvent:
        previous = self._events.get(event.event_id)
        if previous is not None and previous != event:
            raise ValueError(f"Audit event {event.event_id} is immutable")
        self._events[event.event_id] = event
        return event

    def rows(self) -> list[dict[str, Any]]:
        return [event.model_dump() for event in self._events.values()]

    def record(
        self,
        *,
        actor: str,
        action: str,
        timestamp: str,
        situation_id: str,
        evidence_ids: list[str] | None = None,
        source_references: list[str] | None = None,
        scope_snapshot: dict[str, list[str]] | None = None,
        run_id: str = "",
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=stable_id("audit", action, situation_id, timestamp),
            actor=actor,
            action=action,
            timestamp=timestamp,
            situation_id=situation_id,
            evidence_ids=evidence_ids or [],
            source_references=source_references or [],
            scope_snapshot=scope_snapshot or {},
            run_id=run_id,
        )
        return self.append(event)
