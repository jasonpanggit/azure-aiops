"""Regression coverage for topology-insights-empty-fallback.

Live production symptom: an authenticated /network investigate-context call
returned HTTP 200, status=partial, synthesis.mode=deterministic,
policy_status=fallback, fallback_reason=planner_unavailable, with
uncertainty noting that Foundry narration timed out. Despite the same
response carrying a fully successful `network_topology` tool finding (one
hub VNet, one isolated VNet, shared services, resources, relationships),
`synthesis.narration` and `synthesis.executive.claims` were both empty,
so the frontend rendered "Insights unavailable" even though rich,
citation-backed Network evidence existed.

Root cause: `deterministic_network_claims` only built a primary claim from a
successful `firewall_nsg_gaps` finding. If none existed -- exactly the case
when only `network_topology` succeeded -- the function returned `[]`
*before* running the generic direct-citation fallback loop that would
otherwise have projected the successful `network_topology` finding into a
citation-backed claim.
"""

from __future__ import annotations

from operations.orchestration_contract import EvidenceSnapshotV2, SnapshotCoverage
from operations.orchestration_service import (
    OrchestrationService,
    deterministic_network_claims,
)
from operations.tools import STATUS_OK

_HUB_ID = (
    "/subscriptions/sub-a/resourceGroups/rg/providers/"
    "Microsoft.Network/virtualNetworks/hub-vnet"
)
_ISOLATED_ID = (
    "/subscriptions/sub-a/resourceGroups/rg/providers/"
    "Microsoft.Network/virtualNetworks/isolated-vnet"
)


def _network_topology_tool_result() -> dict:
    """Mirror the live production shape: a fully successful topology finding."""

    return {
        "call_id": "topology:0",
        "specialist_id": "network",
        "tool": "network_topology",
        "status": STATUS_OK,
        "data": {
            "summary": {
                "hub_count": 1,
                "spoke_count": 0,
                "isolated_vnet_count": 1,
                "shared_service_count": 2,
            },
            "topology": {
                "hubs": [{
                    "id": _HUB_ID,
                    "name": "hub-vnet",
                    "entity_type": "Microsoft.Network/virtualNetworks",
                    "role": "hub",
                    "peer_count": 1,
                }],
                "isolated": [{
                    "id": _ISOLATED_ID,
                    "name": "isolated-vnet",
                    "entity_type": "Microsoft.Network/virtualNetworks",
                    "role": "isolated",
                    "peer_count": 0,
                }],
            },
        },
        "evidence": [
            {"evidence_id": "tool:topology:0:0"},
            {"evidence_id": "tool:topology:0:1"},
        ],
    }


def _network_snapshot(*, complete: bool = True) -> EvidenceSnapshotV2:
    return EvidenceSnapshotV2(
        page_kind="network",
        page_id="network-topology",
        coverage=SnapshotCoverage(
            visible_count=2,
            total_count=2,
            complete=complete,
        ),
    )


def test_deterministic_network_claims_covers_topology_finding_without_firewall_gaps():
    """The exact planner_unavailable/Foundry-timeout live shape must not be dropped."""

    claims = deterministic_network_claims(
        snapshot=_network_snapshot(),
        tool_results=[_network_topology_tool_result()],
    )

    assert claims, (
        "network_topology is the only successful finding (no firewall_nsg_gaps "
        "claim exists), so the fallback direct-citation loop must still run "
        "and produce a citation-backed claim instead of returning empty."
    )
    assert all(claim["evidence_refs"] for claim in claims), (
        "every deterministic claim must cite real evidence, never fabricate"
    )
    summary = claims[0]["summary"]
    assert "hub_count=1" in summary
    assert "isolated_vnet_count=1" in summary


def test_deterministic_network_claims_empty_when_no_cited_findings_at_all():
    """Boundary: genuinely empty evidence still yields no claims (no fabrication)."""

    claims = deterministic_network_claims(
        snapshot=_network_snapshot(),
        tool_results=[{
            "call_id": "topology:0",
            "specialist_id": "network",
            "tool": "network_topology",
            "status": STATUS_OK,
            "data": {"summary": {}, "topology": {}},
            "evidence": [],
        }],
    )

    assert claims == []


def test_deterministic_network_claims_still_prefers_firewall_claim_first():
    """Boundary: when firewall_nsg_gaps evidence exists it remains the lead claim,
    and a coexisting network_topology finding is still appended (not dropped)."""

    firewall_result = {
        "call_id": "firewall:0",
        "specialist_id": "network",
        "tool": "firewall_nsg_gaps",
        "status": STATUS_OK,
        "data": {
            "gaps": [{
                "gap_id": "gap-1",
                "severity": "critical",
                "title": "Spoke bypasses hub firewall",
            }],
            "rule_findings": [],
        },
        "evidence": [{"evidence_id": "tool:firewall:0:0"}],
    }
    topology_result = _network_topology_tool_result()

    claims = deterministic_network_claims(
        snapshot=_network_snapshot(),
        tool_results=[firewall_result, topology_result],
    )

    assert len(claims) == 2
    assert "Spoke bypasses hub firewall" in claims[0]["summary"]
    assert "hub_count=1" in claims[1]["summary"]


def test_synthesis_narration_and_claims_nonempty_on_foundry_timeout_fallback():
    """End-to-end reproduction of the exact live symptom via _synthesize().

    planner_unavailable / Foundry narration timeout (executive_agent is None,
    narrator_state="timeout") plus a successful network_topology finding must
    produce non-empty, citation-backed deterministic claims -- not the empty
    synthesis.narration / synthesis.executive.claims seen in production.
    """

    service = OrchestrationService(executive_agent=None)
    tool_results = [_network_topology_tool_result()]

    synthesis = service._synthesize(
        "Show me the network topology",
        tool_results,
        retained_evidence=[],
        current_retained_evidence=[],
        snapshot=_network_snapshot(),
        narrator_state="timeout",
    )

    assert synthesis.status == "degraded"
    assert synthesis.claims, (
        "successful network_topology evidence must still yield deterministic "
        "claims when Foundry narration times out"
    )
    assert all(claim.get("evidence_refs") for claim in synthesis.claims)
    assert "Foundry narration timed out" in synthesis.warning
