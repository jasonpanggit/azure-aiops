"""Post-submission verification: poll the real upstream source of truth.

An accepted ARM response only means "accepted". Update Manager and AKS
remain the authority on the actual outcome, so ``ExecutionVerifier`` polls
the operation URL Azure handed back at submission time and never infers
success from the 2xx response alone.
"""

from __future__ import annotations

import httpx
import pytest

from intelligence.remediation.execution_verifier import (
    ExecutionVerificationUnavailable,
    ExecutionVerifier,
)

OPERATION_URL = (
    "https://management.azure.com/subscriptions/sub-1/providers/"
    "Microsoft.Compute/locations/eastus/operations/op-123?api-version=2024-07-01"
)


class _FakeCredential:
    def get_token(self, *scopes, **kwargs):
        return type("Token", (), {"token": "fake-token"})()


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, handler) -> None:
        self._handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def _client_returning(status_code: int, json_body: dict | None = None, *, text: str = "") -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if json_body is not None:
            return httpx.Response(status_code, json=json_body, request=request)
        return httpx.Response(status_code, text=text, request=request)

    return httpx.Client(transport=_FakeTransport(handler))


def _client_raising_transport_error() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return httpx.Client(transport=_FakeTransport(handler))


def _record(provider_job_id: str = OPERATION_URL) -> dict:
    return {"execution_id": "RME-0001", "provider_job_id": provider_job_id}


def test_verify_maps_succeeded_status_to_verified_succeeded_outcome():
    client = _client_returning(200, {"status": "Succeeded"})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["verifiable"] is True
    assert result["outcome"] == "succeeded"
    assert result["verified_state"] == "Succeeded"


def test_verify_maps_failed_status_to_verified_failed_outcome_with_details():
    client = _client_returning(
        200,
        {"status": "Failed", "error": {"code": "PatchFailed", "message": "Reboot timed out"}},
    )
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["verifiable"] is True
    assert result["outcome"] == "failed"
    assert result["verified_state"] == "Failed"
    assert "Reboot timed out" in result["failure_details"]


def test_verify_maps_in_progress_status_to_running_outcome_and_is_repeatable():
    client = _client_returning(200, {"status": "InProgress"})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    first = verifier.verify(_record())
    second = verifier.verify(_record())

    assert first["outcome"] == "running"
    assert second["outcome"] == "running"
    assert first["verifiable"] is True


def test_verify_maps_running_status_alias_to_running_outcome():
    client = _client_returning(200, {"status": "Running"})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record())

    assert result["outcome"] == "running"


def test_verify_raises_typed_error_on_network_failure():
    client = _client_raising_transport_error()
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    with pytest.raises(ExecutionVerificationUnavailable):
        verifier.verify(_record())


def test_verify_reports_not_verifiable_when_no_provider_job_id():
    client = _client_returning(200, {"status": "Succeeded"})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(_record(provider_job_id=""))

    assert result["verifiable"] is False
    assert result["reason"] == "no provider job id"
