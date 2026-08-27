"""D-04a comparison harness: one bounded blast-radius scenario run against
both ``SemanticEngine`` (Hermes) and ``fabric_pipelines.topology_pipeline``
(Fabric-native) arms, using the identical shared curated snapshot from
``tests/topology_comparison_scenario`` (Pitfall 3 -- one fixture, not two).

See ``fabric_pipelines/comparison_report.py`` module docstring for why the
comparison surface is a bounded BFS over each arm's own edge index rather
than a direct call to ``SemanticEngine.get_impact_context()`` (that API's
``cause_type`` branches don't cover network-topology roots at all).
"""

from __future__ import annotations

from datetime import datetime

from fabric_pipelines.comparison_report import (
    build_arm_result,
    compare,
    edge_view_from_camel_case,
    filter_dangling_edges,
    timed,
)
from fabric_pipelines.topology_pipeline import derive_edges
from hermes_arg_connector.normalize import Normalizer
from topology_comparison_scenario import NSG_ID, OBSERVED_AT, VNET_ID, topology_comparison_scenario

_OBSERVED_DT = datetime.fromisoformat(OBSERVED_AT.replace("Z", "+00:00"))


def _hermes_arm(root_id: str):
    scenario = topology_comparison_scenario()
    graph, elapsed = timed(
        Normalizer().normalize, scenario, _OBSERVED_DT, run_id="comparison-harness"
    )
    entity_ids = {
        str(entity["id"])
        for rows in graph.entities.values()
        for entity in rows
    }
    raw_edges = [edge_view_from_camel_case(edge) for edge in graph.relationships]
    # Normalizer.normalize() already drops dangling edges internally
    # (known_entity_ids filter, normalize.py:218-234) -- confirm parity by
    # re-applying the same filter and checking nothing further is dropped.
    filtered, _ = filter_dangling_edges(raw_edges, entity_ids)
    return build_arm_result(
        arm_name="hermes",
        root_id=root_id,
        entity_ids=entity_ids,
        edges=filtered,
        query_count=len(scenario),
        latency_seconds=elapsed,
        supplementary={"dangling_edges_dropped": True, "raw_edge_count": len(raw_edges)},
    ), graph


def _fabric_arm(root_id: str):
    scenario = topology_comparison_scenario()
    (entities, edges), elapsed = timed(derive_edges, scenario, observed=OBSERVED_AT)
    entity_ids = {str(entity["entity_id"]) for entity in entities}
    raw_edges = [edge_view_from_camel_case(edge) for edge in edges]
    filtered, dropped_any = filter_dangling_edges(raw_edges, entity_ids)
    return build_arm_result(
        arm_name="fabric",
        root_id=root_id,
        entity_ids=entity_ids,
        edges=filtered,
        query_count=len(scenario),
        latency_seconds=elapsed,
        supplementary={"dangling_edges_dropped": True, "raw_edge_count": len(raw_edges)},
    ), (entities, edges)


def test_shared_scenario_comparable_impact_both_arms():
    root_id = NSG_ID.lower()
    hermes_result, _ = _hermes_arm(root_id)
    fabric_result, _ = _fabric_arm(root_id)

    report = compare(hermes_result, fabric_result, root_id=root_id)

    assert report.root_id == root_id
    assert report.impacted_ids_match, (
        f"impacted sets diverge: hermes_only={report.hermes_only} "
        f"fabric_only={report.fabric_only}"
    )
    # D-04's five dimensions must all be present -- never a partial report.
    assert report.latency_seconds
    assert "note" in report.operational_cost_proxy
    assert report.hermes_missing_evidence == []
    assert report.fabric_missing_evidence == []
    assert report.hermes_scope_violations == []
    assert report.fabric_scope_violations == []
    # Subnet and VNet (containment/protection chain) must both be reachable
    # from the NSG root through the protectedBy edge, in both arms.
    assert VNET_ID.lower() in hermes_result.impacted_ids
    assert VNET_ID.lower() in fabric_result.impacted_ids


