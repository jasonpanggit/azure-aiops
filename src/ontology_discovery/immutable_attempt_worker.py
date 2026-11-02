"""Default-off coordinator for one broker-owned immutable-attempt dispatch.

This module is deliberately not wired to the publisher CLI or legacy worker.
It coordinates only an explicitly composed broker client, materializer, and
CAS journal; it never falls back to fixed-table publication.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import uuid4

from ontology_discovery.immutable_attempt import AttemptReference, AttemptSession
from ontology_discovery.maintenance_materialization import (
    ATTEMPT_PROTOCOL,
    CandidateGenerationMaterializer,
)
from ontology_discovery.publication_broker_client import PublicationBrokerClient
from ontology_discovery.publisher import (
    OntologyGenerationCandidate,
    PublicationSafetyError,
)
from storage.onelake_documents import (
    DocumentConflictError,
    DocumentSnapshot,
    OneLakeDocumentStore,
)

_JOURNAL_NAMESPACE = "ontology/immutable-attempt-lifecycle"
_TARGET_FIELDS = frozenset(
    {
        "tenant_id",
        "subscription_id",
        "connection_id",
        "workspace_id",
        "item_id",
        "definition_fingerprint",
    }
)
_IN_PROGRESS = frozenset(
    {
        "acquiring",
        "allocated",
        "allocating",
        "commit_preparing",
        "restoring_preparing",
        "staged",
        "staging",
    }
)
_RECOVERABLE = frozenset({"committing", "restoring"})
_TERMINAL = frozenset({"acknowledged", "held", "historical_recovery"})


class AttemptLifecycleConflict(RuntimeError):
    """The dispatch binding or durable lifecycle journal no longer matches."""


@dataclass(frozen=True)
class AttemptLifecycleSnapshot:
    """One immutable-attempt journal record and its CAS revision."""

    record: dict[str, Any]
    revision: int
    etag: str


@runtime_checkable
class AttemptLifecycleJournal(Protocol):
    """Narrow read/create/CAS port for dispatch lifecycle records."""

    def read(self, dispatch_id: str) -> AttemptLifecycleSnapshot | None:
        """Read one dispatch record with its durable compare-and-set revision."""
        raise NotImplementedError

    def create(self, record: Mapping[str, Any]) -> AttemptLifecycleSnapshot:
        """Create a dispatch record exactly once."""
        raise NotImplementedError

    def replace(
        self, record: Mapping[str, Any], *, expected_revision: int
    ) -> AttemptLifecycleSnapshot:
        """Replace one record only when its journal revision still matches."""
        raise NotImplementedError

    def read_target(self, target: Mapping[str, str]) -> AttemptLifecycleSnapshot | None:
        """Read the serialized lifecycle owner for one exact broker target."""
        raise NotImplementedError

    def create_target(self, record: Mapping[str, Any]) -> AttemptLifecycleSnapshot:
        """Claim a target slot exactly once."""
        raise NotImplementedError

    def replace_target(
        self, record: Mapping[str, Any], *, expected_revision: int
    ) -> AttemptLifecycleSnapshot:
        """CAS a target slot without changing its target binding."""
        raise NotImplementedError


class OneLakeAttemptLifecycleJournal(AttemptLifecycleJournal):
    """Dispatch receipts and per-target ownership under a separate namespace.

    Dispatch receipts remain immutable to their dispatch identity; target
    ownership is serialized through a separate target-keyed CAS document.
    Product tables and artifacts are never used for lifecycle state.
    """

    def __init__(self, documents: OneLakeDocumentStore) -> None:
        if not isinstance(documents, OneLakeDocumentStore):
            raise TypeError("attempt lifecycle journal requires OneLakeDocumentStore")
        self._documents = documents

    @staticmethod
    def _name(dispatch_id: str) -> str:
        digest = hashlib.sha256(dispatch_id.encode("utf-8")).hexdigest()
        return f"{_JOURNAL_NAMESPACE}/dispatches/{digest}.json"

    @staticmethod
    def _target_name(target: Mapping[str, str]) -> str:
        digest = hashlib.sha256(_canonical(dict(target)).encode("utf-8")).hexdigest()
        return f"{_JOURNAL_NAMESPACE}/targets/{digest}.json"

    @staticmethod
    def _snapshot(
        value: DocumentSnapshot, dispatch_id: str
    ) -> AttemptLifecycleSnapshot | None:
        if not value.exists:
            return None
        record = value.payload
        if (
            set(record) != {"record"}
            or type(record["record"]) is not dict
            or record["record"].get("dispatch_id") != dispatch_id
            or type(record["record"].get("revision")) is not int
            or record["record"]["revision"] < 0
        ):
            raise ValueError("attempt lifecycle journal record is malformed")
        if value.etag is None:
            raise ValueError("attempt lifecycle journal snapshot has no ETag")
        return AttemptLifecycleSnapshot(
            copy.deepcopy(record["record"]),
            record["record"]["revision"],
            value.etag,
        )

    def read(self, dispatch_id: str) -> AttemptLifecycleSnapshot | None:
        """Read one record using the document store's strict snapshot API."""
        return self._snapshot(
            self._documents.read_snapshot(self._name(dispatch_id)), dispatch_id
        )

    def create(self, record: Mapping[str, Any]) -> AttemptLifecycleSnapshot:
        """Create a record once; a concurrent create is surfaced as conflict."""
        value = copy.deepcopy(dict(record))
        if type(value.get("revision")) is not int or value["revision"] != 0:
            raise ValueError("new attempt lifecycle record must start at revision zero")
        try:
            created = self._documents.create_only(
                self._name(str(value["dispatch_id"])), {"record": value}
            )
        except DocumentConflictError as exc:
            raise AttemptLifecycleConflict("attempt lifecycle already exists") from exc
        return self._snapshot(created, str(value["dispatch_id"]))  # type: ignore[return-value]

    def replace(
        self, record: Mapping[str, Any], *, expected_revision: int
    ) -> AttemptLifecycleSnapshot:
        """CAS one record, refusing stale writers and immutable-binding drift."""
        value = copy.deepcopy(dict(record))
        dispatch_id = str(value["dispatch_id"])
        name = self._name(dispatch_id)
        current = self.read(dispatch_id)
        if current is None or current.revision != expected_revision:
            raise AttemptLifecycleConflict("attempt lifecycle revision changed")
        if value.get("revision") != expected_revision + 1:
            raise ValueError("attempt lifecycle revision must advance exactly once")
        for field in (
            "dispatch_id",
            "operation",
            "target",
            "candidate_digest",
            "restore_reference",
        ):
            if value.get(field) != current.record.get(field):
                raise AttemptLifecycleConflict("attempt lifecycle binding changed")
        try:
            updated = self._documents.replace_if_match(
                name,
                {"record": value},
                expected_etag=current.etag,
            )
        except DocumentConflictError as exc:
            raise AttemptLifecycleConflict("attempt lifecycle CAS conflicted") from exc
        result = self._snapshot(updated, dispatch_id)
        if result is None:
            raise ValueError("attempt lifecycle CAS returned a missing record")
        return result

    @staticmethod
    def _target_snapshot(
        value: DocumentSnapshot, target: Mapping[str, str]
    ) -> AttemptLifecycleSnapshot | None:
        if not value.exists:
            return None
        record = value.payload
        if (
            set(record) != {"record"}
            or type(record["record"]) is not dict
            or record["record"].get("target") != dict(target)
            or type(record["record"].get("dispatch_id")) is not str
            or type(record["record"].get("revision")) is not int
            or record["record"]["revision"] < 0
        ):
            raise ValueError("attempt target journal record is malformed")
        if value.etag is None:
            raise ValueError("attempt target journal snapshot has no ETag")
        return AttemptLifecycleSnapshot(
            copy.deepcopy(record["record"]),
            record["record"]["revision"],
            value.etag,
        )

    def read_target(self, target: Mapping[str, str]) -> AttemptLifecycleSnapshot | None:
        """Read the target-level CAS record using its canonical target key."""
        return self._target_snapshot(
            self._documents.read_snapshot(self._target_name(target)), target
        )

    def create_target(self, record: Mapping[str, Any]) -> AttemptLifecycleSnapshot:
        """Create a target owner record once."""
        value = copy.deepcopy(dict(record))
        target = value.get("target")
        if (
            type(target) is not dict
            or set(target) != _TARGET_FIELDS
            or type(value.get("dispatch_id")) is not str
            or type(value.get("revision")) is not int
            or value["revision"] != 0
        ):
            raise ValueError("new attempt target record is invalid")
        try:
            created = self._documents.create_only(
                self._target_name(target), {"record": value}
            )
        except DocumentConflictError as exc:
            raise AttemptLifecycleConflict("attempt target is already claimed") from exc
        result = self._target_snapshot(created, target)
        if result is None:
            raise ValueError("attempt target create returned a missing record")
        return result

    def replace_target(
        self, record: Mapping[str, Any], *, expected_revision: int
    ) -> AttemptLifecycleSnapshot:
        """CAS target ownership while preserving the target key."""
        value = copy.deepcopy(dict(record))
        target = value.get("target")
        if type(target) is not dict or set(target) != _TARGET_FIELDS:
            raise ValueError("attempt target record has an invalid target")
        current = self.read_target(target)
        if current is None or current.revision != expected_revision:
            raise AttemptLifecycleConflict("attempt target revision changed")
        if value.get("revision") != expected_revision + 1:
            raise ValueError("attempt target revision must advance exactly once")
        try:
            updated = self._documents.replace_if_match(
                self._target_name(target),
                {"record": value},
                expected_etag=current.etag,
            )
        except DocumentConflictError as exc:
            raise AttemptLifecycleConflict("attempt target CAS conflicted") from exc
        result = self._target_snapshot(updated, target)
        if result is None:
            raise ValueError("attempt target CAS returned a missing record")
        return result


