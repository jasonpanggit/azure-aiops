"""Offline ARM contracts, redaction, bounded reads and governed integration."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest
from test_incident_scenarios import (
    ARGS,
    END,
    FOREIGN,
    ROOT,
    SCOPE,
    START,
    context_fixture,
    review,
)

from api.scope import Scope
from operations.incident_history_reader import ArmIncidentHistoryReader
from operations.incident_scenarios import investigate

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
CONNECTION = SimpleNamespace(
    subscription_id="sub-a", connection_id="registered", is_active=True
)


def activity(**updates):
    return {
        "eventDataId": "event-1",
        "eventTimestamp": "2026-10-25T10:10:00Z",
        "submissionTimestamp": "2026-10-25T10:11:00Z",
        "resourceId": ROOT,
        "operationName": {"value": "Microsoft.Compute/virtualMachines/write"},
        "status": {"value": "Succeeded"},
        "caller": "SECRET-CALLER",
        "claims": {"token": "SECRET-TOKEN"},
        "description": "SECRET-DESCRIPTION",
        "properties": {"password": "SECRET-PASSWORD"},
        **updates,
    }


def health(**updates):
    return {
        "id": ROOT
        + "/providers/Microsoft.ResourceHealth/availabilityStatuses/history-1",
        "properties": {
            "occurredTime": "2026-10-25T10:15:00Z",
            "reportedTime": "2026-10-25T10:16:00Z",
            "availabilityState": "Unavailable",
            "summary": "SECRET-HEALTH-FREE-TEXT",
            **updates,
        },
    }


def reader_fixture(responses=None, connections=None, clock=lambda: NOW, **kwargs):
    calls, credentials, sleeps = [], [], []
    responses = list(responses or [])

    def request(method, url, **options):
        calls.append((method, url, options))
        if responses:
            next_response = responses.pop(0)
            if isinstance(next_response, Exception):
                raise next_response
            if isinstance(next_response, httpx.Response):
                return next_response
            return httpx.Response(200, json=next_response)
        return httpx.Response(
            200,
            json={
                "value": [health()] if "availabilityStatuses" in url else [activity()]
            },
        )

    def credential(connection):
        credentials.append(connection.connection_id)
        return SimpleNamespace(
            get_token=lambda scope: SimpleNamespace(token="SECRET-ACCESS")
        )

    reader = ArmIncidentHistoryReader(
        lambda: [CONNECTION] if connections is None else connections,
        credential,
        requester=request,
        clock=clock,
        retry_sleep=sleeps.append,
        **kwargs,
    )
    identity = {"resource_id": ROOT, "subscription_id": "sub-a"}
    return reader, identity, calls, credentials, sleeps


def test_supported_exact_resource_window_requests_and_closed_redacted_projection():
    reader, identity, calls, credentials, _ = reader_fixture()
    result = reader.read(SCOPE, ARGS, identity)
    assert credentials == ["registered"]
    assert len(calls) == 2
    method, url, options = calls[0]
    assert method == "GET"
    assert url.endswith(
        "/subscriptions/sub-a/providers/Microsoft.Insights/eventtypes/management/values"
    )
    assert options["params"]["$filter"] == (
        f"eventTimestamp ge '{START}' and eventTimestamp le '{END}' and resourceUri eq '{ROOT}'"
    )
    assert options["params"]["api-version"] == "2015-04-01"
    assert "caller" not in options["params"]["$select"]
    assert calls[1][1].endswith(
        ROOT + "/providers/Microsoft.ResourceHealth/availabilityStatuses"
    )
    assert calls[1][2]["params"] == {"api-version": "2025-05-01"}
    assert all(
        call[2]["timeout"] == 10 and call[2]["follow_redirects"] is False
        for call in calls
    )
    for family in ("changes", "health"):
        receipt = result[family]
        assert receipt["status"] == "partial" and receipt["complete"] is False
        assert receipt["pagination_exhausted"] is True
        assert receipt["pages_fetched"] == 1
        assert receipt["freshness"] == "fresh"
        assert receipt["resource_id"] == ROOT
        assert len(receipt["rows"]) == 1
    assert result["changes"]["rows"][0]["kind"] == "change"
    assert result["health"]["rows"][0]["status"] == "unhealthy"
    assert "SECRET" not in json.dumps(result)
    assert "caller" not in result["changes"]["rows"][0]


@pytest.mark.parametrize(
    "updates",
    [
        {"resource_id": ROOT + "?redirect=secret"},
        {"resource_id": ROOT + "' or true"},
        {"resource_id": ROOT + "/../escape"},
        {"resource_id": ROOT.replace("/app", "/%2e%2e")},
        {"resource_id": ROOT + "/bad"},
        {"since": "0001-01-01T00:00:00+23:59", "until": "0001-01-01T01:00:00+23:59"},
        {"since": "9999-12-31T22:00:00-23:59", "until": "9999-12-31T23:00:00-23:59"},
        {"until": START},
        {"until": "2026-11-25T11:00:00Z"},
    ],
)
def test_invalid_input_before_any_credential_or_http(updates):
    reader, identity, calls, credentials, _ = reader_fixture()
    with pytest.raises(ValueError):
        reader.read(SCOPE, {**ARGS, **updates}, identity)
    assert calls == credentials == []
    context, _, authorizations, _, _ = context_fixture()
    context.incident_history_read_port_provider = lambda: pytest.fail(
        "Invalid request acquired history"
    )
    assert review(context, **updates).status == "denied"
    assert authorizations == []


@pytest.mark.parametrize(
    "connections,scope,identity_update,code",
    [
        ([], SCOPE, {}, "connection_missing_or_ambiguous"),
        ([CONNECTION, CONNECTION], SCOPE, {}, "connection_missing_or_ambiguous"),
        (
            [
                SimpleNamespace(
                    subscription_id="sub-a", connection_id="disabled", is_active=False
                )
            ],
            SCOPE,
            {},
            "connection_missing_or_ambiguous",
        ),
        (
            [CONNECTION],
            Scope.from_mapping({"subscription": ["foreign"]}),
            {},
            "scope_denied",
        ),
        (
            [CONNECTION],
            Scope.from_mapping({"business_service": ["secret"]}),
            {},
            "scope_denied",
        ),
        ([CONNECTION], SCOPE, {"resource_id": FOREIGN}, "scope_denied"),
        (
            [CONNECTION],
            SCOPE,
            {"subscription_connection": "other"},
            "connection_missing_or_ambiguous",
        ),
    ],
)
def test_scope_connections_and_ambiguous_identity_fail_closed_before_credentials(
    connections,
    scope,
    identity_update,
    code,
):
    reader, identity, calls, credentials, _ = reader_fixture(connections=connections)
    result = reader.read(scope, ARGS, {**identity, **identity_update})
    assert {row["error_code"] for row in result.values()} == {code}
    assert calls == credentials == []


def test_connection_scope_selects_exact_registered_identity_and_no_fallback():
    other = SimpleNamespace(
        subscription_id="sub-a", connection_id="other", is_active=True
    )
    reader, identity, _, credentials, _ = reader_fixture(
        connections=[CONNECTION, other]
    )
    scope = Scope.from_mapping({"subscription_connection": ["registered"]})
    result = reader.read(
        scope, ARGS, {**identity, "subscription_connection": "registered"}
    )
    assert result["changes"]["status"] == "partial"
    assert credentials == ["registered"]


@pytest.mark.parametrize(
    "since,until",
    [
        ("0001-01-01T23:59:00+23:59", "0001-01-02T00:59:00+23:59"),
        ("9999-12-30T23:00:00-23:59", "9999-12-31T00:00:00-23:59"),
    ],
)
def test_valid_boundary_controls_are_unavailable_not_overflow_or_provider_reads(
    since, until
):
    reader, identity, calls, credentials, _ = reader_fixture()
    result = reader.read(SCOPE, {**ARGS, "since": since, "until": until}, identity)
    assert all(
        r["error_code"] == "outside_native_retention_or_future" for r in result.values()
    )
    assert calls == credentials == []


def test_retention_is_source_specific_and_empty_is_not_complete_or_healthy():
    reader, identity, calls, _, _ = reader_fixture(
        [{"value": []}],
        clock=lambda: NOW + timedelta(days=40),
    )
    result = reader.read(SCOPE, ARGS, identity)
    assert len(calls) == 1
    assert result["health"]["status"] == "unavailable"
    assert result["changes"]["status"] == "partial"
    assert result["changes"]["complete"] is False
    assert result["changes"]["rows"] == []


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "denied"),
        (403, "denied"),
        (404, "unsupported_or_missing"),
        (429, "throttled"),
        (500, "provider_error"),
        (302, "provider_error"),
    ],
)
def test_denied_errors_and_redirects_are_sanitized_and_retries_bounded(
    status, code, caplog
):
    response = httpx.Response(
        status, text="SECRET-ERROR", headers={"Retry-After": "999999"}
    )
    reader, identity, calls, _, sleeps = reader_fixture([response] * 4)
    result = reader.read(SCOPE, ARGS, identity)
    assert result["changes"]["error_code"] == code
    assert result["health"]["error_code"] == code
    retryable = status in {429, 500}
    assert len(calls) == (4 if retryable else 2)
    assert sleeps == ([1, 1] if retryable else [])
    assert "SECRET" not in caplog.text + json.dumps(result)


def test_transient_retry_success_and_independent_health_failure():
    reader, identity, calls, _, sleeps = reader_fixture(
        [
            httpx.Response(503),
            {"value": [activity()]},
            httpx.ReadTimeout("SECRET-TRANSPORT"),
        ]
    )
    result = reader.read(SCOPE, ARGS, identity)
    assert len(calls) == 3 and sleeps == [1]
    assert result["changes"]["status"] == "partial"
    assert result["health"]["status"] == "unavailable"
    assert "SECRET" not in json.dumps(result)


def test_pagination_exact_caps_duplicates_and_cross_resource_rows():
    url = "https://management.azure.com/subscriptions/sub-a/providers/Microsoft.Insights/eventtypes/management/values"
    reader, identity, calls, _, _ = reader_fixture(
        [
            {"value": [activity()], "nextLink": url + "?$skiptoken=opaque"},
            {
                "value": [
                    activity(),
                    activity(eventDataId="other", resourceId=FOREIGN),
                ],
                "nextLink": url + "?$skiptoken=two",
            },
            {"value": [], "nextLink": url + "?$skiptoken=three"},
            {"value": [health()]},
        ]
    )
    result = reader.read(SCOPE, ARGS, identity)
    assert len(calls) == 4
    assert result["changes"]["pages_fetched"] == 3
    assert result["changes"]["truncated"] is True
    assert result["changes"]["invalid_rows"] == 1
    assert len(result["changes"]["rows"]) == 1
    assert FOREIGN not in json.dumps(result)


@pytest.mark.parametrize(
    "link",
    [
        "https://evil.example/secret",
        "http://management.azure.com/subscriptions/sub-a/providers/Microsoft.Insights/eventtypes/management/values",
        "https://management.azure.com/subscriptions/foreign/providers/Microsoft.Insights/eventtypes/management/values",
        "https://management.azure.com/subscriptions/sub-a/providers/Microsoft.Insights/eventtypes/management/values?$filter=resourceUri%20eq%20%27foreign%27",
        "https://management.azure.com/subscriptions/sub-a/providers/Microsoft.Insights/eventtypes/management/values?api-version=evil",
        123,
    ],
)
def test_untrusted_continuations_never_forward_authorization(link):
    reader, identity, calls, _, _ = reader_fixture(
        [
            {"value": [activity()], "nextLink": link},
            {"value": []},
        ]
    )
    result = reader.read(SCOPE, ARGS, identity)
    assert result["changes"]["error_code"] == "invalid_continuation"
    assert len(calls) == 2
    assert all(urlsplit(call[1]).netloc == "management.azure.com" for call in calls)


def test_third_page_cannot_replace_original_filter_binding():
    base = "https://management.azure.com/subscriptions/sub-a/providers/Microsoft.Insights/eventtypes/management/values"
    reader, identity, calls, _, _ = reader_fixture(
        [
            {"value": [], "nextLink": base + "?$skiptoken=one"},
            {"value": [], "nextLink": base + "?$filter=broader"},
            {"value": []},
        ]
    )
    result = reader.read(SCOPE, ARGS, identity)
    assert result["changes"]["error_code"] == "invalid_continuation"
    assert len(calls) == 3


def test_row_limit_malformed_chronology_and_missing_activity_provider_times():
    bad = [
        activity(eventTimestamp="0001-01-01T00:00:00+23:59"),
        activity(submissionTimestamp="2026-10-25T10:00:00Z"),
        activity(submissionTimestamp="2026-10-26T10:00:00Z"),
        activity(eventTimestamp=None),
        activity(resourceId=None),
    ]
    reader, identity, _, _, _ = reader_fixture(
        [
            {"value": bad + [activity(), activity(eventDataId="overflow")]},
            {"value": [health(reportedTime=None)]},
        ],
        max_rows=6,
    )
    result = reader.read(SCOPE, ARGS, identity)
    assert result["changes"]["invalid_rows"] == 5
    assert result["changes"]["truncated"] is True
    assert len(result["changes"]["rows"]) == 1
    assert result["health"]["invalid_rows"] == 0
    assert result["health"]["rows"][0]["reported_at"] is None


def test_historical_rows_outside_window_excluded_and_non_changes_not_hypothesized():
    reader, identity, _, _, _ = reader_fixture(
        [
            {
                "value": [
                    activity(
                        eventDataId="before", eventTimestamp="2026-10-25T09:00:00Z"
                    ),
                    activity(eventDataId="failed", status={"value": "Failed"}),
                    activity(
                        eventDataId="action",
                        operationName={
                            "value": "Microsoft.Compute/virtualMachines/restart/action"
                        },
                    ),
                ]
            },
            {"value": [health(availabilityState="Unknown")]},
        ]
    )
    history = reader.read(SCOPE, ARGS, identity)
    assert history["changes"]["excluded_rows"] == 1
    assert all(row["kind"] == "activity" for row in history["changes"]["rows"])
    data = investigate(
        ARGS,
        identity=identity,
        changes=None,
        incidents=None,
        authorize=lambda _: None,
        history=history,
    )
    assert data["hypotheses"] == []
    assert data["status"] == "partial"
    assert data["coverage"]["alerts"]["status"] == "unavailable"


def test_health_support_and_recovery_conflict_have_citations_but_never_causality():
    reader, identity, _, _, _ = reader_fixture(
        [
            {"value": [activity()]},
            {
                "value": [
                    health(),
                    {
                        **health(
                            availabilityState="Available",
                            occurredTime="2026-10-25T10:30:00Z",
                            reportedTime="2026-10-25T10:31:00Z",
                        ),
                        "id": ROOT
                        + "/providers/Microsoft.ResourceHealth/availabilityStatuses/recovery",
                    },
                ]
            },
        ]
    )
    data = investigate(
        ARGS,
        identity=identity,
        changes=None,
        incidents=None,
        authorize=lambda _: None,
        history=reader.read(SCOPE, ARGS, identity),
    )
    hypothesis = data["hypotheses"][0]
    assert hypothesis["causality"] == "not_established"
    assert hypothesis["confidence"] == "low"
    assert len(hypothesis["supporting_evidence"]) == 2
    assert len(hypothesis["counterevidence"]) == 1
    refs = {row["evidence_ref"] for row in data["timeline"]}
    assert (
        set(hypothesis["supporting_evidence"] + hypothesis["counterevidence"]) <= refs
    )
    assert all(
        row["reported_at"] and row["source"].startswith("azure_")
        for row in data["timeline"]
    )
    assert data["coverage"]["dependencies"]["status"] == "not_requested"


def test_stale_collection_is_explicit_and_never_complete():
    times = iter([NOW, NOW + timedelta(minutes=16), NOW + timedelta(minutes=17)])
    reader, identity, _, _, _ = reader_fixture(clock=lambda: next(times))
    result = reader.read(SCOPE, ARGS, identity)
    assert all(
        row["freshness"] == "stale"
        and row["error_code"] == "stale_collection"
        and not row["complete"]
        for row in result.values()
    )


def test_malformed_response_is_unavailable_not_empty():
    reader, identity, _, _, _ = reader_fixture([{"wrong": []}, {"value": "wrong"}])
    result = reader.read(SCOPE, ARGS, identity)
    assert all(
        row["status"] == "unavailable" and row["error_code"] == "malformed_response"
        for row in result.values()
    )


def test_tool_collects_history_once_only_after_authorized_inventory_and_cites_it():
    context, reads, auth, _, _ = context_fixture()
    reader, _, calls, credentials, _ = reader_fixture()
    acquired = []

    def factory():
        acquired.append("history")
        assert auth == [ROOT]
        return reader

    context.incident_history_read_port_provider = factory
    result = review(context)
    assert acquired == ["history"]
    assert reads == ["change", "incidents"]
    assert len(calls) == 2 and credentials == ["registered"]
    data = result.data["investigation"]
    assert data["coverage"]["activity_log"]["status"] == "partial"
    assert data["coverage"]["health"]["status"] == "partial"
    assert len(result.evidence) == 4
    assert any(
        e.source_table == "incident_investigation/activity_log" for e in result.evidence
    )
    assert "SECRET" not in json.dumps(result.to_dict())
    context, _, _, _, _ = context_fixture()
    context.incident_history_read_port_provider = lambda: pytest.fail(
        "Denied inventory acquired history"
    )
    assert review(context, resource_id=FOREIGN).status == "denied"


def test_source_failure_does_not_fabricate_history_or_hide_other_evidence(caplog):
    context, _, _, _, _ = context_fixture()

    def fail():
        raise RuntimeError("SECRET-PROVIDER")

    context.incident_history_read_port_provider = fail
    result = review(context)
    assert result.status == "ok"
    data = result.data["investigation"]
    assert data["coverage"]["health"]["error_code"] == "adapter_failed"
    assert data["coverage"]["activity_log"]["status"] == "unavailable"
    assert data["timeline"]
    assert "SECRET" not in caplog.text + json.dumps(result.to_dict())


@pytest.mark.parametrize("canonical", [True, False])
def test_api_history_is_one_scoped_collection_retained_with_deterministic_citations(
    tmp_path,
    monkeypatch,
    canonical,
):
    from fastapi.testclient import TestClient
    from test_api_copilot_investigation import HEADERS, StubAgent, _context

    from api.app import create_app
    from tests.copilot_authorization_fixtures import enable_authorized_canary

    enable_authorized_canary(monkeypatch)
    if not canonical:
        monkeypatch.setenv("AIOPS_COPILOT_ROLLOUT_MODE", "compatibility")
    fixture, reads, auth, incident, change = context_fixture()
    agent = StubAgent()
    context = _context(tmp_path, agent)
    context.inventory_read_port_provider = fixture.inventory_read_port
    context.hybrid_incident_provider = lambda _: (reads.append("incidents"), incident)[
        1
    ]
    context.change_provider = lambda: (reads.append("change"), change)[1]
    reader, _, calls, credentials, _ = reader_fixture()
    context.incident_history_read_port_provider = lambda: reader
    client = TestClient(create_app(context), raise_server_exceptions=False)
    payload = {
        "contract_version": "1",
        "question": "Review selected resource history",
        "requested_scope": SCOPE.to_dict(),
        "snapshot": {
            "version": "2",
            "page_kind": "changes",
            "page_id": "incident-change-investigation",
            "selected_entities": [{"type": "azure", "resource_id": ROOT}],
            "filters": {"since": [START], "until": [END]},
            "coverage": {"visible_count": 0, "total_count": 0, "complete": False},
            "evidence": [],
        },
        "hint": {"specialist_id": "change", "tool": "incidents", "arguments": ARGS},
    }
    response = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=payload,
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert reads == ["change", "incidents"] and auth == [ROOT]
    assert len(calls) == 2 and credentials == ["registered"]
    assert data["mutation_authorized"] is False
    assert agent.calls == []
    investigation = data["tool_results"][0]["data"]["investigation"]
    assert investigation["coverage"]["health"]["source"] == "azure_resource_health"
    assert any(
        "incident_investigation/activity_log" in row["source"]
        for row in data["citations"]
    )
    retained = client.get(
        f"/api/v1/copilot/threads/{data['thread_id']}/history?subscription=sub-a",
        headers=HEADERS,
    )
    assert retained.status_code == 200, retained.text
    assert (
        retained.json()["data"]["turns"][0]["tool_results"][0]["data"]["investigation"]
        == investigation
    )
    assert len(calls) == 2  # A ledger read never reacquires providers.
    payload["hint"] = {
        **payload["hint"],
        "arguments": {**ARGS, "since": "0001-01-01T00:00:00+23:59"},
    }
    denied = client.post(
        "/api/v1/copilot/investigations?subscription=sub-a",
        headers=HEADERS,
        json=payload,
    )
    assert denied.status_code == 400
    assert len(calls) == 2 and credentials == ["registered"]


def test_credential_failure_is_sanitized_and_no_http_is_attempted(caplog):
    reader, identity, calls, _, _ = reader_fixture()

    def fail(_):
        raise RuntimeError("SECRET-CREDENTIAL")

    reader._credential_factory = fail
    result = reader.read(SCOPE, ARGS, identity)
    assert all(row["error_code"] == "credential_unavailable" for row in result.values())
    assert calls == []
    assert "SECRET" not in caplog.text + json.dumps(result)


def test_repeated_next_link_is_finite_and_conflicting_provider_states_are_retained():
    link = "https://management.azure.com/subscriptions/sub-a/providers/Microsoft.Insights/eventtypes/management/values?$skiptoken=repeated"
    reader, identity, calls, _, _ = reader_fixture(
        [
            {
                "value": [activity(), activity(status={"value": "Failed"})],
                "nextLink": link,
            },
            {"value": [], "nextLink": link},
            {"value": []},
        ]
    )
    result = reader.read(SCOPE, ARGS, identity)
    assert len(calls) == 3
    assert result["changes"]["error_code"] == "invalid_continuation"
    assert {row["status"] for row in result["changes"]["rows"]} == {
        "succeeded",
        "failed",
    }
    query = urlsplit(calls[1][1]).query
    assert "resourceUri" in query and "eventTimestamp" in query


def test_timezone_equivalence_uses_utc_event_order_and_never_query_time():
    reader, identity, _, _, _ = reader_fixture(
        [
            {
                "value": [
                    activity(
                        eventTimestamp="2026-10-25T18:10:00+08:00",
                        submissionTimestamp="2026-10-25T06:11:00-04:00",
                    )
                ]
            },
            {"value": [health(occurredTime="2026-10-25T18:15:00+08:00")]},
        ]
    )
    history = reader.read(SCOPE, ARGS, identity)
    assert history["changes"]["rows"][0]["timestamp"] == "2026-10-25T10:10:00+00:00"
    assert history["health"]["rows"][0]["timestamp"] == "2026-10-25T10:15:00+00:00"
    assert (
        history["changes"]["observed_at"] != history["changes"]["rows"][0]["timestamp"]
    )


def test_official_resource_health_wire_spelling_and_optional_reported_time():
    reader, identity, _, _, _ = reader_fixture(
        [
            {"value": [activity()]},
            {
                "value": [
                    health(
                        occuredTime="2026-10-25T10:15:00Z",
                        occurredTime=None,
                        reportedTime=None,
                    )
                ]
            },
        ]
    )
    result = reader.read(SCOPE, ARGS, identity)["health"]
    assert result["invalid_rows"] == 0
    assert result["rows"][0]["timestamp"] == "2026-10-25T10:15:00+00:00"
    assert result["rows"][0]["reported_at"] is None


@pytest.mark.parametrize(
    "updates",
    [
        {"occurredTime": None, "occuredTime": None},
        {"occurredTime": "2026-10-25T10:15:00Z", "occuredTime": "2026-10-25T10:16:00Z"},
        {"reportedTime": "2026-10-25T10:14:00Z"},
    ],
)
def test_health_requires_unambiguous_event_time_and_valid_optional_reported_time(
    updates,
):
    reader, identity, _, _, _ = reader_fixture(
        [{"value": [activity()]}, {"value": [health(**updates)]}]
    )
    result = reader.read(SCOPE, ARGS, identity)["health"]
    assert result["invalid_rows"] == 1
    assert result["rows"] == []


def test_httpx_transport_preserves_continuation_token_and_original_scope_filter():
    requests = []
    base = "https://management.azure.com/subscriptions/sub-a/providers/Microsoft.Insights/eventtypes/management/values"

    def respond(request):
        requests.append(request)
        if "availabilityStatuses" in request.url.path:
            return httpx.Response(200, json={"value": []})
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"value": [activity()], "nextLink": base + "?$skiptoken=opaque"},
            )
        assert request.url.params["$skiptoken"] == "opaque"
        assert request.url.params["api-version"] == "2015-04-01"
        assert f"resourceUri eq '{ROOT}'" in request.url.params["$filter"]
        assert "eventTimestamp ge" in request.url.params["$filter"]
        assert "eventTimestamp le" in request.url.params["$filter"]
        return httpx.Response(200, json={"value": []})

    reader, identity, _, _, _ = reader_fixture()
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        reader._requester = client.request
        result = reader.read(SCOPE, ARGS, identity)
    assert len(requests) == 3
    assert result["changes"]["pagination_exhausted"] is True
    assert result["changes"]["pages_fetched"] == 2


def test_context_history_resolution_stays_optional_and_outside_managed_providers(
    tmp_path,
):
    from test_api_copilot_investigation import _context

    from api.errors import ApiError

    context = _context(tmp_path, None)
    assert context.resolve_provider("incident_history_read_port", optional=True) is None
    with pytest.raises(ApiError):
        context.resolve_provider("incident_history_read_port")
    sentinel = object()
    context.incident_history_read_port_provider = lambda: sentinel
    assert context.resolve_provider("incident_history_read_port") is sentinel
