from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from fabric.gql_readiness import GqlReadinessError, GqlReadinessProbe

WORKSPACE = "2c1fea36-104d-4c26-86db-12e09e432b41"
GRAPH = "e4aa8669-82d3-4ef4-9241-47252fca23fd"
SUCCESS = {
    "status": {"code": "00000"},
    "result": {
        "kind": "TABLE",
        "columns": [{"name": "probe", "gqlType": "INT64", "jsonType": "number|string"}],
        "data": [{"probe": 1}],
    },
}


class Credential:
    def get_token(self, *scopes):
        assert scopes == ("https://api.fabric.microsoft.com/.default",)
        return SimpleNamespace(token="private-token")


def probe(http, **kwargs):
    return GqlReadinessProbe(
        Credential(),
        workspace_id=WORKSPACE,
        graph_model_id=GRAPH,
        http_client=http,
        sleep=lambda _: None,
        **kwargs,
    )


def test_fixed_query_and_target_with_complete_result():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "POST"
        assert request.url.host == "api.fabric.microsoft.com"
        assert request.url.path == f"/v1/workspaces/{WORKSPACE}/graphModels/{GRAPH}/executeQuery"
        assert dict(request.url.params) == {"beta": "true"}
        assert request.content == b'{"query":"RETURN 1 AS probe LIMIT 1"}'
        assert request.headers["Authorization"] == "Bearer private-token"
        assert request.headers["x-ms-fabric-skill"] == "fabriciq-ontology-cli"
        return httpx.Response(200, json=SUCCESS)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert probe(http).check() is None
    assert len(requests) == 1


def test_continuation_is_encoded_once_and_reuses_exact_query():
    requests = []
    token = "opaque+/%2F?=&"

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, json={
                "status": {"code": "02000"},
                "result": {"kind": "TABLE", "columns": [], "data": [], "nextPage": token},
            })
        assert request.url.params["continuationToken"] == token
        assert request.content == requests[0].content
        assert request.url.path == requests[0].url.path
        return httpx.Response(200, json=SUCCESS)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        probe(http).check()
    assert len(requests) == 2


@pytest.mark.parametrize("status", [301, 307, 400, 401, 403, 408, 429, 500])
def test_http_failure_never_retries_or_follows_redirect(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://example.com/"},
                              json={"message": "private-service-message"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(GqlReadinessError, match=f"gql_http_status:{status}") as error,
    ):
        probe(http).check()
    assert len(requests) == 1
    assert "private" not in str(error.value)


@pytest.mark.parametrize("change", [
    {"status": {"code": "42000", "description": "private"}},
    {"status": {"code": "50000"}},
    {"status": {"code": "01000"}},
    {"status": {"code": "00001"}},
    {"status": {"code": "02000"}},
    {"status": {"code": "00000", "cause": {"code": "01000"}}},
    {"errors": [{"message": "private"}]},
    {"additionalStatuses": [{"code": "01000", "diagnostics": {
        "_graphaneGqlStatus": {"gqlType": "STRING", "value": "01M11"},
    }}]},
    {"result": {"kind": "NOTHING"}},
    {"result": {"kind": "TABLE", "columns": [], "data": [], "nextPage": ""}},
    {"result": {"kind": "TABLE", "columns": [], "data": []}},
])
def test_http200_is_not_automatic_success(change):
    payload = deepcopy(SUCCESS)
    payload.update(change)
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=payload)
    )) as http, pytest.raises(GqlReadinessError):
        probe(http).check()


@pytest.mark.parametrize("value", [True, "1", None, 0, 1.0])
def test_probe_scalar_is_exact_not_truthy(value):
    payload = deepcopy(SUCCESS)
    payload["result"]["data"] = [{"probe": value}]
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=payload)
    )) as http, pytest.raises(GqlReadinessError, match="gql_unexpected_probe_result"):
        probe(http).check()


