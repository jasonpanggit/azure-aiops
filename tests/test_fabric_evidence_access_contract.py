"""Persist the bounded collector access repair without granting writer authority."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "evidence_setup", ROOT / "infra/scripts/setup-platform.py"
)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)
PRINCIPAL = "11111111-1111-1111-1111-111111111111"
SUBSCRIPTION = "22222222-2222-2222-2222-222222222222"


def test_terraform_limits_collector_api_grant_to_validation_subscription():
    source = (ROOT / "infra/terraform/ontology_discovery_job.tf").read_text()
    grant = source.split("ontology_evidence_gateway_grants =", 1)[1].split(
        "ontology_discovery_image =", 1
    )[0]
    assert 'var.enable_fabric && var.ontology_discovery_environment == "validation"' in grant
    assert "azurerm_user_assigned_identity.azure_mcp.principal_id" in grant
    assert 'role  = "reader"' in grant
    assert "scope = { subscription = [var.subscription_id] }" in grant
    api = (ROOT / "infra/terraform/container_apps.tf").read_text()
    assert "local.ontology_evidence_gateway_grants))" in api


def test_setup_accepts_only_exact_collector_grant():
    setup.validate_evidence_api_grants({
        "ontology_evidence_role_contract": {"principal_object_id": PRINCIPAL},
        "ontology_evidence_api_gateway_grants": {
            PRINCIPAL: [{"role": "reader", "scope": {
                "subscription": [SUBSCRIPTION]
            }}]
        },
    }, SUBSCRIPTION)


@pytest.mark.parametrize("grants", [
    None, {},
    {PRINCIPAL: [{"role": "admin"}]},
    {PRINCIPAL: [{"role": "reader"}]},
    {PRINCIPAL: [{"role": "reader", "scope": {"subscription": [PRINCIPAL]}}]},
])
def test_setup_rejects_missing_or_broader_collector_grants(grants):
    with pytest.raises(setup.SetupError, match="exactly reader"):
        setup.validate_evidence_api_grants({
            "ontology_evidence_role_contract": {"principal_object_id": PRINCIPAL},
            "ontology_evidence_api_gateway_grants": grants,
        }, SUBSCRIPTION)


def test_setup_does_not_require_collector_grants_when_validation_disabled():
    setup.validate_evidence_api_grants({}, SUBSCRIPTION)
