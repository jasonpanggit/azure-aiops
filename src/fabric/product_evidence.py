"""Recorded publisher facts, never inferred active-product or query readiness."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

from .schema_registry import PRODUCT_CONTRACTS

if TYPE_CHECKING:
    from .sync_service import FabricSyncResult, FabricSyncService

CONTRACT = "fabric-product-publication/1"
STAGES = ("acquired", "validated", "persisted", "registered", "active", "consumer_query_verified")
_RECORDED_STAGES = frozenset({"validated", "persisted"})
_MAX_BYTES = 64 * 1024
_LOGGER = logging.getLogger(__name__)


class ProductEvidenceError(RuntimeError):
    """A receipt is malformed, ambiguous or inconsistent with its exact scope."""


def _scope(value: Mapping[str, list[str]]) -> dict[str, list[str]]:
    if set(value) != {"subscription"}:
        raise ProductEvidenceError("Publication receipts require exact subscription scope")
    values = value["subscription"]
    if not isinstance(values, list) or not 1 <= len(values) <= 100:
        raise ProductEvidenceError("Publication subscription scope is invalid")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 256 for item in values):
        raise ProductEvidenceError("Publication subscription identity is invalid")
    return {"subscription": sorted({item.strip().casefold() for item in values})}


def _stamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ProductEvidenceError("Publication receipt timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ProductEvidenceError("Publication receipt timestamp requires timezone")
    return parsed.astimezone(UTC).isoformat()


def _identity(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ProductEvidenceError("Publication receipt generation identity is invalid")
    return value


def unknown_product_evidence(table_name: str, reason: str) -> dict[str, Any]:
    """Return all independent stages as unknown, without a successful fallback."""
    return {
        "contract": CONTRACT,
        "table_name": table_name,
        "evidence_mode": "not_recorded",
        "publication_attempt": None,
        "stages": {
            stage: {
                "status": "unknown", "evidence_mode": "not_recorded",
                "reason_code": reason, "last_attempt": None, "last_good": None,
            }
            for stage in STAGES
        },
    }


class ProductEvidenceStore:
    """One exact-scope document holding bounded publisher attempts and last-good facts.

    No table scans, credential selection, retries or registration side effects
    occur. Store roots are supplied by trusted server/publisher composition.
    """

    def __init__(self, documents: OneLakeDocumentStore) -> None:
        self.documents = documents

    @staticmethod
    def _name(scope: dict[str, list[str]]) -> str:
        digest = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
        return f"fabric/product-publication/{digest}.json"

    def _load(self, scope: dict[str, list[str]]):
        snapshot = self.documents.read_snapshot(self._name(scope))
        payload = snapshot.payload
        if snapshot.exists:
            self._validate(payload, scope)
        return snapshot

    @staticmethod
    def _validate(payload: dict[str, Any], scope: dict[str, list[str]]) -> None:
        if len(json.dumps(payload).encode()) > _MAX_BYTES:
            raise ProductEvidenceError("Publication receipt exceeds size limit")
        if set(payload) != {"contract", "scope", "attempt", "records"}:
            raise ProductEvidenceError("Publication receipt fields are invalid")
        if payload.get("contract") != CONTRACT or payload.get("scope") != scope:
            raise ProductEvidenceError("Publication receipt contract or scope mismatch")
        attempt = payload.get("attempt")
        if not isinstance(attempt, dict) or attempt.get("status") not in {"running", "completed", "failed"}:
            raise ProductEvidenceError("Publication attempt is invalid")
        if set(attempt) != {
            "attempt_id", "source_generation", "publication_run_id", "status",
            "attempted_at", "observed_at",
        }:
            raise ProductEvidenceError("Publication attempt fields are invalid")
        _identity(attempt.get("attempt_id"))
        _identity(attempt.get("source_generation"))
        started = _stamp(attempt.get("attempted_at"))
        observed = _stamp(attempt.get("observed_at"))
        if observed < started:
            raise ProductEvidenceError("Publication receipt clock moved backwards")
        if attempt["status"] == "completed":
            _identity(attempt.get("publication_run_id"))
        elif attempt["publication_run_id"] is not None:
            raise ProductEvidenceError("Incomplete publication has a completed run identity")
        records = payload.get("records")
        if not isinstance(records, dict) or set(records) != set(PRODUCT_CONTRACTS):
            raise ProductEvidenceError("Publication receipt product set is invalid")
        for stages in records.values():
            if not isinstance(stages, dict) or set(stages) != set(STAGES):
                raise ProductEvidenceError("Publication receipt stages are invalid")
            for stage, record in stages.items():
                if not isinstance(record, dict) or set(record) != {"last_attempt", "last_good"}:
                    raise ProductEvidenceError("Publication receipt stage is malformed")
                for key, fact in record.items():
                    if fact is None:
                        continue
                    if stage not in _RECORDED_STAGES or not isinstance(fact, dict):
                        raise ProductEvidenceError("Unsupported publication qualification")
                    if set(fact) != {"attempt_id", "source_generation", "publication_run_id", "observed_at", "scope"}:
                        raise ProductEvidenceError("Publication stage fact is malformed")
                    for field in ("attempt_id", "source_generation", "publication_run_id"):
                        _identity(fact[field])
                    if fact["scope"] != scope or _stamp(fact["observed_at"]) > observed:
                        raise ProductEvidenceError("Publication stage fact scope or time mismatch")
                    if key == "last_attempt" and (
                        attempt["status"] != "completed"
                        or any(fact[field] != attempt[field] for field in (
                            "attempt_id", "source_generation", "publication_run_id", "observed_at"
                        ))
                    ):
                        raise ProductEvidenceError("Publication stage belongs to another attempt")
                if record["last_attempt"] is not None and record["last_good"] != record["last_attempt"]:
                    raise ProductEvidenceError("Publication successful stage has inconsistent last-good")

    def begin(self, scope: dict[str, list[str]], source_generation: str, observed_at: str) -> str:
        """Record a new attempt before sync; preserve prior success without promoting it."""
        scope = _scope(scope)
        snapshot = self._load(scope)
        payload = snapshot.payload
        stamp = _stamp(observed_at)
        if payload and stamp < _stamp(payload["attempt"]["observed_at"]):
            raise ProductEvidenceError("Publication receipt clock moved backwards")
        records = {
            name: {
                stage: {
                    "last_attempt": None,
                    "last_good": payload.get("records", {}).get(name, {}).get(stage, {}).get("last_good"),
                }
                for stage in STAGES
            }
            for name in PRODUCT_CONTRACTS
        }
        attempt_id = str(uuid.uuid4())
        body = {
            "contract": CONTRACT, "scope": scope, "records": records,
            "attempt": {
                "attempt_id": attempt_id, "source_generation": _identity(source_generation),
                "publication_run_id": None, "status": "running",
                "attempted_at": stamp, "observed_at": stamp,
            },
        }
        self._save(scope, body, snapshot.etag)
        return attempt_id

    def finish(
        self, scope: dict[str, list[str]], attempt_id: str, observed_at: str, *,
        result: FabricSyncResult | None,
    ) -> None:
        """Record completed sync validation/persistence, not registration or activation."""
        scope = _scope(scope)
        snapshot = self._load(scope)
        body = snapshot.payload
        if not body or body["attempt"]["attempt_id"] != attempt_id:
            raise DocumentConflictError("Publication receipt attempt was superseded")
        attempt = body["attempt"]
        if attempt["status"] != "running":
            raise DocumentConflictError("Publication receipt attempt is already terminal")
        attempt["observed_at"] = _stamp(observed_at)
        succeeded = result is not None and result.status == "completed" and result.failed_records == 0
        attempt["status"] = "completed" if succeeded else "failed"
        if succeeded:
            if result.source_run_id != attempt["source_generation"]:
                raise ProductEvidenceError("Publication result source generation mismatch")
            attempt["publication_run_id"] = _identity(result.run_id)
            for name in set(result.tables).intersection(PRODUCT_CONTRACTS):
                for stage in _RECORDED_STAGES:
                    fact = {
                        key: attempt[key] for key in (
                            "attempt_id", "source_generation", "publication_run_id", "observed_at"
                        )
                    }
                    fact["scope"] = scope
                    body["records"][name][stage] = {"last_attempt": fact, "last_good": fact}
        self._save(scope, body, snapshot.etag)

    def _save(self, scope, body, etag):
        self._validate(body, scope)
        name = self._name(scope)
        if etag is None:
            self.documents.create_only(name, body)
        else:
            self.documents.replace_if_match(name, body, expected_etag=etag)

    def read(self, table_name: str, requested_scope: dict[str, list[str]]) -> dict[str, Any]:
        """Read only one exact subscription-set receipt, never broaden a connection request."""
        if table_name not in PRODUCT_CONTRACTS:
            return unknown_product_evidence(table_name, "product_not_declared")
        if set(requested_scope) != {"subscription"}:
            return unknown_product_evidence(table_name, "no_exact_subscription_publication_receipt")
        scope = _scope(requested_scope)
        payload = self._load(scope).payload
        if not payload:
            return unknown_product_evidence(table_name, "no_recorded_product_publication")
        result = unknown_product_evidence(table_name, "no_stage_qualification_recorded")
        result["evidence_mode"] = "recorded_publisher_outcome"
        result["publication_attempt"] = {**payload["attempt"], "scope": scope}
        for stage, record in payload["records"][table_name].items():
            result["stages"][stage].update(record)
            if record["last_attempt"]:
                result["stages"][stage].update(
                    status="recorded", evidence_mode="recorded_publisher_outcome",
                    reason_code="publisher_stage_completed_not_consumer_qualification",
                )
        return result


def publish_with_product_evidence(
    service: FabricSyncService, store: ProductEvidenceStore, *,
    source_generation: str, scope: dict[str, list[str]],
    assert_lock_held: Callable[[], None], clock: Callable[[], str] | None = None,
    **sync_kwargs: Any,
) -> FabricSyncResult:
    """Wrap the existing producer without interpreting progress telemetry as acceptance."""
    now = clock or (lambda: datetime.now(UTC).isoformat())
    assert_lock_held()
    attempt = store.begin(scope, source_generation, now())
    try:
        result = service.sync(
            replay_source_run_id=source_generation, requested_scope=scope, **sync_kwargs,
        )
    except Exception:
        # A lost lease must not let an old worker overwrite a newer receipt.
        assert_lock_held()
        store.finish(scope, attempt, now(), result=None)
        raise
    assert_lock_held()
    try:
        store.finish(scope, attempt, now(), result=result)
    except Exception:
        _LOGGER.exception(
            "Product publication returned but its completion receipt could not be recorded",
            extra={"error_code": "PRODUCT_PUBLICATION_RECEIPT_FAILED"},
        )
        raise
    return result
