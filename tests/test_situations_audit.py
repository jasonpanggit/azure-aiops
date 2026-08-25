import pytest

from situations.store import AppendOnlyAuditLog
from storage.delta_writer import DeltaWriter


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


def test_delta_audit_append_uses_stable_event_id_and_rejects_mutation(tmp_path) -> None:
    row = {
        "tenant_id": "tenant",
        "subscription_id": "sub-a",
        "resource_id": "event-resource",
        "timestamp": "2026-08-25T02:00:00Z",
        "change_version": "version-1",
        "ingestion_run_id": "run-1",
        "event_id": "audit://stable",
        "actor": "system:ingestion",
        "action": "evidence.ingested",
    }
    writer = DeltaWriter()
    table = tmp_path / "audit"

    writer.write(table, [row], mode="append", key_columns=("event_id",))
    duplicate = writer.write(table, [dict(row)], mode="append", key_columns=("event_id",))

    assert duplicate.skipped
    with pytest.raises(ValueError, match="mutation"):
        writer.write(
            table,
            [{**row, "actor": "spoofed"}],
            mode="append",
            key_columns=("event_id",),
        )
