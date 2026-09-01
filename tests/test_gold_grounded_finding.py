from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fabric_pipelines.gold_grounding_contract import (
    GoldGroundedCitation,
    GoldGroundedFinding,
    parse_gold_grounded_findings,
)


def _valid_citation() -> dict[str, object]:
    return {
        "gold_table": "gold_business_service_health",
        "row_key": "row-1",
        "as_of": "2026-09-01T00:00:00Z",
        "confidence": 0.7,
    }


def _valid_finding_payload() -> dict[str, object]:
    return {
        "finding_id": "finding-1",
        "resource_ids": ["/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"],
        "citations": [_valid_citation()],
        "scope_ok": True,
        "summary": "Service is healthy.",
    }


def test_gold_grounded_citation_requires_mandatory_fields() -> None:
    citation = GoldGroundedCitation.model_validate(_valid_citation())
    assert citation.as_of == datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)

    with pytest.raises(ValidationError):
        GoldGroundedCitation.model_validate({
            **_valid_citation(),
            "gold_table": "",
        })
    with pytest.raises(ValidationError):
        GoldGroundedCitation.model_validate({
            **_valid_citation(),
            "row_key": "",
        })
    with pytest.raises(ValidationError):
        GoldGroundedCitation.model_validate({
            **_valid_citation(),
            "confidence": 1.1,
        })
    with pytest.raises(ValidationError):
        GoldGroundedCitation.model_validate({
            **_valid_citation(),
            "as_of": "not-a-date",
        })


def test_gold_grounded_finding_requires_at_least_one_citation() -> None:
    with pytest.raises(ValidationError):
        GoldGroundedFinding.model_validate({
            **_valid_finding_payload(),
            "citations": [],
        })


def test_gold_grounded_finding_requires_scoped_resource_ids() -> None:
    with pytest.raises(ValidationError, match="resource_ids must be full ARM resource IDs"):
        GoldGroundedFinding.model_validate({
            **_valid_finding_payload(),
            "resource_ids": ["vm-1"],
        })


def test_parse_gold_grounded_findings_skips_prose_and_parses_json_lines() -> None:
    payload_line = GoldGroundedFinding.model_validate(_valid_finding_payload()).model_dump_json()
    findings = parse_gold_grounded_findings(
        "\n".join(
            [
                "non-json preface",
                "```json",
                payload_line,
                "```",
                "footer",
            ]
        )
    )
    assert len(findings) == 1
    assert findings[0].finding_id == "finding-1"
    assert findings[0].degraded is False


def test_parse_gold_grounded_findings_returns_degraded_after_retry_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("fabric_pipelines.gold_grounding_contract.time.sleep", lambda seconds: sleeps.append(seconds))

    findings = parse_gold_grounded_findings(
        "\n".join(
            [
                "{bad json line",
                '{"finding_id":"missing-citations","resource_ids":["/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"],"citations":[],"scope_ok":true,"summary":"x"}',
                '{"finding_id":"still-invalid","resource_ids":["bad-id"],"citations":[{"gold_table":"x","row_key":"y","as_of":"2026-09-01T00:00:00Z","confidence":0.7}],"scope_ok":true,"summary":"x"}',
            ]
        ),
        tool_call_id="tool-1",
    )

    assert len(findings) == 1
    degraded = findings[0]
    assert degraded.degraded is True
    assert degraded.degraded_reason == "unparseable Gold evidence"
    assert degraded.citations
    assert degraded.resource_ids[0].startswith("/subscriptions/")
    assert sleeps == [0.5, 1.0]
