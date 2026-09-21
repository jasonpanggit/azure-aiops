"""Azure SRE Agent thread verification and routing safety."""

from __future__ import annotations

import json

import httpx
import pytest

from intelligence.remediation.execution_service import (
    _supersede_eligibility,
)
from intelligence.remediation.execution_store import RETRYABLE_STATUSES
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


def _submitted_record(**overrides: object) -> dict[str, object]:
    record = _record(
        scope_attributes={"subscription": "sub-1"},
        execution_snapshot={
            "target_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
            "target_kind": "Azure VM",
            "patch_ids": ["KB600001"],
            "operation": "install_patches",
            "snapshot_hash": "a" * 64,
        },
    )
    record.update(overrides)
    return record


def _provider_operation(**overrides: object) -> dict[str, object]:
    evidence: dict[str, object] = {
        "schema_version": "1.0",
        "operation_id": "provider-operation-1",
        "status": "submitted",
        "skill_name": "aiops-install-selected-patches-v1",
        "skill_version": "1.0",
        "operation": "install_patches",
        "target_id": "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
        "patch_ids": ["KB600001"],
    }
    evidence.update(overrides)
    return evidence


def _arc_record(**overrides: object) -> dict[str, object]:
    record = _record(
        scope_attributes={"subscription": "sub-1"},
        execution_snapshot={
            "target_id": (
                "/subscriptions/sub-1/resourceGroups/rg/providers/"
                "Microsoft.HybridCompute/machines/vm-1"
            ),
            "target_kind": "Arc-enabled server",
            "patch_ids": ["5122874"],
            "operation": "install_patches",
            "snapshot_hash": "a" * 64,
        },
    )
    record.update(overrides)
    return record


def _pending_cli_execution_payload(**overrides: object) -> dict[str, object]:
    command = (
        "az connectedmachine install-patches --ids /subscriptions/sub-1/"
        "resourceGroups/rg/providers/Microsoft.HybridCompute/machines/vm-1 "
        "--windows-parameters '{\"kbNumbersToInclude\":[\"5122874\"]}' "
        "--maximum-duration PT2H --reboot-setting IfRequired --no-wait true"
    )
    execution: dict[str, object] = {
        "id": "cli-execution-1",
        "command": command,
        "description": "Setting resource configuration",
        "status": "Pending",
        "originalFunctionCall": json.dumps(
            {
                "Name": "RunAzCliWriteCommands",
                "Arguments": {"command": command},
                "InformationalOnly": False,
                "CallId": "call-1",
            }
        ),
        "output": None,
        "error": None,
        "createdTimestamp": "2026-09-21T12:05:52Z",
        "startedTimestamp": None,
        "completedTimestamp": None,
        "executedBy": None,
        "requiredScopes": None,
        "expiredByTimeout": False,
    }
    execution.update(overrides)
    return {
        **_LIVE_MESSAGE_COMPLETE_THREAD,
        "lastMessage": {
            "isComplete": True,
            "azCliExecution": execution,
        },
    }


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
    assert result["verification_evidence"]["approval_pending"] is True


