from __future__ import annotations

from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from api.scope import Scope
from operations import orchestration_contract as contract
from operations import page_context

ARM_ID = (
    "/subscriptions/SUB-A/resourceGroups/RG/providers/"
    "Microsoft.Compute/virtualMachines/VM-1"
)


def _model(name: str):
    return getattr(contract, name)


def _azure(resource_id: str = ARM_ID):
    return _model("AzureEntityRef")(type="azure", resource_id=resource_id)


def _domain(source_key: str = "Windows Server|2022"):
    return _model("DomainEntityRef")(
        type="domain",
        namespace="inventory",
        kind="operating-system",
        source_key=source_key,
    )


def _evidence(
    evidence_id: str,
    *,
    source_key: str,
    entity=None,
    data: Mapping[str, object] | None = None,
    **overrides,
):
    payload = {
        "evidence_id": evidence_id,
        "source": "inventory/resource_observations",
        "source_key": source_key,
        "entity": entity or _azure(),
        "claim_type": "health",
        "data": dict(data or {"state": "degraded"}),
    }
    payload.update(overrides)
    return contract.SnapshotEvidence.model_validate(payload)


def _snapshot(evidence, **overrides):
    payload = {
        "page_kind": "inventory",
        "page_id": "inventory:azure",
        "coverage": contract.SnapshotCoverage(
            visible_count=len(evidence),
            total_count=len(evidence),
            complete=True,
        ),
        "evidence": evidence,
    }
    payload.update(overrides)
    return contract.EvidenceSnapshotV2.model_validate(payload)


def _canonicalize(snapshot, **overrides):
    return page_context.canonicalize_snapshot_v2(
        snapshot,
        effective_scope=Scope({"subscription": ["sub-a"]}),
        **overrides,
    )


def test_azure_identity_and_hash_are_canonical_and_reorder_stable():
    first = _evidence("browser-z", source_key="record-z")
    second = _evidence(
        "browser-a",
        source_key="record-a",
        entity=_azure(ARM_ID.casefold()),
        data={"state": "healthy"},
    )

    left = _canonicalize(_snapshot([first, second]))
    right = _canonicalize(_snapshot([second, first]))

    assert {row.entity_key for row in left.evidence} == {"azure:" + ARM_ID.casefold()}
    assert left.snapshot_hash() == right.snapshot_hash()
    assert [row.variant_id for row in left.evidence] == [
        row.variant_id for row in right.evidence
    ]


def test_domain_identity_uses_server_resolution_and_ignores_browser_attributes():
    calls = []

    def resolve(entity):
        calls.append(entity.model_dump())
        return {
            "namespace": "inventory",
            "kind": "operating-system",
            "source_key": "windows-server|2022",
            "scope": {"subscription": "sub-a"},
        }

    row = _evidence(
        "os-row",
        source_key="os-source-row",
        entity=_domain(" WINDOWS SERVER|2022 "),
        data={"subscription": "sub-b", "display_name": "spoofed"},
    )

    canonical = _canonicalize(_snapshot([row]), domain_resolver=resolve)

    assert canonical.evidence[0].entity_key == (
        "domain:inventory:operating-system:windows-server|2022"
    )
    assert calls[0]["source_key"] == "WINDOWS SERVER|2022"

    spoofed = _evidence(
        "spoofed-domain",
        source_key="browser-controlled",
        entity=_model("DomainEntityRef")(
            type="domain",
            namespace="browser-spoofed",
            kind="browser-spoofed",
            source_key="Windows Server|2022",
        ),
    )
    spoofed_result = _canonicalize(
        _snapshot([spoofed]),
        domain_resolver=resolve,
    )
    assert spoofed_result.evidence[0].entity_key == canonical.evidence[0].entity_key
    assert spoofed_result.evidence[0].stable_id == canonical.evidence[0].stable_id


def test_authorization_happens_before_retention_for_azure_and_domain_entities():
    selected = _evidence(
        "selected",
        source_key="selected",
        selected=True,
        severity="critical",
    )
    out_of_scope = _evidence(
        "discard-me",
        source_key="discard-me",
        entity=_azure(ARM_ID.replace("SUB-A", "SUB-B")),
        quality="low",
    )
    with pytest.raises(ValueError, match="outside the effective read scope"):
        _canonicalize(_snapshot([selected, out_of_scope]), retention_limit=1)

    domain = _evidence("domain", source_key="domain", entity=_domain())
    with pytest.raises(ValueError, match="outside the effective read scope"):
        _canonicalize(
            _snapshot([domain]),
            domain_resolver=lambda entity: {
                "namespace": entity.namespace,
                "kind": entity.kind,
                "source_key": entity.source_key,
                "scope": {"subscription": "sub-b"},
            },
        )


