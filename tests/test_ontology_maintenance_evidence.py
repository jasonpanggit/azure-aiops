"""Offline tests for source-grounded ontology evidence projection."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from functools import partial
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from onboarding.monitor_logs import APP_DEPENDENCIES_QUERY, AzureMonitorLogsClient
from ontology.subscription_connection import SubscriptionConnection
from ontology_discovery.dispatch_store import PublisherDispatchStore
from ontology_discovery.evidence_projection import (
    project_application_dependency_evidence,
)
from ontology_discovery.incremental import split_evidence_batches
from ontology_discovery.policy import ProposalPolicy
from ontology_discovery.runtime import ProductionConnectionProcessor
from ontology_discovery.store import OntologyRunStore

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
SCOPE = "tenant-1/sub-1"
GENERATION = "inventory-snapshot-7"
FRONTEND_ASSET = "/subscriptions/sub-1/resourcegroups/apps/providers/example/apps/front"
BACKEND_ASSET = "/subscriptions/sub-1/resourcegroups/apps/providers/example/apps/back"
FRONTEND_APP = "application://tenant-1/front"
BACKEND_APP = "application://tenant-1/back"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _fixture(
    *,
    monitor_rows: list[dict[str, object]] | None = None,
    inventory_records: list[dict[str, object]] | None = None,
    bindings: dict[str, str | list[str]] | None = None,
    observed_at: datetime = NOW,
    application_entities: Iterable[dict[str, object]] | None = None,
) -> dict[str, object]:
    rows = inventory_records or [
        {
            "resource_id": FRONTEND_ASSET,
            "payload_json": json.dumps(
                {
                    "id": FRONTEND_ASSET,
                    "tags": {
                        "aiops.dependencyResourceIds": json.dumps([BACKEND_ASSET])
                    },
                }
            ),
            "source_generation_id": GENERATION,
        },
        {
            "resource_id": BACKEND_ASSET,
            "payload_json": json.dumps({"id": BACKEND_ASSET, "tags": {}}),
            "source_generation_id": GENERATION,
        },
    ]
    return project_application_dependency_evidence(
        scope=SCOPE,
        batch_source_generation_id=GENERATION,
        observed_at=observed_at,
        application_entities=application_entities if application_entities is not None else [
            {
                "resource_id": FRONTEND_APP,
                "entity_type": "Application",
                "scope": SCOPE,
                "lifecycle_status": "active",
            },
            {
                "resource_id": BACKEND_APP,
                "entity_type": "Application",
                "scope": SCOPE,
                "lifecycle_status": "active",
            },
        ],
        deterministic_relationships=[
            {
                "subject_id": FRONTEND_ASSET,
                "predicate": "member_of",
                "object_id": FRONTEND_APP,
                "subject_type": "Resource",
                "object_type": "Application",
            },
            {
                "subject_id": BACKEND_ASSET,
                "predicate": "member_of",
                "object_id": BACKEND_APP,
                "subject_type": "Resource",
                "object_type": "Application",
            },
        ],
        inventory_records=rows,
        app_dependency_rows=monitor_rows or [],
        monitor_identity_bindings=bindings or {},
        inventory_generation_id=GENERATION,
        monitor_generation_id="monitor-window-2026-10-19T12:00Z",
        generation_binding_verified=True,
        max_age=timedelta(hours=24),
    )


def _monitor(
    *,
    when: datetime = NOW,
    synthetic: bool = False,
    target: str = "backend-role",
    success: bool = True,
) -> dict[str, object]:
    return {
        "TimeGenerated": when.isoformat(),
        "Id": "call-001",
        "OperationId": "operation-001",
        "_ResourceId": FRONTEND_ASSET,
        "_SubscriptionId": "sub-1",
        "AppRoleName": "frontend-role",
        "Target": target,
        "DependencyType": "HTTP",
        "Success": success,
        "SyntheticSource": "true" if synthetic else "",
        # User-supplied claims must not be treated as origin identity.
        "source": "independent",
        "source_system": "independent",
    }


def test_source_only_pair_reaches_review_with_independent_support() -> None:
    # The pair is novel: only physical-asset membership edges are deterministic.
    projection = _fixture(
        monitor_rows=[_monitor(), _monitor()],
        bindings={
            "frontend-role": FRONTEND_ASSET,
            "backend-role": BACKEND_ASSET,
        },
    )

    assert projection["candidate_pairs"] == [
        {
            "pair_id": f"{FRONTEND_APP}|depends_on|{BACKEND_APP}",
            "scope": SCOPE,
            "subject_id": FRONTEND_APP,
            "subject_type": "Application",
            "predicate": "depends_on",
            "object_id": BACKEND_APP,
            "object_type": "Application",
            "evidence_ids": sorted(
                row["evidence_id"] for row in projection["evidence_records"]
            ),
        }
    ]
    records = projection["evidence_records"]
    assert {record["source"] for record in records} == {
        "azure-resource-graph:dependency-tag",
        "azure-monitor:AppDependencies",
    }
    assert len(records) == 2
    assert len({record["origin_fingerprint"] for record in records}) == 2
    assert all(record["supports"] is True for record in records)
    assert {record["source_generation_id"] for record in records} == {GENERATION}
    assert all(record["original_source_generation_id"] for record in records)
    assert projection["uncertainties"] == []


def test_wrappers_duplicate_events_and_caller_source_labels_do_not_corroborate() -> None:
    first = _monitor()
    duplicate = {**first, "source": "different", "source_system": "another"}
    projection = _fixture(
        monitor_rows=[first, duplicate],
        bindings={
            "frontend-role": FRONTEND_ASSET,
            "backend-role": BACKEND_ASSET,
        },
    )

    assert len(projection["evidence_records"]) == 2
    monitor_facts = [
        row
        for row in projection["evidence_records"]
        if row["source"] == "azure-monitor:AppDependencies"
    ]
    assert len(monitor_facts) == 1
    assert monitor_facts[0]["source_system"] == "AppDependencies"


@pytest.mark.parametrize("container", [list, tuple, iter, lambda rows: (row for row in rows)],
                         ids=["list", "tuple", "iterator", "generator"])
def test_application_entity_iterables_preserve_projection_and_linked_batches(container) -> None:
    bindings = {"frontend-role": FRONTEND_ASSET, "backend-role": BACKEND_ASSET}
    expected = _fixture(monitor_rows=[_monitor()], bindings=bindings)
    projection = _fixture(
        monitor_rows=[_monitor()], bindings=bindings,
        application_entities=container(expected["changed_entities"]),
    )
    assert projection == expected
    batches = split_evidence_batches(
        changed_entities=projection["changed_entities"],
        candidate_pairs=projection["candidate_pairs"],
        evidence_records=projection["evidence_records"],
        source_generation_id=projection["source_generation_id"],
        observed_at=projection["observed_at"],
        freshness=projection["freshness"],
        coverage=projection["coverage"],
    )
    assert len(batches) == 1
    batch = batches[0]
    assert {row["entity_id"] for row in batch.changed_entities} == {FRONTEND_APP, BACKEND_APP}
    assert len(batch.candidate_pairs) == 1
    assert set(batch.candidate_pairs[0]["evidence_ids"]) == {
        row["evidence_id"] for row in batch.evidence_records
    }


def _inventory_with_timestamp(field: str, value: object) -> list[dict[str, object]]:
    return [
        {
            "resource_id": FRONTEND_ASSET,
            "tags": {"aiops.dependencyResourceIds": json.dumps([BACKEND_ASSET])},
            field: value,
        },
        {"resource_id": BACKEND_ASSET},
    ]


@pytest.mark.parametrize("field", ["observed_at", "timestamp"])
@pytest.mark.parametrize("value", [
    "not-a-timestamp", NOW.replace(tzinfo=None).isoformat(), 0, False, [], {},
])
@pytest.mark.parametrize("with_monitor", [False, True])
def test_invalid_inventory_timestamp_abstains_without_losing_independent_facts(
    field: str, value: object, with_monitor: bool,
) -> None:
    rows = _inventory_with_timestamp(field, value)
    before = json.dumps(rows, sort_keys=True)
    projection = _fixture(
        inventory_records=rows,
        monitor_rows=[_monitor()] if with_monitor else [],
        bindings={"frontend-role": FRONTEND_ASSET, "backend-role": BACKEND_ASSET},
    )
    assert json.dumps(rows, sort_keys=True) == before
    assert "source_observation_stale_or_timestamp_invalid" in projection["uncertainties"]
    assert projection["coverage"] == "degraded"
    assert len(projection["changed_entities"]) == 2
    if with_monitor:
        assert len(projection["candidate_pairs"]) == 1
        assert len(projection["evidence_records"]) == 1
        record = projection["evidence_records"][0]
        assert record["source"] == "azure-monitor:AppDependencies"
        assert record["supports"] is True
        assert projection["candidate_pairs"][0]["evidence_ids"] == [record["evidence_id"]]
        assert "dependency_pair_single_source_only" in projection["uncertainties"]
    else:
        assert projection["candidate_pairs"] == []
        assert projection["evidence_records"] == []


@pytest.mark.parametrize("value", [0, False, [], {}])
def test_invalid_primary_inventory_timestamp_cannot_use_valid_alternate(value: object) -> None:
    rows = _inventory_with_timestamp("observed_at", value)
    rows[0]["timestamp"] = NOW.isoformat()
    projection = _fixture(inventory_records=rows)
    assert projection["evidence_records"] == []
    assert projection["candidate_pairs"] == []
    assert "source_observation_stale_or_timestamp_invalid" in projection["uncertainties"]


@pytest.mark.parametrize("field", ["observed_at", "timestamp"])
@pytest.mark.parametrize("value,supports", [
    (NOW.isoformat(), True),
    (NOW, True),
    ("2026-10-19T14:00:00+02:00", True),
    ((NOW - timedelta(hours=24)).isoformat(), True),
    ((NOW - timedelta(hours=24, seconds=1)).isoformat(), False),
    ((NOW + timedelta(seconds=1)).isoformat(), False),
    (None, True),
    ("", True),
])
def test_valid_inventory_timestamps_preserve_freshness_and_existing_fallback(
    field: str, value: str | datetime | None, supports: bool,
) -> None:
    projection = _fixture(inventory_records=_inventory_with_timestamp(field, value))
    assert len(projection["evidence_records"]) == 1
    record = projection["evidence_records"][0]
    expected_time = value or NOW
    parsed = datetime.fromisoformat(expected_time) if isinstance(expected_time, str) else expected_time
    assert record["observed_at"] == parsed.astimezone(UTC).isoformat()
    assert record["expires_at"] == (
        parsed + timedelta(hours=24)
    ).astimezone(UTC).isoformat()
    assert record["supports"] is supports
    assert record["uncertainty"] == (
        "" if supports else "source_observation_stale_or_timestamp_invalid"
    )


def test_absent_ambiguous_out_of_scope_synthetic_and_stale_facts_abstain() -> None:
    cases = [
        _fixture(),
        _fixture(
            monitor_rows=[_monitor()],
            bindings={"frontend-role": FRONTEND_ASSET},
        ),
        _fixture(
            monitor_rows=[_monitor(target="backend-role")],
            bindings={
                "frontend-role": FRONTEND_ASSET,
                "backend-role": "/subscriptions/sub-2/resourceGroups/g/providers/x/y/z",
            },
        ),
        _fixture(
            monitor_rows=[_monitor(synthetic=True)],
            bindings={
                "frontend-role": FRONTEND_ASSET,
                "backend-role": BACKEND_ASSET,
            },
        ),
        _fixture(
            monitor_rows=[_monitor(when=NOW - timedelta(days=5))],
            bindings={
                "frontend-role": FRONTEND_ASSET,
                "backend-role": BACKEND_ASSET,
            },
        ),
    ]
    for projection in cases:
        assert not any(
            row["supports"] is True
            and row["source"] == "azure-monitor:AppDependencies"
            for row in projection["evidence_records"]
        )
        assert projection["uncertainties"]


def test_source_generation_mismatch_and_conflicting_inventory_records_abstain() -> None:
    records = [
        {
            "resource_id": FRONTEND_ASSET,
            "payload_json": json.dumps(
                {
                    "id": FRONTEND_ASSET,
                    "tags": {
                        "aiops.dependencyResourceIds": json.dumps([BACKEND_ASSET])
                    },
                }
            ),
            "source_generation_id": "older-inventory-generation",
        },
        {
            "resource_id": BACKEND_ASSET,
            "payload_json": json.dumps({"id": BACKEND_ASSET, "tags": {}}),
            "source_generation_id": GENERATION,
        },
    ]
    generation_mismatch = _fixture(
        inventory_records=records,
        monitor_rows=None,
    )
    declaration = next(
        row for row in generation_mismatch["evidence_records"]
        if row["source"] == "azure-resource-graph:dependency-tag"
    )
    assert declaration["supports"] is False
    assert declaration["original_source_generation_id"] == "older-inventory-generation"
    assert "source_generation_mismatch" in generation_mismatch["uncertainties"]

    conflicting = [
        records[0],
        {
            **records[0],
            "payload_json": json.dumps(
                {"id": FRONTEND_ASSET, "tags": {"aiops.dependencyResourceIds": "[]"}}
            ),
        },
        records[1],
    ]
    projection = _fixture(inventory_records=conflicting, monitor_rows=None)
    assert not projection["candidate_pairs"]
    assert "inventory_duplicate_resource_conflict" in projection["uncertainties"]


@pytest.mark.parametrize("conflict", [
    {"observed_at": (NOW - timedelta(seconds=1)).isoformat()},
    {"observed_at": (NOW - timedelta(days=2)).isoformat()},
    {"observed_at": (NOW + timedelta(seconds=1)).isoformat()},
    {"observed_at": "invalid"},
    {"source_generation_id": "different-inventory-generation"},
])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("with_monitor", [False, True])
def test_duplicate_inventory_provenance_conflicts_abstain_in_any_order(
    conflict: dict[str, object], reverse: bool, with_monitor: bool,
) -> None:
    row = {
        "resource_id": FRONTEND_ASSET,
        "payload_json": json.dumps({
            "id": FRONTEND_ASSET,
            "tags": {"aiops.dependencyResourceIds": json.dumps([BACKEND_ASSET])},
        }),
        "observed_at": NOW.isoformat(),
        "source_generation_id": f" {GENERATION} ",
    }
    duplicates = [row, {**row, **conflict}]
    if reverse:
        duplicates.reverse()
    rows = [*duplicates, {"resource_id": BACKEND_ASSET}]
    before = deepcopy(rows)
    projection = _fixture(
        inventory_records=rows,
        monitor_rows=[_monitor()] if with_monitor else [],
        bindings={"frontend-role": FRONTEND_ASSET, "backend-role": BACKEND_ASSET},
    )
    assert rows == before
    assert "inventory_duplicate_resource_conflict" in projection["uncertainties"]
    assert projection["coverage"] == "degraded"
    assert len(projection["changed_entities"]) == 2
    assert {record["source"] for record in projection["evidence_records"]} == (
        {"azure-monitor:AppDependencies"} if with_monitor else set()
    )
    if with_monitor:
        assert len(projection["candidate_pairs"]) == 1
        assert projection["evidence_records"][0]["supports"] is True
        assert projection["candidate_pairs"][0]["evidence_ids"] == [
            projection["evidence_records"][0]["evidence_id"],
        ]
    else:
        assert projection["candidate_pairs"] == []


@pytest.mark.parametrize("reverse", [False, True])
def test_equivalent_duplicate_inventory_provenance_preserves_exact_projection(reverse: bool) -> None:
    row = {
        "resource_id": FRONTEND_ASSET,
        "payload_json": json.dumps({
            "id": FRONTEND_ASSET,
            "tags": {"aiops.dependencyResourceIds": json.dumps([BACKEND_ASSET])},
        }),
    }
    equivalent = {
        **row, "timestamp": "2026-10-19T14:00:00+02:00",
        "source_generation_id": GENERATION,
    }
    bindings = {"frontend-role": FRONTEND_ASSET, "backend-role": BACKEND_ASSET}
    expected = _fixture(
        inventory_records=[row, {"resource_id": BACKEND_ASSET}],
        monitor_rows=[_monitor()], bindings=bindings,
    )
    duplicates = [row, equivalent]
    if reverse:
        duplicates.reverse()
    assert _fixture(
        inventory_records=[*duplicates, {"resource_id": BACKEND_ASSET}],
        monitor_rows=[_monitor()], bindings=bindings,
    ) == expected


@pytest.mark.parametrize("conflicting", ["[]", None, "invalid", False])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("with_monitor", [False, True])
def test_conflicting_case_variant_dependency_tags_abstain_in_any_order(
    conflicting: object, reverse: bool, with_monitor: bool,
) -> None:
    tags = [
        ("aiops.dependencyResourceIds", json.dumps([BACKEND_ASSET])),
        ("AIOPS.DEPENDENCYRESOURCEIDS", conflicting),
    ]
    if reverse:
        tags.reverse()
    rows = [
        {"resource_id": FRONTEND_ASSET, "payload_json": json.dumps({"tags": dict(tags)})},
        {"resource_id": BACKEND_ASSET},
    ]
    before = deepcopy(rows)
    projection = _fixture(
        inventory_records=rows,
        monitor_rows=[_monitor()] if with_monitor else [],
        bindings={"frontend-role": FRONTEND_ASSET, "backend-role": BACKEND_ASSET},
    )
    assert rows == before
    assert "dependency_declaration_conflict" in projection["uncertainties"]
    assert projection["coverage"] == "degraded"
    assert len(projection["changed_entities"]) == 2
    assert {row["source"] for row in projection["evidence_records"]} == (
        {"azure-monitor:AppDependencies"} if with_monitor else set()
    )
    if with_monitor:
        assert len(projection["candidate_pairs"]) == 1
        assert projection["evidence_records"][0]["supports"] is True
        assert projection["candidate_pairs"][0]["evidence_ids"] == [
            projection["evidence_records"][0]["evidence_id"],
        ]
    else:
        assert projection["candidate_pairs"] == []


@pytest.mark.parametrize("tag_names", [
    ["aiops.dependencyResourceIds"],
    ["AIOPS.DEPENDENCYRESOURCEIDS"],
    ["aiops.dependencyResourceIds", "AIOPS.DEPENDENCYRESOURCEIDS"],
    ["AIOPS.DEPENDENCYRESOURCEIDS", "aiops.dependencyResourceIds"],
])
def test_unambiguous_case_variant_dependency_tags_retain_support(tag_names: list[str]) -> None:
    projection = _fixture(
        inventory_records=[
            {
                "resource_id": FRONTEND_ASSET,
                "payload_json": json.dumps({
                    "tags": dict.fromkeys(tag_names, json.dumps([BACKEND_ASSET])),
                }),
            },
            {"resource_id": BACKEND_ASSET},
        ],
        monitor_rows=[_monitor()],
        bindings={"frontend-role": FRONTEND_ASSET, "backend-role": BACKEND_ASSET},
    )
    assert projection["coverage"] == "complete"
    assert projection["uncertainties"] == []
    assert len(projection["candidate_pairs"]) == 1
    assert len(projection["evidence_records"]) == 2
    assert all(row["supports"] for row in projection["evidence_records"])
    assert set(projection["candidate_pairs"][0]["evidence_ids"]) == {
        row["evidence_id"] for row in projection["evidence_records"]
    }


@pytest.mark.parametrize("timestamp", [
    "9999-12-31T00:00:00+00:00",
    "9999-12-31T23:59:59.999999+00:00",
    "9999-12-30T23:59:59.999999-01:00",
    "9999-12-31T23:59:59-01:00",
    "0001-01-01T00:00:00+01:00",
])
@pytest.mark.parametrize("source", ["inventory", "monitor"])
def test_unrepresentable_dependency_times_abstain_without_losing_other_source(
    timestamp: str, source: str,
) -> None:
    rows = _inventory_with_timestamp("observed_at", timestamp if source == "inventory" else NOW)
    monitor = _monitor()
    monitor["TimeGenerated"] = timestamp if source == "monitor" else NOW.isoformat()
    before = deepcopy((rows, monitor))
    projection = _fixture(
        inventory_records=rows, monitor_rows=[monitor],
        bindings={"frontend-role": FRONTEND_ASSET, "backend-role": BACKEND_ASSET},
    )
    assert (rows, monitor) == before
    assert projection["coverage"] == "degraded"
    expected_uncertainty = (
        "dependency_observation_timestamp_missing"
        if source == "monitor" and timestamp in {
            "9999-12-31T23:59:59-01:00", "0001-01-01T00:00:00+01:00",
        }
        else "source_observation_stale_or_timestamp_invalid"
    )
    assert expected_uncertainty in projection["uncertainties"]
    expected_source = (
        "azure-monitor:AppDependencies" if source == "inventory"
        else "azure-resource-graph:dependency-tag"
    )
    assert len(projection["evidence_records"]) == 1
    assert projection["evidence_records"][0]["source"] == expected_source
    assert projection["evidence_records"][0]["supports"] is True
    assert len(projection["changed_entities"]) == 2
    assert len(projection["candidate_pairs"]) == 1
    assert projection["candidate_pairs"][0]["evidence_ids"] == [
        projection["evidence_records"][0]["evidence_id"],
    ]


@pytest.mark.parametrize("timestamp", [
    "9999-12-30T23:59:59.999999+00:00",
    "0001-01-01T00:00:00+00:00",
    NOW.isoformat(),
])
@pytest.mark.parametrize("source", ["inventory", "monitor"])
def test_representable_dependency_expiry_retains_existing_facts(
    timestamp: str, source: str,
) -> None:
    monitor = _monitor()
    monitor["TimeGenerated"] = timestamp if source == "monitor" else NOW.isoformat()
    projection = _fixture(
        inventory_records=_inventory_with_timestamp(
            "observed_at", timestamp if source == "inventory" else NOW,
        ),
        monitor_rows=[monitor],
        bindings={"frontend-role": FRONTEND_ASSET, "backend-role": BACKEND_ASSET},
    )
    assert len(projection["evidence_records"]) == 2
    selected = next(row for row in projection["evidence_records"] if row["source"] == (
        "azure-resource-graph:dependency-tag" if source == "inventory"
        else "azure-monitor:AppDependencies"
    ))
    assert datetime.fromisoformat(selected["expires_at"]) == (
        datetime.fromisoformat(timestamp) + timedelta(hours=24)
    )
    assert selected["supports"] is (timestamp == NOW.isoformat())


def test_ambiguous_monitor_binding_is_not_resolved_by_label() -> None:
    projection = _fixture(
        monitor_rows=[_monitor()],
        bindings={
            "frontend-role": [FRONTEND_ASSET, BACKEND_ASSET],
            "backend-role": BACKEND_ASSET,
        },
    )

    assert not any(
        row["source"] == "azure-monitor:AppDependencies" and row["supports"]
        for row in projection["evidence_records"]
    )
    assert "dependency_monitor_identity_binding_missing" in projection["uncertainties"]


@pytest.mark.parametrize("order", list(permutations(range(3))))
@pytest.mark.parametrize("label,valid,conflicting", [
    ("frontend-role", FRONTEND_ASSET, BACKEND_ASSET),
    ("backend-role", BACKEND_ASSET, FRONTEND_ASSET),
])
def test_conflicting_normalized_monitor_aliases_abstain_in_any_order(
    order: tuple[int, ...], label: str, valid: str, conflicting: str,
) -> None:
    aliases = [(label, valid), (label.upper(), conflicting), (f" {label} ", valid)]
    bindings = dict(aliases[index] for index in order)
    bindings.setdefault("frontend-role", FRONTEND_ASSET)
    bindings.setdefault("backend-role", BACKEND_ASSET)
    projection = _fixture(monitor_rows=[_monitor()], bindings=bindings)
    assert {row["source"] for row in projection["evidence_records"]} == {
        "azure-resource-graph:dependency-tag",
    }
    assert "dependency_monitor_identity_binding_missing" in projection["uncertainties"]
    assert projection["coverage"] == "degraded"


@pytest.mark.parametrize("ambiguous", [[], [FRONTEND_ASSET, BACKEND_ASSET]])
@pytest.mark.parametrize("reverse", [False, True])
def test_ambiguous_monitor_alias_cannot_be_replaced_by_a_unique_alias(
    ambiguous: list[str], reverse: bool,
) -> None:
    aliases = [
        ("FRONTEND-ROLE", ambiguous),
        (" frontend-role ", FRONTEND_ASSET),
    ]
    if reverse:
        aliases.reverse()
    bindings = {"backend-role": BACKEND_ASSET, **dict(aliases)}
    projection = _fixture(monitor_rows=[_monitor()], bindings=bindings)
    assert {row["source"] for row in projection["evidence_records"]} == {
        "azure-resource-graph:dependency-tag",
    }
    assert "dependency_monitor_identity_binding_missing" in projection["uncertainties"]


def test_normalized_monitor_aliases_for_the_same_resource_preserve_support() -> None:
    canonical = {"frontend-role": FRONTEND_ASSET, "backend-role": BACKEND_ASSET}
    expected = _fixture(monitor_rows=[_monitor()], bindings=canonical)
    projection = _fixture(
        monitor_rows=[_monitor()],
        bindings={
            **canonical,
            " FRONTEND-ROLE ": f" {FRONTEND_ASSET.upper()} ",
            "BACKEND-ROLE": [BACKEND_ASSET, BACKEND_ASSET.upper()],
        },
    )
    assert projection == expected


def test_ambiguous_inventory_identity_does_not_choose_an_application() -> None:
    projection = project_application_dependency_evidence(
        scope=SCOPE,
        batch_source_generation_id=GENERATION,
        observed_at=NOW,
        application_entities=[
            {"resource_id": FRONTEND_APP, "entity_type": "Application", "scope": SCOPE},
            {"resource_id": BACKEND_APP, "entity_type": "Application", "scope": SCOPE},
            {"resource_id": "application://other", "entity_type": "Application", "scope": SCOPE},
        ],
        deterministic_relationships=[
            {
                "subject_id": FRONTEND_ASSET,
                "predicate": "member_of",
                "object_id": FRONTEND_APP,
            },
            {
                "subject_id": FRONTEND_ASSET,
                "predicate": "member_of",
                "object_id": "application://other",
            },
            {
                "subject_id": BACKEND_ASSET,
                "predicate": "member_of",
                "object_id": BACKEND_APP,
            },
        ],
        inventory_records=[
            {
                "resource_id": FRONTEND_ASSET,
                "payload_json": json.dumps(
                    {"tags": {"aiops.dependencyResourceIds": json.dumps([BACKEND_ASSET])}}
                ),
                "source_generation_id": GENERATION,
            }
        ],
        app_dependency_rows=[],
        monitor_identity_bindings={},
        inventory_generation_id=GENERATION,
        monitor_generation_id="monitor-window-empty",
        max_age=timedelta(hours=24),
    )

    assert not projection["candidate_pairs"]
    assert not any(record["supports"] for record in projection["evidence_records"])
    assert any("ambiguous" in value for value in projection["uncertainties"])


def test_linked_source_facts_are_kept_with_pairs_across_batch_caps() -> None:
    pairs = []
    evidence = []
    for index in range(21):
        target = f"application://tenant-1/target-{index:02}"
        pair_id = f"{FRONTEND_APP}|depends_on|{target}"
        evidence_ids = [f"E-{index:02}-inventory", f"E-{index:02}-monitor"]
        pairs.append(
            {
                "pair_id": pair_id,
                "scope": SCOPE,
                "subject_id": FRONTEND_APP,
                "subject_type": "Application",
                "predicate": "depends_on",
                "object_id": target,
                "object_type": "Application",
                "evidence_ids": evidence_ids,
            }
        )
        evidence.extend(
            {
                "evidence_id": evidence_id,
                "scope": SCOPE,
                "entity_ids": [FRONTEND_APP, target],
                "source": source,
            }
            for evidence_id, source in zip(
                evidence_ids,
                (
                    "azure-resource-graph:dependency-tag",
                    "azure-monitor:AppDependencies",
                ),
                strict=True,
            )
        )

    batches = split_evidence_batches(
        changed_entities=[],
        candidate_pairs=pairs,
        evidence_records=evidence,
        source_generation_id=GENERATION,
        observed_at=NOW,
        freshness="fresh",
        coverage="complete",
    )

    assert len(batches) == 2
    assert all(len(batch.evidence_records) <= 40 for batch in batches)
    assert all(
        {
            row["evidence_id"] for row in batch.evidence_records
        }
        >= set(pair["evidence_ids"])
        for batch in batches
        for pair in batch.candidate_pairs
    )
    assert {
        pair["pair_id"] for batch in batches for pair in batch.candidate_pairs
    } == {pair["pair_id"] for pair in pairs}


def test_fixed_monitor_query_is_narrow_bounded_and_uses_workspace_scope() -> None:
    class Credential:
        @staticmethod
        def get_token(scope):
            assert scope == "https://api.loganalytics.io/.default"
            return SimpleNamespace(token="fixture-token")

    requests = []
    payload = {
        "tables": [
            {
                "columns": [{"name": "TimeGenerated", "type": "datetime"}],
                "rows": [[NOW.isoformat()]],
            }
        ]
    }

    def requester(method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(200, json=payload)

    rows = AzureMonitorLogsClient(
        Credential(), requester=requester
    ).query_application_dependencies("workspace-1")

    assert rows == [{"TimeGenerated": NOW.isoformat()}]
    assert len(requests) == 1
    method, url, kwargs = requests[0]
    assert method == "POST"
    assert "/workspaces/workspace-1/query" in url
    query = kwargs["json"]["query"]
    assert query == APP_DEPENDENCIES_QUERY
    for field in (
        "TimeGenerated",
        "Id",
        "OperationId",
        "_ResourceId",
        "_SubscriptionId",
        "AppRoleName",
        "Target",
        "DependencyType",
        "Success",
        "SyntheticSource",
    ):
        assert field in query
    assert "take 5000" in query
    projected_fields = {
        field.strip().strip(",")
        for field in query.split("| project", 1)[1].split("|", 1)[0].split(",")
    }
    assert not projected_fields.intersection({"Data", "Name", "Properties"})
    assert "TenantId" not in query


@pytest.mark.parametrize("policy_age_days", [0, 2])
def test_runtime_source_projection_reaches_parser_policy_and_durable_dispatch(
    tmp_path: Path, monkeypatch, policy_age_days: int
) -> None:
    import ontology_discovery.runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "ProposalPolicy",
        partial(ProposalPolicy, now=lambda: NOW + timedelta(days=policy_age_days)),
    )
    inventory_generation = "inventory-generation-7"
    runtime_scope = "tenant-1:sub-1:offline-connection"
    application_entities = [
        {
            "resource_id": FRONTEND_APP,
            "entity_id": FRONTEND_APP,
            "entity_type": "Application",
            "name": "frontend",
            "scope": runtime_scope,
            "lifecycle_status": "active",
        },
        {
            "resource_id": BACKEND_APP,
            "entity_id": BACKEND_APP,
            "entity_type": "Application",
            "name": "backend",
            "scope": runtime_scope,
            "lifecycle_status": "active",
        },
    ]
    deterministic = [
        {
            "resource_id": "membership-front",
            "subject_id": FRONTEND_ASSET,
            "subject_type": "Resource",
            "predicate": "member_of",
            "object_id": FRONTEND_APP,
            "object_type": "Application",
            "scope": runtime_scope,
        },
        {
            "resource_id": "membership-back",
            "subject_id": BACKEND_ASSET,
            "subject_type": "Resource",
            "predicate": "member_of",
            "object_id": BACKEND_APP,
            "object_type": "Application",
            "scope": runtime_scope,
        },
    ]
    bronze_resources = [
        {
            "resource_id": FRONTEND_ASSET,
            "source_generation_id": inventory_generation,
            "payload_json": json.dumps(
                {
                    "id": FRONTEND_ASSET,
                    "tags": {
                        "aiops.dependencyResourceIds": json.dumps([BACKEND_ASSET])
                    },
                }
            ),
        },
        {
            "resource_id": BACKEND_ASSET,
            "source_generation_id": inventory_generation,
            "payload_json": json.dumps({"id": BACKEND_ASSET, "tags": {}}),
        },
    ]
    datasets = {
        "ontology_entities": application_entities,
        "ontology_relationships": deterministic,
        "bronze_resources": bronze_resources,
    }
    manifest = {
        "runId": inventory_generation,
        "startedAt": NOW.isoformat(),
        "source": "offline-fixture",
    }

    class FakeDatasetStore:
        fs = None
        is_remote = False

        @staticmethod
        def current_generation():
            return "offline-snapshot"

    class FakePipeline:
        store = FakeDatasetStore()

        @staticmethod
        def refresh():
            return SimpleNamespace(manifest=manifest)

    monkeypatch.setattr(
        runtime_module,
        "build_connection_inventory_pipeline",
        lambda *_args, **_kwargs: FakePipeline(),
    )
    monkeypatch.setattr(
        runtime_module.InventoryDatasetMapper,
        "load",
        lambda *_args, **_kwargs: datasets,
    )

    class ValidationReport:
        passed = True

        @staticmethod
        def to_dict():
            return {"passed": True, "errors": []}

    class Validator:
        @staticmethod
        def validate(_entities, _relationships):
            return ValidationReport()

    monkeypatch.setattr(runtime_module, "OntologyValidator", Validator)

    class SourceGroundedCurator:
        async def propose(self, run, evidence):
            pair = next(
                row
                for row in evidence["candidate_pairs"]
                if row.get("subject_id") == FRONTEND_APP
                and row.get("predicate") == "depends_on"
            )
            return {
                "batch_id": evidence["batch_id"],
                "status": "proposals",
                "missing_evidence": [],
                "proposals": [
                    {
                        "subject_id": pair["subject_id"],
                        "subject_type": pair["subject_type"],
                        "predicate": pair["predicate"],
                        "object_id": pair["object_id"],
                        "object_type": pair["object_type"],
                        "evidence_refs": list(pair["evidence_ids"]),
                        "observed_at": NOW.isoformat(),
                        "rationale": "Two exact independent source facts.",
                        "confidence": 0.95,
                        "uncertainty": [],
                        "disposition": "propose",
                    }
                ],
            }

    connection = SubscriptionConnection(
        connection_id="offline-connection",
        name="offline",
        tenant_id="tenant-1",
        subscription_id="sub-1",
        is_active=True,
    )
    store = OntologyRunStore(tmp_path / "runs.json")
    queued, _ = store.get_or_create_run(
        connection_id=connection.connection_id,
        source_generation_id="logical-generation-7",
        trigger="manual",
        requested_by="offline-test",
        now=NOW,
    )
    run = store.claim(
        queued["run_id"],
        expected_revision=queued["revision"],
        owner="offline-worker",
        lease_seconds=600,
        now=NOW,
    )
    dispatch = PublisherDispatchStore(str(tmp_path / "dispatch")).coordinator()
    processor = ProductionConnectionProcessor(
        store=store,
        dispatch=dispatch,
        connector_config=object(),
        curator=SourceGroundedCurator(),
        resolver=object(),
        monitor_dependency_reader=lambda _connection: [_monitor()],
        monitor_identity_bindings=lambda _connection: {
            "frontend-role": FRONTEND_ASSET,
            "backend-role": BACKEND_ASSET,
        },
        now=lambda: NOW,
    )

    result = asyncio.run(processor(connection, run))
    durable_batches = store.list_evidence_batches(run_id=run["run_id"])
    assert result["status"] == "dispatch_created"
    assert len(durable_batches) == 1
    assert durable_batches[0]["status"] == "dispatched"
    evidence_rows = durable_batches[0]["batch"]["evidence_records"]
    assert {row["source"] for row in evidence_rows} == {
        "azure-resource-graph:dependency-tag",
        "azure-monitor:AppDependencies",
    }
    proposal = durable_batches[0]["result"]["proposals"][0]
    record, _ = store.save_proposal(
        proposal=proposal,
        scope=runtime_scope,
        source_generation_id=run["source_generation_id"],
        schema_version="proposal-schema-v1",
        policy_version="proposal-policy-v1",
        now=NOW,
    )
    decision = processor.policy_coordinator.build_candidate(
        proposals=[record],
        deterministic_edges=deterministic,
        entities={row["resource_id"]: row for row in application_entities},
        evidence_records={row["evidence_id"]: row for row in evidence_rows},
        scope=runtime_scope,
        source_generation_id=run["source_generation_id"],
    )["decisions"][0]
    assert decision.policy_eligible is (policy_age_days == 0)
    assert ("stale_evidence" in decision.reasons) is (policy_age_days == 2)
    assert decision.admitted is False
    assert store.get(run["run_id"])["checkpoint"]["payload"]["source_binding"][
        "inventory_generation_id"
    ] == inventory_generation
    baseline = store.get_committed_baseline(
        connection_id=connection.connection_id,
        scope=runtime_scope,
        lineage_key="inventory+appdependencies:v1",
    )
    assert baseline["coverage"] == "complete"
    assert baseline["source_fingerprint"]