def test_cancel_rejects_exact_pending_approvals_and_confirms_none_remain() -> None:
    requests: list[httpx.Request] = []
    approval_reads = 0
    thread_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal approval_reads, thread_reads
        requests.append(request)
        if request.url.path == "/api/v1/threads/thread-123":
            thread_reads += 1
            status = (
                "Pending User Input"
                if thread_reads == 1
                else "failed_without_action"
            )
            return httpx.Response(200, json={"status": status}, request=request)
        if request.method == "GET":
            approval_reads += 1
            payload = [{"id": "approval-1", "status": "Pending"}] if approval_reads == 1 else []
            return httpx.Response(200, json=payload, request=request)
        assert request.method == "POST"
        assert request.content == b'{"decision":"reject"}'
        return httpx.Response(204, request=request)

    credential = _Credential()
    verifier = SreAgentExecutionVerifier(
        credential=credential,
        agent_endpoint=AGENT_ENDPOINT,
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ),
    )

    result = verifier.cancel(_record())

    assert result == {
        "cancelled": True,
        "thread_id": "thread-123",
        "approval_ids": ["approval-1"],
        "thread_state": "failed_without_action",
    }
    assert [request.method for request in requests] == [
        "GET",
        "GET",
        "POST",
        "GET",
        "GET",
    ]
    assert requests[1].url.path == "/api/v1/approvals/thread-123"
    assert requests[2].url.path == (
        "/api/v1/approvals/thread-123/approval-1/decision"
    )
    assert credential.scopes == [
        (SRE_AGENT_THREAD_SCOPE,),
        (SRE_AGENT_THREAD_SCOPE,),
        (SRE_AGENT_THREAD_SCOPE,),
    ]


def test_cancel_fails_closed_without_a_typed_pending_approval() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload: object = (
            {"status": "Pending User Input"}
            if request.url.path == "/api/v1/threads/thread-123"
            else []
        )
        return httpx.Response(200, json=payload, request=request)

    verifier = SreAgentExecutionVerifier(
        credential=_Credential(),
        agent_endpoint=AGENT_ENDPOINT,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ExecutionVerificationUnavailable) as excinfo:
        verifier.cancel(_record())

    assert excinfo.value.capability == "sre_agent_approval_cancel"


def test_cancel_fails_closed_when_an_approval_remains_after_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/threads/thread-123":
            return httpx.Response(
                200,
                json={"status": "Pending User Input"},
                request=request,
            )
        if request.method == "POST":
            return httpx.Response(204, request=request)
        return httpx.Response(
            200,
            json=[{"id": "approval-1", "status": "Pending"}],
            request=request,
        )

    verifier = SreAgentExecutionVerifier(
        credential=_Credential(),
        agent_endpoint=AGENT_ENDPOINT,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ExecutionVerificationUnavailable, match="still reports"):
        verifier.cancel(_record())


