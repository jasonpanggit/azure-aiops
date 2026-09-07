from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ontology_discovery.drill_control import (
    DrillControlConfig,
    DrillPaused,
    PublisherDrillControl,
)

NOW = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)


def _config(tmp_path, **overrides):
    values = {
        "enabled": True,
        "environment": "validation",
        "connection_environment": "validation",
        "workspace_environment": "validation",
        "publisher_client_id": "publisher-client-id",
        "azure_client_id": "publisher-client-id",
        "drill_root": str(tmp_path / "drill"),
        "protected_roots": (
            str(tmp_path / "connections"),
            str(tmp_path / "commands"),
            str(tmp_path / "dispatch"),
            str(tmp_path / "publication"),
        ),
    }
    values.update(overrides)
    return DrillControlConfig(**values)


def test_drill_control_is_disabled_by_default_and_validation_only(tmp_path):
    disabled = DrillControlConfig.disabled()
    assert disabled.enabled is False
    with pytest.raises(PermissionError, match="disabled"):
        PublisherDrillControl(disabled).arm(
            drill_id="drill-" + "a" * 32,
            target_command_hash="b" * 64,
            fault="pre_cas_pause",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
    with pytest.raises(ValueError, match="validation"):
        PublisherDrillControl(_config(tmp_path, environment="production"))
    with pytest.raises(ValueError, match="isolated"):
        PublisherDrillControl(
            _config(
                tmp_path,
                drill_root=str(tmp_path / "dispatch"),
            )
        )


def test_pre_cas_drill_pauses_once_then_requires_publisher_resume(tmp_path):
    control = PublisherDrillControl(_config(tmp_path))
    command_hash = "c" * 64
    control.arm(
        drill_id="drill-" + "d" * 32,
        target_command_hash=command_hash,
        fault="pre_cas_pause",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )

    with pytest.raises(DrillPaused):
        control.before_cas(command_hash=command_hash, now=NOW)
    assert control.inspect(now=NOW)["status"] == "ready"

    control.resume(
        drill_id="drill-" + "d" * 32,
        actor_client_id="publisher-client-id",
        now=NOW + timedelta(seconds=1),
    )
    control.before_cas(command_hash=command_hash, now=NOW + timedelta(seconds=2))
    assert control.inspect(now=NOW + timedelta(seconds=2))["status"] == "cleaned"
    assert control.audit()[-2:][0]["status"] == "consumed"
    assert control.audit()[-1]["status"] == "cleaned"


def test_post_check_drill_is_allowlisted_single_use_and_expiry_cleans(tmp_path):
    control = PublisherDrillControl(_config(tmp_path))
    command_hash = "e" * 64
    control.arm(
        drill_id="drill-" + "f" * 32,
        target_command_hash=command_hash,
        fault="post_check:semantic",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )

    assert control.fail_post_check(
        command_hash=command_hash, family="semantic", now=NOW
    )
    assert not control.fail_post_check(
        command_hash=command_hash, family="semantic", now=NOW
    )
    assert control.inspect(now=NOW)["status"] == "cleaned"

    control.arm(
        drill_id="drill-" + "1" * 32,
        target_command_hash="2" * 64,
        fault="post_check:api",
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=1),
    )
    assert control.sweep(now=NOW + timedelta(seconds=2)) == 1
    assert control.inspect(now=NOW + timedelta(seconds=2))["status"] == "cleaned"
    assert any(row["status"] == "expired" for row in control.audit())


@pytest.mark.parametrize("fault", ["post_check:unknown", "post_check:", "cas"])
def test_drill_rejects_non_allowlisted_faults(tmp_path, fault):
    control = PublisherDrillControl(_config(tmp_path))
    with pytest.raises(ValueError, match="fault"):
        control.arm(
            drill_id="drill-" + "3" * 32,
            target_command_hash="4" * 64,
            fault=fault,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=1),
        )
