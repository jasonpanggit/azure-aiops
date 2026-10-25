from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from fabric.catalog_source import FabricCatalogSource
from fabric.fabric_client import FabricClient

WORKSPACE = "2c1fea36-104d-4c26-86db-12e09e432b41"
ITEM = "f995229d-970e-44ec-8af5-df9e25261d19"
SECOND_ITEM = "bb479201-8ab1-4fde-ab6c-9f9a16477115"
NOW = datetime(2026, 10, 24, tzinfo=UTC)


class Credential:
    def get_token(self, *scopes):
        assert scopes == (FabricClient.SCOPE,)
        return SimpleNamespace(token="test-token")


def _item(item_id=ITEM):
    return {
        "id": item_id,
        "type": "Lakehouse",
        "displayName": "Ops",
        "description": "Operational evidence",
        "catalogEntryType": "FabricItem",
        "hierarchy": {"workspace": {"id": WORKSPACE}},
    }


def _source(pages, **kwargs):
    calls = []

    def handler(request):
        calls.append(request)
        response = pages[len(calls) - 1]
        if isinstance(response, int):
            return httpx.Response(response, headers={"Retry-After": "0"})
        return httpx.Response(200, json=response)

    client = FabricClient(
        Credential(), http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None, max_attempts=2,
    )
    return FabricCatalogSource(
        client, workspace_id=WORKSPACE, clock=lambda: NOW, **kwargs,
    ), calls


def test_catalog_pages_with_token_only_and_retries_with_telemetry():
    source, calls = _source([
        429,
        {"value": [_item()], "continuationToken": "opaque-token"},
        {"value": [_item(SECOND_ITEM)]},
    ], page_size=1, max_pages=2, max_items=2)
    observation = source.fetch()
    bodies = [json.loads(request.content) for request in calls]
    assert bodies == [
        {"filter": f"WorkspaceId eq '{WORKSPACE}' and Type ne 'Workspace'", "pageSize": 1},
        {"filter": f"WorkspaceId eq '{WORKSPACE}' and Type ne 'Workspace'", "pageSize": 1},
        {"continuationToken": "opaque-token"},
    ]
    for request in calls:
        assert request.method == "POST"
        assert str(request.url) == "https://api.fabric.microsoft.com/v1/catalog/search"
        assert request.headers["x-ms-fabric-skill"] == "onelake-catalog-govern-cli"
    assert calls[0].headers["x-ms-client-request-id"] == calls[1].headers["x-ms-client-request-id"]
    evidence = observation.to_dict()
    assert evidence["coverage"] == "partial"
    assert evidence["authoritative"] is False
    assert evidence["requires_direct_verification"] is True
    assert evidence["search_complete"] is True
    assert evidence["pages_fetched"] == 2
    assert evidence["observed_at"] == NOW.isoformat()
    assert {row["item_id"] for row in evidence["candidates"]} == {ITEM, SECOND_ITEM}


def test_search_excludes_workspace_entries_instead_of_discarding_them():
    workspace = {
        "id": WORKSPACE, "type": "Workspace", "catalogEntryType": "Workspace",
        "displayName": "Workspace without item hierarchy",
    }
    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert f"WorkspaceId eq '{WORKSPACE}'" in body["filter"]
        rows = [_item()]
        if "Type ne 'Workspace'" not in body["filter"]:
            rows.append(workspace)
        return httpx.Response(200, json={"value": rows})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        source = FabricCatalogSource(
            FabricClient(Credential(), http_client=http),
            workspace_id=WORKSPACE, clock=lambda: NOW,
        )
        observation = source.fetch()
    assert [row.item_id for row in observation.candidates] == [ITEM]
    assert len(calls) == 1


def test_workspace_returned_despite_item_filter_still_fails_closed():
    source, _ = _source([{"value": [{
        "id": WORKSPACE, "type": "Workspace", "catalogEntryType": "Workspace",
        "displayName": "Workspace without item hierarchy",
    }]}])
    with pytest.raises(ValueError, match="non-item entry"):
        source.fetch()


def test_empty_catalog_is_non_authoritative():
    source, _ = _source([{"value": []}])
    evidence = source.fetch().to_dict()
    assert evidence["candidates"] == []
    assert evidence["coverage"] == "partial"
    assert evidence["authoritative"] is False