def test_read_approvals_returns_every_row_regardless_of_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/approvals/thread-123"
        return httpx.Response(
            200,
            json=[
                {"id": "approval-1", "status": "Rejected"},
                {"id": "approval-2", "status": "Approved"},
            ],
            request=request,
        )

    verifier = SreAgentExecutionVerifier(
        credential=_Credential(),
        agent_endpoint=AGENT_ENDPOINT,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    rows = verifier.read_approvals(_record())

    assert rows == [
        {"id": "approval-1", "status": "Rejected"},
        {"id": "approval-2", "status": "Approved"},
    ]


def test_read_approvals_returns_empty_list_when_none_exist() -> None:
    verifier, _credential = _verifier([])

    assert verifier.read_approvals(_record()) == []


def test_read_approvals_fails_closed_on_non_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    verifier = SreAgentExecutionVerifier(
        credential=_Credential(),
        agent_endpoint=AGENT_ENDPOINT,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ExecutionVerificationUnavailable) as excinfo:
        verifier.read_approvals(_record())

    assert excinfo.value.capability == "sre_agent_approval_read"


def test_read_approvals_fails_closed_on_unrecognized_shape() -> None:
    verifier, _credential = _verifier({"unexpected": "shape"})

    with pytest.raises(ExecutionVerificationUnavailable) as excinfo:
        verifier.read_approvals(_record())

    assert excinfo.value.capability == "sre_agent_approval_read"


def test_read_approvals_fails_closed_on_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable-sentinel", request=request)

    verifier = SreAgentExecutionVerifier(
        credential=_Credential(),
        agent_endpoint=AGENT_ENDPOINT,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ExecutionVerificationUnavailable) as excinfo:
        verifier.read_approvals(_record())

    assert excinfo.value.capability == "sre_agent_approval_read"
    assert "unreachable-sentinel" not in str(excinfo.value)


def test_complete_without_typed_write_submission_does_not_succeed() -> None:
    verifier, _credential = _verifier(
        {
            "status": "Complete",
            "messages": [{"content": "All selected patches installed successfully"}],
        }
    )

    result = verifier.verify(_record())

    assert result["outcome"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"
    assert result["verified_state"] == "Complete"


def test_no_wait_completion_requires_exact_typed_write_submission() -> None:
    verifier, _credential = _verifier(
        {
            "status": {
                "actionsStatus": {
                    "hasCriticalActions": False,
                    "hasWarningActions": False,
                },
                "incidentStatus": {"status": ""},
            },
            "lastMessage": {"isComplete": True},
            "provider_operation": _provider_operation(),
        }
    )

    result = verifier.verify(_submitted_record())

    assert result == {
        "verifiable": True,
        "outcome": "succeeded",
        "verified_state": "Complete",
        "verification_evidence": {
            "thread_status": {
                "last_message_complete": True,
                "has_critical_actions": False,
                "has_warning_actions": False,
                "incident_status": "",
            },
            "provider_operation": {
                "schema_version": "1.0",
                "operation_id": "provider-operation-1",
                "status": "submitted",
                "skill_name": "aiops-install-selected-patches-v1",
                "skill_version": "1.0",
                "operation": "install_patches",
                "target_id": _submitted_record()["execution_snapshot"]["target_id"],
                "patch_ids": ["KB600001"],
            },
        },
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "1.4"),
        ("operation_id", ""),
        ("status", "failed_without_action"),
        ("skill_name", "other-write-skill"),
        ("skill_version", "1.4"),
        ("operation", "applicability_check"),
        ("target_id", "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-other"),
        ("patch_ids", ["KB600002"]),
    ],
)
def test_completed_thread_with_mismatched_write_submission_never_succeeds(
    field: str,
    value: object,
) -> None:
    verifier, _credential = _verifier(
        {
            "status": {
                "actionsStatus": {
                    "hasCriticalActions": False,
                    "hasWarningActions": False,
                },
                "incidentStatus": {"status": "Completed"},
            },
            "lastMessage": {"isComplete": True},
            "provider_operation": _provider_operation(**{field: value}),
        }
    )

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "1.4"),
        ("operation_id", ""),
        ("skill_name", "other-write-skill"),
        ("patch_ids", ["KB600002"]),
    ],
)
def test_active_thread_with_mismatched_write_submission_stays_running(
    field: str,
    value: object,
) -> None:
    verifier, _credential = _verifier(
        {
            "status": {
                "actionsStatus": {
                    "hasCriticalActions": False,
                    "hasWarningActions": False,
                },
                "incidentStatus": {"status": ""},
            },
            "lastMessage": {"isComplete": True},
            "provider_operation": _provider_operation(**{field: value}),
        }
    )

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "running"
    assert result["provider_active"] is True
    assert "provider_operation" not in result["verification_evidence"]


def test_completed_thread_rejects_extra_provider_operation_fields() -> None:
    operation = _provider_operation()
    operation["unexpected"] = "not-allowed"
    verifier, _credential = _verifier(
        {
            "status": "Complete",
            "provider_operation": operation,
        }
    )

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"


