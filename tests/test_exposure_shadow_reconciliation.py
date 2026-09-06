"""Scoped, generation-bound old/new Exposure reconciliation contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from api.exposure_query import ExposureQueryService
from fabric_pipelines.vulnerability_pipeline import (
    EXPOSURE_GOLD_GENERATIONS_TABLE,
    ExposureCutoverBlocked,
    ExposureGoldFabricPublisher,
)
from operations.exposure_metrics import (
    ExposureReconciliationPolicy,
    reconcile_exposure_arms,
)
from storage.delta_writer import DeltaWriter
from storage.onelake_documents import OneLakeDocumentStore
from tests.exposure_scenario import load_exposure_scenario

GENERATION = "generation-shadow-1"
TARGET = (
    "/subscriptions/sub-sensitive/resourceGroups/rg/providers/"
    "Microsoft.Compute/virtualMachines/vm-sensitive"
)


def _row(
    suffix: str,
    *,
    state: str = "missing",
    completeness: str = "complete",
    freshness: str = "fresh",
    recommendation: str = "Apply the current security update.",
    target_kind: str = "server",
    source_families: tuple[str, ...] = (
        "azure_update_manager_missing",
        "defender_subassessment",
    ),
    deployment_ids: tuple[str, ...] = (),
    enrichment_score: float = 0.8,
    scope_key: str = "scope-sensitive",
) -> dict[str, Any]:
    return {
        "read_model_generation_id": GENERATION,
        "scope_key": scope_key,
        "exposure_id": f"exposure-{suffix}",
        "target_id": f"{TARGET}-{suffix}",
        "weakness_id": f"CVE-2026-{suffix}",
        "state": state,
        "completeness": completeness,
        "freshness": freshness,
        "recommendation": recommendation,
        "target_kind": target_kind,
        "source_families": list(source_families),
        "deployment_ids": list(deployment_ids),
        "enrichment_score": enrichment_score,
    }


def _reconcile(
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
    **kwargs: Any,
):
    return reconcile_exposure_arms(
        old_rows,
        new_rows,
        generation_id=GENERATION,
        old_completeness=kwargs.pop("old_completeness", "complete"),
        new_completeness=kwargs.pop("new_completeness", "complete"),
        authorized_scope_keys=kwargs.pop(
            "authorized_scope_keys",
            {"scope-sensitive"},
        ),
        **kwargs,
    )


def test_reconciliation_fixture_declares_every_zero_tolerance_difference() -> None:
    scenario = load_exposure_scenario()

    assert set(scenario["reconciliation_contract"]["hard_failure_classes"]) == {
        "scope_widening",
        "source_class_disappearance",
        "false_healthy_empty",
        "false_clear",
        "missing_image_relationship",
        "cursor_duplicate",
        "cursor_omission",
    }


def test_shadow_comparison_checks_both_arms_without_assuming_either_is_truth() -> None:
    report = _reconcile(
        [_row("old-only")],
        [_row("new-only")],
    )

    assert report.blocks_cutover is True
    assert report.mismatch_counts["stable_key"] == 2
    assert report.mismatch_counts["count"] == 0
    assert {
        "old_only",
        "new_only",
    } <= {sample["side"] for sample in report.redacted_samples}
    serialized = json.dumps(report.to_manifest(), sort_keys=True)
    assert "old-only" not in serialized
    assert "new-only" not in serialized
    assert "sub-sensitive" not in serialized
    assert "CVE-" not in serialized


def test_scope_widening_is_a_hard_reconciliation_failure() -> None:
    report = _reconcile(
        [_row("one")],
        [_row("one"), _row("outside", scope_key="scope-not-authorized")],
    )

    assert report.mismatch_counts["scope_widening"] == 1
    assert "scope_widening" in report.hard_failure_classes
    assert report.blocks_cutover is True
    assert report.policy["max_unexpected_mismatch_count"] == 0


@pytest.mark.parametrize(
    ("old_rows", "new_rows", "old_completeness", "new_completeness", "mismatch"),
    [
        ([_row("one")], [], "complete", "healthy-empty", "false_healthy_empty"),
        (
            [_row("one", state="missing")],
            [_row("one", state="resolved")],
            "complete",
            "complete",
            "false_clear",
        ),
    ],
)
def test_false_clear_or_false_healthy_empty_blocks_cutover(
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
    old_completeness: str,
    new_completeness: str,
    mismatch: str,
) -> None:
    report = _reconcile(
        old_rows,
        new_rows,
        old_completeness=old_completeness,
        new_completeness=new_completeness,
    )

    assert report.mismatch_counts[mismatch] > 0
    assert mismatch in report.hard_failure_classes
    assert report.passed is False


def test_source_class_identity_state_order_and_completeness_drift_is_reported() -> None:
    old_rows = [_row("one"), _row("two")]
    new_rows = [
        _row(
            "two",
            state="resolved",
            freshness="stale",
            recommendation="Review manually.",
            target_kind="container_image",
            source_families=("azure_update_manager_missing",),
        ),
        _row("three"),
    ]

    report = _reconcile(
        old_rows,
        new_rows,
        old_completeness="complete",
        new_completeness="partial",
    )

    assert {
        "source_class_disappearance",
        "stable_key",
        "state",
        "order",
        "completeness",
        "freshness",
        "recommendation",
        "target_kind",
    } <= {
        mismatch
        for mismatch, count in report.mismatch_counts.items()
        if count
    }
    assert report.compared_count == 3
    assert report.mismatch_ratio > 0
    assert report.blocks_cutover is True


def test_duplicate_and_omitted_cursor_keys_are_hard_failures() -> None:
    report = _reconcile(
        [_row("one"), _row("two")],
        [_row("one"), _row("one")],
    )

    assert report.mismatch_counts["cursor_duplicate"] == 1
    assert report.mismatch_counts["cursor_omission"] == 1
    assert {"cursor_duplicate", "cursor_omission"} <= set(
        report.hard_failure_classes
    )


def test_missing_image_relationship_is_a_hard_failure() -> None:
    old = _row(
        "image",
        target_kind="container_image",
        deployment_ids=("deployment-sensitive",),
    )
    new = _row("image", target_kind="container_image")

    report = _reconcile([old], [new])

    assert report.mismatch_counts["missing_image_relationship"] == 1
    assert report.blocks_cutover is True


def test_expected_time_varying_enrichment_change_is_classified_separately() -> None:
    old = _row("one", enrichment_score=0.8)
    new = _row("one", enrichment_score=0.9)
    report = _reconcile(
        [old],
        [new],
        expected_changes={
            ("scope-sensitive", "exposure-one"): {
                "time_varying_enrichment_score"
            }
        },
    )

    assert report.expected_change_counts == {
        "time_varying_enrichment_score": 1
    }
    assert report.unexpected_mismatch_count == 0
    assert report.mismatch_ratio == 0
    assert report.passed is True
    assert report.blocks_cutover is False


def test_configured_nonzero_policy_is_exact_and_hard_failures_still_block() -> None:
    policy = ExposureReconciliationPolicy(
        max_unexpected_mismatch_count=1,
        max_unexpected_mismatch_ratio=1.0,
    )
    tolerated = _reconcile(
        [_row("one", recommendation="Old")],
        [_row("one", recommendation="New")],
        policy=policy,
    )
    hard = _reconcile(
        [_row("one")],
        [],
        new_completeness="healthy-empty",
        policy=policy,
    )

    assert tolerated.unexpected_mismatch_count == 1
    assert tolerated.mismatch_ratio == 1.0
    assert tolerated.passed is True
    assert hard.blocks_cutover is True


def test_query_service_exposes_representative_read_reconciliation_checkpoint() -> None:
    service = ExposureQueryService(reader=None)

    report = service.reconcile_shadow_page(
        old_rows=[_row("one")],
        new_rows=[_row("one", freshness="stale")],
        generation_id=GENERATION,
        old_completeness="complete",
        new_completeness="complete",
        authorized_scope_keys={"scope-sensitive"},
    )

    assert report.checkpoint == "representative_read"
    assert report.mismatch_counts["freshness"] == 1
    assert report.blocks_cutover is True


def _gold_datasets() -> dict[str, list[dict[str, Any]]]:
    return {
        "gold_exposure_current": [
            {
                "tenant_id": "tenant-sensitive",
                "subscription_id": "sub-sensitive",
                "current_key": "current-sensitive",
                "projection_generation_id": "temporal-1",
                "target_id": TARGET,
                "target_kind": "server",
                "weakness_id": "CVE-2026-1234",
                "weakness_kind": "cve",
                "state": "missing",
                "active": True,
                "active_source_families": ["defender_subassessment"],
                "source_states_json": '{"defender_subassessment":"missing"}',
                "first_detected_at": "2026-09-05T00:00:00Z",
                "first_detection_quality": "provider",
            }
        ],
        "silver_exposure_observations": [
            {
                "tenant_id": "tenant-sensitive",
                "subscription_id": "sub-sensitive",
                "observation_id": "observation-sensitive",
                "resource_id": "observation-sensitive",
                "current_key": "current-sensitive",
                "connection_id": "connection-sensitive",
                "source_family": "defender_subassessment",
                "source_generation": "temporal-1",
                "event_time": "2026-09-05T00:00:00Z",
                "payload_json": '{"recommendation":"Upgrade"}',
            }
        ],
        "metadata_source_status": [
            {
                "tenant_id": "tenant-sensitive",
                "subscription_id": "sub-sensitive",
                "connection_id": "connection-sensitive",
                "source_family": "defender_subassessment",
                "state": "complete",
                "completeness": "complete",
                "last_attempt_at": "2026-09-05T00:00:00Z",
            }
        ],
        "gold_container_exposure_current": [],
        "silver_container_vulnerability_observations": [],
        "silver_exposure_enrichment": [],
        "silver_defender_secure_scores": [],
    }


def test_post_publication_shadow_drift_persists_manifest_and_blocks_pointer(
    tmp_path: Path,
) -> None:
    old_row = _row("old")
    publisher = ExposureGoldFabricPublisher(
        table_root=tmp_path / "Tables",
        delta_writer=DeltaWriter(),
        pointer_store=OneLakeDocumentStore(tmp_path / "Files"),
        shadow_reader=lambda arm, _generation: [old_row] if arm == "old" else [],
        shadow_authorized_scope_keys=frozenset({"scope-sensitive"}),
    )

    with pytest.raises(ExposureCutoverBlocked) as caught:
        publisher.publish(
            _gold_datasets(),
            generation_id=GENERATION,
            projected_at="2026-09-06T00:00:00Z",
        )

    assert publisher.readable_generation_id() is None
    assert caught.value.report.blocks_cutover is True
    metadata = DeltaWriter().read(
        tmp_path / "Tables" / EXPOSURE_GOLD_GENERATIONS_TABLE
    )
    assert metadata[0]["reconciliation_status"] == "shadow_blocked"
    manifest = json.loads(metadata[0]["reconciliation_json"])
    assert manifest["shadow"]["checkpoint"] == "post_publication"
    serialized = json.dumps(manifest["shadow"], sort_keys=True)
    assert "exposure-old" not in serialized
    assert "sub-sensitive" not in serialized
    assert "CVE-" not in serialized
