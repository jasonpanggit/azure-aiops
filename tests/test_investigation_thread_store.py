"""Durable, principal- and scope-bound continuity for canonical investigations.

Continuity used to live only in process memory, so a navigation that landed on
another replica -- or any restart -- silently dropped the operator's thread and
started a fresh one. These tests pin the properties a continuity record has to
hold before it may be served: it must outlive the process, prove ownership and
current scope on every read, refuse corrupt or expired records, keep carried
evidence explicitly historical until it is rechecked, and bound its own growth.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from api.scope import Scope
from operations.autonomous_investigation import (
    configure_ledger_store,
    project_ledger_read_only,
)
from operations.investigation_thread_store import (
    ABSOLUTE_TTL_SECONDS,
    IDLE_TTL_SECONDS,
    MAX_TURNS,
    OBSERVATION_CURRENT,
    OBSERVATION_HISTORICAL,
    InvestigationThreadStore,
    ThreadNotFound,
    ThreadRevisionConflict,
    ThreadStoreUnavailable,
    investigation_thread_store,
    legacy_binding_document_name,
    thread_document_name,
)
from storage.onelake_documents import DocumentConflictError


class FakeDocuments:
    """Dictionary-backed stand-in for ``OneLakeDocumentStore``."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.fail_writes = False
        self.fail_reads = False
        self.conflict_writes = 0
        self.deleted: list[str] = []

    def read(self, name: str) -> dict[str, Any]:
        if self.fail_reads:
            raise RuntimeError("storage unavailable")
        # Deep-copy across the boundary so a stored document is a snapshot and
        # an in-memory mutation can never masquerade as a durable write.
        return deepcopy(self.documents.get(name, {}))

    def read_or_raise(self, name: str) -> dict[str, Any]:
        return self.read(name)

    def write(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        expected_revision: int,
    ) -> None:
        if self.fail_writes:
            raise RuntimeError("storage unavailable")
        if self.conflict_writes:
            self.conflict_writes -= 1
            raise DocumentConflictError("simulated contention")
        current = int(self.documents.get(name, {}).get("revision") or 0)
        if current != expected_revision:
            raise DocumentConflictError("revision conflict")
        self.documents[name] = deepcopy(payload)

    def delete(self, name: str) -> None:
        self.deleted.append(name)
        self.documents.pop(name, None)


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


SUB_A = Scope({"subscription": ["sub-a"]})
SUB_B = Scope({"subscription": ["sub-b"]})
BROAD = Scope({"subscription": ["sub-a", "sub-b"]})


def _turn(marker: str = "one") -> dict[str, Any]:
    return {
        "question": "Show inventory resources.",
        "status": "ok",
        "snapshot_id": f"snap-{marker}",
        "tool_results": [
            {
                "call_id": f"0:0:inventory:{marker}",
                "data": {"subscription": "sub-a"},
                "evidence": [{"evidence_id": f"ev-{marker}", "source": "inventory"}],
            }
        ],
        "citations": [{"citation_id": f"cite-{marker}", "source": "inventory"}],
    }


# ---------------------------------------------------------------------------
# Durability
# ---------------------------------------------------------------------------


def test_thread_survives_process_restart() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    store.append(thread.thread_id, "operator-a", SUB_A, _turn())

    restarted = InvestigationThreadStore(documents=documents)
    history = restarted.history(thread.thread_id, "operator-a", SUB_A)

    assert len(history) == 1
    assert history[0]["question"] == "Show inventory resources."


def test_each_thread_is_its_own_document() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    first = store.create("operator-a", SUB_A)
    second = store.create("operator-a", SUB_A)

    assert thread_document_name(first.thread_id) in documents.documents
    assert thread_document_name(second.thread_id) in documents.documents
    assert len(documents.documents) == 2


def test_durability_outcome_is_explicit() -> None:
    memory_only = InvestigationThreadStore()
    durable = InvestigationThreadStore(documents=FakeDocuments())

    assert memory_only.is_durable is False
    assert memory_only.create("operator-a", SUB_A).durability == "memory_only"
    assert durable.is_durable is True
    assert durable.create("operator-a", SUB_A).durability == "durable"


def test_configured_storage_write_outage_fails_closed() -> None:
    documents = FakeDocuments()
    documents.fail_writes = True
    store = InvestigationThreadStore(documents=documents)

    with pytest.raises(ThreadStoreUnavailable):
        store.create("operator-a", SUB_A)


