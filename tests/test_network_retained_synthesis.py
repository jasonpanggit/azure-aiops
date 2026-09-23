from __future__ import annotations

import json

import pytest

from operations.foundry_agent import (
    AgentAnswer,
    FoundryResponseContractError,
    validate_executive_synthesis,
)
from operations.orchestration_contract import EvidenceSnapshotV2, SnapshotCoverage
from operations.orchestration_service import (
    OrchestrationService,
    _executive_synthesis_payload,
)
from operations.tools import STATUS_OK


@pytest.mark.parametrize("invalid_next_check", [False, True])
def test_network_page_retained_evidence_is_sent_to_executive_synthesis(
    invalid_next_check,
) -> None:
    snapshot = EvidenceSnapshotV2(
        page_kind="network",
        page_id="network-topology",
        coverage=SnapshotCoverage(visible_count=31, total_count=31, complete=True),
        evidence=[],
    )
    retained = [{
        "evidence_id": "retained:acr-gap",
        "source": "page_snapshot:network:network/gaps",
        "status": STATUS_OK,
        "resource_id": (
            "/subscriptions/sub-a/resourceGroups/rg/providers/"
            "Microsoft.ContainerRegistry/registries/aiopsdemoacr"
        ),
        "observation_status": "current",
        "claim_type": "network_gap",
        "severity": "high",
        "data": {
            "resource_name": "aiopsdemoacr",
            "source_key": "netgap-acr",
            "issue": (
                "'aiopsdemoacr' is reachable over its public endpoint because "
                "no private endpoint targets it."
            ),
            "recommendation": (
                "Create a private endpoint for 'aiopsdemoacr' and disable its "
                "public network access."
            ),
        },
    }]
    tool_results = [{
        "call_id": "network:topology",
        "specialist_id": "network",
        "tool": "network_topology",
        "arguments": {},
        "status": STATUS_OK,
        "data": {"summary": {"gap_count": 23, "rule_finding_count": 5}},
        "evidence": [{"source": "network"}],
    }]

    class Coordinator:
        context = None

        def answer(self, *, context, **_kwargs):
            self.context = context
            retained_finding = next(
                finding
                for finding in context["findings"]
                if finding["finding_id"].startswith("network-page:")
            )
            return AgentAnswer(
                text=json.dumps({
                    "findings": [{
                        "finding_id": "network-page-summary",
                        "evidence_refs": retained_finding["evidence_refs"],
                        "confidence": "high",
                        "uncertainty": [],
                        "freshness": "fresh",
                        "actionable": False,
                        "next_check": (
                            "Create a private endpoint now."
                            if invalid_next_check
                            else "Review the cited retained Network row."
                        ),
                        "summary": retained_finding["summary"],
                    }]
                }),
                agent_name="operations-copilot",
                agent_version="5",
            )

    coordinator = Coordinator()
    synthesis = OrchestrationService(
        executive_agent=coordinator,
        always_synthesize=True,
    )._synthesize(
        (
            "Provide an executive summary grounded only in this bounded "
            "Network topology snapshot. Name specific affected resources and "
            "recommendations."
        ),
        tool_results,
        retained_evidence=[],
        current_retained_evidence=retained,
        snapshot=snapshot,
    )

    assert coordinator.context is not None
    assert any(
        finding["finding_id"].startswith("network-page:")
        and finding["evidence_refs"] == ["retained:acr-gap"]
        and "aiopsdemoacr" in finding["summary"]
        and "Create a private endpoint" in finding["summary"]
        for finding in coordinator.context["findings"]
    )
    if invalid_next_check:
        assert synthesis.status == "degraded"
        assert synthesis.mode == "deterministic"
        assert synthesis.degraded_reason == "response_contract"
        assert synthesis.provider_error_reason == "response_contract"
        assert synthesis.provider_error_class == "contract_error"
        assert "failed response validation" in synthesis.warning
        assert synthesis.used_retained_evidence == retained
        assert synthesis.claims
        return
    assert synthesis.status == "synthesized"
    assert synthesis.claims[0]["evidence_refs"] == ["retained:acr-gap"]
    assert "aiopsdemoacr" in synthesis.narration
    assert "Create a private endpoint" in synthesis.narration
    assert synthesis.used_retained_evidence == retained
    assert _executive_synthesis_payload(synthesis)["used_retained_evidence"] == retained


@pytest.mark.parametrize("invalid", [
    {"next_check": "Create a private endpoint now."},
    {"next_check": "Execute az network private-endpoint create."},
    {"evidence_refs": ["retained:invented"]},
    {"confidence": "certain"},
    {"summary": ""},
])
def test_remediation_narration_keeps_citations_and_read_only_checks_strict(invalid):
    finding = {
        "finding_id": "registry-exposure",
        "summary": "Evidence recommends: create a private endpoint for demoacr.",
        "evidence_refs": ["retained:acr-gap"],
        "confidence": "high",
        "freshness": "fresh",
        "uncertainty": [],
        "actionable": False,
        "next_check": "Verify private endpoint coverage for demoacr.",
        **invalid,
    }
    with pytest.raises(FoundryResponseContractError):
        validate_executive_synthesis(
            json.dumps({"findings": [finding]}),
            evidence_refs={"retained:acr-gap"},
        )
