"""Offline Phase 14 admission tests: real processor, validator, stores, signed trust.

Everything here is a synthetic offline qualification.  The isolated test keys
and synthetic planning corpus can never produce a loadable production release
and do not close the real upstream Phase 13 Plan 22 discrepancy.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ontology.ontology_validator import OntologyValidator
from ontology.subscription_connection import SubscriptionConnection
from ontology_discovery.contracts import AdmissionEvaluationSnapshot
from ontology_discovery.curator import OntologyCurator
from ontology_discovery.dispatch_store import PublisherDispatchStore
from ontology_discovery.maintenance_admission import (
    MaintenanceAdmission,
    vocabulary_fingerprint,
)
from ontology_discovery.maintenance_consumers import BudgetLedger
from ontology_discovery.maintenance_relationships import (
    FirstAdmissionLedger,
    materialize_relationship,
)
from ontology_discovery.maintenance_release import (
    MaintenanceConfigError,
    MaintenanceDenied,
    MaintenanceReleaseReader,
    TrustContext,
    TrustedKey,
    approval_message,
    build_production_reader,
    canonical_json,
    digest,
    verify_prerequisite_corpus,
)
from ontology_discovery.policy import ProposalPolicy
from ontology_discovery.runtime import ProductionConnectionProcessor
from ontology_discovery.store import OntologyRunStore

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
SCOPE = "tenant-1:sub-1:offline-connection"
INVENTORY_GENERATION = "inventory-generation-7"
FRONTEND_ASSET = "/subscriptions/sub-1/resourcegroups/apps/providers/example/apps/front"
BACKEND_ASSET = "/subscriptions/sub-1/resourcegroups/apps/providers/example/apps/back"
FRONTEND_APP = "application://tenant-1/front"
BACKEND_APP = "application://tenant-1/back"
IMPL = "sha256:implementation"
ENVIRONMENT = "corrected-env"
SOURCES = ["azure-monitor:AppDependencies", "azure-resource-graph:dependency-tag"]
PROMPT_HASH = "a" * 64
SCHEMA_HASH = "b" * 64
ROLES = ("ontology_steward", "security_owner", "fabric_governance_steward")


# ------------------------------------------------------------------ fixtures


def _key(seed: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)


def _pub(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _sign(key: Ed25519PrivateKey, message: bytes) -> str:
    return base64.b64encode(key.sign(message)).decode()


def write_corpus(root: Path, *, phase13_summaries: int = 22) -> None:
    """Synthetic planning corpus with the exact inherited file structure."""

    def phase(dirname: str, prefix: str, numbers, *, plans: bool = False) -> None:
        directory = root / "phases" / dirname
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{prefix}-VERIFICATION.md").write_text(
            "---\nstatus: passed\n---\nverified\n"
        )
        for number in numbers:
            if plans:
                (directory / f"{prefix}-{number:02d}-PLAN.md").write_text("plan")
            completed = "2026-01-01"
            body = "done"
            if prefix == "13" and number == 20:
                completed = "2026-01-01"
            if prefix == "13" and number == 21:
                completed = "2026-01-02"
            (directory / f"{prefix}-{number:02d}-SUMMARY.md").write_text(
                f"---\nstatus: complete\ncompleted: {completed}\n---\n{body}\n"
            )

    phase("03.1-exposure", "03.1", (19, 20))
    phase("07-inventory", "07", range(1, 7))
    phase("09-consumer", "09", range(1, 12))
    phase("13-ontology", "13", range(1, phase13_summaries + 1))
    phase("03.7-fabric", "03.7", range(1, 13))
    phase("11-copilot", "11", range(1, 17))
    phase("03.8-native", "03.8", (1, 2), plans=True)
    directory = root / "phases" / "13-ontology"
    if phase13_summaries >= 21:
        first = (directory / "13-20-SUMMARY.md").read_text()
        (directory / "13-21-SUMMARY.md").write_text(
            "---\nstatus: complete\ncompleted: 2026-01-02\n---\n"
            f"binds {hashlib.sha256(first.encode()).hexdigest()}\n"
        )


class Authority:
    """Isolated offline issuer/approver keys and mutable control state."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "planning"
        write_corpus(self.root)
        self.issuer_key = _key(1)
        self.approver_keys = {role: _key(10 + i) for i, role in enumerate(ROLES)}
        self.control = {
            "kill": False,
            "revocation_revision": 1,
            "revoked_key_ids": [],
            "revoked_attestations": [],
            "implementation_digest": IMPL,
        }
        self.clock = [NOW]
        self.trust = TrustContext.offline_for_tests(
            environment=ENVIRONMENT,
            implementation_digest=IMPL,
            identity_digest="sha256:identity",
            template_digest="sha256:template",
            root_capability_digest="sha256:root",
            issuers={
                "issuer-1": TrustedKey(
                    "key-issuer", _pub(self.issuer_key), frozenset({"release_attestor"})
                )
            },
            approvers={
                f"approver-{role}": TrustedKey(
                    f"key-{role}", _pub(self.approver_keys[role]), frozenset({role})
                )
                for role in ROLES
            },
            artifact_root=self.root,
        )
        self.envelope = self.sign(self.payload())

    def snapshot(self, **over) -> dict:
        values = {
            "subject_type": "Application",
            "predicate": "depends_on",
            "object_type": "Application",
            "shadow_started_at": NOW - timedelta(days=40),
            "evaluated_at": NOW - timedelta(days=1),
            "expert_adjudicated_eligible_count": 250,
            "critical_failures": (),
            "escalation_recall": 1.0,
            "recall": 0.95,
            "precision_true_positives": 400,
            "precision_total": 400,
            "approvals": ROLES,
            "ai_spec_gates_passed": True,
        }
        values.update(over)
        return AdmissionEvaluationSnapshot.create(**values).model_dump(mode="json")

    def payload(self) -> dict:
        manifest, _ = verify_prerequisite_corpus(self.root, ["03.7", "03.8"])
        first = (self.root / "phases/13-ontology/13-20-SUMMARY.md").read_text()
        lineage = {
            "provider": "foundry",
            "agent_version": "1",
            "model": "gpt-offline",
            "prompt_hash": PROMPT_HASH,
            "schema_hash": SCHEMA_HASH,
            "policy_version": "proposal-policy-v1",
            "schema_version": "proposal-schema-v1",
        }
        return {
            "version": "maintenance-attestation/v1",
            "purpose": "offline-qualification",
            "issuer": {
                "issuer_id": "issuer-1",
                "key_id": "key-issuer",
                "role": "release_attestor",
            },
            "environment": ENVIRONMENT,
            "implementation_digest": IMPL,
            "identity_digest": "sha256:identity",
            "template_digest": "sha256:template",
            "root_capability_digest": "sha256:root",
            "prerequisite": {
                "targets": ["03.7", "03.8"],
                "manifest_digest": manifest,
                "plan20_finalization_digest": hashlib.sha256(first.encode()).hexdigest(),
                "inherited_preconditions_digest": "sha256:preconditions",
            },
            "deployment_decision": {"status": "accepted", "decision_digest": "sha256:dd"},
            "issued_at": (NOW - timedelta(days=1)).isoformat(),
            "not_before": (NOW - timedelta(days=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=30)).isoformat(),
            "revocation_revision": 1,
            "release": {
                "release_id": "release-1",
                "tenant_id": "tenant-1",
                "subscription_id": "sub-1",
                "connection_id": "offline-connection",
                "workspace_id": "workspace-1",
                "item_id": "item-1",
                "sources": SOURCES,
                "pair": {
                    "subject_type": "Application",
                    "predicate": "depends_on",
                    "object_type": "Application",
                },
                "lineage": lineage,
                "definition_fingerprint": vocabulary_fingerprint(),
                "ontology_version": "v1",
                "operations": ["admit", "restore"],
                "max_model_edges": 5,
                "native_planner": False,
            },
            "evaluation": {
                "snapshot": self.snapshot(),
                "bound_lineage": lineage,
                "bound_implementation_digest": IMPL,
            },
        }

    def sign(self, payload: dict, *, drop_role: str | None = None) -> dict:
        base = digest({k: v for k, v in payload.items() if k != "approvals"})
        approvals = []
        for role in ROLES:
            if role == drop_role:
                continue
            approval = {
                "role": role,
                "approver_id": f"approver-{role}",
                "key_id": f"key-{role}",
                "reason": "reviewed exact payload",
                "expires_at": (NOW + timedelta(days=30)).isoformat(),
            }
            approval["signature"] = _sign(
                self.approver_keys[role], approval_message(base, approval)
            )
            approvals.append(approval)
        payload = {**payload, "approvals": approvals}
        return {
            "algorithm": "Ed25519",
            "key_id": payload["issuer"]["key_id"],
            "payload": payload,
            "signature": _sign(self.issuer_key, canonical_json(payload)),
        }

    def reader(self) -> MaintenanceReleaseReader:
        return MaintenanceReleaseReader(
            trust=self.trust,
            envelope_source=lambda: copy.deepcopy(self.envelope),
            control_source=lambda: copy.deepcopy(self.control),
            clock=lambda: self.clock[0],
        )