def test_completed_thread_cannot_make_a_noncanonical_snapshot_operation_valid() -> None:
    record = _submitted_record()
    record["execution_snapshot"]["operation"] = "applicability_check"
    verifier, _credential = _verifier(
        {
            "status": "Complete",
            "provider_operation": _provider_operation(
                operation="applicability_check"
            ),
        }
    )

    result = verifier.verify(record)

    assert result["outcome"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"


def test_typed_failed_without_action_never_becomes_success() -> None:
    verifier, _credential = _verifier(
        {
            "status": "failed_without_action",
        }
    )

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "failed"
    assert result["failure_class"] == "provider_rejected"
    assert result["verified_state"] != "Complete"


def test_composite_failed_without_action_overrides_conflicting_submission_proof() -> None:
    verifier, _credential = _verifier(
        {
            "status": {
                "actionsStatus": {
                    "hasCriticalActions": False,
                    "hasWarningActions": False,
                },
                "incidentStatus": {"status": "failed_without_action"},
            },
            "lastMessage": {"isComplete": True},
            "provider_operation": _provider_operation(),
        }
    )

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "failed"
    assert result["verified_state"] == "Failed"


def test_scalar_submission_ambiguous_preserves_recovery_block() -> None:
    verifier, _credential = _verifier({"status": "submission_ambiguous"})

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"


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
            "running",
            "In Progress",
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
                        "hasCriticalActions": False,
                        "hasWarningActions": True,
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


_LIVE_MESSAGE_COMPLETE_THREAD: dict[str, object] = {
    "status": {
        "actionsStatus": {
            "hasCriticalActions": False,
            "hasWarningActions": False,
        },
        "incidentStatus": {"incidentId": "", "status": ""},
    },
    "lastMessage": {"isComplete": True},
}


def test_live_message_complete_thread_stays_active_before_review_actions() -> None:
    """RME-D7CEC1940ECEC97C regression: the 23:44:44 poll of provider thread
    26937248-4e53-4205-84d7-527477354736 returned a message-complete composite
    while the agent still went on to read applicability and present a Review
    command at 23:45:57. That shape must remain provider-active."""
    verifier, _credential = _verifier(_LIVE_MESSAGE_COMPLETE_THREAD)

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "running"
    assert result["verified_state"] == "In Progress"
    assert result["provider_active"] is True
    assert "failure_class" not in result
    assert result["verification_evidence"]["thread_status"] == {
        "last_message_complete": True,
        "has_critical_actions": False,
        "has_warning_actions": False,
        "incident_status": "",
    }


def test_live_typed_user_question_maps_to_pending_review() -> None:
    payload = {
        **_LIVE_MESSAGE_COMPLETE_THREAD,
        "lastMessage": {
            "isComplete": True,
            "userQuestion": {
                "questionId": "question-123",
                "question": "Submit the displayed command?",
                "header": "Install patch",
                "options": [
                    {
                        "label": "Approve submission",
                        "description": "Submit the reviewed request.",
                    },
                    {
                        "label": "Decline",
                        "description": "Do not submit.",
                    },
                ],
                "allowFreeText": False,
                "status": "Pending",
            },
        },
    }
    verifier, _credential = _verifier(payload)

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "running"
    assert result["verified_state"] == "Pending Review"
    assert result["provider_active"] is True
    assert result["verification_evidence"]["approval_pending"] is True
    assert result["verification_evidence"]["user_question"] == {
        "question_id": "question-123",
        "question": "Submit the displayed command?",
        "options": ["Approve submission", "Decline"],
        "allow_free_text": False,
    }


def test_live_typed_cli_execution_maps_to_exact_pending_review() -> None:
    verifier, _credential = _verifier(_pending_cli_execution_payload())

    result = verifier.verify(_arc_record())

    assert result["outcome"] == "running"
    assert result["verified_state"] == "Pending Review"
    assert result["provider_active"] is True
    assert result["verification_evidence"]["approval_pending"] is True
    assert result["verification_evidence"]["provider_review"] == {
        "kind": "az_cli_execution",
        "execution_id": "cli-execution-1",
        "status": "pending",
        "command": _pending_cli_execution_payload()["lastMessage"][
            "azCliExecution"
        ]["command"],
        "required_scopes": None,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "Completed"),
        ("command", "az account show"),
        ("expiredByTimeout", True),
        ("output", "submitted"),
        ("startedTimestamp", "2026-09-21T12:06:00Z"),
        ("originalFunctionCall", "{}"),
    ],
)
def test_unrecognized_cli_execution_never_unlocks_review(
    field: str,
    value: object,
) -> None:
    payload = _pending_cli_execution_payload(**{field: value})
    verifier, _credential = _verifier(payload)

    result = verifier.verify(_arc_record())

    assert result["verified_state"] == "In Progress"
    assert "approval_pending" not in result["verification_evidence"]
    assert "provider_review" not in result["verification_evidence"]