def test_exact_duplicates_merge_citations_and_strongest_warning():
    rows = [
        _evidence(
            "page-a",
            source_key="same-record",
            citations=["provider:a"],
            status="ok",
        ),
        _evidence(
            "page-b",
            source_key="same-record",
            citations=["provider:b"],
            status="unavailable",
        ),
    ]

    canonical = _canonicalize(_snapshot(rows))

    assert len(canonical.evidence) == 1
    assert canonical.evidence[0].citations == [
        "page-a",
        "page-b",
        "provider:a",
        "provider:b",
    ]
    assert canonical.evidence[0].status == "unavailable"


def test_conflicting_claims_are_retained_as_a_deterministic_conflict_set():
    degraded = _evidence(
        "degraded",
        source_key="same-record",
        data={"state": "degraded"},
    )
    healthy = _evidence(
        "healthy",
        source_key="same-record",
        data={"state": "healthy"},
    )

    canonical = _canonicalize(_snapshot([healthy, degraded]))
    reversed_result = _canonicalize(_snapshot([degraded, healthy]))

    assert len(canonical.evidence) == 2
    assert len(canonical.conflicts) == 1
    assert canonical.conflicts[0].variant_ids == sorted(
        row.variant_id for row in canonical.evidence
    )
    assert canonical.conflicts == reversed_result.conflicts
    assert "conflicting evidence requires resolution" in canonical.uncertainty


def test_retention_never_silently_drops_one_side_of_a_conflict():
    rows = [
        _evidence(
            "degraded",
            source_key="same-record",
            data={"state": "degraded"},
        ),
        _evidence(
            "healthy",
            source_key="same-record",
            data={"state": "healthy"},
        ),
    ]

    with pytest.raises(ValueError, match="cannot preserve conflict set"):
        _canonicalize(_snapshot(rows), retention_limit=1)


def test_normalized_duplicate_hash_is_reorder_stable():
    first = _evidence(
        "first",
        source_key=" Record ",
        source=" Inventory/Resource_Observations ",
        claim_type=" Health ",
    )
    second = _evidence(
        "second",
        source_key="record",
        source="inventory/resource_observations",
        claim_type="health",
    )

    left = _canonicalize(_snapshot([first, second]))
    right = _canonicalize(_snapshot([second, first]))

    assert left.snapshot_hash() == right.snapshot_hash()


def test_retention_ranking_is_deterministic_and_uses_stable_id_as_final_tie_breaker():
    low = _evidence(
        "low",
        source_key="low",
        quality="low",
        severity="low",
    )
    actionable = _evidence(
        "actionable",
        source_key="actionable",
        actionable=True,
        direct=True,
        severity="high",
        quality="high",
    )
    selected = _evidence(
        "selected",
        source_key="selected",
        selected=True,
        severity="critical",
        quality="high",
    )
    tie_b = _evidence("tie-b", source_key="tie-b")
    tie_a = _evidence("tie-a", source_key="tie-a")

    ranked = _canonicalize(
        _snapshot([low, tie_b, actionable, selected, tie_a]),
        retention_limit=4,
    )
    reranked = _canonicalize(
        _snapshot([tie_a, selected, actionable, tie_b, low]),
        retention_limit=4,
    )

    assert [row.citations[0] for row in ranked.evidence[:2]] == [
        "selected",
        "actionable",
    ]
    assert [row.variant_id for row in ranked.evidence] == [
        row.variant_id for row in reranked.evidence
    ]
    assert "evidence retention limit discarded 1 row" in ranked.uncertainty


def test_freshness_coverage_and_conflicts_drive_explicit_insufficiency():
    row = _evidence("stale", source_key="stale")
    claim = _model("MaterialClaim")(
        claim_id="estate-health",
        evidence_refs=["stale"],
        requires_complete_coverage=True,
    )
    snapshot = _snapshot(
        [row],
        coverage=contract.SnapshotCoverage(
            visible_count=1,
            total_count=10,
            complete=False,
        ),
        freshness=[
            contract.SnapshotFreshness(
                source="inventory/resource_observations",
                observed_at="2026-09-01T00:00:00Z",
                status="stale",
            )
        ],
        material_claims=[claim],
    )

    canonical = _canonicalize(snapshot)

    assert canonical.coverage.state == "partial"
    assert canonical.classification == "insufficient_evidence"
    assert "visible subset is incomplete" in canonical.uncertainty
    assert (
        "all retained evidence is stale or unavailable"
        in canonical.insufficiency_reasons
    )
    assert "estate-health requires complete coverage" in canonical.insufficiency_reasons