@pytest.fixture
def authority(tmp_path: Path) -> Authority:
    return Authority(tmp_path)


def _entity(resource_id: str, entity_type: str, name: str) -> dict:
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": resource_id,
        "entity_id": resource_id,
        "timestamp": NOW.isoformat(),
        "change_version": "v1",
        "ingestion_run_id": INVENTORY_GENERATION,
        "entity_type": entity_type,
        "name": name,
        "resource_type": "example/apps",
        "location": "eastus",
        "payload_json": "{}",
        "lineage_json": "{}",
        "semantic_metadata_json": "{}",
        "lifecycle_status": "active",
        "valid_from": NOW.isoformat(),
        "retired_at": "",
        "ontology_version": "v1",
        "scope": SCOPE,
    }


def _member(resource_id: str, subject: str, obj: str) -> dict:
    return {
        "tenant_id": "tenant-1",
        "subscription_id": "sub-1",
        "resource_id": resource_id,
        "timestamp": NOW.isoformat(),
        "change_version": "v1",
        "ingestion_run_id": INVENTORY_GENERATION,
        "subject_id": subject,
        "subject_type": "Resource",
        "predicate": "member_of",
        "object_id": obj,
        "object_type": "Application",
        "source": "deterministic",
        "scope": SCOPE,
        "payload_json": "{}",
        "lineage_json": "{}",
        "lifecycle_status": "active",
        "valid_from": NOW.isoformat(),
        "retired_at": "",
        "ontology_version": "v1",
        "confidence": 1.0,
    }


