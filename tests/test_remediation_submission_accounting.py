"""Submission-accounting tests (Phase 03.3 Recommendation 2).

Only provider-submitted (or submission-ambiguous) attempts consume the
bounded ``MAX_EXECUTION_ATTEMPTS`` retry budget. A refusal that never
touches Azure -- target revalidation failure, ``PatchValidationError``, or
any adapter exception with ``provider_submitted=False`` -- must never
decrement ``remaining_attempts`` and must never block a subsequent retry.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from intelligence.remediation.approval_decisions import execution_snapshot_hash
from intelligence.remediation.execution_service import (
    MAX_EXECUTION_ATTEMPTS,
    RemediationExecutionError,
    RemediationExecutionService,
)
from intelligence.remediation.execution_store import (
    RemediationExecutionStore,
    is_submission_ambiguous,
    submitted_attempt_count,
)
from intelligence.remediation.execution_verifier import ExecutionVerifier
from intelligence.remediation.plan_repository import PlanRepository
from operations.patching.adapters import PatchExecutionResult, PatchExecutionUnavailable
from operations.patching.service import PatchingService

TARGET_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"
NOW = datetime(2026, 9, 4, tzinfo=UTC)


class _FakeCredential:
    def get_token(self, *scopes, **kwargs):
        return type("Token", (), {"token": "fake-token"})()


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, handler) -> None:
        self._handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._handler(request)


def _client_returning(status_code: int, json_body: dict) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=json_body, request=request)

    return httpx.Client(transport=_FakeTransport(handler))


class _FakeVulnerabilityService:
    """Toggle target presence to drive the target-not-found refusal path."""

    def __init__(self, *, present: bool = True) -> None:
        self.freshness = "2026-09-04T00:00:00Z"
        self._present = present

    def asset_exposures(self, scope=None) -> list[dict]:
        if not self._present:
            return []
        return [
            {
                "asset_id": TARGET_ID,
                "name": "vm-payments",
                "inventory_kind": "Azure VM",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "subscription_id": "sub-1",
                "missing_kbs": ["KB600001"],
                "severities": ["Critical"],
                "cve_ids": ["CVE-2026-0001"],
            }
        ]


class _AlwaysRaisingAdapter:
    """Fake patch execution adapter that raises the same exception every call."""

    name = "always-raising"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.submissions: list = []

    def submit(self, run, target) -> PatchExecutionResult:
        self.submissions.append((run, target))
        raise self._exc


class _AllowAfter:
    """Callable toggle: False for the first ``threshold`` calls, True after."""

    def __init__(self, threshold: int) -> None:
        self._threshold = threshold
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls > self._threshold


def _full_plan(**overrides) -> dict:
    plan = {
        "plan_id": "RMP-ACCOUNTING-1",
        "action_id": "controlled-patch-recovery",
        "opportunity_type": "Patch and vulnerability debt",
        "action_version": "v1",
        "resource_key": TARGET_ID,
        "resource": {"id": TARGET_ID, "name": "vm-payments", "entity_type": "VirtualMachine"},
        "title": "Controlled patch and failed-update recovery",
        "risk_assessment": {"overall_risk": {"level": "High", "drivers": []}},
        "approval_requirements": [],
        "execution_steps": [],
        "application": "Payments API",
        "business_service": "Checkout",
        "business_decision": {
            "disposition": "act_now",
            "business_impact": {"status": "known"},
            "review_requirements": [],
            "unknowns": [],
            "urgency_rationale": {
                "evidence_citations": ["assessment:assess-001"]
            },
        },
        "evidence_citations": [
            {"source_type": "assessment", "source_id": "assess-001"}
        ],
        "rollback_plan": {
            "rollback_actions": ["Restore from last known-good snapshot"],
            "automatic_rollback": False,
            "execution_status": "Not Executed",
        },
    }
    plan.update(overrides)
    return plan


def _approve(repository: PlanRepository, plan: dict, *, approver: str = "approver@example.com") -> None:
    snapshot = {
        "target_id": TARGET_ID,
        "patch_ids": ["KB600001"],
        "target_kind": "Azure VM",
        "operation": "install_patches",
        "action_version": plan["action_version"],
    }
    snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)
    repository.decisions.append(
        plan=plan,
        decision="approved",
        approver=approver,
        reason="Approved for patch recovery",
        scope={},
        action_version=plan["action_version"],
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        execution_snapshot=snapshot,
        now=NOW,
    )


def _service(
    *,
    plan: dict,
    present: bool = True,
    adapter=None,
    approver: str = "approver@example.com",
    require_human_approval: bool = False,
    allow_self_approval=False,
    verifier_client: httpx.Client | None = None,
) -> tuple[RemediationExecutionService, RemediationExecutionStore, PlanRepository]:
    store = RemediationExecutionStore()
    repository = PlanRepository()
    repository.replace_generation([plan])
    _approve(repository, plan, approver=approver)
    patching_service = PatchingService(
        _FakeVulnerabilityService(present=present),
        adapter=adapter or _AlwaysRaisingAdapter(PatchExecutionUnavailable("unused")),
        require_human_approval=require_human_approval,
        allow_self_approval=allow_self_approval,
    )
    verifier = (
        ExecutionVerifier(credential=_FakeCredential(), client=verifier_client)
        if verifier_client is not None
        else None
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        execution_verifier=verifier,
        # Shared gate (Phase 03.5, D-02): mirrors the same policy passed
        # to PatchingService above so the two enforcement points agree by
        # construction for this test's scenarios.
        allow_self_approval=allow_self_approval,
        now=lambda: NOW,
    )
    return service, store, repository


# ---------------------------------------------------------------------------
# Task 1: pre-submission refusals never consume budget
# ---------------------------------------------------------------------------


def test_repeated_pre_submission_refusals_never_consume_budget() -> None:
    """Target never resolves -- three execute/retry cycles never spend budget."""
    plan = _full_plan()
    service, store, _ = _service(plan=plan, present=False)

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert result["status"] == "failed"
    execution_id = result["execution_id"]

    for _ in range(2):
        retried = service.retry(execution_id)
        assert retried["status"] == "failed"

    view = service.execution_view(store.get(execution_id))
    assert view["remaining_attempts"] == 3
    assert view["retryable"] is True

    # claim_retry's own CAS gate also uses submitted_attempt_count, not the
    # raw attempt_count -- a fourth retry must still be permitted.
    fourth = service.retry(execution_id)
    assert fourth["status"] == "failed"
    assert service.execution_view(store.get(execution_id))["remaining_attempts"] == 3


# ---------------------------------------------------------------------------
# Task 2: submitted failures are classified and bounded
# ---------------------------------------------------------------------------


def test_repeated_submitted_failures_exhaust_the_budget() -> None:
    plan = _full_plan()
    adapter = _AlwaysRaisingAdapter(
        PatchExecutionUnavailable(
            "Azure rejected",
            provider_submitted=True,
            failure_class="provider_authorization",
        )
    )
    service, store, _ = _service(plan=plan, present=True, adapter=adapter)

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert result["status"] == "failed"
    execution_id = result["execution_id"]

    service.retry(execution_id)
    service.retry(execution_id)

    view = service.execution_view(store.get(execution_id))
    assert view["remaining_attempts"] == 0
    assert view["retryable"] is False
    assert len(adapter.submissions) == MAX_EXECUTION_ATTEMPTS

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.retry(execution_id)
    assert excinfo.value.reason == "max_attempts_exceeded"


def test_retry_refuses_to_switch_the_persisted_execution_provider() -> None:
    plan = _full_plan(plan_id="RMP-ACCOUNTING-PROVIDER")
    first_adapter = _AlwaysRaisingAdapter(
        PatchExecutionUnavailable(
            "Provider rejected",
            provider_submitted=True,
            failure_class="provider_rejected",
        )
    )
    service, store, _ = _service(
        plan=plan,
        present=True,
        adapter=first_adapter,
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]
    assert store.get(execution_id)["provider"] == "always-raising"
    assert store.get(execution_id)["attempts"][0]["provider"] == "always-raising"

    replacement = _AlwaysRaisingAdapter(
        PatchExecutionUnavailable(
            "Replacement rejected",
            provider_submitted=True,
            failure_class="provider_rejected",
        )
    )
    replacement.name = "replacement-provider"
    service._patching._adapter = replacement

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.retry(execution_id)

    assert excinfo.value.reason == "execution_provider_changed"
    assert replacement.submissions == []

    superseding = service.supersede(
        execution_id,
        requested_by="operator@example.com",
        reason="Move the replacement attempt to the configured provider",
    )
    assert superseding["execution_id"] != execution_id
    assert superseding["provider"] == "replacement-provider"
    assert len(replacement.submissions) == 1


def test_retry_refuses_submitted_legacy_record_without_provider_lineage() -> None:
    plan = _full_plan(plan_id="RMP-ACCOUNTING-NO-PROVIDER")
    adapter = _AlwaysRaisingAdapter(
        PatchExecutionUnavailable(
            "Provider rejected",
            provider_submitted=True,
            failure_class="provider_rejected",
        )
    )
    service, store, _ = _service(plan=plan, present=True, adapter=adapter)
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]
    record = store.get(execution_id)
    store.update(
        execution_id,
        provider="",
        actor="legacy-migration-test",
    )
    assert submitted_attempt_count(record) == 1

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.retry(execution_id)

    assert excinfo.value.reason == "execution_provider_unknown"


# ---------------------------------------------------------------------------
# Task 2b: a submission-ambiguous last attempt blocks ordinary retry (CR-01)
# ---------------------------------------------------------------------------


def test_retry_refuses_a_submission_ambiguous_execution() -> None:
    """`retry()` must never fire a second concurrent Azure request while the
    only attempt's true outcome (accepted-and-running vs. never-arrived) is
    still unknown. Mirrors `test_supersede_refuses_a_submission_ambiguous_execution`
    (`tests/test_remediation_execution_supersede.py`), asserting the ordinary,
    far-more-commonly-reached recovery path is guarded identically."""
    plan = _full_plan()
    adapter = _AlwaysRaisingAdapter(
        PatchExecutionUnavailable(
            "Azure Resource Manager was unreachable: connection reset",
            provider_submitted=True,
            failure_class="submission_ambiguous",
        )
    )
    service, store, _ = _service(plan=plan, present=True, adapter=adapter)

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert result["status"] == "failed"
    execution_id = result["execution_id"]
    assert len(adapter.submissions) == 1
    assert is_submission_ambiguous(store.get(execution_id)) is True

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.retry(execution_id)
    assert excinfo.value.reason == "submission_ambiguous"

    # The adapter must never be reached a second time -- this is the whole
    # point of the guard: a second, genuinely concurrent request against the
    # same target must never fire while the first's outcome is unknown.
    assert len(adapter.submissions) == 1

    # The read-side projection (execution_view, consumed by the API/web
    # contract) must agree with the write-side refusal: it must never
    # advertise `retryable: true` for a record `retry()` would actually
    # refuse, and the ineligibility reason must be the same specific,
    # stable value an operator (or an automated caller) can act on.
    view = service.execution_view(store.get(execution_id))
    assert view["retryable"] is False
    assert view["ineligibility_reason"] == "submission_ambiguous"
    # remaining_attempts still reports > 0 -- the budget genuinely was not
    # exhausted; it's the ambiguity, not the ceiling, that refuses retry.
    assert view["remaining_attempts"] == MAX_EXECUTION_ATTEMPTS - 1

    # A second and third call must remain refused identically -- the guard
    # is not a one-shot side effect.
    for _ in range(2):
        with pytest.raises(RemediationExecutionError) as excinfo:
            service.retry(execution_id)
        assert excinfo.value.reason == "submission_ambiguous"
    assert len(adapter.submissions) == 1


def test_only_the_genuine_submission_counts_after_self_approval_refusals() -> None:
    """Self-approval refusals are now caught by the shared execution gate
    (Phase 03.5, D-02) before any execution record is created at all --
    they consume no budget by construction, since nothing is persisted.
    Only the genuine, provider-reaching submission -- once the policy
    permits self-approval -- creates a counted attempt."""
    plan = _full_plan()
    toggle = _AllowAfter(2)  # False (refused) for the first 2 calls, True after
    adapter = _AlwaysRaisingAdapter(
        PatchExecutionUnavailable(
            "Azure rejected",
            provider_submitted=True,
            failure_class="provider_authorization",
        )
    )
    service, store, _ = _service(
        plan=plan,
        present=True,
        adapter=adapter,
        approver="ops@example.com",
        require_human_approval=True,
        allow_self_approval=toggle,
    )

    # First two attempts: the shared gate refuses self-approval before any
    # execution record exists -- no budget consumed, adapter never reached.
    for _ in range(2):
        with pytest.raises(RemediationExecutionError) as excinfo:
            service.execute(plan["plan_id"], requested_by="ops@example.com")
        assert excinfo.value.reason == "self_approval_not_permitted"
    assert adapter.submissions == []

    # Third attempt: the toggle now permits self-approval, so the gate
    # proceeds to the genuine provider-level rejection -- the one
    # submission that actually counts.
    result = service.execute(plan["plan_id"], requested_by="ops@example.com")
    assert result["status"] == "failed"
    execution_id = result["execution_id"]

    assert len(adapter.submissions) == 1

    view = service.execution_view(store.get(execution_id))
    assert view["remaining_attempts"] == MAX_EXECUTION_ATTEMPTS - 1


def test_verifier_detected_failure_carries_a_non_empty_failure_class() -> None:
    plan = _full_plan()
    adapter_recorder: list = []

    class _RecordingSuccessAdapter:
        name = "recording"

        def submit(self, run, target) -> PatchExecutionResult:
            adapter_recorder.append((run, target))
            return PatchExecutionResult(
                provider=self.name,
                provider_job_id="https://management.azure.com/op/1",
                state="submitted",
                message="Accepted by Azure",
            )

    service, store, _ = _service(
        plan=plan,
        present=True,
        adapter=_RecordingSuccessAdapter(),
        verifier_client=_client_returning(200, {"status": "Failed", "error": {"message": "boom"}}),
    )

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert result["status"] == "running"
    execution_id = result["execution_id"]

    verified = service.poll_verification(execution_id)
    assert verified["status"] == "failed"

    record = store.get(execution_id)
    current_attempt = record["attempts"][-1]
    assert current_attempt["failure_class"] == "provider_rejected"
    assert current_attempt["provider_submitted"] is True


# ---------------------------------------------------------------------------
# Task 3: legacy-compatible defaults for pre-existing execution records
# ---------------------------------------------------------------------------


def _strip_new_fields(path, execution_id: str) -> None:
    """Simulate a pre-migration (schema 2.0.0) row on disk."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    for execution in payload["executions"]:
        if execution["execution_id"] != execution_id:
            continue
        for attempt in execution["attempts"]:
            attempt.pop("provider_submitted", None)
            attempt.pop("failure_class", None)
        execution.pop("provider_submitted", None)
        execution.pop("failure_class", None)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_legacy_attempt_with_provider_job_id_reads_as_submitted(tmp_path) -> None:
    path = tmp_path / "state" / "remediation_executions.json"
    store = RemediationExecutionStore(path=path)
    record, _ = store.create_or_get(
        "RMP-LEGACY-1",
        requested_by="legacy@example.com",
        approved_by="approver@example.com",
        execution_snapshot={
            "target_id": TARGET_ID,
            "patch_ids": ["KB600001"],
            "target_kind": "Azure VM",
            "operation": "install_patches",
            "action_version": "v1",
            "snapshot_hash": "hash-1",
        },
    )
    execution_id = record["execution_id"]
    store.transition(
        execution_id,
        expected_revision=int(record["revision"]),
        expected_status="queued",
        status="running",
        actor="legacy@example.com",
        provider_job_id="https://management.azure.com/op/legacy-1",
    )
    _strip_new_fields(path, execution_id)

    reread = RemediationExecutionStore(path=path).get(execution_id)
    assert submitted_attempt_count(reread) == 1