@dataclass(frozen=True)
class AttemptLifecycleResult:
    """Explicit acknowledgement or fail-closed hold; never reader authority."""

    state: Literal["acknowledged", "held", "historical_recovery"]
    record: Mapping[str, Any]


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("attempt lifecycle binding is not canonical JSON") from None


def _candidate_digest(candidate: OntologyGenerationCandidate) -> str:
    if type(candidate) is not OntologyGenerationCandidate:
        raise TypeError("attempt lifecycle requires an immutable generation candidate")
    return hashlib.sha256(_canonical(asdict(candidate)).encode("utf-8")).hexdigest()


def _session_record(session: AttemptSession) -> dict[str, Any]:
    return {
        "owner": session.owner,
        "epoch": session.epoch,
        "session_id": session.session_id,
    }


def _session_from_record(value: Any) -> AttemptSession:
    if (
        type(value) is not dict
        or set(value) != {"owner", "epoch", "session_id"}
        or type(value["owner"]) is not str
        or type(value["session_id"]) is not str
        or type(value["epoch"]) is not int
    ):
        raise AttemptLifecycleConflict("attempt lifecycle session pins are invalid")
    return AttemptSession(value["owner"], value["epoch"], value["session_id"])


def _control_record(value: Any) -> dict[str, Any]:
    if value.session is None:
        return {"session": None, "active": None, "revision": value.revision}
    return {
        "session": _session_record(value.session),
        "active": value.active.as_dict() if value.active is not None else None,
        "revision": value.revision,
    }


