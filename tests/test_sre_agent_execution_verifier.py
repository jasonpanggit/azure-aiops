"""Azure SRE Agent thread verification and routing safety."""

from __future__ import annotations

import httpx
import pytest

from intelligence.remediation.execution_verifier import (
    ExecutionVerificationUnavailable,
)
from intelligence.remediation.sre_agent_verifier import (
    SreAgentExecutionVerifier,
)
from operations.patching.sre_agent_adapter import SRE_AGENT_THREAD_SCOPE

AGENT_ENDPOINT = "https://sre-agent.example.azure.com"
THREAD_URL = f"{AGENT_ENDPOINT}/api/v1/threads/thread-123"


class _Credential:
    def __init__(
        self,
        token: str = "sre-data-token",
        error: Exception | None = None,
    ) -> None:
        self.token = token
        self.error = error
        self.scopes: list[tuple[str, ...]] = []

    def get_token(self, *scopes: str, **_kwargs: object) -> object:
        self.scopes.append(scopes)
        if self.error is not None:
            raise self.error
        return type("Token", (), {"token": self.token})()


def _assert_sanitized_exception(exc: BaseException, sentinel: str) -> None:
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert sentinel not in str(exc)
    assert sentinel not in repr(exc)
    assert sentinel not in repr(vars(exc))


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "provider": "sre-agent",
        "provider_job_id": THREAD_URL,
    }
    record.update(overrides)
    return record


def _verifier(
    payload: dict[str, object],
    *,
    credential: _Credential | None = None,
    requests: list[httpx.Request] | None = None,
) -> tuple[SreAgentExecutionVerifier, _Credential]:
    selected = credential or _Credential()

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return httpx.Response(200, json=payload, request=request)

    return (
        SreAgentExecutionVerifier(
            credential=selected,
            agent_endpoint=AGENT_ENDPOINT,
            client=httpx.Client(
                transport=httpx.MockTransport(handler),
                follow_redirects=True,
            ),
        ),
        selected,
    )


@pytest.mark.parametrize("status", ["In Progress", " in   progress "])
def test_in_progress_maps_to_running_and_uses_data_plane_scope(status: str) -> None:
    requests: list[httpx.Request] = []
    verifier, credential = _verifier({"status": status}, requests=requests)

    result = verifier.verify(_record())

    assert result["outcome"] == "running"
    assert credential.scopes == [(SRE_AGENT_THREAD_SCOPE,)]
    assert requests[0].headers["Authorization"] == "Bearer " + credential.token


def test_pending_user_input_remains_active_for_review_approval() -> None:
    verifier, _credential = _verifier({"status": "Pending User Input"})

    result = verifier.verify(_record())

    assert result["outcome"] == "running"
    assert result["verified_state"] == "Pending Review"
    assert result["provider_active"] is True


def test_complete_is_provider_complete_without_parsing_model_prose() -> None:
    verifier, _credential = _verifier(
        {
            "status": "Complete",
            "messages": [{"content": "All selected patches installed successfully"}],
        }
    )

    result = verifier.verify(_record())

    assert result == {
        "verifiable": True,
        "outcome": "succeeded",
        "verified_state": "Complete",
        "verification_evidence": {"thread_status": "Complete"},
    }


