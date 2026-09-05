"""``RemediationExecutionStore.list_due_for_verification`` scheduling rules.

Durable-state-only: every behavior here is provable from disk alone (no
in-memory scheduler), matching Recommendation 3's Verification Lifecycle
decision that a process restart must lose no in-flight verification state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from intelligence.remediation.execution_store import RemediationExecutionStore

TARGET_ID = "/subscriptions/sub-1/resourcegroups/rg-prod/providers/microsoft.compute/virtualmachines/vm-payments"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _patch_snapshot(**overrides) -> dict:
    snapshot = {
        "target_id": TARGET_ID,
        "patch_ids": ["KB600001", "KB600002"],
        "target_kind": "Azure VM",
        "operation": "install_patches",
        "action_version": "v1",
        "snapshot_hash": "hash-1",
    }
    snapshot.update(overrides)
    return snapshot


def _create_running(store: RemediationExecutionStore, plan_id: str, **snapshot_overrides) -> dict:
    record, _ = store.create_or_get(
        plan_id,
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot=_patch_snapshot(**snapshot_overrides),
        now=NOW,
    )
    return store.transition(
        record["execution_id"],
        expected_revision=int(record["revision"]),
        expected_status="queued",
        status="running",
        actor="operator@example.com",
        provider_job_id="https://management.azure.com/op/1",
        provider_submitted=True,
        now=NOW,
    )


def test_running_with_empty_next_verification_at_is_always_due():
    store = RemediationExecutionStore()
    record = _create_running(store, "RMP-SCHED-1")
    assert record["next_verification_at"] == ""

    due = store.list_due_for_verification(now=NOW)

    assert any(row["execution_id"] == record["execution_id"] for row in due)


def test_running_with_future_next_verification_at_is_excluded():
    store = RemediationExecutionStore()
    record = _create_running(store, "RMP-SCHED-2")
    future = (NOW + timedelta(minutes=10)).isoformat()
    store.transition(
        record["execution_id"],
        expected_revision=int(record["revision"]),
        expected_status="running",
        status="running",
        actor="execution-verifier",
        next_verification_at=future,
        now=NOW,
    )

    due = store.list_due_for_verification(now=NOW)

    assert not any(row["execution_id"] == record["execution_id"] for row in due)


def test_failed_with_submission_ambiguous_failure_class_is_due():
    store = RemediationExecutionStore()
    record = _create_running(store, "RMP-SCHED-3")
    store.transition(
        record["execution_id"],
        expected_revision=int(record["revision"]),
        expected_status="running",
        status="failed",
        actor="execution-verifier",
        outcome="failed",
        failure_details="Azure Resource Manager was unreachable",
        failure_class="submission_ambiguous",
        now=NOW,
    )

    due = store.list_due_for_verification(now=NOW)

    assert any(row["execution_id"] == record["execution_id"] for row in due)


def test_failed_with_other_failure_class_is_never_due():
    store = RemediationExecutionStore()
    record = _create_running(store, "RMP-SCHED-4")
    store.transition(
        record["execution_id"],
        expected_revision=int(record["revision"]),
        expected_status="running",
        status="failed",
        actor="execution-verifier",
        outcome="failed",
        failure_details="Refused by RBAC",
        failure_class="provider_rejected",
        now=NOW,
    )

    due = store.list_due_for_verification(now=NOW)

    assert not any(row["execution_id"] == record["execution_id"] for row in due)


def test_succeeded_patch_record_with_pending_reconciliation_is_due():
    store = RemediationExecutionStore()
    record = _create_running(store, "RMP-SCHED-5")
    store.transition(
        record["execution_id"],
        expected_revision=int(record["revision"]),
        expected_status="running",
        status="succeeded",
        actor="execution-verifier",
        outcome="succeeded",
        verified_state="Succeeded",
        now=NOW,
    )

    due = store.list_due_for_verification(now=NOW)

    assert any(row["execution_id"] == record["execution_id"] for row in due)


def test_succeeded_with_terminal_reconciliation_status_is_never_due_again():
    store = RemediationExecutionStore()
    record = _create_running(store, "RMP-SCHED-6")
    succeeded = store.transition(
        record["execution_id"],
        expected_revision=int(record["revision"]),
        expected_status="running",
        status="succeeded",
        actor="execution-verifier",
        outcome="succeeded",
        verified_state="Succeeded",
        now=NOW,
    )
    for terminal_status in ("reconciled_clean", "reconciled_incomplete", "unreconciled"):
        store.transition(
            succeeded["execution_id"],
            expected_revision=int(store.get(succeeded["execution_id"])["revision"]),
            expected_status="succeeded",
            status="succeeded",
            actor="execution-verifier",
            evidence_reconciliation={
                "status": terminal_status,
                "kbs_cleared": [],
                "kbs_remaining": [],
                "assessed_at": NOW.isoformat(),
            },
            now=NOW,
        )
        due = store.list_due_for_verification(now=NOW)
        assert not any(
            row["execution_id"] == succeeded["execution_id"] for row in due
        ), f"expected not due for reconciliation status {terminal_status!r}"


def test_succeeded_defender_configuration_or_empty_patch_ids_is_never_due():
    store = RemediationExecutionStore()

    defender_record = store.create_or_get(
        "RMP-SCHED-7",
        requested_by="operator@example.com",
        approved_by="approver@example.com",
        execution_snapshot={
            "target_id": TARGET_ID,
            "patch_ids": [],
            "target_kind": "",
            "operation": "configure_defender",
            "action_version": "v1",
            "snapshot_hash": "hash-defender",
            "snapshot_kind": "defender_configuration",
            "desired_properties": {},
            "request": {},
            "precondition": {},
            "prior_properties": {},
        },
        now=NOW,
    )[0]
    store.transition(
        defender_record["execution_id"],
        expected_revision=int(defender_record["revision"]),
        expected_status="queued",
        status="succeeded",
        actor="operator@example.com",
        outcome="succeeded",
        now=NOW,
    )

    empty_patch_record = _create_running(store, "RMP-SCHED-8", patch_ids=[])
    store.transition(
        empty_patch_record["execution_id"],
        expected_revision=int(empty_patch_record["revision"]),
        expected_status="running",
        status="succeeded",
        actor="execution-verifier",
        outcome="succeeded",
        now=NOW,
    )

    due_ids = {row["execution_id"] for row in store.list_due_for_verification(now=NOW)}

    assert defender_record["execution_id"] not in due_ids
    assert empty_patch_record["execution_id"] not in due_ids


def test_legacy_record_without_new_fields_reads_back_with_safe_defaults(tmp_path):
    path = tmp_path / "state" / "remediation_executions.json"
    store = RemediationExecutionStore(path=path)
    record = _create_running(store, "RMP-SCHED-9")
    execution_id = record["execution_id"]

    payload = json.loads(path.read_text(encoding="utf-8"))
    for execution in payload["executions"]:
        if execution["execution_id"] != execution_id:
            continue
        for field in (
            "verification_deadline_at",
            "next_verification_at",
            "verification_attempts",
            "verification_evidence",
            "evidence_reconciliation",
        ):
            execution.pop(field, None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    reread_store = RemediationExecutionStore(path=path)
    reread = reread_store.get(execution_id)

    assert reread["verification_deadline_at"] == ""
    assert reread["next_verification_at"] == ""
    assert reread["verification_attempts"] == 0
    assert reread["verification_evidence"] == {}
    assert reread["evidence_reconciliation"] == {
        "status": "",
        "kbs_cleared": [],
        "kbs_remaining": [],
        "assessed_at": "",
    }

    # Must not raise -- and since status is "running" with no
    # next_verification_at, it is due (immediate-first-poll case).
    due_ids = {row["execution_id"] for row in reread_store.list_due_for_verification(now=NOW)}
    assert execution_id in due_ids
