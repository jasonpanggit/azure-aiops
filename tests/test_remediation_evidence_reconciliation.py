"""Evidence reconciliation and ambiguous-submission reconciliation.

Recommendation 3's Evidence Reconciliation decision: a verified-succeeded
patch execution's immutable selected KB set must be compared against a
freshly refreshed live target assessment before the remediation is ever
reported "clean" -- Azure's own provider-level success is preserved
separately, never silently upgraded to "the KB is actually gone". A
submission-ambiguous failed execution stays retry/supersede-refused only
until either proof of success or a bounded reconciliation deadline passes,
never permanently.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from intelligence.remediation.approval_decisions import execution_snapshot_hash
from intelligence.remediation.execution_service import (
    VERIFICATION_DEADLINE_SECONDS,
    RemediationExecutionError,
    RemediationExecutionService,
)
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.plan_repository import PlanRepository
from operations.patching.adapters import PatchExecutionResult, PatchExecutionUnavailable
from operations.patching.service import PatchingService

TARGET_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


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
                "missing_kbs": ["1111111", "2222222"],
                "severities": ["Critical"],
                "cve_ids": ["CVE-2026-0001"],
            }
        ]


class _OperationUrlAdapter:
    name = "recording-with-operation-url"

    def __init__(self) -> None:
        self.submissions: list = []

    def submit(self, run, target) -> PatchExecutionResult:
        self.submissions.append((run, target))
        return PatchExecutionResult(
            provider=self.name,
            provider_job_id="https://management.azure.com/op/1",
            state="submitted",
            message="Accepted by Azure; Update Manager is authoritative for the outcome.",
        )


class _SreOperationUrlAdapter(_OperationUrlAdapter):
    name = "sre-agent"


class _AmbiguousAdapter:
    """Raises the exact PatchExecutionUnavailable an ambiguous transport
    failure produces -- provider_submitted True, failure_class
    submission_ambiguous."""

    def __init__(self, name: str = "ambiguous") -> None:
        self.name = name

    def submit(self, run, target) -> PatchExecutionResult:
        raise PatchExecutionUnavailable(
            "Azure Resource Manager was unreachable while submitting",
            provider_submitted=True,
            failure_class="submission_ambiguous",
        )


class _StubVerifier:
    """Reports a fixed outcome regardless of the record it is asked about."""

    def __init__(self, outcome: dict) -> None:
        self._outcome = outcome

    def verify(self, execution_record: dict) -> dict:
        return self._outcome


def _plan(**overrides) -> dict:
    plan = {
        "plan_id": "RMP-EVIDENCE-0001",
        "action_id": "controlled-patch-recovery",
        "opportunity_type": "Patch and vulnerability debt",
        "action_version": "v1",
        "resource_key": TARGET_ID,
        "resource": {
            "id": TARGET_ID,
            "name": "vm-payments",
            "entity_type": "VirtualMachine",
            "subscription_id": "sub-1",
        },
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


def _approved_repository(plan: dict, *, patch_ids=("1111111", "2222222")) -> PlanRepository:
    repository = PlanRepository()
    repository.replace_generation([plan])
    snapshot = {
        "target_id": TARGET_ID,
        "patch_ids": list(patch_ids),
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
    return repository


def _succeeded_service(
    *,
    refresher=None,
    deadline_seconds: float = VERIFICATION_DEADLINE_SECONDS,
    patch_ids=("1111111", "2222222"),
    adapter=None,
) -> tuple[RemediationExecutionService, RemediationExecutionStore, str]:
    plan = _plan()
    store = RemediationExecutionStore()
    repository = _approved_repository(plan, patch_ids=patch_ids)
    patching_service = PatchingService(
        _FakeVulnerabilityService(),
        adapter=adapter or _OperationUrlAdapter(),
        require_human_approval=False,
    )
    verification_evidence = (
        {"provider_operation": {"operation_id": "provider-operation-1"}}
        if getattr(patching_service, "adapter_name", "") == "sre-agent"
        else {}
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        execution_verifier=_StubVerifier(
            {
                "verifiable": True,
                "outcome": "succeeded",
                "verified_state": "Succeeded",
                "verification_evidence": verification_evidence,
            }
        ),
        target_evidence_refresher=refresher,
        verification_deadline_seconds=deadline_seconds,
        now=lambda: NOW,
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    polled = service.poll_verification(result["execution_id"])
    assert polled["status"] == "succeeded"
    return service, store, polled["execution_id"]


def _ambiguous_service(
    *,
    refresher=None,
    deadline_seconds: float = VERIFICATION_DEADLINE_SECONDS,
    patch_ids=("1111111", "2222222"),
    adapter=None,
) -> tuple[RemediationExecutionService, RemediationExecutionStore, str]:
    plan = _plan(plan_id="RMP-EVIDENCE-AMBIGUOUS")
    store = RemediationExecutionStore()
    repository = _approved_repository(plan, patch_ids=patch_ids)
    patching_service = PatchingService(
        _FakeVulnerabilityService(),
        adapter=adapter or _AmbiguousAdapter(),
        require_human_approval=False,
    )
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=patching_service,
        execution_store=store,
        target_evidence_refresher=refresher,
        verification_deadline_seconds=deadline_seconds,
        now=lambda: NOW,
    )
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"
    return service, store, result["execution_id"]


# ---------------------------------------------------------------------------
# Task 2: reconcile_evidence
# ---------------------------------------------------------------------------


def test_reconcile_evidence_incomplete_when_selected_kbs_remain():
    calls: list = []

    def refresher(subscription_id, target_id):
        calls.append((subscription_id, target_id))
        return {"missing_kbs": ["2222222"], "assessed_at": "2026-09-04T12:05:00+00:00"}

    service, store, execution_id = _succeeded_service(refresher=refresher)

    result = service.reconcile_evidence(execution_id)

    assert calls == [("sub-1", TARGET_ID)]
    assert result["status"] == "succeeded"
    assert result["evidence_reconciliation"] == {
        "status": "reconciled_incomplete",
        "kbs_cleared": ["1111111"],
        "kbs_remaining": ["2222222"],
        "assessed_at": "2026-09-04T12:05:00+00:00",
    }
    assert store.get(execution_id)["evidence_reconciliation"]["status"] == "reconciled_incomplete"


def test_reconcile_evidence_clean_when_no_selected_kbs_remain():
    def refresher(subscription_id, target_id):
        return {"missing_kbs": [], "assessed_at": "2026-09-04T12:05:00+00:00"}

    service, _store, execution_id = _succeeded_service(refresher=refresher)

    result = service.reconcile_evidence(execution_id)

    assert result["evidence_reconciliation"] == {
        "status": "reconciled_clean",
        "kbs_cleared": ["1111111", "2222222"],
        "kbs_remaining": [],
        "assessed_at": "2026-09-04T12:05:00+00:00",
    }


@pytest.mark.parametrize(
    "assessed_at",
    [
        (NOW - timedelta(seconds=1)).isoformat(),
        NOW.isoformat(),
        NOW.replace(tzinfo=None).isoformat(),
        "not-a-time",
        "",
    ],
)
def test_sre_reconciliation_stays_pending_without_post_terminal_evidence(
    assessed_at: str,
):
    def refresher(subscription_id, target_id):
        return {
            "missing_kbs": [],
            "assessed_at": assessed_at,
            "target_observed": True,
        }

    service, _store, execution_id = _succeeded_service(
        refresher=refresher,
        adapter=_SreOperationUrlAdapter(),
    )
    service._now = lambda: NOW + timedelta(seconds=5)

    result = service.reconcile_evidence(execution_id)

    assert result["status"] == "succeeded"
    assert result["evidence_reconciliation"]["status"] == "pending"
    assert result["evidence_reconciliation"]["kbs_remaining"] == [
        "1111111",
        "2222222",
    ]
    assert result["retryable"] is False
    assert result["supersedable"] is False


def test_sre_unproven_completion_persists_ambiguity_recovery_guards():
    plan = _plan(plan_id="RMP-SRE-UNPROVEN-COMPLETE")
    store = RemediationExecutionStore()
    repository = _approved_repository(plan)
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=PatchingService(
            _FakeVulnerabilityService(),
            adapter=_SreOperationUrlAdapter(),
            require_human_approval=False,
        ),
        execution_store=store,
        execution_verifier=_StubVerifier(
            {
                "verifiable": True,
                "outcome": "failed",
                "verified_state": "CompleteWithoutSubmissionProof",
                "failure_class": "submission_ambiguous",
                "failure_details": "Exact write submission was not proven.",
                "verification_evidence": {"thread_status": "Complete"},
            }
        ),
        now=lambda: NOW,
    )
    submitted = service.execute(
        plan["plan_id"],
        requested_by="operator@example.com",
    )

    result = service.poll_verification(submitted["execution_id"])

    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"
    assert result["retryable"] is False
    assert result["supersede_ineligibility_reason"] == "submission_ambiguous"


def test_sre_reconciliation_accepts_evidence_after_terminal_completion():
    def refresher(subscription_id, target_id):
        return {
            "missing_kbs": [],
            "assessed_at": (NOW + timedelta(seconds=1)).isoformat(),
            "target_observed": True,
        }

    service, _store, execution_id = _succeeded_service(
        refresher=refresher,
        adapter=_SreOperationUrlAdapter(),
    )
    service._now = lambda: NOW + timedelta(seconds=5)

    result = service.reconcile_evidence(execution_id)

    assert result["evidence_reconciliation"]["status"] == "reconciled_clean"


def test_sre_recovered_patch_installation_accepts_same_activity_assessment():
    def refresher(subscription_id, target_id):
        return {
            "missing_kbs": [],
            "assessed_at": "2026-09-04T12:01:00+00:00",
            "target_observed": True,
        }

    service, store, execution_id = _succeeded_service(
        refresher=refresher,
        adapter=_SreOperationUrlAdapter(),
    )
    record = store.get(execution_id)
    record["verification_evidence"] = {
        "provider_operation": {"operation_id": "provider-operation-1"},
        "patch_installation_recovery": {
            "patch_installation": {
                "result_id": "provider-operation-1",
                "start_time": "2026-09-04T12:00:30+00:00",
                "last_modified": "2026-09-04T12:01:00+00:00",
                "child_patch_ids": ["1111111", "2222222"],
            }
        },
    }
    store.update(
        execution_id,
        actor="test",
        verification_evidence=record["verification_evidence"],
    )
    service._now = lambda: NOW + timedelta(seconds=5)

    result = service.reconcile_evidence(execution_id)

    assert result["evidence_reconciliation"] == {
        "status": "reconciled_clean",
        "kbs_cleared": ["1111111", "2222222"],
        "kbs_remaining": [],
        "assessed_at": "2026-09-04T12:01:00+00:00",
    }


def test_sre_recovered_patch_installation_rejects_pre_install_assessment():
    def refresher(subscription_id, target_id):
        return {
            "missing_kbs": [],
            "assessed_at": "2026-09-04T12:00:59+00:00",
            "target_observed": True,
        }

    service, store, execution_id = _succeeded_service(
        refresher=refresher,
        adapter=_SreOperationUrlAdapter(),
    )
    record = store.get(execution_id)
    record["verification_evidence"] = {
        "provider_operation": {"operation_id": "provider-operation-1"},
        "patch_installation_recovery": {
            "patch_installation": {
                "result_id": "provider-operation-1",
                "start_time": "2026-09-04T12:00:30+00:00",
                "last_modified": "2026-09-04T12:01:00+00:00",
                "child_patch_ids": ["1111111", "2222222"],
            }
        },
    }
    store.update(
        execution_id,
        actor="test",
        verification_evidence=record["verification_evidence"],
    )
    service._now = lambda: NOW + timedelta(seconds=5)

    result = service.reconcile_evidence(execution_id)

    assert result["evidence_reconciliation"]["status"] == "pending"
    assert result["evidence_reconciliation"]["kbs_remaining"] == [
        "1111111",
        "2222222",
    ]


def test_non_sre_reconciliation_preserves_existing_timestamp_semantics():
    def refresher(subscription_id, target_id):
        return {
            "missing_kbs": [],
            "assessed_at": (NOW - timedelta(seconds=1)).isoformat(),
            "target_observed": True,
        }

    service, _store, execution_id = _succeeded_service(refresher=refresher)

    result = service.reconcile_evidence(execution_id)

    assert result["evidence_reconciliation"]["status"] == "reconciled_clean"


def test_reconcile_evidence_noop_for_defender_configuration_snapshot():
    store = RemediationExecutionStore()
    record, _ = store.create_or_get(
        "RMP-DEFENDER-EVIDENCE-1",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot={
            "target_id": TARGET_ID,
            "patch_ids": [],
            "target_kind": "",
            "operation": "configure_defender",
            "action_version": "v1",
            "snapshot_hash": "hash-defender",
            "snapshot_kind": "defender_configuration",
        },
        now=NOW,
    )
    succeeded = store.transition(
        record["execution_id"],
        expected_revision=int(record["revision"]),
        expected_status="queued",
        status="succeeded",
        actor="operator@example.com",
        outcome="succeeded",
        now=NOW,
    )
    service = RemediationExecutionService(
        plan_repository=None,
        patching_service=None,
        execution_store=store,
        target_evidence_refresher=lambda s, t: {"missing_kbs": []},
        now=lambda: NOW,
    )

    result = service.reconcile_evidence(record["execution_id"])

    assert result["evidence_reconciliation"]["status"] == ""
    assert store.get(record["execution_id"])["revision"] == int(succeeded["revision"])


def test_reconcile_evidence_noop_for_empty_patch_ids():
    store = RemediationExecutionStore()
    record, _ = store.create_or_get(
        "RMP-EMPTY-EVIDENCE-1",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot={
            "target_id": TARGET_ID,
            "patch_ids": [],
            "target_kind": "Azure VM",
            "operation": "install_patches",
            "action_version": "v1",
            "snapshot_hash": "hash-empty",
        },
        now=NOW,
    )
    succeeded = store.transition(
        record["execution_id"],
        expected_revision=int(record["revision"]),
        expected_status="queued",
        status="succeeded",
        actor="operator@example.com",
        outcome="succeeded",
        now=NOW,
    )
    service = RemediationExecutionService(
        plan_repository=None,
        patching_service=None,
        execution_store=store,
        target_evidence_refresher=lambda s, t: {"missing_kbs": []},
        now=lambda: NOW,
    )

    result = service.reconcile_evidence(record["execution_id"])

    assert result["evidence_reconciliation"]["status"] == ""
    assert store.get(record["execution_id"])["revision"] == int(succeeded["revision"])


def test_reconcile_evidence_noop_once_reconciliation_already_terminal():
    service, store, execution_id = _succeeded_service(
        refresher=lambda s, t: {"missing_kbs": []}
    )
    first = service.reconcile_evidence(execution_id)
    assert first["evidence_reconciliation"]["status"] == "reconciled_clean"
    revision_after_first = int(store.get(execution_id)["revision"])

    second = service.reconcile_evidence(execution_id)

    assert second["evidence_reconciliation"]["status"] == "reconciled_clean"
    assert int(store.get(execution_id)["revision"]) == revision_after_first


def test_reconcile_evidence_pending_when_refresher_unconfigured_within_deadline():
    service, _store, execution_id = _succeeded_service(refresher=None)

    result = service.reconcile_evidence(execution_id)

    assert result["status"] == "succeeded"
    assert result["evidence_reconciliation"]["status"] == "pending"
    assert result["next_verification_at"] > NOW.isoformat()


def test_reconcile_evidence_treats_refresher_exception_like_unavailable():
    def raising_refresher(subscription_id, target_id):
        raise RuntimeError("ARG query failed")

    service, _store, execution_id = _succeeded_service(refresher=raising_refresher)

    result = service.reconcile_evidence(execution_id)

    assert result["evidence_reconciliation"]["status"] == "pending"


def test_reconcile_evidence_unreconciled_when_refresher_unavailable_past_deadline():
    service, _store, execution_id = _succeeded_service(refresher=None, deadline_seconds=60.0)
    service._now = lambda: NOW + timedelta(seconds=120)

    result = service.reconcile_evidence(execution_id)

    assert result["status"] == "succeeded"
    assert result["evidence_reconciliation"]["status"] == "unreconciled"


# ---------------------------------------------------------------------------
# Task 3: reconcile_ambiguous_submission
# ---------------------------------------------------------------------------


def test_reconcile_ambiguous_submission_promotes_to_succeeded_when_proven():
    def refresher(subscription_id, target_id):
        return {"missing_kbs": [], "assessed_at": "2026-09-04T12:10:00+00:00"}

    service, _store, execution_id = _ambiguous_service(refresher=refresher)

    result = service.reconcile_ambiguous_submission(execution_id)

    assert result["status"] == "succeeded"
    assert result["outcome"] == "succeeded"
    assert result["failure_class"] == ""
    assert result["verified_state"] == "reconciled_from_target_evidence"
    assert result["evidence_reconciliation"] == {
        "status": "reconciled_clean",
        "kbs_cleared": ["1111111", "2222222"],
        "kbs_remaining": [],
        "assessed_at": "2026-09-04T12:10:00+00:00",
    }
    assert result["retryable"] is False
    assert result["supersedable"] is False


def test_reconcile_ambiguous_submission_stays_ambiguous_within_deadline_when_unproven():
    def refresher(subscription_id, target_id):
        return {"missing_kbs": ["1111111", "2222222"]}

    service, _store, execution_id = _ambiguous_service(refresher=refresher)

    result = service.reconcile_ambiguous_submission(execution_id)

    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"
    assert result["retryable"] is False
    assert result["supersede_ineligibility_reason"] == "submission_ambiguous"


def test_sre_ambiguous_submission_ignores_pre_submission_target_evidence():
    def refresher(subscription_id, target_id):
        return {
            "missing_kbs": [],
            "assessed_at": (NOW - timedelta(seconds=1)).isoformat(),
            "target_observed": True,
        }

    service, _store, execution_id = _ambiguous_service(
        refresher=refresher,
        adapter=_AmbiguousAdapter(name="sre-agent"),
    )

    result = service.reconcile_ambiguous_submission(execution_id)

    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"
    assert result["retryable"] is False
    assert result["supersede_ineligibility_reason"] == "submission_ambiguous"


def test_reconcile_ambiguous_submission_reclassified_after_deadline_with_no_proof():
    service, _store, execution_id = _ambiguous_service(refresher=None, deadline_seconds=60.0)
    service._now = lambda: NOW + timedelta(seconds=120)

    result = service.reconcile_ambiguous_submission(execution_id)

    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_unconfirmed"
    assert result["verified_state"] == "reconciliation_timed_out"
    assert result["evidence_reconciliation"]["status"] == "unreconciled_timed_out"
    assert result["retryable"] is True
    assert result["supersede_ineligibility_reason"] == ""
    assert result["failure_details"]


def test_sre_ambiguity_remains_non_retryable_after_deadline_without_proof():
    service, store, execution_id = _ambiguous_service(
        refresher=None,
        deadline_seconds=60.0,
        adapter=_AmbiguousAdapter(name="sre-agent"),
    )
    initial = store.get(execution_id)
    assert initial["provider"] == "sre-agent"
    assert initial["attempts"][0]["provider"] == "sre-agent"
    service._now = lambda: NOW + timedelta(seconds=120)

    result = service.reconcile_ambiguous_submission(execution_id)

    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"
    assert result["verified_state"] == "sre_agent_manual_resolution_required"
    assert result["evidence_reconciliation"]["status"] == (
        "unreconciled_manual_resolution"
    )
    assert result["retryable"] is False
    assert result["supersede_ineligibility_reason"] == "submission_ambiguous"
    assert store.list_due_for_verification(now=NOW + timedelta(seconds=180)) == []

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.retry(execution_id)
    assert getattr(excinfo.value, "reason", "") == "submission_ambiguous"

    with pytest.raises(RemediationExecutionError) as supersede_error:
        service.supersede(
            execution_id,
            requested_by="operator@example.com",
            reason="Operator confirmed no recoverable thread handle",
        )
    assert getattr(supersede_error.value, "reason", "") == "submission_ambiguous"
    assert store.get(execution_id)["superseded_by"] == ""


def test_reconcile_ambiguous_submission_skips_refresher_for_defender_configuration():
    calls: list = []

    def refresher(subscription_id, target_id):
        calls.append((subscription_id, target_id))
        return {"missing_kbs": []}

    store = RemediationExecutionStore()
    record, _ = store.create_or_get(
        "RMP-DEFENDER-AMBIGUOUS-1",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot={
            "target_id": TARGET_ID,
            "patch_ids": [],
            "target_kind": "",
            "operation": "configure_defender",
            "action_version": "v1",
            "snapshot_hash": "hash-defender-ambiguous",
            "snapshot_kind": "defender_configuration",
        },
        now=NOW,
    )
    running = store.transition(
        record["execution_id"],
        expected_revision=int(record["revision"]),
        expected_status="queued",
        status="running",
        actor="operator@example.com",
        now=NOW,
    )
    store.transition(
        running["execution_id"],
        expected_revision=int(running["revision"]),
        expected_status="running",
        status="failed",
        actor="operator@example.com",
        outcome="failed",
        failure_details="Azure Resource Manager was unreachable",
        failure_class="submission_ambiguous",
        verification_deadline_at=(NOW + timedelta(seconds=60)).isoformat(),
        next_verification_at=NOW.isoformat(),
        verification_attempts=0,
        now=NOW,
    )
    service = RemediationExecutionService(
        plan_repository=None,
        patching_service=None,
        execution_store=store,
        target_evidence_refresher=refresher,
        verification_deadline_seconds=60.0,
        now=lambda: NOW + timedelta(seconds=120),
    )

    result = service.reconcile_ambiguous_submission(record["execution_id"])

    assert calls == []
    assert result["failure_class"] == "submission_unconfirmed"


# ---------------------------------------------------------------------------
# WR-06: a refresher result must distinguish "target genuinely observed
# clean" from "target not observed at all" (wrong subscription, absent
# target) -- an unconfirmed result must never be treated as "nothing
# missing" for either reconcile_evidence or reconcile_ambiguous_submission.
# ---------------------------------------------------------------------------


def test_reconcile_evidence_wrong_subscription_stays_pending_not_clean():
    """A syntactically valid but *wrong* subscription id still reaches the
    refresher and comes back with an empty `missing_kbs` list -- exactly
    the false-clean shape WR-06 describes. `target_observed=False` must
    keep this pending (never `reconciled_clean`) within the deadline."""

    def refresher(subscription_id, target_id):
        # The live refresher would have queried the wrong subscription and
        # found no matching asset row at all.
        return {"missing_kbs": [], "assessed_at": "2026-09-04T12:05:00+00:00", "target_observed": False}

    service, _store, execution_id = _succeeded_service(refresher=refresher)

    result = service.reconcile_evidence(execution_id)

    assert result["status"] == "succeeded"
    assert result["evidence_reconciliation"]["status"] == "pending"
    assert result["evidence_reconciliation"]["kbs_remaining"] == ["1111111", "2222222"]


def test_reconcile_evidence_wrong_subscription_reaches_unreconciled_after_deadline():
    def refresher(subscription_id, target_id):
        return {"missing_kbs": [], "assessed_at": "", "target_observed": False}

    service, _store, execution_id = _succeeded_service(refresher=refresher, deadline_seconds=60.0)
    service._now = lambda: NOW + timedelta(seconds=120)

    result = service.reconcile_evidence(execution_id)

    assert result["status"] == "succeeded"
    assert result["evidence_reconciliation"]["status"] == "unreconciled"


def test_reconcile_evidence_target_absent_stays_pending_not_clean():
    """A target that genuinely does not exist (never observed, not merely
    the wrong subscription) must be treated identically to the
    wrong-subscription case -- unconfirmed, never clean."""

    def refresher(subscription_id, target_id):
        return {"missing_kbs": [], "target_observed": False}

    service, _store, execution_id = _succeeded_service(refresher=refresher)

    result = service.reconcile_evidence(execution_id)

    assert result["evidence_reconciliation"]["status"] == "pending"


def test_reconcile_evidence_target_observed_with_no_selected_kbs_is_clean():
    """A confirmed observation (`target_observed=True`) with zero
    remaining selected KBs is the genuine clean case WR-06 must still
    allow through unchanged."""

    def refresher(subscription_id, target_id):
        return {"missing_kbs": [], "assessed_at": "2026-09-04T12:05:00+00:00", "target_observed": True}

    service, _store, execution_id = _succeeded_service(refresher=refresher)

    result = service.reconcile_evidence(execution_id)

    assert result["evidence_reconciliation"] == {
        "status": "reconciled_clean",
        "kbs_cleared": ["1111111", "2222222"],
        "kbs_remaining": [],
        "assessed_at": "2026-09-04T12:05:00+00:00",
    }


def test_reconcile_evidence_target_observed_with_kbs_remaining_is_incomplete():
    """A confirmed observation with KBs genuinely still remaining is
    reported incomplete, exactly as before WR-06 -- explicit
    `target_observed=True` must not change this outcome."""

    def refresher(subscription_id, target_id):
        return {"missing_kbs": ["2222222"], "assessed_at": "2026-09-04T12:05:00+00:00", "target_observed": True}

    service, _store, execution_id = _succeeded_service(refresher=refresher)

    result = service.reconcile_evidence(execution_id)

    assert result["evidence_reconciliation"] == {
        "status": "reconciled_incomplete",
        "kbs_cleared": ["1111111"],
        "kbs_remaining": ["2222222"],
        "assessed_at": "2026-09-04T12:05:00+00:00",
    }


def test_reconcile_ambiguous_submission_wrong_subscription_never_promotes_to_succeeded():
    def refresher(subscription_id, target_id):
        return {"missing_kbs": [], "assessed_at": "2026-09-04T12:10:00+00:00", "target_observed": False}

    service, _store, execution_id = _ambiguous_service(refresher=refresher)

    result = service.reconcile_ambiguous_submission(execution_id)

    # Must stay ambiguous within the deadline -- never promoted to
    # "succeeded" on an unconfirmed empty result.
    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"


def test_reconcile_ambiguous_submission_target_absent_never_promotes_to_succeeded():
    def refresher(subscription_id, target_id):
        return {"missing_kbs": [], "target_observed": False}

    service, _store, execution_id = _ambiguous_service(refresher=refresher)

    result = service.reconcile_ambiguous_submission(execution_id)

    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"


def test_reconcile_ambiguous_submission_target_absent_reclassified_after_deadline():
    def refresher(subscription_id, target_id):
        return {"missing_kbs": [], "target_observed": False}

    service, _store, execution_id = _ambiguous_service(refresher=refresher, deadline_seconds=60.0)
    service._now = lambda: NOW + timedelta(seconds=120)

    result = service.reconcile_ambiguous_submission(execution_id)

    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_unconfirmed"
    assert result["evidence_reconciliation"]["status"] == "unreconciled_timed_out"


def test_reconcile_ambiguous_submission_target_observed_with_no_selected_kbs_promotes():
    def refresher(subscription_id, target_id):
        return {"missing_kbs": [], "assessed_at": "2026-09-04T12:10:00+00:00", "target_observed": True}

    service, _store, execution_id = _ambiguous_service(refresher=refresher)

    result = service.reconcile_ambiguous_submission(execution_id)

    assert result["status"] == "succeeded"
    assert result["outcome"] == "succeeded"
    assert result["evidence_reconciliation"]["status"] == "reconciled_clean"


def test_reconcile_ambiguous_submission_target_observed_with_kbs_remaining_stays_ambiguous():
    def refresher(subscription_id, target_id):
        return {"missing_kbs": ["1111111", "2222222"], "target_observed": True}

    service, _store, execution_id = _ambiguous_service(refresher=refresher)

    result = service.reconcile_ambiguous_submission(execution_id)

    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_ambiguous"


# ---------------------------------------------------------------------------
# Task 3: concurrent-claim handling (proven via the shared _transition_or_current
# helper used by poll_verification, reconcile_evidence, and
# reconcile_ambiguous_submission alike)
# ---------------------------------------------------------------------------


def test_transition_or_current_absorbs_claim_conflict_and_returns_current_view():
    service, store, execution_id = _succeeded_service(
        refresher=lambda s, t: {"missing_kbs": []}
    )
    current = store.get(execution_id)
    stale_revision = int(current["revision"]) + 999  # simulates a losing concurrent caller

    result = service._transition_or_current(
        execution_id,
        expected_revision=stale_revision,
        expected_status="succeeded",
        status="succeeded",
        actor="execution-verifier",
        evidence_reconciliation={
            "status": "reconciled_clean",
            "kbs_cleared": [],
            "kbs_remaining": [],
            "assessed_at": "",
        },
    )

    assert result["execution_id"] == execution_id
    assert result["status"] == "succeeded"
    # The losing caller's stale intent never applied -- the record is
    # unchanged from before this call.
    assert int(store.get(execution_id)["revision"]) == int(current["revision"])
    assert store.get(execution_id)["evidence_reconciliation"] == current["evidence_reconciliation"]