def test_failed_durable_append_discards_uncommitted_mutation() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    documents.fail_writes = True

    with pytest.raises(ThreadStoreUnavailable):
        store.append(thread.thread_id, "operator-a", SUB_A, _turn())

    documents.fail_writes = False
    restarted = InvestigationThreadStore(documents=documents)
    assert restarted.history(thread.thread_id, "operator-a", SUB_A) == []


def test_configured_storage_read_outage_is_controlled_unavailable() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)

    documents.fail_reads = True
    restarted = InvestigationThreadStore(documents=documents)
    with pytest.raises(ThreadStoreUnavailable):
        restarted.authorize(thread.thread_id, "operator-a", SUB_A)


def test_continuity_prefers_strict_read_when_adapter_suppresses_errors() -> None:
    class SuppressingDocuments(FakeDocuments):
        def read(self, name: str) -> dict[str, Any]:
            if self.fail_reads:
                return {}
            return super().read(name)

        def read_or_raise(self, name: str) -> dict[str, Any]:
            if self.fail_reads:
                raise RuntimeError("transport unavailable")
            return super().read(name)

    documents = SuppressingDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    documents.fail_reads = True

    with pytest.raises(ThreadStoreUnavailable):
        store.authorize(thread.thread_id, "operator-a", SUB_A)
    with pytest.raises(ThreadStoreUnavailable):
        store.resolve_legacy_binding("legacy-session", "operator-a")


def test_corrupt_document_is_not_served_as_a_thread() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    documents.documents[thread_document_name(thread.thread_id)] = {
        "thread_id": "thr-" + "f" * 32,
        "principal_subject": "operator-a",
    }

    restarted = InvestigationThreadStore(documents=documents)
    with pytest.raises(ThreadNotFound) as raised:
        restarted.authorize(thread.thread_id, "operator-a", SUB_A)
    assert raised.value.reason == "corrupt"


def test_unparseable_document_is_not_served_as_a_thread() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    documents.documents[thread_document_name(thread.thread_id)] = {
        "thread_id": thread.thread_id,
        "principal_subject": "operator-a",
        "scope": {"not-a-dimension": ["x"]},
    }

    restarted = InvestigationThreadStore(documents=documents)
    with pytest.raises(ThreadNotFound) as raised:
        restarted.authorize(thread.thread_id, "operator-a", SUB_A)
    assert raised.value.reason == "corrupt"


# ---------------------------------------------------------------------------
# Principal and scope reauthorization
# ---------------------------------------------------------------------------


def test_principal_scoping_survives_rehydration() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    store.append(thread.thread_id, "operator-a", SUB_A, _turn())

    restarted = InvestigationThreadStore(documents=documents)
    with pytest.raises(ThreadNotFound) as raised:
        restarted.authorize(thread.thread_id, "operator-b", SUB_A)
    assert raised.value.reason == "principal_mismatch"


def test_widened_scope_is_refused_on_every_turn_and_read() -> None:
    store = InvestigationThreadStore()
    thread = store.create("operator-a", SUB_A)

    with pytest.raises(ThreadNotFound) as authorize_failure:
        store.authorize(thread.thread_id, "operator-a", BROAD)
    assert authorize_failure.value.reason == "scope_widened"
    with pytest.raises(ThreadNotFound):
        store.append(thread.thread_id, "operator-a", BROAD, _turn())
    with pytest.raises(ThreadNotFound):
        store.history(thread.thread_id, "operator-a", BROAD)


def test_narrowing_intersects_and_never_widens_back() -> None:
    store = InvestigationThreadStore()
    thread = store.create("operator-a", BROAD)
    narrowed = store.append(thread.thread_id, "operator-a", SUB_A, _turn())

    assert narrowed.scope.to_dict() == {"subscription": ["sub-a"]}
    with pytest.raises(ThreadNotFound):
        store.authorize(thread.thread_id, "operator-a", BROAD)


# ---------------------------------------------------------------------------
# Bounds, expiry, and optimistic concurrency
# ---------------------------------------------------------------------------


def test_exactly_twelve_turns_are_retained() -> None:
    store = InvestigationThreadStore(documents=FakeDocuments())
    thread = store.create("operator-a", SUB_A)
    for index in range(MAX_TURNS + 5):
        store.append(thread.thread_id, "operator-a", SUB_A, _turn(str(index)))

    history = store.history(thread.thread_id, "operator-a", SUB_A)

    assert MAX_TURNS == 12
    assert len(history) == 12
    assert history[0]["snapshot_id"] == "snap-5"
    assert history[-1]["snapshot_id"] == "snap-16"


