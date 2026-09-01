"""Durable, per-ontology terminal-state record of publish attempts.

`onboarding.sync.ConnectionSyncCoordinator` previously surfaced a Fabric
publish failure only via `logger.exception(...)` -- a process-log-level
signal that disappears on restart and is invisible to anything outside the
process (notably a future Fabric medallion health API). This module gives
every publish attempt (preflight-rejected, retryable-failed, or succeeded) a
durably queryable terminal-state record.

Persistence reuses the existing small-control-plane-document storage tier
(:class:`storage.onelake_documents.OneLakeDocumentStore`) already used for
the subscription connection registry (`onboarding.store`) and the CVE
enrichment cache (`intelligence.vulnerability.enrichment_cache`), per
CONTEXT.md's "preserve existing patterns" decision and RESEARCH.md's
"Don't Hand-Roll" guidance -- no new storage backend is introduced. A plain
local root writes a JSON file; a `abfss://...` OneLake root writes the same
JSON shape as a OneLake document. Same code path either way.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from storage.onelake_documents import OneLakeDocumentStore

#: Matches `fabric.config.FabricConfig.ontology.ontology_name`'s default.
#: Kept as a local literal (rather than importing `fabric.config`) so this
#: module -- reachable from `onboarding.sync`, which must stay Fabric-config
#: agnostic -- does not gain a dependency on the Fabric config surface.
DEFAULT_ONTOLOGY_NAME = "Operational_Context_Graph"

#: Small control-plane document path, sibling to
#: `onboarding.store.REGISTRY_DOCUMENT` ("state/subscription_connections.json").
PUBLICATION_STATE_DOCUMENT = "state/ontology_publication_attempts.json"

#: Outcome vocabulary. "rejected" = preflight validation failure (never
#: retried); "failed" = a Fabric REST failure that exhausted
#: `fabric_client.py`'s bounded retry budget; "succeeded" = the publish
#: completed.
OUTCOMES = ("rejected", "failed", "succeeded")


@dataclass(frozen=True)
class PublicationAttemptRecord:
    """One ontology's most recent publish attempt terminal state."""

    attempt_id: str
    ontology_name: str
    outcome: str
    retryable: bool
    error: str
    attempted_at: str
    attempt_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "ontology_name": self.ontology_name,
            "outcome": self.outcome,
            "retryable": self.retryable,
            "error": self.error,
            "attempted_at": self.attempted_at,
            "attempt_count": self.attempt_count,
        }

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "PublicationAttemptRecord | None":
        try:
            return cls(
                attempt_id=str(row["attempt_id"]),
                ontology_name=str(row["ontology_name"]),
                outcome=str(row["outcome"]),
                retryable=bool(row["retryable"]),
                error=str(row.get("error") or ""),
                attempted_at=str(row["attempted_at"]),
                attempt_count=int(row.get("attempt_count") or 1),
            )
        except (KeyError, TypeError, ValueError):
            return None


class PublicationStateStore:
    """Durable, queryable per-ontology publish-attempt terminal state.

    One JSON document holds the *latest* attempt per `ontology_name`, keyed
    by name, under `PUBLICATION_STATE_DOCUMENT`. Writes are last-writer-wins
    (via :meth:`OneLakeDocumentStore.put`): losing a race to a concurrent
    writer only costs one stale terminal-state read, which is an acceptable
    trade-off for this operator-visibility surface (unlike the connection
    registry, which needs strict optimistic-concurrency semantics because it
    guards user-facing mutations).
    """

    def __init__(self, root: str, *, store: OneLakeDocumentStore | None = None) -> None:
        self.root = str(root)
        self.store = store or OneLakeDocumentStore(self.root)

    def record(
        self,
        *,
        ontology_name: str,
        outcome: str,
        retryable: bool,
        error: str = "",
        attempt_id: str | None = None,
        attempted_at: str | None = None,
    ) -> PublicationAttemptRecord:
        """Persist this attempt as the latest terminal state for `ontology_name`."""
        if outcome not in OUTCOMES:
            raise ValueError(f"Unknown publication outcome: {outcome!r}")
        payload = self.store.read(PUBLICATION_STATE_DOCUMENT)
        attempts_raw = payload.get("attempts")
        attempts = dict(attempts_raw) if isinstance(attempts_raw, dict) else {}
        previous = attempts.get(ontology_name)
        previous_count = int(previous.get("attempt_count") or 0) if isinstance(previous, dict) else 0
        record = PublicationAttemptRecord(
            attempt_id=attempt_id or str(uuid.uuid4()),
            ontology_name=ontology_name,
            outcome=outcome,
            retryable=bool(retryable),
            error=str(error or ""),
            attempted_at=attempted_at or _iso(datetime.now(UTC)),
            attempt_count=previous_count + 1,
        )
        attempts[ontology_name] = record.to_dict()
        document = dict(payload)
        document["attempts"] = attempts
        self.store.put(PUBLICATION_STATE_DOCUMENT, document)
        return record

    def get(self, ontology_name: str) -> PublicationAttemptRecord | None:
        """Return the latest attempt for `ontology_name`, or `None` if never attempted."""
        payload = self.store.read(PUBLICATION_STATE_DOCUMENT)
        attempts = payload.get("attempts")
        if not isinstance(attempts, dict):
            return None
        row = attempts.get(ontology_name)
        return PublicationAttemptRecord.from_mapping(row) if isinstance(row, dict) else None

    def list(self) -> list[PublicationAttemptRecord]:
        """Return every ontology's latest attempt record, in no particular order."""
        payload = self.store.read(PUBLICATION_STATE_DOCUMENT)
        attempts = payload.get("attempts")
        if not isinstance(attempts, dict):
            return []
        records = (PublicationAttemptRecord.from_mapping(row) for row in attempts.values())
        return [record for record in records if record is not None]


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "DEFAULT_ONTOLOGY_NAME",
    "OUTCOMES",
    "PUBLICATION_STATE_DOCUMENT",
    "PublicationAttemptRecord",
    "PublicationStateStore",
]
