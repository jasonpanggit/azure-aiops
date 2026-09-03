"""Safety tests for bounded Defender configuration remediation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from api.scope import Scope
from intelligence.remediation.action_catalog import (
    EXECUTABLE_ACTION_IDS,
    governed_action,
)
from intelligence.remediation.approval_decisions import execution_snapshot_hash
from intelligence.remediation.execution_service import (
    RemediationExecutionError,
    RemediationExecutionService,
)
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.execution_verifier import ExecutionVerifier
from intelligence.remediation.plan_repository import PlanRepository
from operations.defender_configuration import (
    ENABLE_DEFENDER_SERVERS_P1,
    ENABLE_DEFENDER_STORAGE_V2,
    AzureArmDefenderConfigurationAdapter,
    DefenderConfigurationResult,
    DefenderConfigurationUnavailable,
    build_defender_configuration_snapshot,
)
from semantic.live_operations import LiveRemediationPlanner

NOW = datetime(2026, 9, 3, tzinfo=UTC)
VM_ID = (
    "/subscriptions/sub-1/resourceGroups/rg/providers/"
    "Microsoft.Compute/virtualMachines/vm-1"
)


class _Credential:
    def get_token(self, *scopes, **kwargs):
        return SimpleNamespace(token="token")


class _RecordingAdapter:
    def __init__(self) -> None:
        self.state = {"pricingTier": "Free"}
        self.submissions: list[dict] = []

    def inspect(self, request: dict) -> dict:
        import hashlib
        import json

        digest = hashlib.sha256(
            json.dumps(
                self.state, separators=(",", ":"), sort_keys=True
            ).encode()
        ).hexdigest()
        return {"etag": '"v1"', "state_hash": digest, "properties": self.state}

    def submit(self, snapshot: dict) -> DefenderConfigurationResult:
        self.submissions.append(snapshot)
        return DefenderConfigurationResult(
            provider="recording",
            provider_job_id=(
                "https://management.azure.com"
                f"{snapshot['request']['path']}?api-version=2024-01-01"
            ),
            state="submitted",
            message="recorded",
        )


def _plan(action_id: str = ENABLE_DEFENDER_SERVERS_P1) -> dict:
    return {
        "plan_id": "RMP-CONFIG-1",
        "action_id": action_id,
        "action_version": "v1",
        "resource_key": VM_ID,
        "resource": {"id": VM_ID, "name": "vm-1"},
        "business_decision": {
            "disposition": "schedule",
            "business_impact": {"status": "known"},
            "review_requirements": [],
            "unknowns": [],
            "urgency_rationale": {
                "evidence_citations": ["assessment:assessment-1"]
            },
        },
        "evidence_citations": [
            {"source_type": "assessment", "source_id": "assessment-1"}
        ],
        "rollback_plan": {
            "rollback_actions": ["Restore the captured prior pricing configuration."]
        },
    }


def _approved_service(
    *, action_id: str = ENABLE_DEFENDER_SERVERS_P1
) -> tuple[RemediationExecutionService, _RecordingAdapter, RemediationExecutionStore]:
    plan = _plan(action_id)
    repository = PlanRepository()
    repository.replace_generation([plan])
    adapter = _RecordingAdapter()
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=None,
        defender_configuration_adapter=adapter,
        execution_store=RemediationExecutionStore(),
        now=lambda: NOW,
    )
    snapshot = service.build_execution_snapshot(
        plan, scope=Scope({"subscription": ["sub-1"]})
    )
    repository.decisions.append(
        plan=plan,
        decision="approved",
        approver="security@example.com",
        reason="Approved exact Defender configuration",
        scope={"subscription": ["sub-1"]},
        action_version=plan["action_version"],
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        execution_snapshot=snapshot,
        now=NOW,
    )
    return service, adapter, service._store


def test_servers_plan_snapshot_is_fixed_and_scope_bounded() -> None:
    adapter = _RecordingAdapter()

    snapshot = build_defender_configuration_snapshot(
        _plan(),
        adapter,
        scope=Scope({"subscription": ["sub-1"]}),
    )
    assert snapshot["request"] == {
        "method": "PUT",
        "path": (
            f"{VM_ID}/providers/Microsoft.Security/pricings/virtualMachines"
        ),
        "api_version": "2024-01-01",
        "body": {"properties": {"pricingTier": "Standard", "subPlan": "P1"}},
    }
    assert snapshot["prior_properties"] == {"pricingTier": "Free"}
    assert snapshot["patch_ids"] == []
    with pytest.raises(
        DefenderConfigurationUnavailable, match="outside the authorized"
    ):
        build_defender_configuration_snapshot(
            _plan(), adapter, scope=Scope({"subscription": ["other"]})
        )


@pytest.mark.parametrize(
    ("action_id", "family", "executable"),
    [
        ("controlled-patch-recovery", "patch", True),
        (ENABLE_DEFENDER_SERVERS_P1, "defender", True),
        ("policy-compliance-remediation", "policy", False),
        ("configuration-baseline-recovery", "configuration", False),
        ("arbitrary-arm-write", "unsupported", False),
    ],
)
def test_governed_action_families_fail_closed(
    action_id: str, family: str, executable: bool
) -> None:
    action = governed_action(action_id)
    assert action.family == family
    assert action.executable is executable
    assert (action_id in EXECUTABLE_ACTION_IDS) is executable
    if not executable:
        assert action.manual_review_reason


def test_storage_plan_requires_an_explicit_subscription_target() -> None:
    adapter = _RecordingAdapter()
    with pytest.raises(DefenderConfigurationUnavailable) as excinfo:
        build_defender_configuration_snapshot(
            _plan(ENABLE_DEFENDER_STORAGE_V2), adapter
        )
    assert excinfo.value.reason == "configuration_target_not_supported"

    plan = _plan(ENABLE_DEFENDER_STORAGE_V2)
    plan["resource_key"] = "/subscriptions/sub-1"
    plan["resource"] = {"id": "/subscriptions/sub-1", "name": "sub-1"}
    snapshot = build_defender_configuration_snapshot(plan, adapter)
    assert snapshot["request"]["path"].endswith(
        "/providers/Microsoft.Security/pricings/StorageAccounts"
    )
    assert snapshot["desired_properties"]["subPlan"] == "DefenderForStorageV2"


def test_azure_adapter_revalidates_state_and_submits_exact_put() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == "Bearer token"
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"ETag": '"v1"'},
                json={"properties": {"pricingTier": "Free"}},
            )
        return httpx.Response(200, json={"properties": {"pricingTier": "Standard"}})

    adapter = AzureArmDefenderConfigurationAdapter(
        _Credential(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    snapshot = build_defender_configuration_snapshot(_plan(), adapter)
    snapshot["snapshot_hash"] = execution_snapshot_hash(snapshot)

    result = adapter.submit(snapshot)

    assert [request.method for request in requests] == ["GET", "GET", "PUT"]
    assert requests[-1].headers["if-match"] == '"v1"'
    assert requests[-1].read() == (
        b'{"properties":{"pricingTier":"Standard","subPlan":"P1"}}'
    )
    assert result.state == "submitted"


def test_azure_adapter_refuses_tampered_or_stale_snapshot() -> None:
    adapter = _RecordingAdapter()
    snapshot = build_defender_configuration_snapshot(_plan(), adapter)
    snapshot["request"]["body"]["properties"]["pricingTier"] = "Free"
    with pytest.raises(DefenderConfigurationUnavailable) as excinfo:
        AzureArmDefenderConfigurationAdapter(
            _Credential(),
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        headers={"ETag": '"v1"'},
                        json={"properties": {"pricingTier": "Free"}},
                    )
                )
            ),
        ).submit(snapshot)
    assert excinfo.value.reason == "execution_snapshot_invalid"


def test_approved_configuration_executes_only_snapshotted_action() -> None:
    service, adapter, _ = _approved_service()

    result = service.execute(
        "RMP-CONFIG-1", requested_by="operator@example.com"
    )

    assert result["status"] == "running"
    assert len(adapter.submissions) == 1
    submitted = adapter.submissions[0]
    assert submitted["action_id"] == ENABLE_DEFENDER_SERVERS_P1
    assert submitted["request"]["body"]["properties"] == {
        "pricingTier": "Standard",
        "subPlan": "P1",
    }


def test_unsupported_configuration_recommendation_remains_manual_review() -> None:
    plan = _plan("defender-manual-review")
    repository = PlanRepository()
    repository.replace_generation([plan])
    service = RemediationExecutionService(
        plan_repository=repository,
        patching_service=None,
        defender_configuration_adapter=_RecordingAdapter(),
        now=lambda: NOW,
    )

    with pytest.raises(RemediationExecutionError) as excinfo:
        service.execute(plan["plan_id"], requested_by="operator@example.com")

    assert excinfo.value.reason == "action_not_executable"


def test_configuration_verifier_requires_desired_properties() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer token"
        return httpx.Response(
            200,
            json={
                "properties": {
                    "pricingTier": "Standard",
                    "subPlan": "P1",
                    "inherited": "False",
                }
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler)
    )
    verifier = ExecutionVerifier(credential=_Credential(), client=client)

    result = verifier.verify(
        {
            "provider_job_id": (
                "https://management.azure.com/subscriptions/sub-1/"
                "providers/Microsoft.Security/pricings/virtualMachines"
                "?api-version=2024-01-01"
            ),
            "execution_snapshot": {
                "snapshot_kind": "defender_configuration",
                "desired_properties": {
                    "pricingTier": "Standard",
                    "subPlan": "P1",
                },
            },
        }
    )

    assert result["outcome"] == "succeeded"
    assert result["verified_state"] == "configuration_matches_approved_snapshot"


def test_live_planner_maps_only_explicit_defender_configuration_titles() -> None:
    class _Service:
        freshness = "2026-09-03T00:00:00Z"

        def asset_exposures(self, scope=None):
            return []

        def defender_posture(self, scope=None):
            base = {
                "assessment_id": "assessment-servers",
                "asset_id": VM_ID,
                "asset_name": "vm-1",
                "resource_type": "Microsoft.Compute/virtualMachines",
                "inventory_kind": "Azure VM",
                "severity": "high",
                "subscription_id": "sub-1",
                "business_service": "Checkout",
                "application": "Payments",
                "last_assessed_at": "2026-09-03T00:00:00Z",
            }
            return [
                {
                    **base,
                    "recommendation": (
                        "Microsoft Defender for Servers should be enabled"
                    ),
                },
                {
                    **base,
                    "assessment_id": "assessment-custom",
                    "recommendation": "Configure Microsoft Defender custom controls",
                },
            ]

    plans = LiveRemediationPlanner(_Service()).generate_plans()["plans"]

    mapped = next(plan for plan in plans if plan["action_id"] == ENABLE_DEFENDER_SERVERS_P1)
    manual = next(plan for plan in plans if plan["action_id"] == "defender-manual-review")
    assert mapped["defender_mapping"]["status"] == "mapped"
    assert mapped["execution_authorized"] is False
    assert manual["defender_mapping"]["status"] == "manual_review"
    assert manual["business_decision"]["review_requirements"] == [
        "Platform security review"
    ]


def test_defender_correlation_identifies_code_authored_direct_action() -> None:
    from defender_correlation_scenario import defender_assessments, defender_resources

    from intelligence.remediation.defender_correlation import (
        DefenderRemediationCorrelator,
    )
    from intelligence.remediation.dependency_analyzer import DependencyAnalyzer
    from intelligence.vulnerability.service import VulnerabilityIntelligenceService

    assessments = defender_assessments()
    assessments[0]["recommendation"] = (
        "Microsoft Defender for Servers should be enabled"
    )
    service = VulnerabilityIntelligenceService.from_rows(
        defender_assessments=[assessments[0]],
        freshness="2026-09-03T00:00:00Z",
    )
    correlator = DefenderRemediationCorrelator(
        vulnerability_service=service,
        dependency_analyzer=DependencyAnalyzer(),
        resource_lookup=defender_resources(),
        action_catalog=[],
    )

    case = correlator.cases()[0]

    assert case["catalog_action_id"] == ENABLE_DEFENDER_SERVERS_P1
    assert case["catalog_match"] is True
    assert case["direct_execution_supported"] is True


def test_terraform_uses_separate_opt_in_and_narrow_defender_role() -> None:
    container_apps = Path("infra/terraform/container_apps.tf").read_text(
        encoding="utf-8"
    )
    main = Path("infra/terraform/main.tf").read_text(encoding="utf-8")
    variables = Path("infra/terraform/variables.tf").read_text(encoding="utf-8")

    assert 'name  = "AIOPS_DEFENDER_CONFIGURATION_EXECUTION"' in container_apps
    assert (
        'value = var.enable_defender_configuration_execution ? "azure" : "disabled"'
        in container_apps
    )
    variable = variables.split(
        'variable "enable_defender_configuration_execution"', maxsplit=1
    )[1].split("}", maxsplit=1)[0]
    assert "default     = false" in variable
    role = main.split(
        'resource "azurerm_role_definition" "apps_defender_configuration"',
        maxsplit=1,
    )[1].split(
        'resource "azurerm_role_assignment" "apps_defender_configuration"',
        maxsplit=1,
    )[0]
    assert '"Microsoft.Security/pricings/read"' in role
    assert '"Microsoft.Security/pricings/write"' in role
    assert "Microsoft.Resources/deployments/write" not in role
    assert 'role_definition_name = "Contributor"' not in role
