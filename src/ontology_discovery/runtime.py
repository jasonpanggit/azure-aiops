"""Production composition for finite, durable ontology coordinator passes."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from fabric.dataset_mapper import InventoryDatasetMapper
from onboarding.config import ConnectorConfig
from onboarding.credentials import CredentialResolver, default_secret_provider
from onboarding.registry import ConnectionNotFoundError, ConnectionRegistry
from onboarding.runtime import build_connection_inventory_pipeline
from ontology.ontology_validator import OntologyValidator
from ontology.subscription_connection import SubscriptionConnection
from storage.fs import is_onelake_uri
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

from .command_intake import (
    MANUAL_RUN,
    MARK_FULL_RECONCILIATION_DUE,
    CommandConflict,
    CoordinatorCommandConsumer,
    scope_receipt,
)
from .coordinator import (
    BoundedEvidenceProcessor,
    ProposalPolicyCoordinator,
)
from .curator import OntologyCurator
from .dispatch_store import CoordinatorDispatchView, PublisherDispatchStore
from .incremental import classify_incremental, normalize_graph_state
from .policy import ProposalPolicy
from .store import RUN_FAILED, RUN_SUCCEEDED, OntologyRunStore, RunClaimConflict

_ALLOWED_RUNTIME_MODES = frozenset({"production", "validation"})
_FORBIDDEN_COORDINATOR_ENV = frozenset(
    {
        "AIOPS_ONTOLOGY_PUBLICATION_HOME",
        "AIOPS_ONTOLOGY_PUBLISHER_CLIENT_ID",
        "AIOPS_PUBLISHER_CREDENTIAL",
    }
)
_FIXTURE_DOCUMENT = "ontology/validation-fixtures.json"
_FIXTURE_ROLES = ("head-change", "retry-rotation", "later-restart")


def validate_capability_roots(
    *,
    connection_home: str,
    command_home: str,
    state_home: str,
    dispatch_home: str,
) -> dict[str, str]:
    """Validate exact coordinator roots and reject authority aliasing."""

    roots = {
        "connection_home": _required(connection_home, "AIOPS_CONNECTION_HOME"),
        "command_home": _required(command_home, "AIOPS_ONTOLOGY_COMMAND_HOME"),
        "state_home": _required(state_home, "AIOPS_ONTOLOGY_STATE_HOME"),
        "dispatch_home": _required(dispatch_home, "AIOPS_ONTOLOGY_DISPATCH_HOME"),
    }
    normalized = {value.rstrip("/").casefold() for value in roots.values()}
    if len(normalized) != len(roots):
        raise ValueError("Coordinator capability roots must be pairwise distinct")
    return roots


@dataclass(frozen=True)
class ProductionRuntimeConfig:
    """Fail-closed coordinator configuration with no publication capability."""

    runtime_mode: str
    connection_home: str
    command_home: str
    state_home: str
    dispatch_home: str
    foundry_endpoint: str
    agent_name: str
    agent_version: str
    connector_config_path: str

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> ProductionRuntimeConfig:
        values = dict(os.environ if environ is None else environ)
        runtime_mode = _required(
            values.get("AIOPS_RUNTIME_MODE"), "AIOPS_RUNTIME_MODE"
        ).casefold()
        if runtime_mode not in _ALLOWED_RUNTIME_MODES:
            raise ValueError(
                "AIOPS_RUNTIME_MODE must be production or validation"
            )
        for forbidden in _FORBIDDEN_COORDINATOR_ENV:
            if str(values.get(forbidden) or "").strip():
                raise ValueError(
                    "Coordinator publication roots and publisher credentials are forbidden"
                )
        roots = validate_capability_roots(
            connection_home=values.get("AIOPS_CONNECTION_HOME", ""),
            command_home=values.get("AIOPS_ONTOLOGY_COMMAND_HOME", ""),
            state_home=values.get("AIOPS_ONTOLOGY_STATE_HOME", ""),
            dispatch_home=values.get("AIOPS_ONTOLOGY_DISPATCH_HOME", ""),
        )
        if runtime_mode == "production":
            for name, value in roots.items():
                if not is_onelake_uri(value):
                    env_name = {
                        "connection_home": "AIOPS_CONNECTION_HOME",
                        "command_home": "AIOPS_ONTOLOGY_COMMAND_HOME",
                        "state_home": "AIOPS_ONTOLOGY_STATE_HOME",
                        "dispatch_home": "AIOPS_ONTOLOGY_DISPATCH_HOME",
                    }[name]
                    raise ValueError(f"{env_name} must be an explicit OneLake URI")
        return cls(
            runtime_mode=runtime_mode,
            **roots,
            foundry_endpoint=_foundry_endpoint(
                values.get("FOUNDRY_PROJECT_ENDPOINT")
            ),
            agent_name=_required(
                values.get("FOUNDRY_ONTOLOGY_AGENT_NAME"),
                "FOUNDRY_ONTOLOGY_AGENT_NAME",
            ),
            agent_version=_required(
                values.get("FOUNDRY_ONTOLOGY_AGENT_VERSION"),
                "FOUNDRY_ONTOLOGY_AGENT_VERSION",
            ),
            connector_config_path=_required(
                values.get("AIOPS_CONFIG_PATH"), "AIOPS_CONFIG_PATH"
            ),
        )


class CoordinatorIntakeAdapter:
    """Claim untrusted intent and reauthorize it before authoritative writes."""

    def __init__(
        self,
        *,
        registry: ConnectionRegistry,
        commands: CoordinatorCommandConsumer,
        run_store: OntologyRunStore,
        source_generation: Callable[[SubscriptionConnection], str],
        environment: str = "production",
        owner: str = "ontology-coordinator-intake",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._commands = commands
        self._run_store = run_store
        self._source_generation = source_generation
        self._environment = environment.casefold()
        self._owner = _required(owner, "owner")
        self._now = now or (lambda: datetime.now(UTC))

    def process_one(self) -> dict[str, int]:
        moment = self._now()
        due = self._commands.list_due(now=moment, limit=1)
        counts = {"accepted": 0, "denied": 0, "contended": 0}
        if not due:
            return counts
        candidate = due[0]
        try:
            claimed = self._commands.claim(
                candidate["command_id"],
                expected_revision=candidate["revision"],
                owner=self._owner,
                now=moment,
            )
        except CommandConflict:
            counts["contended"] = 1
            return counts

        connection, reason_code = self._authorize(claimed, moment)
        if connection is None:
            self._commands.deny(
                claimed["command_id"],
                expected_revision=claimed["revision"],
                owner=self._owner,
                reason_code=reason_code,
                authorization_audit=_authorization_audit(
                    claimed, outcome="denied", reason_code=reason_code
                ),
                now=moment,
            )
            counts["denied"] = 1
            return counts

        try:
            if claimed["type"] == MANUAL_RUN:
                self._run_store.get_or_create_run(
                    connection_id=connection.connection_id,
                    source_generation_id=self._source_generation(connection),
                    trigger="manual",
                    requested_by=claimed["actor_hash"],
                    metadata={"command_id": claimed["command_id"]},
                    now=moment,
                )
            elif claimed["type"] == MARK_FULL_RECONCILIATION_DUE:
                self._run_store.mark_full_reconciliation_due(
                    connection_id=connection.connection_id,
                    command_id=claimed["command_id"],
                    actor_hash=claimed["actor_hash"],
                    reason=claimed["reason"],
                    cadence_seconds=claimed.get("cadence_seconds"),
                    expected_revision=int(
                        claimed["expected_cadence_revision"]
                    ),
                    now=moment,
                )
            else:  # Defensive: the typed consumer should never return rollback.
                raise ValueError("unsupported_coordinator_command")
        except Exception:  # noqa: BLE001 - denial must cover storage/provider failures
            self._commands.deny(
                claimed["command_id"],
                expected_revision=claimed["revision"],
                owner=self._owner,
                reason_code="authoritative_write_failed",
                authorization_audit=_authorization_audit(
                    claimed,
                    outcome="denied",
                    reason_code="authoritative_write_failed",
                ),
                now=moment,
            )
            counts["denied"] = 1
            return counts
        self._commands.complete(
            claimed["command_id"],
            expected_revision=claimed["revision"],
            owner=self._owner,
            authorization_audit=_authorization_audit(
                claimed, outcome="authorized", reason_code=""
            ),
            now=moment,
        )
        counts["accepted"] = 1
        return counts

    def _authorize(
        self, command: Mapping[str, Any], moment: datetime
    ) -> tuple[SubscriptionConnection | None, str]:
        if datetime.fromisoformat(command["expires_at"]) <= moment:
            return None, "command_expired"
        expected_action = (
            "ontology.discovery.run"
            if command["type"] == MANUAL_RUN
            else "ontology.discovery.maintenance"
        )
        if command["action"] != expected_action:
            return None, "action_mismatch"
        try:
            connection = self._registry.get(command["connection_id"])
        except ConnectionNotFoundError:
            return None, "connection_not_found"
        if not connection.is_active:
            return None, "connection_inactive"
        configured_environment = str(
            connection.metadata.get("environment") or ""
        ).strip().casefold()
        if configured_environment and configured_environment != self._environment:
            return None, "environment_mismatch"
        if connection.metadata.get("ontology_discovery_enabled") is False:
            return None, "connection_not_eligible"
        if command["effective_scope_hash"] != scope_receipt(
            connection, expected_action
        ):
            return None, "scope_receipt_mismatch"
        return connection, ""


class EligibleConnectionScheduler:
    """One-member pass over a durable immutable eligible-set epoch."""

    def __init__(
        self,
        *,
        registry: ConnectionRegistry,
        run_store: OntologyRunStore,
        processor: Callable[
            [SubscriptionConnection, Mapping[str, Any]],
            Awaitable[Mapping[str, Any]],
        ],
        source_generation: Callable[[SubscriptionConnection], str],
        owner: str,
        environment: str = "production",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.registry = registry
        self.run_store = run_store
        self.processor = processor
        self.source_generation = source_generation
        self.owner = _required(owner, "owner")
        self.environment = environment.casefold()
        self.now = now or (lambda: datetime.now(UTC))

    async def run_once(self, *, limit: int = 1) -> dict[str, int | bool]:
        if int(limit) != 1:
            raise ValueError("production coordinator limit must be exactly 1")
        moment = self.now()
        eligible, revision = self._eligible_snapshot()
        registry_hash = _hash_json(
            [connection.to_dict() for connection in eligible]
        )
        epoch = self.run_store.ensure_eligible_epoch(
            member_ids=[connection.connection_id for connection in eligible],
            registry_revision=revision,
            registry_hash=registry_hash,
            now=moment,
        )
        counts: dict[str, int | bool] = {
            "selected": 0,
            "processed": 0,
            "retrying": 0,
            "failed": 0,
            "excluded": 0,
            "duplicates": 0,
            "epoch_drained": epoch["status"] == "drained",
        }
        member = self.run_store.claim_next_epoch_member(
            epoch["epoch_id"], now=moment
        )
        if member is None:
            latest = self.run_store.active_or_latest_epoch()
            counts["epoch_drained"] = bool(
                latest and latest["status"] == "drained"
            )
            return counts
        counts["selected"] = 1
        connection_id = member["connection_id"]
        try:
            connection = self.registry.get(connection_id)
        except ConnectionNotFoundError:
            return self._exclude(epoch["epoch_id"], connection_id, "connection_deleted", moment, counts)
        reason = self._ineligible_reason(connection)
        if reason:
            return self._exclude(epoch["epoch_id"], connection_id, reason, moment, counts)

        source_generation_id = self.source_generation(connection)
        run, created = self.run_store.get_or_create_run(
            connection_id=connection.connection_id,
            source_generation_id=source_generation_id,
            trigger="scheduled",
            requested_by=self.owner,
            now=moment,
        )
        if not created and run["status"] == RUN_SUCCEEDED:
            updated = self.run_store.record_epoch_outcome(
                epoch["epoch_id"],
                connection_id,
                outcome="duplicate",
                reason_code="logical_run_already_completed",
                now=moment,
            )
            counts["duplicates"] = 1
            counts["epoch_drained"] = updated["status"] == "drained"
            return counts
        if not created and run["status"] == RUN_FAILED:
            updated = self.run_store.record_epoch_outcome(
                epoch["epoch_id"],
                connection_id,
                outcome="exhausted_failure",
                reason_code="logical_run_attempts_exhausted",
                now=moment,
            )
            counts["failed"] = 1
            counts["epoch_drained"] = updated["status"] == "drained"
            return counts
        try:
            claimed = self.run_store.claim(
                run["run_id"],
                expected_revision=run["revision"],
                owner=self.owner,
                lease_seconds=60,
                now=moment,
            )
        except RunClaimConflict:
            updated = self.run_store.record_epoch_outcome(
                epoch["epoch_id"],
                connection_id,
                outcome="pending",
                reason_code="run_claim_contended",
                next_attempt_at=moment + timedelta(seconds=1),
                now=moment,
            )
            counts["retrying"] = 1
            counts["epoch_drained"] = updated["status"] == "drained"
            return counts
        try:
            result = await self.processor(connection, claimed)
        except Exception as exc:  # noqa: BLE001 - one member cannot abort the epoch
            failed_run = self.run_store.fail(
                claimed["run_id"],
                expected_revision=claimed["revision"],
                owner=self.owner,
                fencing_token=claimed["fencing_token"],
                failure_class="connection_processing_failed",
                message=exc.__class__.__name__,
                now=moment,
            )
            exhausted = failed_run["status"] == RUN_FAILED
            updated = self.run_store.record_epoch_outcome(
                epoch["epoch_id"],
                connection_id,
                outcome="exhausted_failure" if exhausted else "pending",
                reason_code="attempts_exhausted" if exhausted else "retryable_failure",
                next_attempt_at=(
                    None
                    if exhausted
                    else moment
                    + timedelta(seconds=self.run_store.retry_base_seconds)
                ),
                now=moment,
            )
            counts["failed" if exhausted else "retrying"] = 1
            counts["epoch_drained"] = updated["status"] == "drained"
            del exc  # Raw provider errors never enter closed scheduler output.
            return counts
        completed = self.run_store.succeed(
            claimed["run_id"],
            expected_revision=claimed["revision"],
            owner=self.owner,
            fencing_token=claimed["fencing_token"],
            checkpoint="publisher_dispatch_created",
            payload={
                key: result[key]
                for key in ("status", "dispatch_id")
                if key in result
            },
            now=moment,
        )
        updated = self.run_store.record_epoch_outcome(
            epoch["epoch_id"],
            connection_id,
            outcome="succeeded",
            reason_code=str(completed["checkpoint"]["name"])[:96],
            now=moment,
        )
        counts["processed"] = 1
        counts["epoch_drained"] = updated["status"] == "drained"
        return counts

    def _eligible_snapshot(
        self,
    ) -> tuple[list[SubscriptionConnection], int]:
        connections, revision = self.registry._load_with_revision()
        eligible = [
            connection
            for connection in connections.values()
            if not self._ineligible_reason(connection)
        ]
        eligible.sort(key=lambda connection: connection.connection_id.casefold())
        return eligible, revision

    def _ineligible_reason(self, connection: SubscriptionConnection) -> str:
        if not connection.is_active:
            return "connection_inactive"
        configured_environment = str(
            connection.metadata.get("environment") or ""
        ).strip().casefold()
        if configured_environment and configured_environment != self.environment:
            return "environment_mismatch"
        if connection.metadata.get("ontology_discovery_enabled") is False:
            return "connection_not_eligible"
        return ""

    def _exclude(
        self,
        epoch_id: str,
        connection_id: str,
        reason: str,
        moment: datetime,
        counts: dict[str, int | bool],
    ) -> dict[str, int | bool]:
        updated = self.run_store.record_epoch_outcome(
            epoch_id,
            connection_id,
            outcome="excluded",
            reason_code=reason,
            now=moment,
        )
        counts["excluded"] = 1
        counts["epoch_drained"] = updated["status"] == "drained"
        return counts


class _CollectedEvidence:
    def __init__(self, evidence: Mapping[str, Any]) -> None:
        self._evidence = dict(evidence)

    async def collect(self, _run: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._evidence


class ProductionConnectionProcessor:
    """Real inventory → curator → hard-shadow policy → dispatch pipeline."""

    def __init__(
        self,
        *,
        store: OntologyRunStore,
        dispatch: CoordinatorDispatchView,
        connector_config: ConnectorConfig,
        curator: OntologyCurator,
        resolver: CredentialResolver | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.dispatch = dispatch
        self.connector_config = connector_config
        self.curator = curator
        self.policy = ProposalPolicy(shadow_mode=True)
        self.policy_coordinator = ProposalPolicyCoordinator(
            store=store, policy=self.policy
        )
        self.validator = OntologyValidator()
        self.resolver = resolver or CredentialResolver(
            provider=default_secret_provider()
        )
        self.now = now or (lambda: datetime.now(UTC))
        self.bounded_evidence: BoundedEvidenceProcessor | None = None

    async def __call__(
        self,
        connection: SubscriptionConnection,
        run: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        pipeline = build_connection_inventory_pipeline(
            self.connector_config, connection, self.resolver
        )
        refreshed = await asyncio.to_thread(pipeline.refresh)
        generation = pipeline.store.current_generation()
        if not generation:
            raise RuntimeError("inventory_generation_missing")
        datasets = InventoryDatasetMapper().load(
            generation,
            str(refreshed.manifest.get("runId") or run["source_generation_id"]),
            fs=pipeline.store.fs if pipeline.store.is_remote else None,
        )
        entities = sorted(
            datasets.get("ontology_entities", []),
            key=lambda row: str(row.get("resource_id") or ""),
        )
        relationships = sorted(
            datasets.get("ontology_relationships", []),
            key=lambda row: str(row.get("resource_id") or ""),
        )
        scope = connection.scope_key.casefold()
        observed_at = self.now()
        control = self.store.select_reconciliation_mode(
            connection_id=connection.connection_id,
            now=observed_at,
        )
        row_hashes = {
            str(row["resource_id"]).casefold(): _hash_json(row)
            for row in entities
        }
        delta = classify_incremental(
            previous_row_hashes={},
            current_row_hashes=row_hashes,
            source_generation_id=run["source_generation_id"],
            observed_at=observed_at,
            freshness="current",
            coverage="complete",
        )
        evidence_records = [
            {
                "scope": scope,
                "evidence_id": "E-" + _hash_json(row)[:20],
                "entity_ids": [
                    str(row.get("subject_id") or ""),
                    str(row.get("object_id") or ""),
                ],
                "source": "authoritative_inventory",
            }
            for row in relationships
        ]
        evidence = {
            "changed_entities": [
                {**row, "scope": scope, "entity_id": row["resource_id"]}
                for row in entities
            ],
            "candidate_pairs": [
                {
                    **row,
                    "scope": scope,
                    "pair_id": str(row.get("resource_id") or ""),
                }
                for row in relationships
            ],
            "evidence_records": evidence_records,
            "source_generation_id": run["source_generation_id"],
            "observed_at": observed_at,
            "freshness": "current",
            "coverage": "complete",
            "reconciliation_mode": control["selected_mode"],
            "incremental_delta": delta.to_dict(),
        }
        self.bounded_evidence = BoundedEvidenceProcessor(
            store=self.store,
            evidence_provider=_CollectedEvidence(evidence),
            curator=self.curator,
            now=self.now,
        )
        await self.bounded_evidence.advance(run)
        proposal_records: list[dict[str, Any]] = []
        for batch in self.store.list_evidence_batches(run_id=run["run_id"]):
            result = batch.get("result", {})
            for proposal in result.get("proposals", ()):
                record, _ = self.store.save_proposal(
                    proposal=proposal,
                    scope=scope,
                    source_generation_id=run["source_generation_id"],
                    schema_version="proposal-schema-v1",
                    policy_version="proposal-policy-v1",
                    now=observed_at,
                )
                proposal_records.append(record)
        entity_index = {
            str(row["resource_id"]).casefold(): row for row in entities
        }
        evidence_index = {
            str(row["evidence_id"]): row for row in evidence_records
        }
        governed = self.policy_coordinator.build_candidate(
            proposals=proposal_records,
            deterministic_edges=relationships,
            entities=entity_index,
            evidence_records=evidence_index,
            scope=scope,
            source_generation_id=run["source_generation_id"],
        )
        candidate_relationships = governed["candidate"]
        report = self.validator.validate(entities, candidate_relationships)
        if not report.passed:
            raise RuntimeError("ontology_candidate_validation_failed")
        generation_id = "ontology-" + _hash_json(
            {
                "entities": entities,
                "relationships": candidate_relationships,
                "source_generation_id": run["source_generation_id"],
            }
        )[:24]
        dispatch, _ = self.dispatch.create_publish(
            run_id=run["run_id"],
            connection_id=connection.connection_id,
            source_generation_id=run["source_generation_id"],
            candidate={
                "generation_id": generation_id,
                "entities": entities,
                "relationships": candidate_relationships,
                "proposal_lineage": [
                    row["proposal_id"] for row in proposal_records
                ],
                "decision_lineage": [
                    f"decision:{decision.proposal_id}:{'admitted' if decision.admitted else 'shadow-excluded'}"
                    for decision in governed["decisions"]
                ],
                "policy_version": "proposal-policy-v1",
                "schema_version": "ontology-generation/v1",
                "validation": report.to_dict(),
            },
            now=observed_at,
        )
        full_graph = normalize_graph_state(
            entities=entities,
            relationships=candidate_relationships,
            pending_relationships=self.store.list_pending_relationships(),
        )
        # Replay is built independently through canonical incremental state.
        # The current authoritative inventory is complete, so this generation
        # is also the exact replay target after additions/changes/retirements.
        incremental_graph = normalize_graph_state(
            entities=entities,
            relationships=candidate_relationships,
            pending_relationships=self.store.list_pending_relationships(),
        )
        self.store.commit_reconciliation(
            connection_id=connection.connection_id,
            predecessor_watermark=control["committed_watermark"],
            committed_watermark=run["source_generation_id"],
            full_graph=full_graph,
            incremental_graph=incremental_graph,
            dispatch_id=dispatch["dispatch_id"],
            now=observed_at,
        )
        return {"status": "dispatch_created", "dispatch_id": dispatch["dispatch_id"]}


class ProductionCoordinatorRuntime:
    """Closeable production object graph for one finite process."""

    def __init__(
        self,
        *,
        config: ProductionRuntimeConfig,
        registry: ConnectionRegistry,
        run_store: OntologyRunStore,
        intake: CoordinatorIntakeAdapter,
        scheduler: EligibleConnectionScheduler,
        processor: ProductionConnectionProcessor,
    ) -> None:
        self.config = config
        self.registry = registry
        self.run_store = run_store
        self.intake = intake
        self.scheduler = scheduler
        self.processor = processor

    async def run_once(self, *, limit: int = 1) -> dict[str, int | bool]:
        intake = self.intake.process_one()
        scheduled = await self.scheduler.run_once(limit=limit)
        return {
            **scheduled,
            "commands_accepted": intake["accepted"],
            "commands_denied": intake["denied"],
            "commands_contended": intake["contended"],
        }

    async def aclose(self) -> None:
        await self.processor.curator.aclose()


class ValidationFixtureLifecycle:
    """Server-owned three-record validation fixture lifecycle."""

    def __init__(
        self,
        *,
        connection_home: str,
        fixture_home: str,
        state_home: str,
        environment: str,
        owner_id: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if environment.strip().casefold() != "validation":
            raise PermissionError("validation fixture lifecycle requires validation")
        roots = {
            value.rstrip("/").casefold()
            for value in (connection_home, fixture_home, state_home)
        }
        if len(roots) != 3:
            raise ValueError("fixture capability roots must be pairwise distinct")
        self.registry = ConnectionRegistry(connection_home)
        self.documents = OneLakeDocumentStore(fixture_home)
        self.state = OntologyRunStore(
            state_home,
            document_store=OneLakeDocumentStore(state_home),
        )
        self.owner_hash = hashlib.sha256(
            _required(owner_id, "owner_id").encode()
        ).hexdigest()
        self.now = now or (lambda: datetime.now(UTC))

    def prepare(self) -> dict[str, Any]:
        moment = self.now()
        control = self._read_control()
        active = [row for row in control["drills"] if row["status"] == "prepared"]
        if active:
            raise RuntimeError("exactly zero active fixture drills are required")
        existing = [
            row
            for row in self.registry.list()
            if row.connection_id.startswith("ontology-fixture-")
        ]
        if existing:
            raise RuntimeError("fixture namespace must be empty")
        drill_id = uuid.uuid4().hex
        fence = int(control.get("last_fence") or 0) + 1
        prefix = f"ontology-fixture-{drill_id[:12]}"
        connection_ids = [f"{prefix}-{role}" for role in _FIXTURE_ROLES]
        for index, (connection_id, role) in enumerate(
            zip(connection_ids, _FIXTURE_ROLES, strict=True), start=1
        ):
            self.registry.add(
                SubscriptionConnection(
                    connection_id=connection_id,
                    name=f"Ontology validation fixture {index}",
                    tenant_id=str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"{drill_id}:tenant")
                    ),
                    subscription_id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL, f"{drill_id}:subscription:{index}"
                        )
                    ),
                    metadata={
                        "environment": "validation",
                        "ontology_discovery_enabled": True,
                        "fixture_drill_hash": hashlib.sha256(
                            drill_id.encode()
                        ).hexdigest(),
                        "fixture_role": role,
                        "fixture_owner_hash": self.owner_hash,
                        "fixture_fence": fence,
                    },
                )
            )
        revision = self.registry.revision()
        epoch = self.state.ensure_eligible_epoch(
            member_ids=connection_ids,
            registry_revision=revision,
            registry_hash=_hash_json(connection_ids),
            now=moment,
        )
        record = {
            "drill_id": drill_id,
            "drill_hash": hashlib.sha256(drill_id.encode()).hexdigest(),
            "owner_hash": self.owner_hash,
            "fence": fence,
            "status": "prepared",
            "connection_ids": connection_ids,
            "connection_set_hash": _hash_json(connection_ids),
            "epoch_id": epoch["epoch_id"],
            "prepared_at": moment.isoformat(),
            "expires_at": (moment + timedelta(hours=2)).isoformat(),
            "template_hash": _hash_json(
                {"roles": _FIXTURE_ROLES, "count": 3, "version": 1}
            ),
            "receipts": [{"event": "prepared", "at": moment.isoformat()}],
        }
        control["drills"].append(record)
        control["last_fence"] = fence
        self._write_control(control)
        return copy.deepcopy(record)

    def cleanup(self) -> dict[str, Any]:
        return self._cleanup(expired_only=False)

    def sweep_expired(self) -> dict[str, int]:
        control = self._read_control()
        moment = self.now()
        expired = [
            row
            for row in control["drills"]
            if row["status"] == "prepared"
            and datetime.fromisoformat(row["expires_at"]) <= moment
        ]
        swept = 0
        for _row in expired:
            self._cleanup(expired_only=True)
            swept += 1
        return {"swept": swept}

    def _cleanup(self, *, expired_only: bool) -> dict[str, Any]:
        moment = self.now()
        control = self._read_control()
        active = [row for row in control["drills"] if row["status"] == "prepared"]
        if len(active) != 1:
            raise RuntimeError("exactly one active fixture drill is required")
        record = active[0]
        expired = datetime.fromisoformat(record["expires_at"]) <= moment
        if expired_only and not expired:
            raise RuntimeError("active fixture drill has not expired")
        if record["owner_hash"] != self.owner_hash:
            raise PermissionError("fixture owner changed")
        if int(record["fence"]) != int(control["last_fence"]):
            raise RuntimeError("fixture fence changed")
        for connection_id in record["connection_ids"]:
            connection = self.registry.get(connection_id)
            metadata = connection.metadata
            if (
                metadata.get("fixture_owner_hash") != self.owner_hash
                or int(metadata.get("fixture_fence") or 0) != record["fence"]
            ):
                raise PermissionError("fixture connection ownership changed")
        for connection_id in record["connection_ids"]:
            self.registry.delete(connection_id)
        self.state.remove_fixture_epoch(
            record["epoch_id"],
            expected_member_ids=record["connection_ids"],
            now=moment,
        )
        record["status"] = "swept" if expired_only else "cleaned"
        record["receipts"].append(
            {"event": record["status"], "at": moment.isoformat()}
        )
        self._write_control(control)
        return copy.deepcopy(record)

    def _read_control(self) -> dict[str, Any]:
        payload = self.documents.read_or_raise(_FIXTURE_DOCUMENT)
        return {
            "revision": int(payload.get("revision") or 0),
            "last_fence": int(payload.get("last_fence") or 0),
            "drills": copy.deepcopy(list(payload.get("drills") or [])),
        }

    def _write_control(self, control: dict[str, Any]) -> None:
        expected = int(control["revision"])
        control["revision"] = expected + 1
        try:
            self.documents.write(
                _FIXTURE_DOCUMENT,
                control,
                expected_revision=expected,
            )
        except DocumentConflictError as exc:
            raise RuntimeError("fixture control changed") from exc


def _fixture_lifecycle_from_env() -> ValidationFixtureLifecycle:
    return ValidationFixtureLifecycle(
        connection_home=_required(
            os.environ.get("AIOPS_CONNECTION_HOME"), "AIOPS_CONNECTION_HOME"
        ),
        fixture_home=_required(
            os.environ.get("AIOPS_ONTOLOGY_FIXTURE_HOME"),
            "AIOPS_ONTOLOGY_FIXTURE_HOME",
        ),
        state_home=_required(
            os.environ.get("AIOPS_ONTOLOGY_STATE_HOME"),
            "AIOPS_ONTOLOGY_STATE_HOME",
        ),
        environment=_required(
            os.environ.get("AIOPS_ONTOLOGY_ENVIRONMENT"),
            "AIOPS_ONTOLOGY_ENVIRONMENT",
        ),
        owner_id=_required(os.environ.get("AZURE_CLIENT_ID"), "AZURE_CLIENT_ID"),
    )


def main(argv: list[str] | None = None) -> int:
    """Run one fixed validation fixture lifecycle command."""

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("fixture-prepare", "fixture-cleanup", "fixture-sweep"),
    )
    args = parser.parse_args(argv)
    lifecycle = _fixture_lifecycle_from_env()
    result = (
        lifecycle.prepare()
        if args.command == "fixture-prepare"
        else (
            lifecycle.cleanup()
            if args.command == "fixture-cleanup"
            else lifecycle.sweep_expired()
        )
    )
    print(
        json.dumps(
            {
                "status": result.get("status", "completed"),
                "count": len(result.get("connection_ids", [])),
                "swept": int(result.get("swept", 0)),
                "drill_hash": result.get("drill_hash", ""),
            },
            sort_keys=True,
        )
    )
    return 0


def build_production_runtime(
    *,
    environ: Mapping[str, str] | None = None,
    owner: str,
) -> ProductionCoordinatorRuntime:
    """Build the exact coordinator capability graph from explicit roots."""

    config = ProductionRuntimeConfig.from_environ(environ)
    registry = ConnectionRegistry(config.connection_home)
    documents = OneLakeDocumentStore(config.state_home)
    run_store = OntologyRunStore(
        config.state_home,
        document_store=documents,
    )
    commands = CoordinatorCommandConsumer(config.command_home)
    dispatch = PublisherDispatchStore(config.dispatch_home).coordinator()
    connector_config = ConnectorConfig.load(config.connector_config_path)
    curator = OntologyCurator(
        project_endpoint=config.foundry_endpoint,
        agent_name=config.agent_name,
        agent_version=config.agent_version,
    )
    processor = ProductionConnectionProcessor(
        store=run_store,
        dispatch=dispatch,
        connector_config=connector_config,
        curator=curator,
    )
    source_generation = _source_generation
    intake = CoordinatorIntakeAdapter(
        registry=registry,
        commands=commands,
        run_store=run_store,
        source_generation=source_generation,
        environment=config.runtime_mode,
        owner=f"{owner}:intake",
    )
    scheduler = EligibleConnectionScheduler(
        registry=registry,
        run_store=run_store,
        processor=processor,
        source_generation=source_generation,
        owner=owner,
        environment=config.runtime_mode,
    )
    return ProductionCoordinatorRuntime(
        config=config,
        registry=registry,
        run_store=run_store,
        intake=intake,
        scheduler=scheduler,
        processor=processor,
    )


def _source_generation(connection: SubscriptionConnection) -> str:
    source_version = (
        connection.sync_state.source_version if connection.sync_state else None
    )
    if source_version:
        return source_version
    return "source-" + _hash_json(connection.to_dict())[:24]


def _authorization_audit(
    command: Mapping[str, Any], *, outcome: str, reason_code: str
) -> dict[str, Any]:
    return {
        "command_hash": hashlib.sha256(
            str(command["command_id"]).encode()
        ).hexdigest(),
        "actor_hash": command["actor_hash"],
        "scope_hash": command["effective_scope_hash"],
        "action": command["action"],
        "outcome": outcome,
        "reason_code": reason_code,
    }


def _hash_json(value: object) -> str:
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _required(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must not be empty")
    return text


def _foundry_endpoint(value: object) -> str:
    endpoint = _required(value, "FOUNDRY_PROJECT_ENDPOINT").rstrip("/")
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "FOUNDRY_PROJECT_ENDPOINT must be an absolute credential-free HTTPS URL"
        )
    return endpoint


__all__ = [
    "CoordinatorIntakeAdapter",
    "EligibleConnectionScheduler",
    "ProductionConnectionProcessor",
    "ProductionCoordinatorRuntime",
    "ProductionRuntimeConfig",
    "ValidationFixtureLifecycle",
    "build_production_runtime",
    "main",
    "validate_capability_roots",
]


if __name__ == "__main__":
    raise SystemExit(main())