def test_missing_freshness_is_explicitly_insufficient():
    canonical = _canonicalize(_snapshot([_evidence("unknown", source_key="unknown")]))

    assert canonical.classification == "insufficient_evidence"
    assert "retained evidence freshness is unknown" in canonical.uncertainty
    assert (
        "all retained evidence has unknown freshness" in canonical.insufficiency_reasons
    )


def test_duplicate_merge_rejects_citation_overflow():
    rows = [
        _evidence(
            f"row-{index}",
            source_key="same-record",
            citations=[f"provider:{index}:{citation}" for citation in range(32)],
        )
        for index in range(3)
    ]

    with pytest.raises(ValueError, match="citations exceed retention bound"):
        _canonicalize(_snapshot(rows))


def test_material_claims_reject_orphaned_and_discarded_references():
    with pytest.raises(ValidationError, match="missing evidence reference"):
        _snapshot(
            [_evidence("kept", source_key="kept")],
            material_claims=[
                {
                    "claim_id": "orphan",
                    "evidence_refs": ["missing"],
                }
            ],
        )

    snapshot = _snapshot(
        [
            _evidence("selected", source_key="selected", selected=True),
            _evidence("cited-low", source_key="cited-low", quality="low"),
        ],
        material_claims=[
            {
                "claim_id": "must-close",
                "evidence_refs": ["cited-low"],
            }
        ],
    )
    with pytest.raises(ValueError, match="discarded evidence reference"):
        _canonicalize(snapshot, retention_limit=1)


def test_material_claim_cannot_alias_discarded_row_through_citations():
    snapshot = _snapshot(
        [
            _evidence(
                "kept",
                source_key="kept",
                selected=True,
                citations=["discarded"],
            ),
            _evidence(
                "discarded",
                source_key="discarded",
                quality="low",
            ),
        ],
        material_claims=[
            {
                "claim_id": "must-close",
                "evidence_refs": ["discarded"],
            }
        ],
    )

    with pytest.raises(ValueError, match="discarded evidence reference"):
        _canonicalize(snapshot, retention_limit=1)


def test_partial_freshness_outranks_unknown_at_retention_boundary():
    rows = [
        _evidence(
            "unknown",
            source_key="z-unknown",
            source="inventory/unknown",
        ),
        _evidence(
            "partial",
            source_key="a-partial",
            source="inventory/partial",
        ),
    ]
    snapshot = _snapshot(
        rows,
        freshness=[
            contract.SnapshotFreshness(
                source="inventory/partial",
                observed_at="2026-09-01T00:00:00Z",
                status="partial",
            )
        ],
    )

    canonical = _canonicalize(snapshot, retention_limit=1)

    assert canonical.evidence[0].evidence_refs == ["partial"]
    assert canonical.classification == "ready"


def test_many_coverage_dependent_claims_produce_bounded_insufficiency():
    row = _evidence("shared", source_key="shared")
    snapshot = _snapshot(
        [row],
        coverage=contract.SnapshotCoverage(
            visible_count=1,
            total_count=100,
            complete=False,
        ),
        freshness=[
            contract.SnapshotFreshness(
                source="inventory/resource_observations",
                observed_at="2026-09-01T00:00:00Z",
                status="fresh",
            )
        ],
        material_claims=[
            {
                "claim_id": f"claim-{index}",
                "evidence_refs": ["shared"],
                "requires_complete_coverage": True,
            }
            for index in range(65)
        ],
    )

    canonical = _canonicalize(snapshot)

    assert canonical.classification == "insufficient_evidence"
    assert "65 material claims require complete coverage" in (
        canonical.insufficiency_reasons
    )
    assert len(canonical.insufficiency_reasons) <= 64


def test_strict_bounds_reject_oversized_rows_and_lists():
    with pytest.raises(ValidationError, match="evidence row exceeds size limit"):
        _evidence(
            "too-large",
            source_key="too-large",
            data={"blob": "x" * (page_context.MAX_EVIDENCE_ROW_BYTES + 1)},
        )

    rows = [
        _evidence(f"row-{index}", source_key=f"row-{index}")
        for index in range(page_context.MAX_EVIDENCE_ROWS + 1)
    ]
    with pytest.raises(ValidationError):
        _snapshot(rows)


def test_complete_empty_is_distinct_from_unavailable_or_denied():
    empty = _canonicalize(_snapshot([]))
    assert empty.classification == "empty"
    assert empty.insufficiency_reasons == []

    unavailable = _canonicalize(
        _snapshot(
            [
                _evidence(
                    "unavailable",
                    source_key="unavailable",
                    status="unavailable",
                )
            ]
        )
    )
    denied = _canonicalize(
        _snapshot([_evidence("denied", source_key="denied", status="denied")])
    )

    assert unavailable.classification == "insufficient_evidence"
    assert denied.classification == "insufficient_evidence"
    assert unavailable.insufficiency_reasons != denied.insufficiency_reasons
