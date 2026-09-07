"""Dedicated durable dispatch workspace shared only by coordinator and publisher."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

DISPATCH_DOCUMENT = "ontology/publisher-dispatches.json"


class DispatchConflict(RuntimeError):
    """A dispatch create or status compare-and-set conflicted."""


class PublisherDispatchStore:
    """Create typed capability views from only the dedicated dispatch root."""

    def __init__(self, dispatch_root: str) -> None:
        root = str(dispatch_root or "").strip()
        if not root:
            raise ValueError("AIOPS_ONTOLOGY_DISPATCH_HOME must not be empty")
        self._documents = OneLakeDocumentStore(root)

    def coordinator(self) -> CoordinatorDispatchView:
        return CoordinatorDispatchView(self._documents)

    def publisher(self) -> PublisherDispatchView:
        return PublisherDispatchView(self._documents)


class CoordinatorDispatchView:
    """Create/read publish dispatches without claim or publication authority."""

    def __init__(self, documents: OneLakeDocumentStore) -> None:
        self._documents = documents

    def create_publish(
        self,
        *,
        run_id: str,
        connection_id: str,
        source_generation_id: str,
        candidate: Mapping[str, Any],
        now: datetime,
    ) -> tuple[dict[str, Any], bool]:
        moment = _aware(now)
        immutable = {
            "type": "publish",
            "run_id": _required(run_id, "run_id"),
            "connection_id": _required(
                connection_id, "connection_id"
            ).casefold(),
            "source_generation_id": _required(
                source_generation_id, "source_generation_id"
            ),
            "candidate": copy.deepcopy(dict(candidate)),
        }
        canonical = json.dumps(
            immutable, sort_keys=True, separators=(",", ":"), default=str
        )
        content_hash = hashlib.sha256(canonical.encode()).hexdigest()
        dispatch_id = "ODP-" + content_hash[:24].upper()
        record = {
            "dispatch_id": dispatch_id,
            **immutable,
            "content_hash": content_hash,
            "status": "pending",
            "revision": 0,
            "attempt_count": 0,
            "lease_owner": "",
            "lease_expires_at": "",
            "created_at": moment.isoformat(),
            "updated_at": moment.isoformat(),
            "receipts": [],
            "reason_code": "",
        }

        def add(state: dict[str, Any]):
            existing = next(
                (
                    row
                    for row in state["dispatches"]
                    if row["dispatch_id"] == dispatch_id
                ),
                None,
            )
            if existing is not None:
                if existing["content_hash"] != content_hash:
                    raise DispatchConflict("dispatch_identity_conflict")
                return (copy.deepcopy(existing), False)
            state["dispatches"].append(copy.deepcopy(record))
            return (copy.deepcopy(record), True)

        return _mutate(self._documents, add)

    def get_publish(self, dispatch_id: str) -> dict[str, Any] | None:
        return _get(self._documents, dispatch_id, "publish")

    def list_publish(self) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(row)
            for row in _read(self._documents)["dispatches"]
            if row["type"] == "publish"
        ]


class PublisherDispatchView:
    """Claim/status capability; publish payloads are immutable after creation."""

    def __init__(self, documents: OneLakeDocumentStore) -> None:
        self._documents = documents

    def list_due_publish(
        self, *, now: datetime, limit: int = 1
    ) -> list[dict[str, Any]]:
        moment = _aware(now)
        rows = [
            copy.deepcopy(row)
            for row in _read(self._documents)["dispatches"]
            if row["type"] == "publish"
            and row["status"] in {"pending", "retrying"}
            and (
                not row.get("next_attempt_at")
                or datetime.fromisoformat(row["next_attempt_at"]) <= moment
            )
        ]
        rows.sort(key=lambda row: (row["created_at"], row["dispatch_id"]))
        return rows[: max(0, int(limit))]

    def claim_publish(
        self,
        dispatch_id: str,
        *,
        expected_revision: int,
        owner: str,
        now: datetime,
        lease_seconds: int = 60,
    ) -> dict[str, Any]:
        moment = _aware(now)

        def claim(state: dict[str, Any]):
            row = _locate(state, dispatch_id, "publish")
            if (
                row["revision"] != expected_revision
                or row["status"] not in {"pending", "retrying"}
            ):
                raise DispatchConflict("dispatch_claim_conflict")
            row["status"] = "claimed"
            row["revision"] += 1
            row["attempt_count"] += 1
            row["lease_owner"] = _required(owner, "owner")
            row["lease_expires_at"] = (
                moment + timedelta(seconds=max(1, int(lease_seconds)))
            ).isoformat()
            row["updated_at"] = moment.isoformat()
            return copy.deepcopy(row)

        return _mutate(self._documents, claim)

    def complete_publish(
        self,
        dispatch_id: str,
        *,
        expected_revision: int,
        owner: str,
        receipt: Mapping[str, Any],
        now: datetime,
    ) -> dict[str, Any]:
        moment = _aware(now)

        def complete(state: dict[str, Any]):
            row = _locate(state, dispatch_id, "publish")
            if (
                row["revision"] != expected_revision
                or row["status"] != "claimed"
                or row["lease_owner"] != owner
            ):
                raise DispatchConflict("dispatch_status_conflict")
            row["status"] = "completed"
            row["revision"] += 1
            row["receipts"].append(copy.deepcopy(dict(receipt)))
            row["updated_at"] = moment.isoformat()
            return copy.deepcopy(row)

        return _mutate(self._documents, complete)

    def get_publish(self, dispatch_id: str) -> dict[str, Any] | None:
        return _get(self._documents, dispatch_id, "publish")


def _read(documents: OneLakeDocumentStore) -> dict[str, Any]:
    payload = documents.read_or_raise(DISPATCH_DOCUMENT)
    rows = payload.get("dispatches", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise TypeError("ontology dispatch ledger is malformed")
    return {"revision": int(payload.get("revision") or 0), "dispatches": rows}


def _mutate(documents: OneLakeDocumentStore, operation):
    for _ in range(3):
        state = _read(documents)
        expected = state["revision"]
        result = operation(state)
        state["revision"] = expected + 1
        try:
            documents.write(DISPATCH_DOCUMENT, state, expected_revision=expected)
        except DocumentConflictError:
            continue
        return result
    raise DispatchConflict("dispatch_store_contended")


def _get(
    documents: OneLakeDocumentStore, dispatch_id: str, dispatch_type: str
) -> dict[str, Any] | None:
    return next(
        (
            copy.deepcopy(row)
            for row in _read(documents)["dispatches"]
            if row["dispatch_id"] == dispatch_id and row["type"] == dispatch_type
        ),
        None,
    )


def _locate(
    state: Mapping[str, Any], dispatch_id: str, dispatch_type: str
) -> dict[str, Any]:
    row = next(
        (
            item
            for item in state["dispatches"]
            if item["dispatch_id"] == dispatch_id
            and item["type"] == dispatch_type
        ),
        None,
    )
    if row is None:
        raise DispatchConflict("dispatch_not_found")
    return row


def _required(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "CoordinatorDispatchView",
    "DispatchConflict",
    "PublisherDispatchStore",
    "PublisherDispatchView",
]
