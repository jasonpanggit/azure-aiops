"""Release-gate coverage for the staged Exposure production rollout.

The live checks in this module deliberately exercise only redacted control
contracts.  Azure/Fabric payloads and credentials belong to the live validator,
never to test fixtures or assertion output.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from api.runtime import (
    ExposurePromotionEvidence,
    evaluate_exposure_promotion,
    exposure_rollout_from_environment,
)
from fabric.config import (
    ExposureRolloutRuntimeConfig,
    ExposureRolloutStage,
    FabricRuntimeConfig,
)

ROOT = Path(__file__).parents[1]


def _write_fabric_config(path: Path, rollout: str = "") -> FabricRuntimeConfig:
    path.write_text(
        f"""
fabric:
  workspace_name: workspace
  lakehouse_name: lakehouse
  exposure:
    enabled: true
    adapter: fabric_sql
    rollback_mode: false
{rollout}
""",
        encoding="utf-8",
    )
    return FabricRuntimeConfig.load(path)


def _ready_evidence(**overrides: bool) -> ExposurePromotionEvidence:
    values = {
        "adapter_ready": True,
        "cursor_keys_ready": True,
        "source_coverage_ready": True,
        "reconciliation_passed": True,
        "telemetry_ready": True,
        "alerts_ready": True,
        "slo_passed": True,
        "ui_api_contract_passed": True,
        "live_validation_passed": True,
        "ingestion_healthy": True,
        "read_path_healthy": True,
        "key_rotation_healthy": True,
    }
    values.update(overrides)
    return ExposurePromotionEvidence(**values)


def _authorized_rollout(**overrides: object) -> ExposureRolloutRuntimeConfig:
    values: dict[str, object] = {
        "authorized": True,
        "write_stage": ExposureRolloutStage.ON,
        "read_stage": ExposureRolloutStage.CANARY,
        "web_stage": ExposureRolloutStage.CANARY,
        "handoff_stage": ExposureRolloutStage.CANARY,
        "write_generation_id": "generation-v2",
        "read_generation_id": "generation-v2",
        "rollback_generation_id": "generation-v1",
    }
    values.update(overrides)
    return ExposureRolloutRuntimeConfig(**values)


def test_rollout_config_defaults_every_new_surface_off(tmp_path: Path) -> None:
    config = _write_fabric_config(tmp_path / "fabric.yaml")

    assert config.exposure.rollout == ExposureRolloutRuntimeConfig()
    assert {
        config.exposure.rollout.write_stage,
        config.exposure.rollout.read_stage,
        config.exposure.rollout.web_stage,
        config.exposure.rollout.handoff_stage,
    } == {ExposureRolloutStage.OFF}
    assert config.exposure.rollout.authorized is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("authorized", '"true"', "fabric.exposure.rollout.authorized must be boolean"),
        ("write_stage", "enabled", "fabric.exposure.rollout.write_stage"),
        ("read_stage", "true", "fabric.exposure.rollout.read_stage"),
        ("web_stage", "blue", "fabric.exposure.rollout.web_stage"),
        ("handoff_stage", "1", "fabric.exposure.rollout.handoff_stage"),
    ],
)
def test_rollout_config_rejects_ambiguous_or_unknown_values(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        _write_fabric_config(
            tmp_path / f"{field}.yaml",
            f"""
    rollout:
      {field}: {value}
""",
        )


def test_rollout_config_refuses_unauthorized_or_pointerless_promotion(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="authorized"):
        _write_fabric_config(
            tmp_path / "unauthorized.yaml",
            """
    rollout:
      read_stage: canary
      read_generation_id: generation-v2
      rollback_generation_id: generation-v1
""",
        )

    with pytest.raises(ValueError, match="rollback_generation_id"):
        _write_fabric_config(
            tmp_path / "pointerless.yaml",
            """
    rollout:
      authorized: true
      read_stage: canary
      read_generation_id: generation-v2
