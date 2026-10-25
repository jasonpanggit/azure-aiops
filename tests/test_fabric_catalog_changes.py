from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from fabric.catalog_changes import compare_catalog_reports, validate_catalog_report
from fabric.catalog_source import (
    CatalogCandidate,
    CatalogObservation,
    VerifiedCatalogItem,
    VerifiedCatalogObservation,
)

WORKSPACE = "2c1fea36-104d-4c26-86db-12e09e432b41"
FIRST = "f995229d-970e-44ec-8af5-df9e25261d19"
SECOND = "bb479201-8ab1-4fde-ab6c-9f9a16477115"
NOW = datetime(2026, 10, 25, tzinfo=UTC)


def _report(items, observed_at=NOW):
    rows = tuple(
        CatalogCandidate(item_id, item_type, name, description, WORKSPACE)
        for item_id, item_type, name, description in items
    )
    return {
        "status": "advisory_metadata_verified",
        "authentication_mode": "managed_identity",
        "evidence": VerifiedCatalogObservation(
            catalog=CatalogObservation(WORKSPACE, observed_at, 1, rows),
            verified_items=tuple(
                VerifiedCatalogItem(
                    row, f"/workspaces/{WORKSPACE}/items/{row.item_id}",
                    observed_at, False,
                ) for row in rows
            ),
        ).to_dict(),
    }


def _one():
    return _report([(FIRST, "Lakehouse", "Original", "Before")])


def test_added_changed_and_unresolved_are_advisory_without_retirements():
    before = _one()
    after = _report([(SECOND, "Ontology", "New", "")], NOW + timedelta(seconds=1))
    delta = compare_catalog_reports(before, after)
    assert [row["item_id"] for row in delta["added"]] == [SECOND]
    assert delta["unresolved"] == [{
        "before": before["evidence"]["verified_items"][0]["current"],
        "reason": "not_observed",
    }]
    assert delta["retired"] == []
    assert delta["changed"] == []
    assert delta["authoritative"] is False
    assert delta["requires_schema_verification"] is True
    assert delta["requires_steward_review"] is True
    assert before == _one()


def test_changes_use_direct_metadata_not_indexed_metadata():
    before = _one()
    after = _report([(FIRST, "Lakehouse", "Indexed old name", "Indexed old description")])
    direct = after["evidence"]["verified_items"][0]
    direct["current"].update(display_name="Current", description="After")
    direct["catalog_metadata_changed"] = True
    delta = compare_catalog_reports(before, after)
    assert delta["changed"][0]["changed_fields"] == ["display_name", "description"]
    assert delta["changed"][0]["after"]["display_name"] == "Current"
    assert delta["added"] == delta["unresolved"] == delta["retired"] == []


def test_type_change_is_review_only_and_empty_current_is_not_deletion():
    delta = compare_catalog_reports(
        _one(), _report([(FIRST, "Ontology", "Original", "Before")]),
    )
    assert delta["changed"][0]["changed_fields"] == ["item_type"]
    empty = compare_catalog_reports(_one(), _report([]))
    assert len(empty["unresolved"]) == 1
    assert empty["retired"] == []


def test_order_invariant_digest_and_stable_unchanged_ids():
    before = _report([
        (FIRST, "Lakehouse", "One", ""), (SECOND, "Ontology", "Two", ""),
    ])
    after = copy.deepcopy(before)
    after["evidence"]["catalog"]["candidates"].reverse()
    after["evidence"]["verified_items"].reverse()
    delta = compare_catalog_reports(before, after)
    assert delta["unchanged"] == sorted([FIRST, SECOND])
    assert delta["baseline_sha256"] == delta["current_sha256"]


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(status="failed"),
    lambda r: r.update(authentication_mode="user"),
    lambda r: r.update(unexpected="value"),
    lambda r: r["evidence"].update(authoritative=True),
    lambda r: r["evidence"].update(coverage="complete"),
    lambda r: r["evidence"].update(requires_schema_verification=False),
    lambda r: r["evidence"]["catalog"].update(pages_fetched=0),
    lambda r: r["evidence"]["catalog"].update(search_complete=1),
    lambda r: r["evidence"]["catalog"].update(observed_at="2026-10-25T00:00:00"),
    lambda r: r["evidence"]["verified_items"].clear(),
    lambda r: r["evidence"]["verified_items"].append(r["evidence"]["verified_items"][0]),
    lambda r: r["evidence"]["catalog"]["candidates"].append(
        r["evidence"]["catalog"]["candidates"][0],
    ),
    lambda r: r["evidence"]["verified_items"][0].update(endpoint="/elsewhere"),
    lambda r: r["evidence"]["verified_items"][0].update(catalog_metadata_changed=True),
    lambda r: r["evidence"]["verified_items"][0]["current"].update(workspace_id=SECOND),
    lambda r: r["evidence"]["verified_items"][0]["current"].update(item_type="Ontology"),
    lambda r: r["evidence"]["verified_items"][0]["current"].update(display_name=" "),
    lambda r: r["evidence"]["verified_items"][0].update(verified_at="2026-10-24T00:00:00Z"),
])
def test_malformed_baseline_is_rejected(mutation):
    report = _one()
    mutation(report)
    with pytest.raises(ValueError):
        validate_catalog_report(json.dumps(report))


def test_cross_workspace_auth_mode_and_time_reversal_rejected():
    for report in [
        _report([], NOW - timedelta(seconds=1)),
        {**_report([]), "authentication_mode": "service_principal"},
    ]:
        with pytest.raises(ValueError):
            compare_catalog_reports(_one(), report)
    other = _report([])
    other["evidence"]["catalog"]["workspace_id"] = SECOND
    with pytest.raises(ValueError):
        compare_catalog_reports(_one(), other)


def test_baseline_can_be_prior_delta_report_but_derived_delta_is_ignored():
    report = _one()
    report["metadata_delta"] = {"untrusted": "not used as evidence"}
    parsed = validate_catalog_report(json.dumps(report))
    assert parsed == validate_catalog_report(json.dumps(_one()))
    assert compare_catalog_reports(parsed, _one())["changed"] == []


def test_baseline_input_size_and_shape_are_bounded():
    for raw in [
        '{"x":"' + "x" * 2_000_000 + '"}', "[]", "not-json",
        '{"status":"failed","status":"advisory_metadata_verified"}',
    ]:
        with pytest.raises((TypeError, ValueError)):
            validate_catalog_report(raw)


def test_decoder_recursion_is_normalized_to_validation_error():
    raw = "[" * 10000 + "]" * 10000
    with pytest.raises(ValueError) as exc:
        validate_catalog_report(raw)
    assert isinstance(exc.value.__cause__, RecursionError)


def test_exact_item_limit_is_preserved_and_overflow_rejected():
    rows = [(str(UUID(int=index + 1)), "Lakehouse", "Item", "") for index in range(1000)]
    report = _report(rows)
    parsed = validate_catalog_report(json.dumps(report))
    assert len(parsed["evidence"]["verified_items"]) == 1000
    report["evidence"]["catalog"]["candidates"].append(
        report["evidence"]["catalog"]["candidates"][0],
    )
    with pytest.raises(ValueError):
        validate_catalog_report(json.dumps(report))