def inventory_datasets() -> dict:
    return {
        "ontology_entities": [
            _entity(FRONTEND_APP, "Application", "frontend"),
            _entity(BACKEND_APP, "Application", "backend"),
            _entity(FRONTEND_ASSET, "Resource", "front"),
            _entity(BACKEND_ASSET, "Resource", "back"),
        ],
        "ontology_relationships": [
            _member("membership-front", FRONTEND_ASSET, FRONTEND_APP),
            _member("membership-back", BACKEND_ASSET, BACKEND_APP),
        ],
        "bronze_resources": [
            {
                "resource_id": FRONTEND_ASSET,
                "source_generation_id": INVENTORY_GENERATION,
                "payload_json": json.dumps(
                    {
                        "id": FRONTEND_ASSET,
                        "tags": {
                            "aiops.dependencyResourceIds": json.dumps([BACKEND_ASSET])
                        },
                    }
                ),
            },
            {
                "resource_id": BACKEND_ASSET,
                "source_generation_id": INVENTORY_GENERATION,
                "payload_json": json.dumps({"id": BACKEND_ASSET, "tags": {}}),
            },
        ],
    }


def monitor_row() -> dict:
    return {
        "TimeGenerated": NOW.isoformat(),
        "Id": "call-001",
        "OperationId": "operation-001",
        "_ResourceId": FRONTEND_ASSET,
        "_SubscriptionId": "sub-1",
        "AppRoleName": "frontend-role",
        "Target": "backend-role",
        "DependencyType": "HTTP",
        "Success": True,
        "SyntheticSource": "",
    }


class Curator:
    """Scripted curator; real parser/policy/store/validator process its output."""

    agent_version = "1"

    def __init__(self) -> None:
        self.last_attempt = None
        self.calls = 0

    async def propose(self, run, evidence):
        self.calls += 1
        self.last_attempt = {
            "agent_version": "1",
            "prompt_hash": PROMPT_HASH,
            "schema_hash": SCHEMA_HASH,
            "model": "gpt-offline",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "latency_ms": 5,
            "repair_attempt": 0,
            "error": [],
        }
        pair = next(
            row
            for row in evidence["candidate_pairs"]
            if row.get("subject_id") == FRONTEND_APP and row.get("predicate") == "depends_on"
        )
        return {
            "batch_id": evidence["batch_id"],
            "status": "proposals",
            "missing_evidence": [],
            "proposals": [
                {
                    "subject_id": pair["subject_id"],
                    "subject_type": pair["subject_type"],
                    "predicate": pair["predicate"],
                    "object_id": pair["object_id"],
                    "object_type": pair["object_type"],
                    "evidence_refs": list(pair["evidence_ids"]),
                    "observed_at": NOW.isoformat(),
                    "rationale": "Two exact independent source facts.",
                    "confidence": 0.95,
                    "uncertainty": [],
                    "disposition": "propose",
                }
            ],
        }


