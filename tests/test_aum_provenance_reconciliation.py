from __future__ import annotations

from dataclasses import replace

import pytest

from fabric.dataset_mapper import temporal_products_from_legacy
from fabric_pipelines.vulnerability_pipeline import (
    ExposureGoldFabricPublisher,
    materialize_temporal_exposure_tables,
)
from intelligence.vulnerability.exposure_projection import (
    build_temporal_projection,
    project_exposure_gold,
    reconcile_exposure_gold,
)
from storage.delta_writer import DeltaWriter
from storage.onelake_documents import OneLakeDocumentStore

TENANT = "tenant-a"
SUBSCRIPTION = "sub-a"
TARGET = (
    "/subscriptions/sub-a/resourceGroups/rg/providers/"
    "Microsoft.Compute/virtualMachines/vm-a"
)
PROJECTED_AT = "2026-09-14T00:05:00Z"


def _finding(
    kb: str,
    connection_id: str,
    *,
    generation: str,
    observed_at: str = "2026-09-14T00:00:00Z",
) -> dict:
    return {
        "tenant_id": TENANT,
        "subscription_id": SUBSCRIPTION,
        "resource_id": f"finding://{connection_id}/{kb}",
        "ingestion_run_id": generation,
        "connection_id": connection_id,
        "target_resource_id": TARGET,
        "kb_id": kb,
        "update_name": f"Update {kb}",
        "severity": "Critical",
        "status": "missing",
        "last_modified": observed_at,
    }


def _snapshot(
    connection_id: str,
    *,
    generation: str,
    completeness: str = "complete",
    status: str = "succeeded",
    freshness: str = "fresh",
    findings: list[dict] | None = None,
) -> dict[str, list[dict]]:
    snapshot_findings = list(findings or [])
    return {
        "silver_patch_findings": snapshot_findings,
        "silver_patch_snapshot_findings": snapshot_findings,
        "metadata_patch_snapshot": [
            {
                "tenant_id": TENANT,
                "subscription_id": SUBSCRIPTION,
                "resource_id": (
                    f"patch-snapshot://{TENANT}/{SUBSCRIPTION}/{connection_id}"
                ),
                "timestamp": PROJECTED_AT,
                "change_version": generation,
                "ingestion_run_id": generation,
                "connection_id": connection_id,
                "source_generation": generation,
                "status": status,
                "completeness": completeness,
                "freshness": freshness,
                "freshness_at": PROJECTED_AT,
                "freshness_threshold_seconds": 3600,
                "represented_count": len(snapshot_findings),
                "expected_count": len(snapshot_findings),
            }
        ],
    }


def _historical_five(*, generation: str = "generation-old"):
    datasets = {
        "silver_patch_findings": [
            _finding(f"KB{index}", f"legacy:{SUBSCRIPTION}", generation=generation)
            for index in range(1, 6)
        ]
    }
    return materialize_temporal_exposure_tables(
        temporal_products_from_legacy(
            datasets,
            generation_id=generation,
            ingested_at="2026-09-13T00:05:00Z",
        )
    )


def _materialize_refresh(
    *,
    completeness: str,
    status: str = "succeeded",
    freshness: str = "fresh",
    healthy_empty: bool = False,
    existing_rows: list[dict] | tuple[dict, ...] | None = None,
):
    generation = "generation-current"
    findings = (
        []
        if healthy_empty
        else [_finding("KB1", "demo", generation=generation)]
    )
    datasets = _snapshot(
        "demo",
        generation=generation,
        completeness=completeness,
        status=status,
        freshness=freshness,
        findings=findings,
    )
    projection = temporal_products_from_legacy(
        datasets,
        generation_id=generation,
        ingested_at=PROJECTED_AT,
    )
    historical = _historical_five()
    materialized = materialize_temporal_exposure_tables(
        projection,
        existing_rows=(
            historical.all_observation_rows
            if existing_rows is None
            else existing_rows
        ),
    )
    return datasets, materialized


def _gold_datasets(
    datasets: dict[str, list[dict]],
    materialized,
) -> dict[str, list[dict]]:
    return {
        **datasets,
        "gold_exposure_current": list(materialized.current_rows),
        "silver_exposure_observations": list(materialized.all_observation_rows),
        "gold_container_exposure_current": [],
        "silver_container_vulnerability_observations": [],
        "metadata_source_status": [],
        "silver_exposure_enrichment": [],
        "silver_defender_secure_scores": [],
    }


def test_complete_snapshot_reconciles_five_to_one_and_keeps_history() -> None:
    historical = _historical_five()
    historical_by_id = {
        row["observation_id"]: row for row in historical.all_observation_rows
    }
    datasets, materialized = _materialize_refresh(completeness="complete")

    assert len(materialized.current_rows) == 1
    assert materialized.current_rows[0]["weakness_id"] == "KB1"
    assert len(materialized.all_observation_rows) == 6
    refreshed_by_id = {
        row["observation_id"]: row for row in materialized.all_observation_rows
    }
    assert all(
        refreshed_by_id[observation_id] == row
        for observation_id, row in historical_by_id.items()
    )

    projection = project_exposure_gold(
        _gold_datasets(datasets, materialized),
        generation_id="gold-current",
        projected_at=PROJECTED_AT,
    )
    assert len(projection.facts) == 1
    assert projection.facts[0]["connection_id"] == "demo"
    assert projection.facts[0]["source_generation_id"] == "generation-current"


