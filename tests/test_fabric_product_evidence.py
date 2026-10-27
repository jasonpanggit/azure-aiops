"""Publisher outcomes cannot qualify active Gold, consumer reads or broader scope."""

import json
from types import SimpleNamespace

import pytest

from fabric.product_evidence import (
    STAGES,
    ProductEvidenceError,
    ProductEvidenceStore,
    publish_with_product_evidence,
)
from storage.onelake_documents import DocumentConflictError, OneLakeDocumentStore

SCOPE = {"subscription": ["sub-a"]}
TIME = "2026-10-26T14:00:00+00:00"
LATER = "2026-10-26T15:00:00+00:00"
TABLE = "bronze_resources"


def completed(generation="source-1", tables=(TABLE,), **changes):
    return SimpleNamespace(**{
        "status": "completed", "failed_records": 0, "source_run_id": generation,
        "run_id": "publication-1", "tables": tables, **changes,
    })


@pytest.fixture
def receipts(tmp_path):
    return ProductEvidenceStore(OneLakeDocumentStore(tmp_path))


def test_missing_receipt_is_unknown_without_http_clock(receipts):
    result = receipts.read(TABLE, SCOPE)
    assert set(result["stages"]) == set(STAGES)
    assert result["publication_attempt"] is None
    for stage in result["stages"].values():
        assert stage["status"] == "unknown"
        assert stage["last_attempt"] is stage["last_good"] is None


def test_success_records_only_validated_and_persisted_products(receipts):
    attempt = receipts.begin(SCOPE, "source-1", TIME)
    receipts.finish(SCOPE, attempt, LATER, result=completed())
    result = receipts.read(TABLE, SCOPE)
    assert result["publication_attempt"]["status"] == "completed"
    assert result["publication_attempt"]["observed_at"] == LATER
    for name, stage in result["stages"].items():
        if name in {"validated", "persisted"}:
            assert stage["status"] == "recorded"
            assert stage["last_attempt"] == stage["last_good"]
            assert stage["last_good"]["source_generation"] == "source-1"
            assert stage["last_good"]["scope"] == SCOPE
        else:
            assert stage["status"] == "unknown"
            assert stage["last_good"] is None
    # A product declared in source but omitted by the publisher stays unknown.
    assert all(
        stage["status"] == "unknown"
        for stage in receipts.read("gold_exposure_facts", SCOPE)["stages"].values()
    )


def test_failure_retains_last_good_without_calling_it_current(receipts):
    first = receipts.begin(SCOPE, "source-1", TIME)
    receipts.finish(SCOPE, first, TIME, result=completed())
    last_good = receipts.read(TABLE, SCOPE)["stages"]["persisted"]["last_good"]
    second = receipts.begin(SCOPE, "source-2", LATER)
    running = receipts.read(TABLE, SCOPE)
    assert running["publication_attempt"]["status"] == "running"
    assert running["stages"]["persisted"]["status"] == "unknown"
    receipts.finish(SCOPE, second, LATER, result=None)
    failed = receipts.read(TABLE, SCOPE)
    assert failed["publication_attempt"]["status"] == "failed"
    assert failed["stages"]["persisted"]["last_good"] == last_good
    assert failed["stages"]["persisted"]["last_attempt"] is None
    assert failed["stages"]["persisted"]["status"] == "unknown"


@pytest.mark.parametrize("scope", [
    {}, {"subscription": ["sub-b"]},
    {"subscription": ["sub-a"], "subscription_connection": ["demo"]},
    {"subscription_connection": ["demo"]}, {"business_service": ["tier1"]},
    {"subscription": ["sub-a", "sub-b"]},
])
def test_no_scope_broadening_or_aggregate_relabel(receipts, scope):
    attempt = receipts.begin(SCOPE, "source-1", TIME)
    receipts.finish(SCOPE, attempt, TIME, result=completed())
    assert receipts.read(TABLE, scope)["publication_attempt"] is None


def test_exact_scope_set_is_order_and_case_independent(receipts):
    scope = {"subscription": ["SUB-B", "sub-a"]}
    attempt = receipts.begin(scope, "source-1", TIME)
    receipts.finish(scope, attempt, TIME, result=completed())
    assert receipts.read(TABLE, {"subscription": ["sub-a", "sub-b"]})["publication_attempt"]
    assert receipts.read(TABLE, SCOPE)["publication_attempt"] is None