CONNECTION = SubscriptionConnection(
    connection_id="offline-connection",
    name="offline",
    tenant_id="tenant-1",
    subscription_id="sub-1",
    is_active=True,
)


def patch_inventory(monkeypatch) -> None:
    import ontology_discovery.runtime as runtime_module

    manifest = {"runId": INVENTORY_GENERATION, "startedAt": NOW.isoformat(), "source": "offline"}

    class Store:
        fs = None
        is_remote = False

        @staticmethod
        def current_generation():
            return "offline-snapshot"

    class Pipeline:
        store = Store()

        @staticmethod
        def refresh():
            return SimpleNamespace(manifest=manifest)

    monkeypatch.setattr(
        runtime_module, "build_connection_inventory_pipeline", lambda *a, **k: Pipeline()
    )
    monkeypatch.setattr(
        runtime_module.InventoryDatasetMapper, "load", lambda *a, **k: inventory_datasets()
    )


class Env:
    def __init__(self, tmp_path: Path, name: str) -> None:
        self.base = tmp_path / name
        self.runs_path = self.base / "runs.json"
        self.dispatch_path = self.base / "dispatch"
        self.store = OntologyRunStore(self.runs_path)
        self.dispatch = PublisherDispatchStore(str(self.dispatch_path)).coordinator()
        self.curator = Curator()

    def claim(self, source_generation: str = "logical-generation-7", lease_seconds: int = 600, deadline_seconds: int | None = None):
        queued, _ = self.store.get_or_create_run(
            connection_id=CONNECTION.connection_id,
            source_generation_id=source_generation,
            trigger="manual",
            requested_by="offline-test",
            now=NOW,
            **({"deadline_at": NOW + timedelta(seconds=deadline_seconds)} if deadline_seconds else {}),
        )
        return self.store.claim(
            queued["run_id"],
            expected_revision=queued["revision"],
            owner="offline-worker",
            lease_seconds=lease_seconds,
            now=NOW,
        )

    def processor(self, *, maintenance=None, ledger=None, **extra):
        curator = self.curator
        if maintenance is not None:
            # Explicit isolated offline budget transport: one scripted invocation
            # is one bounded attempt, including monkeypatched failure/timeout.
            # No real Foundry endpoint, credential or live qualification exists.
            scripted = curator

            async def transport(payload, *, timeout_seconds):
                context = json.loads(payload["input"][0]["content"])
                document = await scripted.propose(context["run"], context["evidence"])
                return {"document": document, "usage": (scripted.last_attempt or {}).get("usage")}

            class OfflineBudgetCurator(OntologyCurator):
                async def propose(self, run, evidence):
                    response = await self._request(self._payload(json.dumps({
                        "run": run, "evidence": evidence,
                    }, default=str)))
                    self.last_attempt = scripted.last_attempt
                    return response["document"]

            curator = OfflineBudgetCurator(
                project_endpoint="https://offline.invalid", agent_name="offline-curator",
                agent_version="1", transport=transport, max_transport_retries=0,
            )
            extra.setdefault("budget_ledger", BudgetLedger(self.base / "offline-budget.json"))
            extra.setdefault("pricing", {
                "version": "isolated-offline-fixture/v1",
                "input_per_million": 1.0, "output_per_million": 2.0,
            })
            extra.setdefault("max_cost_usd", 1.0)
            extra.setdefault("max_total_seconds", 1800.0)
            extra.setdefault("input_overhead_tokens", 0)  # scripted transport has no hidden prompt
        return ProductionConnectionProcessor(
            store=self.store,
            dispatch=self.dispatch,
            connector_config=object(),
            curator=curator,
            resolver=object(),
            monitor_dependency_reader=lambda _c: [monitor_row()],
            monitor_identity_bindings=lambda _c: {
                "frontend-role": FRONTEND_ASSET,
                "backend-role": BACKEND_ASSET,
            },
            now=lambda: NOW,
            maintenance=maintenance,
            first_admission_ledger=ledger,
            **extra,
        )

    def run(self, processor, run=None):
        run = run or self.claim()
        return asyncio.run(processor(CONNECTION, run)), run

    def published(self) -> list[dict]:
        view = PublisherDispatchStore(str(self.dispatch_path)).publisher()
        return view.list_due_publish(now=NOW + timedelta(days=1), limit=10)


