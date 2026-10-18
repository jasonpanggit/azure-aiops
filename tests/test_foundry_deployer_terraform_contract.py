"""Protect existing Foundry role recipients when Terraform credentials change."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "infra" / "terraform"


def test_foundry_role_recipient_defaults_to_current_deployer() -> None:
    source = (ROOT / "foundry.tf").read_text(encoding="utf-8")
    assert "coalesce(var.foundry_deployer_object_id, local.deployer_object_id)" in source
    variables = (ROOT / "variables.tf").read_text(encoding="utf-8")
    option = variables.split('variable "foundry_deployer_object_id" {', 1)[1]
    option = option.split('\nvariable "', 1)[0]
    assert 'default     = ""' in option
    assert "validation {" in option


def test_foundry_deployment_roles_preserve_existing_recipient() -> None:
    source = (ROOT / "foundry.tf").read_text(encoding="utf-8")
    for name in (
        "deployer_search_index_data_contributor",
        "deployer_search_service_contributor",
        "deployer_cognitive_services_openai_user",
        "deployer_cognitive_services_user",
        "deployer_foundry_manager",
    ):
        block = source.split(f'resource "azurerm_role_assignment" "{name}" {{', 1)[1]
        block = block.split("\n}", 1)[0]
        assert "principal_id         = local.foundry_deployer_object_id" in block
        assert "prevent_destroy = true" in block