def test_legacy_attempt_with_ambiguity_marker_reads_as_submitted(tmp_path) -> None:
    path = tmp_path / "state" / "remediation_executions.json"
    store = RemediationExecutionStore(path=path)
    record, _ = store.create_or_get(
        "RMP-LEGACY-2",
        requested_by="legacy@example.com",
        approved_by="approver@example.com",
        execution_snapshot={
            "target_id": TARGET_ID,
            "patch_ids": ["KB600001"],
            "target_kind": "Azure VM",
            "operation": "install_patches",
            "action_version": "v1",
            "snapshot_hash": "hash-2",
        },
    )
    execution_id = record["execution_id"]
    store.transition(
        execution_id,
        expected_revision=int(record["revision"]),
        expected_status="queued",
        status="failed",
        actor="legacy@example.com",
        failure_details="Azure Resource Manager was unreachable: connection refused",
        outcome="failed",
    )
    _strip_new_fields(path, execution_id)

    reread = RemediationExecutionStore(path=path).get(execution_id)
    assert submitted_attempt_count(reread) == 1


def test_legacy_attempt_with_no_marker_reads_as_pre_submission(tmp_path) -> None:
    path = tmp_path / "state" / "remediation_executions.json"
    store = RemediationExecutionStore(path=path)
    record, _ = store.create_or_get(
        "RMP-LEGACY-3",
        requested_by="legacy@example.com",
        approved_by="approver@example.com",
        execution_snapshot={
            "target_id": TARGET_ID,
            "patch_ids": ["KB600001"],
            "target_kind": "Azure VM",
            "operation": "install_patches",
            "action_version": "v1",
            "snapshot_hash": "hash-3",
        },
    )
    execution_id = record["execution_id"]
    store.transition(
        execution_id,
        expected_revision=int(record["revision"]),
        expected_status="queued",
        status="failed",
        actor="legacy@example.com",
        failure_details="This recommendation has no supported direct execution action",
        outcome="failed",
    )
    _strip_new_fields(path, execution_id)

    reread = RemediationExecutionStore(path=path).get(execution_id)
    assert submitted_attempt_count(reread) == 0


