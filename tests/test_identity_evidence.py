from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from azure.core.exceptions import ClientAuthenticationError

from onboarding.identity_evidence import IdentityEvidenceClient

SUBSCRIPTION = "22222222-2222-2222-2222-222222222222"
PRINCIPAL = "33333333-3333-3333-3333-333333333333"
MEMBER = "44444444-4444-4444-4444-444444444444"


class Credential:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, scope: str):
        self.scopes.append(scope)
        return SimpleNamespace(token="private-token")


def collect(requester, **limits):
    return IdentityEvidenceClient(Credential(), requester=requester, **limits).collect(
        SUBSCRIPTION, PRINCIPAL, "service_principal"
    )


def test_complete_empty_sources_are_not_effective_access():
    credential = Credential()
    calls = []

    def requester(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, json={"value": []})

    result = IdentityEvidenceClient(credential, requester=requester).collect(
        SUBSCRIPTION, PRINCIPAL, "service_principal"
    )
    assert result["source_reads_complete"] is True
    assert result["effective_access"] == "not_evaluated"
    assert result["read_only"] is True
    assert result["started_at"] <= result["completed_at"]
    assert len(calls) == 4
    assert credential.scopes == [
        "https://graph.microsoft.com/.default",
        *["https://management.azure.com/.default"] * 3,
    ]
    for method, url, options in calls:
        assert method == "GET"
        assert options["follow_redirects"] is False
        assert options["timeout"] == 30
        assert options["headers"]["Authorization"] == "Bearer private-token"
        assert (
            (PRINCIPAL in url)
            if "graph.microsoft.com" in url
            else (SUBSCRIPTION in url)
        )
    assert calls[0][2]["headers"]["ConsistencyLevel"] == "eventual"
    assert "private-token" not in json.dumps(result)


@pytest.mark.parametrize(
    "principal_type,path",
    [
        ("user", "users"),
        ("group", "groups"),
        ("service_principal", "servicePrincipals"),
    ],
)
def test_graph_is_exact_principal_and_paginates(principal_type, path):
    graph_calls = []

    def requester(method, url, **kwargs):
        if "graph.microsoft.com" not in url:
            return httpx.Response(200, json={"value": []})
        graph_calls.append(url)
        assert f"/{path}/{PRINCIPAL}/transitiveMemberOf?" in url
        return httpx.Response(
            200,
            json={
                "value": [{"id": MEMBER}],
                **(
                    {"@odata.nextLink": url + "&$skiptoken=next"}
                    if len(graph_calls) == 1
                    else {}
                ),
            },
        )

    result = IdentityEvidenceClient(Credential(), requester=requester).collect(
        SUBSCRIPTION, PRINCIPAL, principal_type
    )
    source = result["sources"]["transitive_membership"]
    assert source["complete"] is True
    assert source["pages_read"] == 2
    assert source["rows"] == [{"id": MEMBER}, {"id": MEMBER}]


@pytest.mark.parametrize(
    "status,reason",
    [
        (401, "permission_denied"),
        (403, "permission_denied"),
        (302, "http_error"),
        (404, "http_error"),
        (429, "http_error"),
        (500, "http_error"),
    ],
)
def test_failed_source_does_not_hide_other_sources_or_error_body(
    status, reason, caplog
):
    calls = []

    def requester(method, url, **kwargs):
        calls.append(url)
        return (
            httpx.Response(status, text="private-server-detail")
            if "graph.microsoft.com" in url
            else httpx.Response(200, json={"value": []})
        )

    result = collect(requester)
    assert len(calls) == 4
    assert result["source_reads_complete"] is False
    source = result["sources"]["transitive_membership"]
    assert source["reason"] == reason
    assert source["http_status"] == status
    assert source["complete"] is False
    assert all(
        row["complete"]
        for name, row in result["sources"].items()
        if name != "transitive_membership"
    )
    assert "private-server-detail" not in json.dumps(result) + caplog.text
    assert "private-token" not in json.dumps(result) + caplog.text
    assert "identity_evidence_read_incomplete" in caplog.text


@pytest.mark.parametrize(
    "next_link",
    [
        "https://attacker.example/steal",
        "http://graph.microsoft.com/v1.0/servicePrincipals/"
        + PRINCIPAL
        + "/transitiveMemberOf",
        "https://graph.microsoft.com/v1.0/users/" + PRINCIPAL + "/transitiveMemberOf",
        "https://graph.microsoft.com@attacker.example/steal",
        "https://graph.microsoft.com:444/v1.0/servicePrincipals/"
        + PRINCIPAL
        + "/transitiveMemberOf",
        "https://[invalid/",
        "/relative-link",
        False,
        "",
    ],
)
def test_unsafe_or_malformed_continuation_is_never_followed(next_link):
    calls = []

    def requester(method, url, **kwargs):
        calls.append(url)
        return httpx.Response(
            200, json={"value": [{"id": MEMBER}], "@odata.nextLink": next_link}
        )

    result = collect(requester)
    assert (
        result["sources"]["transitive_membership"]["reason"] == "invalid_continuation"
    )
    assert len([url for url in calls if "graph.microsoft.com" in url]) == 1


def test_repeated_continuation_is_incomplete_not_looped():
    calls = []

    def requester(method, url, **kwargs):
        calls.append(url)
        return httpx.Response(
            200, json={"value": [{"id": MEMBER}], "@odata.nextLink": url}
        )

    result = collect(requester)
    source = result["sources"]["transitive_membership"]
    assert source["reason"] == "invalid_continuation"
    assert source["rows"] == [{"id": MEMBER}]
    assert source["pages_read"] == 1


