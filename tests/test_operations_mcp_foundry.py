from __future__ import annotations

import json

import pytest

from operations.foundry_agent import (
    FoundryAgentError,
    SPECIALIST_CONTRACT_VERSION,
    parse_specialist_findings,
)


def _finding(**overrides):
    value = {
        "finding_id": "NET-NSG-001:nsg-1",
        "resource_ids": ["/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg"],
        "check_id": "NET-NSG-001",
        "policy_id": "NET-NSG-001",
        "evidence_refs": ["nsg-1"],
        "confidence": "high",
        "uncertainty": [],
        "freshness": "fresh",
        "actionable": True,
        "next_check": "Recheck nsg-1 through the allowlisted Network provider",
        "summary": "Inbound any-source rule",
    }
    value.update(overrides)
    return value


def test_network_contract_requires_citations_and_version():
    result = parse_specialist_findings(
        json.dumps({"findings": [_finding()]}),
        evidence_refs={"nsg-1"},
        resource_ids={_finding()["resource_ids"][0]},
    )
    assert result[0]["evidence_refs"] == ["nsg-1"]
    assert SPECIALIST_CONTRACT_VERSION == "network-finding.v1"


@pytest.mark.parametrize(
    "payload",
    [
        {"findings": [_finding(evidence_refs=["missing"])]},
        {"findings": [_finding(actionable="yes")]},
        {"findings": [_finding(summary="Please execute a production change")]},
        {"findings": [_finding(resource_ids=["/subscriptions/other/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet"])]},
    ],
)
def test_network_contract_rejects_uncited_or_mutation_capable_output(payload):
    with pytest.raises(FoundryAgentError):
        parse_specialist_findings(
            json.dumps(payload),
            evidence_refs={"nsg-1"},
            resource_ids={_finding()["resource_ids"][0]},
        )


def test_network_contract_rejects_prose_wrapper():
    with pytest.raises(FoundryAgentError):
        parse_specialist_findings(
            "Here is the answer: " + json.dumps({"findings": []}),
            evidence_refs={"nsg-1"},
        )
