from types import SimpleNamespace

import pytest

from fabric.graph_refresh import GraphRefreshAmbiguousError, GraphRefreshError
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


def _chain_setup(monkeypatch, tmp_path, status, publication_status, source="activation-1"):
    monkeypatch.setenv("AIOPS_CONFIG_PATH", "/app/config.yaml")
    monkeypatch.setenv("AIOPS_FABRIC_CONFIG", "/app/fabric.yaml")
    monkeypatch.setenv("AIOPS_CONNECTION_HOME", "abfss://workspace/root")
    monkeypatch.setattr(
        publication_cli.ConnectorConfig, "load",
        lambda _path: publication_cli.ConnectorConfig(output_dir=tmp_path),
    )
    monkeypatch.setattr(
        publication_cli,
        "build_onboarding_service",
        lambda _config: SimpleNamespace(
            registry=SimpleNamespace(list=lambda **_k: [SimpleNamespace(connection_id="test")]),
            sync=lambda *a, **k: {"status": "succeeded"},
            sync_coordinator=SimpleNamespace(connection_output_dir=lambda _c: "x"),
        ),
    )
    monkeypatch.setattr(
        publication_cli,
        "run_inventory_refresh_all_connections",
        lambda *a, **k: {
            "status": status,
            "connections": {"test": {"status": status}},
            "fabric_publication": {
                "status": publication_status, "sourceRunId": source, "fabricTables": [],
            },
        },
    )


class _Refresher:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    def refresh(self, *, source_run_id):
        self.calls.append(source_run_id)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.mark.parametrize(
    ("status", "publication_status", "outcome", "code", "calls"),
    [
        ("completed", "completed", {"status": "Completed"}, 0, ["activation-1"]),
        ("completed", "completed", GraphRefreshError("graph_refresh_failed"), 1, ["activation-1"]),
        ("completed", "partial", {"status": "Completed"}, 1, []),
        ("failed", "completed", {"status": "Completed"}, 1, []),
    ],
)
def test_refresh_chained_only_after_verified_publication(
    monkeypatch, capsys, tmp_path, status, publication_status, outcome, code, calls
):
    _chain_setup(monkeypatch, tmp_path, status, publication_status)
    refresher = _Refresher(outcome)
    monkeypatch.setattr(publication_cli, "_graph_refresher", lambda _root, _guard=None: refresher)
    assert publication_cli.main() == code
    assert refresher.calls == calls


def test_refresh_requires_source_run_id(monkeypatch, tmp_path):
    _chain_setup(monkeypatch, tmp_path, "completed", "completed", source=None)
    refresher = _Refresher({"status": "Completed"})
    monkeypatch.setattr(publication_cli, "_graph_refresher", lambda _root, _guard=None: refresher)
    assert publication_cli.main() == 1
    assert refresher.calls == []

@pytest.mark.parametrize(
    ("error", "status", "review"),
    [
        (GraphRefreshAmbiguousError("graph_refresh_poll_failure"), "ambiguous", True),
        (GraphRefreshError("graph_refresh_failed"), "failed", False),
    ],
)
def test_refresh_summary_distinguishes_ambiguous_outcome(
    monkeypatch, capsys, tmp_path, error, status, review,
):
    import json

    _chain_setup(monkeypatch, tmp_path, "completed", "completed")
    refresher = _Refresher(error)
    monkeypatch.setattr(publication_cli, "_graph_refresher", lambda _root, _guard=None: refresher)
    assert publication_cli.main() == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["publication_status"] == "completed"
    assert summary["graph_refresh"]["status"] == status
    assert summary["graph_refresh"]["operator_review_required"] is review
    assert summary["graph_refresh"]["reason"] == str(error)


def test_graph_refresher_env_is_all_or_nothing(monkeypatch):
    monkeypatch.delenv("AIOPS_GRAPH_REFRESH_WORKSPACE_ID", raising=False)
    monkeypatch.delenv("AIOPS_GRAPH_REFRESH_GRAPH_MODEL_ID", raising=False)
    assert publication_cli._graph_refresher("abfss://w/r") is None
    monkeypatch.setenv("AIOPS_GRAPH_REFRESH_WORKSPACE_ID", "2c1fea36-104d-4c26-86db-12e09e432b41")
    with pytest.raises(ValueError):
        publication_cli._graph_refresher("abfss://w/r")


def test_lease_loss_after_refresh_is_not_success(monkeypatch, tmp_path):
    _chain_setup(monkeypatch, tmp_path, "completed", "completed")
    refresher = _Refresher({"status": "Completed"})
    monkeypatch.setattr(publication_cli, "_graph_refresher", lambda _root, _guard=None: refresher)

    class Lost(RuntimeError):
        pass

    real = publication_cli.RunLock.assert_held
    calls = {"n": 0}

    def held(self):
        calls["n"] += 1
        if refresher.calls:
            raise Lost("lease lost")
        return real(self)

    monkeypatch.setattr(publication_cli.RunLock, "assert_held", held)
    with pytest.raises(Lost):
        publication_cli.main()


def test_non_refresh_runtime_error_is_not_swallowed(monkeypatch, tmp_path):
    _chain_setup(monkeypatch, tmp_path, "completed", "completed")
    refresher = _Refresher(RuntimeError("private-storage-detail"))
    monkeypatch.setattr(publication_cli, "_graph_refresher", lambda _root, _guard=None: refresher)
    with pytest.raises(RuntimeError, match="private-storage-detail"):
        publication_cli.main()