def seed_reviewed_proposals(tmp_path: Path, monkeypatch, env: Env) -> None:
    """Obtain real content-addressed proposals via a probe pass, then accept them."""

    probe = Env(tmp_path, "probe")
    probe.run(probe.processor())
    for record in probe.store.list_proposals():
        saved, _ = env.store.save_proposal(
            proposal=record["proposal"],
            scope=record["scope"],
            source_generation_id=record["source_generation_id"],
            schema_version=record["schema_version"],
            policy_version=record["policy_version"],
            now=NOW,
        )
        env.store.review_proposal(
            saved["proposal_id"],
            action="accept",
            expected_revision=0,
            actor="steward@example.com",
            actor_roles={"ontology_steward"},
            reason="Two independent source facts reproduced.",
            now=NOW,
        )


def model_rows(candidate: dict) -> list[dict]:
    return [r for r in candidate["relationships"] if r.get("source") == "model"]


def maintenance_for(authority: Authority) -> MaintenanceAdmission:
    return MaintenanceAdmission(reader=authority.reader(), now=lambda: NOW)


# --------------------------------------------------------------------- tests


def test_authorized_pair_crosses_production_processor_validator_and_durable_dispatch(
    tmp_path, monkeypatch, authority
):
    patch_inventory(monkeypatch)
    env = Env(tmp_path, "main")
    seed_reviewed_proposals(tmp_path, monkeypatch, env)
    ledger = FirstAdmissionLedger(tmp_path / "ledger.json")
    result, _ = env.run(env.processor(maintenance=maintenance_for(authority), ledger=ledger))
    assert result["status"] == "dispatch_created"

    # Reconstruct both stores from disk; no object from the run is reused.
    rebuilt = PublisherDispatchStore(str(env.dispatch_path)).publisher()
    dispatched = rebuilt.list_due_publish(now=NOW + timedelta(days=1), limit=10)
    assert len(dispatched) == 1
    candidate = dispatched[0]["candidate"]
    rows = model_rows(candidate)
    assert len(rows) == 1
    row = rows[0]
    assert row["resource_id"].startswith("maintenance-rel://")
    assert (row["subject_id"], row["predicate"], row["object_id"]) == (
        FRONTEND_APP, "depends_on", BACKEND_APP,
    )
    assert row["model_derived"] is True and row["confidence"] == 1.0
    assert row["lifecycle_status"] == "active" and row["retired_at"] == ""
    # Absent from deterministic input, present only via admission.
    assert not any(
        r["predicate"] == "depends_on" and r["source"] != "model"
        for r in candidate["relationships"]
    )
    lineage = json.loads(row["lineage_json"])
    assert lineage["release_id"] == "release-1"
    assert lineage["attestation_digest"] == authority.reader().read().attestation_digest
    assert lineage["proposal_id"] in candidate["proposal_lineage"]
    assert candidate["maintenance_authorization"]["model_edge_ids"] == [row["resource_id"]]
    # Ordinary, unchanged validator accepts the complete graph.
    assert OntologyValidator().validate(
        candidate["entities"], candidate["relationships"]
    ).passed
    assert OntologyRunStore(env.runs_path).get_review(lineage["proposal_id"])["status"] == "accepted"


def test_default_phase13_processor_stays_shadow_and_test_switch_cannot_enable(
    tmp_path, monkeypatch
):
    patch_inventory(monkeypatch)
    env = Env(tmp_path, "default")
    seed_reviewed_proposals(tmp_path, monkeypatch, env)
    env.run(env.processor())
    candidate = env.published()[0]["candidate"]
    assert model_rows(candidate) == []
    policy = ProposalPolicy(shadow_mode=False, allow_pair_release_testing=True)
    assert policy.shadow_mode is False  # test switch exists but processor never uses it


def test_duplicate_delivery_and_restart_yield_byte_identical_rows(
    tmp_path, monkeypatch, authority
):
    patch_inventory(monkeypatch)
    ledger_path = tmp_path / "ledger.json"
    rows = []
    for name in ("first", "second"):
        env = Env(tmp_path, name)
        seed_reviewed_proposals(tmp_path / name, monkeypatch, env)
        authority.clock[0] = NOW
        env.run(
            env.processor(
                maintenance=maintenance_for(authority),
                ledger=FirstAdmissionLedger(ledger_path),
            )
        )
        rows.append(model_rows(env.published()[0]["candidate"])[0])
    assert canonical_json(rows[0]) == canonical_json(rows[1])
    assert json.loads(ledger_path.read_text())[rows[0]["resource_id"]] == rows[0]["valid_from"]


