from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest


def _load_script():
    path = (
        Path(__file__).parents[1]
        / "infra"
        / "scripts"
        / "push_inventory_refresh_pipeline.py"
    )
    spec = importlib.util.spec_from_file_location(
        "push_inventory_refresh_pipeline",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = ""
        self.headers: dict[str, str] = {}

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        assert 200 <= self.status_code < 300


def test_pipeline_content_sets_ten_minute_http_request_timeout() -> None:
    script = _load_script()

    content = script.build_pipeline_content(
        "https://api.example",
        "secret",
        "connection-id",
        timeout_seconds=1800,
    )

    activity = content["properties"]["activities"][0]
    assert activity["policy"]["timeout"] == "0.00:30:00"
    assert activity["typeProperties"]["httpRequestTimeout"] == "00:10:00"


@pytest.mark.parametrize(
    ("timeout_seconds", "expected"),
    [
        (599, "00:09:59"),
        (600, "00:10:00"),
        (601, "00:10:00"),
    ],
)
def test_pipeline_content_bounds_http_request_timeout(
    timeout_seconds: int,
    expected: str,
) -> None:
    script = _load_script()

    content = script.build_pipeline_content(
        "https://api.example",
        "secret",
        "connection-id",
        timeout_seconds=timeout_seconds,
    )

    activity = content["properties"]["activities"][0]
    assert activity["typeProperties"]["httpRequestTimeout"] == expected


def test_pipeline_content_rejects_nonpositive_timeout() -> None:
    script = _load_script()

    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        script.build_pipeline_content(
            "https://api.example",
            "secret",
            "connection-id",
            timeout_seconds=0,
        )


def test_create_schedule_reuses_one_and_disables_duplicates() -> None:
    script = _load_script()
    existing = [
        {
            "id": "schedule-primary",
            "enabled": False,
            "createdDateTime": "2026-08-26T10:00:00Z",
            "configuration": {
                "type": "Cron",
                "interval": 60,
                "startDateTime": "2026-08-26T10:00:00",
                "endDateTime": "2036-08-23T10:00:00",
                "localTimeZoneId": "UTC",
            },
        },
        {
            "id": "schedule-duplicate",
            "enabled": True,
            "createdDateTime": "2026-08-27T10:00:00Z",
            "configuration": {
                "type": "Cron",
                "interval": 60,
                "startDateTime": "2026-08-27T10:00:00",
                "endDateTime": "2036-08-24T10:00:00",
                "localTimeZoneId": "UTC",
            },
        },
    ]

    class Client:
        def __init__(self) -> None:
            self.patches: list[tuple[str, dict[str, Any]]] = []

        def get(self, path: str) -> _Response:
            assert path.endswith("/jobs/Pipeline/schedules")
            return _Response(200, {"value": existing})

        def patch(self, path: str, *, json: dict[str, Any]) -> _Response:
            self.patches.append((path, json))
            return _Response(200, {})

        def post(self, path: str, *, json: dict[str, Any]) -> _Response:
            raise AssertionError(f"must reuse the existing schedule, not POST {path}")

    client = Client()

    script.create_schedule(
        client,
        "workspace-id",
        "item-id",
        interval_minutes=60,
    )

    assert len(client.patches) == 2
    primary_path, primary_payload = client.patches[0]
    duplicate_path, duplicate_payload = client.patches[1]
    assert primary_path.endswith("/schedules/schedule-primary")
    assert primary_payload["enabled"] is True
    assert primary_payload["configuration"]["interval"] == 60
    assert duplicate_path.endswith("/schedules/schedule-duplicate")
    assert duplicate_payload == {
        "enabled": False,
        "configuration": existing[1]["configuration"],
    }


def test_create_schedule_posts_once_when_no_schedule_exists() -> None:
    script = _load_script()

    class Client:
        def __init__(self) -> None:
            self.posts: list[tuple[str, dict[str, Any]]] = []

        def get(self, path: str) -> _Response:
            assert path.endswith("/jobs/Pipeline/schedules")
            return _Response(200, {"value": []})

        def post(self, path: str, *, json: dict[str, Any]) -> _Response:
            self.posts.append((path, json))
            return _Response(201, {})

        def patch(self, path: str, *, json: dict[str, Any]) -> _Response:
            raise AssertionError(f"no schedule exists to PATCH at {path}")

    client = Client()

    script.create_schedule(
        client,
        "workspace-id",
        "item-id",
        interval_minutes=60,
    )

    assert len(client.posts) == 1
    assert client.posts[0][1]["enabled"] is True
    assert client.posts[0][1]["configuration"]["interval"] == 60
