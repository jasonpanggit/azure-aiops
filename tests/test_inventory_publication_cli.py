from types import SimpleNamespace

import pytest

from intelligence.inventory import publication_cli


def test_inventory_job_requires_explicit_roots(monkeypatch):
    for name in ("AIOPS_CONFIG_PATH", "AIOPS_FABRIC_CONFIG", "AIOPS_CONNECTION_HOME"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="Missing inventory publication configuration"):
        publication_cli.main()


@pytest.mark.parametrize(
    ("status", "publication_status", "exit_code"),
    [("completed", "completed", 0), ("partial", "completed", 1), ("failed", None, 1)],
)
def test_inventory_job_reports_publication_result(
    monkeypatch, capsys, tmp_path, status, publication_status, exit_code
):
    monkeypatch.setenv("AIOPS_CONFIG_PATH", "/app/config.yaml")
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG", "/app/fabric.yaml")
    monkeypatch.setenv("AIOPS_CONNECTION_HOME", "abfss://workspace/root")
    monkeypatch.setattr(
        publication_cli.ConnectorConfig,
        "load",
        lambda _path: publication_cli.ConnectorConfig(output_dir=tmp_path),
    )
    monkeypatch.setattr(
        publication_cli,
        "build_onboarding_service",
        lambda _config: SimpleNamespace(
            registry=SimpleNamespace(
                list=lambda **_kwargs: [SimpleNamespace(connection_id="test")]
            ),
            sync=lambda *args, **kwargs: {"status": "succeeded"},
            sync_coordinator=SimpleNamespace(
                connection_output_dir=lambda _connection: "abfss://workspace/root/connections/test"
            ),
        ),
    )

    def refresh(path, **kwargs):
        from api.inventory_orchestration import run_inventory_refresh_all_connections

        assert path == "/app/config.yaml"
        assert kwargs["registry_root"] == "abfss://workspace/root"
        assert kwargs["fabric_config_path"] == "/app/fabric.yaml"
        assert kwargs["require_all_connections"] is True
        assert kwargs["discovery_output_dirs"] == {
            "test": "abfss://workspace/root/connections/test"
        }
        kwargs["assert_lock_held"]()
        with pytest.raises(RuntimeError, match="already running"):
            run_inventory_refresh_all_connections(path)
        return {
            "status": status,
            "connections": {"test": {"status": status, "error": "private-provider-detail"}},
            "fabric_publication": {"status": publication_status, "fabricTables": ["inventory"]},
        }

    monkeypatch.setattr(publication_cli, "run_inventory_refresh_all_connections", refresh)
    assert publication_cli.main() == exit_code
    assert "private-provider-detail" not in capsys.readouterr().out
    with publication_cli.RunLock(tmp_path):
        pass


@pytest.mark.parametrize("has_connections", [False, True])
def test_inventory_job_never_publishes_missing_or_failed_discovery(monkeypatch, tmp_path, has_connections):
    monkeypatch.setenv("AIOPS_CONFIG_PATH", "/app/config.yaml")
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG", "/app/fabric.yaml")
    monkeypatch.setenv("AIOPS_CONNECTION_HOME", "abfss://workspace/root")
    monkeypatch.setattr(
        publication_cli.ConnectorConfig, "load",
        lambda _path: publication_cli.ConnectorConfig(output_dir=tmp_path),
    )
    monkeypatch.setattr(
        publication_cli, "build_onboarding_service",
        lambda _config: SimpleNamespace(
            registry=SimpleNamespace(
                list=lambda **_kwargs: [SimpleNamespace(connection_id="test")] if has_connections else [],
            ),
            sync=lambda *_args, **_kwargs: {"status": "failed", "error": "private"},
        ),
    )

    def unexpected_publication(*_args, **_kwargs):
        pytest.fail("Publication must not run without successful discovery")

    monkeypatch.setattr(publication_cli, "run_inventory_refresh_all_connections", unexpected_publication)
    with pytest.raises(RuntimeError, match="discovery failed|No active subscription"):
        publication_cli.main()
    with publication_cli.RunLock(tmp_path):
        pass