# ---------------------------------------------------------------------------
# Plan 03.4-02 Task 3: ambiguous-submission reconciliation preserves the
# existing submission-accounting budget -- reconciliation reclassifies
# failure_class, it never mints a new attempt and never changes
# submitted_attempt_count.
# ---------------------------------------------------------------------------


def test_ambiguous_reconciliation_reclassification_does_not_change_submitted_count() -> None:
    plan = _full_plan(plan_id="RMP-ACCOUNTING-AMBIGUOUS")
    adapter = _AlwaysRaisingAdapter(
        PatchExecutionUnavailable(
            "Azure Resource Manager was unreachable",
            provider_submitted=True,
            failure_class="submission_ambiguous",
        )
    )
    service, store, _ = _service(plan=plan, present=True, adapter=adapter)
    service._verification_deadline_seconds = 60.0

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"
    execution_id = result["execution_id"]
    before = submitted_attempt_count(store.get(execution_id))
    assert before == 1
    assert is_submission_ambiguous(store.get(execution_id)) is True

    service._now = lambda: NOW + timedelta(seconds=120)
    reconciled = service.reconcile_ambiguous_submission(execution_id)

    assert reconciled["failure_class"] == "submission_unconfirmed"
    after = submitted_attempt_count(store.get(execution_id))
    assert after == before == 1
    assert is_submission_ambiguous(store.get(execution_id)) is False
    assert reconciled["retryable"] is True
