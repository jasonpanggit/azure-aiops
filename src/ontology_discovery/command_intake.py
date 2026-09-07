"""Typed, create-only ontology command intake with narrow consumer views."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ontology.subscription_connection import SubscriptionConnection
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

COMMAND_DOCUMENT = "ontology/command-intake.json"
MANUAL_RUN = "manual_run"
MARK_FULL_RECONCILIATION_DUE = "mark_full_reconciliation_due"
ROLLBACK = "rollback"
_ACTIONS = {
    MANUAL_RUN: "ontology.discovery.run",
    MARK_FULL_RECONCILIATION_DUE: "ontology.discovery.maintenance",
    ROLLBACK: "ontology.publication.rollback",
}
_MAX_REASON = 512


class CommandConflict(RuntimeError):
    """A command status compare-and-set lost to another worker."""


def scope_receipt(connection: SubscriptionConnection, action: str) -> str:
    """Return the opaque authorization receipt derived from current registry state."""

    canonical = json.dumps(
        {
            "action": _required(action, "action"),
            "connection_id": connection.connection_id.casefold(),
            "scope": connection.scope_key.casefold(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class CommandIntakeService:
    """Producer/status capability used by the API; it cannot claim commands."""

    def __init__(self, command_root: str) -> None:
        self._documents = OneLakeDocumentStore(_required(command_root, "command_root"))

    def enqueue_manual_run(self, **values: Any) -> dict[str, Any]:
        return self._enqueue(MANUAL_RUN, values)

    def enqueue_mark_full_reconciliation_due(self, **values: Any) -> dict[str, Any]:
        return self._enqueue(MARK_FULL_RECONCILIATION_DUE, values)

    def enqueue_rollback(self, **values: Any) -> dict[str, Any]:
        return self._enqueue(ROLLBACK, values)

    def get(self, command_id: str) -> dict[str, Any] | None:
        state = _read(self._documents)
        return next(
            (
                copy.deepcopy(row)
                for row in state["commands"]
                if row["command_id"] == command_id
            ),
            None,
        )

    def _enqueue(self, command_type: str, values: Mapping[str, Any]) -> dict[str, Any]:
        issued_at = _aware(values.get("issued_at"), "issued_at")
        expires_at = _aware(values.get("expires_at"), "expires_at")
        if expires_at <= issued_at:
            raise ValueError("expires_at must be after issued_at")
        action = _required(values.get("action"), "action")
        if action != _ACTIONS[command_type]:
            raise ValueError(f"action is invalid for {command_type}")
        reason = str(values.get("reason") or "").strip()
        if len(reason) > _MAX_REASON:
            raise ValueError("reason exceeds the bounded command contract")
        envelope = {
            "type": command_type,
            "actor_hash": _required(values.get("actor_hash"), "actor_hash"),
            "effective_scope_hash": _required(
                values.get("effective_scope_hash"), "effective_scope_hash"
            ),
            "connection_id": _required(
                values.get("connection_id"), "connection_id"
            ).casefold(),
            "action": action,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "idempotency_key": _required(
                values.get("idempotency_key"), "idempotency_key"
            ),
            "reason": reason,
        }
        if command_type == MARK_FULL_RECONCILIATION_DUE:
            cadence = values.get("cadence_seconds")
            if cadence is not None and (
                isinstance(cadence, bool) or not 60 <= int(cadence) <= 2_592_000
            ):
                raise ValueError("cadence_seconds must be between 60 and 2592000")
            envelope["cadence_seconds"] = int(cadence) if cadence is not None else None
        if command_type == ROLLBACK:
            envelope["target_generation_id"] = _required(
                values.get("target_generation_id"), "target_generation_id"
            )
        identity = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        command_id = "ODC-" + hashlib.sha256(identity.encode()).hexdigest()[:24].upper()
        command = {
            "command_id": command_id,
            **envelope,
            "status": "pending",
            "revision": 0,
            "lease_owner": "",
            "lease_expires_at": "",
            "reason_code": "",
            "authorization_audit": {},
            "created_at": issued_at.isoformat(),
            "updated_at": issued_at.isoformat(),
        }

        def add(state: dict[str, Any]) -> dict[str, Any]:
            existing = next(
                (
                    row
                    for row in state["commands"]
                    if row["command_id"] == command_id
                ),
                None,
            )
            if existing is not None:
                if _immutable(existing) != _immutable(command):
                    raise CommandConflict("command_identity_conflict")
                return copy.deepcopy(existing)
            state["commands"].append(copy.deepcopy(command))
            return copy.deepcopy(command)

        return _mutate(self._documents, add)


class CoordinatorCommandConsumer:
    """Coordinator-only manual/maintenance claim and terminal-status capability."""

    _TYPES = frozenset({MANUAL_RUN, MARK_FULL_RECONCILIATION_DUE})

    def __init__(self, command_root: str) -> None:
        self._documents = OneLakeDocumentStore(_required(command_root, "command_root"))

    def list_due(self, *, now: datetime, limit: int = 1) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        moment = _aware(now, "now")
        rows = [
            copy.deepcopy(row)
            for row in _read(self._documents)["commands"]
            if row["type"] in self._TYPES
            and row["status"] == "pending"
            and datetime.fromisoformat(row["issued_at"]) <= moment
        ]
        rows.sort(key=lambda row: (row["issued_at"], row["command_id"]))
        return rows[:limit]

    def claim(
        self,
        command_id: str,
        *,
        expected_revision: int,
        owner: str,
        now: datetime,
        lease_seconds: int = 60,
    ) -> dict[str, Any]:
        moment = _aware(now, "now")

        def claim_row(state: dict[str, Any]) -> dict[str, Any]:
            row = _locate(state, command_id, self._TYPES)
            if row["status"] != "pending" or row["revision"] != expected_revision:
                raise CommandConflict("command_claim_conflict")
            row["status"] = "claimed"
            row["revision"] += 1
            row["lease_owner"] = _required(owner, "owner")
            row["lease_expires_at"] = (
                moment.timestamp() + max(1, int(lease_seconds))
            )
            row["updated_at"] = moment.isoformat()
            return copy.deepcopy(row)

        return _mutate(self._documents, claim_row)

    def complete(
        self,
        command_id: str,
        *,
        expected_revision: int,
        owner: str,
        authorization_audit: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        return self._terminal(
            command_id,
            expected_revision=expected_revision,
            owner=owner,
            status="completed",
            reason_code="",
            authorization_audit=authorization_audit,
            now=now,
        )

    def deny(
        self,
        command_id: str,
        *,
        expected_revision: int,
        owner: str,
        reason_code: str,
        authorization_audit: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        return self._terminal(
            command_id,
            expected_revision=expected_revision,
            owner=owner,
            status="denied",
            reason_code=_required(reason_code, "reason_code")[:96],
            authorization_audit=authorization_audit,
            now=now,
        )

    def _terminal(
        self,
        command_id: str,
        *,
        expected_revision: int,
        owner: str,
        status: str,
        reason_code: str,
        authorization_audit: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        moment = _aware(now, "now")

        def update(state: dict[str, Any]) -> dict[str, Any]:
            row = _locate(state, command_id, self._TYPES)
            if (
                row["status"] != "claimed"
                or row["revision"] != expected_revision
                or row["lease_owner"] != owner
            ):
                raise CommandConflict("command_status_conflict")
            row["status"] = status
            row["reason_code"] = reason_code
            row["authorization_audit"] = copy.deepcopy(dict(authorization_audit))
            row["revision"] += 1
            row["updated_at"] = moment.isoformat()
            return copy.deepcopy(row)

        return _mutate(self._documents, update)


def _immutable(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "command_id",
            "type",
            "actor_hash",
            "effective_scope_hash",
            "connection_id",
            "action",
            "issued_at",
            "expires_at",
            "idempotency_key",
            "reason",
            "cadence_seconds",
            "target_generation_id",
        )
    }


def _read(documents: OneLakeDocumentStore) -> dict[str, Any]:
    payload = documents.read_or_raise(COMMAND_DOCUMENT)
    rows = payload.get("commands", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise TypeError("ontology command ledger is malformed")
    return {"revision": int(payload.get("revision") or 0), "commands": rows}


def _mutate(documents: OneLakeDocumentStore, operation):
    for _ in range(3):
        state = _read(documents)
        expected = state["revision"]
        result = operation(state)
        state["revision"] = expected + 1
        try:
            documents.write(COMMAND_DOCUMENT, state, expected_revision=expected)
        except DocumentConflictError:
            continue
        return result
    raise CommandConflict("command_store_contended")


def _locate(
    state: Mapping[str, Any], command_id: str, allowed_types: frozenset[str]
) -> dict[str, Any]:
    row = next(
        (
            item
            for item in state["commands"]
            if item["command_id"] == command_id and item["type"] in allowed_types
        ),
        None,
    )
    if row is None:
        raise CommandConflict("command_not_claimable")
    return row


def _required(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "MANUAL_RUN",
    "MARK_FULL_RECONCILIATION_DUE",
    "ROLLBACK",
    "CommandConflict",
    "CommandIntakeService",
    "CoordinatorCommandConsumer",
    "scope_receipt",
]