def test_changed_source_version_changes_change_version_not_identity(tmp_path, authority):
    release = authority.reader().read()
    entities = {e["resource_id"].casefold(): e for e in inventory_datasets()["ontology_entities"]}
    evidence = {
        "e1": {"source": SOURCES[0]},
        "e2": {"source": SOURCES[1]},
    }
    relationship = {
        "subject_id": FRONTEND_APP.casefold(), "subject_type": "Application",
        "predicate": "depends_on", "object_id": BACKEND_APP.casefold(),
        "object_type": "Application", "evidence_refs": ["e1", "e2"],
        # Caller-supplied lifecycle/scope/timestamps must be ignored.
        "valid_from": "1999-01-01T00:00:00+00:00", "scope": "foreign", "timestamp": "x",
        "lifecycle_status": "retired",
    }
    ledger = FirstAdmissionLedger(tmp_path / "l.json")
    built = []
    for generation, instant in (("g1", NOW), ("g2", NOW + timedelta(hours=1))):
        rid_probe = materialize_relationship(
            proposal_id="p", relationship=relationship, release=release,
            entities=entities, evidence_records=evidence, source_observed_at=instant,
            ingestion_run_id="run", first_admitted_at="tmp", source_generation_id=generation,
            ontology_version="v1",
        )["resource_id"]
        built.append(
            materialize_relationship(
                proposal_id="p", relationship=relationship, release=release,
                entities=entities, evidence_records=evidence, source_observed_at=instant,
                ingestion_run_id="run",
                first_admitted_at=ledger.get_or_record(rid_probe, instant),
                source_generation_id=generation, ontology_version="v1",
            )
        )
    assert built[0]["resource_id"] == built[1]["resource_id"]
    assert built[0]["change_version"] != built[1]["change_version"]
    assert built[0]["valid_from"] == built[1]["valid_from"] == NOW.isoformat()
    assert built[0]["scope"] == release.scope and built[0]["lifecycle_status"] == "active"
    sparse = {"resource_id": "maintenance-rel://x", "source": "model", "confidence": 1.0}
    entities_list = list(entities.values())
    assert not OntologyValidator().validate(entities_list, [sparse]).passed


