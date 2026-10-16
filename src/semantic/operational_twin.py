"""Operational digital twin composition.

The twin is a request-time projection over the durable semantic graph and live
operational providers. It does not ask AIOps to snapshot mutable facts; instead
it versions the current composed view and emits provenance for each contribution.
"""

from __future__ import annotations

import re
from collections import deque
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


def _scope_attributes(value: dict[str, Any]) -> dict[str, str]:
    from api.scope import scope_attributes

    attributes = scope_attributes(value)
    if "subscription_connection" not in attributes and value.get("subscription_connection_id"):
        attributes["subscription_connection"] = str(value["subscription_connection_id"]).strip().casefold()
    return attributes


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
        if incidents is not None:
            incident_rows = _as_list(_as_dict(incidents).get("incidents"))
            visible_incidents = [
                row for row in incident_rows
                if self._contribution_in_scope(row, "incident")
            ]
            incidents = {
                **incidents,
                "incidents": visible_incidents,
                "scope_projection_incomplete": len(visible_incidents) != len(incident_rows),
            }
        if remediation is not None:
            remediation = {
                **remediation,
                "plans": [
                    row for row in _as_list(_as_dict(remediation).get("plans"))
                    if self._contribution_in_scope(row, "resource")
                ],
            }

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
            network_attributes = {**_as_dict(resource.get("details")), **resource}
            if not self._in_scope(network_attributes):
                continue
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
                temporal_state={"composed_at": observed_at, "source": "network.topology"},
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
                    target = _entity(kind, str(value), str(value), temporal_state={"composed_at": observed_at})
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
                temporal_state={
                    "composed_at": observed_at,
                    "observed_at": _as_dict(vulnerabilities).get("freshness"),
                    "source": "vulnerability.live",
                },
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
                temporal_state={
                    "composed_at": observed_at,
                    "event_started_at": identity.get("started_at"),
                    "observed_at": _as_dict(incidents).get("freshness"),
                    "source": "incidents",
                },
                provenance=[{"source": "incidents", "confidence": "medium"}],
            )
            entities[entity["id"]] = entity
            for service in _as_list(_as_dict(incident.get("business_impact")).get("business_services")):
                if not self._in_scope({**identity, **incident, "business_service": str(service)}):
                    continue
                target = _entity("business_service", str(service), str(service), temporal_state={"composed_at": observed_at})
                entities.setdefault(target["id"], target)
                relationships.append(_relationship(entity["id"], target["id"], "affects", confidence="medium"))
            for event in _as_list(incident.get("timeline")):
                events.append(
                    {
                        "timestamp": event.get("timestamp") or observed_at,
                        "type": event.get("event_type") or "incident_event",
                        "entity": entity["id"],
                        "summary": event.get("summary") or incident_id,
                        "provenance": {"source": "incidents"},
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
                temporal_state={
                    "composed_at": observed_at,
                    "generated_at": _as_dict(remediation).get("generated_at"),
                    "observed_at": _as_dict(remediation).get("freshness"),
                    "source": "remediation",
                },
                provenance=[{"source": "remediation", "confidence": "medium"}],
            )
            entities[entity["id"]] = entity
            service = plan.get("business_service")
            if service:
                target = _entity("business_service", str(service), str(service), temporal_state={"composed_at": observed_at})
                entities.setdefault(target["id"], target)
                relationships.append(_relationship(entity["id"], target["id"], "mitigates_risk_for", confidence="medium"))
            events.append({"timestamp": observed_at, "type": "remediation_candidate", "entity": entity["id"], "summary": entity["name"]})

        provenance.extend(
            [
                {"source": "semantic_graph", "confidence": "high" if self.semantic is not None else "unknown"},
                {"source": "network", "confidence": "high" if network_report is not None else "unknown"},
                {"source": "vulnerability", "confidence": "medium" if vulnerabilities is not None else "unknown"},
                {"source": "incidents", "confidence": "medium" if incidents is not None else "unknown"},
                {"source": "remediation", "confidence": "medium" if remediation is not None else "unknown"},
            ]
        )
        entity_list = list(entities.values())
        rel_list = list({
            rel["id"]: rel for rel in relationships
            if rel["source"] in entities and rel["target"] in entities
        }.values())
        current_version = _version((entity_list, rel_list, events))
        return {
            "twin_id": "operational-twin",
            "version": current_version,
            "previous_version": None,
            "observed_at": observed_at,
            "observation_kind": "request_time_composition",
            "scope": self.scope or {},
            "entities": entity_list,
            "relationships": rel_list,
            "timeline": sorted(events, key=lambda item: str(item.get("timestamp")), reverse=True),
            "provenance": provenance,
            "confidence": self._confidence(provenance),
            "temporal": {
                "current_state_version": current_version,
                "previous_state_version": None,
                "change_history": [],
                "risk_trend": self._risk_trend(vulnerabilities, incidents),
                "dependency_evolution": self._dependency_evolution(rel_list),
            },
            "warnings": [
                f"{item['source']} unavailable: {item['error']}" for item in source_errors
            ] + (
                ["Incident and remediation rows require confirmed metadata for every requested scope dimension; unmapped or conflicting rows are omitted."]
                if self.scope else []
            ),
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
        return {
            "current_version": snapshot["version"],
            "previous_version": None,
            "comparison_available": False,
            "added": [],
            "removed": [],
            "changed": [],
            "summary": "No retained baseline selected. Current observations are not historical differences.",
            "warnings": snapshot["warnings"],
        }

    def scenario(self, scenario_type: str, target: str = "") -> dict[str, Any]:
        narratives = {
            "firewall_failure": "Review inspection dependencies if the selected resource's firewall path fails.",
            "route_change": "Review routing and inspection dependencies before changing the selected resource's path.",
            "subscription_outage": "Review the selected resource's mapped dependencies for a hypothetical subscription outage.",
            "cve_exploitation": "Review mapped dependencies; exploitability, reachability and compromise are not established.",
            "patch_deployment": "Review mapped dependencies before patching; compatibility and risk reduction are not established.",
            "architecture_remediation": "Review mapped dependencies before remediation; control improvement is not established.",
        }
        if scenario_type not in narratives:
            raise ValueError("Select a supported Twin scenario")
        snapshot = self.snapshot()
        impacted, truncated = self._impacted(snapshot, target)
        return {
            "scenario": scenario_type,
            "target": target,
            "version": snapshot["version"],
            "likely_impact": narratives[scenario_type],
            "risk_delta": None,
            "analysis_kind": "bounded_topology_review",
            "authority": "none",
            "impacted_total": len(impacted),
            "truncated": truncated or len(impacted) > 25,
            "traversal": {"direction": "undirected", "max_hops": 3, "max_entities": 500},
            "impacted_entities": impacted[:25],
            "assumptions": [
                "Review only; no execution, deployment approval or measured risk delta.",
                "Related entities follow observed links in either direction, at most three hops and 500 entities.",
                "Links show mapped association, not causal failure propagation or verified network reachability.",
                "The selected resource is the seed, not proof of a scenario-specific fault or subscription-wide coverage.",
                "Missing providers and unmapped dependencies remain unknown.",
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
    def _risk_trend(vulnerabilities: Any, incidents: Any) -> list[dict[str, Any]]:
        vuln = _as_dict(vulnerabilities)
        critical = vuln.get("critical_count")
        if (
            isinstance(critical, bool) or not isinstance(critical, int) or critical < 0
            or not isinstance(incidents, dict) or not isinstance(incidents.get("incidents"), list)
            or incidents.get("scope_projection_incomplete")
        ):
            return []
        incident_count = len(_as_list(_as_dict(incidents).get("incidents")))
        return [
            {
                "timestamp": _utc_now(),
                "risk_score": min(100, critical * 20 + incident_count * 12),
                "interpretation": "Heuristic current index: min(100, critical vulnerabilities * 20 + visible incidents * 12); not a measured trend, probability or reliability score.",
                "drivers": {
                    "critical_vulnerabilities": critical,
                    "active_incidents": incident_count,
                },
            }
        ]

    @staticmethod
    def _dependency_evolution(relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for rel in relationships:
            counts[str(rel.get("type"))] = counts.get(str(rel.get("type")), 0) + 1
        return [{"relationship_type": key, "current_count": value, "previous_count": None} for key, value in sorted(counts.items())]

    @staticmethod
    def _impacted(snapshot: dict[str, Any], target: str) -> tuple[list[dict[str, Any]], bool]:
        by_id = {entity["id"]: entity for entity in snapshot["entities"]}
        start = target if target.startswith("resource:") else f"resource:{target}"
        if not target or start not in by_id or by_id[start]["kind"] != "resource":
            raise LookupError("Select an observed resource in the current scope")
        adjacency: dict[str, set[str]] = {}
        for rel in snapshot["relationships"]:
            source, destination = rel["source"], rel["target"]
            if source in by_id and destination in by_id:
                adjacency.setdefault(source, set()).add(destination)
                adjacency.setdefault(destination, set()).add(source)
        ids = {start}
        queue = deque([(start, 0)])
        truncated = False
        while queue:
            current, depth = queue.popleft()
            neighbors = adjacency.get(current, set()) - ids
            if depth == 3:
                truncated |= bool(neighbors)
                continue
            for other in sorted(neighbors):
                if len(ids) == 500:
                    truncated = True
                    break
                ids.add(other)
                queue.append((other, depth + 1))
        return [by_id[item] for item in sorted(ids)], truncated

    def _contribution_in_scope(self, row: dict[str, Any], nested: str) -> bool:
        from api.scope import Scope

        outer = _scope_attributes(row)
        inner = _scope_attributes(_as_dict(row.get(nested)))
        if any(outer[key] != inner[key] for key in outer.keys() & inner.keys()):
            return False
        return Scope.from_mapping(self.scope).matches({**outer, **inner})

    def _in_scope(self, resource: dict[str, Any]) -> bool:
        from api.scope import Scope

        return Scope.from_mapping(self.scope).matches(_scope_attributes(resource))
