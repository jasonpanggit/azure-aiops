from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from .models import (
    AuditEvent,
    EvidenceRecord,
    Situation,
    SituationLink,
    SourceStatus,
    stable_id,
)

_FAMILY_ALIASES = {
    "arg": "arg_activity_log",
    "resource_changes": "arg_activity_log",
    "activity_log": "arg_activity_log",
    "monitor": "monitor",
    "service_health": "service_health",
    "defender": "defender",
    "policy": "policy",
    "vulnerability": "vulnerability",
}


def _iso(value: datetime | str | None) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return str(value or "").strip()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _resource_ids(row: Mapping[str, Any]) -> list[str]:
    values = row.get("resource_ids") or row.get("target_resource_ids") or []
    if isinstance(values, str):
        values = [values]
    target = (
        row.get("resource_id")
        or row.get("target_resource_id")
        or row.get("targetResourceId")
        or row.get("resourceId")
    )
    return sorted({str(item).strip().casefold() for item in [target, *values] if str(item or "").strip()})


def _scope(row: Mapping[str, Any], resources: Iterable[Mapping[str, Any]] = ()) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    aliases = {
        "subscription": ("subscription", "subscription_id", "subscriptionId"),
        "business_service": ("business_service", "businessService"),
        "application": ("application", "applicationName"),
        "environment": ("environment", "environmentName"),
        "owner": ("owner", "project_owner"),
        "region": ("region", "location"),
    }
    candidates = [row, *resources]
    for dimension, keys in aliases.items():
        values = sorted(
            {
                str(candidate.get(key)).strip().casefold()
                for candidate in candidates
                for key in keys
                if candidate.get(key)
            }
        )
        if values:
            result[dimension] = values
    return result


def _priority(severity: str) -> str:
    value = severity.casefold()
    return "P1" if value in {"critical", "sev0", "sev1"} else "P2" if value in {"high", "sev2"} else "P3"


