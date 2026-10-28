from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from onboarding.azure_clients import (
    AzureCostManagementClient,
    AzureResourceGraphClient,
    _retry_delay,
)
from onboarding.query_contract import QuerySpec

SPEC = QuerySpec("resources", "Resources", "Resources | project id", False)
CREDENTIAL = SimpleNamespace(get_token=lambda _: SimpleNamespace(token="t"))


def _client(outcomes, sleeps, **kwargs):
    remaining = list(outcomes)

    def requester(method, url, **_):
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return AzureResourceGraphClient(
        CREDENTIAL, requester=requester, retry_sleep=sleeps.append, **kwargs
    )


def test_connect_error_is_retried_then_succeeds():
    sleeps: list[float] = []
    client = _client(
        [
            httpx.ConnectError("Errno 99"),
            httpx.Response(200, json={"data": [{"id": "a"}]}),
        ],
        sleeps,
    )
    assert client.query(SPEC, ["sub"]) == [{"id": "a"}]
    assert sleeps == [1.0]


def test_throttling_honors_retry_after_then_succeeds():
    sleeps: list[float] = []
    client = _client(
        [
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"data": []}),
        ],
        sleeps,
    )
    assert client.query(SPEC, ["sub"]) == []
    assert sleeps == [7.0]


def test_connect_error_budget_is_bounded_and_reraises():
    sleeps: list[float] = []
    client = _client([httpx.ConnectError("x")] * 3, sleeps, max_retries=2)
    with pytest.raises(httpx.ConnectError):
        client.query(SPEC, ["sub"])
    assert sleeps == [1.0, 2.0]


def test_non_transient_error_is_not_retried():
    sleeps: list[float] = []
    client = _client([httpx.Response(400, text="bad")], sleeps)
    with pytest.raises(RuntimeError, match="failed"):
        client.query(SPEC, ["sub"])
    assert sleeps == []


def test_negative_retries_rejected():
    with pytest.raises(ValueError):
        AzureResourceGraphClient(CREDENTIAL, max_retries=-1)


@pytest.mark.parametrize("status", [429, 503])
def test_http_retry_budget_exhaustion_preserves_failure(status):
    sleeps = []
    client = _client([httpx.Response(status, text="exhausted")] * 4, sleeps)
    with pytest.raises(RuntimeError, match="exhausted"):
        client.query(SPEC, ["sub"])
    assert sleeps == [1.0, 2.0, 4.0]


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_zero_retry_budget_preserves_transport_error(error):
    sleeps = []
    failure = error("original")
    client = _client([failure], sleeps, max_retries=0)
    with pytest.raises(error) as caught:
        client.query(SPEC, ["sub"])
    assert caught.value is failure
    assert sleeps == []


def test_retry_retains_scoped_page_payload_and_does_not_duplicate_rows():
    calls = []
    sleeps = []
    outcomes = iter(
        [
            httpx.Response(200, json={"data": [{"id": "a"}], "$skipToken": "next"}),
            httpx.ReadTimeout("transient"),
            httpx.Response(503),
            httpx.Response(200, json={"data": [{"id": "b"}]}),
        ]
    )

    def requester(method, url, **kwargs):
        calls.append(kwargs)
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    client = AzureResourceGraphClient(
        CREDENTIAL,
        requester=requester,
        retry_sleep=sleeps.append,
    )
    result = client.query_with_metadata(SPEC, ["sub"])
    assert result.rows == ({"id": "a"}, {"id": "b"})
    assert result.complete and result.pages_fetched == 2
    assert calls[1:] == [calls[1]] * 3
    assert calls[1]["json"] == {
        "subscriptions": ["sub"],
        "query": SPEC.query,
        "options": {"$top": 1000, "$skipToken": "next"},
    }
    assert calls[0]["headers"] == calls[1]["headers"]
    assert sleeps == [1.0, 2.0]


def test_later_page_exhaustion_never_returns_partial_rows():
    sleeps = []
    client = _client(
        [
            httpx.Response(200, json={"data": [{"id": "a"}], "$skipToken": "next"}),
            httpx.ConnectError("exhausted"),
            httpx.ConnectError("exhausted"),
        ],
        sleeps,
        max_retries=1,
    )
    with pytest.raises(httpx.ConnectError, match="exhausted"):
        client.query_with_metadata(SPEC, ["sub"])
    assert sleeps == [1.0]


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_other_http_errors_are_not_retried(status):
    sleeps = []
    client = _client([httpx.Response(status, text="unchanged")], sleeps)
    with pytest.raises(RuntimeError, match="unchanged"):
        client.query(SPEC, ["sub"])
    assert sleeps == []


@pytest.mark.parametrize(
    "header",
    [
        "Retry-After",
        "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after",
        "x-ms-ratelimit-microsoft.costmanagement-tenant-retry-after",
        "x-ms-ratelimit-microsoft.costmanagement-client-retry-after",
    ],
)
@pytest.mark.parametrize("raw,expected", [("7", 7), ("99999", 120), ("-1", 0)])
def test_retry_headers_have_finite_bounded_delay(header, raw, expected):
    assert _retry_delay(httpx.Response(429, headers={header: raw}), 0) == expected


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "invalid"])
def test_invalid_retry_headers_fall_back_without_invalid_sleep(raw):
    response = httpx.Response(429, headers={"Retry-After": raw})
    assert _retry_delay(response, 2) == 4
    assert _retry_delay(response, 8) == 30


def test_cost_default_survives_five_throttles_and_reports_retry(caplog):
    outcomes = iter(
        [httpx.Response(429, headers={"Retry-After": "999"})] * 5
        + [
            httpx.Response(200, json={"properties": {"columns": [], "rows": []}}),
        ]
    )
    sleeps = []
    client = AzureCostManagementClient(
        CREDENTIAL,
        requester=lambda *a, **k: next(outcomes),
        retry_sleep=sleeps.append,
    )
    assert client.query_actual_costs(["sub"]) == []
    assert client.max_retries == 5 and sleeps == [120] * 5
    assert "Cost Management HTTP 429; retry 5/5 in 120.0s" in caplog.text


def test_cost_default_exhaustion_is_failure_not_empty_success():
    sleeps = []
    client = AzureCostManagementClient(
        CREDENTIAL,
        requester=lambda *a, **k: httpx.Response(429),
        retry_sleep=sleeps.append,
    )
    with pytest.raises(RuntimeError, match="every subscription"):
        client.query_actual_costs(["sub"])
    assert sleeps == [1, 2, 4, 8, 16]


def test_arg_retry_log_has_classification_without_transport_details(caplog):
    client = _client(
        [
            httpx.ConnectError("sensitive provider detail"),
            httpx.Response(200, json={"data": []}),
        ],
        [],
    )
    assert client.query(SPEC, ["sub"]) == []
    assert "ARG transport ConnectError; retry 1/3 in 1.0s" in caplog.text
    assert "sensitive provider detail" not in caplog.text
