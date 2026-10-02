import json

from operations.foundry_agent import (
    MAX_SYNTHESIS_FINDINGS,
    _normalize_coordinator_findings,
    _resolve_finding_id_citations,
)
from operations.orchestration_service import (
    _drop_page_irrelevant_results,
    _has_substantive_findings,
)
from operations.tools import STATUS_OK


def _row(**overrides):
    row = {
        "finding_id": "f-1",
        "summary": "Two subnets lack an NSG.",
        "evidence_refs": ["ev-1"],
        "confidence": "high",
        "freshness": "fresh",
        "uncertainty": [],
        "actionable": True,
        "next_check": "Review the subnet NSG associations.",
    }
    row.update(overrides)
    return row


def test_normalizer_fills_missing_ids_and_dedupes_refs():
    text = json.dumps(
        {"findings": [_row(finding_id="", evidence_refs=["ev-1", "ev-1", " "])]}
    )
    finding = json.loads(_normalize_coordinator_findings(text))["findings"][0]
    assert finding["finding_id"] == "exec-1"
    assert finding["evidence_refs"] == ["ev-1"]


def test_normalizer_coerces_unknown_enums_and_bounds_next_check():
    text = json.dumps(
        {
            "findings": [
                _row(confidence="Very High", freshness="stale-ish", next_check=""),
                _row(finding_id="f-2", next_check="x" * 400),
            ]
        }
    )
    first, second = json.loads(_normalize_coordinator_findings(text))["findings"]
    assert first["confidence"] == "unknown"
    assert first["freshness"] == "unknown"
    assert first["next_check"]
    assert len(second["next_check"]) == 240
    assert second["next_check"].endswith("...")


def test_normalizer_caps_finding_count():
    rows = [_row(finding_id=f"f-{index}") for index in range(MAX_SYNTHESIS_FINDINGS + 3)]
    findings = json.loads(
        _normalize_coordinator_findings(json.dumps({"findings": rows}))
    )["findings"]
    assert len(findings) == MAX_SYNTHESIS_FINDINGS


def test_finding_id_citation_expands_to_published_refs():
    context = {
        "findings": [{"finding_id": "call-7", "evidence_refs": ["ev-a", "ev-b"]}],
        "retained_evidence": [{"evidence_id": "ret-1"}],
    }
    text = json.dumps(
        {"findings": [_row(evidence_refs=["call-7", "ret-1", "ev-a", "bogus"])]}
    )
    refs = json.loads(_resolve_finding_id_citations(text, context))["findings"][0][
        "evidence_refs"
    ]
    # Aliases expand; known refs stay; unknown refs survive for closure to reject.
    assert refs == ["ev-a", "ev-b", "ret-1", "bogus"]


def test_finding_id_citation_without_context_is_unchanged():
    text = json.dumps({"findings": [_row()]})
    assert _resolve_finding_id_citations(text, None) == text


def test_connections_pages_drop_tenant_inventory_results():
    results = [
        {"tool": "inventory_resources", "status": STATUS_OK},
        {"tool": "connections_registry", "status": STATUS_OK},
    ]
    for page_kind in ("connections", "connections_fabric"):
        kept = _drop_page_irrelevant_results(page_kind, results)
        assert [item["tool"] for item in kept] == ["connections_registry"]
    assert len(_drop_page_irrelevant_results("network", results)) == 2
    assert len(_drop_page_irrelevant_results(None, results)) == 2


def test_coverage_only_evidence_is_not_substantive():
    coverage_only = [
        {"status": STATUS_OK, "evidence_refs": ["page_snapshot:twin:coverage"]},
        {"status": "unavailable", "evidence_refs": ["tool:call-1:0"]},
    ]
    assert not _has_substantive_findings(coverage_only)
    assert not _has_substantive_findings(
        coverage_only,
        [{"status": STATUS_OK, "source": "page_snapshot:twin:coverage"}],
    )


def test_observed_evidence_is_substantive():
    assert _has_substantive_findings(
        [{"status": STATUS_OK, "evidence_refs": ["tool:call-1:0"]}]
    )
    assert _has_substantive_findings(
        [], [{"status": STATUS_OK, "source": "network_topology"}]
    )
    assert not _has_substantive_findings(
        [], [{"status": "failed", "source": "network_topology"}]
    )
