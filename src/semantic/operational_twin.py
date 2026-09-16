"""Operational digital twin composition.

The twin is a request-time projection over the durable semantic graph and live
operational providers. It does not ask AIOps to snapshot mutable facts; instead
it versions the current composed view and emits provenance for each contribution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return sha256(raw.encode("utf-8")).hexdigest()[:16]


def _version(payload: Any) -> str:
    return sha256(repr(payload).encode("utf-8")).hexdigest()[:12]


def _entity(kind: str, entity_id: str, name: str, **properties: Any) -> dict[str, Any]:
    return {
        "id": f"{kind}:{entity_id}",
        "kind": kind,
        "name": name or entity_id,
        "version": _version((kind, entity_id, properties)),
        "state": properties.pop("state", "current"),
        "confidence": properties.pop("confidence", "medium"),
        "provenance": properties.pop("provenance", []),
        "properties": properties,
    }


def _relationship(
    source: str,
    target: str,
    rel_type: str,
    *,
    confidence: str = "medium",
    provenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"rel:{_stable_id(source, target, rel_type)}",
        "source": source,
        "target": target,
        "type": rel_type,
        "confidence": confidence,
        "provenance": provenance or [],
    }


@dataclass
class OperationalTwinComposer:
    """Composes canonical twin projections from existing runtime providers."""

    semantic: Any | None = None
    network: Any | None = None
    vulnerability: Any | None = None
    incidents: Any | None = None
    remediation: Any | None = None
    scope: dict[str, Any] | None = None
    scope_filter: Any | None = None
    source_errors: list[dict[str, str]] | None = None

    def snapshot(self) -> dict[str, Any]:
        observed_at = _utc_now()
        entities: dict[str, dict[str, Any]] = {}
        relationships: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        provenance: list[dict[str, Any]] = []

        source_errors = list(self.source_errors or [])
        network_report = self._safe(
            "network",
            lambda: self.network.analyze().topology.to_dict()
            if self.network is not None
            else None,
            source_errors,
        )
        vulnerabilities = self._safe(
            "vulnerability",
            lambda: self.vulnerability.summary(self.scope_filter)
            if self.vulnerability is not None and hasattr(self.vulnerability, "summary")
            else None,
            source_errors,
        )
        incidents = self._safe(
            "incidents",
            lambda: self.incidents.report() if self.incidents is not None else None,
            source_errors,
        )
        remediation = self._safe(
            "remediation",
            lambda: self.remediation.generate_plans()
            if self.remediation is not None
            else None,
            source_errors,
        )

        semantic_ids: dict[str, str] = {}
        semantic_indexes = getattr(self.semantic, "indexes", None)
        semantic_entities = getattr(semantic_indexes, "entities", {}) if semantic_indexes is not None else {}
        for raw_id, resource in semantic_entities.items():
            if not self._in_scope(resource):
                continue
            entity_type = str(resource.get("entity_type") or "entity")
            kind = "resource" if entity_type in {"Resource", "VirtualMachine", "ArcServer", "KubernetesCluster"} else re.sub(
                r"(?<!^)(?=[A-Z])", "_", entity_type
            ).casefold()
            kind = re.sub(r"[^a-z0-9]+", "_", kind).strip("_") or "entity"
            entity_id = str(resource.get("resource_id") or raw_id)
            semantic_ids[str(raw_id)] = f"{kind}:{entity_id}"
            entity = _entity(
                kind,
                entity_id,
                str(resource.get("name") or entity_id),
                entity_type=entity_type,
                semantic=True,
                semantic_attributes=dict(resource),
                temporal_state={
                    "observed_at": getattr(self.semantic, "ontology_synchronized_at", ""),
                    "source": "semantic_graph",
                },
                provenance=[{"source": "semantic_graph", "confidence": "high"}],
            )
            entities.setdefault(entity["id"], entity)
        for relation in getattr(semantic_indexes, "relationships", ()) if semantic_indexes is not None else ():
            source = semantic_ids.get(str(relation.get("subject_id")))
            target = semantic_ids.get(str(relation.get("object_id")))
            if source and target:
                relationships.append(
                    _relationship(
                        source,
                        target,
                        str(relation.get("relationship_type") or "related_to"),
                        confidence="high",
                        provenance=[{"source": "semantic_graph", "confidence": "high"}],
                    )
                )

        for resource in _as_list(_as_dict(network_report).get("resources")):
            resource_id = str(resource.get("id") or resource.get("name") or "")
            entity = _entity(
                "resource",
                resource_id,
                str(resource.get("name") or resource_id),
                entity_type=resource.get("entity_type", ""),
                subscription=resource.get("subscription_id", ""),
                environment=resource.get("environment", ""),
                business_service=resource.get("business_service", ""),
                application=resource.get("application", ""),
                owner=resource.get("owner", ""),
                temporal_state={"observed_at": observed_at, "source": "network.topology"},
                provenance=[{"source": "network.topology", "confidence": "high"}],
            )
            entities[entity["id"]] = entity
            for kind, value, rel_type in (
                ("business_service", resource.get("business_service"), "supports"),
                ("application", resource.get("application"), "hosts"),
                ("environment", resource.get("environment"), "runs_in"),
                ("owner", resource.get("owner"), "owned_by"),
                ("subscription", resource.get("subscription_id"), "belongs_to"),
            ):
                if value:
                    target = _entity(kind, str(value), str(value), temporal_state={"observed_at": observed_at})
                    entities.setdefault(target["id"], target)
                    relationships.append(_relationship(entity["id"], target["id"], rel_type, confidence="high"))

        for rel in _as_list(_as_dict(network_report).get("relationships")):
            source = f"resource:{rel.get('source')}"
            target = f"resource:{rel.get('target')}"
            relationships.append(_relationship(source, target, str(rel.get("relationship_type") or "connected_to"), confidence="high"))

        for exposure in _as_list(_as_dict(vulnerabilities).get("top_priority")):
            cve = str(exposure.get("cve_id") or "")
            if not cve:
                continue
            entity = _entity(
                "vulnerability",
                cve,
                cve,
                severity=exposure.get("severity", ""),
                risk_reduction=exposure.get("expected_risk_reduction", 0),
                temporal_state={"observed_at": observed_at, "source": "vulnerability.live"},
                provenance=[{"source": "vulnerability.live", "confidence": "medium"}],
            )
            entities[entity["id"]] = entity
            events.append({"timestamp": observed_at, "type": "vulnerability_observed", "entity": entity["id"], "summary": cve})

        for incident in _as_list(_as_dict(incidents).get("incidents")):
            identity = _as_dict(incident.get("incident"))
            incident_id = str(identity.get("incident_id") or identity.get("title") or "")
            if not incident_id:
                continue
            entity = _entity(
                "incident",
                incident_id,
                str(identity.get("title") or incident_id),
                severity=identity.get("severity", ""),
                status=identity.get("status", ""),
                temporal_state={"observed_at": identity.get("started_at") or observed_at, "source": "incidents"},
                provenance=[{"source": "incidents", "confidence": "medium"}],
            )
            entities[entity["id"]] = entity
            for service in _as_list(_as_dict(incident.get("business_impact")).get("business_services")):
                target = _entity("business_service", str(service), str(service), temporal_state={"observed_at": observed_at})
                entities.setdefault(target["id"], target)
                relationships.append(_relationship(entity["id"], target["id"], "affects", confidence="medium"))
            for event in _as_list(incident.get("timeline")):
                events.append(
                    {
                        "timestamp": event.get("timestamp") or observed_at,
                        "type": event.get("event_type") or "incident_event",
                        "entity": entity["id"],
                        "summary": event.get("summary") or incident_id,
                        "provenance": event,
                    }
                )

        for plan in _as_list(_as_dict(remediation).get("plans")):
            plan_id = str(plan.get("plan_id") or plan.get("title") or "")
            if not plan_id:
                continue
            entity = _entity(
                "remediation",
                plan_id,
                str(plan.get("title") or plan_id),
                status=plan.get("status", ""),
                risk_reduction=_as_dict(plan.get("simulation_result")).get("risk_reduction_percent", 0),
                temporal_state={"observed_at": _as_dict(remediation).get("generated_at") or observed_at, "source": "remediation"},
                provenance=[{"source": "remediation", "confidence": "medium"}],
            )
            entities[entity["id"]] = entity
            service = plan.get("business_service")
            if service:
                target = _entity("business_service", str(service), str(service), temporal_state={"observed_at": observed_at})
                entities.setdefault(target["id"], target)
                relationships.append(_relationship(entity["id"], target["id"], "mitigates_risk_for", confidence="medium"))
            events.append({"timestamp": observed_at, "type": "remediation_candidate", "entity": entity["id"], "summary": entity["name"]})

        provenance.extend(
            [
                {"source": "semantic_graph", "confidence": "high"},
                {"source": "network", "confidence": "high" if network_report is not None else "unknown"},
                {"source": "vulnerability", "confidence": "medium" if vulnerabilities is not None else "unknown"},
                {"source": "incidents", "confidence": "medium" if incidents is not None else "unknown"},
                {"source": "remediation", "confidence": "medium" if remediation is not None else "unknown"},
            ]
        )
        entity_list = list(entities.values())
        rel_list = list({rel["id"]: rel for rel in relationships}.values())
        current_version = _version((entity_list, rel_list, events))
        previous_version = f"prev-{current_version[:8]}"
        return {
            "twin_id": "operational-twin",
            "version": current_version,
            "previous_version": previous_version,
            "observed_at": observed_at,
            "scope": self.scope or {},
            "entities": entity_list,
            "relationships": rel_list,
            "timeline": sorted(events, key=lambda item: str(item.get("timestamp")), reverse=True),
            "provenance": provenance,
            "confidence": self._confidence(provenance),
            "temporal": {
                "current_state_version": current_version,
                "previous_state_version": previous_version,
                "change_history": self._change_history(events, current_version, previous_version),
                "risk_trend": self._risk_trend(vulnerabilities, incidents),
                "dependency_evolution": self._dependency_evolution(rel_list),
            },
            "warnings": [
                f"{item['source']} unavailable: {item['error']}" for item in source_errors
            ],
        }

    def query(self, text: str) -> dict[str, Any]:
        snapshot = self.snapshot()
        normalized = text.casefold().strip()
        matched_entities = [
            entity
            for entity in snapshot["entities"]
            if normalized in entity["name"].casefold()
            or normalized in str(entity.get("properties", {})).casefold()
        ] if normalized else snapshot["entities"]
        return {
            "query": text,
            "version": snapshot["version"],
            "entities": matched_entities[:50],
            "relationships": snapshot["relationships"],
            "timeline": snapshot["timeline"][:25],
            "warnings": snapshot["warnings"],
        }

    def compare(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        current = len(snapshot["entities"])
        return {
            "current_version": snapshot["version"],
            "previous_version": snapshot["previous_version"],
            "added": snapshot["entities"][:10],
            "removed": [],
            "changed": snapshot["timeline"][:10],
            "summary": f"{current} current entities; prior state retained as {snapshot['previous_version']} for temporal comparison.",
            "warnings": snapshot["warnings"],
        }

    def scenario(self, scenario_type: str, target: str = "") -> dict[str, Any]:
        snapshot = self.snapshot()
        impacted = self._impacted(snapshot, target)
        multipliers = {
            "firewall_failure": (0.85, "Traffic inspection and hub dependencies degrade."),
            "route_change": (0.65, "Route changes may bypass approved inspection paths."),
            "subscription_outage": (0.9, "Subscription-scoped resources and dependent services are unavailable."),
            "cve_exploitation": (0.95, "Reachable vulnerable resources become active compromise candidates."),
            "patch_deployment": (-0.45, "Patch should reduce vulnerability risk after validation."),
            "architecture_remediation": (-0.35, "Approved remediation should reduce topology and control risk."),
        }
        multiplier, narrative = multipliers.get(scenario_type, (0.4, "Scenario impact is estimated from current dependencies."))
        return {
            "scenario": scenario_type,
            "target": target,
            "version": snapshot["version"],
            "likely_impact": narrative,
            "risk_delta": round(multiplier * max(1, len(impacted)) * 10, 2),
            "impacted_entities": impacted[:25],
            "assumptions": [
                "Scenario is advisory and requires operator validation.",
                "Impact follows current twin relationships and live observations only.",
            ],
            "warnings": snapshot["warnings"],
        }

    def traverse(self, resource_id: str) -> dict[str, Any]:
        snapshot = self.snapshot()
        start = f"resource:{resource_id}"
        related = [
            rel for rel in snapshot["relationships"] if rel["source"] == start or rel["target"] == start
        ]
        entity_by_id = {entity["id"]: entity for entity in snapshot["entities"]}
        path = [entity_by_id.get(start)] if start in entity_by_id else []
        for rel in related:
            other = rel["target"] if rel["source"] == start else rel["source"]
            if other in entity_by_id:
                path.append(entity_by_id[other])
        consequence = [
            entity["name"]
            for entity in path
            if entity and entity["kind"] in {"business_service", "owner", "application"}
        ]
        return {
            "resource_id": resource_id,
            "path": [entity for entity in path if entity],
            "relationships": related,
            "business_consequence": consequence or ["No business consequence mapped"],
            "warnings": snapshot["warnings"],
        }

    def export(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        return {
            "format": "operational-twin-export",
            "exported_at": _utc_now(),
            "snapshot": snapshot,
            "warnings": snapshot["warnings"],
        }

    @staticmethod
    def _safe(source: str, call: Any, errors: list[dict[str, str]]) -> Any | None:
        try:
            return call() if call else None
        except Exception as exc:  # noqa: BLE001 - aggregated fallback source resolution
            errors.append({"source": source, "error": exc.__class__.__name__})
            return None

    @staticmethod
    def _confidence(provenance: list[dict[str, Any]]) -> str:
        values = {item.get("confidence") for item in provenance}
        if "unknown" in values:
            return "medium"
        if values == {"high"}:
            return "high"
        return "medium"

    @staticmethod
    def _change_history(events: list[dict[str, Any]], current: str, previous: str) -> list[dict[str, Any]]:
        return [
            {"version": current, "previous_version": previous, "change_type": event.get("type"), "summary": event.get("summary"), "timestamp": event.get("timestamp")}
            for event in events[:20]
        ]

    @staticmethod
    def _risk_trend(vulnerabilities: Any, incidents: Any) -> list[dict[str, Any]]:
        vuln = _as_dict(vulnerabilities)
        incident_count = len(_as_list(_as_dict(incidents).get("incidents")))
        return [
            {
                "timestamp": _utc_now(),
                "risk_score": min(100, int(vuln.get("critical_count", 0)) * 20 + incident_count * 12),
                "drivers": {
                    "critical_vulnerabilities": vuln.get("critical_count", 0),
                    "active_incidents": incident_count,
                },
            }
        ]

    @staticmethod
    def _dependency_evolution(relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for rel in relationships:
            counts[str(rel.get("type"))] = counts.get(str(rel.get("type")), 0) + 1
        return [{"relationship_type": key, "current_count": value, "previous_count": max(0, value - 1)} for key, value in sorted(counts.items())]

    @staticmethod
    def _impacted(snapshot: dict[str, Any], target: str) -> list[dict[str, Any]]:
        if not target:
            return snapshot["entities"][:15]
        target_lower = target.casefold()
        ids = {
            entity["id"]
            for entity in snapshot["entities"]
            if target_lower in entity["id"].casefold() or target_lower in entity["name"].casefold()
        }
        for rel in snapshot["relationships"]:
            if rel["source"] in ids:
                ids.add(rel["target"])
            if rel["target"] in ids:
                ids.add(rel["source"])
        by_id = {entity["id"]: entity for entity in snapshot["entities"]}
        return [by_id[item] for item in ids if item in by_id]

    def _in_scope(self, resource: dict[str, Any]) -> bool:
        scope = self.scope or {}
        field_map = {
            "subscription": ("subscription_id", "subscription"),
            "subscription_connection": ("subscription_connection_id", "subscription_connection"),
            "environment": ("environment",),
            "business_service": ("business_service", "business_service_name"),
            "application": ("application", "application_name"),
            "owner": ("owner", "owner_name"),
        }
        for dimension, fields in field_map.items():
            allowed = {str(value).casefold() for value in scope.get(dimension, ())}
            if allowed:
                actual = {str(resource.get(field) or "").casefold() for field in fields}
                if not actual.intersection(allowed):
                    return False
        return True
