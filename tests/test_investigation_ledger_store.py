"""Durability guarantees for the investigation ledger.

Investigation ledgers record the evidence and human decisions behind actions
taken against production infrastructure. Before this suite the store was an
in-memory ``OrderedDict`` that was lost on every replica restart and evicted
the oldest 1000th entry, so an approval could disappear silently. These tests
pin the properties an audit trail has to hold.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from operations.autonomous_investigation import (
    InvestigationLedgerStore,
    _ledger_document_name,
)


class FakeDocuments:
    """Dictionary-backed stand-in for ``OneLakeDocumentStore``."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.fail_writes = False
        self.fail_reads = False

    def read(self, name: str) -> dict[str, Any]:
        if self.fail_reads:
            raise RuntimeError("storage unavailable")
        # Deep-copy on both sides of the boundary so a stored document is a
        # snapshot, not a live reference. Sharing the dict would let in-place
        # mutations of a cached ledger appear to have been persisted when no
        # write ever happened, hiding a lost-approval bug.
        return deepcopy(self.documents.get(name, {}))

    def put(self, name: str, payload: dict[str, Any]) -> None:
        if self.fail_writes:
            raise RuntimeError("storage unavailable")
        self.documents[name] = deepcopy(payload)


def ledger(ledger_id: str = "mai-abc123456789", *, created_by: str = "operator@example.com") -> dict[str, Any]:
    return {
        "ledger_id": ledger_id,
        "created_by": created_by,
        "status": "completed",
        "decisions": [],
        "approvals": [],
    }


def test_ledger_survives_process_restart() -> None:
    """The property the in-memory store could not provide."""
    documents = FakeDocuments()
    InvestigationLedgerStore(documents=documents).add(ledger())

    # A new store is a new replica: it shares storage but no memory.
    restarted = InvestigationLedgerStore(documents=documents)
    assert restarted.ledgers == {}

    recovered = restarted.get("mai-abc123456789", "operator@example.com")
    assert recovered is not None
    assert recovered["ledger_id"] == "mai-abc123456789"


def test_durable_ledgers_are_never_lost_to_eviction() -> None:
    """Retention is indefinite: eviction bounds memory, not the audit trail."""
    documents = FakeDocuments()
    store = InvestigationLedgerStore(max_entries=2, documents=documents)
    for index in range(5):
        store.add(ledger(f"mai-{index:012d}"))

    assert len(store.ledgers) == 2, "memory stays bounded"
    # The first ledger was evicted from memory but is still auditable.
    assert store.get("mai-000000000000", "operator@example.com") is not None


def test_approvals_are_persisted() -> None:
    """An approval that vanishes on restart is worse than no approval."""
    documents = FakeDocuments()
    store = InvestigationLedgerStore(documents=documents)
    store.add(ledger())
    store.record_decision(
        "mai-abc123456789", "operator@example.com", "approve_plan", {"plan": "restart-vm"}
    )

    restarted = InvestigationLedgerStore(documents=documents)
    recovered = restarted.get("mai-abc123456789", "operator@example.com")
    assert recovered is not None
    assert [entry["action"] for entry in recovered["approvals"]] == ["approve_plan"]


def test_principal_scoping_survives_rehydration() -> None:
    """Reloading from storage must not widen who can read a ledger."""
    documents = FakeDocuments()
    InvestigationLedgerStore(documents=documents).add(ledger())

    restarted = InvestigationLedgerStore(documents=documents)
    assert restarted.get("mai-abc123456789", "intruder@example.com") is None


def test_corrupt_document_is_not_served_as_a_ledger() -> None:
    """``read`` returns {} for a corrupt document; that must not become a hit.

    The document store deliberately treats unreadable blobs as empty so a bad
    blob cannot take the API down. For a cache that is right. For an audit
    record, returning a truncated or mismatched document would be worse than
    reporting nothing, so identity is re-checked after the read.

    The stored document deliberately carries the *correct* ``created_by``: a
    document that failed the principal check would be rejected anyway, and
    would not exercise the identity check at all.
    """
    documents = FakeDocuments()
    documents.documents[_ledger_document_name("mai-abc123456789")] = {
        "ledger_id": "mai-different",
        "created_by": "operator@example.com",
        "decisions": [],
        "approvals": [],
    }

    store = InvestigationLedgerStore(documents=documents)
    assert store.get("mai-abc123456789", "operator@example.com") is None


def test_storage_outage_does_not_fail_the_investigation() -> None:
    """A failed audit write is logged, never raised into the operator's run."""
    documents = FakeDocuments()
    documents.fail_writes = True
    store = InvestigationLedgerStore(documents=documents)

    store.add(ledger())  # must not raise

    assert store.get("mai-abc123456789", "operator@example.com") is not None


def test_read_outage_is_a_miss_not_a_crash() -> None:
    documents = FakeDocuments()
    documents.fail_reads = True
    store = InvestigationLedgerStore(documents=documents)

    assert store.get("mai-abc123456789", "operator@example.com") is None


def test_without_a_document_store_behaviour_is_unchanged() -> None:
    """Local development keeps the previous bounded in-memory semantics."""
    store = InvestigationLedgerStore(max_entries=2)
    assert store.is_durable is False
    for index in range(3):
        store.add(ledger(f"mai-{index:012d}"))

    assert store.get("mai-000000000000", "operator@example.com") is None
    assert store.get("mai-000000000002", "operator@example.com") is not None


def test_each_ledger_is_its_own_document() -> None:
    """One document per ledger keeps writes contention-free across replicas."""
    documents = FakeDocuments()
    store = InvestigationLedgerStore(documents=documents)
    store.add(ledger("mai-000000000001"))
    store.add(ledger("mai-000000000002"))

    assert sorted(documents.documents) == [
        "ledgers/mai-000000000001.json",
        "ledgers/mai-000000000002.json",
    ]
