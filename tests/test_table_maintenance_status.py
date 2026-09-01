from __future__ import annotations

from fabric import table_maintenance


class _FakeClient:
    def __init__(self, runs: list[dict] | None = None) -> None:
        self.runs = runs or []

    def iter_items(self, path: str, **kwargs):
        for run in self.runs:
            yield run


def test_last_maintenance_status_returns_latest_run_without_triggering(monkeypatch) -> None:
    fake = _FakeClient(
        runs=[
            {
                "id": "old",
                "status": "Succeeded",
                "startTimeUtc": "2026-09-01T07:00:00Z",
                "jobType": "LakehouseMaintenance",
            },
            {
                "id": "new",
                "status": "Failed",
                "startTimeUtc": "2026-09-01T08:00:00Z",
                "jobType": "LakehouseMaintenance",
            },
        ]
    )
    monkeypatch.setattr(table_maintenance, "_default_fabric_client", lambda: fake)

    status = table_maintenance.last_maintenance_status("ws-1", "lakehouse-1")

    assert status == {
        "status": "failed",
        "last_run_at": "2026-09-01T08:00:00Z",
        "activity_name": "LakehouseMaintenance",
    }


def test_module_exposes_no_trigger_function() -> None:
    assert hasattr(table_maintenance, "last_maintenance_status")
    assert not hasattr(table_maintenance, "run_maintenance")
    assert not hasattr(table_maintenance, "trigger_maintenance")


def test_no_runs_returns_no_runs_recorded() -> None:
    status = table_maintenance.last_maintenance_status(
        "ws-1",
        "lakehouse-1",
        client=_FakeClient(runs=[]),
    )

    assert status["status"] == "no_runs_recorded"
    assert status["last_run_at"] == ""
