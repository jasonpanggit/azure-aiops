"""Regression coverage for 03.4-REVIEW.md's Critical/Warning findings.

Each test here reproduces the exact failure mode the review demonstrated
(crash-window CR-01, empty-subscription CR-02, pending-patch WR-01,
Defender-configuration envelope-status WR-02, coordinator-construction
WR-03, CAS-contention WR-04, cross-thread cache WR-05) and proves the fix
closes it, independent of the surrounding CONTEXT.md-driven happy-path
suites (``test_remediation_verification_scheduling.py``,
``test_remediation_evidence_reconciliation.py``,
``test_remediation_verification_coordinator.py``,
``test_remediation_execution_verifier.py``).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from api.app import create_app
from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.runtime import build_context
from api.telemetry import ApiTelemetry
from intelligence.remediation.approval_decisions import execution_snapshot_hash
from intelligence.remediation.execution_service import (
    RemediationExecutionError,
    RemediationExecutionService,
)
from intelligence.remediation.execution_store import (
    ExecutionLockContended,
    RemediationExecutionStore,
)
from intelligence.remediation.execution_verifier import (
    ExecutionVerificationUnavailable,
    ExecutionVerifier,
)
from intelligence.remediation.plan_repository import PlanRepository
from intelligence.remediation.sre_agent_verifier import SreAgentExecutionVerifier
from intelligence.remediation.verification_coordinator import (
    RemediationVerificationCoordinator,
)
from onboarding.local_seed import DEFAULT_LOCAL_SUBSCRIPTION_ID, seed_local_environment
from onboarding.service import SubscriptionOnboardingService
from operations.patching.adapters import RecordingPatchExecutionAdapter
from operations.patching.service import PatchingService
from operations.patching.sre_agent_adapter import SRE_AGENT_PROVIDER
from semantic.live_provider import LiveObservation

TARGET_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
TOKENS = '{"demo-token-0123456789abcdef": {"subject": "d@e.com", "grants": [{"role": "admin"}]}}'


class _FakeVulnerabilityService:
    freshness = "2026-09-04T12:00:00Z"

    def asset_exposures(self, scope=None) -> list[dict]:
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


def _full_plan(**overrides) -> dict:
    plan = {
        "plan_id": "RMP-REVIEWFIX-0001",
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
            "urgency_rationale": {"evidence_citations": ["assessment:assess-001"]},
        },
        "evidence_citations": [{"source_type": "assessment", "source_id": "assess-001"}],
        "rollback_plan": {
            "rollback_actions": [],
            "automatic_rollback": False,
            "execution_status": "Not Executed",
        },
    }
    plan.update(overrides)
    return plan


def _approve(repository: PlanRepository, plan: dict) -> None:
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
        approver="approver@example.com",
        reason="Approved for patch recovery",
        scope={},
        action_version=plan["action_version"],
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        execution_snapshot=snapshot,
        now=NOW,
    )


def _execution_snapshot(plan: dict) -> dict:
    snapshot = {
        "target_id": TARGET_ID,
        "patch_ids": ["KB600001"],
        "target_kind": "Azure VM",
        "operation": "install_patches",
        "action_version": plan["action_version"],
    }
    snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)
    return snapshot


def _service_with_store(
    *, execution_store: RemediationExecutionStore | None = None
) -> tuple[RemediationExecutionService, RemediationExecutionStore, dict]:
    plan = _full_plan()
    store = execution_store or RemediationExecutionStore()
    repository = PlanRepository()
    repository.replace_generation([plan])
    _approve(repository, plan)
    patching_service = PatchingService(
        _FakeVulnerabilityService(),
        adapter=RecordingPatchExecutionAdapter(),
        require_human_approval=False,
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        now=lambda: NOW,
    )
    return service, store, plan


def test_execution_passes_exact_durable_approval_to_patch_adapter() -> None:
    service, _store, plan = _service_with_store()

    service.execute(plan["plan_id"], requested_by="operator@example.com")

    run, _target = service._patching._adapter.submissions[0]
    approval = run.details["approval_context"]
    assert approval["decision"] == "approved"
    assert approval["approved_by"] == "approver@example.com"
    assert approval["execution_snapshot"] == _execution_snapshot(plan)
    assert approval["decision_id"].startswith("RMD-")
    assert approval["decided_at"] == NOW.isoformat()
    assert approval["expires_at"] == (NOW + timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# CR-01: verification deadline seeded atomically with the running/retrying
# claim, not one write later -- so no crash window leaves a record
# undeadlined and polling forever.
# ---------------------------------------------------------------------------


def test_execute_crash_between_running_claim_and_submission_seeds_deadline_and_recovers():
    """Reproduces the review's own day-0/1/10/100/1000 trace directly: a
    record transitioned queued->running *outside* of `_submit_and_record`
    (simulating a crash before the adapter is ever called) must not be able
    to sit `status="running"` with an empty deadline forever."""
    service, store, plan = _service_with_store()
    created, claimed = store.create_or_get(
        plan["plan_id"],
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot=_execution_snapshot(plan),
        now=NOW,
    )
    assert claimed

    # Exactly the CAS write `execute()` performs before ever calling
    # `_submit_and_record` -- then stop, as if the process crashed here.
    record = store.transition(
        created["execution_id"],
        expected_revision=int(created["revision"]),
        expected_status="queued",
        status="running",
        actor="operator@example.com",
        **service._claim_schedule_fields(),
    )
    execution_id = record["execution_id"]

    assert record["verification_deadline_at"] != ""
    assert record["next_verification_at"] != ""
    assert record["verification_attempts"] == 0

    for days in (0, 1, 10, 100, 1000):
        service._now = lambda days=days: NOW + timedelta(days=days)
        polled = service.poll_verification(execution_id)

    assert polled["status"] == "failed"
    assert polled["outcome"] == "unknown"
    assert polled["failure_class"] == "verification_timed_out"
    stored = store.get(execution_id)
    assert stored["status"] == "failed"
    assert stored["attempts"][-1]["failure_class"] == "verification_timed_out"


def test_pending_review_thread_stays_active_past_local_deadline() -> None:
    class _PendingReviewVerifier:
        def verify(self, _record):
            return {
                "verifiable": True,
                "outcome": "running",
                "verified_state": "Pending Review",
                "provider_active": True,
                "verification_evidence": {
                    "thread_status": {
                        "last_message_complete": False,
                        "has_critical_actions": True,
                        "has_warning_actions": False,
                        "incident_status": "Active",
                    }
                },
            }

    service, store, plan = _service_with_store()
    service._verifier = _PendingReviewVerifier()
    created, _claimed = store.create_or_get(
        plan["plan_id"],
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot=_execution_snapshot(plan),
        now=NOW,
    )
    running = store.transition(
        created["execution_id"],
        expected_revision=int(created["revision"]),
        expected_status="queued",
        status="running",
        actor="operator@example.com",
        provider="sre-agent",
        provider_job_id="https://sre.example/api/v1/threads/thread-1",
        verification_deadline_at=(NOW - timedelta(seconds=1)).isoformat(),
        next_verification_at=NOW.isoformat(),
        now=NOW,
    )

    result = service.poll_verification(running["execution_id"])

    assert result["status"] == "running"
    assert result["verified_state"] == "Pending Review"
    assert result["retryable"] is False
    assert result["supersedable"] is False
    assert store.get(running["execution_id"])["status"] == "running"


def test_stale_blank_sre_thread_times_out_past_deadline_and_is_not_due() -> None:
    class _BlankReachableVerifier:
        def verify(self, _record):
            return {
                "verifiable": True,
                "outcome": "running",
                "verified_state": "In Progress",
                "provider_active": True,
                "verification_evidence": {
                    "thread_status": {
                        "last_message_complete": True,
                        "has_critical_actions": False,
                        "has_warning_actions": False,
                        "incident_status": "",
                    }
                },
            }

    service, store, plan = _service_with_store()
    service._verifier = _BlankReachableVerifier()
    created, _claimed = store.create_or_get(
        plan["plan_id"],
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot=_execution_snapshot(plan),
        now=NOW,
    )
    running = store.transition(
        created["execution_id"],
        expected_revision=int(created["revision"]),
        expected_status="queued",
        status="running",
        actor="operator@example.com",
        provider=SRE_AGENT_PROVIDER,
        provider_job_id="https://sre.example/api/v1/threads/thread-1",
        verification_deadline_at=(NOW - timedelta(seconds=1)).isoformat(),
        next_verification_at=NOW.isoformat(),
        now=NOW,
    )

    result = service.poll_verification(running["execution_id"])

    assert result["status"] == "failed"
    assert result["outcome"] == "unknown"
    assert result["failure_class"] == "verification_timed_out"
    assert result["verified_state"] == "verification_deadline_exceeded"
    assert result["failure_details"]
    assert result["retryable"] is True
    assert result["supersedable"] is True
    assert running["execution_id"] not in {
        due["execution_id"] for due in store.list_due_for_verification(now=NOW)
    }


def test_unchanged_running_verification_poll_skips_duplicates_but_audits_changes() -> None:
    class _StableRunningVerifier:
        def __init__(self) -> None:
            self.evidence = {"thread_status": "In Progress"}

        def verify(self, _record):
            return {
                "verifiable": True,
                "outcome": "running",
                "verified_state": "In Progress",
                "verification_evidence": self.evidence,
            }

    service, store, plan = _service_with_store()
    verifier = _StableRunningVerifier()
    service._verifier = verifier
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]

    first = service.poll_verification(execution_id)
    after_first = store.get(execution_id)
    history_len = len(after_first["history"])
    transition_len = len(after_first["attempts"][-1]["transitions"])

    second = service.poll_verification(execution_id)
    after_second = store.get(execution_id)

    assert second["status"] == first["status"] == "running"
    assert second["verified_state"] == first["verified_state"] == "In Progress"
    assert second["verification_evidence"] == first["verification_evidence"]
    assert after_second["verification_attempts"] == after_first["verification_attempts"] + 1
    assert after_second["revision"] == after_first["revision"] + 1
    assert len(after_second["history"]) == history_len
    assert len(after_second["attempts"][-1]["transitions"]) == transition_len

    verifier.evidence = {"thread_status": "Waiting for approval"}
    service.poll_verification(execution_id)
    changed = store.get(execution_id)

    assert changed["verification_evidence"] == verifier.evidence
    assert len(changed["history"]) == history_len + 1
    assert len(changed["attempts"][-1]["transitions"]) == transition_len + 1


@pytest.mark.parametrize("mode", ["missing", "unavailable", "not_verifiable"])
def test_unproven_review_thread_times_out_instead_of_running_forever(
    mode: str,
) -> None:
    class _UnavailableVerifier:
        def verify(self, _record):
            if mode == "unavailable":
                raise ExecutionVerificationUnavailable("thread unavailable")
            return {"verifiable": False, "reason": "thread not verifiable"}

    service, store, plan = _service_with_store()
    service._verifier = None if mode == "missing" else _UnavailableVerifier()
    created, _claimed = store.create_or_get(
        plan["plan_id"],
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot=_execution_snapshot(plan),
        now=NOW,
    )
    running = store.transition(
        created["execution_id"],
        expected_revision=int(created["revision"]),
        expected_status="queued",
        status="running",
        actor="operator@example.com",
        provider="sre-agent",
        provider_job_id="https://sre.example/api/v1/threads/thread-1",
        verification_deadline_at=(NOW - timedelta(seconds=1)).isoformat(),
        next_verification_at=NOW.isoformat(),
        now=NOW,
    )

    result = service.poll_verification(running["execution_id"])

    assert result["status"] == "failed"
    assert result["failure_class"] == "verification_timed_out"
    assert result["retryable"] is True
    assert result["supersedable"] is True


def test_retry_crash_between_claim_and_running_transition_seeds_deadline_and_recovers():
    """CR-01's 'worse variant': a crash between `claim_retry()`'s own CAS
    write (status="retrying") and the following retrying->running
    transition must not leave a record invisible to
    `list_due_for_verification`/polling forever."""
    service, store, plan = _service_with_store()
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]
    running = store.get(execution_id)
    assert running["status"] == "running"

    # Force a bounded, retryable failure so a retry would ordinarily be legal.
    store.transition(
        execution_id,
        expected_revision=int(running["revision"]),
        expected_status="running",
        status="failed",
        actor="execution-verifier",
        outcome="failed",
        failure_details="Refused by RBAC",
        failure_class="provider_rejected",
        now=NOW,
    )
    failed = store.get(execution_id)

    # Exactly the CAS write `retry()` performs (claim_retry) -- then stop,
    # as if the process crashed before the following retrying -> running
    # transition ever ran.
    schedule_fields = service._claim_schedule_fields()
    claimed = store.claim_retry(
        execution_id,
        expected_revision=int(failed["revision"]),
        actor="operator@example.com",
        max_attempts=3,
        now=NOW,
        **schedule_fields,
    )

    assert claimed["status"] == "retrying"
    assert claimed["verification_deadline_at"] != ""
    assert claimed["next_verification_at"] != ""

    due_ids = {row["execution_id"] for row in store.list_due_for_verification(now=NOW)}
    assert execution_id in due_ids

    for days in (0, 1, 10, 100, 1000):
        service._now = lambda days=days: NOW + timedelta(days=days)
        polled = service.poll_verification(execution_id)

    assert polled["status"] == "failed"
    assert polled["outcome"] == "unknown"
    assert polled["failure_class"] == "verification_timed_out"
    stored = store.get(execution_id)
    assert stored["status"] == "failed"


def test_run_once_dispatches_retrying_records_to_poll_verification_too():
    """The coordinator must recover a stranded "retrying" record exactly
    like a stranded "running" one, not silently skip it forever."""

    class _FakeStore:
        def __init__(self, due: list[dict]) -> None:
            self._due = due

        def list_due_for_verification(self, *, now):
            return list(self._due)

    class _RecordingService:
        def __init__(self) -> None:
            self.poll_calls: list[str] = []

        def poll_verification(self, execution_id: str) -> dict:
            self.poll_calls.append(execution_id)
            return {}

    due = [{"execution_id": "RME-RETRYING", "status": "retrying", "attempts": []}]
    coordinator = RemediationVerificationCoordinator(
        execution_store=_FakeStore(due), execution_service=_RecordingService()
    )

    summary = coordinator.run_once(NOW)

    assert coordinator._service.poll_calls == ["RME-RETRYING"]
    assert summary == {"processed": 1, "errored": 0, "skipped_contended": 0}


# ---------------------------------------------------------------------------
# CR-02: fail closed on an unresolvable subscription/target scope rather
# than silently querying with it.
# ---------------------------------------------------------------------------


def test_target_evidence_refresher_fails_closed_on_empty_subscription_or_target(
    monkeypatch, tmp_path
):
    """The real `api.runtime` wiring must never reach a live vulnerability
    build for an unresolvable scope -- an empty/blank subscription_id or
    target_id must short-circuit to "unavailable", never "nothing missing"."""
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path / "aiops"))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError(
            "live_vulnerability_service must never be reached for an "
            "unresolvable subscription/target scope (CR-02)"
        )

    monkeypatch.setattr("api.runtime.live_vulnerability_service", _must_not_be_called)

    context = build_context()
    coordinator = context.verification_coordinator_provider()
    refresher = coordinator._service._evidence_refresher

    assert refresher("", TARGET_ID) is None
    assert refresher("   ", TARGET_ID) is None
    assert refresher("sub-1", "") is None
    assert refresher("sub-1", "   ") is None


# ---------------------------------------------------------------------------
# WR-06: the real `_target_evidence_refresher` wiring must distinguish a
# target genuinely observed (clean, or with KBs remaining) from a target
# never observed at all (wrong subscription / absent target) -- exercised
# through the actual `hybrid_vulnerability`/`live_vulnerability_service`
# call chain, not a hand-rolled stub.
# ---------------------------------------------------------------------------


def test_target_evidence_refresher_distinguishes_observed_from_absent_targets(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("AIOPS_HOME", str(tmp_path / "aiops"))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)

    from intelligence.vulnerability.service import VulnerabilityIntelligenceService

    clean_target = TARGET_ID
    dirty_target = (
        "/subscriptions/sub-1/resourcegroups/rg-prod/providers/"
        "microsoft.compute/virtualmachines/vm-dirty"
    )
    absent_target = (
        "/subscriptions/sub-1/resourcegroups/rg-prod/providers/"
        "microsoft.compute/virtualmachines/vm-never-seen"
    )

    def _fake_live_vulnerability_service(
        live_resources,
        *,
        subscription_ids,
        semantic=None,
        network=None,
        build_service,
        snapshot=None,
    ):
        return VulnerabilityIntelligenceService.from_rows(
            findings=[
                {
                    "finding_id": f"{dirty_target}|KB111111|CVE-2026-0001",
                    "server_id": dirty_target,
                    "subscription_id": "sub-1",
                    "missing_kb": "111111",
                    "cve_id": "CVE-2026-0001",
                    "severity": "Critical",
                }
            ],
            freshness="2026-09-04T12:00:00Z",
            # `clean_target` and `dirty_target` were both actually seen in
            # this snapshot's raw Update-Manager rows (one has a genuinely
            # remaining KB, the other was assessed/installed clean);
            # `absent_target` was never observed at all.
            observed_asset_ids=[clean_target, dirty_target],
        )

    monkeypatch.setattr(
        "api.runtime.live_vulnerability_service", _fake_live_vulnerability_service
    )
    monkeypatch.setattr(
        "api.runtime._enrichment_cache",
        lambda _name: SimpleNamespace(
            get_entry=lambda _key: (
                True,
                {
                    "schema_version": "1.0.0",
                    "subscription_ids": ["sub-1"],
                    "observed_at": "2026-09-04T12:00:00Z",
                    "findings": [],
                },
                0.0,
            )
        ),
    )

    context = build_context()
    coordinator = context.verification_coordinator_provider()
    refresher = coordinator._service._evidence_refresher

    # Target observed, with KBs remaining.
    dirty = refresher("sub-1", dirty_target)
    assert dirty == {
        "missing_kbs": ["111111"],
        "assessed_at": "2026-09-04T12:00:00Z",
        "target_observed": True,
    }

    # Target observed, with no selected KBs remaining -- genuinely clean.
    clean = refresher("sub-1", clean_target)
    assert clean == {
        "missing_kbs": [],
        "assessed_at": "2026-09-04T12:00:00Z",
        "target_observed": True,
    }

    # Target never observed at all (covers both "wrong subscription" and
    # "target absent" -- from this refresher's perspective they are the
    # identical "not found in this subscription's snapshot" case): must
    # not be reported as clean.
    absent = refresher("sub-1", absent_target)
    assert absent == {
        "missing_kbs": [],
        "assessed_at": "2026-09-04T12:00:00Z",
        "target_observed": False,
    }


# ---------------------------------------------------------------------------
# WR-01: a non-zero pending_count is material incompleteness, never a clean
# success, even when the envelope/nested status otherwise reads "Succeeded".
# ---------------------------------------------------------------------------


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


def test_verify_succeeded_envelope_with_pending_patches_is_never_clean_success():
    """Reproduces the review's exact numbers: only 3 of 10 selected patches
    installed, 7 still pending, envelope/nested status both "Succeeded"."""
    client = _client_returning(
        200,
        {
            "status": "Succeeded",
            "properties": {
                "status": "Succeeded",
                "installedPatchCount": 3,
                "failedPatchCount": 0,
                "pendingPatchCount": 7,
            },
        },
    )
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(
        {
            "execution_id": "RME-PENDING",
            "provider_job_id": "https://management.azure.com/op/pending",
        }
    )

    assert result["verifiable"] is True
    assert result["outcome"] == "failed"
    assert result["verified_state"] == "succeeded_with_pending_patches"
    evidence = result["verification_evidence"]
    assert evidence["installed_count"] == 3
    assert evidence["failed_count"] == 0
    assert evidence["pending_count"] == 7


# ---------------------------------------------------------------------------
# CR-03: a non-terminal ARM envelope status (e.g. "InProgress") must remain
# "running" even when patch counts show ordinary installed/pending progress
# -- only a *terminal* envelope may reinterpret those counts as
# partial/failed. Getting this wrong makes a genuinely in-progress
# installation immediately retry-eligible while Azure is still actively
# working (double-mutation risk), and burns one of the three bounded retry
# attempts for an operation that never actually failed.
# ---------------------------------------------------------------------------


def test_verify_in_progress_envelope_with_pending_patches_is_still_running():
    """Isolated verifier-level regression: the review's exact numbers
    (installed=3, failed=0, pending=7 of 10 selected) with a genuinely
    non-terminal "InProgress" envelope status must report "running", not a
    terminal failure -- unlike the WR-01 scenario, where the same counts
    accompany an envelope status of "Succeeded"."""
    client = _client_returning(
        200,
        {
            "status": "InProgress",
            "properties": {
                "status": "InProgress",
                "installedPatchCount": 3,
                "failedPatchCount": 0,
                "pendingPatchCount": 7,
            },
        },
    )
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)

    result = verifier.verify(
        {
            "execution_id": "RME-INPROGRESS",
            "provider_job_id": "https://management.azure.com/op/in-progress",
        }
    )

    assert result["verifiable"] is True
    assert result["outcome"] == "running"
    assert result["verified_state"] == "InProgress"


def test_poll_verification_in_progress_envelope_never_transitions_terminal_or_becomes_retry_eligible():
    """End-to-end regression (real ``ExecutionVerifier`` + real
    ``RemediationExecutionService`` + real ``RemediationExecutionStore``, no
    stubs): reproduces CR-03's exact scenario through the same call chain
    the review traced -- ``poll_verification`` must never transition a
    genuinely still-running ARM operation (envelope status "InProgress",
    ordinary mid-flight installed/pending counts) to a terminal outcome,
    across repeated polls, and the record must therefore never become
    eligible for ``retry()`` while Azure is still actively installing
    patches (the exact double-submission risk ``is_submission_ambiguous``'s
    CR-01 guard exists to prevent -- here the risk is a *false* terminal
    transition creating a *new* unguarded path to the same danger)."""
    client = _client_returning(
        200,
        {
            "status": "InProgress",
            "properties": {
                "status": "InProgress",
                "installedPatchCount": 3,
                "failedPatchCount": 0,
                "pendingPatchCount": 7,
            },
        },
    )
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)
    service, store, plan = _service_with_store()
    service._verifier = verifier

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]
    running = store.get(execution_id)
    assert running["status"] == "running"

    # Give the running record a real-looking ARM operation URL so the real
    # verifier actually polls it -- RecordingPatchExecutionAdapter's own
    # "recorded-<run_id>" provider_job_id is not itself a URL; the fake
    # transport above answers identically regardless of the URL polled.
    store.transition(
        execution_id,
        expected_revision=int(running["revision"]),
        expected_status="running",
        status="running",
        actor="operator@example.com",
        provider_job_id="https://management.azure.com/op/still-installing",
    )

    # Repeated polls (simulating the background coordinator checking in
    # over time while Azure is still genuinely mid-installation) must never
    # flip to a terminal outcome.
    for _ in range(3):
        polled = service.poll_verification(execution_id)
        assert polled["status"] == "running"
        assert polled.get("outcome") not in {"failed", "succeeded", "cancelled"}

    stored = store.get(execution_id)
    assert stored["status"] == "running"
    assert stored["verification_attempts"] == 3

    # Never retry-eligible while genuinely still running: because
    # `poll_verification` never mis-transitioned the record to "failed" in
    # the first place, `retry()`'s own terminal-state guard now correctly
    # (and independently) refuses it -- proving no duplicate-retry path was
    # ever opened.
    with pytest.raises(RemediationExecutionError) as exc_info:
        service.retry(execution_id)
    assert exc_info.value.reason == "execution_not_retryable"

    stored_after_retry_attempt = store.get(execution_id)
    assert stored_after_retry_attempt["status"] == "running"
    assert stored_after_retry_attempt["revision"] == stored["revision"]


# ---------------------------------------------------------------------------
# WR-02: Defender-configuration verification must honor the ARM envelope
# status, not only the properties-match heuristic.
# ---------------------------------------------------------------------------


def test_verify_defender_configuration_envelope_failed_is_reported_failed_not_running():
    client = _client_returning(
        200,
        {
            "status": "Failed",
            "error": {"code": "PolicyConflict", "message": "Denied by Azure Policy"},
            "properties": {"enabled": False},
        },
    )
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)
    record = {
        "execution_id": "RME-DEFENDER-FAILED",
        "provider_job_id": "https://management.azure.com/op/defender-1",
        "execution_snapshot": {
            "snapshot_kind": "defender_configuration",
            "desired_properties": {"enabled": True},
        },
    }

    result = verifier.verify(record)

    assert result["outcome"] == "failed"
    assert "PolicyConflict" in result["failure_details"] or "Denied by Azure Policy" in result["failure_details"]


def test_verify_defender_configuration_envelope_cancelled_is_reported_cancelled():
    client = _client_returning(200, {"status": "Canceled", "properties": {"enabled": False}})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)
    record = {
        "execution_id": "RME-DEFENDER-CANCELLED",
        "provider_job_id": "https://management.azure.com/op/defender-2",
        "execution_snapshot": {
            "snapshot_kind": "defender_configuration",
            "desired_properties": {"enabled": True},
        },
    }

    result = verifier.verify(record)

    assert result["outcome"] == "cancelled"


def test_verify_defender_configuration_still_running_when_no_terminal_status_yet():
    """Regression guard: an in-progress (non-terminal) envelope status must
    still fall through to the properties-match heuristic exactly as before
    WR-02's fix -- only a terminally failed/cancelled envelope short-circuits."""
    client = _client_returning(200, {"status": "InProgress", "properties": {"enabled": False}})
    verifier = ExecutionVerifier(credential=_FakeCredential(), client=client)
    record = {
        "execution_id": "RME-DEFENDER-PENDING",
        "provider_job_id": "https://management.azure.com/op/defender-3",
        "execution_snapshot": {
            "snapshot_kind": "defender_configuration",
            "desired_properties": {"enabled": True},
        },
    }

    result = verifier.verify(record)

    assert result["outcome"] == "running"
    assert result["verified_state"] == "configuration_pending"