class ImmutableAttemptWorker:
    """Run one explicitly selected broker lifecycle without legacy publication.

    The application composition root supplies the already configured
    ``PublicationBrokerClient``, immutable-mode materializer, journal port,
    dispatch ID and target. None of these broker dependencies can be selected
    by candidate or dispatch payload. Lease renewal and automatic reallocation
    are intentionally unsupported.
    """

    def __init__(
        self,
        *,
        dispatch_id: str,
        expected_target: Mapping[str, str],
        client: PublicationBrokerClient,
        materializer: CandidateGenerationMaterializer,
        journal: AttemptLifecycleJournal,
        lease_seconds: int = 300,
        cancelled: Callable[[], bool] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            type(dispatch_id) is not str
            or not dispatch_id.strip()
            or len(dispatch_id) > 256
            or type(expected_target) is not dict
            or set(expected_target) != _TARGET_FIELDS
            or any(
                type(value) is not str or not value
                for value in expected_target.values()
            )
        ):
            raise ValueError("attempt lifecycle trusted dispatch binding is invalid")
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            raise ValueError(
                "attempt lifecycle lease must be between 1 and 300 seconds"
            )
        if (
            not isinstance(client, PublicationBrokerClient)
            or materializer.publication_protocol != ATTEMPT_PROTOCOL
            or materializer.attempt_protocol is not client
            or dict(client.expected_target) != expected_target
            or dict(materializer.expected_target or {}) != expected_target
            or not isinstance(journal, AttemptLifecycleJournal)
        ):
            raise ValueError(
                "attempt lifecycle dependencies are not one trusted binding"
            )
        self._dispatch_id = dispatch_id
        self._target = copy.deepcopy(dict(expected_target))
        self._client = client
        self._materializer = materializer
        self._journal = journal
        self._lease_seconds = lease_seconds
        self._cancelled = cancelled or (lambda: False)
        self._monotonic = monotonic
        self._run_id = str(uuid4())
        self._deadline: float | None = None
        self._snapshot: AttemptLifecycleSnapshot | None = None

    def publish(self, candidate: OntologyGenerationCandidate) -> AttemptLifecycleResult:
        """Acquire, stage, and admit one candidate using the journaled pins."""
        digest = _candidate_digest(candidate)
        identity = {
            "dispatch_id": self._dispatch_id,
            "operation": "admit",
            "target": self._target,
            "candidate_digest": digest,
            "restore_reference": None,
        }
        snapshot = self._open(identity)
        terminal = self._terminal(snapshot)
        if terminal is not None:
            return terminal
        snapshot = self._prepare_run(snapshot)
        if isinstance(snapshot, AttemptLifecycleResult):
            return snapshot
        if snapshot.record["state"] == "intent":
            snapshot = self._acquire(snapshot)
        if snapshot.record["state"] == "acquired":
            snapshot = self._allocate(snapshot)
        if snapshot.record["state"] == "allocated":
            snapshot = self._stage(snapshot, candidate)
        if snapshot.record["state"] == "staged":
            return self._admit(snapshot)
        return self._result(snapshot)

    def restore(self, reference: AttemptReference) -> AttemptLifecycleResult:
        """Restore one constructor-selected retained reference under new pins."""
        if type(reference) is not AttemptReference:
            raise TypeError("restore requires a trusted exact AttemptReference")
        digest = hashlib.sha256(
            _canonical(reference.as_dict()).encode("utf-8")
        ).hexdigest()
        identity = {
            "dispatch_id": self._dispatch_id,
            "operation": "restore",
            "target": self._target,
            "candidate_digest": digest,
            "restore_reference": reference.as_dict(),
        }
        snapshot = self._open(identity)
        terminal = self._terminal(snapshot)
        if terminal is not None:
            return terminal
        snapshot = self._prepare_run(snapshot)
        if isinstance(snapshot, AttemptLifecycleResult):
            return snapshot
        if snapshot.record["state"] == "intent":
            catalog = self._client.read_catalog(reference)
            if catalog["candidate"]["expected_target"] != self._target:
                held = self._hold(snapshot, "restore_target_mismatch")
                return self._result(held)
            snapshot = self._acquire(snapshot)
        if snapshot.record["state"] == "acquired":
            return self._restore_attempt(snapshot, reference)
        return self._result(snapshot)

    def _open(self, identity: Mapping[str, Any]) -> AttemptLifecycleSnapshot:
        snapshot = self._journal.read(self._dispatch_id)
        if snapshot is None:
            value = {
                "schema_version": 1,
                **copy.deepcopy(dict(identity)),
                "revision": 0,
                "state": "intent",
                "run_id": self._run_id,
                "session": None,
                "broker_revision": None,
                "attempt_id": None,
                "reference": None,
                "request_pins": None,
                "acknowledged_control": None,
                "historical_control": None,
                "hold_reason": "",
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            }
            self._snapshot = self._journal.create(value)
            self._claim_target(identity)
            return self._snapshot
        for field, expected in identity.items():
            if snapshot.record.get(field) != expected:
                raise AttemptLifecycleConflict(
                    f"dispatch {self._dispatch_id!r} was reused with a different {field}"
                )
        self._snapshot = snapshot
        if snapshot.record["state"] not in _TERMINAL:
            self._claim_target(identity)
        return snapshot

    def _claim_target(self, identity: Mapping[str, Any]) -> None:
        target = identity["target"]
        current = self._journal.read_target(target)
        if current is None:
            record = {
                "schema_version": 1,
                **copy.deepcopy(dict(identity)),
                "revision": 0,
                "state": "in_progress",
            }
            try:
                self._journal.create_target(record)
                return
            except AttemptLifecycleConflict:
                current = self._journal.read_target(target)
                if current is None:
                    raise
        if current.record.get("dispatch_id") == self._dispatch_id:
            for field in (
                "operation",
                "target",
                "candidate_digest",
                "restore_reference",
            ):
                if current.record.get(field) != identity.get(field):
                    raise AttemptLifecycleConflict(
                        "attempt target owner binding changed"
                    )
            return

        prior = self._journal.read(str(current.record["dispatch_id"]))
        if prior is None:
            raise AttemptLifecycleConflict(
                "target is owned by a dispatch without a durable receipt"
            )
        if prior.record.get("target") != target or any(
            current.record.get(field) != prior.record.get(field)
            for field in ("operation", "candidate_digest", "restore_reference")
        ):
            raise AttemptLifecycleConflict("target owner receipt binding changed")
        if prior.record.get("state") not in {"acknowledged", "historical_recovery"}:
            raise AttemptLifecycleConflict(
                f"target is held by dispatch {current.record['dispatch_id']!r}"
            )
        replacement = {
            "schema_version": 1,
            **copy.deepcopy(dict(identity)),
            "revision": current.revision + 1,
            "state": "in_progress",
        }
        self._journal.replace_target(replacement, expected_revision=current.revision)

    def _mark_target_state(self, state: str) -> None:
        if self._snapshot is None:
            raise AttemptLifecycleConflict("attempt lifecycle has no journal snapshot")
        target_snapshot = self._journal.read_target(self._target)
        if target_snapshot is None:
            raise AttemptLifecycleConflict("attempt target owner record is missing")
        if target_snapshot.record.get("dispatch_id") != self._dispatch_id:
            return
        updated = {
            **target_snapshot.record,
            "state": state,
            "revision": target_snapshot.revision + 1,
        }
        self._journal.replace_target(
            updated, expected_revision=target_snapshot.revision
        )

    def _prepare_run(
        self, snapshot: AttemptLifecycleSnapshot
    ) -> AttemptLifecycleSnapshot | AttemptLifecycleResult:
        record = snapshot.record
        if record["state"] in _RECOVERABLE:
            return self._recover(snapshot)
        if record["state"] in _TERMINAL:
            return snapshot
        if record["state"] != "intent" and record.get("run_id") != self._run_id:
            return self._hold(snapshot, "worker_restarted_before_safe_boundary")
        return snapshot

    def _terminal(
        self, snapshot: AttemptLifecycleSnapshot
    ) -> AttemptLifecycleResult | None:
        if snapshot.record["state"] in _TERMINAL:
            return self._result(snapshot)
        return None

    def _save(self, state: str, **updates: Any) -> AttemptLifecycleSnapshot:
        if self._snapshot is None:
            raise AttemptLifecycleConflict("attempt lifecycle has no journal snapshot")
        current = self._snapshot
        record = {
            **copy.deepcopy(current.record),
            **copy.deepcopy(updates),
            "state": state,
            "revision": current.revision + 1,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self._snapshot = self._journal.replace(
            record, expected_revision=current.revision
        )
        if state in {"acknowledged", "historical_recovery"}:
            self._mark_target_state(state)
        return self._snapshot

    def _result(self, snapshot: AttemptLifecycleSnapshot) -> AttemptLifecycleResult:
        state = snapshot.record["state"]
        if state in {"acknowledged", "held", "historical_recovery"}:
            return AttemptLifecycleResult(state, copy.deepcopy(snapshot.record))
        return AttemptLifecycleResult("held", copy.deepcopy(snapshot.record))

    def _hold(
        self, snapshot: AttemptLifecycleSnapshot, reason: str
    ) -> AttemptLifecycleSnapshot:
        if snapshot.record["state"] in _TERMINAL:
            return snapshot
        self._snapshot = snapshot
        held = self._save("held", hold_reason=reason)
        self._mark_target_state("held")
        return held

    def _check(self, snapshot: AttemptLifecycleSnapshot) -> None:
        if self._cancelled():
            self._hold(snapshot, "cancelled_before_mutation")
            raise AttemptLifecycleConflict(
                "attempt lifecycle cancelled before mutation"
            )
        if self._deadline is not None and self._monotonic() >= self._deadline:
            self._hold(snapshot, "lease_budget_exhausted")
            raise AttemptLifecycleConflict("attempt lifecycle lease budget exhausted")

    def _check_current(self) -> None:
        if self._snapshot is None:
            raise AttemptLifecycleConflict("attempt lifecycle has no journal snapshot")
        self._check(self._snapshot)

    def _acquire(self, snapshot: AttemptLifecycleSnapshot) -> AttemptLifecycleSnapshot:
        self._check(snapshot)
        control = self._client.control()
        snapshot = self._save(
            "acquiring",
            observed_revision=control.revision,
            run_id=self._run_id,
        )
        self._check(snapshot)
        started = self._monotonic()
        try:
            acquired = self._client.acquire(
                expected_revision=control.revision,
                lease_seconds=self._lease_seconds,
                before_send=self._check_current,
            )
        except Exception:
            self._hold(self._snapshot or snapshot, "acquire_outcome_unconfirmed")
            raise
        if acquired.session is None:
            self._hold(snapshot, "broker_returned_no_session")
            raise AttemptLifecycleConflict("broker acquisition returned no session")
        self._deadline = started + self._lease_seconds
        snapshot = self._save(
            "acquired",
            session=_session_record(acquired.session),
            broker_revision=acquired.revision,
            run_id=self._run_id,
        )
        return snapshot

    def _session(self, snapshot: AttemptLifecycleSnapshot) -> AttemptSession:
        return _session_from_record(snapshot.record.get("session"))

    def _assert_control(self, snapshot: AttemptLifecycleSnapshot) -> None:
        control = self._client.control()
        if (
            control.session != self._session(snapshot)
            or control.revision != snapshot.record["broker_revision"]
        ):
            self._hold(snapshot, "broker_session_or_revision_changed")
            raise AttemptLifecycleConflict("broker session or revision changed")

    def _allocate(self, snapshot: AttemptLifecycleSnapshot) -> AttemptLifecycleSnapshot:
        self._check(snapshot)
        self._assert_control(snapshot)
        snapshot = self._save("allocating", run_id=self._run_id)
        self._check(snapshot)
        try:
            attempt_id = self._client.allocate_attempt(
                self._session(snapshot),
                before_send=self._check_current,
            )
        except Exception:
            self._hold(self._snapshot or snapshot, "allocation_outcome_unconfirmed")
            raise
        return self._save("allocated", attempt_id=attempt_id, run_id=self._run_id)

    def _stage(
        self,
        snapshot: AttemptLifecycleSnapshot,
        candidate: OntologyGenerationCandidate,
    ) -> AttemptLifecycleSnapshot:
        self._check(snapshot)
        self._assert_control(snapshot)
        self._materializer.bind_attempt(
            self._session(snapshot),
            attempt_id=snapshot.record["attempt_id"],
            before_send=self._check_current,
        )
        snapshot = self._save("staging", run_id=self._run_id)
        try:
            result = self._materializer(candidate)
            reference = AttemptReference.parse(result["attempt_reference"])
        except Exception:
            self._hold(self._snapshot or snapshot, "stage_outcome_unconfirmed")
            raise
        return self._save(
            "staged",
            reference=reference.as_dict(),
            run_id=self._run_id,
        )

    def _admit(self, snapshot: AttemptLifecycleSnapshot) -> AttemptLifecycleResult:
        reference = AttemptReference.parse(snapshot.record["reference"])
        self._materializer.bind_attempt(
            self._session(snapshot),
            attempt_id=snapshot.record["attempt_id"],
            reference=reference,
            before_send=self._check_current,
        )
        return self._commit(snapshot, operation="admit", reference=reference)

    def _restore_attempt(
        self,
        snapshot: AttemptLifecycleSnapshot,
        reference: AttemptReference,
    ) -> AttemptLifecycleResult:
        self._check(snapshot)
        self._assert_control(snapshot)
        self._materializer.bind_attempt(
            self._session(snapshot),
            attempt_id=reference.attempt_id,
            reference=reference,
            before_send=self._check_current,
        )
        request_id = str(uuid4())
        snapshot = self._save(
            "restoring_preparing",
            run_id=self._run_id,
            request_id=request_id,
            expected_revision=snapshot.record["broker_revision"],
            reference=reference.as_dict(),
        )

        def persist(pins: Mapping[str, Any]) -> None:
            self._validate_pins(
                pins,
                snapshot,
                operation="restore",
                request_id=request_id,
                reference=reference,
            )
            self._save("restoring", request_pins=dict(pins))

        try:
            control = self._materializer.restore_attempt(
                reference,
                expected_revision=snapshot.record["broker_revision"],
                request_id=request_id,
                commit_intent_recorder=persist,
            )
        except Exception:
            current = self._snapshot
            if current is not None and current.record["state"] == "restoring":
                return self._recover(current)
            self._hold(self._snapshot or snapshot, "restore_failed_before_commit")
            raise
        return self._acknowledge(control)

    def _commit(
        self,
        snapshot: AttemptLifecycleSnapshot,
        *,
        operation: Literal["admit", "restore"],
        reference: AttemptReference,
    ) -> AttemptLifecycleResult:
        self._check(snapshot)
        self._assert_control(snapshot)
        request_id = str(uuid4())
        snapshot = self._save(
            "commit_preparing",
            run_id=self._run_id,
            request_id=request_id,
            expected_revision=snapshot.record["broker_revision"],
            reference=reference.as_dict(),
        )

        def persist(pins: Mapping[str, Any]) -> None:
            self._validate_pins(
                pins,
                snapshot,
                operation=operation,
                request_id=request_id,
                reference=reference,
            )
            self._save("committing", request_pins=dict(pins))

        try:
            control = self._materializer.commit_attempt(
                expected_revision=snapshot.record["broker_revision"],
                request_id=request_id,
                commit_intent_recorder=persist,
            )
        except Exception:
            current = self._snapshot
            if current is not None and current.record["state"] == "committing":
                return self._recover(current)
            self._hold(self._snapshot or snapshot, "commit_failed_before_request")
            raise
        return self._acknowledge(control)

    def _validate_pins(
        self,
        pins: Mapping[str, Any],
        snapshot: AttemptLifecycleSnapshot,
        *,
        operation: Literal["admit", "restore"],
        request_id: str,
        reference: AttemptReference,
    ) -> None:
        expected = {
            "session": _session_record(self._session(snapshot)),
            "reference": reference.as_dict(),
            "expected_revision": snapshot.record["broker_revision"],
            "operation": operation,
            "request_id": request_id,
        }
        if any(pins.get(key) != value for key, value in expected.items()):
            raise AttemptLifecycleConflict(
                "materializer commit pins differ from journal intent"
            )
        digest = pins.get("authorization_digest")
        if type(digest) is not str or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise AttemptLifecycleConflict(
                "materializer authorization digest is invalid"
            )
        if set(pins) != {*expected, "authorization_digest"}:
            raise AttemptLifecycleConflict(
                "materializer commit pins contain unknown fields"
            )

    def _recover(self, snapshot: AttemptLifecycleSnapshot) -> AttemptLifecycleResult:
        pins = snapshot.record.get("request_pins")
        if (
            snapshot.record["state"] not in _RECOVERABLE
            or type(pins) is not dict
            or set(pins)
            != {
                "session",
                "reference",
                "expected_revision",
                "operation",
                "request_id",
                "authorization_digest",
            }
        ):
            held = self._hold(snapshot, "original_recovery_pins_missing")
            return self._result(held)
        try:
            session = _session_from_record(pins["session"])
            reference = AttemptReference.parse(pins["reference"])
            self._materializer.bind_attempt(
                session, attempt_id=reference.attempt_id, reference=reference
            )
            outcome = self._materializer.recover_attempt_outcome(
                reference,
                expected_revision=pins["expected_revision"],
                request_id=pins["request_id"],
                operation=pins["operation"],
                authorization_digest=pins["authorization_digest"],
            )
        except (
            AttemptLifecycleConflict,
            PublicationSafetyError,
            KeyError,
            TypeError,
            ValueError,
        ):
            held = self._hold(snapshot, "read_only_recovery_unavailable")
            return self._result(held)
        if outcome is None:
            held = self._hold(snapshot, "no_historical_commit_outcome")
            return self._result(held)
        recovered = self._save(
            "historical_recovery",
            historical_control=_control_record(outcome),
            hold_reason="historical_outcome_does_not_prove_current_active_or_reader_access",
        )
        return self._result(recovered)

    def _acknowledge(self, control: Any) -> AttemptLifecycleResult:
        if self._snapshot is None:
            raise AttemptLifecycleConflict("attempt lifecycle has no journal snapshot")
        snapshot = self._save(
            "acknowledged",
            acknowledged_control=_control_record(control),
            hold_reason="",
        )
        return self._result(snapshot)