def test_poll_budget_is_finite():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "status": {"code": "02000"},
            "result": {"kind": "TABLE", "columns": [], "data": [], "nextPage": "same"},
        })

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(GqlReadinessError, match="gql_continuation_budget_exhausted"),
    ):
        probe(http, max_requests=3).check()
    assert len(requests) == 3


def test_byte_budget_covers_all_continuation_responses():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "status": {"code": "02000", "description": "x" * 40_000},
            "result": {"kind": "TABLE", "columns": [], "data": [], "nextPage": "same"},
        })

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(GqlReadinessError, match="gql_response_too_large"),
    ):
        probe(http).check()
    assert len(requests) == 2


@pytest.mark.parametrize("token", ["", None, 1, "x" * 8_193])
def test_invalid_continuation_tokens_rejected(token):
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={
            "status": {"code": "02000"},
            "result": {"kind": "TABLE", "columns": [], "data": [], "nextPage": token},
        })
    )) as http, pytest.raises(GqlReadinessError, match="gql_incomplete_result"):
        probe(http).check()


def test_success_with_a_continuation_is_not_complete():
    payload = deepcopy(SUCCESS)
    payload["result"]["nextPage"] = "more"
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=payload)
    )) as http, pytest.raises(GqlReadinessError, match="gql_incomplete_result"):
        probe(http).check()


def test_poll_delay_cannot_admit_a_result_after_deadline():
    now = [0.0]
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={
            "status": {"code": "02000"},
            "result": {"kind": "TABLE", "columns": [], "data": [], "nextPage": "more"},
        })

    def sleep(delay):
        now[0] += delay

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        instance = GqlReadinessProbe(
            Credential(), workspace_id=WORKSPACE, graph_model_id=GRAPH,
            http_client=http, clock=lambda: now[0], sleep=sleep, timeout_seconds=1,
        )
        with pytest.raises(GqlReadinessError, match="gql_deadline_exceeded"):
            instance.check()
    assert len(calls) == 1


def test_deadline_checks_completed_response():
    now = [0.0]

    def handler(_):
        now[0] = 30
        return httpx.Response(200, json=SUCCESS)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(GqlReadinessError, match="gql_deadline_exceeded"),
    ):
        probe(http, clock=lambda: now[0]).check()


def test_expired_credential_acquisition_cannot_send_request():
    now = [0.0]

    class SlowCredential(Credential):
        def get_token(self, *scopes):
            now[0] = 30
            return super().get_token(*scopes)

    def forbidden(_):
        pytest.fail("deadline expired before transport")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as http:
        instance = probe(http, clock=lambda: now[0])
        instance._credential = SlowCredential()
        with pytest.raises(GqlReadinessError, match="gql_deadline_exceeded"):
            instance.check()


@pytest.mark.parametrize("content,reason", [
    (b"not json", "gql_invalid_json"),
    (b"x" * 65_537, "gql_response_too_large"),
    (b"[]", "gql_invalid_response"),
])
def test_malformed_and_oversized_responses_fail_closed(content, reason):
    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, content=content)
    )) as http, pytest.raises(GqlReadinessError, match=reason):
        probe(http).check()


def test_transport_failure_is_not_retried_and_is_sanitized():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private service text")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as http,
        pytest.raises(GqlReadinessError, match="^gql_transport_failure$"),
    ):
        probe(http).check()
    assert len(calls) == 1


@pytest.mark.parametrize("kwargs", [
    {"timeout_seconds": float("nan")}, {"timeout_seconds": float("inf")},
    {"timeout_seconds": 0}, {"timeout_seconds": 61}, {"timeout_seconds": True},
    {"max_requests": 0}, {"max_requests": 11}, {"max_requests": True},
])
def test_invalid_budgets_rejected_before_network(kwargs):
    with httpx.Client() as http, pytest.raises(ValueError):
        probe(http, **kwargs)


def test_target_cannot_contain_url_or_path_injection():
    with httpx.Client() as http, pytest.raises(ValueError):
        GqlReadinessProbe(Credential(), workspace_id="../other",
                          graph_model_id=GRAPH, http_client=http)