MUTATIONS = {
    "unsupported_native": lambda a, p: p["release"].update(native_planner=True),
    "wrong_environment": lambda a, p: p.update(environment="other"),
    "implementation_drift": lambda a, p: p.update(implementation_digest="sha256:other"),
    "deployment_unaccepted": lambda a, p: p["deployment_decision"].update(status="pending"),
    "expired": lambda a, p: p.update(expires_at=(NOW - timedelta(hours=1)).isoformat()),
    "future": lambda a, p: p.update(not_before=(NOW + timedelta(hours=1)).isoformat()),
    "stale_evaluation": lambda a, p: p["evaluation"].update(snapshot=a.snapshot(
        shadow_started_at=NOW - timedelta(days=100), evaluated_at=NOW - timedelta(days=60))),
    "ineligible_evaluation": lambda a, p: p["evaluation"].update(snapshot=a.snapshot(recall=0.5)),
    "evaluation_bound_to_old_implementation": lambda a, p: p["evaluation"].update(bound_implementation_digest="sha256:old"),
    "plan20_digest": lambda a, p: p["prerequisite"].update(plan20_finalization_digest="0" * 64),
    "manifest_digest": lambda a, p: p["prerequisite"].update(manifest_digest="0" * 64),
    "missing_preconditions": lambda a, p: p["prerequisite"].update(inherited_preconditions_digest=""),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_signed_but_mismatched_attestation_denies(authority, name):
    payload = authority.payload()
    MUTATIONS[name](authority, payload)
    authority.envelope = authority.sign(payload)
    reason = authority.reader().check()
    assert reason, name


def test_forged_unknown_revoked_and_approval_failures_deny(authority):
    good = authority.envelope
    forged = copy.deepcopy(good)
    forged["payload"]["release"]["max_model_edges"] = 99
    authority.envelope = forged
    assert authority.reader().check() == "signature_invalid"
    authority.envelope = {**good, "algorithm": "none"}
    assert authority.reader().check() == "algorithm_not_allowed"
    authority.envelope = {**good, "key_id": "unknown"}
    assert authority.reader().check() == "issuer_untrusted"
    authority.envelope = authority.sign(authority.payload(), drop_role="security_owner")
    assert authority.reader().check() == "approvals_incomplete"
    authority.envelope = good
    assert authority.reader().check() == ""
    authority.control["revoked_key_ids"] = ["key-issuer"]
    assert authority.reader().check() == "issuer_revoked"
    authority.control["revoked_key_ids"] = []
    authority.control["revocation_revision"] = 2
    assert authority.reader().check() == "revocation_revision_changed"
    authority.control["revocation_revision"] = 1
    authority.control["kill"] = True
    assert authority.reader().check() == "kill_switch_engaged"
    authority.control["kill"] = False
    authority.control["implementation_digest"] = "sha256:drifted"
    assert authority.reader().check() == "implementation_drift"


def test_self_approval_is_not_authentication(authority):
    payload = authority.payload()
    envelope = authority.sign(payload)
    # The issuer cannot also act as an approver, and an unsigned role string fails.
    envelope["payload"]["approvals"][0]["approver_id"] = "issuer-1"
    envelope["signature"] = _sign(authority.issuer_key, canonical_json(envelope["payload"]))
    authority.envelope = envelope
    assert authority.reader().check() == "approval_untrusted"


def test_prerequisite_corpus_requires_exact_counts_and_order(tmp_path):
    root = tmp_path / "p"
    write_corpus(root, phase13_summaries=21)  # the real upstream shortfall
    with pytest.raises(MaintenanceDenied) as shortfall:
        verify_prerequisite_corpus(root, ["03.7"])
    assert shortfall.value.reason == "prerequisite_summary_missing:13-22"

    ok = tmp_path / "ok"
    write_corpus(ok)
    verify_prerequisite_corpus(ok, ["03.7", "03.8"])
    verification = ok / "phases/09-consumer/09-VERIFICATION.md"
    verification.write_text("---\nstatus: passed\nwaiver: accepted\n---\n")
    with pytest.raises(MaintenanceDenied):
        verify_prerequisite_corpus(ok, ["03.7"])
    verification.write_text("---\nstatus: gaps_found\n---\n")
    with pytest.raises(MaintenanceDenied):
        verify_prerequisite_corpus(ok, ["03.7"])


def test_real_repository_corpus_is_blocked_and_not_lowered():
    planning = Path(__file__).resolve().parents[1] / ".planning"
    if not planning.is_dir():
        pytest.skip("planning corpus not present")
    with pytest.raises(MaintenanceDenied):
        verify_prerequisite_corpus(planning, ["03.7", "03.8"])


def test_plan21_preceding_plan20_denies(authority):
    directory = authority.root / "phases/13-ontology"
    first = directory / "13-20-SUMMARY.md"
    first.write_text(first.read_text().replace("2026-01-01", "2026-02-01"))
    payload = authority.payload()  # reissued over the changed files
    authority.envelope = authority.sign(payload)
    assert authority.reader().check() == "plan21_precedes_plan20_finalization" or (
        authority.reader().check().startswith("plan21_")
    )


def test_prerequisite_file_change_after_signing_denies(authority):
    (authority.root / "phases/13-ontology/13-22-SUMMARY.md").unlink()
    assert authority.reader().check() == "prerequisite_summary_missing:13-22"


def test_processor_denies_without_review_forgery_kill_and_keeps_deterministic(
    tmp_path, monkeypatch, authority
):
    patch_inventory(monkeypatch)
    # No accepted review -> awaiting_review, deterministic graph still dispatched.
    env = Env(tmp_path, "unreviewed")
    env.run(env.processor(
        maintenance=maintenance_for(authority),
        ledger=FirstAdmissionLedger(tmp_path / "l1.json"),
    ))
    assert model_rows(env.published()[0]["candidate"]) == []
    assert len(env.published()[0]["candidate"]["relationships"]) == 2

    # Kill: no provider call at all, deterministic refresh still dispatches.
    authority.control["kill"] = True
    env2 = Env(tmp_path, "killed")
    seed_reviewed_proposals(tmp_path / "k", monkeypatch, env2)
    env2.curator.calls = 0
    env2.run(env2.processor(
        maintenance=maintenance_for(authority),
        ledger=FirstAdmissionLedger(tmp_path / "l2.json"),
    ))
    assert env2.curator.calls == 0
    assert model_rows(env2.published()[0]["candidate"]) == []

    # Forged envelope denies admission even with accepted review.
    authority.control["kill"] = False
    forged = copy.deepcopy(authority.envelope)
    forged["payload"]["release"]["max_model_edges"] = 4
    authority.envelope = forged
    env3 = Env(tmp_path, "forged")
    seed_reviewed_proposals(tmp_path / "f", monkeypatch, env3)
    env3.run(env3.processor(
        maintenance=maintenance_for(authority),
        ledger=FirstAdmissionLedger(tmp_path / "l3.json"),
    ))
    assert model_rows(env3.published()[0]["candidate"]) == []


def test_release_lost_before_dispatch_aborts_without_dispatch(tmp_path, monkeypatch, authority):
    patch_inventory(monkeypatch)
    env = Env(tmp_path, "lost")
    seed_reviewed_proposals(tmp_path, monkeypatch, env)
    admission = maintenance_for(authority)
    calls = {"n": 0}
    real = admission.check_open

    def flaky(operation="admit"):
        calls["n"] += 1
        if calls["n"] >= 2:  # open at start, revoked immediately before dispatch
            authority.control["kill"] = True
        return real(operation)

    admission.check_open = flaky
    with pytest.raises(RuntimeError, match="maintenance_authorization_lost"):
        env.run(env.processor(maintenance=admission, ledger=FirstAdmissionLedger(tmp_path / "l.json")))
    assert env.published() == []


def test_runtime_reader_is_read_only_and_production_refuses_test_trust(tmp_path, authority):
    reader = authority.reader()
    assert not [n for n in dir(reader) if n.startswith(("write", "issue", "update", "approve", "save"))]
    assert build_production_reader({}) is None
    config = {
        "purpose": "offline-qualification", "environment": ENVIRONMENT,
        "implementation_digest": IMPL, "identity_digest": "i", "template_digest": "t",
        "root_capability_digest": "r", "issuers": {}, "approvers": {},
        "artifact_root": str(authority.root), "release_path": "x", "control_path": "y",
    }
    path = tmp_path / "trust.json"
    path.write_text(json.dumps(config))
    with pytest.raises(MaintenanceConfigError, match="not_live"):
        build_production_reader({"ONTOLOGY_MAINTENANCE_TRUST_CONFIG": str(path)})
    config["purpose"] = "live-release"
    config["issuers"] = {"i": {"key_id": "k", "public_key_b64": base64.b64encode(_pub(_key(1))).decode(),
                               "roles": ["release_attestor"], "origin": "test"}}
    path.write_text(json.dumps(config))
    with pytest.raises(MaintenanceConfigError, match="origin_rejected"):
        build_production_reader({"ONTOLOGY_MAINTENANCE_TRUST_CONFIG": str(path)})
    # A live-purpose trust rejects an offline-purpose attestation.
    live = TrustContext(**{**authority.trust.__dict__, "purpose": "live-release"})
    live_reader = MaintenanceReleaseReader(
        trust=live, envelope_source=lambda: authority.envelope,
        control_source=lambda: authority.control, clock=lambda: NOW,
    )
    assert live_reader.check() == "purpose_mismatch"


@pytest.mark.parametrize("field", ["prompt_hash", "schema_hash", "agent_version", "provider"])
def test_observed_lineage_mismatch_blocks_admission(tmp_path, monkeypatch, authority, field):
    patch_inventory(monkeypatch)
    payload = authority.payload()
    other = "9" if field == "agent_version" else ("native" if field == "provider" else "c" * 64)
    payload["release"]["lineage"][field] = other
    payload["evaluation"]["bound_lineage"][field] = other
    authority.envelope = authority.sign(payload)
    assert authority.reader().check() == ""  # validly signed and internally consistent
    env = Env(tmp_path, "lineage")
    seed_reviewed_proposals(tmp_path, monkeypatch, env)
    env.run(env.processor(
        maintenance=maintenance_for(authority),
        ledger=FirstAdmissionLedger(tmp_path / "l.json"),
    ))
    assert model_rows(env.published()[0]["candidate"]) == []


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(tenant_id="tenant-2"),
    lambda r: r.update(connection_id="other-connection"),
    lambda r: r["pair"].update(subject_type="Resource"),
    lambda r: r.update(sources=["azure-monitor:AppDependencies", "other:source"]),
    lambda r: r.update(definition_fingerprint="sha256:stale"),
])
def test_release_scope_pair_source_definition_mismatch_blocks_admission(
    tmp_path, monkeypatch, authority, mutate
):
    patch_inventory(monkeypatch)
    payload = authority.payload()
    mutate(payload["release"])
    authority.envelope = authority.sign(payload)
    env = Env(tmp_path, "scope")
    seed_reviewed_proposals(tmp_path, monkeypatch, env)
    env.run(env.processor(
        maintenance=maintenance_for(authority),
        ledger=FirstAdmissionLedger(tmp_path / "l.json"),
    ))
    assert model_rows(env.published()[0]["candidate"]) == []
