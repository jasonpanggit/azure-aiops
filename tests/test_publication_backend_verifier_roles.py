"""Unassigned verifier roles cannot enable storage or publication authority."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "infra/publication-backend"
VERIFIER = BACKEND / "verifier_roles.tf"


def test_verifier_roles_only_declare_one_read_per_resource_scope() -> None:
    source = VERIFIER.read_text()
    actions = re.findall(r'action\s*=\s*"([^"]+)"', source)
    assert actions == [
        "Microsoft.Storage/storageAccounts/read",
        "Microsoft.Storage/storageAccounts/blobServices/read",
        "Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies/read",
    ]
    assert 'azurerm_storage_account.artifacts["candidate"].id, null)' in source
    assert '/blobServices/default", null)' in source
    assert 'azurerm_storage_container.artifacts["candidate"].id, null)' in source
    assert "for pair in setproduct(keys(local.candidates)" in source
    assert "for_each          = local.verifier_candidates" in source
    assert re.findall(r'resource "([^"]+)"', source) == ["azurerm_role_definition"]


def test_verifier_cannot_create_assignments_or_data_plane_grants() -> None:
    source = VERIFIER.read_text()
    assert not re.search(r'\b(data|module|provisioner)\s+"', source)
    assert not re.search(r'"[^"\n]*(?:\*|Contributor|listKeys|generateUserDelegationKey)[^"\n]*"', source)
    for field in ("data_actions", "not_data_actions", "not_actions"):
        assert re.search(rf"\b{field}\s*=\s*\[\]", source)
    all_sources = "\n".join(p.read_text() for p in BACKEND.glob("*.tf"))
    assert re.findall(
        r'resource "azurerm_role_assignment" "([^"]+)"', all_sources
    ) == ["registry_pull"]
    assert "role_definition_name = \"AcrPull\"" in all_sources
    assert 'resource "azurerm_role_assignment"' not in source


def test_verifier_output_is_proposal_only_and_disabled_is_null() -> None:
    source = VERIFIER.read_text()
    for field in ("assigned", "execution_enabled", "qualified"):
        assert re.search(rf"\b{field}\s*=\s*false", source)
        assert not re.search(rf"\b{field}\s*=\s*true", source)
    assert 'output "publication_backend_verifier_roles_v1"' in source
    assert "var.enable && var.settings != null ?" in source
    assert "} : null" in source
    assert "role.role_definition_resource_id" in source
    assert 'azurerm_user_assigned_identity.broker["candidate"].principal_id' in source
    assert 'variable "' not in source
    assert "locked" not in source
    assert "sql" not in source.lower().split('description       = "', 1)[0]


def test_old_candidate_and_output_are_not_repurposed_as_verifier_grants() -> None:
    main = (BACKEND / "main.tf").read_text()
    role = main.split('resource "azurerm_role_definition"', 1)[1].split(
        'resource "azurerm_role_assignment"', 1
    )[0]
    assert '"Microsoft.Storage/storageAccounts/read"' not in role
    assert '"Microsoft.Storage/storageAccounts/blobServices/read"' not in role
    assert "artifact_verifier_candidate" not in main
    assert "artifact_verifier_candidate" not in (BACKEND / "outputs.tf").read_text()
