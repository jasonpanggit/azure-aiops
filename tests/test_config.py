from __future__ import annotations

from pathlib import Path

from hermes_arg_connector.config import ConnectorConfig


def test_relative_output_dir_resolves_from_config_directory(tmp_path: Path) -> None:
    config_dir = tmp_path / "deployment"
    config_dir.mkdir()
    config = config_dir / "config.yaml"
    config.write_text("storage:\n  output_dir: ./datasets\n")

    loaded = ConnectorConfig.load(config)

    assert loaded.output_dir == (config_dir / "datasets").resolve()


def test_remote_output_dir_is_preserved_as_uri(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    root = "abfss://hermes@account.dfs.core.windows.net/discovery"
    config.write_text(f"storage:\n  output_dir: {root}\n")

    loaded = ConnectorConfig.load(config)

    assert loaded.output_dir == root


def test_production_defaults_use_preinstalled_mcp_and_bounded_runtime(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("storage:\n  output_dir: ./data\n")

    loaded = ConnectorConfig.load(config)

    assert loaded.azure_mcp_command == ("azmcp",)
    assert loaded.command_timeout_seconds == 60
    assert loaded.max_query_workers == 5
    assert loaded.retain_raw_queries is False
