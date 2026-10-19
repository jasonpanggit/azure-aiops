"""Read-only evidence collectors must fail closed without manufacturing acceptance."""

from __future__ import annotations

import base64
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from api.scope import Scope

SPEC = importlib.util.spec_from_file_location(
    "inventory_collector", Path(__file__).parents[1] / "scripts/collect_inventory_evidence.py"
)
assert SPEC and SPEC.loader
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
SCOPE = Scope.from_mapping({"subscription": ["sub-a"]})


def _payload(family="resources", *, generation="gen-1", offset=0, limit=2, total=3):
    key = "resources" if family == "resources" else "groups"
    rows = [
        {"resource_id": f"resource-{i}", "subscription_id": "sub-a", "family": "paas"}
        if key == "resources" else {"key": f"group-{i}"}
        for i in range(offset, min(offset + limit, total))
    ]
    return {
        "data": {
            key: rows, "generation_id": generation, "query_version": "v1",
            "requested_scope": SCOPE.to_dict(),
            "source_status": {"arg": {"state": "ready", "error": "private provider message"}},
        },
        "scope": SCOPE.to_dict(),
        "evidence": [{"timestamp": "2026-10-16T01:16:10Z", "freshness": "stale"}],
        "pagination": {
            "offset": offset, "limit": limit, "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
        },
    }


def test_get_only_collector_pages_all_families_without_exporting_rows():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.params["subscription"] == "sub-a"
        if "/paas/" in request.url.path:
            index = int(request.url.path.rsplit("-", 1)[-1])
            payload = _payload(total=1)
            payload["data"]["resources"][0]["resource_id"] = f"resource-{index}"
            payload["data"]["resources"][0]["properties"] = {"private": "not-exported"}
            return httpx.Response(200, json=payload)
        family = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=_payload(
            family, offset=int(request.url.params["offset"]),
            limit=int(request.url.params["limit"]),
        ))

    with httpx.Client(base_url="https://api.example", transport=httpx.MockTransport(handler)) as client:
        result = collector.collect_api(client, SCOPE, page_size=2)
    assert len(requests) == 11
    assert all(value["total"] == 3 for value in result.values())
    assert "resource-0" not in str(result)
    assert "private provider message" not in str(result)
    assert result["os"]["pages"][0]["source_clocks"][0]["freshness"] == "stale"
    assert result["paas"]["identity_comparison"]["exact_match"] is True


@pytest.mark.parametrize("mutation,error", [
    ("scope", "effective_scope_mismatch"),
    ("generation", "generation_or_query_version_missing"),
    ("page_size", "page_count_mismatch"),
    ("row_scope", "resource_outside_scope"),
    ("raw", "raw_properties_exposed"),
    ("evidence", "source_evidence_missing"),
    ("statuses", "source_status_missing"),
])
def test_response_contract_fails_closed(mutation, error):
    payload = _payload()
    if mutation == "scope":
        payload["scope"] = {}
    elif mutation == "generation":
        payload["data"]["generation_id"] = ""
    elif mutation == "page_size":
        payload["data"]["resources"].pop()
    elif mutation == "row_scope":
        payload["data"]["resources"][0]["subscription_id"] = "sub-b"
    elif mutation == "raw":
        payload["data"]["resources"][0]["properties"] = {"secret": "not-public"}
    elif mutation == "evidence":
        payload["evidence"] = []
    elif mutation == "statuses":
        payload["data"]["source_status"] = {}
    with pytest.raises(ValueError, match=error):
        collector.summarize_response(payload, SCOPE)


@pytest.mark.parametrize("fault,error", [
    ("generation", "generation_changed_during_collection"),
    ("duplicate", "duplicate_or_missing_identity"),
    ("truncation", "silent_truncation"),
    ("offset", "offset_mismatch"),
])
def test_collection_rejects_drift_duplicates_and_incomplete_pages(fault, error):
    def handler(request):
        offset = int(request.url.params["offset"])
        payload = _payload(offset=offset)
        if fault == "generation" and offset:
            payload["data"]["generation_id"] = "changed"
        elif fault == "duplicate" and offset:
            payload["data"]["resources"][0]["resource_id"] = "resource-0"
        elif fault == "truncation":
            payload["pagination"]["next_offset"] = None
        elif fault == "offset":
            payload["pagination"]["offset"] = 1
        return httpx.Response(200, json=payload)

    with (
        httpx.Client(base_url="https://api.example", transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ValueError, match=error),
    ):
        collector.collect_api(client, SCOPE, page_size=2)


