import pytest

from situations.store import AppendOnlyAuditLog


def test_audit_log_is_append_only_and_attributed() -> None:
    log = AppendOnlyAuditLog()
    event = log.record(
        actor="system:ingestion",
        action="evidence.ingested",
        timestamp="2026-08-25T02:00:00Z",
        situation_id="situation://one",
        source_references=["arg-1"],
        scope_snapshot={"subscription": ["sub-a"]},
    )
    assert log.append(event) == event
    with pytest.raises(ValueError, match="immutable"):
        log.append(event.model_copy(update={"actor": "spoofed"}))
    assert log.rows()[0]["scope_snapshot"] == {"subscription": ["sub-a"]}
