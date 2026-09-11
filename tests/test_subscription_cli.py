from __future__ import annotations

import json
from pathlib import Path

from test_subscription_onboarding import (
    CLIENT,
    SUBSCRIPTION,
    TENANT,
    FakeIngestion,
    FakeProbe,
    build_service,
)

from onboarding import cli
from onboarding.local_seed import DEFAULT_LOCAL_CONNECTION_ID


def _config(tmp_path: Path) -> str:
    config = tmp_path / "config.yaml"
    config.write_text(f"storage:\n  output_dir: {tmp_path / 'data'}\n")
    return str(config)


def _patch_service(monkeypatch, service) -> None:
    monkeypatch.setattr(
        "onboarding.runtime.build_onboarding_service", lambda config, **kwargs: service
    )


def _run(argv: list[str]) -> int:
    return cli.main(argv)


def test_cli_add_list_map_validate_sync_health_disable(tmp_path, monkeypatch, capsys) -> None:
    data_dir = tmp_path / "data"
    service = build_service(data_dir, ingestion=FakeIngestion())
    _patch_service(monkeypatch, service)
    config = _config(tmp_path)

    assert _run(
        [
            "subscriptions", "add", "prod-core",
            "--tenant-id", TENANT,
            "--subscription-id", SUBSCRIPTION,
            "--client-id", CLIENT,
            "--secret-ref", "env://SPN_SECRET",
            "--config", config,
        ]
    ) == 0
    added = json.loads(capsys.readouterr().out)
    assert added["connection_id"] == "prod-core"

    assert _run(["subscriptions", "list", "--config", config]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1

    assert _run(
        [
            "subscriptions", "map", "prod-core",
            "--business-service", "Payments",
            "--environment", "production",
            "--criticality", "critical",
            "--config", config,
        ]
    ) == 0
    mapped = json.loads(capsys.readouterr().out)
    assert mapped["business_metadata"]["business_service"] == "Payments"

    assert _run(["subscriptions", "validate", "prod-core", "--config", config]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True

    assert _run(["subscriptions", "sync", "prod-core", "--config", config]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "succeeded"

    assert _run(["subscriptions", "health", "--config", config]) == 0
    assert json.loads(capsys.readouterr().out)["connections"][0]["overall"] == "healthy"

    assert _run(["subscriptions", "disable", "prod-core", "--config", config]) == 0
    assert json.loads(capsys.readouterr().out)["is_active"] is False


def test_cli_validate_failure_exits_nonzero(tmp_path, monkeypatch, capsys) -> None:
    data_dir = tmp_path / "data"
    service = build_service(data_dir, probe=FakeProbe(auth_error="bad secret"))
    _patch_service(monkeypatch, service)
    config = _config(tmp_path)

    _run(
        [
            "subscriptions", "add", "prod-core",
            "--tenant-id", TENANT,
            "--subscription-id", SUBSCRIPTION,
            "--client-id", CLIENT,
            "--secret-ref", "env://SPN_SECRET",
            "--config", config,
        ]
    )
    capsys.readouterr()

    assert _run(["subscriptions", "validate", "prod-core", "--config", config]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_cli_unknown_connection_reports_error(tmp_path, monkeypatch, capsys) -> None:
    service = build_service(tmp_path / "data")
    _patch_service(monkeypatch, service)

    assert _run(["subscriptions", "detail", "missing", "--config", _config(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_cli_secret_never_appears_in_output(tmp_path, monkeypatch, capsys) -> None:
    service = build_service(tmp_path / "data", env={"SPN_SECRET": "s3cret"})
    _patch_service(monkeypatch, service)
    config = _config(tmp_path)

    _run(
        [
            "subscriptions", "add", "prod-core",
            "--tenant-id", TENANT,
            "--subscription-id", SUBSCRIPTION,
            "--client-id", CLIENT,
            "--secret-ref", "env://SPN_SECRET",
            "--config", config,
        ]
    )

    assert "s3cret" not in capsys.readouterr().out


def test_cli_subscriptions_without_command_shows_usage(capsys) -> None:
    assert _run(["subscriptions"]) == 2
    assert "subscriptions" in capsys.readouterr().out


def test_cli_local_seeds_file_backed_api_snapshot(tmp_path, monkeypatch, capsys) -> None:
    home = tmp_path / "aiops-local"
    fixture = Path("tests/fixtures/mock_arg_responses.json")

    assert _run(["local", "--home", str(home), "--fixture", str(fixture)]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "seeded"
    assert result["connection"]["connection_id"] == DEFAULT_LOCAL_CONNECTION_ID
    assert result["connection"]["sync_state"]["status"] == "succeeded"
    assert result["connection"]["health"]["healthy"] is True
    assert (home / "state" / "subscription_connections.json").exists()
    assert (home / "connections" / DEFAULT_LOCAL_CONNECTION_ID / "current" / "manifest.json").exists()


def test_cli_local_spn_injects_env_backed_connection(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "super-secret-value")
    home = tmp_path / "aiops-local"

    assert _run(["local-spn", "--home", str(home), "--connection-id", "local-spn"]) == 0

    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["status"] == "created"
    assert result["connection"]["connection_id"] == "local-spn"
    assert result["connection"]["subscription_id"] == SUBSCRIPTION
    assert result["connection"]["credential"]["secret_ref"] == "env://AZURE_CLIENT_SECRET"
    assert "super-secret-value" not in output

    assert _run(["local-spn", "--home", str(home), "--connection-id", "local-spn"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "updated"


def test_cli_local_spn_removes_fixture_connection(tmp_path, monkeypatch, capsys) -> None:
    home = tmp_path / "aiops-local"
    fixture = Path("tests/fixtures/mock_arg_responses.json")
    assert _run(["local", "--home", str(home), "--fixture", str(fixture)]) == 0
    capsys.readouterr()

    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "super-secret-value")

    assert _run(["local-spn", "--home", str(home), "--connection-id", "local-spn"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["connection"]["connection_id"] == "local-spn"
    registry = json.loads((home / "state" / "subscription_connections.json").read_text())
    assert [row["connection_id"] for row in registry["connections"]] == ["local-spn"]


def test_cli_local_spn_can_sync_after_injection(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "super-secret-value")

    class FakeService:
        def sync(self, connection_id: str, *, mode: str = "initial"):
            return {"connection_id": connection_id, "status": "succeeded", "mode": mode}

    monkeypatch.setattr(
        "onboarding.runtime.build_onboarding_service",
        lambda config: FakeService(),
    )

    assert _run(["local-spn", "--home", str(tmp_path / "aiops-local"), "--sync"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["sync"] == {
        "connection_id": "local-spn",
        "status": "succeeded",
        "mode": "initial",
    }


def test_cli_activate_streams_progress_to_stderr_and_terminal_json_to_stdout(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _patch_service(monkeypatch, object())

    def fake_activate_runtime(service, **kwargs):
        kwargs["progress_callback"](
            {
                "event": "activation_progress",
                "stage": "activation",
                "status": "started",
                "elapsed_seconds": 0.0,
            }
        )
        return {"status": "activated", "connections": ["hub"]}

    monkeypatch.setattr(
        "onboarding.activation.activate_runtime",
        fake_activate_runtime,
    )

    assert _run(["activate", "--config", _config(tmp_path)]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "status": "activated",
        "connections": ["hub"],
    }
    assert json.loads(captured.err) == {
        "event": "activation_progress",
        "stage": "activation",
        "status": "started",
        "elapsed_seconds": 0.0,
    }


def test_cli_activate_forwards_exact_replay_source_run_id(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _patch_service(monkeypatch, object())
    captured_kwargs: dict[str, object] = {}

    def fake_activate_runtime(service, **kwargs):
        captured_kwargs.update(kwargs)
        return {"status": "activated", "connections": ["hub"]}

    monkeypatch.setattr(
        "onboarding.activation.activate_runtime",
        fake_activate_runtime,
    )

    assert (
        _run(
            [
                "activate",
                "--config",
                _config(tmp_path),
                "--replay-source-run-id",
                "exact-generation",
            ]
        )
        == 0
    )

    assert captured_kwargs["replay_source_run_id"] == "exact-generation"
    assert json.loads(capsys.readouterr().out)["status"] == "activated"


def test_cli_activate_renders_only_sanitized_failure_fields(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    from onboarding.activation import ActivationFailure

    _patch_service(monkeypatch, object())
    secret = "credential=planted-secret"
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/x/y"

    def fail_activation(*args, **kwargs):
        raise ActivationFailure(
            stage="connection_discovery",
            error_code="ACTIVATION_FAILED",
            elapsed_seconds=7.5,
        ) from RuntimeError(f"{secret} {resource_id}")

    monkeypatch.setattr(
        "onboarding.activation.activate_runtime",
        fail_activation,
    )

    assert _run(["activate", "--config", _config(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "status": "error",
        "stage": "connection_discovery",
        "error_code": "ACTIVATION_FAILED",
        "elapsed_seconds": 7.5,
    }
    assert captured.err == ""
    assert secret not in captured.out
    assert resource_id not in captured.out
