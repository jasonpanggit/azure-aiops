from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from fabric import patch_publication
from fabric.runtime import FabricRuntimeMode
from fabric.sync_service import FabricSyncResult
from onboarding import cli


@dataclass(frozen=True)
class _FabricConfig:
    source_data_root: str


def _result(*, status: str = "completed") -> FabricSyncResult:
    return FabricSyncResult(
        run_id="publication-secret",
        source_run_id="source-generation-secret",
        status=status,
        replay=False,
        rows_processed=12,
        rows_added=10,
        rows_changed=2,
        rows_removed=0,
        failed_records=0,
        tables=("metadata_patch_snapshot", "silver_patch_snapshot_findings"),
        duration_seconds=1.25,
    )


def test_patch_publication_uses_writer_runtime_and_sanitizes_result(
    monkeypatch,
) -> None:
    loaded_connector: list[str] = []
    loaded_fabric: list[str] = []
    modes: list[FabricRuntimeMode] = []
    replayed: list[str] = []
    combined: list[tuple[list[str], str]] = []
    connector_config = SimpleNamespace(output_dir="/data")
    connection = SimpleNamespace(connection_id="connection-a")
    monkeypatch.setattr(
        patch_publication.ConnectorConfig,
        "load",
        lambda path: loaded_connector.append(str(path)) or connector_config,
    )
    monkeypatch.setattr(
        patch_publication,
        "ConnectionRegistry",
        lambda _root: SimpleNamespace(list=lambda **_kwargs: [connection]),
    )
    monkeypatch.setattr(
        patch_publication,
        "ConnectionSyncCoordinator",
        lambda _root: SimpleNamespace(
            connection_output_dir=lambda _connection: (
                "/data/connections/connection-a"
            )
        ),
    )
    monkeypatch.setattr(
        patch_publication,
        "publish_combined_snapshot",
        lambda service, connection_ids, target: (
            combined.append((connection_ids, str(target)))
            or {"runId": "source-generation-secret"}
        ),
    )
    monkeypatch.setattr(
        patch_publication.FabricRuntimeConfig,
        "load",
        lambda path: loaded_fabric.append(str(path))
        or _FabricConfig(source_data_root="/old"),
    )
    monkeypatch.setattr(
        patch_publication,
        "build_runtime",
        lambda config, *, mode: (
            modes.append(mode)
            or SimpleNamespace(
                service=SimpleNamespace(
                    sync_patch_tables=lambda **kwargs: (
                        replayed.append(kwargs["replay_source_run_id"])
                        or _result()
                    ),
                )
            )
        ),
    )

    result = patch_publication.run_patch_publication(
    "/app/config.yaml",
    "/app/fabric.config.yaml",
    )

    assert loaded_connector == ["/app/config.yaml"]
    assert loaded_fabric == ["/app/fabric.config.yaml"]
    assert modes == [FabricRuntimeMode.PUBLISH]
    assert replayed == ["source-generation-secret"]
    assert combined == [
        (
            ["connection-a"],
            "/data",
        )
    ]
    assert result == {
        "status": "completed",
        "source_generation_hash": (
            "b10200d40358ca9acf9479db"
        ),
        "tables_published": 2,
        "rows_processed": 12,
        "failed_records": 0,
        "duration_seconds": 1.25,
    }
    assert "publication-secret" not in str(result)
    assert "source-generation-secret" not in str(result)


def test_patch_publish_cli_emits_sanitized_result(monkeypatch, capsys) -> None:
    captured: list[str] = []
    monkeypatch.setattr(
        patch_publication,
        "run_patch_publication",
        lambda config, fabric_config: captured.extend(
            [str(config), str(fabric_config)]
        )
        or {
            "status": "skipped",
            "source_generation_hash": "a" * 24,
            "tables_published": 0,
            "rows_processed": 0,
            "failed_records": 0,
            "duration_seconds": 0.01,
        },
    )

    assert cli.main(
        ["patch-publish", "--fabric-config", "/app/fabric.config.yaml"]
    ) == 0

    assert captured == ["config.yaml", "/app/fabric.config.yaml"]
    assert json.loads(capsys.readouterr().out)["status"] == "skipped"


def test_patch_publication_fails_closed_without_active_connections(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        patch_publication.ConnectorConfig,
        "load",
        lambda _path: SimpleNamespace(output_dir="/data"),
    )
    monkeypatch.setattr(
        patch_publication,
        "ConnectionRegistry",
        lambda _root: SimpleNamespace(list=lambda **_kwargs: []),
    )
    monkeypatch.setattr(
        patch_publication,
        "ConnectionSyncCoordinator",
        lambda _root: SimpleNamespace(),
    )

    with pytest.raises(
        RuntimeError,
        match="No active subscription connections are registered",
    ):
        patch_publication.run_patch_publication(
            "/app/config.yaml",
            "/app/fabric.config.yaml",
        )


def test_patch_publish_cli_sanitizes_lock_conflict(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        patch_publication,
        "run_patch_publication",
        lambda *_paths: (_ for _ in ()).throw(
            RuntimeError("Fabric synchronization is already running")
        ),
    )

    assert cli.main(["patch-publish"]) == 1

    assert json.loads(capsys.readouterr().err) == {
        "reason_code": "writer_lock_unavailable",
        "status": "failed",
    }
