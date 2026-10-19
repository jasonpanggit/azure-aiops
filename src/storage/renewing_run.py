"""Caller-owned lifetime management for finite source-ingestion leases."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Event, Lock, Thread
from time import monotonic

from .locking import LEASE_DURATION_SECONDS, LeaseLostError, RunLock

RENEW_INTERVAL_SECONDS = LEASE_DURATION_SECONDS / 3


class _RunLeaseGuard:
    def __init__(self, lock: RunLock, acquired_at: float) -> None:
        self._lock = lock
        self._deadline = acquired_at + LEASE_DURATION_SECONDS
        self._mutex = Lock()
        self._lost: LeaseLostError | None = None

    def _assert_valid(self) -> None:
        if self._lost is None and monotonic() >= self._deadline:
            self._lost = LeaseLostError("source run lease validity expired")
        if self._lost is not None:
            raise self._lost
        self._lock.assert_held()

    def assert_held(self) -> None:
        """Reject known loss or expired validity, including an in-flight renewal."""
        with self._mutex:
            self._assert_valid()

    def renew(self) -> None:
        self.assert_held()
        started = monotonic()
        try:
            self._lock.renew()
        except LeaseLostError as error:
            with self._mutex:
                self._lost = self._lost or error
            raise
        with self._mutex:
            # A late success cannot revive a caller that may have lost exclusivity.
            self._assert_valid()
            self._deadline = started + LEASE_DURATION_SECONDS


@contextmanager
def renewing_run_lock(lock: RunLock) -> Iterator[RunLock | _RunLeaseGuard]:
    """Renew a remote run lease until work stops, and propagate loss to its owner.

    Callers must also check ``assert_held`` immediately before consequential
    writes; raising at context exit alone cannot protect publication. Validity
    is measured before each service call, never from its potentially delayed
    response. A blocked renewal cannot leave the publication guard healthy.
    """
    acquired_at = monotonic()
    with lock:
        if not lock.is_remote:
            yield lock
            return
        guard = _RunLeaseGuard(lock, acquired_at)
        guard.assert_held()
        stop = Event()
        def renew() -> None:
            while not stop.wait(RENEW_INTERVAL_SECONDS):
                try:
                    guard.renew()
                except LeaseLostError:
                    stop.set()
                    return

        worker = Thread(target=renew, name="source-run-lease-renewal", daemon=True)
        worker.start()
        try:
            yield guard
        finally:
            stop.set()
            worker.join()
        guard.assert_held()
