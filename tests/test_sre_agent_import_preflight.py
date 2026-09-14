"""Offline tests for the Azure SRE Agent import preflight."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_FIXTURE = REPO_ROOT / "tests/fixtures/sre_agent_resource.sanitized.json"
RBAC_FIXTURE = REPO_ROOT / "tests/fixtures/sre_agent_rbac.sanitized.json"


def _load_module():
    path = REPO_ROOT / "scripts/preflight_sre_agent_import.py"
    spec = importlib.util.spec_from_file_location("preflight_sre_agent_import", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_resource_preflight_emits_exact_non_secret_import_contract() -> None:
    module = _load_module()

    result = module.validate_resource_evidence(_fixture(RESOURCE_FIXTURE))

    assert result["status"] == "resource-ready"
    assert result["importAddress"] == "azapi_resource.sre_agent[0]"
    assert result["tfvars"] == {
        "enable_sre_agent_management": True,
        "sre_agent_managed_resources": list(module.EXPECTED_MANAGED_RESOURCES),
    }
    assert result["importCommand"] == (
        "terraform -chdir=infra/terraform import -input=false "
        "-var-file=sre-agent.import.tfvars.json "
        "'azapi_resource.sre_agent[0]' "
        "'/subscriptions/a87a8e64-a52a-4aa8-a760-5e8919d23cd1/"
        "resourceGroups/rg-sredemo-dev/providers/Microsoft.App/agents/"
        "sre-agent-sredemo'"
    )
    serialized = json.dumps(result)
    assert "connectionString" not in serialized
    assert "connectionKey" not in serialized
    assert result["liveMutationPerformed"] is False


def test_preflight_has_no_azure_terraform_or_network_execution_path() -> None:
    source = (
        REPO_ROOT / "scripts/preflight_sre_agent_import.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "import subprocess",
        "from subprocess",
        "os.system",
        "urlopen",
        "requests.",
        "httpx.",
    ):
        assert forbidden not in source


def test_resource_preflight_rejects_read_only_action_mode() -> None:
    module = _load_module()
    payload = _fixture(RESOURCE_FIXTURE)
    payload["resource"]["properties"]["actionConfiguration"]["mode"] = "ReadOnly"

    with pytest.raises(module.PreflightError, match="read-only SRE Agent"):
        module.validate_resource_evidence(payload)


def test_resource_preflight_rejects_read_only_service_properties() -> None:
    module = _load_module()
    payload = _fixture(RESOURCE_FIXTURE)
    payload["resource"]["properties"]["agentEndpoint"] = "redacted.example"

    with pytest.raises(module.PreflightError, match="read-only properties: agentEndpoint"):
        module.validate_resource_evidence(payload)


def test_resource_preflight_rejects_top_level_output_fields() -> None:
    module = _load_module()
    payload = _fixture(RESOURCE_FIXTURE)
    payload["resource"]["systemData"] = {"createdAt": "2026-09-14T00:00:00Z"}

    with pytest.raises(module.PreflightError, match="output-only fields: systemData"):
        module.validate_resource_evidence(payload)


def test_resource_preflight_rejects_unknown_wrapper_fields() -> None:
    module = _load_module()
    payload = _fixture(RESOURCE_FIXTURE)
    payload["accessToken"] = "not-sanitized"

    with pytest.raises(module.PreflightError, match="resource evidence contains"):
        module.validate_resource_evidence(payload)


def test_resource_preflight_rejects_retained_empty_secret_fields() -> None:
    module = _load_module()
    payload = _fixture(RESOURCE_FIXTURE)
    payload["resource"]["properties"]["incidentManagementConfiguration"][
        "connectionKey"
    ] = ""

    with pytest.raises(module.PreflightError, match="omit secret field connectionKey"):
        module.validate_resource_evidence(payload)


def test_resource_preflight_rejects_cross_subscription_managed_resource() -> None:
    module = _load_module()
    payload = _fixture(RESOURCE_FIXTURE)
    payload["resource"]["properties"]["knowledgeGraphConfiguration"][
        "managedResources"
    ][0] = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/x"

    with pytest.raises(module.PreflightError, match="exact observed set"):
        module.validate_resource_evidence(payload)


def test_resource_cli_writes_only_gitignored_non_secret_tfvars(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module()
    output = tmp_path / "sre-agent.import.tfvars.json"
    output.write_text("{}\n", encoding="utf-8")
    output.chmod(0o644)

    code = module.main(
        [
            "resource",
            "--resource-json",
            str(RESOURCE_FIXTURE),
            "--tfvars-output",
            str(output),
        ]
    )

    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "enable_sre_agent_management": True,
        "sre_agent_managed_resources": list(module.EXPECTED_MANAGED_RESOURCES),
    }
    assert output.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.glob(f".{output.name}.*")) == []
    cli_result = json.loads(capsys.readouterr().out)
    assert cli_result["writtenTfvarsPath"] == str(output)
    assert f"-var-file={output.resolve()}" in cli_result["importCommand"]


def test_rbac_preflight_accepts_current_least_privilege_split() -> None:
    module = _load_module()

    result = module.validate_rbac_evidence(_fixture(RBAC_FIXTURE))

    assert result["status"] == "rbac-ready"
    assert result["systemAssignedAssignmentCount"] == 0
    assert result["userAssignedAssignmentCount"] == 8
    assert result["outsideSubscriptionAssignments"] == 0
    assert result["liveMutationPerformed"] is False


def test_rbac_preflight_rejects_assignment_outside_selected_subscription() -> None:
    module = _load_module()
    payload = _fixture(RBAC_FIXTURE)
    assignment = copy.deepcopy(
        payload["principals"][1]["queries"][0]["assignments"][0]
    )
    assignment["scope"] = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/x"
    )
    payload["principals"][1]["queries"][0]["assignments"].append(assignment)

    with pytest.raises(module.PreflightError, match="outside selected subscription"):
        module.validate_rbac_evidence(payload)


def test_rbac_preflight_rejects_incomplete_visible_subscription_coverage() -> None:
    module = _load_module()
    payload = _fixture(RBAC_FIXTURE)
    payload["visibleTenantSubscriptionIds"].append(
        "00000000-0000-0000-0000-000000000000"
    )

    with pytest.raises(module.PreflightError, match="must exactly match visible"):
        module.validate_rbac_evidence(payload)


def test_rbac_preflight_rejects_missing_per_principal_inherited_query() -> None:
    module = _load_module()
    payload = _fixture(RBAC_FIXTURE)
    payload["principals"][0]["queries"] = []

    with pytest.raises(module.PreflightError, match="do not cover visible"):
        module.validate_rbac_evidence(payload)


def test_rbac_preflight_rejects_query_without_inherited_assignments() -> None:
    module = _load_module()
    payload = _fixture(RBAC_FIXTURE)
    payload["principals"][1]["queries"][0]["includeInherited"] = False

    with pytest.raises(module.PreflightError, match="must include inherited"):
        module.validate_rbac_evidence(payload)


def test_rbac_preflight_rejects_misattributed_query_assignments() -> None:
    module = _load_module()
    payload = _fixture(RBAC_FIXTURE)
    other_subscription = "00000000-0000-0000-0000-000000000000"
    payload["visibleTenantSubscriptionIds"].append(other_subscription)
    payload["queriedSubscriptionIds"].append(other_subscription)
    payload["principals"][0]["queries"].append(
        {
            "assignments": [],
            "includeInherited": True,
            "subscriptionId": other_subscription,
        }
    )
    payload["principals"][1]["queries"].append(
        {
            "assignments": [
                copy.deepcopy(
                    payload["principals"][1]["queries"][0]["assignments"][0]
                )
            ],
            "includeInherited": True,
            "subscriptionId": other_subscription,
        }
    )

    with pytest.raises(module.PreflightError, match="does not match its query"):
        module.validate_rbac_evidence(payload)


def test_rbac_preflight_rejects_missing_required_user_access() -> None:
    module = _load_module()
    payload = _fixture(RBAC_FIXTURE)
    payload["principals"][1]["queries"][0]["assignments"] = []

    with pytest.raises(module.PreflightError, match="no selected-subscription access"):
        module.validate_rbac_evidence(payload)