def test_later_http_failure_does_not_return_earlier_candidates():
    source, calls = _source([
        {"value": [_item()], "continuationToken": "next"},
        403,
    ])
    with pytest.raises(httpx.HTTPStatusError):
        source.fetch()
    assert len(calls) == 2


def test_later_cross_scope_item_rejects_whole_observation():
    row = _item(SECOND_ITEM)
    row["hierarchy"]["workspace"]["id"] = SECOND_ITEM
    source, calls = _source([
        {"value": [_item()], "continuationToken": "next"},
        {"value": [row]},
    ])
    with pytest.raises(ValueError, match="outside the allowed workspace"):
        source.fetch()
    assert len(calls) == 2


@pytest.mark.parametrize("page", [
    {},
    {"value": None},
    {"value": {}},
    {"value": [None]},
    {"value": [], "continuationToken": 12},
    {"value": [], "continuationToken": " "},
    {"value": [], "continuationUri": "https://untrusted.example/next"},
])
def test_malformed_catalog_fails_without_partial_output(page):
    source, calls = _source([page])
    with pytest.raises((TypeError, ValueError)):
        source.fetch()
    assert len(calls) == 1


@pytest.mark.parametrize("field,value", [
    ("id", "not-a-guid"),
    ("type", ""),
    ("type", "Workspace"),
    ("displayName", None),
    ("description", {}),
    ("catalogEntryType", "Workspace"),
    ("hierarchy", {}),
    ("hierarchy", {"workspace": {"id": SECOND_ITEM}}),
])
def test_invalid_or_cross_scope_candidate_rejected(field, value):
    row = _item()
    row[field] = value
    source, _ = _source([{"value": [row]}])
    with pytest.raises((TypeError, ValueError)):
        source.fetch()


def test_optional_description_and_future_item_type_are_preserved():
    row = _item()
    row["description"] = None
    row["type"] = "FutureFabricItem"
    source, _ = _source([{"value": [row]}])
    candidate = source.fetch().candidates[0]
    assert candidate.item_type == "FutureFabricItem"
    assert candidate.description == ""


@pytest.mark.parametrize("pages,options,message,request_count", [
    ([{"value": [_item(), _item(SECOND_ITEM)]}], {"page_size": 1}, "oversized", 1),
    ([{"value": [_item(), _item(SECOND_ITEM)]}], {"max_items": 1}, "item limit", 1),
    ([{"value": [_item(), _item()]}], {}, "duplicate", 1),
    ([{"value": [_item()], "continuationToken": "next"},
      {"value": [_item()]}], {}, "duplicate", 2),
    ([{"value": [], "continuationToken": "repeat"},
      {"value": [], "continuationToken": "repeat"}], {}, "repeated", 2),
    ([{"value": [], "continuationToken": "next"}], {"max_pages": 1}, "page limit", 1),
])
def test_catalog_bounds_and_paging_fail_closed(pages, options, message, request_count):
    source, calls = _source(copy.deepcopy(pages), **options)
    with pytest.raises(ValueError, match=message):
        source.fetch()
    assert len(calls) == request_count


@pytest.mark.parametrize("status", [401, 403, 500, 202])
def test_catalog_http_or_unexpected_async_failure_is_not_empty_success(status):
    source, calls = _source([status, status])
    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        source.fetch()
    assert len(calls) == (2 if status == 500 else 1)


@pytest.mark.parametrize("kwargs", [
    {"page_size": 0}, {"page_size": 1001}, {"page_size": True},
    {"max_pages": -1}, {"max_items": 0}, {"max_items": 1.5},
])
def test_invalid_bounds_fail_before_any_http(kwargs):
    with pytest.raises(ValueError):
        _source([], **kwargs)


def test_invalid_workspace_rejected_before_any_http():
    client = FabricClient(Credential())
    with pytest.raises(ValueError):
        FabricCatalogSource(client, workspace_id="x' or Type eq 'Lakehouse")
    client.http.close()


def test_naive_observation_time_rejected():
    source, _ = _source([{"value": []}])
    source.clock = lambda: NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        source.fetch()
