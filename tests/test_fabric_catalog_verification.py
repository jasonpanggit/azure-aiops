from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from fabric.catalog_source import FabricCatalogSource
from fabric.fabric_client import FabricClient

WORKSPACE = "2c1fea36-104d-4c26-86db-12e09e432b41"
ITEM = "f995229d-970e-44ec-8af5-df9e25261d19"
OTHER = "bb479201-8ab1-4fde-ab6c-9f9a16477115"
NOW = datetime(2026, 10, 24, tzinfo=UTC)


class Credential:
    def get_token(self, *scopes):
        return SimpleNamespace(token="test-token")


def _catalog(item_id=ITEM):
    return {
        "id": item_id, "type": "Lakehouse", "displayName": "Indexed name",
        "description": "Indexed description", "catalogEntryType": "FabricItem",
        "hierarchy": {"workspace": {"id": WORKSPACE}},
    }


def _direct(item_id=ITEM):
    return {
        "id": item_id, "workspaceId": WORKSPACE, "type": "Lakehouse",
        "displayName": "Current name", "description": "Current description",
    }


def _source(responses, **options):
    calls = []

    def handler(request):
        calls.append(request)
        result = responses[len(calls) - 1]
        if isinstance(result, int):
            return httpx.Response(result, headers={"Retry-After": "0"})
        return httpx.Response(200, json=result)

    return FabricCatalogSource(
        FabricClient(
            Credential(), http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_attempts=2, sleep=lambda _: None,
        ),
        workspace_id=WORKSPACE, clock=lambda: NOW, **options,
    ), calls


def test_direct_verification_retains_catalog_and_current_metadata():
    source, calls = _source([{"value": [_catalog()]}, _direct()])
    evidence = source.fetch_verified().to_dict()
    assert [request.method for request in calls] == ["POST", "GET"]
    assert str(calls[1].url) == (
        f"https://api.fabric.microsoft.com/v1/workspaces/{WORKSPACE}/items/{ITEM}"
    )
    assert evidence["catalog"]["candidates"][0]["display_name"] == "Indexed name"
    row = evidence["verified_items"][0]
    assert row["current"]["display_name"] == "Current name"
    assert row["current"]["description"] == "Current description"
    assert row["catalog_metadata_changed"] is True
    assert row["verified_at"] == NOW.isoformat()
    assert row["endpoint"] == f"/workspaces/{WORKSPACE}/items/{ITEM}"
    assert evidence["authoritative"] is False
    assert evidence["coverage"] == "partial"
    assert evidence["requires_schema_verification"] is True
    assert evidence["requires_direct_verification"] is False
    assert evidence["verification_scope"] == "item_metadata_only"
    for request in calls:
        assert request.headers["x-ms-fabric-skill"] == "onelake-catalog-govern-cli"


@pytest.mark.parametrize("field,value", [
    ("id", OTHER), ("id", None), ("workspaceId", OTHER),
    ("workspaceId", None), ("type", "Ontology"), ("displayName", ""),
    ("description", []),
])
def test_direct_malformed_or_identity_type_drift_fails_closed(field, value):
    response = _direct()
    response[field] = value
    source, calls = _source([{"value": [_catalog()]}, response])
    with pytest.raises((ValueError, TypeError)):
        source.fetch_verified()
    assert len(calls) == 2


@pytest.mark.parametrize("status", [401, 403, 404, 500, 202])
def test_direct_access_deleted_transient_and_async_failures_propagate(status):
    source, _ = _source([{"value": [_catalog()]}, status, status])
    with pytest.raises((httpx.HTTPStatusError, ValueError, TypeError)):
        source.fetch_verified()


def test_later_direct_failure_never_returns_partial_verified_success():
    source, calls = _source([
        {"value": [_catalog(ITEM), _catalog(OTHER)]},
        _direct(OTHER), 404,
    ])
    with pytest.raises(httpx.HTTPStatusError):
        source.fetch_verified()
    assert len(calls) == 3


def test_search_must_finish_before_any_direct_get_and_bounds_apply():
    source, calls = _source([
        {"value": [_catalog()], "continuationToken": "next"},
    ], max_pages=1)
    with pytest.raises(ValueError, match="page limit"):
        source.fetch_verified()
    assert len(calls) == 1
    assert calls[0].method == "POST"


def test_exact_item_bound_verifies_each_item_after_all_search_pages():
    source, calls = _source([
        {"value": [_catalog(ITEM)], "continuationToken": "next"},
        {"value": [_catalog(OTHER)]},
        _direct(OTHER), _direct(ITEM),
    ], page_size=1, max_pages=2, max_items=2)
    evidence = source.fetch_verified().to_dict()
    assert [request.method for request in calls] == ["POST", "POST", "GET", "GET"]
    assert json.loads(calls[1].content) == {"continuationToken": "next"}
    assert {row["current"]["item_id"] for row in evidence["verified_items"]} == {ITEM, OTHER}


def test_item_overflow_prevents_all_direct_verification():
    source, calls = _source([
        {"value": [_catalog(ITEM), _catalog(OTHER)]},
    ], max_items=1)
    with pytest.raises(ValueError, match="item limit"):
        source.fetch_verified()
    assert len(calls) == 1


def test_empty_search_remains_non_authoritative():
    source, calls = _source([{"value": []}])
    evidence = source.fetch_verified().to_dict()
    assert evidence["verified_items"] == []
    assert evidence["authoritative"] is False
    assert evidence["coverage"] == "partial"
    assert len(calls) == 1


@pytest.mark.parametrize("verified_at", [
    NOW.replace(tzinfo=None),
    NOW.replace(year=2025),
])
def test_invalid_verification_clock_rejects_observation(verified_at):
    source, _ = _source([{"value": [_catalog()]}, _direct()])
    times = iter([NOW, verified_at])
    source.clock = lambda: next(times)
    with pytest.raises(ValueError, match="time"):
        source.fetch_verified()


def test_direct_retry_keeps_telemetry_and_identity():
    source, calls = _source([{"value": [_catalog()]}, 429, _direct()])
    source.fetch_verified()
    assert calls[1].url == calls[2].url
    assert calls[1].headers["x-ms-client-request-id"] == calls[2].headers["x-ms-client-request-id"]
    assert calls[2].headers["x-ms-fabric-skill"] == "onelake-catalog-govern-cli"


def test_unchanged_metadata_and_optional_description():
    indexed = _catalog()
    indexed.pop("description")
    direct = _direct()
    direct.update(displayName=indexed["displayName"], description=None)
    source, _ = _source([{"value": [indexed]}, direct])
    row = source.fetch_verified().to_dict()["verified_items"][0]
    assert row["catalog_metadata_changed"] is False
    assert row["current"]["description"] == ""


def test_search_only_fetch_still_makes_no_direct_requests():
    source, calls = _source([{"value": [_catalog()]}])
    evidence = source.fetch().to_dict()
    assert evidence["requires_direct_verification"] is True
    assert len(calls) == 1
    assert json.loads(calls[0].content)["filter"] == f"WorkspaceId eq '{WORKSPACE}'"