def materialize_graph(graph: Any, run_id: str, *, ingested_at: datetime | str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Materialize normalized resource changes without storing raw source payloads in situations."""
    ingested = _iso(ingested_at or datetime.now(UTC))
    entity_by_id = {
        str(row.get("id") or "").casefold(): row
        for rows in getattr(graph, "entities", {}).values()
        for row in rows
        if row.get("id")
    }
    situations: list[Situation] = []
    evidence: list[EvidenceRecord] = []
    links: list[SituationLink] = []
    audits: list[AuditEvent] = []
    for change in getattr(graph, "changes", ()):
        resource_ids = _resource_ids(change)
        if not resource_ids:
            continue
        target = resource_ids[0]
        resource = entity_by_id.get(target, {})
        observed = str(change.get("changedAt") or change.get("lastObservedTimestamp") or ingested)
        source_id = str(change.get("id") or stable_id("source", target, observed))
        fingerprint = hashlib.sha256(
            _canonical(
                {
                    key: value
                    for key, value in change.items()
                    if key not in {"properties", "lastObservedTimestamp"}
                }
            ).encode()
        ).hexdigest()
        evidence_id = stable_id("evidence", "arg_activity_log", source_id, fingerprint)
        situation_id = stable_id("situation", "resource_change", target)
        severity = str(change.get("severity") or resource.get("severity") or "medium")
        tags = resource.get("tags") or {}
        owner = str(resource.get("owner") or tags.get("owner") or "")
        support_team = str(resource.get("supportTeam") or tags.get("supportgroup") or tags.get("supportTeam") or "")
        situation = Situation(
            situation_id=situation_id,
            resource_id=situation_id,
            title=str(change.get("summary") or change.get("changeType") or f"Resource change on {target}"),
            situation_type="resource_change",
            severity=severity,
            priority=_priority(severity),
            scope=_scope(change, [resource]),
            owner=owner,
            support_team=support_team,
            affected_resource_ids=resource_ids,
            linked_evidence_ids=[evidence_id],
            started_at=observed,
            last_observed_at=observed,
            evidence_state="complete",
            run_id=run_id,
        )
        item = EvidenceRecord(
            evidence_id=evidence_id,
            source_family="arg_activity_log",
            source_object_id=source_id,
            locator=str(change.get("locator") or change.get("sourceUrl") or ""),
            resource_ids=resource_ids,
            observed_at=observed,
            ingested_at=ingested,
            watermark=observed,
            provenance={"run_id": run_id, "source_system": "arg:ResourceChanges"},
            freshness="fresh",
            quality="complete",
            availability="available",
            confidence="high",
            assertion=str(change.get("changeType") or "resource changed"),
            fingerprint=fingerprint,
            situation_id=situation_id,
            run_id=run_id,
        )
        situations.append(situation)
        evidence.append(item)
        links.append(
            SituationLink(
                link_id=stable_id("link", situation_id, "Resource", target),
                situation_id=situation_id,
                entity_type="Resource",
                entity_id=target,
                relation="affects",
                provenance={"source": "arg:ResourceChanges"},
            )
        )
        audits.extend(
            [
                AuditEvent(
                    event_id=stable_id("audit", "observation", evidence_id),
                    actor="system:ingestion",
                    action="observation.recorded",
                    timestamp=observed,
                    situation_id=situation_id,
                    evidence_ids=[evidence_id],
                    source_references=[source_id],
                    run_id=run_id,
                ),
                AuditEvent(
                    event_id=stable_id("audit", "situation-created", situation_id),
                    actor="system:ingestion",
                    action="situation.created",
                    timestamp=observed,
                    situation_id=situation_id,
                    evidence_ids=[evidence_id],
                    source_references=[source_id],
                    run_id=run_id,
                ),
            ]
        )
    return {
        "situations": [row.to_dict() for row in _dedupe(situations, "situation_id")],
        "evidence": [row.to_dict() for row in _dedupe(evidence, "evidence_id")],
        "links": [row.to_dict() for row in _dedupe(links, "link_id")],
        "audit_events": [row.to_dict() for row in _dedupe(audits, "event_id")],
    }


def normalize_signal_families(
    payloads: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    run_id: str,
    ingested_at: datetime | str,
    requested_scope: dict[str, list[str]] | None = None,
) -> tuple[list[EvidenceRecord], list[SourceStatus]]:
    """Normalize six source families into one envelope and retain failures as status rows."""
    ingested = _iso(ingested_at)
    output: list[EvidenceRecord] = []
    statuses: list[SourceStatus] = []
    for raw_family, rows in payloads.items():
        family = _FAMILY_ALIASES.get(raw_family, raw_family)
        row_list = list(rows or ())
        failed = next((row for row in row_list if str(row.get("status") or "").casefold() in {"failed", "unavailable"}), None)
        status = "failed" if failed else "succeeded"
        watermark = max((str(row.get("watermark") or row.get("observed_at") or "") for row in row_list), default="")
        statuses.append(
            SourceStatus(
                source_family=family,
                run_id=run_id,
                status=status,
                observed_at=max((str(row.get("observed_at") or "") for row in row_list), default=""),
                ingested_at=ingested,
                watermark="" if failed else watermark,
                query_version=str((row_list[0] if row_list else {}).get("query_version") or ""),
                requested_scope=requested_scope or {},
                provider_status=str((failed or {}).get("status") or "ok"),
                freshness="unknown" if failed else "fresh",
                availability="unavailable" if failed else "available",
                quality="degraded" if failed else "complete",
                error=str((failed or {}).get("error") or ""),
            )
        )
        if failed:
            continue
        for row in row_list:
            source_id = str(row.get("source_object_id") or row.get("id") or row.get("source_id") or "").strip()
            observed = str(row.get("observed_at") or row.get("timestamp") or ingested)
            fingerprint = hashlib.sha256(_canonical({key: value for key, value in row.items() if key not in {"observed_at", "ingested_at"}}).encode()).hexdigest()
            output.append(
                EvidenceRecord(
                    evidence_id=stable_id("evidence", family, source_id, fingerprint),
                    source_family=family,
                    source_object_id=source_id or fingerprint[:24],
                    locator=str(row.get("locator") or row.get("deep_link") or ""),
                    resource_ids=_resource_ids(row),
                    entity_ids=[str(item) for item in row.get("entity_ids") or []],
                    observed_at=observed,
                    ingested_at=str(row.get("ingested_at") or ingested),
                    watermark=str(row.get("watermark") or observed),
                    ingestion_status="succeeded",
                    provenance={"run_id": run_id, "query_version": str(row.get("query_version") or "")},
                    freshness=str(row.get("freshness") or "fresh"),
                    quality=str(row.get("quality") or "complete"),
                    availability="available",
                    confidence=str(row.get("confidence") or "unknown"),
                    assertion=str(row.get("assertion") or row.get("summary") or ""),
                    fingerprint=fingerprint,
                    run_id=run_id,
                )
            )
    unique: dict[tuple[str, str], EvidenceRecord] = {}
    for item in output:
        unique[(item.source_family, item.fingerprint)] = item
    grouped: dict[str, list[EvidenceRecord]] = {}
    for item in unique.values():
        for resource_id in item.resource_ids:
            grouped.setdefault(resource_id, []).append(item)
    for items in grouped.values():
        assertions = {item.assertion for item in items if item.assertion}
        if len(assertions) > 1:
            for item in items:
                item_copy = item.model_copy(update={"quality": "contradictory"})
                unique[(item.source_family, item.fingerprint)] = item_copy
    return list(unique.values()), statuses


def _dedupe(rows: Iterable[Any], key: str) -> list[Any]:
    return list({getattr(row, key): row for row in rows}.values())