def test_connection_and_undeclared_reads_do_not_open_document(receipts, monkeypatch):
    monkeypatch.setattr(receipts.documents, "read_snapshot", lambda _: pytest.fail("No broader read"))
    assert receipts.read(TABLE, {"subscription_connection": ["demo"]})["publication_attempt"] is None
    assert receipts.read("invented", SCOPE)["publication_attempt"] is None


def test_superseded_or_terminal_attempt_cannot_write(receipts):
    old = receipts.begin(SCOPE, "source-1", TIME)
    current = receipts.begin(SCOPE, "source-2", LATER)
    with pytest.raises(DocumentConflictError):
        receipts.finish(SCOPE, old, LATER, result=completed())
    receipts.finish(SCOPE, current, LATER, result=None)
    with pytest.raises(DocumentConflictError):
        receipts.finish(SCOPE, current, LATER, result=completed("source-2"))


def test_result_mismatch_and_clock_regression_fail_before_write(receipts):
    attempt = receipts.begin(SCOPE, "source-1", LATER)
    with pytest.raises(ProductEvidenceError, match="source generation"):
        receipts.finish(SCOPE, attempt, LATER, result=completed("other"))
    with pytest.raises(ProductEvidenceError, match="clock"):
        receipts.finish(SCOPE, attempt, TIME, result=completed())
    assert receipts.read(TABLE, SCOPE)["publication_attempt"]["status"] == "running"


@pytest.mark.parametrize("mutation", [
    "contract", "scope", "stage", "activation", "time", "attempt", "oversize", "last_good",
])
def test_malformed_receipt_is_explicit_error_not_empty_success(receipts, mutation):
    attempt = receipts.begin(SCOPE, "source-1", TIME)
    receipts.finish(SCOPE, attempt, TIME, result=completed())
    name = receipts._name(SCOPE)
    payload = receipts.documents.read_or_raise(name)
    if mutation == "contract":
        payload["contract"] = "unknown"
    elif mutation == "scope":
        payload["scope"] = {"subscription": ["other"]}
    elif mutation == "stage":
        del payload["records"][TABLE]["persisted"]
    elif mutation == "activation":
        payload["records"][TABLE]["active"] = payload["records"][TABLE]["persisted"]
    elif mutation == "time":
        payload["attempt"]["observed_at"] = "not-a-clock"
    elif mutation == "attempt":
        payload["records"][TABLE]["persisted"]["last_attempt"]["attempt_id"] = "other"
    elif mutation == "last_good":
        payload["records"][TABLE]["persisted"]["last_good"] = None
    else:
        payload["padding"] = "x" * 65536
    path = receipts.documents.root + "/" + name
    from pathlib import Path
    Path(path).write_text(json.dumps(payload))
    with pytest.raises(ProductEvidenceError):
        receipts.read(TABLE, SCOPE)


def test_corrupt_json_and_storage_errors_propagate(receipts, monkeypatch):
    receipts.begin(SCOPE, "source-1", TIME)
    from pathlib import Path
    Path(receipts.documents.root, receipts._name(SCOPE)).write_text("{")
    with pytest.raises(ValueError):
        receipts.read(TABLE, SCOPE)
    monkeypatch.setattr(receipts.documents, "read_snapshot", lambda _: (_ for _ in ()).throw(OSError("unavailable")))
    with pytest.raises(OSError):
        receipts.read(TABLE, SCOPE)


