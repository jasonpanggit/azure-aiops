from __future__ import annotations

import pytest
from semantic_scenario import semantic_scenario

from agents.operations.operations_agent import (
    OperationsAgent,
    _validate_operations_result,
)
from semantic.semantic_engine import SemanticEngine

BANNED = {
    "tenant_id",
    "subscription_id",
    "resource_id",
    "ingestion_run_id",
    "source_run_id",
    "payload_json",
    "lineage_json",
    "semantic_metadata_json",
}


def test_every_conclusion_and_recommendation_is_explainable():
    result = OperationsAgent(
        SemanticEngine.from_rows(**semantic_scenario())
    ).analyze("Analyze VM", "vm-payments")

    for conclusion in result["conclusions"]:
        assert set(conclusion) >= {
            "evidence",
            "data_sources",
            "reasoning",
            "risk_factors",
        }
        assert conclusion["evidence"]
        assert conclusion["data_sources"]
        assert conclusion["reasoning"]
    for recommendation in result["recommendations"]:
        assert recommendation["evidence"]
        assert recommendation["rationale"]
        assert 0 <= recommendation["confidence"] <= 1


def test_operations_output_never_exposes_raw_internal_fields_or_actions():
    result = OperationsAgent(
        SemanticEngine.from_rows(**semantic_scenario())
    ).analyze(
        "Generate Incident Context",
        "vm-payments",
        subject_type="VirtualMachine",
    )

    def keys(value):
        if isinstance(value, dict):
            return set(value) | {
                nested for item in value.values() for nested in keys(item)
            }
        if isinstance(value, list):
            return {nested for item in value for nested in keys(item)}
        return set()

    assert not BANNED & keys(result)
    assert "execute" not in str(result).casefold()
    assert "action_result" not in result


def test_impact_output_does_not_reflect_raw_subject_identifier():
    scenario = semantic_scenario()
    raw_id = next(
        row["resource_id"]
        for row in scenario["entities"]
        if row["name"] == "vm-payments"
    )
    result = OperationsAgent(SemanticEngine.from_rows(**scenario)).analyze(
        "Show Impact Summary", raw_id, subject_type="VirtualMachine"
    )

    assert raw_id not in str(result)
    assert result["subject"]["name"] == "vm-payments"


def test_operations_response_validator_rejects_unsafe_or_unexplained_output():
    with pytest.raises(ValueError, match="unsafe fields"):
        _validate_operations_result(
            {
                "command": "Analyze VM",
                "subject": {"name": "vm", "entity_type": "VirtualMachine"},
                "conclusions": [],
                "recommendations": [],
                "read_only": True,
                "payload_json": "unsafe",
            }
        )

    with pytest.raises(ValueError, match="conclusion contract"):
        _validate_operations_result(
            {
                "command": "Analyze VM",
                "subject": {"name": "vm", "entity_type": "VirtualMachine"},
                "conclusions": [{"reasoning": "unsupported"}],
                "recommendations": [],
                "read_only": True,
            }
        )

    with pytest.raises(ValueError, match="unsafe fields"):
        _validate_operations_result(
            {
                "command": "Analyze VM",
                "subject": {"name": "vm", "entity_type": "VirtualMachine"},
                "conclusions": [
                    {
                        "domain": "Security Exposure",
                        "evidence": ({"payload_json": "unsafe"},),
                        "data_sources": ["Semantic Knowledge Layer"],
                        "reasoning": "unsafe",
                        "risk_factors": [],
                    }
                ],
                "recommendations": [],
                "read_only": True,
            }
        )


def test_context_analysis_discloses_truncated_semantic_evidence():
    scenario = semantic_scenario()
    payments_id = next(
        row["resource_id"]
        for row in scenario["entities"]
        if row["entity_type"] == "Application" and row["name"] == "Payments"
    )
    scenario["entities"].extend(
        {
            "resource_id": f"extra-resource-{index}",
            "entity_type": "Resource",
            "name": f"Extra Resource {index}",
            "lifecycle_status": "active",
        }
        for index in range(60)
    )
    scenario["relationships"].extend(
        {
            "resource_id": f"extra-host-{index}",
            "subject_id": payments_id,
            "subject_type": "Application",
            "predicate": "hosted_on",
            "object_id": f"extra-resource-{index}",
            "object_type": "Resource",
            "lifecycle_status": "active",
        }
        for index in range(60)
    )
    scenario["inventory"].extend(
        {
            "resource_id": f"extra-resource-{index}",
            "name": f"Extra Resource {index}",
            "status": "available",
        }
        for index in range(60)
    )

    result = OperationsAgent(SemanticEngine.from_rows(**scenario)).analyze(
        "Analyze Application", "Payments"
    )

    assert result["evidence_metadata"]["truncated"] is True
    assert result["evidence_metadata"]["sections"]["infrastructure"] == {
        "count": 61,
        "returned": 50,
        "truncated": True,
    }
