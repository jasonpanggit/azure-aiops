"""Build Fabric operational impact context graph rows.

The graph combines resource identity/topology and assessment-domain findings
into a single table shape that Fabric IQ can expose for traversal.  It is a
Fabric-side replacement data product for operational context queries; it does
not call Hermes or perform live Azure discovery.
"""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

OUTPUT_TABLE = "operational_context_graph"
SOURCE_TAG = "fabric_pipeline:impact_context"


@dataclass(frozen=True)
class ImpactContextGraphResult:
    table_name: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    summary: dict[str, Any]


def build_graph(
    *,
    resources: Iterable[Mapping[str, Any]],
    topology_edges: Iterable[Mapping[str, Any]] = (),
    governance_findings: Iterable[Mapping[str, Any]] = (),
    vulnerability_findings: Iterable[Mapping[str, Any]] = (),
    lifecycle_findings: Iterable[Mapping[str, Any]] = (),
    patch_findings: Iterable[Mapping[str, Any]] = (),
    change_findings: Iterable[Mapping[str, Any]] = (),
) -> ImpactContextGraphResult:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    for row in resources:
        resource_id = _resource_id(row)
        if not resource_id:
            continue
        nodes[resource_id] = {
            "node_id": resource_id,
            "node_type": str(row.get("entity_type") or row.get("resource_type") or row.get("type") or "Resource"),
            "name": str(row.get("name") or resource_id.rsplit("/", 1)[-1]),
            "risk_score": 0,
            "compliance_score": None,
            "lifecycle_status": "",
            "patch_status": "",
            "finding_counts": {
                "governance": 0,
                "vulnerability": 0,
                "lifecycle": 0,
                "patch": 0,
                "change": 0,
            },
            "source": SOURCE_TAG,
        }

    for edge in topology_edges:
        subject = str(edge.get("subject_id") or edge.get("subjectId") or "")
        obj = str(edge.get("object_id") or edge.get("objectId") or "")
        if subject in nodes and obj in nodes:
            _add_edge(edges, subject, str(edge.get("predicate") or "relatedTo"), obj, "topology")

    _merge_findings(nodes, governance_findings, domain="governance")
    _merge_findings(nodes, vulnerability_findings, domain="vulnerability")
    _merge_findings(nodes, lifecycle_findings, domain="lifecycle")
    _merge_findings(nodes, patch_findings, domain="patch")
    _merge_findings(nodes, change_findings, domain="change")

    return ImpactContextGraphResult(
        table_name=OUTPUT_TABLE,
        nodes=list(nodes.values()),
        edges=list(edges.values()),
        summary={"node_count": len(nodes), "edge_count": len(edges), "source": SOURCE_TAG},
    )


def traverse(
    graph: ImpactContextGraphResult,
    root_id: str,
    *,
    allowed_resource_ids: set[str] | None = None,
    max_depth: int = 3,
) -> dict[str, Any]:
    allowed = allowed_resource_ids
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge["subject_id"], []).append(edge)
    nodes_by_id = {node["node_id"]: node for node in graph.nodes}
    if root_id not in nodes_by_id or (allowed is not None and root_id not in allowed):
        return {"nodes": [], "edges": [], "truncated": False}
    seen = {root_id}
    queue = deque([(root_id, 0)])
    out_edges: list[dict[str, Any]] = []
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for edge in adjacency.get(current, []):
            target = edge["object_id"]
            if allowed is not None and target not in allowed:
                continue
            out_edges.append(edge)
            if target not in seen:
                seen.add(target)
                queue.append((target, depth + 1))
    return {
        "nodes": [nodes_by_id[node_id] for node_id in seen],
        "edges": out_edges,
        "truncated": False,
    }


def _merge_findings(
    nodes: dict[str, dict[str, Any]],
    findings: Iterable[Mapping[str, Any]],
    *,
    domain: str,
) -> None:
    for finding in findings:
        resource_id = _resource_id(finding)
        if resource_id not in nodes:
            continue
        node = nodes[resource_id]
        node["finding_counts"][domain] += 1
        node["risk_score"] = max(int(node.get("risk_score") or 0), _int(finding.get("risk_score") or finding.get("priority_score")))
        if domain in {"governance", "change", "patch"} and finding.get("compliance_score") is not None:
            node["compliance_score"] = finding.get("compliance_score")
        if domain == "lifecycle":
            node["lifecycle_status"] = str(finding.get("lifecycle_status") or "")
        if domain == "patch":
            node["patch_status"] = str(finding.get("status") or "")


def _add_edge(index: dict[str, dict[str, Any]], subject: str, predicate: str, obj: str, source: str) -> None:
    digest = hashlib.sha256(f"{subject}|{predicate}|{obj}|{source}".encode()).hexdigest()[:24]
    index[digest] = {
        "relationship_id": digest,
        "subject_id": subject,
        "predicate": predicate,
        "object_id": obj,
        "source": source,
    }


def _resource_id(row: Mapping[str, Any]) -> str:
    return str(row.get("resource_id") or row.get("resourceId") or row.get("id") or row.get("server_id") or "")


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


__all__ = [
    "OUTPUT_TABLE",
    "SOURCE_TAG",
    "ImpactContextGraphResult",
    "build_graph",
    "traverse",
]