def test_wrapper_runs_original_sync_and_records_failure(receipts):
    calls = []

    def sync(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("publisher failed")

    with pytest.raises(RuntimeError, match="publisher failed"):
        publish_with_product_evidence(
            SimpleNamespace(sync=sync), receipts, source_generation="source-1",
            scope=SCOPE, assert_lock_held=lambda: None, clock=lambda: TIME,
            exposure_pointer_store="existing-pointer",
        )
    assert calls == [{
        "replay_source_run_id": "source-1", "requested_scope": SCOPE,
        "exposure_pointer_store": "existing-pointer",
    }]
    assert receipts.read(TABLE, SCOPE)["publication_attempt"]["status"] == "failed"


def test_wrapper_does_not_report_registration_or_activation_from_process_success(receipts):
    expected = completed(tables=(TABLE, "gold_exposure_facts"))
    service = SimpleNamespace(sync=lambda **_: expected, lakehouse_manager=object())
    actual = publish_with_product_evidence(
        service, receipts, source_generation="source-1", scope=SCOPE,
        assert_lock_held=lambda: None, clock=lambda: TIME,
    )
    assert actual is expected
    gold = receipts.read("gold_exposure_facts", SCOPE)
    assert gold["stages"]["persisted"]["status"] == "recorded"
    for stage in ("registered", "active", "consumer_query_verified"):
        assert gold["stages"][stage]["status"] == "unknown"


def test_lease_loss_leaves_running_attempt_not_false_failure_or_success(receipts):
    held = True

    def sync(**_):
        nonlocal held
        held = False
        return completed()

    def check():
        if not held:
            raise RuntimeError("lease lost")

    with pytest.raises(RuntimeError, match="lease lost"):
        publish_with_product_evidence(
            SimpleNamespace(sync=sync), receipts, source_generation="source-1",
            scope=SCOPE, assert_lock_held=check, clock=lambda: TIME,
        )
    assert receipts.read(TABLE, SCOPE)["publication_attempt"]["status"] == "running"


def test_api_runtime_reader_uses_server_owned_root_and_exact_scope(receipts, monkeypatch):
    from api import runtime
    from api.scope import Scope

    attempt = receipts.begin(SCOPE, "source-1", TIME)
    receipts.finish(SCOPE, attempt, TIME, result=completed())
    monkeypatch.setattr(runtime, "aiops_home", lambda: receipts.documents.root)
    result = runtime._read_fabric_product_evidence(TABLE, Scope(SCOPE))
    assert result["stages"]["persisted"]["status"] == "recorded"
    assert runtime._read_fabric_product_evidence(
        TABLE, Scope({"subscription_connection": ["demo"]}),
    )["publication_attempt"] is None


def test_receipt_write_failure_after_completed_sync_is_explicit(receipts, monkeypatch, caplog):
    original = receipts.finish

    def fail(*args, **kwargs):
        if kwargs["result"] is not None:
            raise OSError("receipt persistence failed")
        original(*args, **kwargs)

    monkeypatch.setattr(receipts, "finish", fail)
    with pytest.raises(OSError, match="receipt persistence failed"):
        publish_with_product_evidence(
            SimpleNamespace(sync=lambda **_: completed()), receipts,
            source_generation="source-1", scope=SCOPE,
            assert_lock_held=lambda: None, clock=lambda: TIME,
        )
    assert "completion receipt could not be recorded" in caplog.text
    assert receipts.read(TABLE, SCOPE)["publication_attempt"]["status"] == "running"


def test_concurrent_finish_cannot_overwrite_a_newer_attempt(receipts, monkeypatch):
    attempt = receipts.begin(SCOPE, "source-1", TIME)
    competitor = ProductEvidenceStore(OneLakeDocumentStore(receipts.documents.root))
    replace = receipts.documents.replace_if_match

    def race(name, body, *, expected_etag):
        competitor.begin(SCOPE, "source-2", LATER)
        return replace(name, body, expected_etag=expected_etag)

    monkeypatch.setattr(receipts.documents, "replace_if_match", race)
    with pytest.raises(DocumentConflictError):
        receipts.finish(SCOPE, attempt, LATER, result=completed())
    current = receipts.read(TABLE, SCOPE)
    assert current["publication_attempt"]["source_generation"] == "source-2"
    assert current["publication_attempt"]["status"] == "running"
    assert current["stages"]["persisted"]["last_good"] is None


@pytest.mark.parametrize("changes", [
    {"failed_records": 1}, {"status": "failed"}, {"status": "running"},
])
def test_non_success_results_never_qualify_stages(receipts, changes):
    attempt = receipts.begin(SCOPE, "source-1", TIME)
    receipts.finish(SCOPE, attempt, LATER, result=completed(**changes))
    outcome = receipts.read(TABLE, SCOPE)
    assert outcome["publication_attempt"]["status"] == "failed"
    assert all(stage["status"] == "unknown" for stage in outcome["stages"].values())
