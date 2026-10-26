"""Source product declarations cannot establish runtime health or scope."""

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from fabric.medallion_health import dataset_contract, dataset_status
from fabric.schema_registry import (
    PRODUCT_CONTRACT_VERSION,
    PRODUCT_CONTRACTS,
    SCHEMA_VERSION,
    SCHEMAS,
    product_contract_for,
    schema_for,
)

EXPECTED_IDENTITIES = {
    "bronze_resources": "resource_id",
    "silver_vm_inventory": "resource_id",
    "gold_exposure_facts": "fact_id",
    "gold_exposure_dimensions": "dimension_key",
    "gold_exposure_facets": "facet_key",
    "gold_exposure_summaries": "summary_key",
    "gold_exposure_evidence": "evidence_id",
    "gold_exposure_current": "current_key",
    "gold_container_exposure_current": "container_exposure_id",
    "gold_container_exposure_coverage": "coverage_id",
}


@pytest.mark.parametrize("name,identity", EXPECTED_IDENTITIES.items())
def test_declared_product_resolves_existing_schema_and_identity(name, identity):
    result = product_contract_for(name)
    schema = schema_for(name)
    assert schema.equals(SCHEMAS[name], check_metadata=True)
    assert result["status"] == "declared"
    assert result["table_name"] == name
    assert result["version"] == PRODUCT_CONTRACT_VERSION == "1.0.0"
    assert result["schema_version"] == SCHEMA_VERSION == "2.7.0"
    assert result["identity_fields"] == [identity]
    for field in (*result["identity_fields"], result["generation"]["field"]):
        assert schema.field(field).nullable is False
    assert result["physical_inventory"] == result["consumer_readiness"] == "not_collected"
    assert result["operational_owner"] == "not_collected"
    assert result["retention_policy"] == "not_declared"
    assert result["lifecycle"] == "source_declared"
    assert result["scope_requirements"]["authorization"] == "not_granted_by_declaration"
    assert result["scope_requirements"]["connection_membership"] == "requires_producer_evidence"
    assert result["source_inputs_completeness"] == "partial_not_dependency_graph"
    assert result["freshness_policy_ref"]["table"].endswith(f".tables.{name}")
    assert result["grain"] and result["owner_role"] and result["producer_ref"]
    assert result["source_inputs"] and result["consumer"]


def test_catalog_is_bounded_and_declarations_are_immutable():
    assert set(PRODUCT_CONTRACTS) == set(EXPECTED_IDENTITIES)
    with pytest.raises(TypeError):
        PRODUCT_CONTRACTS["new"] = PRODUCT_CONTRACTS["bronze_resources"]
    with pytest.raises(FrozenInstanceError):
        PRODUCT_CONTRACTS["bronze_resources"].grain = "changed"


def test_serialization_is_deterministic_and_detached():
    first = product_contract_for("gold_exposure_facts")
    encoded = json.dumps(first, sort_keys=True)
    first["identity_fields"].append("invented")
    first["generation"]["field"] = "invented"
    first["scope_requirements"]["authorization"] = "granted"
    first["freshness_policy_ref"]["fallback"].clear()
    assert json.dumps(product_contract_for("gold_exposure_facts"), sort_keys=True) == encoded


@pytest.mark.parametrize("name", ["unknown", "gold_invented", "silver_server_inventory", ""])
def test_missing_declarations_do_not_invent_contracts(name):
    result = product_contract_for(name)
    assert result["status"] == "not_declared"
    assert "grain" not in result and "scope_requirements" not in result
    assert result["physical_inventory"] == "not_collected"


def test_current_and_generation_products_remain_distinct():
    inventory = product_contract_for("bronze_resources")
    current = product_contract_for("gold_exposure_current")
    analytics = product_contract_for("gold_exposure_facts")
    assert inventory["temporal_mode"] == current["temporal_mode"] == "current_snapshot"
    assert analytics["temporal_mode"] == "generation_snapshot"
    assert analytics["generation"] == {
        "field": "read_model_generation_id", "group": "exposure_gold_read_model",
    }
    assert current["generation"]["group"] != analytics["generation"]["group"]
    assert inventory["scope_requirements"]["semantics"] == "subscription_snapshot"
    assert analytics["scope_requirements"]["semantics"] == "row_scoped_generation"


def test_declaration_cannot_create_health_registration_or_diagnostics():
    now = datetime(2026, 10, 26, tzinfo=UTC)
    status = dataset_status("gold_exposure_facts", clock=lambda: now)
    contract = dataset_contract("gold_exposure_facts", source_status=(), clock=lambda: now)
    assert status["availability"] == "unavailable"
    assert status["freshness"] == "unknown"
    assert contract["product_contract"]["status"] == "declared"
    assert contract["source_diagnostics"] == []
    assert contract["producer_ownership"] == "not_collected"
    assert contract["deployed_schema_validation"] == "not_collected"
    assert contract["dataset_dependency_graph"] == "not_collected"