@pytest.mark.parametrize(
    ("completeness", "status", "freshness"),
    [
        ("partial", "partial", "fresh"),
        ("stale", "partial", "stale"),
        ("unavailable", "partial", "fresh"),
        ("complete", "failed-with-lkg", "fresh"),
    ],
)
def test_non_authoritative_snapshot_preserves_five_current_keys(
    completeness: str,
    status: str,
    freshness: str,
) -> None:
    _datasets, materialized = _materialize_refresh(
        completeness=completeness,
        status=status,
        freshness=freshness,
    )

    assert len(materialized.current_rows) == 5
    assert all(row["active"] for row in materialized.current_rows)


def test_healthy_empty_snapshot_removes_all_aum_current_keys() -> None:
    _datasets, materialized = _materialize_refresh(
        completeness="healthy-empty",
        healthy_empty=True,
    )

    assert materialized.current_rows == ()
    assert len(materialized.all_observation_rows) == 5


def test_complete_snapshot_closes_aum_but_preserves_mixed_defender_evidence() -> None:
    historical = _historical_five()
    defender = build_temporal_projection(
        [
            {
                "tenant_id": TENANT,
                "connection_id": "defender",
                "source_family": "defender_subassessment",
                "target_id": TARGET,
                "target_kind": "server",
                "weakness_id": "KB2",
                "weakness_kind": "kb",
                "status": "unhealthy",
                "provider_operation_id": "defender-kb2",
                "provider_event_time": "2026-09-13T01:00:00Z",
                "provider_event_time_quality": "provider",
            }
        ],
        generation_id="generation-defender",
        ingested_at="2026-09-13T01:05:00Z",
    )
    mixed = materialize_temporal_exposure_tables(
        defender,
        existing_rows=historical.all_observation_rows,
    )
    generation = "generation-current"
    datasets = _snapshot(
        "demo",
        generation=generation,
        findings=[_finding("KB1", "demo", generation=generation)],
    )
    refreshed = materialize_temporal_exposure_tables(
        temporal_products_from_legacy(
            datasets,
            generation_id=generation,
            ingested_at=PROJECTED_AT,
        ),
        existing_rows=mixed.all_observation_rows,
    )

    assert {row["weakness_id"] for row in refreshed.current_rows} == {
        "KB1",
        "KB2",
    }
    kb2 = next(row for row in refreshed.current_rows if row["weakness_id"] == "KB2")
    assert kb2["active_source_families"] == ["defender"]


def test_tied_legacy_and_demo_provenance_uses_authoritative_connection() -> None:
    generation = "generation-current"
    legacy = _finding("KB1", f"legacy:{SUBSCRIPTION}", generation=generation)
    demo = _finding("KB1", "demo", generation=generation)
    historical = materialize_temporal_exposure_tables(
        temporal_products_from_legacy(
            {"silver_patch_findings": [legacy]},
            generation_id=generation,
            ingested_at=PROJECTED_AT,
        )
    )
    datasets = _snapshot("demo", generation=generation, findings=[demo])
    materialized = materialize_temporal_exposure_tables(
        temporal_products_from_legacy(
            datasets,
            generation_id=generation,
            ingested_at=PROJECTED_AT,
        ),
        existing_rows=historical.all_observation_rows,
    )

    projection = project_exposure_gold(
        _gold_datasets(datasets, materialized),
        generation_id="gold-current",
        projected_at=PROJECTED_AT,
    )

    assert projection.facts[0]["connection_id"] == "demo"


def test_reconciliation_rejects_active_legacy_against_complete_demo_snapshot() -> None:
    datasets, materialized = _materialize_refresh(completeness="complete")
    gold_datasets = _gold_datasets(datasets, materialized)
    projection = project_exposure_gold(
        gold_datasets,
        generation_id="gold-current",
        projected_at=PROJECTED_AT,
    )
    fact = dict(projection.facts[0])
    fact["connection_id"] = f"legacy:{SUBSCRIPTION}"
    fact["scope_key"] = fact["scope_key"].replace("demo", f"legacy:{SUBSCRIPTION}")
    corrupted = replace(projection, facts=(fact,))

    with pytest.raises(ValueError, match="authoritative_patch_snapshot"):
        reconcile_exposure_gold(gold_datasets, corrupted)


def test_two_generation_publication_retains_legacy_and_activates_demo(
    tmp_path,
) -> None:
    historical = _historical_five()
    old_datasets = _gold_datasets({}, historical)
    datasets, refreshed = _materialize_refresh(completeness="complete")
    new_datasets = _gold_datasets(datasets, refreshed)
    publisher = ExposureGoldFabricPublisher(
        table_root=tmp_path / "Tables",
        delta_writer=DeltaWriter(),
        pointer_store=OneLakeDocumentStore(tmp_path / "Files"),
    )

    publisher.publish(
        old_datasets,
        generation_id="gold-old",
        projected_at="2026-09-13T00:05:00Z",
    )
    result = publisher.publish(
        new_datasets,
        generation_id="gold-new",
        projected_at=PROJECTED_AT,
    )
    rows = DeltaWriter().read(tmp_path / "Tables/gold_exposure_facts")
    old = [row for row in rows if row["read_model_generation_id"] == "gold-old"]
    new = [row for row in rows if row["read_model_generation_id"] == "gold-new"]

    assert result.readable_generation_id == "gold-new"
    assert len(old) == 5
    assert {row["connection_id"] for row in old} == {f"legacy:{SUBSCRIPTION}"}
    assert sum(bool(row["active"]) for row in old) == 5
    assert len(new) == 1
    assert {row["connection_id"] for row in new} == {"demo"}
    assert sum(bool(row["active"]) for row in new) == 1
    assert not any(
        row["active"] and row["connection_id"].startswith("legacy:")
        for row in new
    )
