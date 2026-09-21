"""Regression tests for the retired Operations Copilot authorization gate."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from operations import copilot_canary_authorization as authorization
from operations.copilot_canary_authorization import CanaryAuthorizationError
from operations.maf_orchestrator import (
    authorize_canonical_execution,
    canonical_orchestration_enabled,
    copilot_rollout_decision,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_rollout_authorization_gate_is_retired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", "100")
    monkeypatch.setenv("AIOPS_SOURCE_REVISION", "a" * 40)

    assert authorization.canary_authorization_required() is False
    assert authorization.require_canary_authorization_if_requested() is None
    assert authorization.canary_authorization_health() == {
        "required": False,
        "status": "retired",
        "reason": "",
    }

    metadata = authorization.validate_canary_authorization(
        environment={
            "AIOPS_COPILOT_ROLLOUT_MODE": "default",
            "AIOPS_COPILOT_CANARY_PERCENTAGE": "100",
            "AIOPS_SOURCE_REVISION": "a" * 40,
        },
        manifest_path=REPO_ROOT / "does-not-exist.json",
        default_manifest_path=REPO_ROOT / "does-not-exist-default.json",
        build_metadata_path=REPO_ROOT / "does-not-exist-metadata.json",
        reviewed_tree_root=REPO_ROOT / "does-not-exist-root",
        now=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert metadata.authorization_id == "unified-deployment"
    assert metadata.mode == "default"
    assert metadata.manifest_sha256 == ""
    assert metadata.reviewed_tree_sha256 == ""
    assert metadata.percentage == 100


def test_rollout_modes_no_longer_require_manifest_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPS_COPILOT_ROLLBACK_MODE", "compatibility")
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "canary")
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", "10")

    canary = copilot_rollout_decision(stable_key="operator-a")
    assert canary.mode == "canary"
    assert canary.authorization_id == ""
    assert 0 <= canary.canary_bucket < 100

    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", "100")
    default = copilot_rollout_decision(stable_key="operator-a")
    assert default.mode == "default"
    assert default.canonical_enabled is True
    assert default.authorization_id == ""
    assert canonical_orchestration_enabled(stable_key="operator-a") is True


def test_canonical_execution_authorizer_checks_route_not_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "default")
    monkeypatch.setenv("AIOPS_COPILOT_CANARY_PERCENTAGE", "100")

    authorize_canonical_execution(
        request={"question": "network status"},
        principal_subject="operator-a",
        stable_key="operator-a",
    )

    with pytest.raises(CanaryAuthorizationError, match="validated rollout authority"):
        authorize_canonical_execution(
            request={"question": "network status"},
            principal_subject="operator-a",
            stable_key="operator-b",
        )


def test_retired_gate_still_rejects_malformed_rollout_metadata() -> None:
    with pytest.raises(CanaryAuthorizationError, match="rollout percentage"):
        authorization.validate_canary_authorization(
            environment={
                "AIOPS_COPILOT_ROLLOUT_MODE": "canary",
                "AIOPS_COPILOT_CANARY_PERCENTAGE": "not-a-number",
            }
        )

    with pytest.raises(CanaryAuthorizationError, match="source revision"):
        authorization.validate_canary_authorization(
            environment={
                "AIOPS_COPILOT_ROLLOUT_MODE": "canary",
                "AIOPS_COPILOT_CANARY_PERCENTAGE": "10",
                "AIOPS_SOURCE_REVISION": "main",
            }
        )
