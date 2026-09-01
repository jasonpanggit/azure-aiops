from __future__ import annotations

from datetime import UTC, datetime

import httpx

from fabric.capacity_health import check_capacity_state


class _Token:
    def __init__(self, token: str = "arm-token") -> None:
        self.token = token


class _Credential:
    def get_token(self, *scopes: str) -> _Token:
        assert scopes == ("https://management.azure.com/.default",)
        return _Token()


def _request(status_code: int, payload: dict) -> httpx.Response:
    request = httpx.Request("GET", "https://management.azure.com/example")
    return httpx.Response(status_code, request=request, json=payload)


def test_active_capacity_is_classified_healthy() -> None:
    result = check_capacity_state(
        "sub-1",
        "rg-1",
        "cap-1",
        credential=_Credential(),
        requester=lambda *args, **kwargs: _request(
            200,
            {
                "properties": {"state": "Active", "provisioningState": "Succeeded"},
                "sku": {"name": "F4"},
            },
        ),
        clock=lambda: datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC),
    )

    assert result["state"] == "healthy"
    assert result["raw_state"] == "Active"
    assert result["provisioning_state"] == "Succeeded"
    assert result["sku"] == "F4"


def test_paused_capacity_is_classified_unavailable() -> None:
    result = check_capacity_state(
        "sub-1",
        "rg-1",
        "cap-1",
        credential=_Credential(),
        requester=lambda *args, **kwargs: _request(
            200,
            {
                "properties": {"state": "Paused", "provisioningState": "Succeeded"},
                "sku": {"name": "F4"},
            },
        ),
    )

    assert result["state"] == "unavailable"
    assert result["raw_state"] == "Paused"


def test_arm_call_failure_is_classified_unknown() -> None:
    result = check_capacity_state(
        "sub-1",
        "rg-1",
        "cap-1",
        credential=_Credential(),
        requester=lambda *args, **kwargs: _request(403, {"error": "forbidden"}),
    )

    assert result["state"] == "unknown"
    assert result["state"] not in {"healthy", "unavailable"}


def test_check_uses_default_azure_identity_credential_path(monkeypatch) -> None:
    called = {"count": 0}

    def _default() -> _Credential:
        called["count"] += 1
        return _Credential()

    monkeypatch.setattr("fabric.capacity_health._default_arm_credential", _default)

    check_capacity_state(
        "sub-1",
        "rg-1",
        "cap-1",
        requester=lambda *args, **kwargs: _request(
            200,
            {"properties": {"state": "Active", "provisioningState": "Succeeded"}, "sku": {"name": "F4"}},
        ),
    )

    assert called["count"] == 1