@pytest.mark.parametrize(
    ("payload", "outcome", "state"),
    [
        (
            {
                "status": {
                    "actionsStatus": {
                        "hasCriticalActions": False,
                        "hasWarningActions": False,
                    },
                    "incidentStatus": {"status": ""},
                },
                "lastMessage": {"isComplete": True, "content": "failed"},
            },
            "succeeded",
            "Complete",
        ),
        (
            {
                "status": {
                    "actionsStatus": {
                        "hasCriticalActions": True,
                        "hasWarningActions": False,
                    },
                    "incidentStatus": {"status": "Active"},
                },
                "lastMessage": {"isComplete": True},
            },
            "running",
            "Pending Review",
        ),
        (
            {
                "status": {
                    "actionsStatus": {
                        "hasCriticalActions": True,
                        "hasWarningActions": False,
                    },
                    "incidentStatus": {"status": "Active"},
                },
                "lastMessage": {"isComplete": False},
            },
            "running",
            "Pending Review",
        ),
        (
            {
                "status": {
                    "actionsStatus": {
                        "hasCriticalActions": False,
                        "hasWarningActions": True,
                    },
                    "incidentStatus": {"status": "Failed"},
                },
                "lastMessage": {"isComplete": True, "content": "success"},
            },
            "failed",
            "Failed",
        ),
    ],
)
def test_production_composite_thread_shapes_are_typed_without_prose(
    payload: dict[str, object],
    outcome: str,
    state: str,
) -> None:
    verifier, _credential = _verifier(payload)

    result = verifier.verify(_record())

    assert result["outcome"] == outcome
    assert result["verified_state"] == state
    assert result["verification_evidence"]["thread_status"][
        "last_message_complete"
    ] is payload["lastMessage"]["isComplete"]


def test_unknown_status_remains_running_until_deadline() -> None:
    verifier, _credential = _verifier({"status": "PreviewStatus"})

    result = verifier.verify(_record())

    assert result["outcome"] == "running"
    assert result["verified_state"] == "PreviewStatus"


def test_thread_handle_must_stay_under_configured_agent_endpoint() -> None:
    requests: list[httpx.Request] = []
    verifier, _credential = _verifier({"status": "Complete"}, requests=requests)

    with pytest.raises(ExecutionVerificationUnavailable, match="outside"):
        verifier.verify(
            _record(provider_job_id="https://attacker.example/api/v1/threads/thread-123")
        )

    assert requests == []


def test_poll_does_not_follow_redirects() -> None:
    requests: list[httpx.Request] = []
    sentinel = "sentinel-verifier-non-200"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            307,
            headers={"Location": "https://attacker.example/steal"},
            request=request,
        )

    verifier = SreAgentExecutionVerifier(
        credential=_Credential(token=sentinel),
        agent_endpoint=AGENT_ENDPOINT,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ),
    )

    with pytest.raises(ExecutionVerificationUnavailable) as excinfo:
        verifier.verify(_record())

    assert len(requests) == 1
    assert sentinel not in requests[0].headers.get("Authorization", "")
    _assert_sanitized_exception(excinfo.value, sentinel)


def test_authenticated_transport_failure_has_no_http_exception_chain() -> None:
    sentinel = "sentinel-verifier-transport"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response lost", request=request)

    credential = _Credential(token=sentinel)
    verifier = SreAgentExecutionVerifier(
        credential=credential,
        agent_endpoint=AGENT_ENDPOINT,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ExecutionVerificationUnavailable) as excinfo:
        verifier.verify(_record())

    assert credential.scopes == [(SRE_AGENT_THREAD_SCOPE,)]
    _assert_sanitized_exception(excinfo.value, sentinel)


def test_token_failure_occurs_before_thread_request() -> None:
    requests: list[httpx.Request] = []
    verifier, _credential = _verifier(
        {"status": "Complete"},
        credential=_Credential(error=RuntimeError("identity unavailable")),
        requests=requests,
    )

    with pytest.raises(ExecutionVerificationUnavailable, match="data-plane token"):
        verifier.verify(_record())

    assert requests == []


def test_empty_token_is_typed_and_occurs_before_thread_request() -> None:
    requests: list[httpx.Request] = []
    credential = _Credential(token="")
    verifier, _credential = _verifier(
        {"status": "Complete"},
        credential=credential,
        requests=requests,
    )

    with pytest.raises(ExecutionVerificationUnavailable, match="empty") as excinfo:
        verifier.verify(_record())

    assert excinfo.value.capability == "sre_agent_token"
    assert credential.scopes == [(SRE_AGENT_THREAD_SCOPE,)]
    assert requests == []