def test_http_failure_is_not_healthy_empty():
    with httpx.Client(base_url="https://api.example", transport=httpx.MockTransport(
        lambda request: httpx.Response(503, json={"error": {"message": "private"}})
    )) as client:
        result = collector.collect_api(client, SCOPE)
    assert all(value == {"status": "blocked", "http_status": 503} for value in result.values())


def test_page_budget_exhaustion_is_explicit():
    with httpx.Client(base_url="https://api.example", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=_payload(request.url.path.rsplit("/", 1)[-1]))
    )) as client:
        result = collector.collect_api(client, SCOPE, page_size=2, max_pages=1)
    assert all(value["reason"] == "page_budget_exhausted" for value in result.values())


def test_browser_comparison_requires_exact_generation_rows_and_rendering():
    first = collector.summarize_response(_payload(), SCOPE)
    api = {"resources": {"status": "observed", "pages": [first]}}
    browser = {"schema": "inventory-browser-v1", "families": {
        "resources": {**first, "rendered_rows_match": True},
    }}
    result = collector.compare_browser(browser, api)
    assert result["families_compared"] == ["resources"]
    assert result["all_four_families"] is False
    assert result["screen_reader_acceptance"] == "unproved"
    broken = copy.deepcopy(browser)
    broken["families"]["resources"]["rows_sha256"] = "different"
    with pytest.raises(ValueError, match="browser_api_mismatch"):
        collector.compare_browser(broken, api)
    broken = copy.deepcopy(browser)
    broken["families"]["resources"]["rendered_rows_match"] = False
    with pytest.raises(ValueError, match="browser_rows_not_rendered"):
        collector.compare_browser(broken, api)


def test_snapshot_preserves_nested_payload_and_records_unproved_watermarks(tmp_path):
    from intelligence.inventory.models import ResourceObservation
    from storage.datasets import DatasetStore

    row = ResourceObservation.from_provider_row(
        {"id": "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Web/sites/app",
         "name": "app", "subscriptionId": "sub-a", "type": "Microsoft.Web/sites",
         "properties": {"nested": {"items": [1, 2, {"secret": "kept-in-memory"}]}}},
        family="paas", observed_at="2026-10-16T01:16:10Z", ingestion_run_id="source-run",
    ).to_fabric_row()
    store = DatasetStore(tmp_path)
    store.publish(
        {"inventory/resource_observations": [row]}, {},
        {"runId": "gen-1", "startedAt": "2026-10-16T01:16:10Z", "queryVersion": "v1"},
        ontology={},
    )
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    result = collector.collect_snapshot(str(tmp_path), SCOPE)

    assert result["raw_properties_compared"] == 1
    assert result["temporal_identity_complete"] == 1
    assert result["provider_watermark_advancement"] == "unproved"
    assert result["graph_pipeline_viability"] == "unproved"
    assert "kept-in-memory" not in str(result)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("audience", ["api://audience", "audience"])
def test_delegated_v1_and_v2_audience_targets_are_guarded(monkeypatch, audience):
    part = base64.urlsafe_b64encode(json.dumps({"tid": "tenant", "aud": audience}).encode()).decode().rstrip("=")
    token = f"header.{part}.signature"
    monkeypatch.setattr(collector.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=json.dumps({"accessToken": token}),
    ))
    assert collector._token("tenant", "sub-a", "api://audience") == token
    with pytest.raises(ValueError, match="delegated_token_target_mismatch"):
        collector._token("wrong-tenant", "sub-a", "api://audience")


def test_unconfigured_software_is_not_healthy_empty():
    payload = _payload("software", total=0)
    payload["data"]["source_status"] = {"logs": {
        "state": "unavailable", "workspace_count": 0, "row_count": 0,
        "error": "No Log Analytics workspace was discovered in this connection's scope",
    }}
    result = collector.summarize_response(payload, SCOPE)
    assert result["source_status"]["logs"] == {
        "state": "unavailable", "row_count": 0, "workspace_count": 0,
        "reason": "no_discovered_configurationdata_destination",
    }


@pytest.mark.parametrize("fault,error", [
    ("identity", "paas_identity_set_mismatch"),
    ("total", "total_changed_during_collection"),
])
def test_group_detail_identity_and_page_totals_must_match(fault, error):
    def handler(request):
        offset = int(request.url.params["offset"])
        if "/paas/" in request.url.path:
            payload = _payload(offset=offset, limit=1, total=2 if fault == "total" else 1)
            if fault == "identity":
                payload["data"]["resources"][0]["resource_id"] = "missing-from-cross-family"
            elif offset:
                payload["pagination"]["total"] = 3
            return httpx.Response(200, json=payload)
        family = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=_payload(family, limit=1, total=1))

    with (
        httpx.Client(base_url="https://api.example", transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ValueError, match=error),
    ):
        collector.collect_api(client, SCOPE, page_size=1)
