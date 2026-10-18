"""Safety contract for the opt-in Azure SRE Agent patch adapter."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

import httpx
import pytest

import operations.patching.sre_agent_adapter as sre_adapter
from intelligence.remediation.approval_decisions import execution_snapshot_hash
from operations.patching.adapters import PatchExecutionUnavailable
from operations.patching.models import AvailablePatch, PatchRun, PatchTarget
from operations.patching.sre_agent_adapter import (
    SRE_AGENT_TRIGGER_SCOPE,
    SreAgentPatchExecutionAdapter,
)

TRIGGER_URL = (
    "https://trigger.example.sre.azure.com/api/v1/httptriggers/trigger/"
    "secret-trigger-id"
)
TRIGGER_ID = "secret-trigger-id"
TRIGGER_ORIGIN = "https://trigger.example.sre.azure.com"
AGENT_ENDPOINT = "https://sre-agent.example.azure.com"
SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000001"
TARGET_PREFIX = f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-prod"
VM_ID = f"{TARGET_PREFIX}/providers/Microsoft.Compute/virtualMachines/vm-payments"
ARC_ID = f"{TARGET_PREFIX}/providers/Microsoft.HybridCompute/machines/arc-payments"


class _Credential:
    def __init__(
        self, *, token: str = "workload-token", error: Exception | None = None
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


def _target(**overrides: object) -> PatchTarget:
    values = {
        "target_id": VM_ID,
        "name": "vm-payments",
        "inventory_kind": "Azure VM",
        "subscription_id": SUBSCRIPTION_ID,
        "resource_group": "rg-prod",
        "available_patches": (AvailablePatch(patch_id="KB600001"),),
    }
    values.update(overrides)
    return PatchTarget(**values)


def _run(**overrides: object) -> PatchRun:
    target_id = str(overrides.get("target_id", VM_ID))
    target_kind = str(overrides.get("inventory_kind", "Azure VM"))
    patch_ids = tuple(overrides.get("patch_ids", ("KB600001",)))
    operation = str(overrides.get("operation", "install_patches"))
    snapshot = {
        "target_id": target_id,
        "patch_ids": list(patch_ids),
        "target_kind": target_kind,
        "operation": operation,
        "action_version": "action-version-1",
        "subscription_id": SUBSCRIPTION_ID,
        "approver": "approver@example.com",
    }
    snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)
    values = {
        "run_id": "run-immutable-1",
        "target_id": target_id,
        "inventory_kind": target_kind,
        "operation": operation,
        "patch_ids": patch_ids,
        "reboot_setting": "IfRequired",
        "requested_by": "operator@example.com",
        "approved_by": "approver@example.com",
        "subscription_id": SUBSCRIPTION_ID,
        "details": {
            "approval_context": {
                "decision_id": "RMD-APPROVED-1",
                "decision": "approved",
                "decided_at": "2026-09-16T08:00:00+00:00",
                "expires_at": "2026-09-17T08:00:00+00:00",
                "approved_by": "approver@example.com",
                "execution_snapshot": snapshot,
            }
        },
    }
    values.update(overrides)
    return PatchRun(**values)


def _adapter(
    handler,
    *,
    credential: _Credential | None = None,
    target_prefix: str = TARGET_PREFIX,
) -> tuple[SreAgentPatchExecutionAdapter, _Credential]:
    selected_credential = credential or _Credential()
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    )
    return (
        SreAgentPatchExecutionAdapter(
            selected_credential,
            trigger_url=TRIGGER_URL,
            trigger_id=TRIGGER_ID,
            trigger_origin=TRIGGER_ORIGIN,
            agent_endpoint=AGENT_ENDPOINT,
            subscription_id=SUBSCRIPTION_ID,
            target_prefix=target_prefix,
            client=client,
            now=lambda: datetime(2026, 9, 16, 12, tzinfo=UTC),
        ),
        selected_credential,
    )


def test_rollout_binding_survives_the_locked_provider_envelope() -> None:
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(202, json={"success": True, "threadId": "thread-rollout"}, request=request)
    adapter, _ = _adapter(handler)
    run = _run()
    snapshot = run.details["approval_context"]["execution_snapshot"]
    snapshot["rollout"] = {"rollout_id": "RMO-" + "a" * 32, "terms_hash": "b" * 64, "wave": 1}
    snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)
    adapter.submit(run, _target())
    sent = json.loads(requests[0].content)["approval"]["execution_snapshot"]
    assert sent == snapshot
    assert sent["snapshot_hash"] == sre_adapter._approved_snapshot_hash(sent)


@pytest.mark.parametrize("mutation", [
    {"wave": True}, {"wave": 0}, {"wave": 6}, {"terms_hash": "not-a-digest"},
    {"rollout_id": "foreign"}, {"extra": "not-allowed"},
])
def test_invalid_rollout_metadata_never_crosses_the_provider_boundary(mutation) -> None:
    adapter, _ = _adapter(lambda _: pytest.fail("Invalid metadata must not submit"))
    run = _run()
    snapshot = run.details["approval_context"]["execution_snapshot"]
    snapshot["rollout"] = {"rollout_id": "RMO-" + "a" * 32, "terms_hash": "b" * 64, "wave": 1, **mutation}
    snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)
    with pytest.raises(PatchExecutionUnavailable):
        adapter.submit(run, _target())


def test_submit_posts_only_the_versioned_immutable_envelope() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            202,
            json={"success": True, "threadId": "thread-123"},
            request=request,
        )

    adapter, credential = _adapter(handler)
    result = adapter.submit(_run(), _target())

    assert credential.scopes == [(SRE_AGENT_TRIGGER_SCOPE,)]
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == TRIGGER_URL
    assert request.headers["Authorization"] == "Bearer " + credential.token
    payload = json.loads(request.content)
    assert payload == {
        "schema_version": "1.1",
        "run_id": "run-immutable-1",
        "subscription_id": SUBSCRIPTION_ID,
        "target_id": VM_ID,
        "target_kind": "Azure VM",
        "patch_ids": ["KB600001"],
        "approval": _run().details["approval_context"],
        "skill_chain": sre_adapter._skill_contract(),
        "reboot_setting": "IfRequired",
        "maximum_duration": "PT2H",
        "requested_by": "operator@example.com",
        "approved_by": "approver@example.com",
        "operation": "install_patches",
    }
    assert result.provider == "sre-agent"
    assert result.provider_job_id == (
        "https://sre-agent.example.azure.com/api/v1/threads/thread-123"
    )
    assert "secret-trigger-id" not in result.provider_job_id
    assert result.details == {
        "http_status": 202,
        "thread_id": "thread-123",
        "resource_id": VM_ID,
        "subscription_id": SUBSCRIPTION_ID,
        "schema_version": "1.1",
    }


def test_approval_projection_fields_do_not_change_snapshot_hash_identity() -> None:
    snapshot = copy.deepcopy(_run().details["approval_context"]["execution_snapshot"])
    snapshot_without_projection = {
        key: value
        for key, value in snapshot.items()
        if key not in {"subscription_id", "approver", "snapshot_hash"}
    }

    assert execution_snapshot_hash(snapshot) == execution_snapshot_hash(
        snapshot_without_projection
    )
    assert sre_adapter._approved_snapshot_hash(snapshot) == snapshot["snapshot_hash"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subscription_id", "00000000-0000-0000-0000-000000000002"),
        ("approver", "different-approver@example.com"),
    ],
)
def test_approval_projection_must_match_top_level_envelope_before_http(
    field: str,
    value: str,
) -> None:
    requests: list[httpx.Request] = []
    run = _run()
    run.details["approval_context"]["execution_snapshot"][field] = value
    adapter, credential = _adapter(
        lambda request: (
            requests.append(request)
            or httpx.Response(202, json={"success": True, "threadId": "unused"})
        )
    )

    with pytest.raises(PatchExecutionUnavailable, match="locked contract"):
        adapter.submit(run, _target())

    assert requests == []
    assert credential.scopes == []


def test_submit_rejects_real_payload_builder_drift_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    original = sre_adapter._build_sre_agent_patch_envelope

    def drifted_payload(**kwargs: object) -> dict[str, object]:
        payload = original(**kwargs)
        payload["operation"] = "assess_patches"
        return payload

    monkeypatch.setattr(
        sre_adapter,
        "_build_sre_agent_patch_envelope",
        drifted_payload,
    )
    adapter, credential = _adapter(
        lambda request: (
            requests.append(request)
            or httpx.Response(202, json={"success": True, "threadId": "unused"})
        )
    )

    with pytest.raises(PatchExecutionUnavailable, match="locked contract") as excinfo:
        adapter.submit(_run(), _target())

    assert requests == []
    assert credential.scopes == []
    assert excinfo.value.provider_submitted is False
    assert excinfo.value.failure_class == "internal_validation"


def test_operator_identity_is_audit_data_and_never_used_as_bearer_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            202,
            json={"success": True, "threadId": "thread-123"},
            request=request,
        )

    adapter, credential = _adapter(handler)
    run = _run(
        requested_by="operator-token-value",
        approved_by="approver-token-value",
    )
    run.details["approval_context"]["approved_by"] = "approver-token-value"
    run.details["approval_context"]["execution_snapshot"]["approver"] = (
        "approver-token-value"
    )
    adapter.submit(run, _target())

    authorization = requests[0].headers["Authorization"]
    payload = json.loads(requests[0].content)
    assert authorization == "Bearer " + credential.token
    assert "operator-token-value" not in authorization
    assert "approver-token-value" not in authorization
    assert payload["requested_by"] == "operator-token-value"
    assert payload["approved_by"] == "approver-token-value"


def test_arc_target_uses_the_same_exact_bounded_envelope() -> None:
    arc_id = ARC_ID
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            202,
            json={"success": True, "threadId": "thread-arc"},
            request=request,
        )

    adapter, _credential = _adapter(handler)
    adapter.submit(
        _run(target_id=arc_id, inventory_kind="Arc-enabled server"),
        _target(target_id=arc_id, inventory_kind="Arc-enabled server"),
    )

    body = json.loads(requests[0].content)
    assert body["target_id"] == arc_id
    assert body["target_kind"] == "Arc-enabled server"
    assert body["patch_ids"] == ["KB600001"]


@pytest.mark.parametrize(
    ("target_id", "target_kind"),
    [
        (
            (
                f"{TARGET_PREFIX}/providers/Microsoft.Compute/virtualMachines/vm-a/"
                "extensions/agent"
            ),
            "Azure VM",
        ),
        (f"{TARGET_PREFIX}/providers/Microsoft.Compute/virtualMachines/vm a", "Azure VM"),
        (VM_ID, "Arc-enabled server"),
        (ARC_ID, "Azure VM"),
    ],
)
def test_malformed_child_or_cross_kind_targets_are_rejected_before_http(
    target_id: str,
    target_kind: str,
) -> None:
    requests: list[httpx.Request] = []
    adapter, credential = _adapter(
        lambda request: (
            requests.append(request)
            or httpx.Response(202, json={"success": True, "threadId": "unused"})
        )
    )

    with pytest.raises(PatchExecutionUnavailable, match="exact VM or Arc"):
        adapter.submit(
            _run(target_id=target_id, inventory_kind=target_kind),
            _target(target_id=target_id, inventory_kind=target_kind),
        )

    assert requests == []
    assert credential.scopes == []


def test_approval_snapshot_drift_is_rejected_before_token_or_http() -> None:
    requests: list[httpx.Request] = []
    run = _run()
    approval = copy.deepcopy(run.details["approval_context"])
    approval["execution_snapshot"]["patch_ids"] = ["KB600002"]
    run.details["approval_context"] = approval
    adapter, credential = _adapter(
        lambda request: (
            requests.append(request)
            or httpx.Response(202, json={"success": True, "threadId": "unused"})
        )
    )

    with pytest.raises(PatchExecutionUnavailable, match="locked contract"):
        adapter.submit(run, _target())

    assert requests == []
    assert credential.scopes == []


@pytest.mark.parametrize(
    ("run_overrides", "target_overrides", "message"),
    [
        ({"patch_ids": ()}, {}, "non-empty patch IDs"),
        ({"patch_ids": ("",)}, {}, "non-empty patch IDs"),
        ({"patch_ids": ("KB600001;echo",)}, {}, "non-empty patch IDs"),
        ({"patch_ids": ("KB600001", "KB600001")}, {}, "bounded set"),
        ({"patch_ids": ("KB-NOT-AVAILABLE",)}, {}, "not available"),
        (
            {"operation": "node_image_upgrade", "inventory_kind": "AKS node"},
            {"inventory_kind": "AKS node"},
            "install_patches only",
        ),
        (
            {"subscription_id": "00000000-0000-0000-0000-000000000002"},
            {},
            "configured subscription",
        ),
        (
            {},
            {"subscription_id": "00000000-0000-0000-0000-000000000002"},
            "configured subscription",
        ),
        (
            {
                "target_id": f"{TARGET_PREFIX}/providers/Microsoft.Compute/virtualMachines/other"
            },
            {},
            "does not match",
        ),
    ],
)
def test_invalid_or_cross_scope_submissions_are_refused_before_http(
    run_overrides: dict[str, object],
    target_overrides: dict[str, object],
    message: str,
) -> None:
    requests: list[httpx.Request] = []
    adapter, _credential = _adapter(
        lambda request: (
            requests.append(request)
            or httpx.Response(202, json={"success": True, "threadId": "unused"})
        )
    )

    with pytest.raises(PatchExecutionUnavailable, match=message) as excinfo:
        run = _run(**run_overrides)
        adapter.submit(run, _target(**target_overrides))

    assert requests == []
    assert excinfo.value.provider_submitted is False


def test_target_outside_configured_prefix_is_refused() -> None:
    requests: list[httpx.Request] = []
    adapter, _credential = _adapter(
        lambda request: (
            requests.append(request)
            or httpx.Response(202, json={"success": True, "threadId": "unused"})
        ),
        target_prefix=f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/other-rg",
    )

    with pytest.raises(PatchExecutionUnavailable, match="outside") as excinfo:
        adapter.submit(_run(), _target())

    assert requests == []
    assert excinfo.value.failure_class == "target_precondition"


def test_payload_bound_rejects_more_than_256_patch_ids() -> None:
    patch_ids = tuple(f"pkg-{index}" for index in range(257))
    target = _target(
        available_patches=tuple(
            AvailablePatch(patch_id=patch_id) for patch_id in patch_ids
        )
    )
    adapter, _credential = _adapter(
        lambda request: httpx.Response(
            202,
            json={"success": True, "threadId": "unused"},
            request=request,
        )
    )

    with pytest.raises(PatchExecutionUnavailable, match="bounded set"):
        adapter.submit(_run(patch_ids=patch_ids), target)


def test_token_failure_is_pre_submit_authorization_failure() -> None:
    requests: list[httpx.Request] = []
    adapter, _credential = _adapter(
        lambda request: (
            requests.append(request)
            or httpx.Response(202, json={"success": True, "threadId": "unused"})
        ),
        credential=_Credential(error=RuntimeError("identity unavailable")),
    )

    with pytest.raises(PatchExecutionUnavailable, match="trigger token") as excinfo:
        adapter.submit(_run(), _target())

    assert requests == []
    assert excinfo.value.provider_submitted is False
    assert excinfo.value.failure_class == "provider_authorization"


def test_empty_token_is_pre_submit_authorization_failure() -> None:
    requests: list[httpx.Request] = []
    adapter, credential = _adapter(
        lambda request: (
            requests.append(request)
            or httpx.Response(202, json={"success": True, "threadId": "unused"})
        ),
        credential=_Credential(token=""),
    )

    with pytest.raises(PatchExecutionUnavailable, match="empty") as excinfo:
        adapter.submit(_run(), _target())

    assert credential.scopes == [(SRE_AGENT_TRIGGER_SCOPE,)]
    assert requests == []
    assert excinfo.value.provider_submitted is False
    assert excinfo.value.failure_class == "provider_authorization"


@pytest.mark.parametrize(
    ("status", "payload", "failure_class"),
    [
        (403, {"error": "forbidden"}, "provider_authorization"),
        (409, {"error": "conflict"}, "provider_rejected"),
        (408, {"error": "timeout"}, "submission_ambiguous"),
        (429, {"error": "busy"}, "provider_transient"),
        (500, {"error": "down"}, "submission_ambiguous"),
        (307, {}, "provider_rejected"),
    ],
)
def test_non_202_responses_are_rejected_without_following_redirects(
    status: int,
    payload: dict[str, object],
    failure_class: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        headers = (
            {"Location": "https://attacker.example/steal"} if status == 307 else {}
        )
        return httpx.Response(status, json=payload, headers=headers, request=request)

    adapter, _credential = _adapter(handler)
    with pytest.raises(PatchExecutionUnavailable) as excinfo:
        adapter.submit(_run(), _target())

    assert len(requests) == 1
    assert excinfo.value.provider_submitted is True
    assert excinfo.value.failure_class == failure_class


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"success": False, "threadId": "thread-123"},
        {"success": True, "threadId": ""},
        {"success": "true", "threadId": "thread-123"},
    ],
)
def test_accepted_response_requires_true_success_and_thread_id(
    payload: dict[str, object],
) -> None:
    adapter, _credential = _adapter(
        lambda request: httpx.Response(202, json=payload, request=request)
    )

    with pytest.raises(PatchExecutionUnavailable, match="thread handle") as excinfo:
        adapter.submit(_run(), _target())

    assert excinfo.value.provider_submitted is True
    assert excinfo.value.failure_class == "submission_ambiguous"


def test_accepted_non_json_response_is_submission_ambiguous() -> None:
    adapter, _credential = _adapter(
        lambda request: httpx.Response(202, text="accepted", request=request)
    )

    with pytest.raises(PatchExecutionUnavailable, match="unreadable") as excinfo:
        adapter.submit(_run(), _target())

    assert excinfo.value.provider_submitted is True
    assert excinfo.value.failure_class == "submission_ambiguous"


def test_transport_failure_after_post_is_submission_ambiguous() -> None:
    sentinel = "sentinel-adapter-bearer"
    adapter, credential = _adapter(
        lambda request: (_ for _ in ()).throw(
            httpx.ReadTimeout("response lost", request=request)
        ),
        credential=_Credential(token=sentinel),
    )

    with pytest.raises(PatchExecutionUnavailable) as excinfo:
        adapter.submit(_run(), _target())

    assert credential.scopes == [(SRE_AGENT_TRIGGER_SCOPE,)]
    assert excinfo.value.provider_submitted is True
    assert excinfo.value.failure_class == "submission_ambiguous"
    _assert_sanitized_exception(excinfo.value, sentinel)


@pytest.mark.parametrize(
    "url",
    [
        "http://sre.example/api/v1/httptriggers/trigger/id",
        "https://user:pass@sre.example/api/v1/httptriggers/trigger/id",
        "https://sre.example/api/v1/httptriggers/trigger/",
        "https://sre.example/api/v1/httptriggers/trigger/id?secret=value",
    ],
)
def test_trigger_url_must_be_a_single_https_trigger(url: str) -> None:
    with pytest.raises(ValueError):
        SreAgentPatchExecutionAdapter(
            _Credential(),
            trigger_url=url,
            trigger_id=TRIGGER_ID,
            trigger_origin=TRIGGER_ORIGIN,
            agent_endpoint=AGENT_ENDPOINT,
            subscription_id=SUBSCRIPTION_ID,
            target_prefix=TARGET_PREFIX,
        )


@pytest.mark.parametrize(
    ("subscription_id", "target_prefix"),
    [
        ("sub-1", TARGET_PREFIX),
        (SUBSCRIPTION_ID, f"/subscriptions/{SUBSCRIPTION_ID}"),
        (
            SUBSCRIPTION_ID,
            (
                "/subscriptions/00000000-0000-0000-0000-000000000002/"
                "resourceGroups/rg-prod"
            ),
        ),
    ],
)
def test_configuration_requires_one_guid_and_narrow_matching_prefix(
    subscription_id: str,
    target_prefix: str,
) -> None:
    with pytest.raises(ValueError):
        SreAgentPatchExecutionAdapter(
            _Credential(),
            trigger_url=TRIGGER_URL,
            trigger_id=TRIGGER_ID,
            trigger_origin=TRIGGER_ORIGIN,
            agent_endpoint=AGENT_ENDPOINT,
            subscription_id=subscription_id,
            target_prefix=target_prefix,
        )


@pytest.mark.parametrize(
    "trigger_origin",
    [
        "https://other.example.sre.azure.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://[::1]",
        "https://user@trigger.example.sre.azure.com",
        "https://trigger.example.sre.azure.com:8443",
        "https://trigger.example.sre.azure.com/unexpected-path",
    ],
)
def test_trigger_url_must_match_independent_public_trigger_origin(
    trigger_origin: str,
) -> None:
    with pytest.raises(ValueError):
        SreAgentPatchExecutionAdapter(
            _Credential(),
            trigger_url=TRIGGER_URL,
            trigger_id=TRIGGER_ID,
            trigger_origin=trigger_origin,
            agent_endpoint=AGENT_ENDPOINT,
            subscription_id=SUBSCRIPTION_ID,
            target_prefix=TARGET_PREFIX,
        )


def test_trigger_and_thread_origins_are_independently_pinned() -> None:
    adapter, _credential = _adapter(
        lambda request: httpx.Response(
            202,
            json={"success": True, "threadId": "thread-123"},
            request=request,
        )
    )

    result = adapter.submit(_run(), _target())

    assert result.provider_job_id.startswith(f"{AGENT_ENDPOINT}/api/v1/threads/")


def test_same_origin_wrong_trigger_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="trigger ID"):
        SreAgentPatchExecutionAdapter(
            _Credential(),
            trigger_url=TRIGGER_URL,
            trigger_id="different-trigger-id",
            trigger_origin=TRIGGER_ORIGIN,
            agent_endpoint=AGENT_ENDPOINT,
            subscription_id=SUBSCRIPTION_ID,
            target_prefix=TARGET_PREFIX,
        )


def test_trigger_id_whitespace_is_not_normalized() -> None:
    with pytest.raises(ValueError, match="trigger ID"):
        SreAgentPatchExecutionAdapter(
            _Credential(),
            trigger_url=TRIGGER_URL,
            trigger_id=f" {TRIGGER_ID} ",
            trigger_origin=TRIGGER_ORIGIN,
            agent_endpoint=AGENT_ENDPOINT,
            subscription_id=SUBSCRIPTION_ID,
            target_prefix=TARGET_PREFIX,
        )


@pytest.mark.parametrize(
    "target_id",
    [
        f"{VM_ID}/extensions/monitor",
        (
            f"{TARGET_PREFIX}/providers/Microsoft.Compute/virtualMachines/"
            "vm-payments/runCommands/patch"
        ),
        f"{VM_ID}?api-version=2024-07-01",
        f"{VM_ID}/",
        VM_ID.replace("/providers/", "//providers/"),
    ],
)
def test_child_resource_targets_are_refused(target_id: str) -> None:
    adapter, _credential = _adapter(
        lambda request: httpx.Response(
            202,
            json={"success": True, "threadId": "unused"},
            request=request,
        )
    )

    with pytest.raises(PatchExecutionUnavailable, match="target"):
        adapter.submit(
            _run(target_id=target_id),
            _target(target_id=target_id),
        )
