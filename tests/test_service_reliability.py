"""Declared objectives never manufacture service uptime from missing request telemetry."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from onboarding.monitor_logs import AzureMonitorLogsClient
from operations.service_reliability import (
    ObjectivePolicy,
    ObjectiveRequest,
    RequestAggregate,
    ServiceObjective,
    ServiceObjectiveStore,
    component_id,
    evaluate_requests,
)
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

RESOURCE = "/subscriptions/11111111-1111-1111-1111-111111111111/resourcegroups/apps/providers/microsoft.insights/components/payroll"
START, END = "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"
SCOPE = {"business_service": ["payroll"], "region": ["eastus"]}


def _objective(**updates):
    return ServiceObjective(**{
        "resource_id": RESOURCE, "business_service": "Payroll", "success_target_basis_points": 9950,
        "window_hours": 24, **updates,
    })


def _aggregate(**updates):
    return RequestAggregate(**{
        "record_count": 100, "represented_count": 100, "failed_count": 2,
        "unknown_success_records": 0, "invalid_weight_records": 0,
        "sampled_records": 0, "invalid_duration_records": 0, "p95_duration_ms": 100.0,
        "first_observed_at": "2026-01-01T00:10:00Z", "last_observed_at": "2026-01-01T23:59:00Z",
        **updates,
    })


def _evaluate(aggregate=None, objective=None, **times):
    return evaluate_requests(aggregate or _aggregate(), objective or _objective(), **{
        "started_at": START, "finished_at": END, **times,
    })


@pytest.mark.parametrize("identity", [
    "https://foreign.example/query", RESOURCE + "/child", RESOURCE + "?query=raw",
    RESOURCE.replace("/apps/", "/../"), RESOURCE.replace("/payroll", "/%2e%2e"),
    RESOURCE.replace("/payroll", "/\x00payroll"), RESOURCE.replace("/payroll", "/pay roll"),
])
def test_component_identity_rejects_endpoint_query_and_path_ambiguity(identity):
    with pytest.raises(ValueError):
        component_id(identity)
    credential = Mock()
    with pytest.raises(ValueError):
        AzureMonitorLogsClient(credential).query_request_telemetry(identity, 24)
    credential.get_token.assert_not_called()


@pytest.mark.parametrize("updates", [
    {"expected_revision": True}, {"window_hours": True}, {"window_hours": 2},
    {"success_target_basis_points": 99.5}, {"success_target_basis_points": 0},
    {"success_target_basis_points": 10001}, {"metrics": {}}, {"authority": "approved"},
])
def test_strict_objective_requests_reject_fabricated_measurements_and_defaults(updates):
    with pytest.raises(ValidationError):
        ObjectiveRequest(**{
            "expected_revision": 0, "resource_id": RESOURCE,
            "success_target_basis_points": 9950, "window_hours": 24, **updates,
        })


def test_objectives_are_explicit_exact_scope_shared_revisioned_declarations(tmp_path):
    documents = OneLakeDocumentStore(tmp_path)
    store = ServiceObjectiveStore(documents)
    assert store.read(SCOPE)["objectives"] == []
    saved = store.update(SCOPE, "admin-a", 0, objective=_objective())
    assert ServiceObjectiveStore(documents).read(SCOPE) == saved
    assert saved["updated_by"] == "admin-a"
    assert store.read({})["objectives"] == []
    assert store.read({"business_service": ["payroll"]})["objectives"] == []
    with pytest.raises(DocumentConflictError):
        store.update(SCOPE, "admin-b", 0, objective=_objective())
    changed = store.update(SCOPE, "admin-b", 1, objective=_objective(success_target_basis_points=9990))
    assert changed["updated_by"] == "admin-b"
    assert changed["objectives"][0]["success_target_basis_points"] == 9990
    assert store.update(SCOPE, "admin-b", 2, remove=RESOURCE)["objectives"] == []
    with pytest.raises(KeyError):
        store.update(SCOPE, "admin-b", 3, remove=RESOURCE)


@pytest.mark.parametrize("existing", [False, True])
def test_objective_create_and_replace_are_single_winner_atomic(tmp_path, existing):
    store = ServiceObjectiveStore(OneLakeDocumentStore(tmp_path))
    if existing:
        store.update(SCOPE, "admin-a", 0, objective=_objective())
    gate = Barrier(2)
    read = store._read

    def simultaneous(scope):
        result = read(scope)
        gate.wait()
        return result

    store._read = simultaneous

    def write(actor):
        try:
            store.update(SCOPE, actor, int(existing), objective=_objective())
            return "saved"
        except DocumentConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, ["admin-a", "admin-b"])) == ["conflict", "saved"]
    store._read = read
    assert store.read(SCOPE)["revision"] == int(existing) + 1


@pytest.mark.parametrize("failure", ["scope", "schema", "identity", "count", "timestamp"])
def test_corrupt_stored_policy_never_becomes_an_empty_policy(tmp_path, failure):
    documents = OneLakeDocumentStore(tmp_path)
    store = ServiceObjectiveStore(documents)
    saved = store.update(SCOPE, "admin-a", 0, objective=_objective())
    if failure == "scope":
        saved["scope"] = {}
    elif failure == "schema":
        saved["schema_version"] = True
    elif failure == "identity":
        saved["objectives"].append(saved["objectives"][0])
    elif failure == "count":
        saved["revision"] = 0
    else:
        saved["updated_at"] = "2026-01-01"
    name = store._name(SCOPE)
    documents.replace_if_match(name, saved, expected_etag=documents.read_snapshot(name).etag)
    with pytest.raises(RuntimeError):
        store.read(SCOPE)


def test_objective_capacity_has_no_automatic_eviction(tmp_path):
    store = ServiceObjectiveStore(OneLakeDocumentStore(tmp_path))
    for revision in range(20):
        store.update(SCOPE, "admin-a", revision, objective=_objective(resource_id=f"{RESOURCE}-{revision}"))
    before = store.read(SCOPE)
    with pytest.raises(ValueError, match="20"):
        store.update(SCOPE, "admin-a", 20, objective=_objective(resource_id=f"{RESOURCE}-overflow"))
    assert store.read(SCOPE) == before


def test_measured_request_success_and_declared_budget_are_not_heuristic_posture():
    result = _evaluate()
    assert result["request_success_percent"] == 98.0
    assert result["allowed_failed_requests"] == 0.5
    assert result["remaining_failed_request_budget"] == -1.5
    assert result["consumed_budget_percent"] == 400.0
    assert result["p95_observed_record_duration_ms"] == 100.0
    assert result["authority"] == "none" and result["sampling_estimated"] is False
    assert "Not whole-service uptime" in result["interpretation"]


def test_no_telemetry_is_unknown_not_one_hundred_percent_available():
    empty = _aggregate(
        record_count=0, represented_count=0, failed_count=0,
        p95_duration_ms=None, first_observed_at=None, last_observed_at=None,
    )
    result = _evaluate(empty)
    assert result["request_success_percent"] is None
    assert result["allowed_failed_requests"] is None
    assert result["remaining_failed_request_budget"] is None
    assert result["p95_observed_record_duration_ms"] is None


@pytest.mark.parametrize("quality", ["unknown_success_records", "invalid_weight_records"])
def test_unknown_quality_withholds_success_and_budget_without_manufacturing_zero(quality):
    result = _evaluate(_aggregate(**{quality: 1}))
    assert result["request_success_percent"] is result["allowed_failed_requests"] is None
    assert result["remaining_failed_request_budget"] is None
    assert _evaluate(_aggregate(invalid_duration_records=1))["p95_observed_record_duration_ms"] is None


def test_sampling_and_zero_budget_are_explicit_not_divided_or_rounded_away():
    result = _evaluate(_aggregate(sampled_records=1, represented_count=101))
    assert result["sampling_estimated"] is True
    assert result["request_success_percent"] == pytest.approx(100 * 99 / 101)
    result = _evaluate(objective=_objective(success_target_basis_points=10000))
    assert result["allowed_failed_requests"] == 0
    assert result["remaining_failed_request_budget"] == -2
    assert result["consumed_budget_percent"] is None


@pytest.mark.parametrize("updates", [
    {"record_count": True}, {"represented_count": 2.0}, {"failed_count": 101},
    {"sampled_records": 1}, {"unknown_success_records": 101},
    {"p95_duration_ms": float("nan")}, {"p95_duration_ms": -1.0},
    {"first_observed_at": "2026-01-01"}, {"last_observed_at": "2025-12-31T00:00:00Z"},
])
def test_invalid_measured_aggregate_is_rejected_not_sanitized_to_success(updates):
    with pytest.raises(ValidationError):
        _aggregate(**updates)


def test_window_and_source_observations_must_match():
    with pytest.raises(ValueError, match="window"):
        _evaluate(finished_at="2026-01-03T00:00:00Z")
    with pytest.raises(ValueError, match="outside"):
        _evaluate(_aggregate(last_observed_at=END))


def _logs_response(payload=None, status=200):
    aggregate = _aggregate().model_dump()
    return httpx.Response(status, json=payload if payload is not None else {
        "tables": [{"columns": [{"name": key} for key in aggregate], "rows": [list(aggregate.values())]}],
    })


def test_resource_context_uses_fixed_endpoint_kql_window_and_no_raw_telemetry():
    requester = Mock(return_value=_logs_response())
    credential = Mock(get_token=Mock(return_value=SimpleNamespace(token="private-local-fixture")))
    result = AzureMonitorLogsClient(credential, requester=requester).query_request_telemetry(RESOURCE.upper(), 24)
    _, endpoint = requester.call_args.args
    assert endpoint == f"https://api.loganalytics.azure.com/v1{RESOURCE}/query"
    body = requester.call_args.kwargs["json"]
    assert set(body) == {"query"}
    assert f"| where _ResourceId =~ {json.dumps(RESOURCE)}" in body["query"]
    assert "summarize record_count=count()" in body["query"] and "take " not in body["query"]
    assert (datetime.fromisoformat(result["window_finished_at"]) - datetime.fromisoformat(result["window_started_at"])).total_seconds() == 86400
    assert result["resource_id"] == RESOURCE
    assert set(result["aggregate"]) == set(RequestAggregate.model_fields)


@pytest.mark.parametrize("status,payload", [
    (206, None), (403, None), (200, {"error": {"message": "private provider marker"}, "tables": []}),
    (200, {"tables": [{"columns": [{"name": "record_count"}], "rows": []}]}),
])
def test_request_telemetry_refuses_partial_error_and_missing_aggregate(status, payload):
    client = AzureMonitorLogsClient(
        Mock(get_token=Mock(return_value=SimpleNamespace(token="private-local-fixture"))),
        requester=Mock(return_value=_logs_response(payload, status)),
    )
    with pytest.raises((ValueError, RuntimeError)) as error:
        client.query_request_telemetry(RESOURCE, 24)
    assert "private provider marker" not in str(error.value)


def test_policy_schema_rejects_invalid_objective_version_and_editor():
    for updates in [{"schema_version": True}, {"updated_by": ""}, {"objectives": [_objective(), _objective()]}]:
        with pytest.raises(ValidationError):
            ObjectivePolicy(**{
                "schema_version": 1, "scope": SCOPE, "revision": 1,
                "updated_at": END, "updated_by": "admin-a", "objectives": [_objective()], **updates,
            })


def test_policy_byte_bound_measures_exact_ascii_escaped_document(monkeypatch):
    from operations import service_reliability

    payload = {
        "schema_version": 1, "scope": {"business_service": ["\u4e2d"]}, "revision": 0,
        "updated_at": "", "updated_by": "", "objectives": [],
    }
    actual_bytes = len((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
    monkeypatch.setattr(service_reliability, "MAX_POLICY_BYTES", actual_bytes)
    assert ObjectivePolicy.model_validate(payload).scope == payload["scope"]
    monkeypatch.setattr(service_reliability, "MAX_POLICY_BYTES", actual_bytes - 1)
    with pytest.raises(ValidationError, match="128 KiB"):
        ObjectivePolicy.model_validate(payload)
