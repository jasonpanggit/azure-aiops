from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_TF = ROOT / "infra" / "terraform" / "ontology_discovery_identity.tf"
JOB_TF = ROOT / "infra" / "terraform" / "ontology_discovery_job.tf"
FOUNDRY_TF = ROOT / "infra" / "terraform" / "foundry.tf"
CONTAINER_APPS_TF = ROOT / "infra" / "terraform" / "container_apps.tf"


def _resource(text: str, kind: str, name: str) -> str:
    marker = f'resource "{kind}" "{name}"'
    start = text.index(marker)
    next_resource = text.find('\nresource "', start + len(marker))
    return text[start:] if next_resource == -1 else text[start:next_resource]


def _quoted_items(block: str) -> list[str]:
    return [
        ast.literal_eval(line.strip().rstrip(","))
        for line in block.splitlines()
        if line.strip().startswith('"')
    ]


def test_publisher_has_a_distinct_identity_and_narrow_custom_role() -> None:
    terraform = IDENTITY_TF.read_text(encoding="utf-8")
    role = _resource(terraform, "azurerm_role_definition", "ontology_publisher")
    assignment = _resource(
        terraform,
        "azurerm_role_assignment",
        "ontology_publisher",
    )
    actions = terraform.split(
        "ontology_publisher_data_actions = [", maxsplit=1
    )[1].split("]", maxsplit=1)[0]

    assert 'resource "azurerm_user_assigned_identity" "ontology_publisher"' in terraform
    assert _quoted_items(actions) == [
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action",
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
        "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
    ]
    assert "data_actions     = local.ontology_publisher_data_actions" in role
    assert "actions          = []" in role
    assert "Contributor" not in role
    assert "Owner" not in role
    assert "list" not in role.casefold()
    assert (
        "principal_id                     = "
        "azurerm_user_assigned_identity.ontology_publisher.principal_id"
        in assignment
    )


def test_api_coordinator_and_curator_do_not_receive_publisher_role_or_credential() -> None:
    identity = IDENTITY_TF.read_text(encoding="utf-8")
    job = JOB_TF.read_text(encoding="utf-8")
    foundry = FOUNDRY_TF.read_text(encoding="utf-8")
    api = _resource(
        CONTAINER_APPS_TF.read_text(encoding="utf-8"),
        "azurerm_container_app",
        "api",
    )
    assignment = _resource(
        identity,
        "azurerm_role_assignment",
        "ontology_publisher",
    )

    assert "ontology_coordinator" not in assignment
    assert "azurerm_user_assigned_identity.apps" not in assignment
    assert "azurerm_cognitive_account_project.ops" not in assignment
    assert "ONTOLOGY_PUBLISHER" not in job
    assert "ontology_publisher.client_id" not in job
    assert "ONTOLOGY_PUBLISHER" not in api
    assert "ontology_publisher.client_id" not in api
    curator = _resource(
        foundry,
        "terraform_data",
        "foundry_ontology_curator_agent",
    )
    assert "ontology_publisher" not in curator
    assert "AZURE_CLIENT_SECRET" in curator  # deployer-only script credential
    assert "ONTOLOGY_PUBLISHER" not in curator


def test_publisher_has_no_model_or_read_generalization_grant() -> None:
    identity = IDENTITY_TF.read_text(encoding="utf-8")
    role = _resource(identity, "azurerm_role_definition", "ontology_publisher")
    assignment = _resource(
        identity,
        "azurerm_role_assignment",
        "ontology_publisher",
    )
    effective_grant = role + assignment

    assert "Cognitive Services" not in effective_grant
    assert "Foundry" not in effective_grant
    assert "OpenAI" not in effective_grant
    assert "Reader" not in assignment
    assert "Contributor" not in assignment
    assert "list" not in effective_grant.casefold()
