"""D-04/D-04a comparison harness support: measures Hermes's
``SemanticEngine`` arm against the Fabric-native ``topology_pipeline`` arm
on the identical shared curated snapshot (``tests/topology_comparison_scenario``,
Pitfall 3) and produces a single reproducible ``ComparisonReport`` covering
all five D-04 dimensions.

Both arms are reduced to one uniform interface -- ``ArmResult`` -- before
comparison, so ``compare()`` never has to special-case which arm produced
which shape. This is required because the two arms' native APIs are *not*
directly comparable for a network-topology root:

- ``SemanticEngine.get_impact_context()`` branches on ``cause_type``
  (``PatchAssessment`` / ``Subscription`` / ``Application`` / ``ASSET_TYPES``)
  and falls back to an empty impacted-set for any other entity type. A
  VNet/Subnet/NSG root is not one of those recognised types, so calling
  ``get_impact_context()`` directly on a network root is *not* a fair
  comparison point on its own -- it would always report a near-empty
  blast radius regardless of how rich the underlying graph is.
- ``fabric_pipelines.topology_pipeline.derive_edges()`` has no equivalent
  concept at all -- it just returns entities/edges.

The fair, shared comparison surface is therefore a bounded breadth-first
traversal over each arm's own relationship/edge index, starting from the
same root id -- this is what both ``Normalizer.normalize()`` (via
``NormalizedGraph.relationships``) and ``derive_edges()`` (via its edge
dict) actually support natively, and it is the literal blast-radius
question D-04 asks about ("what is reachable from this root"). Hermes's
``get_impact_context()`` is *also* invoked and recorded (``cause_type``
plus its own reported ``blast_radius``) as supplementary evidence, so the
named API in the plan objective is exercised and its cause_type/ASSET_TYPES
gap is documented explicitly rather than silently worked around.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EdgeView:
    """Arm-agnostic projection of one relationship/edge, used for both the
    BFS traversal and the D-05 explicit-state checks."""

    relationship_id: str
    subject_id: str
    predicate: str
    object_id: str
    source: str
    confidence: float
    assertion_state: str


@dataclass(frozen=True)
class ArmResult:
    """Uniform per-arm measurement: what was reached from ``root_id``, the
    edges considered, and the cost/latency incurred producing it."""

    arm_name: str
    root_id: str
    entity_ids: set[str]
    edges: list[EdgeView]
    impacted_ids: set[str]
    query_count: int
    latency_seconds: float
    supplementary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComparisonReport:
    """Covers all five D-04 dimensions for one shared scenario. Every field
    is populated from an actual measurement -- if a dimension can only be
    approximated (operational cost), the proxy is labelled explicitly
    rather than the dimension being omitted."""

    root_id: str
    hermes: ArmResult
    fabric: ArmResult

    # Dimension 1: correctness
    impacted_ids_match: bool
    hermes_only: set[str]
    fabric_only: set[str]

    # Dimension 2: evidence links
    hermes_missing_evidence: list[str]
    fabric_missing_evidence: list[str]

    # Dimension 3: authorization / scope
    hermes_scope_violations: list[str]
    fabric_scope_violations: list[str]

    # Dimension 4: latency
    latency_seconds: dict[str, float]

    # Dimension 5: operational cost (documented proxy, never omitted)
    operational_cost_proxy: dict[str, Any]

    # D-05: explicit non-accepted edges, and dangling-edge drop parity
    non_accepted_states: dict[str, list[str]]
    dangling_edges_dropped: dict[str, bool]

    def is_correct(self) -> bool:
        return self.impacted_ids_match

    def to_markdown(self) -> str:
        lines: list[str] = []
        lines.append(f"### Root: `{self.root_id}`")
        lines.append("")
        lines.append("#### 1. Correctness")
        lines.append(f"- Impacted-set match: **{self.impacted_ids_match}**")
        lines.append(f"- Hermes impacted count: {len(self.hermes.impacted_ids)}")
        lines.append(f"- Fabric impacted count: {len(self.fabric.impacted_ids)}")
        if self.hermes_only:
            lines.append(f"- Only in Hermes: {sorted(self.hermes_only)}")
        if self.fabric_only:
            lines.append(f"- Only in Fabric: {sorted(self.fabric_only)}")
        lines.append("")
        lines.append("#### 2. Evidence-link presence")
        lines.append(
            f"- Hermes edges missing source/confidence evidence: {self.hermes_missing_evidence or 'none'}"
        )
        lines.append(
            f"- Fabric edges missing source/confidence evidence: {self.fabric_missing_evidence or 'none'}"
        )
        lines.append("")
        lines.append("#### 3. Authorization / scope enforcement")
        lines.append(f"- Hermes scope violations: {self.hermes_scope_violations or 'none'}")
        lines.append(f"- Fabric scope violations: {self.fabric_scope_violations or 'none'}")
        lines.append("")
        lines.append("#### 4. Latency (wall-clock, seconds)")
        for arm, seconds in self.latency_seconds.items():
            lines.append(f"- {arm}: {seconds:.6f}s")
        lines.append("")
        lines.append("#### 5. Operational cost (documented proxy -- not live billing telemetry)")
        for key, value in self.operational_cost_proxy.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
        lines.append("#### D-05: explicit non-accepted edge states")
        for arm, states in self.non_accepted_states.items():
            lines.append(f"- {arm}: {states or 'none'}")
        lines.append("")
        lines.append("#### D-05 edge case: dangling-edge (unemitted endpoint) drop parity")
        for arm, dropped in self.dangling_edges_dropped.items():
            lines.append(f"- {arm} drops dangling edges: {dropped}")
        return "\n".join(lines)


def edge_view_from_camel_case(edge: Any) -> EdgeView:
    """Both arms emit the same Hermes-style camelCase edge envelope
    (``relationshipId``/``subjectId``/``predicate``/``objectId``/``source``/
    ``confidence``/``assertionState``) -- one adapter covers both."""
    return EdgeView(
        relationship_id=str(edge["relationshipId"]),
        subject_id=str(edge["subjectId"]),
        predicate=str(edge["predicate"]),
        object_id=str(edge["objectId"]),
        source=str(edge.get("source") or ""),
        confidence=float(edge.get("confidence") or 0.0),
        assertion_state=str(edge.get("assertionState") or ""),
    )


def filter_dangling_edges(
    edges: list[EdgeView], entity_ids: set[str]
) -> tuple[list[EdgeView], bool]:
    """Drops any edge whose subject or object id is missing from the
    emitted entity set -- mirrors ``Normalizer.normalize()``'s
    ``known_entity_ids`` filter (normalize.py:218-234). Both arms must show
    this same drop behavior (D-05 edge case / Test 3); ``derive_edges()``
    itself does not filter, so the comparison harness applies this
    uniformly to both arms' raw edges rather than special-casing one arm.
    Returns the filtered edges plus whether anything was actually dropped.
    """
    kept = [
        edge
        for edge in edges
        if edge.subject_id in entity_ids and edge.object_id in entity_ids
    ]
    return kept, len(kept) != len(edges)


def bfs_impact(root_id: str, edges: list[EdgeView], entity_ids: set[str]) -> set[str]:
    """Undirected bounded BFS over an arm's own edge index, starting from
    ``root_id``. This is the shared comparison primitive both arms are
    reduced to -- neither arm's native "impact" API is used here, since
    only this traversal is actually defined identically for both arms.
    """
    adjacency: dict[str, set[str]] = {entity_id: set() for entity_id in entity_ids}
    for edge in edges:
        if edge.subject_id in entity_ids and edge.object_id in entity_ids:
            adjacency.setdefault(edge.subject_id, set()).add(edge.object_id)
            adjacency.setdefault(edge.object_id, set()).add(edge.subject_id)
    if root_id not in entity_ids:
        return set()
    seen = {root_id}
    queue: deque[str] = deque([root_id])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, ()):
            if neighbor not in seen:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen - {root_id}


def build_arm_result(
    *,
    arm_name: str,
    root_id: str,
    entity_ids: set[str],
    edges: list[EdgeView],
    query_count: int,
    latency_seconds: float,
    supplementary: dict[str, Any] | None = None,
) -> ArmResult:
    impacted = bfs_impact(root_id, edges, entity_ids)
    return ArmResult(
        arm_name=arm_name,
        root_id=root_id,
        entity_ids=entity_ids,
        edges=edges,
        impacted_ids=impacted,
        query_count=query_count,
        latency_seconds=latency_seconds,
        supplementary=dict(supplementary or {}),
    )


def _missing_evidence(edges: list[EdgeView]) -> list[str]:
    """An edge with no ``source`` tag or non-positive confidence carries no
    usable evidence link -- both arms must always populate these."""
    return [
        edge.relationship_id
        for edge in edges
        if not edge.source or edge.confidence <= 0
    ]


def _scope_violations(edges: list[EdgeView], entity_ids: set[str]) -> list[str]:
    """An edge referencing an entity outside the authorized/emitted scope
    (i.e. either endpoint not recorded) would be an unscoped read leaking into
    the result -- flagged explicitly rather than silently included."""
    return [
        edge.relationship_id
        for edge in edges
        if edge.subject_id not in entity_ids or edge.object_id not in entity_ids
    ]


def _non_accepted_states(edges: list[EdgeView]) -> list[str]:
    return sorted({edge.assertion_state for edge in edges if edge.assertion_state != "accepted"})


def compare(hermes: ArmResult, fabric: ArmResult, *, root_id: str) -> ComparisonReport:
    """Produces the five-dimension D-04 comparison for one shared scenario.
    Neither arm's raw output is trusted as ground truth over the other --
    both are measured against the same shared-fixture entity/edge index.
    """
    impacted_match = hermes.impacted_ids == fabric.impacted_ids
    hermes_only = hermes.impacted_ids - fabric.impacted_ids
    fabric_only = fabric.impacted_ids - hermes.impacted_ids

    hermes_missing_evidence = _missing_evidence(hermes.edges)
    fabric_missing_evidence = _missing_evidence(fabric.edges)

    hermes_scope_violations = _scope_violations(hermes.edges, hermes.entity_ids)
    fabric_scope_violations = _scope_violations(fabric.edges, fabric.entity_ids)

    latency = {hermes.arm_name: hermes.latency_seconds, fabric.arm_name: fabric.latency_seconds}

    operational_cost_proxy = {
        "note": "proxy metric -- query count and edge count, not live Azure billing telemetry",
        f"{hermes.arm_name}_query_count": hermes.query_count,
        f"{fabric.arm_name}_query_count": fabric.query_count,
        f"{hermes.arm_name}_edge_count": len(hermes.edges),
        f"{fabric.arm_name}_edge_count": len(fabric.edges),
    }

    non_accepted_states = {
        hermes.arm_name: _non_accepted_states(hermes.edges),
        fabric.arm_name: _non_accepted_states(fabric.edges),
    }

    dangling_edges_dropped = {
        hermes.arm_name: bool(hermes.supplementary.get("dangling_edges_dropped", False)),
        fabric.arm_name: bool(fabric.supplementary.get("dangling_edges_dropped", False)),
    }

    return ComparisonReport(
        root_id=root_id,
        hermes=hermes,
        fabric=fabric,
        impacted_ids_match=impacted_match,
        hermes_only=hermes_only,
        fabric_only=fabric_only,
        hermes_missing_evidence=hermes_missing_evidence,
        fabric_missing_evidence=fabric_missing_evidence,
        hermes_scope_violations=hermes_scope_violations,
        fabric_scope_violations=fabric_scope_violations,
        latency_seconds=latency,
        operational_cost_proxy=operational_cost_proxy,
        non_accepted_states=non_accepted_states,
        dangling_edges_dropped=dangling_edges_dropped,
    )


def timed(fn, *args, **kwargs) -> tuple[Any, float]:
    """Small wall-clock helper so both arms record latency identically."""
    started = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed = time.perf_counter() - started
    return result, elapsed


__all__ = [
    "ArmResult",
    "ComparisonReport",
    "EdgeView",
    "bfs_impact",
    "build_arm_result",
    "compare",
    "edge_view_from_camel_case",
    "filter_dangling_edges",
    "timed",
]