# ---------------------------------------------------------------------------
# WR-03: the coordinator's one-time construction call must be guarded like
# every per-pass call inside its own loop.
# ---------------------------------------------------------------------------


def test_start_verification_coordinator_construction_failure_does_not_crash_app_startup(
    tmp_path,
):
    def _raising_provider():
        raise RuntimeError("simulated construction failure")

    context = ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {"placeholder-token-0123456789abcdef": Principal(subject="operator@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
        verification_coordinator_provider=_raising_provider,
    )

    app = create_app(context)

    assert app is not None
    assert getattr(app.state, "verification_coordinator_thread", None) is None


# ---------------------------------------------------------------------------
# WR-04: legitimate multi-replica CAS-lock contention must be counted
# separately from a genuine defect, never folded into "errored".
# ---------------------------------------------------------------------------


def test_claim_lock_contention_raises_execution_lock_contended(monkeypatch, tmp_path):
    """Simulates another replica holding the cross-process claim lock for
    the entire retry window, deterministically (no real 5s sleep)."""
    import intelligence.remediation.execution_store as execution_store_module

    store = RemediationExecutionStore(path=tmp_path / "state" / "remediation_executions.json")
    record = store.create("RMP-CONTENDED-1", requested_by="operator@example.com")

    def _always_busy(self):
        raise RuntimeError("lock busy")

    monkeypatch.setattr(execution_store_module.RunLock, "__enter__", _always_busy)
    # First call establishes the deadline (t=0 -> deadline=5.0); the retry
    # loop's own deadline check must observe an elapsed time past it on the
    # very next call, without any real sleep.
    monotonic_values = iter([0.0, 10.0, 10.0, 10.0, 10.0])
    monkeypatch.setattr(
        execution_store_module.time, "monotonic", lambda: next(monotonic_values)
    )
    monkeypatch.setattr(execution_store_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(ExecutionLockContended):
        store.transition(
            record["execution_id"],
            expected_revision=int(record["revision"]),
            expected_status="queued",
            status="running",
            actor="operator@example.com",
        )


def test_run_once_counts_lock_contention_separately_from_errored():
    class _FakeStore:
        def __init__(self, due: list[dict]) -> None:
            self._due = due

        def list_due_for_verification(self, *, now):
            return list(self._due)

    class _ContendedThenOkService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def poll_verification(self, execution_id: str) -> dict:
            self.calls.append(execution_id)
            if execution_id == "RME-CONTENDED":
                raise ExecutionLockContended("lock busy")
            return {}

    due = [
        {"execution_id": "RME-CONTENDED", "status": "running", "attempts": []},
        {"execution_id": "RME-OK", "status": "running", "attempts": []},
    ]
    service = _ContendedThenOkService()
    coordinator = RemediationVerificationCoordinator(
        execution_store=_FakeStore(due), execution_service=service
    )

    summary = coordinator.run_once(NOW)

    # Contention on one record never blocks the next due record.
    assert service.calls == ["RME-CONTENDED", "RME-OK"]
    assert summary == {"processed": 1, "errored": 0, "skipped_contended": 1}


# ---------------------------------------------------------------------------
# WR-05: any cache newly reachable from the background
# remediation-verification-coordinator thread must be thread-safe.
# ---------------------------------------------------------------------------


def test_hybrid_vulnerability_cache_serializes_concurrent_builds_for_same_key(
    monkeypatch, tmp_path
):
    """The background coordinator thread now reads/writes this same
    process-global cache concurrently with request threads via
    `_target_evidence_refresher`. Proves same-key concurrent callers
    serialize on one build (via `_ttl_cache_lock`) instead of each racing a
    competing build that could silently overwrite the other's write."""
    home = tmp_path / "aiops-local"
    seed_local_environment(root=home, fixture="tests/fixtures/mock_arg_responses.json")
    monkeypatch.setenv("AIOPS_HOME", str(home))
    monkeypatch.setenv("AIOPS_API_AUTH", "token")
    monkeypatch.setenv("AIOPS_API_TOKENS", TOKENS)
    monkeypatch.setenv("AIOPS_RUNTIME_MODE", "demo")

    # `hybrid_vulnerability` calls `hybrid_network` first, which needs a
    # working ARG-reader per connection; the seeded local fixture's
    # connection uses a "local_fixture" credential kind the real ARG client
    # builder does not support. Only `hybrid_vulnerability`'s own cache
    # locking is under test here, so the underlying live resource query is
    # faked out to a fast, deterministic empty result -- no real Azure/ARG
    # call, no dependency on credential resolution.
    monkeypatch.setattr(
        "semantic.live_provider.ConnectionScopedLiveResourceProvider.query",
        lambda self, spec, *, subscription_ids: LiveObservation((), ""),
    )

    build_calls = {"count": 0}
    build_entered = threading.Event()
    release_build = threading.Event()

    class _FakeVulnerabilityServiceStub:
        freshness = "2026-01-01T00:00:00Z"

        def asset_exposures(self, scope=None):
            return []

    def _fake_live_vulnerability_service(*args, **kwargs):
        build_calls["count"] += 1
        build_entered.set()
        assert release_build.wait(timeout=5), "build was never released"
        return _FakeVulnerabilityServiceStub()

    monkeypatch.setattr(
        "api.runtime.live_vulnerability_service", _fake_live_vulnerability_service
    )

    context = build_context()
    original_get = context.provider_runtime.get
    graph_resolution_modes: list[bool] = []

    def tracked_get(name: str, *, optional: bool = False):
        if name == "semantic_graph":
            graph_resolution_modes.append(optional)
        return original_get(name, optional=optional)

    monkeypatch.setattr(context.provider_runtime, "get", tracked_get)
    subscription_ids = [DEFAULT_LOCAL_SUBSCRIPTION_ID]

    results: list = []
    first_thread = threading.Thread(
        target=lambda: results.append(
            context.hybrid_vulnerability_provider(subscription_ids)
        )
    )
    first_thread.start()
    assert build_entered.wait(timeout=5), "first caller never entered build"

    second_thread = threading.Thread(
        target=lambda: results.append(
            context.hybrid_vulnerability_provider(subscription_ids)
        )
    )
    second_thread.start()
    second_thread.join(timeout=0.2)
    assert second_thread.is_alive(), (
        "second caller did not block behind the in-flight build for the same key"
    )

    release_build.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()

    assert build_calls["count"] == 1
    assert len(results) == 2
    assert results[0] is results[1]
    assert graph_resolution_modes
    assert all(graph_resolution_modes)


# ---------------------------------------------------------------------------
# Live regression (RME-D7CEC1940ECEC97C / provider thread
# 26937248-4e53-4205-84d7-527477354736): a composite SRE Agent thread whose
# only "completion" signal is ``lastMessage.isComplete`` is still active.
# ---------------------------------------------------------------------------


_LIVE_SRE_AGENT_ENDPOINT = "https://sre-agent.example.azure.com"
_LIVE_SRE_THREAD_URL = (
    f"{_LIVE_SRE_AGENT_ENDPOINT}/api/v1/threads/"
    "26937248-4e53-4205-84d7-527477354736"
)
_LIVE_SRE_THREAD_PAYLOAD = {
    "status": {
        "actionsStatus": {"hasCriticalActions": False, "hasWarningActions": False},
        "incidentStatus": {"incidentId": "", "status": ""},
    },
    "lastMessage": {"isComplete": True},
}


def test_message_complete_sre_thread_never_transitions_terminal_or_unlocks_recovery():
    """End-to-end regression with the real ``SreAgentExecutionVerifier``, the
    real ``RemediationExecutionService`` and the real store: the production
    composite polled at 2026-09-16T23:44:44Z (clear action flags, empty
    incident status, ``lastMessage.isComplete=true``) must stay ``running``
    across repeated polls, because that same thread went on to read
    applicability at 23:45:42 and present its single Review command at
    23:45:57. A false terminal transition there would open retry and
    supersession while the original Review command was still approvable."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_LIVE_SRE_THREAD_PAYLOAD, request=request)

    verifier = SreAgentExecutionVerifier(
        credential=_FakeCredential(),
        agent_endpoint=_LIVE_SRE_AGENT_ENDPOINT,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    service, store, plan = _service_with_store()
    service._verifier = verifier

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]
    running = store.get(execution_id)
    store.transition(
        execution_id,
        expected_revision=int(running["revision"]),
        expected_status="running",
        status="running",
        actor="operator@example.com",
        provider=SRE_AGENT_PROVIDER,
        provider_job_id=_LIVE_SRE_THREAD_URL,
    )

    for _ in range(3):
        polled = service.poll_verification(execution_id)
        assert polled["status"] == "running"
        assert polled.get("outcome") not in {"failed", "succeeded", "cancelled"}

    stored = store.get(execution_id)
    assert stored["status"] == "running"
    assert stored["verified_state"] == "In Progress"
    assert stored.get("failure_class") in {None, ""}

    with pytest.raises(RemediationExecutionError) as retry_error:
        service.retry(execution_id)
    assert retry_error.value.reason == "execution_not_retryable"

    with pytest.raises(RemediationExecutionError) as supersede_error:
        service.supersede(
            execution_id,
            requested_by="operator@example.com",
            reason="live thread still approvable",
        )
    assert supersede_error.value.reason == "execution_active"

    assert store.get(execution_id)["revision"] == stored["revision"]