def test_later_page_denial_preserves_rows_but_never_claims_complete():
    calls = 0

    def requester(method, url, **kwargs):
        nonlocal calls
        if "graph.microsoft.com" not in url:
            return httpx.Response(200, json={"value": []})
        calls += 1
        if calls == 2:
            return httpx.Response(403, text="private-server-detail")
        return httpx.Response(
            200, json={"value": [{"id": MEMBER}], "@odata.nextLink": url + "&page=2"}
        )

    result = collect(requester)
    source = result["sources"]["transitive_membership"]
    assert source == {
        "complete": False,
        "reason": "permission_denied",
        "http_status": 403,
        "pages_read": 1,
        "rows": [{"id": MEMBER}],
    }
    assert result["source_reads_complete"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"value": [{"id": "/assignment"}]},
        {"value": [{"id": "/assignment", "properties": []}]},
        {"value": [{"id": "not-an-arm-id", "properties": {}}]},
    ],
)
def test_arm_rows_require_an_arm_id_and_properties(payload):
    result = collect(lambda *args, **kwargs: httpx.Response(200, json=payload))
    assert all(
        row["reason"] == "invalid_payload"
        for name, row in result["sources"].items()
        if name != "transitive_membership"
    )


def test_empty_token_never_reaches_http():
    def no_request(*args, **kwargs):
        pytest.fail("An empty token must not reach HTTP")

    result = IdentityEvidenceClient(
        SimpleNamespace(get_token=lambda scope: SimpleNamespace(token="")),
        requester=no_request,
    ).collect(SUBSCRIPTION, PRINCIPAL, "service_principal")
    assert all(
        row["reason"] == "credential_unavailable" for row in result["sources"].values()
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"value": None},
        {"value": [None]},
        {"value": ["row"]},
        {"value": [{}]},
        {"value": [{"id": "not-a-uuid"}]},
    ],
)
def test_malformed_graph_source_is_not_complete(payload):
    result = collect(lambda *args, **kwargs: httpx.Response(200, json=payload))
    assert result["sources"]["transitive_membership"]["reason"] == "invalid_payload"
    assert result["source_reads_complete"] is False


def test_non_json_and_transport_failures_are_explicit():
    result = collect(lambda *args, **kwargs: httpx.Response(200, content=b"not json"))
    assert all(row["reason"] == "invalid_payload" for row in result["sources"].values())

    def requester(*args, **kwargs):
        raise httpx.ReadTimeout("private-server-detail")

    result = collect(requester)
    assert all(
        row["reason"] == "transport_unavailable" for row in result["sources"].values()
    )
    assert "private-server-detail" not in json.dumps(result)


def test_credential_failure_still_reports_every_source(caplog):
    class DeniedCredential:
        def get_token(self, scope):
            raise ClientAuthenticationError("private-server-detail")

    def no_request(*args, **kwargs):
        pytest.fail("No HTTP requests with an unavailable credential")

    result = IdentityEvidenceClient(DeniedCredential(), requester=no_request).collect(
        SUBSCRIPTION, PRINCIPAL, "service_principal"
    )
    assert len(result["sources"]) == 4
    assert all(
        row["reason"] == "credential_unavailable" for row in result["sources"].values()
    )
    assert "private-server-detail" not in json.dumps(result) + caplog.text


@pytest.mark.parametrize(
    "limit,reason",
    [
        ({"max_pages": 1}, "page_limit"),
        ({"max_rows": 1}, "row_limit"),
        ({"max_page_bytes": 1}, "page_byte_limit"),
    ],
)
def test_limits_never_become_complete(limit, reason):
    def requester(method, url, **kwargs):
        key = "@odata.nextLink" if "graph.microsoft.com" in url else "nextLink"
        rows = (
            [{"id": MEMBER}]
            if key.startswith("@")
            else [{"id": "/scope/row", "properties": {}}]
        )
        return httpx.Response(200, json={"value": rows, key: url + "&page=2"})

    result = collect(requester, **limit)
    assert result["source_reads_complete"] is False
    assert all(row["reason"] == reason for row in result["sources"].values())


def test_arm_nextlink_is_consumed_with_properties_intact():
    calls = []
    row = {
        "id": "/subscriptions/"
        + SUBSCRIPTION
        + "/providers/Microsoft.Authorization/denyAssignments/example",
        "properties": {"principals": [{"id": PRINCIPAL}]},
    }

    def requester(method, url, **kwargs):
        calls.append(url)
        if "/denyAssignments?" in url:
            return httpx.Response(
                200,
                json={
                    "value": [row],
                    **({"nextLink": url + "&page=2"} if "page=2" not in url else {}),
                },
            )
        return httpx.Response(200, json={"value": []})

    result = collect(requester)
    source = result["sources"]["deny_assignments"]
    assert source["complete"] is True
    assert source["pages_read"] == 2
    assert source["rows"] == [row, row]
    assert len(calls) == 5


@pytest.mark.parametrize(
    "field,value",
    [
        ("subscription_id", "../../escape"),
        ("principal_id", PRINCIPAL.replace("-", "")),
        ("principal_id", None),
        ("principal_type", "application"),
    ],
)
def test_invalid_scope_or_principal_is_rejected_before_authentication(field, value):
    credential = Credential()
    arguments = {
        "subscription_id": SUBSCRIPTION,
        "principal_id": PRINCIPAL,
        "principal_type": "user",
    }
    arguments[field] = value
    with pytest.raises(ValueError):
        IdentityEvidenceClient(credential).collect(**arguments)
    assert credential.scopes == []


@pytest.mark.parametrize(
    "limit", ["timeout", "max_pages", "max_rows", "max_page_bytes"]
)
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_limits_require_positive_integers(limit, value):
    with pytest.raises(ValueError, match="positive integers"):
        IdentityEvidenceClient(Credential(), **{limit: value})