def test_approve_review_posts_only_the_fresh_exact_cli_execution() -> None:
    requests: list[httpx.Request] = []
    payload = _pending_cli_execution_payload(requiredScopes="scope-a scope-b")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=payload, request=request)
        assert request.method == "POST"
        assert request.url.path == (
            "/api/v1/azCliExecution/thread-123/cli-execution-1/action"
        )
        assert request.headers["x-sreagent-obo-scope"] == "scope-a scope-b"
        assert json.loads(request.content) == {
            "action": "run",
            "user": "operator@example.com",
            "ApproveScope": "none",
        }
        return httpx.Response(202, json={"status": "accepted"}, request=request)

    verifier = SreAgentExecutionVerifier(
        credential=_Credential(),
        agent_endpoint=AGENT_ENDPOINT,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = verifier.approve_review(
        _arc_record(),
        requested_by="operator@example.com",
    )

    assert result == {
        "accepted": True,
        "thread_id": "thread-123",
        "execution_id": "cli-execution-1",
        "action": "run",
    }
    assert [request.method for request in requests] == ["GET", "POST"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "Answered"),
        ("allowFreeText", True),
        (
            "options",
            [
                {"label": "Run anything"},
                {"label": "Decline"},
            ],
        ),
    ],
)
def test_unrecognized_user_question_does_not_unlock_review(
    field: str,
    value: object,
) -> None:
    question = {
        "questionId": "question-123",
        "question": "Submit the displayed command?",
        "options": [
            {"label": "Approve submission"},
            {"label": "Decline"},
        ],
        "allowFreeText": False,
        "status": "Pending",
    }
    question[field] = value
    payload = {
        **_LIVE_MESSAGE_COMPLETE_THREAD,
        "lastMessage": {
            "isComplete": True,
            "userQuestion": question,
        },
    }
    verifier, _credential = _verifier(payload)

    result = verifier.verify(_submitted_record())

    assert result["verified_state"] == "In Progress"
    assert "approval_pending" not in result["verification_evidence"]
    assert "user_question" not in result["verification_evidence"]


def test_live_message_complete_thread_is_not_retryable_or_supersedable() -> None:
    """The still-active thread must not unlock retry or supersession while the
    original Review command remains approvable."""
    verifier, _credential = _verifier(_LIVE_MESSAGE_COMPLETE_THREAD)

    result = verifier.verify(_submitted_record())

    record = {
        "status": "running" if result["outcome"] == "running" else result["outcome"],
        "verification_evidence": result["verification_evidence"],
    }
    assert _supersede_eligibility(record) == "execution_active"
    assert record["status"] not in RETRYABLE_STATUSES


def test_message_complete_never_reports_submission_ambiguous_without_terminality() -> (
    None
):
    """Message-level completion alone must not produce the recovery-blocking
    ``submission_ambiguous`` failure class."""
    verifier, _credential = _verifier(_LIVE_MESSAGE_COMPLETE_THREAD)

    result = verifier.verify(_record())

    assert result["outcome"] != "failed"
    assert result.get("failure_class") is None
    assert result["verified_state"] != "CompleteWithoutSubmissionProof"


def test_message_incomplete_thread_also_stays_running() -> None:
    payload = {
        "status": {
            "actionsStatus": {
                "hasCriticalActions": False,
                "hasWarningActions": False,
            },
            "incidentStatus": {"incidentId": "", "status": ""},
        },
        "lastMessage": {"isComplete": False},
    }
    verifier, _credential = _verifier(payload)

    result = verifier.verify(_record())

    assert result["outcome"] == "running"
    assert result["verified_state"] == "In Progress"


