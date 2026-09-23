"""Page rows must be asserted as claims or synthesis loses every detail."""

from __future__ import annotations

from api.routers.copilot import MAX_CLAIM_EVIDENCE_REFS, _page_material_claims
from operations.orchestration_contract import (
    EvidenceSnapshotV2,
    SnapshotCoverage,
    SnapshotEvidence,
)
from operations.page_context import select_browser_evidence_for_retention


def _rid(name: str) -> str:
    return (
        "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg"
        f"/providers/Microsoft.Network/virtualNetworks/{name}"
    )


def _row(evidence_id: str, *, resource_id: str = "", status: str = "ok") -> SnapshotEvidence:
    return SnapshotEvidence(
        evidence_id=evidence_id,
        source="network/gaps",
        status=status,
        observed_at="2026-01-01T00:00:00Z",
        resource_id=resource_id,
        data={"issue": "public endpoint", "recommendation": "add private endpoint"},
    )


def test_per_resource_rows_survive_retention_under_partial_coverage() -> None:
    """The detail rows that name a resource must reach synthesis."""

    evidence = [
        _row("gap-1", resource_id=_rid("acr")),
        _row("gap-2", resource_id=_rid("kv")),
    ]
    snapshot = EvidenceSnapshotV2(
        page_kind="network",
        page_id="network",
        coverage=SnapshotCoverage(visible_count=2, total_count=2, complete=False),
        evidence=evidence,
        material_claims=_page_material_claims(evidence),
    )

    retained = select_browser_evidence_for_retention(snapshot)

    assert {row.evidence_id for row in retained.evidence} == {"gap-1", "gap-2"}


def test_aggregate_rows_stay_gated_on_complete_coverage() -> None:
    """A count without a resource identity is unsafe under partial coverage."""

    evidence = [_row("topology-summary")]
    snapshot = EvidenceSnapshotV2(
        page_kind="network",
        page_id="network",
        coverage=SnapshotCoverage(visible_count=1, total_count=1, complete=False),
        evidence=evidence,
        material_claims=_page_material_claims(evidence),
    )

    retained = select_browser_evidence_for_retention(snapshot)

    assert retained.evidence == ()


def test_claim_evidence_refs_respect_the_contract_bound() -> None:
    """Chunking keeps every minted claim inside the contract's ref limit."""

    evidence = [
        _row(f"gap-{index}", resource_id=_rid(f"r{index}"))
        for index in range(MAX_CLAIM_EVIDENCE_REFS + 5)
    ]

    claims = _page_material_claims(evidence)

    assert len(claims) == 2
    assert all(len(claim.evidence_refs) <= MAX_CLAIM_EVIDENCE_REFS for claim in claims)
    assert sum(len(claim.evidence_refs) for claim in claims) == len(evidence)


def test_unavailable_rows_are_never_asserted() -> None:
    """Only observed rows may back a material claim."""

    evidence = [_row("gap-1", resource_id=_rid("acr"), status="denied")]

    assert _page_material_claims(evidence) == []
