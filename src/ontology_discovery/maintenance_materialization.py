"""Exact staged-generation product materialization and fenced recovery (Plan 14-06).

The maintenance materializer is the only component that writes physical
ontology products for a Phase 14 generation.  It never replays inventory or
rebuilds the deterministic graph: it projects the *immutable staged* generation
(authenticated, hash-verified, authorization-bound) into the closed canonical +
typed product manifest, verifies per-product row membership/hash/Delta version
by independent readback, and persists an immutable product receipt.  Readers are
pinned to the receipt of the generation the authoritative pointer names, never
to latest Delta heads.

Recovery is physical: a durable, CAS-versioned journal plus a renewable
target-scoped fenced lease let a failed/died worker be reconciled by
rematerializing the retained authorized generation's products (no table is ever
deleted).  Pointer, product and consumer restoration are recorded separately.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import re
import threading
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa

from fabric.schema_registry import schema_for
from fabric.sync_service import _generation_catalog, ontology_generation_products
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

from .maintenance_consumers import CONSUMER_FAMILIES, ConsumerObservation
from .publisher import PublicationSafetyError

RECEIPT_VERSION = "ontology-product-receipt/v1"
JOURNAL_VERSION = "ontology-recovery-journal/v1"
TERMINAL_PHASES = frozenset({"post_verified", "restored", "reconciled"})
_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
_HISTORY_LIMIT = 40
_LOCAL_LOCKS_GUARD = threading.Lock()
_LOCAL_LOCKS: dict[str, threading.Lock] = {}


class MaintenanceOwnershipLost(PublicationSafetyError):
    """Target ownership/fence no longer belongs to this writer."""


class MaterializationCritical(PublicationSafetyError):
    """Uncertain physical state; promotion stays closed until reconciled."""


class _LocalTargetMutationLock:
    """Process-shared exclusion for every local writer of one ontology target."""

    def __init__(self, root: Path, target: str) -> None:
        self.path = root / f".ontology-maintenance-{_safe(target, 'target')}.lock"
        self._handle: Any = None
        key = str(self.path.resolve())
        with _LOCAL_LOCKS_GUARD:
            self._thread_lock = _LOCAL_LOCKS.setdefault(key, threading.Lock())

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self._thread_lock.acquire()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except BaseException:
                handle.close()
                raise
            self._handle = handle
        except BaseException:
            self._thread_lock.release()
            raise

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
                self._thread_lock.release()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _safe(value: str, what: str) -> str:
    if not _SAFE.fullmatch(str(value)):
        raise PublicationSafetyError(f"unsafe {what}")
    return str(value)


def _normalize(row: Mapping[str, Any], table: str) -> dict[str, Any]:
    schema = schema_for(table)
    out: dict[str, Any] = {}
    for field in schema:
        value = row.get(field.name)
        if value is not None:
            if pa.types.is_floating(field.type):
                value = float(value)
            elif pa.types.is_integer(field.type):
                value = int(value)
            elif pa.types.is_boolean(field.type):
                value = bool(value)
        out[field.name] = value
    return out


def _membership(rows: Sequence[Mapping[str, Any]], table: str) -> list[str]:
    return sorted(_canonical(_normalize(row, table)) for row in rows)


# ----------------------------------------------------------------- lease/journal


class TargetLease:
    """Renewable, fenced, token-checked ownership of one physical product target."""

    def __init__(
        self,
        documents: OneLakeDocumentStore,
        target: str,
        *,
        clock: Callable[[], datetime],
        ttl: timedelta,
    ) -> None:
        self._documents = documents
        self._name = f"maintenance/lease/{_safe(target, 'target')}.json"
        self._clock = clock
        self._ttl = ttl
        self.token = ""
        self.owner = ""
        self.fence = 0
        self.lost = False

    def _payload(self, owner: str, fence: int, token: str, now: datetime) -> dict[str, Any]:
        return {
            "owner": owner,
            "fence": int(fence),
            "token": token,
            "expires_at": (now + self._ttl).isoformat(),
        }

    def acquire(self, owner: str, fence: int) -> None:
        now = self._clock()
        snap = self._documents.read_snapshot(self._name)
        token = uuid.uuid4().hex
        payload = self._payload(owner, fence, token, now)
        try:
            if not snap.exists:
                self._documents.create_only(self._name, payload)
            else:
                cur = snap.payload
                expired = datetime.fromisoformat(str(cur["expires_at"])) <= now
                if int(cur["fence"]) > fence:
                    raise MaintenanceOwnershipLost("target_lease_stale_fence")
                if not expired and not (cur["owner"] == owner and fence >= int(cur["fence"])):
                    raise MaintenanceOwnershipLost("target_owned_by_another_writer")
                if not expired and cur["owner"] == owner and self.token != cur["token"]:
                    # Same publisher identity restarted: the dead holder's token
                    # is replaced so a zombie instance can no longer write.
                    pass
                self._documents.replace_if_match(
                    self._name, payload, expected_etag=snap.etag
                )
        except DocumentConflictError as exc:
            raise MaintenanceOwnershipLost("target_lease_contended") from exc
        self.token, self.owner, self.fence = token, owner, int(fence)

    def assert_held(self) -> None:
        """Verify and renew; raises if ownership was lost for any reason."""
        if not self.token:
            raise MaintenanceOwnershipLost("target_lease_not_held")
        now = self._clock()
        snap = self._documents.read_snapshot(self._name)
        cur = snap.payload
        if (
            not snap.exists
            or cur.get("token") != self.token
            or cur.get("owner") != self.owner
            or int(cur.get("fence", -1)) != self.fence
            or datetime.fromisoformat(str(cur["expires_at"])) <= now
        ):
            self.token = ""
            self.lost = True
            raise MaintenanceOwnershipLost("target_lease_lost")
        try:
            self._documents.replace_if_match(
                self._name,
                self._payload(self.owner, self.fence, self.token, now),
                expected_etag=snap.etag,
            )
        except DocumentConflictError as exc:
            self.token = ""
            self.lost = True
            raise MaintenanceOwnershipLost("target_lease_lost") from exc

    def release(self) -> None:
        if not self.token:
            return
        snap = self._documents.read_snapshot(self._name)
        if snap.exists and snap.payload.get("token") == self.token:
            expired = self._payload(self.owner, self.fence, self.token, self._clock())
            expired["expires_at"] = (self._clock() - timedelta(seconds=1)).isoformat()
            try:
                self._documents.replace_if_match(
                    self._name, expired, expected_etag=snap.etag
                )
            except DocumentConflictError:
                pass
        self.token = ""


class RecoveryJournal:
    """CAS-versioned durable journal for one target (bounded history)."""

    def __init__(self, documents: OneLakeDocumentStore, target: str) -> None:
        self._documents = documents
        self._name = f"maintenance/journal/{_safe(target, 'target')}.json"
        self.etag: str | None = None

    def read(self) -> dict[str, Any] | None:
        snap = self._documents.read_snapshot(self._name)
        self.etag = snap.etag
        return dict(snap.payload) if snap.exists else None

    def write(self, payload: dict[str, Any]) -> dict[str, Any]:
        history = list(payload.get("history", []))[-_HISTORY_LIMIT:]
        payload = {**payload, "version": JOURNAL_VERSION, "history": history}
        try:
            if self.etag is None:
                snap = self._documents.create_only(self._name, payload)
            else:
                snap = self._documents.replace_if_match(
                    self._name, payload, expected_etag=self.etag
                )
        except DocumentConflictError as exc:
            raise MaintenanceOwnershipLost("recovery_journal_changed") from exc
        self.etag = snap.etag
        return payload


class ProductReceiptStore:
    """Immutable, content-addressed product receipts (sequence per generation)."""

    def __init__(self, documents: OneLakeDocumentStore) -> None:
        self._documents = documents

    def _names(self, generation_id: str) -> list[str]:
        prefix = f"maintenance/products/{_safe(generation_id, 'generation')}/"
        names, token = [], None
        while True:
            page, token = self._documents.list_names(prefix, limit=200, continuation=token)
            names.extend(page)
            if not token:
                return sorted(names)

    def latest(self, generation_id: str) -> dict[str, Any] | None:
        names = self._names(generation_id)
        if not names:
            return None
        snap = self._documents.read_snapshot(names[-1])
        return dict(snap.payload) if snap.exists else None

    def put(self, generation_id: str, body: dict[str, Any]) -> dict[str, Any]:
        for _ in range(8):
            names = self._names(generation_id)
            seq = len(names) + 1
            receipt = {**body, "sequence": seq, "receipt_version": RECEIPT_VERSION}
            receipt["receipt_digest"] = _hash(receipt)
            name = f"maintenance/products/{generation_id}/{seq:08d}.json"
            try:
                self._documents.create_only(name, receipt)
                return receipt
            except DocumentConflictError:
                continue
        raise PublicationSafetyError("product receipt sequence contended")


# --------------------------------------------------------------------- readers


class PinnedProductReader:
    """Reads products at the receipt versions of the pointer's generation only."""

    def __init__(
        self,
        *,
        read_pointer: Callable[[], Any],
        receipts: ProductReceiptStore,
        delta: Any,
        onelake: Any,
    ) -> None:
        self._pointer = read_pointer
        self._receipts = receipts
        self._delta = delta
        self._onelake = onelake
        self._cache: tuple[str, str, tuple[list, list]] | None = None

    def active(self) -> tuple[str | None, dict[str, Any] | None]:
        snapshot = self._pointer()
        if snapshot.pointer is None:
            return None, None
        generation = snapshot.pointer.active_generation
        return generation, self._receipts.latest(generation)

    def read_table(self, table: str, receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
        product = receipt["products"][table]
        layer, logical = table.split("_", 1)
        return self._delta.read(
            self._onelake.table_uri(layer, logical), version=int(product["version"])
        )

    def verify(self, receipt: Mapping[str, Any]) -> dict[str, str]:
        """Re-read every product at its pinned version and re-hash membership."""
        digests: dict[str, str] = {}
        for table, product in sorted(receipt["products"].items()):
            rows = self.read_table(table, receipt)
            members = _membership(rows, table)
            if len(rows) != int(product["rows"]) or _hash(members) != product["hash"]:
                raise PublicationSafetyError(f"product_readback_mismatch:{table}")
            digests[table] = product["hash"]
        return digests

    def read_ontology(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        generation, receipt = self.active()
        if generation is None:
            return [], []
        if receipt is None:
            raise PublicationSafetyError("product_receipt_missing")
        key = (generation, str(receipt["receipt_digest"]))
        if self._cache is not None and self._cache[:2] == key:
            return list(self._cache[2][0]), list(self._cache[2][1])
        entities = self.read_table("ontology_entities", receipt)
        relationships = self.read_table("ontology_relationships", receipt)
        self._cache = (*key, (entities, relationships))
        return list(entities), list(relationships)


# ----------------------------------------------------------------- materializer


@dataclass
class _Context:
    owner_id: str
    fence: int
    predecessor: str | None
    pointer_etag: str | None


class CandidateGenerationMaterializer:
    """Publisher-owned exact materializer + fenced physical recovery port."""

    maintenance_candidate_bound = True

    def __init__(
        self,
        *,
        storage: Any,
        documents: OneLakeDocumentStore,
        service: Any,
        authorizer: Any | None,
        target_id: str,
        clock: Callable[[], datetime],
        expected_target: Mapping[str, str] | None = None,
        definition_fingerprint: Callable[[], str] | None = None,
        lease_ttl: timedelta = timedelta(minutes=5),
        fault: Callable[[str], None] | None = None,
    ) -> None:
        if storage is None or documents is None or service is None:
            raise PublicationSafetyError("materializer_unqualified")
        local_root = getattr(getattr(service, "onelake", None), "local_root", None)
        if local_root is None:
            raise PublicationSafetyError("remote_mutation_lock_unqualified")
        self._storage = storage
        self._service = service
        self._authorizer = authorizer
        self._target = _safe(target_id, "target")
        self._expected_target = (
            {str(key): str(value) for key, value in expected_target.items()}
            if expected_target is not None
            else None
        )
        self._definition_fingerprint = definition_fingerprint
        self._mutation_lock = _LocalTargetMutationLock(Path(local_root), self._target)
        self._clock = clock
        self._fault = fault or (lambda _point: None)
        self.lease = TargetLease(documents, self._target, clock=clock, ttl=lease_ttl)
        self.journal = RecoveryJournal(documents, self._target)
        self.receipts = ProductReceiptStore(documents)
        self.reader = PinnedProductReader(
            read_pointer=storage.read_pointer,
            receipts=self.receipts,
            delta=service.delta,
            onelake=service.onelake,
        )
        self._ctx: _Context | None = None
        self._state: dict[str, Any] | None = None
        self._writes = 0
        self._began = False
        self._runtime_guard: Callable[[], None] | None = None
        self._restore_pointer: tuple[str | None, str | None] | None = None
        self._restore_expected: dict[str, str] | None = None
        self._operation_generation: str | None = None

    # ------------------------------------------------------------- binding
    def bind(
        self,
        *,
        owner_id: str,
        fence: int,
        predecessor: str | None,
        pointer_etag: str | None,
        runtime_guard: Callable[[], None] | None = None,
    ) -> None:
        self._ctx = _Context(owner_id, int(fence), predecessor, pointer_etag)
        self._began = False
        self._runtime_guard = runtime_guard

    def _context(self) -> _Context:
        if self._ctx is None:
            raise PublicationSafetyError("materializer_unbound")
        return self._ctx

    def _acquire(self) -> None:
        ctx = self._context()
        if self.lease.lost:
            raise MaintenanceOwnershipLost("target_lease_requires_fresh_holder")
        if not self.lease.token:
            self.lease.acquire(ctx.owner_id, ctx.fence)

    def assert_owned(self) -> None:
        self.lease.assert_held()

    def assert_restore_authorized(self) -> None:
        """Fresh authenticated restore authority, independent of admission cancellation."""
        self.assert_owned()
        try:
            self._reauthorize_restore()
        except Exception as exc:
            raise PublicationSafetyError("restore_not_authorized") from exc

    def release(self) -> None:
        self.lease.release()
        self._mutation_lock.release()

    def _fault_at(self, point: str) -> None:
        """Let crash-injection tests model process death without orphaning locks."""
        try:
            self._fault(point)
        except BaseException:
            # In production a dead process drops flock and closes its lease
            # handle. Test fault injectors raise BaseException in-process, so
            # explicitly mirror that OS cleanup before reconstruction proceeds.
            self.release()
            raise

    # ------------------------------------------------------------- journal
    def _transition(self, phase: str, **fields: Any) -> dict[str, Any]:
        ctx = self._context()
        current = self.journal.read() or {}
        # Stale-owner protection: a journal written under a newer fence cannot
        # be advanced by an older owner.
        if current and int(current.get("fence", 0)) > ctx.fence:
            raise MaintenanceOwnershipLost("journal_owned_by_newer_fence")
        history = [*current.get("history", []), phase]
        body = {
            **current,
            **fields,
            "target": self._target,
            "phase": phase,
            "owner": ctx.owner_id,
            "fence": ctx.fence,
            "updated_at": self._clock().isoformat(),
            "history": history,
        }
        written = self.journal.write(body)
        self._state = written
        return written

    # ------------------------------------------------------------ verification
    @staticmethod
    def _identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in manifest.items() if k not in {"content_hash", "complete"}}

    def _staged(self, generation_id: str) -> dict[str, Any]:
        try:
            staged = self._storage.read_generation(generation_id)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise PublicationSafetyError("staged_generation_unavailable") from exc
        manifest = staged["manifest"]
        if (
            manifest.get("complete") is not True
            or _hash(self._identity(manifest)) != manifest.get("content_hash")
            or _hash(staged["entities"]) != manifest.get("entity_hash")
            or _hash(staged["relationships"]) != manifest.get("relationship_hash")
            or manifest.get("generation_id") != generation_id
        ):
            raise PublicationSafetyError("staged_generation_tampered")
        return staged

    def _authorization(
        self, generation_id: str, staged: Mapping[str, Any], *, mode: str
    ) -> dict[str, str]:
        expected_target = self._target_for(staged, generation_id)
        rows = (
            self._authorizer.model_rows(staged["relationships"])
            if self._authorizer is not None
            else [
                r for r in staged["relationships"]
                if str(r.get("source") or "").casefold() in {"model", "ai", "llm"}
                or r.get("model_derived") is True
            ]
        )
        fresh: dict[str, Any] = {}
        if mode == "restore":
            # Even a deterministic predecessor requires separately current
            # restore authority. Absence of model rows is not a boolean bypass.
            try:
                self._restore_expected = self._restore_target_for(
                    generation_id, staged, expected_target
                )
                release = self._reauthorize_restore()
            except Exception as exc:
                raise PublicationSafetyError("restore_not_authorized") from exc
        else:
            if self._authorizer is None:
                raise PublicationSafetyError("materializer_unqualified")
            try:
                if rows:
                    manifest = staged["manifest"]
                    persisted = type(
                        "_StagedCandidate",
                        (),
                        {
                            "relationships": tuple(staged["relationships"]),
                            "entities": tuple(staged["entities"]),
                            "proposal_lineage": tuple(staged["lineage"]["proposal_ids"]),
                            "source_generation": str(manifest["source_generation"]),
                        },
                    )()
                    release, fresh = self._authorizer.authorize_bound(
                        persisted, expected_target
                    )
                else:
                    release = self._authorizer.reader.read("admit")
            except Exception as exc:
                reason = getattr(exc, "reason", "authorization_denied")
                raise PublicationSafetyError(f"maintenance authorization denied: {reason}") from exc
            self._validate_release_target(release, expected_target)
        if not rows:
            if mode == "restore":
                retained = self.receipts.latest(generation_id)
                if retained is None:
                    raise PublicationSafetyError("restore_content_authority_missing")
                return {
                    "authorization_digest": str(retained["authorization_digest"]),
                    "attestation_digest": str(retained["attestation_digest"]),
                    "release_id": str(retained.get("release_id") or ""),
                }
            return {
                "authorization_digest": _hash(
                    {
                        "release": release.authorization_binding(),
                        "target": expected_target,
                        "generation_id": generation_id,
                        "content_hash": staged["manifest"]["content_hash"],
                    }
                ),
                "attestation_digest": release.attestation_digest,
                "release_id": release.release_id,
            }
        if self._authorizer is None:
            raise PublicationSafetyError("materializer_unqualified")
        manifest = staged["manifest"]
        try:
            recorded = self._storage.read_stage_authorization(
                target_generation_id=generation_id,
                owner_id=str(manifest["owner_id"]),
                fence=int(manifest["fence"]),
            )
        except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
            raise PublicationSafetyError("stage_authorization_missing") from exc
        if (
            recorded.get("event") != "maintenance_stage_authorization"
            or recorded.get("generation_id") != generation_id
            or recorded.get("content_hash") != manifest["content_hash"]
            or (
                mode != "restore"
                and (
                    recorded.get("release_id") != release.release_id
                    or recorded.get("attestation_digest") != release.attestation_digest
                )
            )
        ):
            raise PublicationSafetyError("stage_authorization_mismatch")
        if mode != "restore":
            if fresh.get("authorization_digest") != recorded.get("authorization_digest"):
                raise PublicationSafetyError("stage_authorization_digest_changed")
            if (
                fresh.get("release_id") != release.release_id
                or fresh.get("attestation_digest") != release.attestation_digest
            ):
                raise PublicationSafetyError("stage_authorization_changed")
        if mode == "restore":
            original = self.receipts.latest(generation_id)
            expected_digest = (
                str(original.get("authorization_digest") or "")
                if original is not None
                else str((self.journal.read() or {}).get("operation", {}).get("authorization_digest") or "")
            )
            if not expected_digest:
                raise PublicationSafetyError("restore_content_authority_missing")
            if self._restore_expected is not None:
                self._restore_expected["authorization_digest"] = expected_digest
            self._reauthorize_restore()
        return {
            "authorization_digest": str(recorded.get("authorization_digest") or ""),
            "attestation_digest": str(recorded.get("attestation_digest") or ""),
            "release_id": str(recorded.get("release_id") or ""),
        }

    def _target_for(
        self, staged: Mapping[str, Any], generation_id: str
    ) -> dict[str, str]:
        required = {
            "tenant_id",
            "subscription_id",
            "connection_id",
            "workspace_id",
            "item_id",
            "definition_fingerprint",
        }
        target = self._expected_target
        if target is None or set(target) != required or any(not target.get(k) for k in required):
            raise PublicationSafetyError("maintenance_target_binding_unqualified")
        onelake = self._service.onelake
        if (
            str(onelake.workspace_id) != target["workspace_id"]
            or str(onelake.lakehouse_id) != target["item_id"]
        ):
            raise PublicationSafetyError("physical_target_mismatch")
        fingerprint = (
            str(self._definition_fingerprint())
            if self._definition_fingerprint is not None
            else target["definition_fingerprint"]
        )
        if fingerprint != target["definition_fingerprint"]:
            raise PublicationSafetyError("definition_target_mismatch")
        if not generation_id or staged["manifest"].get("generation_id") != generation_id:
            raise PublicationSafetyError("generation_target_mismatch")
        return dict(target)

    @staticmethod
    def _validate_release_target(release: Any, target: Mapping[str, str]) -> None:
        declared = {
            "tenant_id": str(release.tenant_id),
            "subscription_id": str(release.subscription_id),
            "connection_id": str(release.connection_id),
            "workspace_id": str(release.workspace_id),
            "item_id": str(release.item_id),
            "definition_fingerprint": str(release.definition_fingerprint),
        }
        if any(target.get(key) != value for key, value in declared.items()):
            raise PublicationSafetyError("maintenance_release_target_mismatch")

    def _restore_target_for(
        self,
        generation_id: str,
        staged: Mapping[str, Any],
        target: Mapping[str, str],
    ) -> dict[str, str]:
        recorded = self._restore_authorization_digest(generation_id)
        return {
            **target,
            "generation_id": generation_id,
            "content_hash": str(staged["manifest"]["content_hash"]),
            "authorization_digest": recorded,
        }

    def _restore_authorization_digest(self, generation_id: str) -> str:
        receipt = self.receipts.latest(generation_id)
        if receipt is not None:
            return str(receipt.get("authorization_digest") or "")
        operation = (self.journal.read() or {}).get("operation") or {}
        if operation.get("generation_id") == generation_id:
            return str(operation.get("authorization_digest") or "")
        return ""

    def _reauthorize_restore(self) -> Any:
        if self._authorizer is None or self._restore_expected is None:
            raise PublicationSafetyError("restore_authority_missing")
        onelake = self._service.onelake
        if (
            str(onelake.workspace_id) != self._restore_expected["workspace_id"]
            or str(onelake.lakehouse_id) != self._restore_expected["item_id"]
        ):
            raise PublicationSafetyError("physical_target_mismatch")
        if (
            self._definition_fingerprint is not None
            and str(self._definition_fingerprint())
            != self._restore_expected["definition_fingerprint"]
        ):
            raise PublicationSafetyError("definition_target_mismatch")
        verified = self._authorizer.authorize_restore(
            expected_target=self._restore_expected
        )
        self._validate_release_target(verified, self._restore_expected)
        return verified

    def _reauthorize_admission(self) -> None:
        generation_id = self._operation_generation
        if generation_id is None:
            return
        staged = self._staged(generation_id)
        self._authorization(generation_id, staged, mode="admit")

    # ---------------------------------------------------------- materialization
    def _guard_write(self) -> None:
        def guard() -> None:
            self.lease.assert_held()
            if self._restore_pointer is not None:
                snap = self._storage.read_pointer()
                actual = (snap.pointer.active_generation if snap.pointer else None, snap.etag)
                if actual != self._restore_pointer:
                    raise PublicationSafetyError("restore_pointer_changed")
                self._reauthorize_restore()
            elif self._runtime_guard is not None:
                self._runtime_guard()
                self._reauthorize_admission()
            else:
                self._reauthorize_admission()

        # The fault hook represents the last scheduling gap, not a write.
        # Authorize once *after* it, immediately before the consequential sink
        # call. Checking on both sides doubled all cryptographic/corpus work
        # without protecting any additional mutation.
        self.lease.assert_held()
        self._writes += 1
        self._fault_at(f"before_table_write:{self._writes}")
        # Fault hooks model a scheduling gap immediately before the sink call.
        guard()

    def _catalog_read(self) -> dict[str, Any]:
        onelake = self._service.onelake
        if getattr(onelake, "local_root", None) is not None:
            path = onelake.local_root / "Files" / "ontology" / "metadata" / "catalog.json"
            return json.loads(path.read_text()) if path.is_file() else {}
        file_system = onelake.service.get_file_system_client(onelake.workspace_id)
        client = file_system.get_file_client(
            f"{onelake.lakehouse_id}/Files/ontology/metadata/catalog.json"
        )
        return json.loads(client.download_file().readall())

    def _materialize(
        self, generation_id: str, staged: Mapping[str, Any], auth: Mapping[str, str], *, kind: str
    ) -> dict[str, Any]:
        ctx = self._context()
        manifest = staged["manifest"]
        expected = ontology_generation_products(
            staged["entities"],
            staged["relationships"],
            generation_id=generation_id,
            source_generation=str(manifest["source_generation"]),
            content_hash=str(manifest["content_hash"]),
            authorization_digest=auth["authorization_digest"],
            attestation_digest=auth["attestation_digest"],
            validation=staged["validation"],
        )
        delta, onelake = self._service.delta, self._service.onelake

        def uri(table: str) -> str:
            layer, logical = table.split("_", 1)
            return onelake.table_uri(layer, logical)

        before = {table: delta.version(uri(table)) for table in expected}
        self._writes = 0
        self._operation_generation = generation_id
        self._mutation_lock.acquire()
        try:
            # Ownership may have changed while this process waited for the
            # target-wide OS lock. Never enter a sink write on a stale lease.
            self.lease.assert_held()
            written = self._service.materialize_ontology_generation(
                entities=staged["entities"],
                relationships=staged["relationships"],
                generation_id=generation_id,
                source_generation=str(manifest["source_generation"]),
                content_hash=str(manifest["content_hash"]),
                authorization_digest=auth["authorization_digest"],
                attestation_digest=auth["attestation_digest"],
                validation=staged["validation"],
                guard=self._guard_write,
            )
            self.lease.assert_held()
            if kind == "restoration":
                self._reauthorize_restore()
            else:
                self._reauthorize_admission()
            products: dict[str, dict[str, Any]] = {}
            for table, rows in expected.items():
                self.lease.assert_held()
                # Version-pinned readback has no external mutation. Fresh
                # authorization brackets the entire observation; the later
                # receipt/pointer boundary revalidates before any write.
                version = int(written[table]["version"])
                if delta.version(uri(table)) != version:
                    raise PublicationSafetyError(f"product_head_moved:{table}")
                actual = _membership(delta.read(uri(table), version=version), table)
                want = _membership(rows, table)
                if actual != want:
                    raise PublicationSafetyError(f"product_readback_mismatch:{table}")
                products[table] = {
                    "rows": len(rows),
                    "hash": _hash(want),
                    "version": version,
                }
            catalog = _generation_catalog(
                expected, written, generation_id, str(manifest["content_hash"])
            )
            self.lease.assert_held()
            if kind == "restoration":
                self._reauthorize_restore()
            else:
                self._reauthorize_admission()
            if self._catalog_read() != json.loads(json.dumps(catalog)):
                raise PublicationSafetyError("product_catalog_mismatch")
            self.lease.assert_held()
            return self.receipts.put(
                generation_id,
                {
                    "generation_id": generation_id,
                    "source_generation": str(manifest["source_generation"]),
                    "content_hash": str(manifest["content_hash"]),
                    "entity_hash": str(manifest["entity_hash"]),
                    "relationship_hash": str(manifest["relationship_hash"]),
                    "authorization_digest": auth["authorization_digest"],
                    "attestation_digest": auth["attestation_digest"],
                    "target": self._target,
                    "kind": kind,
                    "products": products,
                    "predecessor_versions": {k: v for k, v in before.items()},
                    "catalog_hash": _hash(catalog),
                    "materialized_by": {"owner": ctx.owner_id, "fence": ctx.fence},
                },
            )
        finally:
            # The target-wide lock covers every physical table/catalog write
            # and its readback as one mutation interval, but not non-mutating
            # pointer/audit/post-check work. This lets a fresh process recover
            # after a simulated process death while fencing stale later writes.
            self._mutation_lock.release()

    def __call__(self, candidate: Any) -> Mapping[str, Any]:
        ctx = self._context()
        self._acquire()
        reconciled = self.reconcile()
        if self._runtime_guard is not None:
            self._runtime_guard()
        self._operation_generation = candidate.generation_id
        staged = self._staged(candidate.generation_id)
        if (
            tuple(staged["entities"]) != tuple(candidate.entities)
            or tuple(staged["relationships"]) != tuple(candidate.relationships)
            or staged["manifest"]["source_generation"] != candidate.source_generation
        ):
            raise PublicationSafetyError("candidate_differs_from_immutable_stage")
        auth = self._authorization(candidate.generation_id, staged, mode="admit")
        if (
            reconciled.get("state") == "materialized"
            and reconciled.get("generation_id") == candidate.generation_id
        ):
            receipt = self.receipts.latest(candidate.generation_id)
            if receipt is None:
                raise PublicationSafetyError("product_receipt_missing")
            if (
                receipt.get("content_hash") != staged["manifest"]["content_hash"]
                or receipt.get("authorization_digest") != auth["authorization_digest"]
                or receipt.get("attestation_digest") != auth["attestation_digest"]
            ):
                raise PublicationSafetyError("product_receipt_disagrees_with_candidate")
            self._verify_materialized_heads(receipt)
            self._began = True
            self._mutation_lock.release()
            return {
                "status": "completed",
                "receipt_digest": receipt["receipt_digest"],
                "products": receipt["products"],
                "content_hash": receipt["content_hash"],
                "authorization_digest": receipt["authorization_digest"],
                "attestation_digest": receipt["attestation_digest"],
            }
        predecessor = ctx.predecessor
        prior = self.receipts.latest(predecessor) if predecessor else None
        self._transition(
            "intent",
            operation={
                "generation_id": candidate.generation_id,
                "content_hash": staged["manifest"]["content_hash"],
                "authorization_digest": auth["authorization_digest"],
                "attestation_digest": auth["attestation_digest"],
            },
            predecessor={
                "generation_id": predecessor,
                "pointer_etag": ctx.pointer_etag,
                "receipt_digest": (prior or {}).get("receipt_digest"),
                "products": (prior or {}).get("products"),
            },
            recovery={},
            recovery_intent={},
        )
        self._began = True
        self._fault_at("after_intent")
        self._transition("materializing")
        receipt = self._materialize(candidate.generation_id, staged, auth, kind="materialization")
        self._transition(
            "materialized",
            new={"receipt_digest": receipt["receipt_digest"], "sequence": receipt["sequence"]},
        )
        self._fault_at("after_materialized")
        return {
            "status": "completed",
            "receipt_digest": receipt["receipt_digest"],
            "products": receipt["products"],
            "content_hash": receipt["content_hash"],
            "authorization_digest": receipt["authorization_digest"],
            "attestation_digest": receipt["attestation_digest"],
        }

    def verify_before_cas(self, candidate: Any) -> dict[str, Any]:
        """Candidate, stage, authorization and observed products must agree."""
        self.lease.assert_held()
        if self._runtime_guard is not None:
            self._runtime_guard()
        staged = self._staged(candidate.generation_id)
        self._operation_generation = candidate.generation_id
        receipt = self.receipts.latest(candidate.generation_id)
        if receipt is None:
            raise PublicationSafetyError("product_receipt_missing")
        auth = self._authorization(candidate.generation_id, staged, mode="admit")
        manifest = staged["manifest"]
        if (
            receipt["content_hash"] != manifest["content_hash"]
            or receipt["authorization_digest"] != auth["authorization_digest"]
            or receipt["attestation_digest"] != auth["attestation_digest"]
            or receipt["entity_hash"] != _hash(list(candidate.entities))
            or receipt["relationship_hash"] != _hash(list(candidate.relationships))
        ):
            raise PublicationSafetyError("product_receipt_disagrees_with_candidate")
        self.reader.verify(receipt)
        # Heads must still be the pinned versions (no stray write by anyone).
        for table, product in receipt["products"].items():
            self.lease.assert_held()
            layer, logical = table.split("_", 1)
            head = self._service.delta.version(self._service.onelake.table_uri(layer, logical))
            if head != product["version"]:
                raise PublicationSafetyError(f"product_head_moved:{table}")
        self._reauthorize_admission()
        return receipt

    def record_pointer_committed(self, pointer_etag: str) -> None:
        self._transition("pointer_committed", pointer_etag=pointer_etag)
        self._fault_at("after_pointer_commit")

    def complete(self) -> None:
        self._transition("post_verified")
        self.release()

    # ---------------------------------------------------------------- recovery
    def _active_generation(self) -> str | None:
        snap = self._storage.read_pointer()
        return snap.pointer.active_generation if snap.pointer else None

    def _critical(self, reason: str, exc: BaseException | None = None) -> None:
        # Best effort: lease loss may prevent the durable critical write.
        with contextlib.suppress(Exception):
            self._transition("critical", critical_reason=reason)
        raise MaterializationCritical(reason) from exc

    def quarantine(self, reason: str) -> None:
        self._transition("critical", critical_reason=reason)

    def recover_physical(
        self,
        *,
        reason: str,
        target: str | None = None,
        expected_active: str | None = None,
    ) -> dict[str, Any]:
        """Rematerialize the products of the *currently authoritative* generation.

        Never writes the caller's predecessor over a different winner: the
        pointer is re-read and the exact authorized winner is reconciled.
        """
        self._context()
        try:
            self._acquire()
            self.lease.assert_held()
            self._transition("recovery_required", recovery_reason=reason)
            snapshot = self._storage.read_pointer()
            active = snapshot.pointer.active_generation if snapshot.pointer else None
            winner = expected_active is not None and active != expected_active
            if winner or target is None:
                # A different generation owns the pointer: reconcile *its*
                # exact authorized products; never write a stale predecessor.
                target = active
            if target is None:
                self._transition(
                    "restored",
                    recovery={"physical": False, "pointer": False, "consumer": False,
                              "target_generation": None, "note": "no_authoritative_generation"},
                )
                return {"target_generation": None, "winner_reconciled": False}
            self._restore_pointer = (active, snapshot.etag)
            self._transition(
                "restoring",
                recovery_intent={
                    "target_generation": target,
                    "expected_active": active,
                    "pointer_etag": snapshot.etag,
                    "reason": reason,
                },
                recovery={"target_generation": target},
            )
            staged = self._staged(target)
            self._operation_generation = target
            auth = self._authorization(target, staged, mode="restore")
            self._fault_at("restore_write")
            receipt = self._materialize(target, staged, auth, kind="restoration")
            self._fault_at("after_restore_physical")
            self._transition(
                "restoring",
                recovery={
                    "physical": True,
                    "pointer": self._active_generation() == target,
                    "restored_from": reason,
                    "consumer": False,
                    "target_generation": target,
                    "receipt_digest": receipt["receipt_digest"],
                    "winner_reconciled": winner,
                },
            )
            return {
                "target_generation": target,
                "receipt_digest": receipt["receipt_digest"],
                "winner_reconciled": winner,
            }
        except MaintenanceOwnershipLost as exc:
            self._critical("recovery_ownership_lost", exc)
        except MaterializationCritical:
            raise
        except Exception as exc:  # noqa: BLE001
            self._critical("recovery_failed", exc)
        finally:
            self._restore_pointer = None
        raise AssertionError("unreachable")  # pragma: no cover

    def mark_recovery(self, *, pointer: bool, consumer: bool) -> None:
        current = self.journal.read() or {}
        recovery = dict(current.get("recovery") or {})
        recovery["pointer"] = bool(pointer)
        recovery["consumer"] = bool(consumer)
        phase = "restored" if pointer and consumer else "critical"
        self._transition(phase, recovery=recovery)

    def record_restore_pointer(self) -> None:
        """Crash boundary after pointer CAS, before consumer completion."""
        self._fault_at("after_restore_pointer")

    def recover_after_failure(self, reason: str, *, candidate_generation: str) -> dict[str, Any]:
        if not self._began:
            return {"state": "not_started"}
        active = self._active_generation()
        if active == candidate_generation:
            # CAS did succeed; products are the new authoritative ones.  Leave the
            # journal at pointer_committed for restart/post-check reconciliation.
            return {"state": "pointer_committed"}
        return self.recover_physical(reason=reason)

    def reconcile(self) -> dict[str, Any]:
        """Restart reconciliation of a non-terminal journal against real state."""
        self._acquire()
        current = self.journal.read()
        if current is None or current.get("phase") in TERMINAL_PHASES:
            return {"state": "clean"}
        if (
            current.get("phase") == "critical"
            and current.get("critical_reason") == "rollback_pointer_or_consumer_uncertain"
        ):
            raise MaterializationCritical("rollback_requires_explicit_reconciliation")
        active = self._active_generation()
        operation = (current.get("operation") or {}).get("generation_id")
        self._operation_generation = str(operation) if operation else None
        if current.get("phase") == "materialized" and active != operation:
            snapshot = self._storage.read_pointer()
            predecessor = current.get("predecessor") or {}
            expected_generation = predecessor.get("generation_id")
            expected_etag = predecessor.get("pointer_etag")
            actual_etag = snapshot.etag
            if (
                active == expected_generation
                and actual_etag == expected_etag
                and operation
            ):
                receipt = self.receipts.latest(str(operation))
                if receipt is not None:
                    try:
                        self._verify_materialized_heads(receipt)
                    except (OSError, RuntimeError, ValueError, TypeError):
                        pass
                    else:
                        return {
                            "state": "materialized",
                            "generation_id": str(operation),
                            "receipt_digest": receipt["receipt_digest"],
                        }
        if current.get("phase") == "pointer_committed" and active == operation:
            receipt = self.receipts.latest(active)
            if receipt is None:
                self._critical("committed_generation_without_receipt")
            self.reader.verify(receipt)
            return {"state": "committed", "generation_id": active, "receipt_digest": receipt["receipt_digest"]}
        if current.get("phase") == "critical" or current.get("phase") in {
            "intent", "materializing", "materialized", "pointer_committed",
            "recovery_required", "restoring",
        }:
            result = self.recover_physical(reason=f"reconcile:{current.get('phase')}")
            return {"state": "restored", **result}
        return {"state": "clean"}

    def _verify_materialized_heads(self, receipt: Mapping[str, Any]) -> None:
        """Verify retained exact product versions still occupy every physical head."""
        self._mutation_lock.acquire()
        try:
            self.lease.assert_held()
            self._reauthorize_admission()
            self.reader.verify(receipt)
            for table, product in receipt["products"].items():
                self.lease.assert_held()
                self._reauthorize_admission()
                layer, logical = table.split("_", 1)
                head = self._service.delta.version(
                    self._service.onelake.table_uri(layer, logical)
                )
                if head != product["version"]:
                    raise PublicationSafetyError(f"product_head_moved:{table}")
            self.lease.assert_held()
            self._reauthorize_admission()
            if _hash(self._catalog_read()) != receipt.get("catalog_hash"):
                raise PublicationSafetyError("product_catalog_mismatch")
        finally:
            self._mutation_lock.release()

    def has_open_critical(self) -> bool:
        current = self.journal.read()
        return bool(current and current.get("phase") == "critical")


# ------------------------------------------------------------ consumer observers


class ProductConsumerPorts:
    """Five distinct real read surfaces over staged documents / pinned products."""

    def __init__(
        self,
        *,
        storage: Any,
        reader: PinnedProductReader,
        service: Any,
        definition_fingerprint: Callable[[], str],
        clock: Callable[[], datetime],
    ) -> None:
        self._storage = storage
        self._reader = reader
        self._service = service
        self._definition = definition_fingerprint
        self._clock = clock
        self._n = 0

    def ports(self) -> dict[str, Any]:
        outer = self

        class _Port:
            def __init__(self, family: str) -> None:
                self.family = family

            def observe(self, family: str, generation_id: str, stage: str):
                return outer._observe(family, generation_id, stage)

        return {family: _Port(family) for family in CONSUMER_FAMILIES}

    def _observe(self, family: str, generation_id: str, stage: str) -> ConsumerObservation:
        self._n += 1
        status, result, fingerprint = "pass", "", ""
        try:
            if stage == "staged":
                staged = self._storage.read_generation(generation_id)
                surface = {
                    "api": staged["entities"],
                    "fabric": staged["relationships"],
                    "agent": staged["lineage"],
                    "export": staged["compatibility"],
                    "semantic": staged["validation"],
                }[family]
                ok = (
                    staged["manifest"].get("complete") is True
                    and staged["validation"].get("passed") is True
                    and staged["compatibility"].get("all_consumers_compatible") is True
                )
                status = "pass" if ok else "fail"
                result = _hash(surface)
            else:
                active, receipt = self._reader.active()
                if active != generation_id or receipt is None:
                    status = "fail"
                    result = _hash({"active": active, "wanted": generation_id})
                else:
                    fingerprint = str(receipt["receipt_digest"])
                    result, status = self._surface(family, receipt)
        except Exception as exc:  # noqa: BLE001 - an unreadable surface is a fail
            status, result = "fail", _hash({"error": type(exc).__name__, "family": family})
        return ConsumerObservation(
            family=family,
            observer_id=f"product-observer:{family}",
            source_id=f"product-surface:{family}",
            capture_id=f"{family}-{uuid.uuid4().hex[:12]}-{self._n}",
            result_hash=_hash({"family": family, "result": result, "n": self._n}),
            generation_id=generation_id,
            stage=stage,
            definition_fingerprint=self._definition(),
            product_fingerprint=fingerprint,
            observed_at=self._clock(),
            status=status,
        )

    def _surface(self, family: str, receipt: Mapping[str, Any]) -> tuple[str, str]:
        reader = self._reader
        staged = self._storage.read_generation(receipt["generation_id"])
        if family == "api":
            rows = reader.read_table("ontology_relationships", receipt)
            ok = _membership(rows, "ontology_relationships") == _membership(
                staged["relationships"], "ontology_relationships"
            )
            return _hash(_membership(rows, "ontology_relationships")), "pass" if ok else "fail"
        if family == "fabric":
            tables = sorted(t for t in receipt["products"] if t.startswith("ontology_rel_"))
            digest = {t: _hash(_membership(reader.read_table(t, receipt), t)) for t in tables}
            ok = all(digest[t] == receipt["products"][t]["hash"] for t in tables)
            return _hash(digest), "pass" if ok else "fail"
        if family == "agent":
            entities, relationships = self._service._read_authoritative_ontology()
            ok = _membership(relationships, "ontology_relationships") == _membership(
                staged["relationships"], "ontology_relationships"
            ) and _membership(entities, "ontology_entities") == _membership(
                staged["entities"], "ontology_entities"
            )
            return _hash([len(entities), len(relationships)]), "pass" if ok else "fail"
        if family == "export":
            rows = reader.read_table("ontology_entities", receipt)
            catalog_ok = True
            try:
                catalog = json.loads(json.dumps(
                    _generation_catalog(
                        {t: [None] * p["rows"] for t, p in receipt["products"].items()},
                        {t: {"version": p["version"]} for t, p in receipt["products"].items()},
                        receipt["generation_id"], receipt["content_hash"],
                    )
                ))
                catalog_ok = _hash(catalog) == receipt["catalog_hash"]
            except Exception:  # noqa: BLE001
                catalog_ok = False
            ok = catalog_ok and _hash(_membership(rows, "ontology_entities")) == receipt["products"]["ontology_entities"]["hash"]
            return _hash(_membership(rows, "ontology_entities")), "pass" if ok else "fail"
        health = reader.read_table("ontology_health", receipt)
        quality = reader.read_table("ontology_quality_report", receipt)
        ok = (
            len(health) == 1
            and health[0]["resource_id"] == f"ontology-health://{receipt['generation_id']}"
            and health[0]["relationship_count"] == len(staged["relationships"])
            and len(quality) == 1
            and quality[0]["passed"] is True
        )
        return _hash([health, quality]), "pass" if ok else "fail"


def utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "CandidateGenerationMaterializer",
    "MaintenanceOwnershipLost",
    "MaterializationCritical",
    "PinnedProductReader",
    "ProductConsumerPorts",
    "ProductReceiptStore",
    "RecoveryJournal",
    "TargetLease",
]