def test_idle_expiry_is_one_hour() -> None:
    clock = FakeClock()
    store = InvestigationThreadStore(documents=FakeDocuments(), clock=clock)
    thread = store.create("operator-a", SUB_A)

    clock.advance(IDLE_TTL_SECONDS - 1)
    assert store.authorize(thread.thread_id, "operator-a", SUB_A)

    clock.advance(IDLE_TTL_SECONDS + 1)
    with pytest.raises(ThreadNotFound) as raised:
        store.authorize(thread.thread_id, "operator-a", SUB_A)
    assert IDLE_TTL_SECONDS == 60 * 60
    assert raised.value.reason == "expired_idle"


def test_absolute_expiry_is_twenty_four_hours_despite_activity() -> None:
    clock = FakeClock()
    store = InvestigationThreadStore(documents=FakeDocuments(), clock=clock)
    thread = store.create("operator-a", SUB_A)

    # Keep the thread continuously active; idle expiry can never fire.
    for _ in range(48):
        clock.advance(IDLE_TTL_SECONDS / 2)
        try:
            store.append(thread.thread_id, "operator-a", SUB_A, _turn())
        except ThreadNotFound as expired:
            assert expired.reason == "expired_absolute"
            break
    else:  # pragma: no cover - defensive
        pytest.fail("absolute expiry never fired")

    assert ABSOLUTE_TTL_SECONDS == 24 * 60 * 60


def test_expired_documents_are_removed_by_bounded_cleanup() -> None:
    clock = FakeClock()
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents, clock=clock)
    threads = [store.create("operator-a", SUB_A) for _ in range(5)]

    clock.advance(ABSOLUTE_TTL_SECONDS + 1)
    removed = store.cleanup(max_removals=2)

    assert removed == 2
    assert len(documents.deleted) == 2
    assert store.cleanup(max_removals=100) == 3
    assert documents.documents == {}
    for thread in threads:
        with pytest.raises(ThreadNotFound):
            store.authorize(thread.thread_id, "operator-a", SUB_A)


def test_stale_revision_raises_an_explicit_conflict() -> None:
    store = InvestigationThreadStore(documents=FakeDocuments())
    thread = store.create("operator-a", SUB_A)
    store.append(thread.thread_id, "operator-a", SUB_A, _turn(), expected_revision=0)

    with pytest.raises(ThreadRevisionConflict) as raised:
        store.append(
            thread.thread_id,
            "operator-a",
            SUB_A,
            _turn("two"),
            expected_revision=0,
        )

    assert raised.value.current_revision == 1
    assert store.append(
        thread.thread_id,
        "operator-a",
        SUB_A,
        _turn("two"),
        expected_revision=1,
    ).revision == 2


def test_concurrent_replicas_see_the_same_revision_after_restart() -> None:
    documents = FakeDocuments()
    first = InvestigationThreadStore(documents=documents)
    thread = first.create("operator-a", SUB_A)
    first.append(thread.thread_id, "operator-a", SUB_A, _turn())

    second = InvestigationThreadStore(documents=documents)
    assert second.authorize(thread.thread_id, "operator-a", SUB_A).revision == 1
    with pytest.raises(ThreadRevisionConflict):
        second.append(
            thread.thread_id,
            "operator-a",
            SUB_A,
            _turn("two"),
            expected_revision=0,
        )


def test_stale_replica_cannot_overwrite_a_concurrent_turn() -> None:
    documents = FakeDocuments()
    first = InvestigationThreadStore(documents=documents)
    thread = first.create("operator-a", SUB_A)
    second = InvestigationThreadStore(documents=documents)
    second.authorize(thread.thread_id, "operator-a", SUB_A)

    second.append(
        thread.thread_id,
        "operator-a",
        SUB_A,
        _turn("second"),
        expected_revision=0,
    )
    with pytest.raises(ThreadRevisionConflict) as raised:
        first.append(
            thread.thread_id,
            "operator-a",
            SUB_A,
            _turn("first"),
            expected_revision=0,
        )

    assert raised.value.current_revision == 1
    restarted = InvestigationThreadStore(documents=documents)
    history = restarted.history(thread.thread_id, "operator-a", SUB_A)
    assert [item["snapshot_id"] for item in history] == ["snap-second"]


def test_document_revision_is_distinct_from_thread_revision() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    store.authorize(thread.thread_id, "operator-a", SUB_A)
    store.append(thread.thread_id, "operator-a", SUB_A, _turn())

    document = documents.documents[thread_document_name(thread.thread_id)]
    assert document["revision"] > document["thread_revision"]
    assert document["thread_revision"] == 1


