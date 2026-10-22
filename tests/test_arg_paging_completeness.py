from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from intelligence.vulnerability.acquisition import (
    AcquisitionBatchFailure,
    AcquisitionFailure,
    AcquisitionFailureCode,
    successful_rows_by_query,
)
from onboarding.azure_clients import (
    AzureCliArgClient,
    AzureResourceGraphClient,
    CommandResult,
)
from onboarding.discovery_source import AzureResourceGraphSource
from onboarding.query_contract import QuerySpec

SPEC = QuerySpec("resources", "Resources", "Resources | project id", False)


@pytest.fixture(params=["cli", "rest"])
def client_factory(request):
    def build(payloads, *, max_pages=3):
        remaining = list(payloads)
        calls = []
        if request.param == "cli":
            def run(command, timeout):
                calls.append(command)
                return CommandResult(0, json.dumps(remaining.pop(0)), "")

            client = AzureCliArgClient(
                runner=SimpleNamespace(run=run), max_pages=max_pages,
            )
        else:
            def requester(method, url, **kwargs):
                calls.append(kwargs["json"])
                return httpx.Response(200, json=remaining.pop(0))

            credential = SimpleNamespace(
                get_token=lambda _: SimpleNamespace(token="test-token"),
            )
            client = AzureResourceGraphClient(
                credential, requester=requester, max_pages=max_pages,
            )
        return client, calls

    return build


@pytest.mark.parametrize("flag", ["resultTruncated", "result_truncated"])
@pytest.mark.parametrize("value", ["true", True])
def test_truncated_page_without_continuation_never_returns_complete(client_factory, flag, value):
    client, calls = client_factory([{"data": [{"id": "partial"}], flag: value}])
    with pytest.raises(RuntimeError, match="truncated.*continuation"):
        client.query_with_metadata(SPEC, ["sub"])
    assert len(calls) == 1


@pytest.mark.parametrize("flag", ["resultTruncated", "result_truncated"])
@pytest.mark.parametrize("value", [None, "unknown", 1, [], {}])
def test_invalid_truncation_metadata_fails_closed(client_factory, flag, value):
    client, _ = client_factory([{"data": [], flag: value}])
    with pytest.raises(TypeError, match="truncation"):
        client.query_with_metadata(SPEC, ["sub"])


@pytest.mark.parametrize("flag", ["resultTruncated", "result_truncated"])
@pytest.mark.parametrize("value", ["false", False])
def test_explicit_complete_page_is_preserved(client_factory, flag, value):
    client, _ = client_factory([{"data": [{"id": "a"}], flag: value}])
    result = client.query_with_metadata(SPEC, ["sub"])
    assert result.complete
    assert result.pages_fetched == 1
    assert result.rows == ({"id": "a"},)


@pytest.mark.parametrize("token_key", ["skip_token", "skipToken", "$skipToken"])
def test_truncated_page_with_valid_continuation_is_fully_drained(client_factory, token_key):
    client, calls = client_factory([
        {"data": [{"id": "a"}], "resultTruncated": "true", token_key: "next"},
        {"data": [{"id": "b"}], "resultTruncated": "false"},
    ])
    result = client.query_with_metadata(SPEC, ["sub"])
    assert result.complete
    assert result.pages_fetched == 2
    assert result.rows == ({"id": "a"}, {"id": "b"})
    assert "next" in json.dumps(calls[1])


def test_later_unpageable_truncation_cannot_return_partial_accumulation(client_factory):
    client, calls = client_factory([
        {"data": [{"id": "a"}], "$skipToken": "next"},
        {"data": [{"id": "b"}], "resultTruncated": "true"},
    ])
    with pytest.raises(RuntimeError, match="truncated.*continuation"):
        client.query(SPEC, ["sub"])
    assert len(calls) == 2


def test_continuation_still_obeys_existing_page_budget(client_factory):
    client, calls = client_factory([
        {"data": [{"id": "a"}], "resultTruncated": "true", "$skipToken": "next"},
    ], max_pages=1)
    with pytest.raises(RuntimeError, match="exceeded max_pages=1"):
        client.query_with_metadata(SPEC, ["sub"])
    assert len(calls) == 1


@pytest.mark.parametrize("value", [1, True, {}, ["next"], " "])
def test_malformed_continuation_is_not_used_as_completion_proof(client_factory, value):
    client, _ = client_factory([{"data": [], "$skipToken": value}])
    with pytest.raises(TypeError, match="continuation"):
        client.query_with_metadata(SPEC, ["sub"])


def test_conflicting_token_aliases_are_not_silently_selected(client_factory):
    client, _ = client_factory([{
        "data": [], "$skipToken": "one", "skip_token": "another",
    }])
    with pytest.raises(TypeError, match="conflicting continuation"):
        client.query_with_metadata(SPEC, ["sub"])


def test_truncated_acquisition_is_failure_not_successful_empty_source(client_factory):
    client, _ = client_factory([{"data": [], "resultTruncated": "true"}])
    source = AzureResourceGraphSource(mcp=None, arg=client, connection_id="demo")
    outcomes = source.fetch([SPEC], ["sub"])
    failure = outcomes[SPEC.name]
    assert isinstance(failure, AcquisitionFailure)
    assert failure.error_code is AcquisitionFailureCode.PAGING_INCOMPLETE
    assert failure.connection_id == "demo"
    assert failure.scope == ("sub",)
    assert not hasattr(failure, "rows")
    with pytest.raises(AcquisitionBatchFailure):
        successful_rows_by_query(outcomes)
