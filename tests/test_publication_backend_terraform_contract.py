"""Source-only, default-disabled publication backend infrastructure boundaries."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "infra" / "publication-backend"


def test_backend_is_separate_and_has_no_production_state_wiring() -> None:
    sources = "\n".join(path.read_text() for path in BACKEND.glob("*.tf"))
    assert not re.search(r'\b(data|module|provisioner)\s+"', sources)
    assert "terraform_remote_state" not in sources
    assert not re.search(r'\bbackend\s+"', sources)
    for path in (ROOT / "infra" / "terraform").glob("*.tf"):
        assert "publication-backend" not in path.read_text()


def test_all_resources_use_default_disabled_candidate_keys() -> None:
    source = (BACKEND / "main.tf").read_text()
    resources = re.findall(
        r'resource "[^"]+" "[^"]+" \{(.*?)(?=\nresource |\Z)', source, re.DOTALL
    )
    assert len(resources) == 17
    for resource in resources:
        assert re.search(
            r"for_each\s*=\s*local\.(candidates|private_services)\b", resource
        )
    assert "var.enable && var.settings != null" in source
    variables = (BACKEND / "variables.tf").read_text()
    enable = variables.split('variable "enable" {', 1)[1].split('\nvariable "', 1)[0]
    assert re.search(r"default\s*=\s*false", enable)


def test_only_registry_pull_is_assigned_and_no_sql_grant_is_invented() -> None:
    source = (BACKEND / "main.tf").read_text()
    assignments = re.findall(r'resource "azurerm_role_assignment" "([^"]+)"', source)
    assert assignments == ["registry_pull"]
    assert 'role_definition_name = "AcrPull"' in source
    assert "generateUserDelegationKey" not in source
    assert "listKeys" not in source
    assert "administrator_login" not in source
    assert "client_secret" not in source
    role = source.split('resource "azurerm_role_definition"', 1)[1].split(
        'resource "azurerm_role_assignment"', 1
    )[0]
    assert "blobs/delete" not in role
    assert "*" not in role
    assert "immutabilityPolicies/read" in role
    assert "immutabilityPolicies/write" not in role
    assert "role_definition_resource_id" not in source


def test_lock_and_execution_have_no_enablement_switch() -> None:
    source = (BACKEND / "main.tf").read_text()
    assert re.search(r"locked\s*=\s*false", source)
    assert "ignore_changes" not in source
    assert "exit 78" in source
    assert "schedule_trigger_config" not in source
    assert "event_trigger_config" not in source
    variables = (BACKEND / "variables.tf").read_text()
    assert 'var.settings.policy_state == "Unlocked"' in variables
    assert 'variable "execution_enabled"' not in variables
    outputs = (BACKEND / "outputs.tf").read_text()
    assert re.search(r"execution_enabled\s*=\s*false", outputs)
    assert re.search(r"qualified\s*=\s*false", outputs)
    assert re.search(r"endpoint\s*=\s*null", outputs)


def test_provider_matches_repository_lock_and_preserves_checksums() -> None:
    pattern = r'provider "registry.terraform.io/hashicorp/azurerm" \{(.*?)\n\}'
    original = re.search(
        pattern,
        (ROOT / "infra" / "terraform" / ".terraform.lock.hcl").read_text(),
        re.DOTALL,
    ).group(1)
    isolated = re.search(
        pattern, (BACKEND / ".terraform.lock.hcl").read_text(), re.DOTALL
    ).group(1)
    assert re.search(r'version\s*=\s*"5.2.0"', original)
    assert re.findall(r'"(?:h1|zh):[^"]+"', original) == re.findall(
        r'"(?:h1|zh):[^"]+"', isolated
    )
    assert 'version = "= 5.2.0"' in (BACKEND / "providers.tf").read_text()