@pytest.mark.parametrize(
    "incident_status",
    ["failed_without_action", "blocked_no_action", "Failed", " error "],
)
def test_explicit_terminal_failure_incident_status_still_fails(
    incident_status: str,
) -> None:
    payload = {
        "status": {
            "actionsStatus": {
                "hasCriticalActions": False,
                "hasWarningActions": False,
            },
            "incidentStatus": {"incidentId": "inc-1", "status": incident_status},
        },
        "lastMessage": {"isComplete": True},
    }
    verifier, _credential = _verifier(payload)

    result = verifier.verify(_record())

    assert result["outcome"] == "failed"
    assert result["verified_state"] == "Failed"


@pytest.mark.parametrize("incident_status", ["cancelled", "Canceled"])
def test_explicit_terminal_cancelled_incident_status_still_cancels(
    incident_status: str,
) -> None:
    payload = {
        "status": {
            "actionsStatus": {
                "hasCriticalActions": False,
                "hasWarningActions": False,
            },
            "incidentStatus": {"incidentId": "inc-1", "status": incident_status},
        },
        "lastMessage": {"isComplete": True},
    }
    verifier, _credential = _verifier(payload)

    result = verifier.verify(_record())

    assert result["outcome"] == "cancelled"
    assert result["verified_state"] == "Cancelled"


def test_explicit_terminal_success_without_submission_proof_stays_blocked() -> None:
    payload = {
        "status": {
            "actionsStatus": {
                "hasCriticalActions": False,
                "hasWarningActions": False,
            },
            "incidentStatus": {"incidentId": "inc-1", "status": "Completed"},
        },
        "lastMessage": {"isComplete": True},
    }
    verifier, _credential = _verifier(payload)

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"
    assert result["verified_state"] == "CompleteWithoutSubmissionProof"


def test_declined_review_prose_is_never_read_as_an_outcome() -> None:
    """The live thread's final typed prose was ``failed_without_action`` in
    message text only; prose must never drive the verified outcome."""
    payload = {
        "status": {
            "actionsStatus": {
                "hasCriticalActions": False,
                "hasWarningActions": False,
            },
            "incidentStatus": {"incidentId": "", "status": ""},
        },
        "lastMessage": {
            "isComplete": True,
            "content": "failed_without_action: the user declined the patch install",
        },
    }
    verifier, _credential = _verifier(payload)

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "running"
    assert result["provider_active"] is True


@pytest.mark.parametrize(
    ("critical", "warning"),
    [(True, False), (False, True)],
)
def test_typed_submission_proof_outranks_pending_action_flags(
    critical: bool,
    warning: bool,
) -> None:
    """Stale action flags must not hold a proven submission open forever."""
    payload = {
        "status": {
            "actionsStatus": {
                "hasCriticalActions": critical,
                "hasWarningActions": warning,
            },
            "incidentStatus": {"incidentId": "", "status": ""},
        },
        "lastMessage": {"isComplete": True},
        "provider_operation": _provider_operation(),
    }
    verifier, _credential = _verifier(payload)

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "succeeded"
    assert result["verified_state"] == "Complete"


@pytest.mark.parametrize(
    ("critical", "warning"),
    [(True, False), (False, True)],
)
def test_terminal_success_status_with_action_flags_still_blocks_recovery(
    critical: bool,
    warning: bool,
) -> None:
    """A terminal-success thread without proof must reach the recovery block
    rather than poll forever behind a stale action flag."""
    payload = {
        "status": {
            "actionsStatus": {
                "hasCriticalActions": critical,
                "hasWarningActions": warning,
            },
            "incidentStatus": {"incidentId": "inc-1", "status": "Completed"},
        },
        "lastMessage": {"isComplete": True},
    }
    verifier, _credential = _verifier(payload)

    result = verifier.verify(_submitted_record())

    assert result["outcome"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"


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
