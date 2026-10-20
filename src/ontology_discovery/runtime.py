"""Production composition for finite, durable ontology coordinator passes."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
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
from ontology.subscription_connection import CredentialReference, SubscriptionConnection
from storage.fs import is_onelake_uri
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

from .command_intake import (
    MANUAL_RUN,
    MARK_FULL_RECONCILIATION_DUE,
    CommandConflict,
    CoordinatorCommandConsumer,
    scope_receipt,
)
from .contracts import Curator
from .coordinator import (
    BoundedEvidenceProcessor,
    ProposalPolicyCoordinator,
)
from .curator import OntologyCurator
from .dispatch_store import CoordinatorDispatchView, PublisherDispatchStore
from .evidence_projection import project_application_dependency_evidence
from .incremental import (
    apply_incremental_graph,
    classify_incremental,
    graph_row_hashes,
    normalize_graph_state,
)
from .maintenance_admission import MaintenanceAdmission, vocabulary_fingerprint
from .maintenance_consumers import (
    BudgetLedger,
    cost_usd,
)
from .maintenance_relationships import FirstAdmissionLedger
from .maintenance_release import (
    PURPOSE_OFFLINE,
    MaintenanceConfigError,
    MaintenanceReleaseReader,
    build_production_reader,
)
from .planner_capabilities import PlannerSelection, select_planner
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
            values.get("AIOPS_ONTOLOGY_ENVIRONMENT")
            or values.get("AIOPS_RUNTIME_MODE"),
            "AIOPS_ONTOLOGY_ENVIRONMENT",
        ).casefold()
        if runtime_mode not in _ALLOWED_RUNTIME_MODES:
            raise ValueError(
                "AIOPS_ONTOLOGY_ENVIRONMENT must be production or validation"
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

        authorization = scope_receipt(connection, "ontology.discovery.run")
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
                actor=self.owner,
                authorization_receipt=authorization,
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
                actor=self.owner,
                authorization_receipt=authorization,
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
                actor=self.owner,
                authorization_receipt=authorization,
                now=moment,
            )
            counts["retrying"] = 1
            counts["epoch_drained"] = updated["status"] == "drained"
            return counts
        try:
            result = await self.processor(connection, claimed)
        except Exception as exc:  # noqa: BLE001 - one member cannot abort the epoch
            current_run = self.run_store.get(claimed["run_id"])
            if not _run_lease_matches(current_run, claimed):
                updated = self.run_store.record_epoch_outcome(
                    epoch["epoch_id"],
                    connection_id,
                    outcome="pending",
                    reason_code="run_lease_lost",
                    next_attempt_at=moment + timedelta(seconds=1),
                    actor=self.owner,
                    authorization_receipt=authorization,
                    now=moment,
                )
                counts["lease_lost"] = 1
                counts["epoch_drained"] = updated["status"] == "drained"
                del exc
                return counts
            failed_run = self.run_store.fail(
                claimed["run_id"],
                expected_revision=int(current_run["revision"]),
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
                actor=self.owner,
                authorization_receipt=authorization,
                now=moment,
            )
            counts["failed" if exhausted else "retrying"] = 1
            counts["epoch_drained"] = updated["status"] == "drained"
            del exc  # Raw provider errors never enter closed scheduler output.
            return counts
        current_run = self.run_store.get(claimed["run_id"])
        if not _run_lease_matches(current_run, claimed):
            updated = self.run_store.record_epoch_outcome(
                epoch["epoch_id"],
                connection_id,
                outcome="pending",
                reason_code="run_lease_lost",
                next_attempt_at=moment + timedelta(seconds=1),
                actor=self.owner,
                authorization_receipt=authorization,
                now=moment,
            )
            counts["lease_lost"] = 1
            counts["epoch_drained"] = updated["status"] == "drained"
            return counts
        completed = self.run_store.succeed(
            claimed["run_id"],
            expected_revision=int(current_run["revision"]),
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
            actor=self.owner,
            authorization_receipt=authorization,
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
            actor=self.owner,
            authorization_receipt=_hash_json(
                {
                    "connection_id": connection_id,
                    "environment": self.environment,
                    "action": "ontology.discovery.run",
                    "outcome": "denied",
                    "reason_code": reason,
                }
            ),
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
        curator: Curator,
        planner_selection: PlannerSelection | None = None,
        resolver: CredentialResolver | None = None,
        monitor_dependency_reader: Callable[
            [SubscriptionConnection], list[Mapping[str, Any]] | None
        ]
        | None = None,
        monitor_identity_bindings: Callable[
            [SubscriptionConnection], Mapping[str, str | list[str] | tuple[str, ...]]
        ]
        | None = None,
        now: Callable[[], datetime] | None = None,
        maintenance: MaintenanceAdmission | None = None,
        first_admission_ledger: FirstAdmissionLedger | None = None,
        budget_ledger: BudgetLedger | None = None,
        pricing: Mapping[str, Any] | None = None,
        max_total_seconds: float = 1800.0,
        max_cost_usd: float | None = None,
        input_overhead_tokens: int | None = None,
    ) -> None:
        self.budget_ledger = budget_ledger
        self.pricing = pricing
        self.max_total_seconds = max_total_seconds
        self.max_cost_usd = max_cost_usd
        self.input_overhead_tokens = input_overhead_tokens
        if maintenance is not None and first_admission_ledger is None:
            raise MaintenanceConfigError("maintenance_first_admission_ledger_required")
        offline_budget = (
            isinstance(maintenance, MaintenanceAdmission)
            and isinstance(maintenance.reader, MaintenanceReleaseReader)
            and maintenance.reader.purpose == PURPOSE_OFFLINE
        )
        if maintenance is not None and (
            not isinstance(budget_ledger, BudgetLedger)
            or not isinstance(curator, OntologyCurator)
            or getattr(curator._request, "__func__", None) is not OntologyCurator._request
            or getattr(curator.budget_scope, "__func__", None) is not OntologyCurator.budget_scope
            or (
                not offline_budget
                and getattr(curator.propose, "__func__", None) is not OntologyCurator.propose
            )
            or not isinstance(pricing, Mapping)
            or not isinstance(pricing.get("version"), str)
            or not 1 <= len(pricing["version"]) <= 128
            or cost_usd({"input_tokens": 1, "output_tokens": 1}, pricing) is None
            or max_cost_usd is None
            or not math.isfinite(max_cost_usd) or max_cost_usd <= 0
            or not math.isfinite(max_total_seconds) or max_total_seconds <= 0
            or not isinstance(input_overhead_tokens, int)
            or isinstance(input_overhead_tokens, bool) or input_overhead_tokens < 0
        ):
            raise MaintenanceConfigError("maintenance_budget_unqualified")
        self.maintenance = maintenance
        self.first_admission_ledger = first_admission_ledger
        self.store = store
        self.dispatch = dispatch
        self.connector_config = connector_config
        self.curator = curator
        self.planner_selection = planner_selection or select_planner()
        self.planner_selection.require_supported()
        self.policy = ProposalPolicy(shadow_mode=True)
        self.policy_coordinator = ProposalPolicyCoordinator(
            store=store, policy=self.policy
        )
        self.validator = OntologyValidator()
        self.resolver = resolver or CredentialResolver(
            provider=default_secret_provider()
        )
        self.monitor_dependency_reader = monitor_dependency_reader
        self.monitor_identity_bindings = monitor_identity_bindings
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
        manifest = refreshed.manifest
        if not isinstance(manifest, Mapping):
            raise TypeError("inventory_manifest_missing")
        inventory_generation = _required(
            manifest.get("runId"), "inventory_manifest.runId"
        )
        datasets = InventoryDatasetMapper().load(
            generation,
            inventory_generation,
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
        monitor_rows = (
            None
            if self.monitor_dependency_reader is None
            else self.monitor_dependency_reader(connection)
        )
        identity_bindings = (
            {}
            if self.monitor_identity_bindings is None
            else self.monitor_identity_bindings(connection)
        )
        monitor_generation = "monitor-window-" + _hash_json(
            {
                "date": observed_at.astimezone(UTC).date().isoformat(),
                "rows": [
                    {
                        key: row.get(key)
                        for key in (
                            "TimeGenerated",
                            "Id",
                            "OperationId",
                            "_ResourceId",
                            "_SubscriptionId",
                            "AppRoleName",
                            "Target",
                            "DependencyType",
                            "Success",
                            "SyntheticSource",
                        )
                    }
                    for row in (monitor_rows or ())
                ],
            }
        )
        manifest_fingerprint = _hash_json(manifest)
        inventory_fingerprint = _hash_json(
            {
                "entities": [_hash_json(row) for row in entities],
                "relationships": [_hash_json(row) for row in relationships],
                "resources": [
                    _hash_json(row) for row in datasets.get("bronze_resources", ())
                ],
            }
        )
        source_binding = {
            "run_source_generation_id": str(run["source_generation_id"]),
            "inventory_generation_id": inventory_generation,
            "manifest_fingerprint": manifest_fingerprint,
            "inventory_fingerprint": inventory_fingerprint,
            "monitor_generation_id": monitor_generation,
            "monitor_fingerprint": _hash_json(monitor_rows)
            if monitor_rows is not None
            else "unavailable",
            "scope": scope,
        }
        checkpoint_payload = dict(run.get("checkpoint", {}).get("payload") or {})
        prior_binding = checkpoint_payload.get("source_binding")
        if prior_binding is not None and prior_binding != source_binding:
            raise RuntimeError("inventory_source_generation_binding_conflict")
        if (
            prior_binding is None
            and self.store.list_evidence_batches(run_id=str(run["run_id"]))
        ):
            raise RuntimeError("existing_evidence_run_has_no_source_binding")
        bound_run = dict(run)
        if prior_binding is None:
            checkpoint_payload["source_binding"] = source_binding
            bound_run = self.store.checkpoint(
                str(run["run_id"]),
                expected_revision=int(run["revision"]),
                owner=str(run["lease_owner"]),
                fencing_token=int(run["fencing_token"]),
                name="source_snapshot_bound",
                payload=checkpoint_payload,
                now=observed_at,
            )

        projection = project_application_dependency_evidence(
            scope=scope,
            batch_source_generation_id=str(run["source_generation_id"]),
            observed_at=observed_at,
            application_entities=entities,
            deterministic_relationships=relationships,
            inventory_records=datasets.get("bronze_resources", ()),
            app_dependency_rows=monitor_rows,
            monitor_identity_bindings=identity_bindings,
            inventory_generation_id=inventory_generation,
            monitor_generation_id=monitor_generation,
            generation_binding_verified=True,
            inventory_observed_at=_manifest_time(manifest, observed_at),
        )
        checkpoint_payload = dict(bound_run.get("checkpoint", {}).get("payload") or {})
        checkpoint_payload["source_projection"] = {
            "coverage": projection["coverage"],
            "uncertainties": projection["uncertainties"],
            "candidate_count": len(projection["candidate_pairs"]),
            "evidence_count": len(projection["evidence_records"]),
        }
        bound_run = self.store.checkpoint(
            str(bound_run["run_id"]),
            expected_revision=int(bound_run["revision"]),
            owner=str(bound_run["lease_owner"]),
            fencing_token=int(bound_run["fencing_token"]),
            name="source_observations_projected",
            payload=checkpoint_payload,
            now=observed_at,
        )

        lineage_key = "inventory+appdependencies:v1"
        try:
            baseline = self.store.get_committed_baseline(
                connection_id=connection.connection_id,
                scope=scope,
                lineage_key=lineage_key,
            )
        except ValueError:
            baseline = None
        control = self.store.select_reconciliation_mode(
            connection_id=connection.connection_id,
            now=observed_at,
            baseline_scope=scope,
            baseline_lineage_key=lineage_key,
        )
        source_graph = normalize_graph_state(
            entities=entities,
            relationships=relationships,
            pending_relationships=self.store.list_pending_relationships(),
        )
        delta = classify_incremental(
            previous_row_hashes=(
                dict(baseline["row_hashes"])
                if baseline is not None and control["selected_mode"] == "incremental"
                else {}
            ),
            current_row_hashes=graph_row_hashes(source_graph),
            source_generation_id=str(run["source_generation_id"]),
            observed_at=observed_at,
            freshness=(
                "current" if projection["coverage"] == "complete" else "degraded"
            ),
            coverage=str(projection["coverage"]),
        )
        changed_ids = set(delta.added) | set(delta.changed)
        if control["selected_mode"] == "full":
            changed_entities = entities
            candidate_relationships = relationships
        else:
            changed_entities = [
                row
                for row in entities
                if f"entities/{str(row.get('resource_id') or '').casefold()}"
                in changed_ids
            ]
            candidate_relationships = [
                row
                for row in relationships
                if f"relationships/{str(row.get('resource_id') or '').casefold()}"
                in changed_ids
            ]
        endpoint_ids = {
            str(pair.get(field) or "").casefold()
            for pair in projection["candidate_pairs"]
            for field in ("subject_id", "object_id")
        }
        contexts = {
            str(row.get("resource_id") or "").casefold(): row for row in entities
        }
        changed_by_id = {
            str(row.get("resource_id") or "").casefold(): row
            for row in changed_entities
        }
        changed_by_id.update(
            {
                endpoint: contexts[endpoint]
                for endpoint in endpoint_ids
                if endpoint in contexts
            }
        )
        batch_entities = [
            {**row, "scope": scope, "entity_id": row["resource_id"]}
            for row in changed_by_id.values()
        ]
        deterministic_pairs = [
            {
                **row,
                "scope": scope,
                "pair_id": str(row.get("resource_id") or ""),
            }
            for row in candidate_relationships
        ]
        candidate_pairs = _merge_candidate_pairs(
            deterministic_pairs, projection["candidate_pairs"]
        )
        evidence_records = projection["evidence_records"]
        evidence = {
            "changed_entities": batch_entities,
            "candidate_pairs": candidate_pairs,
            "evidence_records": evidence_records,
            "source_generation_id": run["source_generation_id"],
            "observed_at": observed_at,
            "freshness": (
                "current" if projection["coverage"] == "complete" else "degraded"
            ),
            "coverage": projection["coverage"],
            "uncertainties": projection["uncertainties"],
            "reconciliation_mode": control["selected_mode"],
            "incremental_delta": delta.to_dict(),
        }
        self.bounded_evidence = BoundedEvidenceProcessor(
            store=self.store,
            evidence_provider=_CollectedEvidence(evidence),
            curator=self.curator,
            planner_selection=self.planner_selection,
            now=self.now,
        )
        maintenance_denial = (
            "" if self.maintenance is None else self.maintenance.check_open("admit")
        )
        if self.maintenance is None:
            await self.bounded_evidence.advance(bound_run)
        elif not maintenance_denial:
            # Outer remaining-run deadline bounds every nested retry/repair/tool
            # attempt; late work can neither persist nor be admitted.
            remaining = (
                datetime.fromisoformat(str(bound_run["deadline_at"])) - self.now()
            ).total_seconds()
            if remaining <= 0:
                raise RuntimeError("maintenance_run_deadline_exceeded")
            try:
                # Binding is task-local; concurrent connections cannot exchange
                # usage attribution. Every nested transport retry reserves first
                # and settles in finally, including timeout/cancellation.
                assert isinstance(self.curator, OntologyCurator)
                assert self.budget_ledger is not None
                with self.curator.budget_scope(
                    str(run["run_id"]), self.budget_ledger,
                    pricing=self.pricing, max_cost_usd=self.max_cost_usd,
                    max_total_seconds=self.max_total_seconds,
                    input_overhead_tokens=self.input_overhead_tokens,
                ):
                    await asyncio.wait_for(
                        self.bounded_evidence.advance(bound_run), timeout=remaining
                    )
            except TimeoutError:
                raise RuntimeError("maintenance_run_deadline_exceeded") from None
        # Kill/revocation: deterministic refresh continues with no new model call.
        proposal_records: list[dict[str, Any]] = []
        receipts_by_proposal: dict[str, Mapping[str, Any]] = {}
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
                receipts_by_proposal[str(record["proposal_id"])] = (
                    result.get("provider_receipt") or {}
                )
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
        maintenance_decisions: list[Any] = []
        maintenance_authorization: dict[str, Any] | None = None
        if self.maintenance is not None and not maintenance_denial:
            maintenance_decisions = self._admit(
                proposal_records,
                receipts_by_proposal,
                connection=connection,
                scope=scope,
                source_generation_id=str(run["source_generation_id"]),
                entity_index=entity_index,
                evidence_index=evidence_index,
            )
            observation = self.first_admission_ledger.record_source_observation(
                str(run["source_generation_id"]),
                observed_at=_manifest_time(manifest, observed_at),
                ingestion_run_id=inventory_generation,
                manifest_digest=_hash_json(manifest),
            )
            rows = self.maintenance.canonical_rows(
                maintenance_decisions,
                deterministic_edges=relationships,
                records_by_id={str(r["proposal_id"]): r for r in proposal_records},
                entities=entity_index,
                evidence_records=evidence_index,
                source_observed_at=datetime.fromisoformat(
                    observation["source_observed_at"]
                ),
                ingestion_run_id=str(observation["ingestion_run_id"]),
                first_admission=lambda rid, instant: (
                    self.first_admission_ledger.get_or_record(
                        rid,
                        instant,
                        provenance={
                            "source_generation_id": str(run["source_generation_id"]),
                            "ingestion_run_id": str(observation["ingestion_run_id"]),
                        },
                    )
                ),
                source_generation_id=str(run["source_generation_id"]),
            )
            if rows:
                candidate_relationships = [*candidate_relationships, *rows]
                admitted = [d for d in maintenance_decisions if d.admitted]
                release = admitted[0].release
                maintenance_authorization = {
                    "release_id": release.release_id,
                    "attestation_digest": release.attestation_digest,
                    "proposal_ids": sorted(d.proposal_id for d in admitted),
                    "model_edge_ids": sorted(r["resource_id"] for r in rows),
                }
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
        if maintenance_authorization is not None:
            # Re-read authenticated release, kill/revocation and freshness
            # immediately before the durable dispatch.
            denial = self.maintenance.check_open("admit")
            if denial:
                raise RuntimeError("maintenance_authorization_lost:" + denial)
        admitted_ids = {d.proposal_id for d in maintenance_decisions if d.admitted}
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
                    f"decision:{decision.proposal_id}:"
                    + (
                        "maintenance-admitted"
                        if decision.proposal_id in admitted_ids
                        else "admitted"
                        if decision.admitted
                        else "shadow-excluded"
                    )
                    for decision in governed["decisions"]
                ],
                "policy_version": "proposal-policy-v1",
                "schema_version": "ontology-generation/v1",
                "validation": report.to_dict(),
                **(
                    {"maintenance_authorization": maintenance_authorization}
                    if maintenance_authorization is not None
                    else {}
                ),
            },
            now=observed_at,
        )
        full_graph = normalize_graph_state(
            entities=entities,
            relationships=candidate_relationships,
            pending_relationships=self.store.list_pending_relationships(),
        )
        replay_delta = classify_incremental(
            previous_row_hashes=(
                dict(baseline["row_hashes"])
                if baseline is not None and control["selected_mode"] == "incremental"
                else {}
            ),
            current_row_hashes=graph_row_hashes(full_graph),
            source_generation_id=str(run["source_generation_id"]),
            observed_at=observed_at,
            freshness=(
                "current" if projection["coverage"] == "complete" else "degraded"
            ),
            coverage=str(projection["coverage"]),
        )
        incremental_graph = apply_incremental_graph(
            previous_graph=(
                baseline["graph"]
                if baseline is not None and control["selected_mode"] == "incremental"
                else {"entities": [], "relationships": [], "pending": []}
            ),
            current_graph=full_graph,
            delta=replay_delta,
        )
        self.store.commit_reconciliation(
            connection_id=connection.connection_id,
            predecessor_watermark=control["committed_watermark"],
            committed_watermark=str(run["source_generation_id"]),
            full_graph=full_graph,
            incremental_graph=incremental_graph,
            dispatch_id=dispatch["dispatch_id"],
            baseline={
                "scope": scope,
                "lineage_key": lineage_key,
                "schema_version": "ontology-graph-v1",
                "coverage": str(projection["coverage"]),
                "row_hashes": graph_row_hashes(incremental_graph),
                "graph": incremental_graph,
                "source_fingerprint": _hash_json(source_binding),
            },
            baseline_expected_revision=(
                baseline["revision"] if baseline is not None else None
            ),
            now=observed_at,
        )
        return {"status": "dispatch_created", "dispatch_id": dispatch["dispatch_id"]}


    def _admit(
        self,
        proposal_records: list[dict[str, Any]],
        receipts: Mapping[str, Mapping[str, Any]],
        *,
        connection: SubscriptionConnection,
        scope: str,
        source_generation_id: str,
        entity_index: Mapping[str, Mapping[str, Any]],
        evidence_index: Mapping[str, Mapping[str, Any]],
    ) -> list[Any]:
        assert self.maintenance is not None
        decisions = []
        for record in proposal_records:
            receipt = receipts.get(str(record["proposal_id"])) or {}
            observed = {
                "provider": str(receipt.get("selected_provider") or ""),
                "agent_version": str(receipt.get("agent_version") or ""),
                "prompt_hash": str(receipt.get("prompt_hash") or ""),
                "schema_hash": str(receipt.get("schema_hash") or ""),
                "policy_version": str(record.get("policy_version") or ""),
                "schema_version": str(record.get("schema_version") or ""),
                "definition_fingerprint": vocabulary_fingerprint(),
            }
            # Exact model is obligatory maintenance evidence: absent/empty is
            # carried as "" and denied by the admission check.
            observed["model"] = str(receipt.get("model") or "")
            decisions.append(
                self.maintenance.evaluate(
                    record,
                    entities=entity_index,
                    evidence_records=evidence_index,
                    scope=scope,
                    source_generation_id=source_generation_id,
                    review_status=str(
                        self.store.get_review(str(record["proposal_id"]))["status"]
                    ),
                    observed_lineage=observed,
                    connection=connection,
                )
            )
        return decisions


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
        owned_curator: OntologyCurator | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.run_store = run_store
        self.intake = intake
        self.scheduler = scheduler
        self.processor = processor
        self._owned_curator = owned_curator

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
        """Close only the default curator created and owned by this runtime."""
        if self._owned_curator is not None:
            await self._owned_curator.aclose()


class ValidationFixtureLifecycle:
    """Server-owned three-record validation fixture lifecycle."""

    def __init__(
        self,
        *,
        connection_home: str,
        source_connection_home: str,
        fixture_home: str,
        state_home: str,
        environment: str,
        owner_id: str,
        tenant_id: str,
        subscription_id: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if environment.strip().casefold() != "validation":
            raise PermissionError("validation fixture lifecycle requires validation")
        roots = {
            value.rstrip("/").casefold()
            for value in (
                connection_home,
                source_connection_home,
                fixture_home,
                state_home,
            )
        }
        if len(roots) != 4:
            raise ValueError("fixture capability roots must be pairwise distinct")
        self.registry = ConnectionRegistry(connection_home)
        self.source_registry = ConnectionRegistry(source_connection_home)
        self.documents = OneLakeDocumentStore(fixture_home)
        self.state = OntologyRunStore(
            state_home,
            document_store=OneLakeDocumentStore(state_home),
        )
        self.owner_id = _required(owner_id, "owner_id")
        self.owner_hash = hashlib.sha256(self.owner_id.encode()).hexdigest()
        self.tenant_id = _required(tenant_id, "tenant_id")
        self.subscription_id = _required(
            subscription_id,
            "subscription_id",
        )
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
            if row.metadata.get("fixture_owner_hash") == self.owner_hash
        ]
        if existing:
            raise RuntimeError("fixture namespace must be empty")
        drill_id = uuid.uuid4().hex
        fence = int(control.get("last_fence") or 0) + 1
        prefix = f"ontology-fixture-{drill_id[:12]}"
        source_candidates = sorted(
            (
                row
                for row in self.source_registry.list(include_disabled=False)
                if self.source_registry.metadata_for(row).environment
                in {"development", "test", "validation"}
                and row.metadata.get("ontology_discovery_enabled") is True
                and row.credential is not None
                and row.credential.active
            ),
            key=lambda row: row.connection_id.casefold(),
        )
        if len(source_candidates) != 1:
            raise RuntimeError(
                "exactly one eligible non-production source connection is required"
            )
        source_connection = source_candidates[0]
        connection_ids = [
            source_connection.connection_id,
            *[
                f"{prefix}-{role}"
                for role in _FIXTURE_ROLES[1:]
            ],
        ]
        for index, (connection_id, role) in enumerate(
            zip(connection_ids, _FIXTURE_ROLES, strict=True), start=1
        ):
            metadata = {
                "environment": "validation",
                "ontology_discovery_enabled": True,
                "fixture_drill_hash": hashlib.sha256(
                    drill_id.encode()
                ).hexdigest(),
                "fixture_role": role,
                "fixture_owner_hash": self.owner_hash,
                "fixture_fence": fence,
            }
            if index == 1:
                source_payload = source_connection.to_dict()
                source_payload.update(
                    {
                        "name": "Ontology validation source fixture",
                        "metadata": {
                            **source_connection.metadata,
                            **metadata,
                            "source_connection_hash": _hash_json(
                                source_connection.connection_id
                            ),
                        },
                    }
                )
                fixture_connection = SubscriptionConnection.from_mapping(
                    source_payload
                )
            else:
                fixture_connection = SubscriptionConnection(
                    connection_id=connection_id,
                    name=f"Ontology validation fixture {index}",
                    tenant_id=self.tenant_id,
                    subscription_id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"{drill_id}:subscription:{index}",
                        )
                    ),
                    credential=CredentialReference(
                        credential_id=f"{connection_id}-managed-identity",
                        kind="managed_identity",
                        client_id=self.owner_id,
                        tenant_id=self.tenant_id,
                    ),
                    metadata=metadata,
                )
            self.registry.add(
                fixture_connection
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
        source_connection_home=_required(
            os.environ.get("AIOPS_SOURCE_CONNECTION_HOME"),
            "AIOPS_SOURCE_CONNECTION_HOME",
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
        tenant_id=_required(
            os.environ.get("AIOPS_ONTOLOGY_FIXTURE_TENANT_ID"),
            "AIOPS_ONTOLOGY_FIXTURE_TENANT_ID",
        ),
        subscription_id=_required(
            os.environ.get("AIOPS_ONTOLOGY_FIXTURE_SUBSCRIPTION_ID"),
            "AIOPS_ONTOLOGY_FIXTURE_SUBSCRIPTION_ID",
        ),
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
    curator: Curator | None = None,
    planner_selection: PlannerSelection | None = None,
    monitor_dependency_reader: Callable[
        [SubscriptionConnection], list[Mapping[str, Any]] | None
    ]
    | None = None,
    monitor_identity_bindings: Callable[
        [SubscriptionConnection], Mapping[str, str | list[str] | tuple[str, ...]]
    ]
    | None = None,
) -> ProductionCoordinatorRuntime:
    """Build the existing graph, optionally borrowing a protocol-only curator.

    Injection does not relax environment/root validation or hard-shadow policy.
    The caller owns an injected curator and any external transport it uses.
    """

    config = ProductionRuntimeConfig.from_environ(environ)
    selection = planner_selection or select_planner(
        execution_class="live" if curator is None else "provenance_unavailable"
    )
    selection.require_supported()
    registry = ConnectionRegistry(config.connection_home)
    documents = OneLakeDocumentStore(config.state_home)
    run_store = OntologyRunStore(
        config.state_home,
        document_store=documents,
    )
    commands = CoordinatorCommandConsumer(config.command_home)
    dispatch = PublisherDispatchStore(config.dispatch_home).coordinator()
    connector_config = ConnectorConfig.load(config.connector_config_path)
    owned_curator = (
        OntologyCurator(
            project_endpoint=config.foundry_endpoint,
            agent_name=config.agent_name,
            agent_version=config.agent_version,
        )
        if curator is None else None
    )
    selected_curator = curator if curator is not None else owned_curator
    assert selected_curator is not None
    # Default-off, server-selected.  A selected maintenance mode without the
    # approved ledger binding fails startup closed; no caller/model flag exists.
    maintenance_reader = build_production_reader(environ if environ is not None else os.environ)
    maintenance = None
    ledger = None
    budget_ledger = None
    pricing = None
    max_cost_usd = None
    max_total_seconds = 1800.0
    input_overhead_tokens = None
    if maintenance_reader is not None:
        # Production cannot qualify an arbitrary protocol implementation (or a
        # subclass overriding the bounded attempt seam) by a caller boolean.
        if type(selected_curator) is not OntologyCurator:
            raise MaintenanceConfigError("maintenance_budget_unqualified")
        ledger_path = str(
            (environ if environ is not None else os.environ).get(
                "ONTOLOGY_MAINTENANCE_LEDGER_PATH"
            )
            or ""
        ).strip()
        if not ledger_path:
            raise MaintenanceConfigError("maintenance_first_admission_ledger_required")
        maintenance = MaintenanceAdmission(reader=maintenance_reader)
        ledger = FirstAdmissionLedger(ledger_path)
        bindings = environ if environ is not None else os.environ
        try:
            budget_path = str(bindings.get("ONTOLOGY_MAINTENANCE_BUDGET_PATH") or "").strip()
            pricing = json.loads(str(bindings.get("ONTOLOGY_MAINTENANCE_PRICING_JSON") or "null"))
            max_cost_usd = float(bindings.get("ONTOLOGY_MAINTENANCE_MAX_COST_USD") or "nan")
            max_total_seconds = float(bindings.get("ONTOLOGY_MAINTENANCE_MAX_SECONDS") or "1800")
            input_overhead_tokens = int(bindings.get("ONTOLOGY_MAINTENANCE_INPUT_OVERHEAD_TOKENS") or "")
            if not budget_path or not isinstance(pricing, Mapping):
                raise ValueError
            budget_ledger = BudgetLedger(budget_path)
        except (TypeError, ValueError):
            raise MaintenanceConfigError("maintenance_budget_unqualified") from None
    processor = ProductionConnectionProcessor(
        store=run_store,
        dispatch=dispatch,
        connector_config=connector_config,
        curator=selected_curator,
        planner_selection=selection,
        monitor_dependency_reader=monitor_dependency_reader,
        monitor_identity_bindings=monitor_identity_bindings,
        maintenance=maintenance,
        first_admission_ledger=ledger,
        budget_ledger=budget_ledger,
        pricing=pricing,
        max_cost_usd=max_cost_usd,
        max_total_seconds=max_total_seconds,
        input_overhead_tokens=input_overhead_tokens,
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
        owned_curator=owned_curator,
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


def _manifest_time(manifest: Mapping[str, Any], fallback: datetime) -> datetime:
    value = manifest.get("startedAt") or manifest.get("completedAt")
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return fallback
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return fallback
    return parsed


def _run_lease_matches(
    current: Mapping[str, Any] | None, claimed: Mapping[str, Any]
) -> bool:
    return bool(
        current is not None
        and current.get("status") == "running"
        and current.get("lease_owner") == claimed.get("lease_owner")
        and current.get("fencing_token") == claimed.get("fencing_token")
    )


def _merge_candidate_pairs(
    deterministic: list[Mapping[str, Any]],
    projected: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one scoped record per exact directional triple."""

    by_pair: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in (*deterministic, *projected):
        key = (
            str(record.get("subject_id") or "").casefold(),
            str(record.get("predicate") or ""),
            str(record.get("object_id") or "").casefold(),
        )
        if not all(key):
            continue
        current = by_pair.get(key)
        if current is None or record.get("evidence_ids"):
            by_pair[key] = {**dict(record), "scope": str(record.get("scope") or "")}
    return [
        by_pair[key]
        for key in sorted(by_pair)
    ]


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
