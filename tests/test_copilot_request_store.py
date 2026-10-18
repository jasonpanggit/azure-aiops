"""Lost-response admission markers survive replicas without duplicate dispatch."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_investigation_thread_store import FakeClock

from api.scope import SCOPE_DIMENSIONS, Scope
from operations.copilot_request_store import (
    ADMISSION_WINDOW_SECONDS,
    RECEIPT_TTL_SECONDS,
    CopilotRequestStore,
    RequestAlreadyAccepted,
    RequestKeyExpired,
    RequestReceiptNotFound,
    RequestReceiptUnavailable,
    receipt_document_name,
)
from storage.onelake_documents import OneLakeDocumentStore

NOW = 1_800_000_000.0
KEY = f"req-{int(NOW * 1000)}-{'a' * 32}"
SCOPE = Scope.from_mapping({key: [f"{key}-a"] for key in SCOPE_DIMENSIONS})


def test_exact_receipt_survives_restart_without_question_or_answer_storage(tmp_path):
    documents, clock = OneLakeDocumentStore(tmp_path), FakeClock(NOW)
    store = CopilotRequestStore(documents, clock=clock)
    store.accept("owner", KEY, SCOPE, {"question": "Private question", "session_id": "root"})
    before = documents.read(receipt_document_name("owner", KEY))
    assert "Private question" not in str(before)
    assert store.read("owner", KEY, SCOPE)["status"] == "accepted_outcome_unconfirmed"
    assert documents.read(receipt_document_name("owner", KEY)) == before
    store.complete("owner", KEY, SCOPE, thread_id=f"thr-{'b' * 32}", thread_revision=7)
    restarted = CopilotRequestStore(OneLakeDocumentStore(tmp_path), clock=clock)
    assert restarted.read("owner", KEY, SCOPE) == {
        "request_key": KEY, "status": "completed", "durability": "durable",
        "thread_id": f"thr-{'b' * 32}", "thread_revision": 7,
    }
    with pytest.raises(RequestAlreadyAccepted):
        restarted.accept("owner", KEY, SCOPE, {"question": "Private question", "session_id": "root"})


def test_cross_instance_concurrent_admission_has_only_one_winner(tmp_path):
    def admit(_):
        store = CopilotRequestStore(OneLakeDocumentStore(tmp_path), clock=lambda: NOW)
        try:
            store.accept("owner", KEY, SCOPE, {"question": "Same question"})
            return "dispatch"
        except RequestAlreadyAccepted:
            return "withheld"
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(admit, range(16)))
    assert outcomes.count("dispatch") == 1
    assert outcomes.count("withheld") == 15


@pytest.mark.parametrize("dimension", SCOPE_DIMENSIONS)
def test_receipts_withhold_every_different_scope_dimension_and_reject_changed_replay(tmp_path, dimension):
    store = CopilotRequestStore(OneLakeDocumentStore(tmp_path), clock=lambda: NOW)
    store.accept("owner", KEY, SCOPE, {"question": "Original"})
    different = SCOPE.with_dimension(dimension, ["other"])
    with pytest.raises(RequestReceiptNotFound):
        store.read("owner", KEY, different)
    with pytest.raises(RequestAlreadyAccepted):
        store.accept("owner", KEY, different, {"question": "Changed"})
    with pytest.raises(RequestReceiptNotFound):
        store.read("foreign", KEY, SCOPE)
    with pytest.raises(RequestReceiptNotFound):
        store.read("owner", KEY, Scope.unrestricted())


@pytest.mark.parametrize("age", [ADMISSION_WINDOW_SECONDS + 1, -61, RECEIPT_TTL_SECONDS + 1])
def test_stale_or_future_key_never_admitted_even_after_document_loss(tmp_path, age):
    store = CopilotRequestStore(OneLakeDocumentStore(tmp_path), clock=lambda: NOW + age)
    with pytest.raises(RequestKeyExpired):
        store.accept("owner", KEY, SCOPE, {"question": "Question"})
    assert not list(tmp_path.glob("copilot-requests/*.json"))


def test_receipt_expiry_does_not_renew_or_permit_redispatch(tmp_path):
    documents, clock = OneLakeDocumentStore(tmp_path), FakeClock(NOW)
    store = CopilotRequestStore(documents, clock=clock)
    store.accept("owner", KEY, SCOPE, {})
    before = documents.read(receipt_document_name("owner", KEY))
    clock.advance(RECEIPT_TTL_SECONDS + 1)
    with pytest.raises(RequestReceiptNotFound):
        store.read("owner", KEY, SCOPE)
    with pytest.raises(RequestKeyExpired):
        store.accept("owner", KEY, SCOPE, {})
    assert documents.read(receipt_document_name("owner", KEY)) == before


@pytest.mark.parametrize("operation", ["read_or_raise", "create_only", "write"])
def test_storage_failure_is_not_a_memory_fallback_or_retry_permission(tmp_path, monkeypatch, operation):
    documents = OneLakeDocumentStore(tmp_path)
    store = CopilotRequestStore(documents, clock=lambda: NOW)
    if operation == "write":
        store.accept("owner", KEY, SCOPE, {})
    def fail(*_args, **_kwargs):
        raise OSError("storage unavailable")
    monkeypatch.setattr(documents, operation, fail)
    with pytest.raises(RequestReceiptUnavailable):
        if operation == "write":
            store.complete("owner", KEY, SCOPE, thread_id=f"thr-{'b' * 32}", thread_revision=1)
        else:
            store.accept("owner", KEY, SCOPE, {})
    if operation == "write":
        assert store.read("owner", KEY, SCOPE)["status"] == "accepted_outcome_unconfirmed"
        with pytest.raises(RequestAlreadyAccepted):
            store.accept("owner", KEY, SCOPE, {})


def test_lost_admission_write_response_still_prevents_second_dispatch(tmp_path, monkeypatch):
    documents = OneLakeDocumentStore(tmp_path)
    store = CopilotRequestStore(documents, clock=lambda: NOW)
    create = documents.create_only
    def committed_but_response_lost(*args, **kwargs):
        create(*args, **kwargs)
        raise OSError("response lost after commit")
    monkeypatch.setattr(documents, "create_only", committed_but_response_lost)
    with pytest.raises(RequestReceiptUnavailable):
        store.accept("owner", KEY, SCOPE, {})
    with pytest.raises(RequestAlreadyAccepted):
        store.accept("owner", KEY, SCOPE, {})


@pytest.mark.parametrize("content", ["{}", '{"revision": 0}', "invalid JSON"])
def test_corrupt_or_empty_existing_marker_cannot_be_replaced(tmp_path, content):
    path = tmp_path / receipt_document_name("owner", KEY)
    path.parent.mkdir(parents=True)
    path.write_text(content)
    store = CopilotRequestStore(OneLakeDocumentStore(tmp_path), clock=lambda: NOW)
    with pytest.raises((RequestAlreadyAccepted, RequestReceiptUnavailable)):
        store.accept("owner", KEY, SCOPE, {})
    assert path.read_text() == content


def test_missing_configuration_and_invalid_completion_fail_closed(tmp_path):
    with pytest.raises(RequestReceiptUnavailable):
        CopilotRequestStore(None, clock=lambda: NOW).accept("owner", KEY, SCOPE, {})
    store = CopilotRequestStore(OneLakeDocumentStore(tmp_path), clock=lambda: NOW)
    store.accept("owner", KEY, SCOPE, {})
    with pytest.raises(RequestReceiptUnavailable):
        store.complete("owner", KEY, SCOPE, thread_id="", thread_revision=0)
    assert store.read("owner", KEY, SCOPE)["status"] == "accepted_outcome_unconfirmed"
