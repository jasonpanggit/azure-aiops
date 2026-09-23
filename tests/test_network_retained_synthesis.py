from __future__ import annotations

import json

from operations.foundry_agent import AgentAnswer
from operations.orchestration_contract import EvidenceSnapshotV2, SnapshotCoverage
from operations.orchestration_service import OrchestrationService
from operations.tools import STATUS_OK


def test_network_page_retained_evidence_is_sent_to_executive_synthesis() -> None:
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
                "Plan a private endpoint for 'aiopsdemoacr' and disable its "
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
                        "next_check": "Review the cited retained Network row.",
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
        and "Plan a private endpoint" in finding["summary"]
        for finding in coordinator.context["findings"]
    )
    assert synthesis.status == "synthesized"
    assert synthesis.claims[0]["evidence_refs"] == ["retained:acr-gap"]
    assert "aiopsdemoacr" in synthesis.narration
    assert "Plan a private endpoint" in synthesis.narration
    assert synthesis.used_retained_evidence == retained
