"""Regression tests for Phase 03.2 Recommendation 1 (03-REVIEW.md CR-01/WR-07).

A live remediation plan's identity used to be a hash of mutable evidence
(``missing_kbs``). The moment a patch install actually succeeded, that same
evidence changed, the plan's ``plan_id`` changed with it, and the execution
record for the run that just changed a production host became permanently
unreachable -- never polled, never verified, orphaned from its audit trail.

These tests prove: (1) plan identity is now stable regardless of evidence
mutation, for both the live and Fabric planner families; (2) an executed
plan's execution record survives evidence mutation and plan regeneration,
and can still reach a verified terminal state; (3) authorization for a
single execution read is decided from the execution's own scope attributes,
not from the continued existence/scope of its originating plan.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from api.errors import ApiError, ErrorCode
from api.routers.remediation import get_execution
from api.scope import Scope
from intelligence.remediation.approval_decisions import execution_snapshot_hash
from intelligence.remediation.execution_service import RemediationExecutionService
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.plan_repository import PlanRepository
from operations.patching.adapters import RecordingPatchExecutionAdapter
from operations.patching.service import PatchingService
from semantic.live_operations import LiveRemediationPlanner
from tests.remediation_scenario import remediation_planner

VM_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"

NOW = datetime(2026, 8, 18, 13, tzinfo=UTC)


class _MutableVulnerabilityService:
    """A live ``asset_exposures()`` feed whose ``missing_kbs`` may be mutated.

    Mirrors exactly what a successful patch install does to live evidence:
    the missing-KB set for the same asset shrinks or empties between one
    ``generate_plans()`` call and the next.
    """

    def __init__(self) -> None:
        self.freshness = "2026-08-18T13:00:00Z"
        self.missing_kbs = ["KB600001"]

    def asset_exposures(self, scope=None) -> list[dict]:
        return [
            {
                "asset_id": VM_ID,
                "name": "vm-payments",
                "inventory_kind": "Azure VM",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "subscription_id": "sub-1",
                "business_service": "Checkout",
                "application": "Payments API",
                "missing_kbs": list(self.missing_kbs),
                "finding_ids": ["finding-001"],
                "finding_count": 1,
                "severities": ["Critical"],
                "cve_ids": ["CVE-2026-0001"],
            }
        ]


def _future_expiry() -> str:
    return (datetime.now(UTC) + timedelta(days=30)).isoformat()


class _FakeExecutionVerifier:
    """Duck-typed :class:`ExecutionVerifier` returning a fixed outcome."""

    def __init__(self, outcome: dict) -> None:
        self._outcome = outcome
        self.calls = 0

    def verify(self, record: dict) -> dict:
        self.calls += 1
        return self._outcome


def _patch_recovery_plan(result: dict) -> dict:
    return next(row for row in result["plans"] if row["action_id"] == "controlled-patch-recovery")


def _approve(planner: LiveRemediationPlanner, plan: dict) -> dict:
    """Approve ``plan`` with a snapshot that will validate against the target."""
    snapshot = {
        "target_id": VM_ID,
        "patch_ids": ["KB600001"],
        "target_kind": "Azure VM",
        "operation": "install_patches",
        "action_version": plan["action_version"],
    }
    snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)
    # Record one decision per distinct role_id this plan's own
    # approval_requirements actually demands (Phase 03.5 CR-05 fix: one
    # decision attests exactly one required role via approval_role_id --
    # even this live-planner default single-role policy still carries its
    # own distinct stage-gate row alongside the RBAC-compatible policy
    # row, so a single legacy-shaped decision can no longer satisfy both).
    distinct_role_ids = sorted(
        {
            str(row.get("role_id") or row.get("role") or "")
            for row in plan.get("approval_requirements") or []
        }
    )
    if not distinct_role_ids:
        distinct_role_ids = [""]
    for role_id in distinct_role_ids:
        planner.repository.decisions.append(
            plan=plan,
            decision="approved",
            approver="approver@example.com",
            reason="CAB approved after evidence review",
            scope={},
            action_version=plan["action_version"],
            expires_at=_future_expiry(),
            execution_snapshot=snapshot,
            approver_roles=[role_id] if role_id else [],
            approval_role_id=role_id,
        )
    return snapshot


def _build_service(
    planner: LiveRemediationPlanner,
    vulnerability_service: _MutableVulnerabilityService,
    *,
    verifier=None,
) -> tuple[RemediationExecutionService, RemediationExecutionStore]:
    patching_service = PatchingService(
        vulnerability_service,
        adapter=RecordingPatchExecutionAdapter(),
        require_human_approval=False,
    )
    store = RemediationExecutionStore()
    service = RemediationExecutionService(
        plan_repository=planner.repository,
        patching_service=patching_service,
        execution_store=store,
        execution_verifier=verifier,
        now=lambda: NOW,
    )
    return service, store


def test_live_plan_id_is_stable_across_repeated_missing_kbs_changes() -> None:
    """Acceptance (b): plan_id is byte-identical across >=10 generations."""
    vulnerability_service = _MutableVulnerabilityService()
    planner = LiveRemediationPlanner(vulnerability_service)

    first_result = planner.generate_plans()
    plan_id = _patch_recovery_plan(first_result)["plan_id"]

    for iteration in range(10):
        vulnerability_service.missing_kbs = (
            [] if iteration % 2 == 0 else [f"KB60000{iteration}"]
        )
        result = planner.generate_plans()
        assert _patch_recovery_plan(result)["plan_id"] == plan_id


def test_live_patch_action_version_ignores_arg_collection_time() -> None:
    first_service = _MutableVulnerabilityService()
    second_service = _MutableVulnerabilityService()
    second_service.freshness = "2026-08-18T13:05:00Z"

    first = _patch_recovery_plan(
        LiveRemediationPlanner(first_service).generate_plans()
    )
    second = _patch_recovery_plan(
        LiveRemediationPlanner(second_service).generate_plans()
    )

    assert first["action_version"] == second["action_version"]
    assert first["evidence_citations"][0]["observed_at"] == ""
    assert second["evidence_citations"][0]["observed_at"] == ""


def test_live_patch_action_version_ignores_derived_cve_enrichment() -> None:
    """A KB-to-CVE lookup must not version the governed target/KB action."""

    class _EnrichedVulnerabilityService(_MutableVulnerabilityService):
        def __init__(self, finding_id: str) -> None:
            super().__init__()
            self.finding_id = finding_id

        def asset_exposures(self, scope=None) -> list[dict]:
            rows = super().asset_exposures(scope)
            rows[0]["finding_ids"] = [self.finding_id]
            return rows

    source_id = (
        "/subscriptions/SUB-1/resourceGroups/RG/providers/"
        "Microsoft.HybridCompute/machines/VM-1/"
        "patchAssessmentResults/latest/softwarePatches/1"
    )
    first = _patch_recovery_plan(
        LiveRemediationPlanner(
            _EnrichedVulnerabilityService(f"{source_id}|CVE-2026-0001")
        ).generate_plans()
    )
    second = _patch_recovery_plan(
        LiveRemediationPlanner(
            _EnrichedVulnerabilityService(
                f"{source_id.casefold()}|KB-600001"
            )
        ).generate_plans()
    )
    different_source = _patch_recovery_plan(
        LiveRemediationPlanner(
            _EnrichedVulnerabilityService("patch-assessment-002|CVE-2026-0001")
        ).generate_plans()
    )

    assert first["plan_id"] == second["plan_id"]
    assert first["recommended_action"] == second["recommended_action"]
    assert first["action_version"] == second["action_version"]
    assert first["evidence_citations"] == second["evidence_citations"]
    assert different_source["action_version"] != first["action_version"]


@pytest.mark.parametrize("finding_count", [9, 10, 11])
def test_live_patch_action_version_canonicalizes_citations_before_limiting(
    finding_count: int,
) -> None:
    """Provider row order must not select a different first-ten evidence set."""

    class _ManyFindingVulnerabilityService(_MutableVulnerabilityService):
        def __init__(self, finding_ids: list[str]) -> None:
            super().__init__()
            self.finding_ids = finding_ids

        def asset_exposures(self, scope=None) -> list[dict]:
            rows = super().asset_exposures(scope)
            rows[0]["finding_ids"] = list(self.finding_ids)
            return rows

    finding_ids = [f"finding-{index:02d}" for index in range(finding_count)]
    first = _patch_recovery_plan(
        LiveRemediationPlanner(
            _ManyFindingVulnerabilityService(finding_ids)
        ).generate_plans()
    )
    second = _patch_recovery_plan(
        LiveRemediationPlanner(
            _ManyFindingVulnerabilityService(list(reversed(finding_ids)))
        ).generate_plans()
    )

    assert first["action_version"] == second["action_version"]
    assert first["evidence_citations"] == second["evidence_citations"]


def test_live_plan_id_is_stable_across_subscription_id_casing_changes() -> None:
    """WR-03: the identity hash casefolds ``subscription_id`` the same way
    ``canonical_resource_key`` already casefolds the target. ARG/vulnerability
    feed rows are external data whose GUID casing this codebase does not
    control; without normalization, the same asset reported with a
    differently-cased subscription GUID between two polls would mint a new
    plan_id, reproducing the CR-01/WR-07 audit-orphaning failure mode."""

    class _CasingVulnerabilityService(_MutableVulnerabilityService):
        def __init__(self) -> None:
            super().__init__()
            self.subscription_id = "sub-1"

        def asset_exposures(self, scope=None) -> list[dict]:
            rows = super().asset_exposures(scope)
            for row in rows:
                row["subscription_id"] = self.subscription_id
            return rows

    vulnerability_service = _CasingVulnerabilityService()
    planner = LiveRemediationPlanner(vulnerability_service)

    first_result = planner.generate_plans()
    plan_id = _patch_recovery_plan(first_result)["plan_id"]

    for casing in ("SUB-1", "Sub-1", "sUb-1", "sub-1"):
        vulnerability_service.subscription_id = casing
        result = planner.generate_plans()
        assert _patch_recovery_plan(result)["plan_id"] == plan_id


def test_plan_repository_serializes_replace_generation_and_reads() -> None:
    """WR-01: hybrid_remediation now shares one ``PlanRepository`` across
    concurrently in-flight requests for up to 30s, and every remediation
    route handler is a plain ``def`` route Starlette dispatches to its
    worker thread pool. ``replace_generation``/``list``/``get`` must
    therefore serialize the same way ``RemediationExecutionStore`` already
    does around every read/write, instead of racing unsynchronized on the
    same shared instance."""
    repository = PlanRepository()
    repository.replace_generation([{"plan_id": "RMP-1", "title": "one"}])

    started = threading.Event()
    release = threading.Event()

    def _hold_lock() -> None:
        with repository._lock:
            started.set()
            assert release.wait(timeout=5), "writer never released the lock"

    holder = threading.Thread(target=_hold_lock)
    holder.start()
    assert started.wait(timeout=5), "writer never acquired the lock"

    reader_result: list[dict | None] = []

    def _read() -> None:
        reader_result.append(repository.get("RMP-1"))

    reader = threading.Thread(target=_read)
    reader.start()
    # The reader must block while the writer holds the lock -- proving get()
    # and replace_generation() share the same lock rather than racing.
    reader.join(timeout=0.2)
    assert reader.is_alive(), "reader did not block on the writer's held lock"

    release.set()
    holder.join(timeout=5)
    reader.join(timeout=5)
    assert not reader.is_alive()
    assert reader_result == [{"plan_id": "RMP-1", "title": "one"}]


def test_fabric_plan_id_is_stable_across_repeated_generation() -> None:
    """Regression guard: the Fabric/snapshot planner was already stable."""
    planner = remediation_planner()
    plan_ids: set[str] = set()

    for _ in range(10):
        result = planner.generate_plans()
        plan_ids.add(tuple(sorted(row["plan_id"] for row in result["plans"])))

    assert len(plan_ids) == 1


def test_executed_plan_survives_evidence_mutation_and_reaches_verified_terminal_state() -> None:
    """Acceptance (a): execution/audit continuity survives evidence refresh."""
    vulnerability_service = _MutableVulnerabilityService()
    planner = LiveRemediationPlanner(vulnerability_service)

    generated = planner.generate_plans()
    plan = _patch_recovery_plan(generated)
    _approve(planner, plan)

    verifier = _FakeExecutionVerifier(
        {"verifiable": True, "outcome": "succeeded", "verified_state": "KB600001 installed"}
    )
    service, store = _build_service(planner, vulnerability_service, verifier=verifier)

    executed = service.execute(plan["plan_id"], requested_by="operator@example.com")
    assert executed["status"] == "running"
    execution_id = executed["execution_id"]

    # The evidence that used to be baked into plan_id changes -- exactly what
    # a successful patch install does -- and plans regenerate.
    vulnerability_service.missing_kbs = []
    regenerated = planner.generate_plans()
    regenerated_plan = _patch_recovery_plan(regenerated)
    assert regenerated_plan["plan_id"] == plan["plan_id"]

    fetched = service.get_execution(execution_id)
    assert fetched is not None
    assert fetched["execution_id"] == execution_id
    assert fetched["plan_id"] == plan["plan_id"]

    polled = service.poll_verification(execution_id)
    assert polled["execution_id"] == execution_id
    assert polled["status"] == "succeeded"
    assert store.get(execution_id)["status"] == "succeeded"


def test_get_execution_out_of_scope_is_not_found_even_though_plan_still_matches() -> None:
    """A restricted scope that doesn't match the execution's own scope 404s,
    even though the underlying plan (which is never consulted) still exists
    and would itself match."""
    vulnerability_service = _MutableVulnerabilityService()
    planner = LiveRemediationPlanner(vulnerability_service)

    generated = planner.generate_plans()
    plan = _patch_recovery_plan(generated)
    _approve(planner, plan)

    service, _ = _build_service(planner, vulnerability_service)
    executed = service.execute(plan["plan_id"], requested_by="operator@example.com")
    execution_id = executed["execution_id"]

    context = SimpleNamespace(execution_provider=lambda scope: service)
    restricted_scope = Scope({"subscription": ["sub-does-not-exist"]})

    with pytest.raises(ApiError) as excinfo:
        get_execution(execution_id, context, restricted_scope)

    assert excinfo.value.code == ErrorCode.NOT_FOUND

    # An unrestricted -- or correctly matching -- scope still reaches it.
    unrestricted = get_execution(execution_id, context, Scope.unrestricted())
    assert unrestricted["data"]["execution_id"] == execution_id


class _DefenderConfigurationVulnerabilityService:
    """A live ``defender_posture()`` feed whose ``last_assessed_at`` may be mutated.

    Used to prove the Defender-configuration family's ``action_version`` is
    evidence-content-sensitive via the shared ``action_version_for()`` helper
    (Phase 03.5, Plan 04).
    """

    def __init__(self) -> None:
        self.freshness = "2026-09-03T00:00:00Z"
        self.last_assessed_at = "2026-09-03T00:00:00Z"

    def asset_exposures(self, scope=None) -> list[dict]:
        return []

    def defender_posture(self, scope=None) -> list[dict]:
        return [
            {
                "assessment_id": "assessment-servers",
                "asset_id": VM_ID,
                "asset_name": "vm-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "inventory_kind": "Azure VM",
                "severity": "high",
                "subscription_id": "sub-1",
                "business_service": "Checkout",
                "application": "Payments",
                "last_assessed_at": self.last_assessed_at,
                "recommendation": "Microsoft Defender for Servers should be enabled",
            }
        ]


def _defender_plan(result: dict) -> dict:
    return next(
        row
        for row in result["plans"]
        if row["opportunity_type"] == "Defender configuration"
    )


def test_patch_plan_approval_requirements_use_the_apporval_engine_shape() -> None:
    vulnerability_service = _MutableVulnerabilityService()
    planner = LiveRemediationPlanner(vulnerability_service)

    plan = _patch_recovery_plan(planner.generate_plans())

    requirement = next(
        row for row in plan["approval_requirements"] if row["role"] == "Change approver"
    )
    assert requirement["policy_id"] == "live-patch-change-approval"
    assert "reason" not in requirement
    assert "approval_evidence_required" in requirement


def test_defender_configuration_plan_approval_requirements_use_the_approval_engine_shape() -> None:
    vulnerability_service = _DefenderConfigurationVulnerabilityService()
    planner = LiveRemediationPlanner(vulnerability_service)

    plan = _defender_plan(planner.generate_plans())

    requirement = next(
        row
        for row in plan["approval_requirements"]
        if row["role"] == "Security Response Owner"
    )
    assert requirement["policy_id"] == "live-defender-configuration-approval"
    assert "reason" not in requirement


def test_patch_action_version_changes_when_missing_kbs_changes_and_is_stable_otherwise() -> None:
    vulnerability_service = _MutableVulnerabilityService()
    planner = LiveRemediationPlanner(vulnerability_service)

    first = _patch_recovery_plan(planner.generate_plans())["action_version"]
    second = _patch_recovery_plan(planner.generate_plans())["action_version"]
    assert first == second

    vulnerability_service.missing_kbs = ["KB600001", "KB600002"]
    changed = _patch_recovery_plan(planner.generate_plans())["action_version"]
    assert changed != first

    # plan_id stability (D-01) is unaffected by the action_version change.
    assert (
        _patch_recovery_plan(planner.generate_plans())["plan_id"]
        == _patch_recovery_plan(planner.generate_plans())["plan_id"]
    )


def test_defender_configuration_action_version_changes_when_last_assessed_at_changes() -> None:
    vulnerability_service = _DefenderConfigurationVulnerabilityService()
    planner = LiveRemediationPlanner(vulnerability_service)

    first = _defender_plan(planner.generate_plans())["action_version"]
    second = _defender_plan(planner.generate_plans())["action_version"]
    assert first == second

    vulnerability_service.last_assessed_at = "2026-09-04T00:00:00Z"
    changed = _defender_plan(planner.generate_plans())["action_version"]
    assert changed != first


def test_configuration_plan_evidence_citation_freshness_is_computed_not_asserted() -> None:
    """Phase 03.6 UI-SPEC: '_configuration_plan' must never hardcode
    'freshness': 'current' -- it must be computed from the citation's own
    `last_assessed_at` timestamp via `classify_freshness`."""
    vulnerability_service = _DefenderConfigurationVulnerabilityService()
    vulnerability_service.last_assessed_at = "2026-01-01T00:00:00Z"
    planner = LiveRemediationPlanner(vulnerability_service)

    plan = _defender_plan(planner.generate_plans())

    citation = plan["evidence_citations"][0]
    assert citation["freshness"] == "stale"
    assert citation["freshness"] != "current"


def test_live_plan_evidence_citation_freshness_is_computed_not_asserted() -> None:
    """Phase 03.6 UI-SPEC: '_plan' must never hardcode 'freshness':
    'current' -- it must be computed from the service's own freshness
    timestamp via `classify_freshness`."""
    vulnerability_service = _MutableVulnerabilityService()
    vulnerability_service.freshness = datetime.now(UTC).isoformat()
    planner = LiveRemediationPlanner(vulnerability_service)

    plan = _patch_recovery_plan(planner.generate_plans())

    citation = plan["evidence_citations"][0]
    assert citation["freshness"] == "fresh"
    assert citation["freshness"] != "current"
