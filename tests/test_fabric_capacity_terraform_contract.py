"""Least-privilege Terraform contract for the portal capacity health probe."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "infra" / "terraform"


def test_runtime_grounding_never_inherits_historical_item_identity() -> None:
    runtime = (ROOT / "fabric_runtime_config.tf").read_text(encoding="utf-8")
    assert 'key => value if key != "gold_grounding_agent"' in runtime
    assert 'var.fabric_gold_grounding_agent_id == "" ? {}' in runtime
    assert "item_id      = var.fabric_gold_grounding_agent_id" in runtime
    variables = (ROOT / "variables.tf").read_text(encoding="utf-8")
    option = variables.split('variable "fabric_gold_grounding_agent_id" {', 1)[1]
    option = option.split('\nvariable "', 1)[0]
    assert 'default     = ""' in option
    assert "validation {" in option


def test_deployer_is_always_in_fabric_capacity_administrators() -> None:
    fabric = (ROOT / "fabric.tf").read_text(encoding="utf-8")
    admins = fabric.split("fabric_admins =", 1)[1].split("\n}", 1)[0]
    assert "distinct(concat(" in admins
    assert "var.fabric_capacity_admins" in admins
    assert "local.deployer_object_id" in admins


def test_deployer_has_workspace_admin_separate_from_runtime_identity() -> None:
    fabric = (ROOT / "fabric.tf").read_text(encoding="utf-8")
    role = fabric.split(
        'resource "fabric_workspace_role_assignment" "terraform_deployer" {', 1
    )[1].split("\n}", 1)[0]
    assert "workspace_id = fabric_workspace.ops[0].id" in role
    assert 'role         = "Admin"' in role
    assert "id   = local.deployer_object_id" in role
    assert 'type = "ServicePrincipal"' in role


def test_capacity_reader_can_be_enabled_without_global_role_management() -> None:
    fabric = (ROOT / "fabric.tf").read_text(encoding="utf-8")
    role = fabric.split(
        'resource "azurerm_role_assignment" "fabric_capacity_reader_apps" {', 1
    )[1].split("\n}", 1)[0]
    assert (
        "count = var.enable_fabric && "
        "(var.enable_role_assignments || var.enable_fabric_capacity_health_reader) ? 1 : 0"
    ) in role
    assert "scope                            = azurerm_fabric_capacity.main[0].id" in role
    assert 'role_definition_name             = "Reader"' in role
    assert (
        "principal_id                     = azurerm_user_assigned_identity.apps.principal_id"
    ) in role


def test_capacity_reader_override_is_opt_in_and_has_no_other_consumers() -> None:
    variables = (ROOT / "variables.tf").read_text(encoding="utf-8")
    option = variables.split(
        'variable "enable_fabric_capacity_health_reader" {', 1
    )[1].split("\n}", 1)[0]
    assert re.search(r"type\s*=\s*bool", option)
    assert re.search(r"default\s*=\s*false", option)
    consumers = [
        source.name
        for source in ROOT.glob("*.tf")
        if "var.enable_fabric_capacity_health_reader" in source.read_text(encoding="utf-8")
    ]
    assert consumers == ["fabric.tf"]
