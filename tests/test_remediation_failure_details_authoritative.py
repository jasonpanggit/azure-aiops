"""Failure Details Authoritative Contract (Phase 03.6 UI-SPEC).

Every ``execution_service.py`` call site that transitions an execution to a
terminal ``"failed"`` (or ``"cancelled"``) status must populate
``execution.failure_details`` with a non-empty string -- the Verify step's
pre-/post-submission honesty sentences (Plan 03.6-04) read from this single
field and must never interpolate an empty value. This file exhaustively
enumerates all six such call sites so a future omission fails the suite
instead of silently reintroducing blank copy.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from test_remediation_evidence_reconciliation import NOW as AMBIGUOUS_NOW
from test_remediation_evidence_reconciliation import _ambiguous_service
from test_remediation_execution_service import NOW, _plan, _service_with_store

from intelligence.remediation.execution_service import VERIFICATION_DEADLINE_SECONDS
from operations.patching.adapters import PatchExecutionUnavailable


class _FailingAdapter:
    """Raises PatchExecutionUnavailable on every submit -- pre-submission
    provider-unavailable failure path, already correct today; included as a
    baseline regression guard.
    """

    name = "failing"

    def submit(self, run, target):
        raise PatchExecutionUnavailable("No execution identity configured")


def _retrying_past_deadline():
    """An execution left in ``"retrying"`` (crash between claim_retry() and
    the following ``retrying -> running`` transition), past its
    verification deadline -- mirrors ``poll_verification``'s own CR-01
    docstring scenario.
    """
    plan = _plan()
    service, store = _service_with_store(plan=plan)
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
    store.claim_retry(
        execution_id,
        expected_revision=int(failed["revision"]),
        actor="operator@example.com",
        max_attempts=5,
        now=NOW,
        **schedule_fields,
    )

    service._now = lambda: NOW + timedelta(seconds=VERIFICATION_DEADLINE_SECONDS + 1)
    return service, store, execution_id


def _running_past_deadline():
    plan = _plan()
    service, store = _service_with_store(plan=plan)
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]

    service._now = lambda: NOW + timedelta(seconds=VERIFICATION_DEADLINE_SECONDS + 1)
    return service, store, execution_id


class _FakeTerminalVerifier:
    """An ``ExecutionVerifier`` whose ARM-verified terminal outcome omits
    ``failure_details`` entirely -- reproduces the real implementation gap
    WR-01 identified: the shipped ``ExecutionVerifier`` populates this field
    in the overwhelming majority of cases, but ``poll_verification``'s
    ``"failed"``/``"cancelled"`` branches previously did an unguarded
    pass-through of whatever the verifier returned, silently defaulting to
    ``""`` when the key was absent.
    """

    def __init__(self, outcome: str):
        self._outcome = outcome

    def verify(self, record):
        return {"verifiable": True, "outcome": self._outcome, "verified_state": "Failed"}


def _service_with_terminal_verifier_gap(outcome: str):
    """A running execution whose injected verifier reports a terminal ARM
    outcome (``"failed"`` or ``"cancelled"``) with no ``failure_details``
    key -- the two real call sites (``poll_verification`` lines
    ``result_outcome == "failed"`` / ``== "cancelled"``) WR-01 found
    uncovered by this "exhaustive" suite.
    """
    plan = _plan()
    service, store = _service_with_store(plan=plan)
    result = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = result["execution_id"]

    service._verifier = _FakeTerminalVerifier(outcome)
    return service, store, execution_id


def test_retrying_branch_verification_timed_out_populates_failure_details():
    service, store, execution_id = _retrying_past_deadline()

    polled = service.poll_verification(execution_id)

    assert polled["status"] == "failed"
    assert polled["failure_class"] == "verification_timed_out"
    assert polled["failure_details"]
    assert store.get(execution_id)["failure_details"]


def test_running_branch_verification_timed_out_populates_failure_details():
    service, store, execution_id = _running_past_deadline()

    polled = service.poll_verification(execution_id)

    assert polled["status"] == "failed"
    assert polled["failure_class"] == "verification_timed_out"
    assert polled["failure_details"]
    assert store.get(execution_id)["failure_details"]


def test_reconcile_ambiguous_submission_timeout_populates_failure_details():
    service, _store, execution_id = _ambiguous_service(refresher=None, deadline_seconds=60.0)
    service._now = lambda: AMBIGUOUS_NOW + timedelta(seconds=120)

    result = service.reconcile_ambiguous_submission(execution_id)

    assert result["status"] == "failed"
    assert result["failure_class"] == "submission_unconfirmed"
    assert result["failure_details"]


def test_provider_rejected_failed_backfills_failure_details_when_verifier_omits_it():
    """ARM-verified real terminal ``"failed"`` (``failure_class ==
    "provider_rejected"``) -- the call site WR-01 reproduced against the
    shipped code as returning ``""`` when the injected ``ExecutionVerifier``
    doesn't supply ``failure_details``.
    """
    service, store, execution_id = _service_with_terminal_verifier_gap("failed")

    polled = service.poll_verification(execution_id)

    assert polled["status"] == "failed"
    assert polled["failure_class"] == "provider_rejected"
    assert polled["failure_details"]
    assert store.get(execution_id)["failure_details"]


def test_provider_rejected_cancelled_backfills_failure_details_when_verifier_omits_it():
    """ARM-verified real terminal ``"cancelled"`` -- the sibling call site to
    the ``"failed"`` branch above; same unguarded pass-through gap.
    """
    service, store, execution_id = _service_with_terminal_verifier_gap("cancelled")

    polled = service.poll_verification(execution_id)

    assert polled["status"] == "cancelled"
    assert polled["failure_details"]
    assert store.get(execution_id)["failure_details"]


def test_pre_submission_provider_unavailable_populates_failure_details():
    """Baseline/regression guard: this path was already correct."""
    plan = _plan()
    service, store = _service_with_store(plan=plan, adapter=_FailingAdapter())

    result = service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert result["status"] == "failed"
    assert result["failure_details"]
    assert store.get(result["execution_id"])["failure_details"]


@pytest.mark.parametrize(
    "case",
    [
        "pre_submission",
        "retrying_timeout",
        "running_timeout",
        "ambiguous_reconciliation_timeout",
        "provider_rejected_failed",
        "provider_rejected_cancelled",
    ],
)
def test_exhaustive_terminal_failure_call_sites_populate_failure_details(case):
    """Exhaustive, parametrized regression guard: every
    execution_service.py call site that transitions an execution to
    terminal ``"failed"``/``"cancelled"`` status must populate
    ``failure_details``. A future call site that starts omitting it must
    fail this test, not silently pass.
    """
    if case == "pre_submission":
        # (a) pre-submission provider-unavailable failure via _submit_and_record
        plan = _plan()
        service, _store = _service_with_store(plan=plan, adapter=_FailingAdapter())
        result = service.execute(plan["plan_id"], requested_by="operator@example.com")
        assert result["status"] == "failed"
        assert result["failure_details"]
    elif case == "retrying_timeout":
        # (b) the "retrying"-branch verification_timed_out timeout
        service, _store, execution_id = _retrying_past_deadline()
        polled = service.poll_verification(execution_id)
        assert polled["status"] == "failed"
        assert polled["failure_details"]
    elif case == "running_timeout":
        # (c) the "running"-branch verification_timed_out timeout
        service, _store, execution_id = _running_past_deadline()
        polled = service.poll_verification(execution_id)
        assert polled["status"] == "failed"
        assert polled["failure_details"]
    elif case == "ambiguous_reconciliation_timeout":
        # (d) reconcile_ambiguous_submission's submission_unconfirmed timeout
        service, _store, execution_id = _ambiguous_service(refresher=None, deadline_seconds=60.0)
        service._now = lambda: AMBIGUOUS_NOW + timedelta(seconds=120)
        result = service.reconcile_ambiguous_submission(execution_id)
        assert result["status"] == "failed"
        assert result["failure_details"]
    elif case == "provider_rejected_failed":
        # (e) poll_verification's ARM-verified real "failed" transition
        # (failure_class="provider_rejected") -- WR-01's reproduced gap.
        service, _store, execution_id = _service_with_terminal_verifier_gap("failed")
        polled = service.poll_verification(execution_id)
        assert polled["status"] == "failed"
        assert polled["failure_class"] == "provider_rejected"
        assert polled["failure_details"]
    else:
        # (f) poll_verification's ARM-verified "cancelled" transition --
        # sibling of (e), same previously-unguarded pass-through.
        service, _store, execution_id = _service_with_terminal_verifier_gap("cancelled")
        polled = service.poll_verification(execution_id)
        assert polled["status"] == "cancelled"
        assert polled["failure_details"]
