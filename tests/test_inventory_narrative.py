from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.scope import Scope
from intelligence.inventory.narrative import build_inventory_narrative
from intelligence.inventory.service import InventoryService
from intelligence.inventory.software_normalization import normalize_configuration_data

FIXTURES = Path(__file__).parent / "fixtures"


def _facts(result: dict) -> dict[str, str]:
    return {item["label"]: item["value"] for item in result["data"]["fact_items"]}


@pytest.mark.parametrize("state", ["unavailable", "partial", "degraded", "stale"])
def test_unavailable_software_never_becomes_successful_zero(state: str) -> None:
    payload = json.loads((FIXTURES / "mock_inventory_arg.json").read_text())
    payload["software_observations"] = []
    payload["software_source_status"] = {"logs": {"state": state}}
    result = build_inventory_narrative(InventoryService(payload), Scope.unrestricted())

    assert _facts(result)["Software observations"] == "Unknown"
    assert _facts(result)["Software groups"] == "Unknown"
    assert "Complete software counts and absence are unknown" in result["data"]["fact_summary"]
    assert "0 installed-software" not in result["data"]["fact_summary"]
    assert "Top software: none" not in result["data"]["fact_summary"]
    assert any(f"source is {state}" in warning for warning in result["warnings"])


def test_ready_empty_software_remains_a_genuine_zero() -> None:
    result = build_inventory_narrative(
        InventoryService({
            "observations": [],
            "source_status": {"azure_vm": {"state": "ready"}, "arc": {"state": "ready"}},
            "software_observations": [],
            "software_source_status": {"logs": {"state": "ready"}},
        }),
        Scope.unrestricted(),
    )
    assert _facts(result)["Software observations"] == "0"
    assert _facts(result)["Software groups"] == "0"
    assert "0 installed-software observations across 0 software groups" in result["data"]["fact_summary"]


def test_retained_partial_software_counts_are_not_discarded_or_promoted_to_totals() -> None:
    payload = json.loads((FIXTURES / "mock_inventory_arg.json").read_text())
    software = json.loads((FIXTURES / "mock_configurationdata.json").read_text())
    payload["software_observations"] = [
        row.to_dict()
        for row in normalize_configuration_data(software, InventoryService(payload).snapshot.observations)
    ]
    payload["software_source_status"] = {"logs": {"state": "partial"}}
    service = InventoryService(payload)
    count = service.narrative_aggregates(Scope.unrestricted())["software_install_count"]
    assert count > 0
    result = build_inventory_narrative(service, Scope.unrestricted())
    assert _facts(result)["Software observations"] == f"{count} observed (incomplete)"
    assert "Top observed software:" in result["data"]["fact_summary"]
    assert "Complete software counts and absence are unknown" in result["data"]["fact_summary"]


def test_unavailable_os_does_not_claim_no_machines_or_no_eol_risk() -> None:
    result = build_inventory_narrative(
        InventoryService({
            "observations": [],
            "source_status": {"azure_vm": {"state": "unavailable"}, "arc": {"state": "ready"}},
            "software_source_status": {"logs": {"state": "ready"}},
        }),
        Scope.unrestricted(),
    )
    assert _facts(result)["Machines"] == "Unknown"
    assert _facts(result)["OS groups"] == "Unknown"
    assert _facts(result)["EOL risk"] == "Unknown"
    assert "Complete machine and OS-group counts are unknown" in result["data"]["fact_summary"]
    assert "0 machines" not in result["data"]["fact_summary"]
    assert "Top OS groups: none" not in result["data"]["fact_summary"]


def test_partial_os_preserves_observed_rows_without_claiming_complete_risk() -> None:
    payload = json.loads((FIXTURES / "mock_inventory_arg.json").read_text())
    payload["source_status"] = {
        "azure_vm": {"state": "ready"},
        "arc": {"state": "partial"},
    }
    result = build_inventory_narrative(InventoryService(payload), Scope.unrestricted())
    assert _facts(result)["Machines"] == "5 observed (incomplete)"
    assert "overall risk unknown" in _facts(result)["EOL risk"]
    assert "Observed rows only:" in result["data"]["fact_summary"]
    assert _facts(result)["Software observations"] == "0"


def test_software_group_total_is_not_truncated_with_top_group_payload() -> None:
    payload = json.loads((FIXTURES / "mock_inventory_arg.json").read_text())
    software = json.loads((FIXTURES / "mock_configurationdata.json").read_text())
    row = normalize_configuration_data(software, InventoryService(payload).snapshot.observations)[0].to_dict()
    payload["software_observations"] = [
        {**row, "software_name": f"Application {index}"} for index in range(30)
    ]
    payload["software_source_status"] = {"logs": {"state": "ready"}}
    service = InventoryService(payload)
    aggregates = service.narrative_aggregates(Scope.unrestricted())
    assert len(aggregates["software_groups"]) == 12
    result = build_inventory_narrative(service, Scope.unrestricted())
    assert _facts(result)["Software groups"] == "30"
    assert "30 installed-software observations across 30 software groups" in result["data"]["fact_summary"]


def test_narrator_receives_unknown_software_not_false_absence() -> None:
    captured: dict = {}

    class Narrator:
        def answer(self, *, question: str, context: dict):
            from operations.foundry_agent import AgentAnswer

            captured.update(context)
            assert "never proves zero" in question
            return AgentAnswer(text="Software coverage is unknown.", agent_name="test")

    result = build_inventory_narrative(
        InventoryService({
            "source_status": {"azure_vm": {"state": "ready"}},
            "software_source_status": {"logs": {"state": "unavailable"}},
        }),
        Scope.unrestricted(),
        Narrator(),
    )
    assert _facts({"data": captured["facts"]})["Software observations"] == "Unknown"
    assert "Top software: none" not in captured["facts"]["fact_summary"]
    assert result["data"]["narrated_summary"] == "Software coverage is unknown."
