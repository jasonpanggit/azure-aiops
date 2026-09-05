"""The autonomous half of Recommendation 3: no browser required.

``ExecutionVerifier``/``RemediationExecutionService`` (Plans 03.4-01 and
03.4-02) already know how to poll a running execution to a terminal outcome,
reconcile a verified-succeeded patch execution's selected KBs against
refreshed target evidence, and clear or reclassify a submission-ambiguous
failure. What was missing is *something that calls them without being
asked*: every existing caller was an HTTP route, so an execution's fate
depended on someone keeping a browser tab open (CR-03).

``RemediationVerificationCoordinator`` is that something. It owns no
scheduling/backoff/deadline logic of its own -- all of that already lives in
:mod:`intelligence.remediation.execution_store` (``list_due_for_verification``)
and :mod:`intelligence.remediation.execution_service` (the deadline-aware
CAS transitions). This module is iteration, per-record dispatch by shape,
and per-record error isolation only. It is deliberately free of any
FastAPI/HTTP/threading import so it is constructible and callable in a plain
unit test with fakes; :mod:`api.app` wires it into a background thread
exactly like the existing provider-refresh loop.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .execution_store import ExecutionLockContended, is_submission_ambiguous

_LOGGER = logging.getLogger("aiops.remediation.verification_coordinator")


class RemediationVerificationCoordinator:
    """Drives every due execution record to a real terminal outcome.

    Constructed with the store/service pair a caller already has (or, in
    production, the coordinator-owned instances :mod:`api.runtime` builds
    with ``plan_repository=None``/``patching_service=None`` -- this
    coordinator never calls ``execute``/``retry``/``supersede``, only the
    three read/reconcile methods dispatched below).
    """

    def __init__(
        self,
        *,
        execution_store: Any,
        execution_service: Any,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = execution_store
        self._service = execution_service
        self._now = now

    def run_once(self, now: datetime | None = None) -> dict[str, int]:
        """Process every currently-due execution record exactly once.

        Dispatches purely by record shape (never by remembering what it
        did last time -- durable state is the only source of truth):
        ``"running"``/``"retrying"`` (CR-01: a stranded retry claim is
        recovered identically to a stranded running claim) ->
        :meth:`poll_verification`; ``"failed"`` with a submission-ambiguous
        last attempt -> :meth:`reconcile_ambiguous_submission`;
        ``"succeeded"`` (which, by ``list_due_for_verification``'s own
        contract, only ever returns a not-yet-terminally-reconciled patch
        record here) -> :meth:`reconcile_evidence`. A per-record exception
        is caught and counted, never allowed to abort the batch or escape
        this method. WR-04: a record whose write lost to legitimate
        multi-replica lock contention (:class:`~.execution_store
        .ExecutionLockContended`) is counted separately as
        ``"skipped_contended"`` rather than folded into ``"errored"`` --
        it is expected to resolve on its own on the next pass, not a defect
        in verification logic.
        """
        moment = now or self._now()
        due = self._store.list_due_for_verification(now=moment)
        processed = 0
        errored = 0
        skipped_contended = 0
        for record in due:
            execution_id = str(record.get("execution_id") or "")
            status = str(record.get("status") or "")
            try:
                if status == "running":
                    self._service.poll_verification(execution_id)
                elif status == "retrying":
                    # CR-01: a "retrying" record stranded by a crash between
                    # claim_retry() and the following retrying -> running
                    # transition is recovered the same way -- bounded
                    # exclusively by its own seeded deadline, never
                    # resubmitted here.
                    self._service.poll_verification(execution_id)
                elif status == "failed" and is_submission_ambiguous(record):
                    self._service.reconcile_ambiguous_submission(execution_id)
                elif status == "succeeded":
                    self._service.reconcile_evidence(execution_id)
                else:
                    # list_due_for_verification's own contract should never
                    # return anything else, but an unrecognized shape is
                    # simply skipped rather than guessed at.
                    continue
                processed += 1
            except ExecutionLockContended:
                skipped_contended += 1
                _LOGGER.debug(
                    "remediation_verification_pass_lock_contended",
                    extra={"execution_id": execution_id, "status": status},
                )
            except Exception:
                errored += 1
                _LOGGER.exception(
                    "remediation_verification_pass_failed",
                    extra={"execution_id": execution_id, "status": status},
                )
        return {
            "processed": processed,
            "errored": errored,
            "skipped_contended": skipped_contended,
        }


__all__ = ["RemediationVerificationCoordinator"]
