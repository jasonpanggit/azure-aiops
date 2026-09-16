from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fabric_pipelines.gold_grounding_contract import (
    GoldGroundedCitation,
    GoldGroundedFinding,
    GoldGroundingEmptyProof,
    GoldGroundingStatus,
    parse_gold_grounded_findings,
)

RESOURCE = (
    "/subscriptions/sub-1/resourceGroups/rg/providers/"
    "Microsoft.Compute/virtualMachines/vm1"
)
GENERATION = "generation-1"


def _valid_citation() -> dict[str, object]:
    return {
        "resource_id": RESOURCE,
        "generation_id": GENERATION,
        "gold_table": "gold_business_service_health",
        "row_key": "row-1",
        "as_of": "2026-09-01T00:00:00Z",
        "confidence": 0.7,
    }


def _valid_finding_payload() -> dict[str, object]:
    return {
        "finding_id": "finding-1",
        "generation_id": GENERATION,
        "citations": [_valid_citation()],
        "scope_ok": True,
        "summary": "Service is healthy.",
    }


def test_citation_requires_resource_generation_and_evidence_fields() -> None:
    citation = GoldGroundedCitation.model_validate(_valid_citation())
    assert citation.as_of == datetime(2026, 9, 1, tzinfo=UTC)

    for field, value in (
        ("resource_id", "vm-1"),
        ("generation_id", ""),
        ("gold_table", ""),
        ("row_key", ""),
        ("as_of", "not-a-date"),
        ("confidence", 1.1),
    ):
        with pytest.raises(ValidationError):
            GoldGroundedCitation.model_validate({**_valid_citation(), field: value})


def test_finding_requires_citations_scope_and_one_generation() -> None:
    with pytest.raises(ValidationError):
        GoldGroundedFinding.model_validate(
            {**_valid_finding_payload(), "citations": []}
        )
    with pytest.raises(ValidationError, match="scope_ok must be true"):
        GoldGroundedFinding.model_validate(
            {**_valid_finding_payload(), "scope_ok": False}
        )
    with pytest.raises(ValidationError, match="match the finding generation"):
        GoldGroundedFinding.model_validate(
            {
                **_valid_finding_payload(),
                "citations": [{**_valid_citation(), "generation_id": "generation-2"}],
            }
        )


def test_parser_classifies_success_empty_malformed_and_stale() -> None:
    payload_line = GoldGroundedFinding.model_validate(
        _valid_finding_payload()
    ).model_dump_json()
    success = parse_gold_grounded_findings(
        f"preface\n```json\n{payload_line}\n```",
        expected_generation_id=GENERATION,
    )
    proof = GoldGroundingEmptyProof(
        status="healthy_empty",
        generation_id=GENERATION,
        gold_table="metadata_exposure_gold_generations",
        row_key="generation-1",
        as_of="2026-09-01T00:00:00Z",
        reconciliation_status="reconciled",
        scoped_row_count=0,
        scope_ok=True,
    )
    empty = parse_gold_grounded_findings(
        proof.model_dump_json(),
        expected_generation_id=GENERATION,
        empty_manifest=proof.model_dump(mode="json"),
    )
    blank = parse_gold_grounded_findings(
        "",
        expected_generation_id=GENERATION,
    )
    malformed = parse_gold_grounded_findings(
        "No structured findings available.",
        expected_generation_id=GENERATION,
    )
    stale = parse_gold_grounded_findings(
        GoldGroundedFinding.model_validate(
            {
                **_valid_finding_payload(),
                "generation_id": "generation-2",
                "citations": [{**_valid_citation(), "generation_id": "generation-2"}],
            }
        ).model_dump_json(),
        expected_generation_id=GENERATION,
        empty_manifest=proof.model_dump(mode="json"),
    )

    assert success.status == GoldGroundingStatus.SUCCESS
    assert success.findings[0].resource_ids == [RESOURCE]
    assert empty.status == GoldGroundingStatus.HEALTHY_EMPTY
    assert empty.empty_proof is not None
    assert blank.status == GoldGroundingStatus.MALFORMED
    assert malformed.status == GoldGroundingStatus.MALFORMED
    assert malformed.findings == ()
    assert stale.status == GoldGroundingStatus.STALE


def test_healthy_empty_requires_manifest_proof() -> None:
    proof = GoldGroundingEmptyProof(
        status="healthy_empty",
        generation_id=GENERATION,
        gold_table="metadata_exposure_gold_generations",
        row_key=GENERATION,
        as_of="2026-09-01T00:00:00Z",
        reconciliation_status="reconciled",
        scoped_row_count=0,
        scope_ok=True,
    )
    malformed = parse_gold_grounded_findings(
        '{"status":"healthy_empty","generation_id":"generation-1"}',
        expected_generation_id=GENERATION,
    )
    unverified = parse_gold_grounded_findings(
        proof.model_dump_json(),
        expected_generation_id=GENERATION,
    )
    stale = parse_gold_grounded_findings(
        GoldGroundingEmptyProof(
            status="healthy_empty",
            generation_id="generation-2",
            gold_table="metadata_exposure_gold_generations",
            row_key="generation-2",
            as_of="2026-09-01T00:00:00Z",
            reconciliation_status="reconciled",
            scoped_row_count=0,
            scope_ok=True,
        ).model_dump_json(),
        expected_generation_id=GENERATION,
        empty_manifest=proof.model_dump(mode="json"),
    )

    assert malformed.status == GoldGroundingStatus.MALFORMED
    assert unverified.status == GoldGroundingStatus.MALFORMED
    assert stale.status == GoldGroundingStatus.STALE
