"""Scope-first durable ontology discovery, publication, and evaluation APIs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Annotated, Any

from fastapi import APIRouter, Query

from ontology_discovery.command_intake import (
    CommandIntakeService,
    scope_receipt,
)
from ontology_discovery.evaluation import EvaluationSnapshot
from ontology_discovery.evaluation_store import (
    EvaluationSnapshotStore,
    SnapshotIntegrityError,
)
from ontology_discovery.store import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RETRYING,
    RUN_RUNNING,
    TERMINAL_STATUSES,
    OntologyRunStore,
    ProposalReviewConflict,
    RunClaimConflict,
)

from ..dependencies import (
    ApprovePrincipal,
    Context,
    MaintainOntologyPrincipal,
    OperatePrincipal,
    Page,
    ReadScope,
    RequestedScope,
)
from ..errors import ApiError, ErrorCode, scrub
from ..evidence import CONFIDENCE_HIGH, Evidence, envelope
from ..models import (
    OntologyMaintenanceRequest,
    OntologyProposalReviewRequest,
    OntologyRollbackRequest,
    OntologyRunMutationRequest,
    OntologyRunNowRequest,
)
from ..rbac import (
    ACTION_APPROVE,
    ACTION_MAINTAIN_ONTOLOGY,
    ACTION_OPERATE,
    Principal,
)
from ..scope import Scope

router = APIRouter(
    prefix="/api/v1/ontology-discovery",
    tags=["ontology-discovery"],
)

ConnectionId = Annotated[str, Query(min_length=1, max_length=160)]
SOURCE_ENGINE = "ontology_discovery.durable_services"
SOURCE_TABLE = "ontology_discovery_runs"
_RUN_FIELDS = (
    "run_id",
    "connection_id",
    "source_generation_id",
    "trigger",
    "status",
    "revision",
    "attempt_count",
    "max_attempts",
    "created_at",
    "updated_at",
    "deadline_at",
    "next_attempt_at",
    "lease_expires_at",
    "fencing_token",
    "cancel_requested",
    "checkpoint",
    "failure_class",
    "message",
)
_PROPOSAL_FIELDS = (
    "subject_id",
    "subject_type",
    "predicate",
    "object_id",
    "object_type",
    "rationale",
    "confidence",
    "freshness",
)
_CHECKPOINT_PAYLOAD_FIELDS = (
    "generation_id",
    "active_generation",
    "source_generation",
    "pointer_etag",
    "fabric_run_id",
    "fabric_status",
    "proposal_count",
    "accepted_count",
    "published_count",
)


def evaluation_scope_key(connection: Mapping[str, object]) -> str:
    """Return the opaque, deterministic evaluation identity for a connection."""

    payload = {
        "connection_id": str(connection.get("connection_id") or "").casefold(),
        "subscription_id": str(connection.get("subscription_id") or "").casefold(),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"scope-{digest[:32]}"


class OntologyDiscoveryApi:
    """Read/action facade over durable services without publication authority."""

    def __init__(
        self,
        *,
        onboarding: Any,
        run_store: OntologyRunStore,
        evaluation_store: EvaluationSnapshotStore | None = None,
        generation_resolver_factory: Callable[[str], Any | None] | None = None,
        rollback_action: Callable[..., Mapping[str, Any]] | None = None,
        command_intake: CommandIntakeService | None = None,
        connection_reader: Callable[[str], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.onboarding = onboarding
        self.run_store = run_store
        self.evaluation_store = evaluation_store
        self._generation_resolver_factory = generation_resolver_factory
        self._rollback_action = rollback_action
        self.command_intake = command_intake
        self._connection_reader = connection_reader
        self._clock = clock or (lambda: datetime.now(UTC))

    def connection(self, connection_id: str) -> dict[str, Any]:
        if self._connection_reader is not None:
            connection = self._connection_reader(connection_id)
            if hasattr(connection, "to_dict"):
                return dict(connection.to_dict())
            return dict(connection)
        return self.onboarding.detail(connection_id)

    def _command_connection(self, connection_id: str) -> Any:
        if self._connection_reader is not None:
            return self._connection_reader(connection_id)
        return self.onboarding.registry.get(connection_id)

    def command(self, command_id: str) -> dict[str, Any] | None:
        if self.command_intake is None:
            return None
        command = self.command_intake.get(command_id)
        return self._project_command(command) if command is not None else None

    def runs(self, connection_id: str) -> list[dict[str, Any]]:
        return [
            self._project_run(row)
            for row in self.run_store.list_runs(connection_id=connection_id)
        ]

    def run(self, connection_id: str, run_id: str) -> dict[str, Any] | None:
        record = self.run_store.get(run_id)
        if record is None or record["connection_id"] != connection_id.casefold():
            return None
        return self._project_run(record)

    def run_now(
        self,
        connection_id: str,
        *,
        actor: str,
        idempotency_key: str,
        reason: str,
    ) -> dict[str, Any]:
        active = next(
            (
                row
                for row in self.run_store.list_runs(connection_id=connection_id)
                if row["status"] not in TERMINAL_STATUSES
            ),
            None,
        )
        if active is not None:
            raise RunClaimConflict("active_run_exists", active)
        if self.command_intake is not None:
            connection = self._command_connection(connection_id)
            moment = self._clock()
            command = self.command_intake.enqueue_manual_run(
                actor_hash=_opaque_hash(actor),
                effective_scope_hash=scope_receipt(
                    connection, "ontology.discovery.run"
                ),
                connection_id=connection_id,
                action="ontology.discovery.run",
                issued_at=moment,
                expires_at=moment + timedelta(minutes=15),
                idempotency_key=idempotency_key,
                reason=reason,
            )
            return self._project_command(command)
        result = self.onboarding.enqueue_ontology_refresh(
            connection_id,
            mode="manual",
            requested_by=actor,
        )
        record = self.run_store.get(result["run_id"])
        if record is None:
            raise RuntimeError("durable run was not created")
        return self._project_run(record)

    def cancel(
        self,
        connection_id: str,
        run_id: str,
        *,
        expected_revision: int,
        actor: str,
        reason: str,
    ) -> dict[str, Any] | None:
        if self.run(connection_id, run_id) is None:
            return None
        return self._project_run(
            self.run_store.request_cancel(
                run_id,
                expected_revision=expected_revision,
                actor=actor,
                reason=reason,
                now=self._clock(),
            )
        )

    def retry(
        self,
        connection_id: str,
        run_id: str,
        *,
        expected_revision: int,
        actor: str,
        reason: str,
    ) -> dict[str, Any] | None:
        if self.run(connection_id, run_id) is None:
            return None
        return self._project_run(
            self.run_store.request_retry(
                run_id,
                expected_revision=expected_revision,
                actor=actor,
                reason=reason,
                now=self._clock(),
            )
        )

    def proposals(self, connection: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [
            self._project_proposal(row)
            for row in self.run_store.list_proposals()
            if self._proposal_matches(row, connection)
        ]

    def proposal(
        self,
        connection: Mapping[str, Any],
        proposal_id: str,
    ) -> dict[str, Any] | None:
        return next(
            (
                row
                for row in self.proposals(connection)
                if row["proposal_id"] == proposal_id
            ),
            None,
        )

    def review(
        self,
        connection: Mapping[str, Any],
        proposal_id: str,
        *,
        action: str,
        expected_revision: int,
        actor: str,
        actor_roles: set[str],
        reason: str,
    ) -> dict[str, Any] | None:
        if self.proposal(connection, proposal_id) is None:
            return None
        review = self.run_store.review_proposal(
            proposal_id,
            action=action,
            expected_revision=expected_revision,
            actor=actor,
            actor_roles=actor_roles,
            reason=reason,
            now=self._clock(),
        )
        return self._project_review(review)

    def generation(self, connection_id: str) -> dict[str, Any]:
        resolver = (
            self._generation_resolver_factory(connection_id)
            if self._generation_resolver_factory is not None
            else None
        )
        if resolver is None:
            return self._missing_generation("generation_provider_unavailable")
        try:
            selection = resolver.resolve()
            manifest = resolver.read_metadata("manifest.json", selection=selection)
            validation = resolver.read_metadata("validation.json", selection=selection)
            compatibility = resolver.read_metadata(
                "compatibility.json", selection=selection
            )
            audit_intent = resolver.read_metadata(
                "audit-intent.json", selection=selection
            )
            audit_result = resolver.read_metadata(
                "audit-result.json", selection=selection
            )
        except (LookupError, OSError, TypeError, ValueError):
            return self._missing_generation("generation_pointer_unavailable")
        prior_generation = _generation_id(selection.prior_generation)
        can_rollback = bool(
            prior_generation
            and selection.pointer_etag
            and (self.command_intake is not None or self._rollback_action is not None)
        )
        reason = ""
        if not prior_generation:
            reason = "prior_generation_unavailable"
        elif not selection.pointer_etag:
            reason = "generation_pointer_etag_unavailable"
        elif self.command_intake is None and self._rollback_action is None:
            reason = "publisher_action_unavailable"
        return {
            "status": "active",
            "active_generation": selection.generation_id,
            "prior_generation": prior_generation,
            "source_generation": selection.source_generation,
            "pointer_etag": selection.pointer_etag,
            "fence": int(manifest.get("fence") or 0),
            "complete": manifest.get("complete") is True,
            "validation": {
                "passed": validation.get("passed") is True,
                "errors": list(validation.get("errors") or ())[:100],
                "model_derived_relationships": int(
                    validation.get("model_derived_relationships") or 0
                ),
            },
            "compatibility": {
                "all_consumers_compatible": (
                    compatibility.get("all_consumers_compatible") is True
                )
            },
            "publication": {
                "intent": str(audit_intent.get("outcome") or ""),
                "result": str(audit_result.get("outcome") or ""),
            },
            "can_rollback": can_rollback,
            "rollback_disabled_reason": reason,
        }

    def rollback(
        self,
        connection_id: str,
        generation_id: str,
        *,
        expected_etag: str,
        actor: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        generation = self.generation(connection_id)
        if generation_id != generation.get("prior_generation"):
            return None
        if expected_etag != generation.get("pointer_etag"):
            raise ApiError(
                ErrorCode.CONFLICT,
                "The active generation changed; refresh before rollback",
                {
                    "expected_etag": expected_etag,
                    "current_etag": generation.get("pointer_etag") or "",
                },
            )
        if not generation["can_rollback"]:
            raise ApiError(
                ErrorCode.CONFLICT,
                "Rollback is not currently eligible",
                {"reason": generation["rollback_disabled_reason"]},
            )
        if self.command_intake is not None:
            connection = self._command_connection(connection_id)
            moment = self._clock()
            return self._project_command(
                self.command_intake.enqueue_rollback(
                    actor_hash=_opaque_hash(actor),
                    effective_scope_hash=scope_receipt(
                        connection, "ontology.publication.rollback"
                    ),
                    connection_id=connection_id,
                    action="ontology.publication.rollback",
                    issued_at=moment,
                    expires_at=moment + timedelta(minutes=15),
                    idempotency_key=idempotency_key,
                    reason=reason,
                    target_generation_id=generation_id,
                    observed_active_generation=str(generation["active_generation"]),
                    observed_pointer_etag=expected_etag,
                )
            )
        if self._rollback_action is None:
            raise ApiError(
                ErrorCode.CONFLICT,
                "Rollback command intake is unavailable",
                {"reason": "command_intake_unavailable"},
            )
        return dict(
            self._rollback_action(
                connection_id=connection_id,
                generation_id=generation_id,
                expected_etag=expected_etag,
                actor=actor,
                reason=reason,
                idempotency_key=idempotency_key,
            )
        )

    def request_full_reconciliation(
        self,
        connection_id: str,
        *,
        expected_revision: int,
        actor: str,
        reason: str,
        idempotency_key: str,
        cadence_seconds: int | None,
    ) -> dict[str, Any]:
        if self.command_intake is None:
            raise ApiError(
                ErrorCode.CONFLICT,
                "Ontology maintenance command intake is unavailable",
            )
        detail = self.connection(connection_id)
        environment = str(detail.get("environment") or "").strip().casefold()
        if not environment or environment == "production":
            raise ApiError(
                ErrorCode.CONFLICT,
                "Full reconciliation maintenance is non-production only",
                {"reason": "non_production_environment_required"},
            )
        control = self.run_store.get_reconciliation_control(connection_id)
        current_revision = int((control or {}).get("revision") or 0)
        if current_revision != expected_revision:
            raise ApiError(
                ErrorCode.CONFLICT,
                "The reconciliation cadence changed; refresh before acting",
                {"current_revision": current_revision},
            )
        connection = self._command_connection(connection_id)
        moment = self._clock()
        command = self.command_intake.enqueue_mark_full_reconciliation_due(
            actor_hash=_opaque_hash(actor),
            effective_scope_hash=scope_receipt(
                connection, "ontology.discovery.maintenance"
            ),
            connection_id=connection_id,
            action="ontology.discovery.maintenance",
            issued_at=moment,
            expires_at=moment + timedelta(minutes=15),
            idempotency_key=idempotency_key,
            reason=reason,
            expected_cadence_revision=current_revision,
            cadence_seconds=cadence_seconds,
        )
        return self._project_command(command)

    def evaluation(self, connection: Mapping[str, Any]) -> dict[str, Any]:
        if self.evaluation_store is None:
            return _evaluation_missing("evaluation_provider_unavailable")
        scope_hash = evaluation_scope_key(connection).removeprefix("scope-")
        lookup = self.evaluation_store.latest(scope_hash, now=self._clock())
        snapshot = (
            self._project_snapshot(lookup.snapshot)
            if lookup.snapshot is not None
            else None
        )
        release_eligible = bool(
            lookup.status.value == "fresh"
            and lookup.snapshot is not None
            and lookup.snapshot.release_eligible
        )
        disabled_reason = ""
        if not release_eligible:
            disabled_reason = (
                lookup.reason
                if lookup.status.value != "fresh"
                else "evaluation_release_ineligible"
            )
        return {
            "status": lookup.status.value,
            "reason": lookup.reason,
            "pointer_revision": lookup.pointer_revision,
            "snapshot": snapshot,
            "release_eligible": release_eligible,
            "release_disabled_reason": disabled_reason,
        }

    def evaluations(self, connection: Mapping[str, Any]) -> list[dict[str, Any]]:
        if self.evaluation_store is None:
            return []
        scope_hash = evaluation_scope_key(connection).removeprefix("scope-")
        try:
            snapshots = self.evaluation_store.history(
                scope_hash,
                limit=self.evaluation_store.max_snapshots_per_scope,
            )
        except (OSError, ValueError, SnapshotIntegrityError):
            return []
        return [self._project_snapshot(snapshot) for snapshot in snapshots]

    def status(self, connection: Mapping[str, Any]) -> dict[str, Any]:
        connection_id = str(connection["connection_id"])
        runs = self.runs(connection_id)
        current = runs[0] if runs else None
        proposals = self.proposals(connection)
        pending = [
            self._project_pending(row)
            for row in self.run_store.list_pending_relationships(include_terminal=False)
            if self._scope_text_matches(str(row.get("scope") or ""), connection)
        ][:500]
        return {
            "scheduler": {
                "owner": "external_job",
                "api_owned": False,
                "state": "available",
                "can_run_now": current is None
                or current["status"] in TERMINAL_STATUSES,
                "run_now_disabled_reason": (
                    ""
                    if current is None or current["status"] in TERMINAL_STATUSES
                    else "active_run_exists"
                ),
            },
            "current_run": current,
            "incremental": {
                "checkpoint": (
                    current["checkpoint"]["name"] if current is not None else ""
                ),
                "pending_relationships": pending,
                "pending_count": len(pending),
            },
            "proposals": {
                "pending_count": sum(
                    row["review"]["status"] == "pending" for row in proposals
                ),
                "total": len(proposals),
            },
            "generation": self.generation(connection_id),
            "evaluation": self.evaluation(connection),
        }

    @staticmethod
    def _project_run(record: Mapping[str, Any]) -> dict[str, Any]:
        projected = {field: record.get(field) for field in _RUN_FIELDS}
        checkpoint = record.get("checkpoint")
        payload = checkpoint.get("payload") if isinstance(checkpoint, Mapping) else {}
        projected["checkpoint"] = {
            "name": (
                str(checkpoint.get("name") or "")
                if isinstance(checkpoint, Mapping)
                else ""
            ),
            "payload": {
                field: payload.get(field)
                for field in _CHECKPOINT_PAYLOAD_FIELDS
                if isinstance(payload, Mapping) and field in payload
            },
        }
        projected["message"] = scrub(record.get("message"))
        status = str(record.get("status") or "")
        can_cancel = status in {RUN_QUEUED, RUN_RUNNING, RUN_RETRYING}
        can_retry = status in {RUN_FAILED, RUN_CANCELLED} and int(
            record.get("attempt_count") or 0
        ) < int(record.get("max_attempts") or 0)
        projected.update(
            {
                "can_cancel": can_cancel,
                "can_retry": can_retry,
                "disabled_reasons": {
                    "cancel": "" if can_cancel else "run_not_cancellable",
                    "retry": (
                        ""
                        if can_retry
                        else (
                            "attempts_exhausted"
                            if status in {RUN_FAILED, RUN_CANCELLED}
                            else "run_not_terminal"
                        )
                    ),
                },
            }
        )
        return projected

    @staticmethod
    def _project_review(review: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "proposal_id": str(review.get("proposal_id") or ""),
            "status": str(review.get("status") or "pending"),
            "revision": int(review.get("revision") or 0),
            "events": [
                {
                    key: event.get(key)
                    for key in (
                        "revision",
                        "action",
                        "status",
                        "actor_roles",
                        "policy_version",
                        "approved_at",
                        "proposer_identity",
                        "separation_of_duty",
                        "reason",
                        "recorded_at",
                    )
                }
                for event in list(review.get("events") or ())[-50:]
                if isinstance(event, Mapping)
            ],
        }

    @classmethod
    def _project_proposal(cls, record: Mapping[str, Any]) -> dict[str, Any]:
        proposal = record.get("proposal")
        safe_proposal = {
            field: proposal.get(field)
            for field in _PROPOSAL_FIELDS
            if isinstance(proposal, Mapping) and field in proposal
        }
        return {
            "proposal_id": str(record.get("proposal_id") or ""),
            "proposal": safe_proposal,
            "proposer_identity": str(record.get("proposer_identity") or ""),
            "proposer_kind": str(record.get("proposer_kind") or ""),
            "source_generation_id": str(record.get("source_generation_id") or ""),
            "schema_version": str(record.get("schema_version") or ""),
            "policy_version": str(record.get("policy_version") or ""),
            "supersedes_proposal_id": str(record.get("supersedes_proposal_id") or ""),
            "created_at": str(record.get("created_at") or ""),
            "review": cls._project_review(record.get("review") or {}),
        }

    @staticmethod
    def _project_pending(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: record.get(key)
            for key in (
                "pending_id",
                "subject_id",
                "predicate",
                "object_id",
                "missing_endpoint_ids",
                "attempts",
                "freshness",
                "terminal_state",
                "revision",
                "created_at",
                "updated_at",
            )
        }

    @staticmethod
    def _project_command(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: record.get(key)
            for key in (
                "command_id",
                "type",
                "connection_id",
                "status",
                "revision",
                "reason_code",
                "created_at",
                "updated_at",
                "target_generation_id",
                "observed_active_generation",
                "observed_pointer_etag",
            )
            if key in record
        }

    @staticmethod
    def _project_snapshot(snapshot: EvaluationSnapshot) -> dict[str, Any]:
        return snapshot.model_dump(mode="json")

    @classmethod
    def _proposal_matches(
        cls,
        record: Mapping[str, Any],
        connection: Mapping[str, Any],
    ) -> bool:
        return cls._scope_text_matches(str(record.get("scope") or ""), connection)

    @staticmethod
    def _scope_text_matches(
        value: str,
        connection: Mapping[str, Any],
    ) -> bool:
        tokens = {
            token for token in re.split(r"[^a-z0-9_.-]+", value.casefold()) if token
        }
        identifiers = {
            str(connection.get("connection_id") or "").casefold(),
            str(connection.get("subscription_id") or "").casefold(),
        }
        return any(identifier and identifier in tokens for identifier in identifiers)

    @staticmethod
    def _missing_generation(reason: str) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "active_generation": "",
            "prior_generation": "",
            "source_generation": "",
            "pointer_etag": "",
            "fence": 0,
            "complete": False,
            "validation": {
                "passed": False,
                "errors": [],
                "model_derived_relationships": 0,
            },
            "compatibility": {"all_consumers_compatible": False},
            "publication": {"intent": "", "result": ""},
            "can_rollback": False,
            "rollback_disabled_reason": reason,
        }


def _generation_id(value: object) -> str:
    text = str(value or "").rstrip("/")
    return PurePath(text).name if text else ""


def _opaque_hash(value: object) -> str:
    return hashlib.sha256(str(value or "").strip().encode()).hexdigest()


def _evaluation_missing(reason: str) -> dict[str, Any]:
    return {
        "status": "missing",
        "reason": reason,
        "pointer_revision": None,
        "snapshot": None,
        "release_eligible": False,
        "release_disabled_reason": reason,
    }


def _provider(context: Context) -> OntologyDiscoveryApi:
    factory = context.ontology_discovery_provider
    provider = factory() if factory is not None else None
    if provider is None:
        raise ApiError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            "Ontology discovery data is unavailable",
            {"capability": "ontology_discovery", "provider_state": "unavailable"},
        )
    return provider


def _connection(
    service: OntologyDiscoveryApi,
    connection_id: str,
    scope: Scope,
) -> dict[str, Any]:
    try:
        detail = service.connection(connection_id)
    except Exception as exc:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "No subscription connection matches this scope",
        ) from exc
    attributes = {
        "subscription": detail.get("subscription_id", ""),
        "subscription_connection": detail.get("connection_id", ""),
        **{
            key: detail.get(key, "")
            for key in (
                "business_service",
                "application",
                "environment",
                "criticality",
            )
        },
    }
    if not scope.is_unrestricted() and not scope.matches(attributes):
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "No subscription connection matches this scope",
        )
    return detail


def _evidence(connection_id: str, timestamp: str = "") -> Evidence:
    return Evidence(
        source_engine=SOURCE_ENGINE,
        source_table=SOURCE_TABLE,
        timestamp=timestamp,
        subscription_connection=connection_id,
        confidence=CONFIDENCE_HIGH,
    )


def _run_conflict(exc: RunClaimConflict) -> ApiError:
    return ApiError(
        ErrorCode.CONFLICT,
        "The ontology run changed; refresh before acting",
        {
            "reason": exc.reason,
            "current_revision": int(exc.record.get("revision") or 0),
        },
    )


@router.get("/status", summary="Get durable ontology automation status")
def status(
    connection_id: ConnectionId,
    context: Context,
    scope: ReadScope,
) -> dict[str, Any]:
    service = _provider(context)
    connection = _connection(service, connection_id, scope)
    return envelope(
        service.status(connection),
        evidence=_evidence(connection_id),
        scope=scope.to_dict(),
    )


@router.get("/runs", summary="List durable ontology discovery runs")
def runs(
    connection_id: ConnectionId,
    context: Context,
    scope: ReadScope,
    page: Page,
) -> dict[str, Any]:
    service = _provider(context)
    _connection(service, connection_id, scope)
    rows = service.runs(connection_id)
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_evidence(connection_id),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
    )


@router.post("/runs", summary="Request a durable ontology discovery run")
def run_now(
    payload: OntologyRunNowRequest,
    connection_id: ConnectionId,
    context: Context,
    requested: RequestedScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    scope = context.authorizer.effective_scope(principal, ACTION_OPERATE, requested)
    service = _provider(context)
    _connection(service, connection_id, scope)
    try:
        result = service.run_now(
            connection_id,
            actor=principal.subject,
            idempotency_key=payload.idempotency_key,
            reason=payload.reason,
        )
    except RunClaimConflict as exc:
        raise _run_conflict(exc) from exc
    return envelope(result, evidence=_evidence(connection_id), scope=scope.to_dict())


@router.get("/runs/{run_id}", summary="Get one durable ontology discovery run")
def run_detail(
    run_id: str,
    connection_id: ConnectionId,
    context: Context,
    scope: ReadScope,
) -> dict[str, Any]:
    service = _provider(context)
    _connection(service, connection_id, scope)
    result = service.run(connection_id, run_id)
    if result is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No ontology run matches this scope")
    return envelope(result, evidence=_evidence(connection_id), scope=scope.to_dict())


def _mutate_run(
    operation: str,
    run_id: str,
    payload: OntologyRunMutationRequest,
    connection_id: str,
    context: Context,
    requested: Scope,
    principal: Principal,
) -> dict[str, Any]:
    scope = context.authorizer.effective_scope(principal, ACTION_OPERATE, requested)
    service = _provider(context)
    _connection(service, connection_id, scope)
    try:
        result = getattr(service, operation)(
            connection_id,
            run_id,
            expected_revision=payload.expected_revision,
            actor=principal.subject,
            reason=payload.reason,
        )
    except RunClaimConflict as exc:
        raise _run_conflict(exc) from exc
    if result is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No ontology run matches this scope")
    return envelope(result, evidence=_evidence(connection_id), scope=scope.to_dict())


@router.post("/runs/{run_id}/cancel", summary="Cancel a durable ontology run")
def cancel_run(
    run_id: str,
    payload: OntologyRunMutationRequest,
    connection_id: ConnectionId,
    context: Context,
    requested: RequestedScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    return _mutate_run(
        "cancel", run_id, payload, connection_id, context, requested, principal
    )


@router.post("/runs/{run_id}/retry", summary="Retry a durable ontology run")
def retry_run(
    run_id: str,
    payload: OntologyRunMutationRequest,
    connection_id: ConnectionId,
    context: Context,
    requested: RequestedScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    return _mutate_run(
        "retry", run_id, payload, connection_id, context, requested, principal
    )


@router.get("/proposals", summary="List scoped ontology proposals")
def proposals(
    connection_id: ConnectionId,
    context: Context,
    scope: ReadScope,
    page: Page,
) -> dict[str, Any]:
    service = _provider(context)
    connection = _connection(service, connection_id, scope)
    rows = service.proposals(connection)
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_evidence(connection_id),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
    )


@router.get("/proposals/{proposal_id}", summary="Get one scoped ontology proposal")
def proposal_detail(
    proposal_id: str,
    connection_id: ConnectionId,
    context: Context,
    scope: ReadScope,
) -> dict[str, Any]:
    service = _provider(context)
    connection = _connection(service, connection_id, scope)
    result = service.proposal(connection, proposal_id)
    if result is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No ontology proposal matches this scope")
    return envelope(result, evidence=_evidence(connection_id), scope=scope.to_dict())


@router.post(
    "/proposals/{proposal_id}/review",
    summary="Review an ontology proposal",
)
def review_proposal(
    proposal_id: str,
    payload: OntologyProposalReviewRequest,
    connection_id: ConnectionId,
    context: Context,
    requested: RequestedScope,
    principal: ApprovePrincipal,
) -> dict[str, Any]:
    scope = context.authorizer.effective_scope(principal, ACTION_APPROVE, requested)
    service = _provider(context)
    connection = _connection(service, connection_id, scope)
    try:
        result = service.review(
            connection,
            proposal_id,
            action=payload.action,
            expected_revision=payload.expected_revision,
            actor=principal.subject,
            actor_roles=set(principal.roles()),
            reason=payload.reason,
        )
    except ProposalReviewConflict as exc:
        raise ApiError(
            ErrorCode.CONFLICT,
            "The ontology proposal changed; refresh before deciding",
            {
                "proposal_id": proposal_id,
                "current_revision": int(exc.record.get("revision") or 0),
            },
        ) from exc
    if result is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No ontology proposal matches this scope")
    return envelope(result, evidence=_evidence(connection_id), scope=scope.to_dict())


@router.get("/generations", summary="Get ontology generation and publication state")
def generations(
    connection_id: ConnectionId,
    context: Context,
    scope: ReadScope,
) -> dict[str, Any]:
    service = _provider(context)
    _connection(service, connection_id, scope)
    return envelope(
        service.generation(connection_id),
        evidence=_evidence(connection_id),
        scope=scope.to_dict(),
    )


@router.get("/publications", summary="Get bounded ontology publication history")
def publications(
    connection_id: ConnectionId,
    context: Context,
    scope: ReadScope,
    page: Page,
) -> dict[str, Any]:
    service = _provider(context)
    _connection(service, connection_id, scope)
    rows = [
        row
        for row in service.runs(connection_id)
        if str(row["checkpoint"]["name"]).startswith("publication_")
    ]
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_evidence(connection_id),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
    )


@router.post(
    "/generations/{generation_id}/rollback",
    summary="Request publisher-owned ontology rollback",
)
def rollback_generation(
    generation_id: str,
    payload: OntologyRollbackRequest,
    connection_id: ConnectionId,
    context: Context,
    requested: RequestedScope,
    principal: OperatePrincipal,
) -> dict[str, Any]:
    scope = context.authorizer.effective_scope(principal, ACTION_OPERATE, requested)
    service = _provider(context)
    _connection(service, connection_id, scope)
    result = service.rollback(
        connection_id,
        generation_id,
        expected_etag=payload.expected_etag,
        actor=principal.subject,
        reason=payload.reason,
        idempotency_key=payload.idempotency_key,
    )
    if result is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "No rollback-eligible ontology generation matches this scope",
        )
    return envelope(result, evidence=_evidence(connection_id), scope=scope.to_dict())


@router.post(
    "/connections/{connection_id}/maintenance/full-reconciliation-due",
    summary="Request a non-production full ontology reconciliation",
)
def request_full_reconciliation(
    connection_id: str,
    payload: OntologyMaintenanceRequest,
    context: Context,
    requested: RequestedScope,
    principal: MaintainOntologyPrincipal,
) -> dict[str, Any]:
    scope = context.authorizer.effective_scope(
        principal, ACTION_MAINTAIN_ONTOLOGY, requested
    )
    service = _provider(context)
    _connection(service, connection_id, scope)
    result = service.request_full_reconciliation(
        connection_id,
        expected_revision=payload.expected_revision,
        actor=principal.subject,
        reason=payload.reason,
        idempotency_key=payload.idempotency_key,
        cadence_seconds=payload.cadence_seconds,
    )
    return envelope(result, evidence=_evidence(connection_id), scope=scope.to_dict())


@router.get("/evaluation", summary="Get latest durable ontology evaluation")
def evaluation(
    connection_id: ConnectionId,
    context: Context,
    scope: ReadScope,
) -> dict[str, Any]:
    service = _provider(context)
    connection = _connection(service, connection_id, scope)
    result = service.evaluation(connection)
    timestamp = (
        str((result.get("snapshot") or {}).get("evaluated_at") or "")
        if isinstance(result.get("snapshot"), Mapping)
        else ""
    )
    return envelope(
        result,
        evidence=_evidence(connection_id, timestamp),
        scope=scope.to_dict(),
    )


@router.get("/evaluations", summary="List durable ontology evaluations")
def evaluations(
    connection_id: ConnectionId,
    context: Context,
    scope: ReadScope,
    page: Page,
) -> dict[str, Any]:
    service = _provider(context)
    connection = _connection(service, connection_id, scope)
    rows = service.evaluations(connection)
    return envelope(
        rows[page.offset : page.offset + page.limit],
        evidence=_evidence(connection_id),
        scope=scope.to_dict(),
        pagination=page.to_dict(len(rows)),
    )


__all__ = ["OntologyDiscoveryApi", "evaluation_scope_key", "router"]
