"""Finite, browser-independent ontology discovery coordinator."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .contracts import RunProcessor
from .store import (
    RUN_RETRYING,
    OntologyRunStore,
    RunClaimConflict,
    RunDeadlineExceeded,
    RunLeaseLost,
)

_LOGGER = logging.getLogger("aiops.ontology_discovery.coordinator")


class OntologyDiscoveryCoordinator:
    """Claim and advance a bounded set of runs from durable state alone."""

    def __init__(
        self,
        *,
        store: OntologyRunStore,
        processor: RunProcessor,
        owner: str,
        lease_seconds: int = 60,
        now=None,
    ) -> None:
        if not owner.strip():
            raise ValueError("owner must not be empty")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        self._store = store
        self._processor = processor
        self._owner = owner
        self._lease_seconds = lease_seconds
        self._now = now or (lambda: datetime.now(UTC))

    async def run_once(
        self, *, now: datetime | None = None, limit: int = 10
    ) -> dict[str, int]:
        """Advance at most ``limit`` due runs, isolating each failure."""
        moment = now or self._now()
        due = self._store.list_due(now=moment, limit=limit)
        counts = {
            "selected": len(due),
            "processed": 0,
            "retrying": 0,
            "failed": 0,
            "timed_out": 0,
            "cancelled": 0,
            "skipped_contended": 0,
            "lease_lost": 0,
            "errored": 0,
        }
        for record in due:
            run_id = record["run_id"]
            try:
                if moment >= datetime.fromisoformat(record["deadline_at"]):
                    self._store.expire(
                        run_id,
                        expected_revision=record["revision"],
                        actor=self._owner,
                        now=moment,
                    )
                    counts["timed_out"] += 1
                    continue
                if record["attempt_count"] >= record["max_attempts"]:
                    self._store.exhaust(
                        run_id,
                        expected_revision=record["revision"],
                        actor=self._owner,
                        now=moment,
                    )
                    counts["failed"] += 1
                    continue
                claimed = self._store.claim(
                    run_id,
                    expected_revision=record["revision"],
                    owner=self._owner,
                    lease_seconds=self._lease_seconds,
                    now=moment,
                )
                try:
                    result = await self._processor.advance(claimed)
                except Exception as exc:
                    failed = self._store.fail(
                        run_id,
                        expected_revision=claimed["revision"],
                        owner=self._owner,
                        fencing_token=claimed["fencing_token"],
                        failure_class="processor_error",
                        message=str(exc) or exc.__class__.__name__,
                        now=moment,
                    )
                    counts["retrying" if failed["status"] == RUN_RETRYING else "failed"] += 1
                    _LOGGER.exception(
                        "ontology_discovery_run_failed",
                        extra={"run_id": run_id},
                    )
                    continue
                if result.complete:
                    self._store.succeed(
                        run_id,
                        expected_revision=claimed["revision"],
                        owner=self._owner,
                        fencing_token=claimed["fencing_token"],
                        checkpoint=result.checkpoint,
                        payload=result.payload,
                        now=moment,
                    )
                    counts["processed"] += 1
                else:
                    self._store.checkpoint(
                        run_id,
                        expected_revision=claimed["revision"],
                        owner=self._owner,
                        fencing_token=claimed["fencing_token"],
                        name=result.checkpoint,
                        payload=result.payload,
                        now=moment,
                    )
                    counts["processed"] += 1
            except RunClaimConflict:
                counts["skipped_contended"] += 1
            except RunDeadlineExceeded:
                counts["timed_out"] += 1
            except RunLeaseLost:
                counts["lease_lost"] += 1
            except Exception:
                counts["errored"] += 1
                _LOGGER.exception(
                    "ontology_discovery_run_dispatch_failed",
                    extra={"run_id": run_id},
                )
        return counts


__all__ = ["OntologyDiscoveryCoordinator"]
