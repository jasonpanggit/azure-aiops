"""Offline admission, snapshot binding, persistence and authorization proofs."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from test_api_remediation_execution import (
    ADMIN_TOKEN,
    READER_TOKEN,
    SCOPED_OPERATOR_TOKEN,
    _approve,
    _auth,
    _client,
    _patch_recovery_plan,
)

from intelligence.remediation.approval_decisions import execution_snapshot_hash
from intelligence.remediation.execution_store import RemediationExecutionStore
from intelligence.remediation.rollout import RolloutError, RolloutMember, RolloutTerms
from operations.defender_configuration import configuration_snapshot_hash
from operations.patching.adapters import RecordingPatchExecutionAdapter

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def snapshot(index=1):
    row = {
        "target_id": f"/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-{index}",
        "patch_ids": ["KB600001"], "target_kind": "Azure VM",
        "operation": "install_patches", "action_version": f"version-{index}",
    }
    return {**row, "snapshot_hash": execution_snapshot_hash(row)}


def terms(**changes):
    return RolloutTerms(
        **{
            "title": "Reviewed target waves", "window_start": (NOW - timedelta(hours=1)).isoformat(),
            "window_end": (NOW + timedelta(hours=1)).isoformat(),
            "require_reconciled_evidence": True,
            "members": [RolloutMember(
                plan_id=f"plan-{index}", target_id=snapshot(index)["target_id"],
                action_version=f"version-{index}", snapshot_hash=snapshot(index)["snapshot_hash"],
                patch_ids=snapshot(index)["patch_ids"],
                wave=index, scope_attributes={"subscription": "sub-1"},
            ) for index in (1, 2)], **changes,
        },
    )


def create(store, **changes):
    return store.create_rollout(terms(**changes), expected_revision=store.rollout_collection(now=NOW)["revision"], actor="operator", now=NOW)


def control(store, record, action="open", wave=1, **changes):
    return store.control_rollout(record["rollout_id"], expected_revision=record["revision"], action=action, wave=wave, actor="operator", now=changes.get("now", NOW))


def claim(store, index=1):
    return store.create_or_get(
        f"plan-{index}", requested_by="operator", approved_by="approver",
        approval_decision_id=f"decision-{index}",
        execution_snapshot=store.bind_rollout_snapshot(f"plan-{index}", snapshot(index)), now=NOW,
    )[0]


def finish(store, execution, status, **fields):
    current = store.get(execution["execution_id"])
    return store.transition(
        current["execution_id"], expected_revision=current["revision"],
        expected_status=current["status"], status=status, actor="recording-verifier",
        now=NOW, **fields,
    )


def test_durable_terms_open_pause_and_recorded_progress_without_dispatch(tmp_path):
    path = tmp_path / "state/executions.json"
    store = RemediationExecutionStore(path)
    row = create(store)
    assert row["opened_wave"] == 0
    assert row["targets"][0]["admission_reason"] == "rollout_wave_not_open"
    restored = RemediationExecutionStore(path)
    row = control(restored, row)
    assert row["opened_wave"] == 1
    execution = claim(restored)
    assert execution["status"] == "queued"
    row = control(restored, row, "pause", 0)
    with pytest.raises(RolloutError, match="paused"):
        restored.check_rollout_admission("plan-1", execution["execution_snapshot"], now=NOW)
    row = control(restored, row, "resume", 0)
    assert row["targets"][0]["execution_id"] == execution["execution_id"]
    assert RemediationExecutionStore(path).rollout_collection(now=NOW)["rollouts"] == [row]


@pytest.mark.parametrize("changes", [
    {"window_start": "2026-10-17T00:00:00"},
    {"window_end": "not-a-date"},
    {"window_end": (NOW - timedelta(days=1)).isoformat()},
    {"window_end": (NOW + timedelta(days=2)).isoformat()},
    {"members": []},
    {"members": [terms().members[0]] * 2},
    {"members": [terms().members[1]]},
    {"require_reconciled_evidence": "true"},
])
def test_invalid_terms_fail_closed(changes):
    with pytest.raises(ValidationError):
        terms(**changes)


def test_snapshot_binding_rejects_old_approval_and_every_altered_term():
    store = RemediationExecutionStore()
    row = create(store)
    original = snapshot()
    bound = store.bind_rollout_snapshot("plan-1", original)
    assert bound["snapshot_hash"] != original["snapshot_hash"]
    assert bound["rollout"]["terms_hash"] == row["terms_hash"]
    assert bound["snapshot_hash"] == execution_snapshot_hash(bound)
    with pytest.raises(RolloutError, match="Approval"):
        store.validate_rollout_binding("plan-1", original)
    for key, value in {"wave": 2, "terms_hash": "a" * 64, "rollout_id": "RMO-" + "b" * 32}.items():
        changed = copy.deepcopy(bound)
        changed["rollout"][key] = value
        changed["snapshot_hash"] = execution_snapshot_hash(changed)
        with pytest.raises(RolloutError):
            store.validate_rollout_binding("plan-1", changed)
    changed = {**original, "patch_ids": ["KB600002"]}
    with pytest.raises(RolloutError, match="differs"):
        store.bind_rollout_snapshot("plan-1", changed)


def test_all_terms_affect_hash_and_legacy_both_family_hashes_are_preserved():
    baseline = terms()
    for changes in [
        {"window_end": (NOW + timedelta(hours=2)).isoformat()},
        {"title": "Other explicit terms"}, {"require_reconciled_evidence": False},
        {"members": [baseline.members[0], baseline.members[1].model_copy(update={"wave": 1})]},
    ]:
        assert terms(**changes).digest() != baseline.digest()
    configuration = {**snapshot(), "snapshot_kind": "defender_configuration", "patch_ids": []}
    old = configuration_snapshot_hash(configuration)
    assert execution_snapshot_hash(configuration) == old
    configuration["rollout"] = {"rollout_id": "RMO-" + "a" * 32, "terms_hash": "b" * 64, "wave": 1}
    assert execution_snapshot_hash(configuration) == configuration_snapshot_hash(configuration) != old


@pytest.mark.parametrize("when", [NOW - timedelta(hours=1, seconds=1), NOW + timedelta(hours=1)])
def test_window_rejects_before_start_and_at_exclusive_end(when):
    store = RemediationExecutionStore()
    row = create(store)
    with pytest.raises(RolloutError) as error:
        control(store, row, now=when)
    assert error.value.reason == "rollout_window_closed"
    assert store.list_all() == []


def test_order_and_prior_provider_and_evidence_success_are_real_gates():
    store = RemediationExecutionStore()
    row = create(store)
    with pytest.raises(RolloutError):
        control(store, row, wave=2)
    row = control(store, row)
    with pytest.raises(RolloutError, match="provider success"):
        control(store, row, wave=2)
    first = claim(store)
    finish(store, first, "succeeded")
    with pytest.raises(RolloutError, match="refreshed evidence"):
        control(store, row, wave=2)
    store.update(first["execution_id"], evidence_reconciliation={"status": "reconciled_clean"})
    row = control(store, row, wave=2)
    second = claim(store, 2)
    assert second["execution_snapshot"]["rollout"]["wave"] == 2
    with pytest.raises(RolloutError, match="explicitly open"):
        store.check_rollout_admission("plan-1", first["execution_snapshot"], now=NOW)


def test_failure_stops_new_work_but_allows_explicit_bounded_recovery():
    combined = [member.model_copy(update={"wave": 1}) for member in terms().members]
    store = RemediationExecutionStore()
    row = control(store, create(store, members=combined))
    first = claim(store)
    finish(store, first, "failed", provider_submitted=True)
    with pytest.raises(RolloutError) as error:
        claim(store, 2)
    assert error.value.reason == "rollout_stopped"
    first = store.get(first["execution_id"])
    retry = store.claim_retry(first["execution_id"], expected_revision=first["revision"], actor="operator", max_attempts=3, now=NOW)
    with pytest.raises(RolloutError, match="failed"):
        claim(store, 2)
    finish(store, retry, "succeeded")
    assert claim(store, 2)["status"] == "queued"
    assert row["opened_wave"] == 1


def test_cas_duplicate_plan_and_reapproval_cannot_repeat_a_rollout_target(tmp_path):
    path = tmp_path / "executions.json"
    store = RemediationExecutionStore(path)
    row = create(store)
    with pytest.raises(RolloutError) as error:
        RemediationExecutionStore(path).create_rollout(terms(), expected_revision=0, actor="other", now=NOW)
    assert error.value.reason == "rollout_revision_conflict"
    with pytest.raises(RolloutError, match="already"):
        create(store)
    control(store, row)
    with pytest.raises(RolloutError, match="Reload"):
        control(RemediationExecutionStore(path), row)
    first = claim(store)
    finish(store, first, "failed")
    same, claimed = store.create_or_get(
        "plan-1", requested_by="other", approved_by="other-approver",
        approval_decision_id="new-approval", execution_snapshot=first["execution_snapshot"], now=NOW,
    )
    assert not claimed and same["execution_id"] == first["execution_id"]


def http_setup(tmp_path):
    adapter = RecordingPatchExecutionAdapter()
    client, _, store = _client(tmp_path, adapter=adapter)
    context = client.app.state.context
    context.rollout_store_provider = lambda: store
    plan = _patch_recovery_plan(client)
    preview = client.get(f"/api/v1/remediation/plans/{plan['plan_id']}/preview", headers=_auth()).json()["data"]["execution_snapshot"]
    payload = {
        "title": "Explicit test wave", "window_start": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "window_end": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "targets": [{"plan_id": plan["plan_id"], "preview_snapshot_hash": preview["snapshot_hash"], "wave": 1}],
        "expected_revision": 0,
    }
    return client, context, plan, payload, adapter


def test_http_exact_snapshot_new_approval_required_and_scope_read_is_provider_free(tmp_path):
    client, context, plan, payload, adapter = http_setup(tmp_path)
    _approve(context.remediation_provider(), plan)
    response = client.post("/api/v1/remediation/rollouts", headers=_auth(), json=payload)
    assert response.status_code == 200, response.text
    row = response.json()["data"]
    denied = client.post(f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth())
    assert denied.status_code == 409 and denied.json()["error"]["details"]["reason"] == "rollout_approval_stale"
    context.remediation_provider = lambda: pytest.fail("Stored reads must not generate/acquire plans")
    result = client.get("/api/v1/remediation/rollouts", headers=_auth(READER_TOKEN))
    assert result.status_code == 200 and result.json()["data"]["rollouts"][0]["can_manage"] is False
    result = client.get("/api/v1/remediation/rollouts?subscription=outside", headers=_auth(ADMIN_TOKEN))
    assert result.json()["data"]["rollouts"] == []
    denied = client.post(f"/api/v1/remediation/rollouts/{row['rollout_id']}/admission", headers=_auth(SCOPED_OPERATOR_TOKEN), json={"action": "open", "wave": 1, "expected_revision": 0})
    assert denied.status_code == 404
    assert adapter.submissions == []


@pytest.mark.parametrize("mutation", [
    {"expected_revision": True}, {"targets": []}, {"extra": "unsafe"},
    {"window_start": "2026-10-17T00:00:00"},
])
def test_http_invalid_inputs_never_reserve_targets(tmp_path, mutation):
    client, context, _, payload, _ = http_setup(tmp_path)
    response = client.post("/api/v1/remediation/rollouts", headers=_auth(), json={**payload, **mutation})
    assert response.status_code in {400, 422}
    assert context.rollout_store_provider().rollout_collection()["rollouts"] == []


def test_http_fresh_approved_binding_still_needs_explicit_open_before_one_dispatch(tmp_path):
    client, context, plan, payload, adapter = http_setup(tmp_path)
    row = client.post("/api/v1/remediation/rollouts", headers=_auth(), json=payload).json()["data"]
    plan_id = plan["plan_id"]
    preview = client.get(f"/api/v1/remediation/plans/{plan_id}/preview", headers=_auth()).json()["data"]["execution_snapshot"]
    assert preview["rollout"]["terms_hash"] == row["terms_hash"]
    assert preview["snapshot_hash"] != payload["targets"][0]["preview_snapshot_hash"]
    for requirement in plan["approval_requirements"]:
        approved = client.post(f"/api/v1/remediation-plans/{plan_id}/decisions", headers=_auth(ADMIN_TOKEN), json={
            "decision": "approved", "reason": "Reviewed immutable terms and target",
            "action_version": plan["action_version"], "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "preview_snapshot_hash": preview["snapshot_hash"],
            "role_id": requirement.get("role_id") or requirement["role"],
        })
        assert approved.status_code == 201, approved.text
    denied = client.post(f"/api/v1/remediation/plans/{plan_id}/execute", headers=_auth())
    assert denied.status_code == 409, denied.text
    assert denied.json()["error"]["details"]["reason"] == "rollout_wave_not_open"
    assert adapter.submissions == []
    opened = client.post(f"/api/v1/remediation/rollouts/{row['rollout_id']}/admission", headers=_auth(), json={"action": "open", "wave": 1, "expected_revision": 0})
    assert opened.status_code == 200, opened.text
    assert adapter.submissions == []
    result = client.post(f"/api/v1/remediation/plans/{plan_id}/execute", headers=_auth())
    assert result.status_code == 202, result.text
    assert result.json()["data"]["status"] == "running"
    assert result.json()["data"]["execution_snapshot"]["rollout"] == preview["rollout"]
    assert len(adapter.submissions) == 1
    repeated = client.post(f"/api/v1/remediation/plans/{plan_id}/execute", headers=_auth())
    assert repeated.status_code == 202 and len(adapter.submissions) == 1
    assert context.rollout_store_provider().rollout_collection()["rollouts"][0]["targets"][0]["status"] == "running"


@pytest.mark.parametrize("dimension", [
    "subscription", "subscription_connection", "business_service", "application",
    "environment", "owner", "support_team", "region", "criticality",
])
def test_stored_scope_read_filters_all_nine_dimensions(tmp_path, dimension):
    client, _, _, payload, _ = http_setup(tmp_path)
    assert client.post("/api/v1/remediation/rollouts", headers=_auth(), json=payload).status_code == 200
    response = client.get(f"/api/v1/remediation/rollouts?{dimension}=outside", headers=_auth(ADMIN_TOKEN))
    assert response.status_code == 200 and response.json()["data"]["rollouts"] == []


def test_hard_bounds_and_corrupt_terms_are_not_silently_discarded(tmp_path):
    path = tmp_path / "executions.json"
    store = RemediationExecutionStore(path)
    with pytest.raises(ValidationError):
        terms(members=[terms().members[0]] * 21)
    with pytest.raises(ValidationError):
        terms(members=[terms().members[0].model_copy(update={"wave": 6})])
    create(store)
    import json
    state = json.loads(path.read_text())
    state["rollouts"][0]["terms"]["window_end"] = (NOW + timedelta(hours=2)).isoformat()
    path.write_text(json.dumps(state))
    with pytest.raises(ValidationError, match="digest"):
        RemediationExecutionStore(path).rollout_collection(now=NOW)


def test_stored_selection_is_recovered_as_input_but_source_drift_still_fails(tmp_path):
    store = RemediationExecutionStore(tmp_path / "state.json")
    create(store)
    assert store.rollout_patch_selection("plan-1") == ["KB600001"]
    assert store.rollout_patch_selection("unknown-plan") is None
    changed = {**snapshot(), "patch_ids": ["KB600002"]}
    with pytest.raises(RolloutError, match="differs"):
        store.bind_rollout_snapshot("plan-1", changed)


def test_http_storage_failure_is_explicit_and_does_not_return_empty_success(tmp_path):
    client, context, _, _, _ = http_setup(tmp_path)
    def unavailable():
        raise OSError("Synthetic storage outage")
    context.rollout_store_provider = unavailable
    response = client.get("/api/v1/remediation/rollouts", headers=_auth())
    assert response.status_code == 503
    assert "data" not in response.json()


def test_retirement_allows_new_terms_without_reviving_old_or_legacy_approvals(tmp_path):
    store = RemediationExecutionStore(tmp_path / "state.json")
    first = create(store)
    old_approved = store.bind_rollout_snapshot("plan-1", snapshot())
    retired = control(store, first, "retire", 0)
    assert retired["retired"] and retired["paused"]
    assert store.bind_rollout_snapshot("plan-1", snapshot()) == snapshot()
    assert store.rollout_patch_selection("plan-1") is None
    for approval in [old_approved, snapshot()]:
        with pytest.raises(RolloutError) as error:
            store.validate_rollout_binding("plan-1", approval)
        assert error.value.reason == "rollout_retired"
    second = create(store, title="Replacement reviewed terms")
    assert second["rollout_id"] != first["rollout_id"]
    assert len(RemediationExecutionStore(tmp_path / "state.json").rollout_collection(now=NOW)["rollouts"]) == 2
    with pytest.raises(RolloutError, match="Approval"):
        store.validate_rollout_binding("plan-1", old_approved)
    control(store, second)
    assert claim(store)["execution_snapshot"]["rollout"]["rollout_id"] == second["rollout_id"]
    with pytest.raises(RolloutError) as error:
        control(store, retired, "resume", 0)
    assert error.value.reason == "rollout_retired"


def test_started_rollouts_cannot_be_retired_even_after_a_failed_claim():
    store = RemediationExecutionStore()
    row = control(store, create(store))
    first = claim(store)
    finish(store, first, "failed", provider_submitted=False)
    with pytest.raises(RolloutError) as error:
        control(store, row, "retire", 0)
    assert error.value.reason == "rollout_already_started"
    assert not store.rollout_collection(now=NOW)["rollouts"][0]["retired"]


def test_collection_count_and_serialized_size_are_hard_rejection_bounds():
    store = RemediationExecutionStore()
    row = create(store)
    with pytest.raises(ValueError, match="bounded collection"):
        store._validated_rollouts([row] * 101)
    large = terms(members=[
        RolloutMember(
            plan_id=f"large-{index}", target_id=snapshot(index)["target_id"],
            action_version="v1", snapshot_hash=snapshot(index)["snapshot_hash"], wave=1,
            scope_attributes={f"dimension-{key}": "s" * 512 for key in range(9)},
        ) for index in range(20)
    ])
    record = create(RemediationExecutionStore(), **large.model_dump())
    with pytest.raises(ValueError, match="MiB"):
        store._validated_rollouts([record] * 20)


def test_http_retirement_redeclares_same_plan_but_never_restores_pre_rollout_approval(tmp_path):
    client, context, plan, payload, adapter = http_setup(tmp_path)
    _approve(context.remediation_provider(), plan)
    first = client.post("/api/v1/remediation/rollouts", headers=_auth(), json=payload).json()["data"]
    retired = client.post(f"/api/v1/remediation/rollouts/{first['rollout_id']}/admission", headers=_auth(), json={"action": "retire", "wave": 0, "expected_revision": 0})
    assert retired.status_code == 200, retired.text
    denied = client.post(f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth())
    assert denied.status_code == 409 and denied.json()["error"]["details"]["reason"] == "rollout_retired"
    payload["expected_revision"] = context.rollout_store_provider().rollout_collection()["revision"]
    replacement = client.post("/api/v1/remediation/rollouts", headers=_auth(), json=payload)
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["data"]["rollout_id"] != first["rollout_id"]
    denied = client.post(f"/api/v1/remediation/plans/{plan['plan_id']}/execute", headers=_auth())
    assert denied.status_code == 409 and denied.json()["error"]["details"]["reason"] == "rollout_approval_stale"
    assert adapter.submissions == []


def test_retirement_and_claim_cannot_both_win_across_store_instances(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "executions.json"
    store = RemediationExecutionStore(path)
    row = control(store, create(store))
    barrier = Barrier(2)
    def compete(retire):
        other = RemediationExecutionStore(path)
        barrier.wait(timeout=5)
        try:
            if retire:
                control(other, row, "retire", 0)
            else:
                claim(other)
            return "retired" if retire else "claimed"
        except RolloutError as exc:
            return exc.reason
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(compete, [True, False]))
    assert set(outcomes) in [
        {"retired", "rollout_retired"},
        {"claimed", "rollout_already_started"},
    ]
    stored = RemediationExecutionStore(path).rollout_collection(now=NOW)["rollouts"][0]
    assert not (stored["retired"] and stored["targets"][0]["execution_id"])


def test_succeeded_targets_can_receive_new_terms_without_reusing_old_execution():
    store = RemediationExecutionStore()
    first = control(store, create(store))
    execution = claim(store)
    finish(store, execution, "succeeded")
    old_snapshot = execution["execution_snapshot"]
    control(store, first, "retire", 0)
    second = control(store, create(store))
    fresh = claim(store)
    assert fresh["execution_id"] != execution["execution_id"]
    assert fresh["execution_snapshot"]["rollout"]["rollout_id"] == second["rollout_id"]
    assert store.get(execution["execution_id"])["status"] == "succeeded"
    with pytest.raises(RolloutError, match="Approval"):
        store.validate_rollout_binding("plan-1", old_snapshot)