def test_ledger_store_configuration_also_wires_thread_durability() -> None:
    documents = FakeDocuments()
    configure_ledger_store(documents)
    try:
        assert investigation_thread_store().documents is documents
    finally:
        configure_ledger_store(None)


def test_ledger_store_configuration_rejects_adapter_without_thread_cas() -> None:
    class LedgerOnlyDocuments:
        def read(self, name: str) -> dict[str, Any]:
            return {}

        def put(self, name: str, payload: dict[str, Any]) -> None:
            return None

    with pytest.raises(TypeError, match="thread compare-and-swap"):
        configure_ledger_store(LedgerOnlyDocuments())


def test_history_returns_fresh_state_after_one_persistence_conflict() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    store.append(thread.thread_id, "operator-a", SUB_A, _turn())
    documents.conflict_writes = 1

    history = store.history(thread.thread_id, "operator-a", SUB_A)

    assert [item["snapshot_id"] for item in history] == ["snap-one"]


def test_authorize_fails_closed_after_sustained_touch_contention() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    documents.conflict_writes = 2

    with pytest.raises(ThreadRevisionConflict):
        store.authorize(thread.thread_id, "operator-a", SUB_A)


def test_legacy_session_binding_survives_replica_restart() -> None:
    documents = FakeDocuments()
    first = InvestigationThreadStore(documents=documents)
    thread = first.create("operator-a", SUB_A)

    assert (
        first.bind_legacy_session("legacy-session", "operator-a", thread.thread_id)
        == thread.thread_id
    )
    restarted = InvestigationThreadStore(documents=documents)
    assert (
        restarted.resolve_legacy_binding("legacy-session", "operator-a")
        == thread.thread_id
    )
    binding = documents.documents[
        legacy_binding_document_name("legacy-session", "operator-a")
    ]
    assert "operator-a" not in str(binding)
    assert "legacy-session" not in str(binding)


def test_legacy_session_binding_is_first_writer_wins_across_replicas() -> None:
    documents = FakeDocuments()
    first = InvestigationThreadStore(documents=documents)
    second = InvestigationThreadStore(documents=documents)
    first_thread = first.create("operator-a", SUB_A)
    second_thread = second.create("operator-a", SUB_A)

    winner = first.bind_legacy_session(
        "legacy-session", "operator-a", first_thread.thread_id
    )
    observed = second.bind_legacy_session(
        "legacy-session", "operator-a", second_thread.thread_id
    )

    assert observed == winner == first_thread.thread_id


def test_legacy_binding_read_outage_fails_closed() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    documents.fail_reads = True

    with pytest.raises(ThreadStoreUnavailable):
        store.resolve_legacy_binding("legacy-session", "operator-a")


def test_legacy_binding_write_outage_does_not_return_local_candidate() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    documents.fail_writes = True

    with pytest.raises(ThreadStoreUnavailable):
        store.bind_legacy_session("legacy-session", "operator-a", thread.thread_id)

    documents.fail_writes = False
    assert store.resolve_legacy_binding("legacy-session", "operator-a") is None


def test_legacy_binding_unresolved_cross_replica_conflict_fails_closed() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    documents.conflict_writes = 1

    with pytest.raises(ThreadRevisionConflict):
        store.bind_legacy_session("legacy-session", "operator-a", thread.thread_id)


def test_legacy_binding_invalidation_outage_preserves_durable_binding() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    thread = store.create("operator-a", SUB_A)
    store.bind_legacy_session("legacy-session", "operator-a", thread.thread_id)
    documents.fail_writes = True

    with pytest.raises(ThreadStoreUnavailable):
        store.forget_legacy_binding("legacy-session", "operator-a")

    documents.fail_writes = False
    assert (
        store.resolve_legacy_binding("legacy-session", "operator-a")
        == thread.thread_id
    )


def test_expired_legacy_binding_can_be_replaced() -> None:
    documents = FakeDocuments()
    store = InvestigationThreadStore(documents=documents)
    expired = store.create("operator-a", SUB_A)
    replacement = store.create("operator-a", SUB_A)
    store.bind_legacy_session("legacy-session", "operator-a", expired.thread_id)

    store.forget_legacy_binding("legacy-session", "operator-a")
    rebound = store.bind_legacy_session(
        "legacy-session", "operator-a", replacement.thread_id
    )

    assert rebound == replacement.thread_id


# ---------------------------------------------------------------------------
# Snapshot identity and evidence aging
# ---------------------------------------------------------------------------


