"""Separate durable schema-proposal/review store (never the relationship store).

Layout under the document root::

    schema-proposals/<id>/proposal.json            immutable (create-only)
    schema-proposals/<id>/reviews/<seq>.json       append-only, create-only CAS

Review authority is supplied by the trusted local execution context, never by
actor roles inside the imported payload.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

from .schema_proposals import (
    SchemaProposalEnvelope,
    SchemaProposalRejected,
    operation_digest,
    parse_envelope,
    proposal_id_for,
)

_PREFIX = "schema-proposals"
MAX_REVIEWS = 1_000


class SchemaReviewDenied(PermissionError):
    """Unauthorized or stale review attempt."""


class SchemaProposalStore:
    def __init__(
        self,
        root: Path | str,
        *,
        is_steward: Callable[[str], bool],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._docs = OneLakeDocumentStore(root)
        self._is_steward = is_steward
        self._clock = clock

    def _proposal_name(self, proposal_id: str) -> str:
        return f"{_PREFIX}/{proposal_id}/proposal.json"

    def _review_name(self, proposal_id: str, seq: int) -> str:
        return f"{_PREFIX}/{proposal_id}/reviews/{seq:06d}.json"

    def import_proposal(self, envelope: SchemaProposalEnvelope) -> str:
        """Persist the immutable proposal (idempotent for identical content)."""

        proposal_id = proposal_id_for(envelope)
        record = {
            "proposal_id": proposal_id,
            "operation_digest": operation_digest(envelope),
            "envelope": envelope.model_dump(mode="json"),
            "advisory_only": True,
            "imported_at": self._clock().isoformat(),
        }
        try:
            self._docs.create_only(self._proposal_name(proposal_id), record)
        except DocumentConflictError:
            pass  # identical content-addressed proposal already imported
        return proposal_id

    def load(self, proposal_id: str) -> SchemaProposalEnvelope:
        snapshot = self._docs.read_snapshot(self._proposal_name(proposal_id))
        if not snapshot.exists:
            raise KeyError(proposal_id)
        envelope = parse_envelope(snapshot.payload["envelope"])
        if proposal_id_for(envelope) != proposal_id or snapshot.payload.get(
            "operation_digest"
        ) != operation_digest(envelope):
            raise SchemaProposalRejected("stored proposal failed digest verification")
        return envelope

    def reviews(self, proposal_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for seq in range(1, MAX_REVIEWS + 1):
            snap = self._docs.read_snapshot(self._review_name(proposal_id, seq))
            if not snap.exists:
                break
            out.append(snap.payload)
        return out

    def revision(self, proposal_id: str) -> int:
        return len(self.reviews(proposal_id))

    def review(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        decision: str,
        expected_revision: int,
        current_base_fingerprint: str,
    ) -> dict[str, Any]:
        """Append one authorized review bound to base/target/operation digest."""

        if decision not in ("approve", "reject"):
            raise SchemaReviewDenied("decision must be approve or reject")
        if not self._is_steward(reviewer):
            raise SchemaReviewDenied("reviewer lacks schema steward authority")
        envelope = self.load(proposal_id)
        if current_base_fingerprint != envelope.base_fingerprint:
            raise SchemaReviewDenied("base definition changed since proposal")
        existing = self.reviews(proposal_id)
        if len(existing) != expected_revision:
            raise SchemaReviewDenied("stale review revision")
        event = {
            "proposal_id": proposal_id,
            "sequence": expected_revision + 1,
            "decision": decision,
            "reviewer": reviewer,
            "reviewed_at": self._clock().isoformat(),
            "binding": {
                "workspace_id": envelope.workspace_id,
                "item_id": envelope.item_id,
                "format": envelope.format,
                "base_fingerprint": envelope.base_fingerprint,
                "operation_digest": operation_digest(envelope),
            },
        }
        event["event_digest"] = hashlib.sha256(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        try:
            self._docs.create_only(self._review_name(proposal_id, expected_revision + 1), event)
        except DocumentConflictError as exc:
            raise SchemaReviewDenied("stale review revision") from exc
        return event

    def approval_usable(self, proposal_id: str, *, current_base_fingerprint: str) -> bool:
        """True only if the latest review approves and the base is unchanged.

        Usable means "may proceed to a separate, approval-bound materialization
        plan"; it never executes or approves a format/target migration.
        """

        try:
            envelope = self.load(proposal_id)
        except (KeyError, SchemaProposalRejected):
            return False
        reviews = self.reviews(proposal_id)
        if not reviews or reviews[-1].get("decision") != "approve":
            return False
        binding = reviews[-1].get("binding") or {}
        return (
            current_base_fingerprint == envelope.base_fingerprint
            and binding.get("base_fingerprint") == envelope.base_fingerprint
            and binding.get("operation_digest") == operation_digest(envelope)
        )