""",
        )


@pytest.mark.parametrize(
    ("failed_field", "reason_code"),
    [
        ("adapter_ready", "adapter_not_ready"),
        ("cursor_keys_ready", "cursor_keys_not_ready"),
        ("source_coverage_ready", "source_coverage_incomplete"),
        ("reconciliation_passed", "semantic_reconciliation_failed"),
        ("telemetry_ready", "telemetry_missing"),
        ("alerts_ready", "alerts_missing"),
        ("slo_passed", "slo_failed"),
        ("ui_api_contract_passed", "ui_api_contract_failed"),
        ("live_validation_passed", "live_validation_failed"),
    ],
)
def test_every_failed_promotion_prerequisite_blocks_canary(
    failed_field: str,
    reason_code: str,
) -> None:
    decision = evaluate_exposure_promotion(
        _authorized_rollout(),
        replace(_ready_evidence(), **{failed_field: False}),
    )

    assert decision.allowed is False
    assert reason_code in decision.blocked_reasons
    assert decision.active_reader_generation_id == "generation-v1"
    assert decision.rollback_required is True
    assert decision.preserve_evidence is True


@pytest.mark.parametrize(
    ("failed_field", "reason_code"),
    [
        ("ingestion_healthy", "ingestion_unhealthy"),
        ("read_path_healthy", "read_path_unhealthy"),
        ("key_rotation_healthy", "key_rotation_unhealthy"),
    ],
)
def test_runtime_failure_rolls_reader_pointer_back_without_deleting_history(
    failed_field: str,
    reason_code: str,
) -> None:
    decision = evaluate_exposure_promotion(
        _authorized_rollout(read_stage=ExposureRolloutStage.ON),
        replace(_ready_evidence(), **{failed_field: False}),
    )

    assert decision.allowed is False
    assert decision.rollback_required is True
    assert decision.active_reader_generation_id == "generation-v1"
    assert decision.candidate_generation_id == "generation-v2"
    assert reason_code in decision.blocked_reasons
    assert decision.destructive_actions == ()


def test_ready_rollout_keeps_writer_and_reader_pointers_independent() -> None:
    decision = evaluate_exposure_promotion(
        _authorized_rollout(
            write_generation_id="generation-write",
            read_generation_id="generation-read",
        ),
        _ready_evidence(),
    )

    assert decision.allowed is True
    assert decision.active_writer_generation_id == "generation-write"
    assert decision.active_reader_generation_id == "generation-read"
    assert decision.rollback_required is False


def test_environment_rollout_overrides_are_centralized_and_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPS_EXPOSURE_ROLLOUT_AUTHORIZED", "true")
    monkeypatch.setenv("AIOPS_EXPOSURE_WRITE_STAGE", "shadow")
    monkeypatch.setenv("AIOPS_EXPOSURE_READ_STAGE", "canary")
    monkeypatch.setenv("AIOPS_EXPOSURE_WEB_STAGE", "canary")
    monkeypatch.setenv("AIOPS_EXPOSURE_HANDOFF_STAGE", "canary")
    monkeypatch.setenv("AIOPS_EXPOSURE_WRITE_GENERATION_ID", "generation-write")
    monkeypatch.setenv("AIOPS_EXPOSURE_READ_GENERATION_ID", "generation-read")
    monkeypatch.setenv("AIOPS_EXPOSURE_ROLLBACK_GENERATION_ID", "generation-v1")

    rollout = exposure_rollout_from_environment()

    assert rollout.authorized is True
    assert rollout.write_stage is ExposureRolloutStage.SHADOW
    assert rollout.read_stage is ExposureRolloutStage.CANARY
    assert rollout.web_stage is ExposureRolloutStage.CANARY
    assert rollout.handoff_stage is ExposureRolloutStage.CANARY
    assert rollout.write_generation_id == "generation-write"
    assert rollout.read_generation_id == "generation-read"
    assert rollout.rollback_generation_id == "generation-v1"

    monkeypatch.setenv("AIOPS_EXPOSURE_READ_STAGE", "maybe")
    with pytest.raises(ValueError, match="AIOPS_EXPOSURE_READ_STAGE"):
        exposure_rollout_from_environment()


def test_container_apps_wires_only_non_secret_rollout_controls() -> None:
    container_apps = (ROOT / "infra/terraform/container_apps.tf").read_text(
        encoding="utf-8"
    )
    variables = (ROOT / "infra/terraform/variables.tf").read_text(encoding="utf-8")

    for name in (
        "AIOPS_EXPOSURE_ROLLOUT_AUTHORIZED",
        "AIOPS_EXPOSURE_WRITE_STAGE",
        "AIOPS_EXPOSURE_READ_STAGE",
        "AIOPS_EXPOSURE_WEB_STAGE",
        "AIOPS_EXPOSURE_HANDOFF_STAGE",
        "AIOPS_EXPOSURE_WRITE_GENERATION_ID",
        "AIOPS_EXPOSURE_READ_GENERATION_ID",
        "AIOPS_EXPOSURE_ROLLBACK_GENERATION_ID",
    ):
        assert f'name  = "{name}"' in container_apps
    assert 'variable "exposure_rollout_authorized"' in variables
    assert 'default     = false' in variables
    assert "secret_name" not in container_apps.split(
        'name  = "AIOPS_EXPOSURE_ROLLOUT_AUTHORIZED"', 1
    )[1].split("}", 1)[0]


def test_rollout_code_preserves_remediation_lifecycle_guards() -> None:
    runtime = (ROOT / "src/api/runtime.py").read_text(encoding="utf-8")

    assert "_hybrid_remediation_cache" in runtime
    assert "_remediation_decision_store()" in runtime
    assert "_remediation_execution_store()" in runtime
    assert '"target_observed": target_observed' in runtime
    coordinator = runtime.split("def _verification_coordinator()", 1)[1]
    assert "plan_repository=None" in coordinator
    assert "patching_service=None" in coordinator


def _complete_live_evidence() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "binding": {
            "commit": "abcdef12",
            "config_digest": "sha256:" + ("a" * 64),
            "generation_id": "generation-live",
        },
        "sources": {
            "aum": {"status": "pass"},
            "defender_digest": {
                "status": "pass",
                "evidence_kind": "exact_digest",
            },
            "container_insights": {
                "status": "pass",
                "supported": True,
                "deployment_match": "exact",
            },
            "fabric_sql": {
                "status": "pass",
                "adapter": "fabric_sql",
                "driver": "ODBC Driver 18 for SQL Server",
            },
        },
        "persistence": {
            "status": "pass",
            "generation_id": "generation-live",
        },
        "ontology": {
            "status": "pass",
            "generation_id": "generation-live",
        },
        "scope_identity": {
            "status": "pass",
            "api_scope_hash": "sha256:" + ("b" * 64),
            "web_scope_hash": "sha256:" + ("b" * 64),
        },
        "ui_suites": {
            "shared_primitives": "pass",
            "overview": "pass",
            "cve": "pass",
            "kb": "pass",
            "risk_dialog": "pass",
        },
        "cursor": {
            "status": "pass",
            "active_ref": "exposure-cursor-active",
            "previous_ref": "exposure-cursor-previous",
            "active_kid": "cursor-active-20260907",
            "previous_kid": "cursor-previous-20260907",
            "ttl_minutes": 15,
            "overlap_minutes": 30,
            "rotation_verified": True,
            "expiry_verified": True,
            "secret_values_exposed": False,
        },
        "governance": {
            "status": "pass",
            "executable_action_ids": [
                "controlled-patch-recovery",
                "defender-enable-servers-plan-p1",
                "defender-enable-storage-plan-v2",
            ],
            "container_handoff": "review_handoff",
            "container_operation_calls": 0,
        },
        "telemetry": {"status": "pass"},
        "alerts": {
            "status": "pass",
            "enabled": True,
            "one_cycle": True,
        },
        "benchmark": {
            "status": "pass",
            "adapter": {
                "adapter_id": "fabric_sql",
                "production_slo_evidence": True,
                "delta_selected": False,
            },
            "dataset": {
                "row_count": 100_000,
                "generation_id": "generation-live",
                "target_kind_counts": {
                    "server": 80_000,
                    "container_image": 20_000,
                },
            },
            "full_walk": {
                "duplicate_count": 0,
                "omission_count": 0,
            },
            "slo": {
                "target_p95_ms": 2_000,
                "observed_under_target": True,
                "production_certified": True,
            },
        },
        "phase4": {
            "status": "pass",
            "digest_to_workload": {
                "evidence_kind": "exact_digest",
                "source": "container_insights",
                "supported": True,
                "round_trip": True,
                "represented": 1,
                "total": 1,
            },
        },
    }


def test_deploy_config_pins_authoritative_fabric_sql_endpoint() -> None:
    config = yaml.safe_load(
        (ROOT / "fabric.config.deploy.yaml").read_text(encoding="utf-8")
    )

    assert config["fabric"]["sql_endpoint"] == {
        "server": (
            "a4y4r76a7qxe3b4y2wbnunsqly-u6gteheqetoerg5g32gb6mzxky."
            "datawarehouse.fabric.microsoft.com"
        ),
        "database": "b4089445-1001-45a6-a0ea-2b4a0851eace",
        "schema": "dbo",
    }


def test_alerts_can_reuse_existing_action_group_without_email_receivers() -> None:
    alerting = (ROOT / "infra/terraform/alerting.tf").read_text(encoding="utf-8")
    variables = (ROOT / "infra/terraform/variables.tf").read_text(encoding="utf-8")

    assert 'variable "existing_alert_action_group_id"' in variables
    assert "local.alerting_enabled" in alerting
    assert "local.alert_action_group_id" in alerting
    assert (
        'count               = local.create_alert_action_group ? 1 : 0'
        in alerting
    )
    assert alerting.count("local.alerting_enabled ? 1 : 0") == 11
    assert alerting.count("skip_query_validation = true") == 8
    assert "[local.alert_action_group_id]" in alerting
    assert "action_group_id = local.alert_action_group_id" in alerting


def test_cursor_kids_are_validated_non_secret_variables_not_placeholders() -> None:
    container_apps = (ROOT / "infra/terraform/container_apps.tf").read_text(
        encoding="utf-8"
    )
    variables = (ROOT / "infra/terraform/variables.tf").read_text(encoding="utf-8")

    assert 'variable "exposure_cursor_active_kid"' in variables
    assert 'variable "exposure_cursor_previous_kid"' in variables
    assert "var.exposure_cursor_active_kid" in container_apps
    assert "var.exposure_cursor_previous_kid" in container_apps
    assert "unprovisioned" not in container_apps
    assert "exposure_cursor_active_kid != var.exposure_cursor_previous_kid" in variables


def test_api_image_contains_live_validator_and_benchmark() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert (
        "COPY scripts/benchmark_exposure_read_model.py "
        "/app/scripts/benchmark_exposure_read_model.py"
    ) in dockerfile
    assert (
        "COPY scripts/validate_exposure_live.py "
        "/app/scripts/validate_exposure_live.py"
    ) in dockerfile
    assert "msodbcsql18 libgssapi-krb5-2" in dockerfile


def test_complete_live_evidence_passes_without_leaking_scoped_values() -> None:
    from scripts.validate_exposure_live import evaluate_live_evidence

    report = evaluate_live_evidence(_complete_live_evidence())

    assert report["status"] == "pass"
    assert report["phase4_ready"] is True
    assert report["missing_evidence"] == []
    assert report["sanitized"] is True
    serialized = str(report).casefold()
    for forbidden in ("access_token", "client_secret", "cursor_key", "raw_payload"):
        assert forbidden not in serialized


def test_typed_unknown_digest_to_workload_evidence_blocks_phase4() -> None:
    from scripts.validate_exposure_live import evaluate_live_evidence

    evidence = _complete_live_evidence()
    phase4 = dict(evidence["phase4"])
    phase4["status"] = "blocked"
    phase4["digest_to_workload"] = {
        "evidence_kind": "typed_unknown",
        "source": "container_insights",
        "supported": True,
        "round_trip": False,
        "represented": 0,
        "total": 1,
    }
    evidence["phase4"] = phase4

    report = evaluate_live_evidence(evidence)

    assert report["status"] == "blocked"
    assert report["phase4_ready"] is False
    assert report["missing_evidence"] == [
        "exact_supported_defender_digest_to_container_insights_workload_round_trip"
    ]


@pytest.mark.parametrize(
    "unsafe_key",
    ["access_token", "client_secret", "cursor_key", "raw_payload"],
)
def test_live_validator_rejects_secret_or_raw_payload_fields(
    unsafe_key: str,
) -> None:
    from scripts.validate_exposure_live import evaluate_live_evidence

    evidence = _complete_live_evidence()
    evidence["unsafe"] = {unsafe_key: "must-never-be-emitted"}

    with pytest.raises(ValueError, match="unsafe evidence field"):
        evaluate_live_evidence(evidence)