def test_snapshot_identity_is_retained_per_turn() -> None:
    store = InvestigationThreadStore(documents=FakeDocuments())
    thread = store.create("operator-a", SUB_A)
    store.append(thread.thread_id, "operator-a", SUB_A, _turn("alpha"))

    restarted = InvestigationThreadStore(documents=FakeDocuments())
    restarted._threads.clear()
    history = store.history(thread.thread_id, "operator-a", SUB_A)

    assert history[0]["snapshot_id"] == "snap-alpha"


def test_carried_evidence_is_historical_until_rechecked() -> None:
    store = InvestigationThreadStore(documents=FakeDocuments())
    thread = store.create("operator-a", SUB_A)
    store.append(thread.thread_id, "operator-a", SUB_A, _turn("one"))
    store.append(thread.thread_id, "operator-a", SUB_A, _turn("two"))

    history = store.history(thread.thread_id, "operator-a", SUB_A)

    assert history[0]["observation_status"] == OBSERVATION_HISTORICAL
    assert history[1]["observation_status"] == OBSERVATION_CURRENT
    assert (
        history[0]["tool_results"][0]["evidence"][0]["observation_status"]
        == OBSERVATION_HISTORICAL
    )
    assert history[0]["citations"][0]["observation_status"] == OBSERVATION_HISTORICAL
    assert (
        history[1]["tool_results"][0]["evidence"][0]["observation_status"]
        == OBSERVATION_CURRENT
    )


def test_beginning_a_new_turn_ages_previously_carried_evidence() -> None:
    store = InvestigationThreadStore(documents=FakeDocuments())
    thread = store.create("operator-a", SUB_A)
    store.append(thread.thread_id, "operator-a", SUB_A, _turn("one"))

    store.authorize(thread.thread_id, "operator-a", SUB_A)
    history = store.history(thread.thread_id, "operator-a", SUB_A)

    assert history[0]["observation_status"] == OBSERVATION_HISTORICAL


def test_scope_narrowing_still_redacts_wider_historical_turns() -> None:
    store = InvestigationThreadStore(documents=FakeDocuments())
    thread = store.create("operator-a", BROAD)
    store.append(
        thread.thread_id,
        "operator-a",
        BROAD,
        {"status": "ok", "tool_results": [{"data": {"secret": "b-only"}}]},
    )
    store.append(thread.thread_id, "operator-a", SUB_A, _turn())

    history = store.history(thread.thread_id, "operator-a", SUB_A)

    assert history[0]["status"] == "historical_scope_restricted"
    assert history[0]["observation_status"] == OBSERVATION_HISTORICAL
    assert "b-only" not in str(history)


# ---------------------------------------------------------------------------
# Opportunistic legacy import
# ---------------------------------------------------------------------------


def test_active_legacy_conversation_is_imported_without_mutating_it() -> None:
    store = InvestigationThreadStore(documents=FakeDocuments())
    legacy_turns = [
        {"question": "first", "status": "ok"},
        {"question": "second", "status": "ok"},
    ]
    original = deepcopy(legacy_turns)

    thread = store.import_legacy_turns("operator-a", SUB_A, legacy_turns)
    history = store.history(thread.thread_id, "operator-a", SUB_A)

    assert legacy_turns == original
    assert [turn["question"] for turn in history] == ["first", "second"]
    assert all(turn["imported_from"] == "legacy_conversation" for turn in history)
    assert history[-1]["observation_status"] == OBSERVATION_HISTORICAL


def test_legacy_import_is_bounded_and_skips_empty_conversations() -> None:
    store = InvestigationThreadStore(documents=FakeDocuments())

    assert store.import_legacy_turns("operator-a", SUB_A, []) is None

    thread = store.import_legacy_turns(
        "operator-a",
        SUB_A,
        [{"question": str(index)} for index in range(30)],
    )
    history = store.history(thread.thread_id, "operator-a", SUB_A)

    assert len(history) == MAX_TURNS
    assert history[0]["question"] == "18"


def test_old_ledger_read_projection_never_mutates_the_stored_ledger() -> None:
    ledger = {
        "ledger_id": "mai-abc123456789",
        "created_by": "operator-a",
        "findings": [{"finding_id": "f1", "summary": "kept"}],
        "tool_calls": [{"tool": "inventory_resources", "status": "ok"}],
    }
    original = deepcopy(ledger)

    projection = project_ledger_read_only(ledger)

    assert ledger == original
    assert projection["observation_status"] == OBSERVATION_HISTORICAL
    assert projection["findings"][0]["observation_status"] == OBSERVATION_HISTORICAL
    assert projection["tool_calls"][0]["observation_status"] == OBSERVATION_HISTORICAL
    projection["findings"][0]["summary"] = "tampered"
    assert ledger == original
