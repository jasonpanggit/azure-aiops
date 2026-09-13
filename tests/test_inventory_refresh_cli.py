from __future__ import annotations

import json
from pathlib import Path

from deltalake import DeltaTable

from onboarding import cli
from onboarding.inventory_refresh import run_inventory_refresh


def test_selected_connection_refresh_uses_registered_connection_orchestrator(
    monkeypatch,
) -> None:
    captured: dict[str, str] = {}

    def run_registered(config_path, *, fabric_config_path="", connection_id=""):
        captured.update(
            config_path=config_path,
            fabric_config_path=fabric_config_path,
            connection_id=connection_id,
        )
        return {"status": "completed"}

    monkeypatch.setattr(
        "onboarding.inventory_refresh.run_inventory_refresh_all_connections",
        run_registered,
    )
    monkeypatch.setattr(
        "azure.identity.DefaultAzureCredential",
        lambda: (_ for _ in ()).throw(
            AssertionError("selected connection refresh must not use managed identity")
        ),
    )

    result = run_inventory_refresh(
        "config.yaml",
        fabric_config_path="fabric.yaml",
        connection_id="conn-selected",
    )

    assert result == {"status": "completed"}
    assert captured == {
        "config_path": "config.yaml",
        "fabric_config_path": "fabric.yaml",
        "connection_id": "conn-selected",
    }


def test_inventory_refresh_cli_publishes_to_configured_local_onelake(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    class AzureClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def list_subscriptions(self):
            return [{"subscriptionId": "sub-a"}, {"subscriptionId": "sub-b"}]

        def fetch(self, specs, _subscriptions):
            fixture = json.loads(
                (Path(__file__).parent / "fixtures" / "mock_inventory_arg.json").read_text()
            )
            fixture.setdefault(
                "inventory_log_analytics_workspaces",
                [{"workspaceId": "workspace-1"}],
            )
            return {spec.name: list(fixture.get(spec.name, [])) for spec in specs}

    class LogsClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def query_configuration_data(self, _workspace_id: str):
            return json.loads(
                (Path(__file__).parent / "fixtures" / "mock_configurationdata.json").read_text()
            )

    class Credential:
        pass

    monkeypatch.setattr("onboarding.discovery_source.AzureResourceGraphSource", AzureClient)
    monkeypatch.setattr("onboarding.monitor_logs.AzureMonitorLogsClient", LogsClient)
    monkeypatch.setattr("azure.identity.DefaultAzureCredential", Credential)

    config = tmp_path / "config.yaml"
    config.write_text(
        "\n".join(
            [
                "storage:",
                f"  output_dir: {tmp_path / 'compat'}",
                "azure:",
                "  subscriptions:",
                "    - sub-a",
                "    - sub-b",
            ]
        )
    )
    fabric_config = tmp_path / "fabric.config.yaml"
    fabric_config.write_text(
        "\n".join(
            [
                "fabric:",
                "  workspace_id: workspace",
                "  lakehouse_id: lakehouse",
                f"  local_onelake_root: {tmp_path / 'lakehouse'}",
            ]
        )
    )

    assert cli.main(
        [
            "inventory-refresh",
            "--config",
            str(config),
            "--fabric-config",
            str(fabric_config),
        ]
    ) == 0

    manifest = json.loads(capsys.readouterr().out)

    assert manifest["fabricTableWrites"]["inventory_os_observations"]["rowsProcessed"] > 0
    assert manifest["fabricTableWrites"]["inventory_software_observations"]["rowsProcessed"] > 0
    assert (
        DeltaTable(str(tmp_path / "lakehouse" / "Tables" / "inventory_os_observations"))
        .to_pyarrow_table()
        .num_rows
        > 0
    )