def test_non_accepted_edge_state_stays_explicit_in_both_arms():
    """An edge deliberately marked non-accepted in the fixture must survive
    into both arms' output as explicit -- not dropped, not silently
    upgraded to "accepted" (D-05)."""
    root_id = NSG_ID.lower()
    hermes_result, hermes_graph = _hermes_arm(root_id)
    fabric_result, (fabric_entities, fabric_edges) = _fabric_arm(root_id)

    # Inject one deliberately-stale/unauthorized-looking edge directly into
    # each arm's own edge collection (post-derivation), mirroring how a
    # conflicting/unauthorized observation would arrive from an external
    # join (e.g. flowlog_ingest's "fixture_only" state) without needing a
    # second shared fixture (Pitfall 3: same underlying entities, only the
    # edge's assertion_state differs).
    stale_predicate = "flaggedStale"
    subject = NSG_ID.lower()
    obj = VNET_ID.lower()

    hermes_stale_edge = {
        "relationshipId": "stale-hermes-0001",
        "subjectId": subject,
        "predicate": stale_predicate,
        "objectId": obj,
        "confidence": 0.4,
        "source": "test:injected-stale",
        "assertionState": "conflicting",
    }
    fabric_stale_edge = {
        "relationshipId": "stale-fabric-0001",
        "subjectId": subject,
        "predicate": stale_predicate,
        "objectId": obj,
        "confidence": 0.4,
        "source": "test:injected-stale",
        "assertionState": "conflicting",
    }

    hermes_edges = hermes_result.edges + [edge_view_from_camel_case(hermes_stale_edge)]
    fabric_edges_view = fabric_result.edges + [edge_view_from_camel_case(fabric_stale_edge)]

    hermes_with_stale = build_arm_result(
        arm_name="hermes",
        root_id=root_id,
        entity_ids=hermes_result.entity_ids,
        edges=hermes_edges,
        query_count=hermes_result.query_count,
        latency_seconds=hermes_result.latency_seconds,
        supplementary=hermes_result.supplementary,
    )
    fabric_with_stale = build_arm_result(
        arm_name="fabric",
        root_id=root_id,
        entity_ids=fabric_result.entity_ids,
        edges=fabric_edges_view,
        query_count=fabric_result.query_count,
        latency_seconds=fabric_result.latency_seconds,
        supplementary=fabric_result.supplementary,
    )

    report = compare(hermes_with_stale, fabric_with_stale, root_id=root_id)

    assert "conflicting" in report.non_accepted_states["hermes"]
    assert "conflicting" in report.non_accepted_states["fabric"]


def test_dangling_edge_dropped_consistently_by_both_arms():
    """An edge whose endpoint is missing from the emitted entity set must be
    dropped by both arms -- not silently kept in one arm only. Following the
    CR-01 fix (08-REVIEW.md), ``derive_edges()`` now ports the same
    ``known_entity_ids`` filter ``Normalizer.normalize()`` applies internally,
    so both arms drop dangling edges before the harness's own filter even
    runs, and the harness filter finds nothing further to drop in either
    case."""
    root_id = NSG_ID.lower()
    scenario = topology_comparison_scenario()

    graph = Normalizer().normalize(scenario, _OBSERVED_DT, run_id="comparison-harness")
    hermes_entity_ids = {
        str(entity["id"]) for rows in graph.entities.values() for entity in rows
    }
    hermes_raw_edges = [edge_view_from_camel_case(edge) for edge in graph.relationships]

    entities, edges = derive_edges(scenario, observed=OBSERVED_AT)
    fabric_entity_ids = {str(entity["entity_id"]) for entity in entities}
    fabric_raw_edges = [edge_view_from_camel_case(edge) for edge in edges]

    # Post-CR-01 fix: derive_edges() now filters dangling edges internally,
    # the same as Normalizer.normalize() always has -- neither arm's raw
    # output should contain a dangling edge to the unemitted resource-group
    # container any more.
    fabric_has_dangling_before_filter = any(
        edge.subject_id not in fabric_entity_ids or edge.object_id not in fabric_entity_ids
        for edge in fabric_raw_edges
    )
    assert fabric_has_dangling_before_filter is False, (
        "derive_edges() should no longer emit dangling edges after the CR-01 fix"
    )

    hermes_filtered, hermes_dropped_any = filter_dangling_edges(
        hermes_raw_edges, hermes_entity_ids
    )
    fabric_filtered, fabric_dropped_any = filter_dangling_edges(
        fabric_raw_edges, fabric_entity_ids
    )

    # Both arms now filter internally, so re-applying the harness filter
    # finds nothing further to drop in either case.
    assert hermes_dropped_any is False
    assert fabric_dropped_any is False

    # Once both arms pass through the shared harness filter, neither
    # arm's *comparable* edge set contains a dangling edge -- consistent
    # end state, which is what the comparison actually measures.
    assert all(
        edge.subject_id in hermes_entity_ids and edge.object_id in hermes_entity_ids
        for edge in hermes_filtered
    )
    assert all(
        edge.subject_id in fabric_entity_ids and edge.object_id in fabric_entity_ids
        for edge in fabric_filtered
    )
