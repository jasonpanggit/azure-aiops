"""Durable single-dispatch, safe-boundary stop and exact-scope job contracts."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from api.scope import SCOPE_DIMENSIONS, Scope
from operations.investigation_jobs import (
    JOB_TTL_SECONDS,
    InvestigationBudgetExpired,
    InvestigationExecutionControl,
    InvestigationJobStore,
    InvestigationStopped,
    JobConflict,
    JobNotFound,
    JobUnavailable,
    job_document_name,
)
from storage.onelake_documents import OneLakeDocumentStore

JOB = f"job-{'a' * 32}"
WORKER = "b" * 32
SCOPE = Scope.from_mapping({key: [f"{key}-a"] for key in SCOPE_DIMENSIONS})
NOW = 1_800_000_000.0


def accepted(tmp_path):
    store = InvestigationJobStore(OneLakeDocumentStore(tmp_path), clock=lambda: NOW)
    record, created = store.accept("owner", JOB, SCOPE, objective="Private objective", timeout_seconds=8.0)
    assert created and record["revision"] == 1
    return store


def test_restarted_store_reads_exact_admission_without_dispatch_or_renewal(tmp_path):
    store = accepted(tmp_path)
    documents = OneLakeDocumentStore(tmp_path)
    before = documents.read_or_raise(job_document_name("owner", JOB))
    restarted = InvestigationJobStore(documents, clock=lambda: NOW + 600)
    record, created = restarted.accept("owner", JOB, SCOPE, objective="Private objective", timeout_seconds=8.0)
    assert not created
    assert record["status"] == "accepted_outcome_unconfirmed"
    assert record["liveness"] == "not_established"
    assert record["durability"] == "durable"
    assert "worker_id" not in record and "principal_subject" not in record
    assert documents.read_or_raise(job_document_name("owner", JOB)) == before
    assert store.read("owner", JOB, SCOPE) == record


@pytest.mark.parametrize("dimension", SCOPE_DIMENSIONS)
def test_every_scope_dimension_is_exact_for_all_reads_and_mutations(tmp_path, dimension):
    store = accepted(tmp_path)
    different = SCOPE.with_dimension(dimension, ["other"])
    for scope in (different, Scope.unrestricted()):
        with pytest.raises(JobNotFound):
            store.read("owner", JOB, scope)
        with pytest.raises(JobNotFound):
            store.request_stop("owner", JOB, scope)
        with pytest.raises(JobNotFound):
            store.claim("owner", JOB, scope, WORKER)
        with pytest.raises(JobConflict):
            store.accept("owner", JOB, scope, objective="Private objective", timeout_seconds=8.0)
    with pytest.raises(JobNotFound):
        store.read("foreign", JOB, SCOPE)


@pytest.mark.parametrize("objective,timeout", [("Changed", 8.0), ("Private objective", 9.0)])
def test_same_identity_never_dispatches_changed_payload(tmp_path, objective, timeout):
    store = accepted(tmp_path)
    with pytest.raises(JobConflict):
        store.accept("owner", JOB, SCOPE, objective=objective, timeout_seconds=timeout)


def test_cross_process_admission_and_claim_each_have_only_one_winner(tmp_path):
    def admit(_):
        store = InvestigationJobStore(OneLakeDocumentStore(tmp_path), clock=lambda: NOW)
        try:
            _, created = store.accept("owner", JOB, SCOPE, objective="Question", timeout_seconds=8.0)
            return created
        except JobConflict:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(admit, range(16))) == 1

    def claim(index):
        store = InvestigationJobStore(OneLakeDocumentStore(tmp_path), clock=lambda: NOW)
        try:
            store.claim("owner", JOB, SCOPE, f"{index:032x}")
            return True
        except (JobConflict, JobUnavailable):
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(claim, range(1, 17))) == 1
    restarted = InvestigationJobStore(OneLakeDocumentStore(tmp_path), clock=lambda: NOW + 600)
    assert restarted.read("owner", JOB, SCOPE)["status"] == "running"
    with pytest.raises(JobConflict):
        restarted.claim("owner", JOB, SCOPE, WORKER)


@pytest.mark.parametrize("stop_before_claim", [True, False])
def test_stop_is_only_requested_until_worker_acknowledges_safe_boundary(tmp_path, stop_before_claim):
    store = accepted(tmp_path)
    if stop_before_claim:
        requested = store.request_stop("owner", JOB, SCOPE)
        assert requested["status"] == "accepted_outcome_unconfirmed"
    store.claim("owner", JOB, SCOPE, WORKER)
    if not stop_before_claim:
        store.checkpoint("owner", JOB, SCOPE, WORKER, "tool:network_topology")
    requested = store.request_stop("owner", JOB, SCOPE)
    assert requested["status"] == "running" and requested["stop_requested"]
    assert store.request_stop("owner", JOB, SCOPE) == requested
    with pytest.raises(InvestigationStopped):
        store.checkpoint("owner", JOB, SCOPE, WORKER, "next_tool")
    store.finish("owner", JOB, SCOPE, WORKER, status="stopped", stage="stopped_at_safe_boundary")
    record = store.read("owner", JOB, SCOPE)
    assert record["status"] == "stopped" and not record["ledger_id"]
    assert store.request_stop("owner", JOB, SCOPE) == record


def test_late_stop_does_not_hide_a_ledger_already_completed(tmp_path):
    store = accepted(tmp_path)
    store.claim("owner", JOB, SCOPE, WORKER)
    store.request_stop("owner", JOB, SCOPE)
    store.finish("owner", JOB, SCOPE, WORKER, status="completed", ledger_id="mai-exact", stage="ledger_retained")
    record = store.read("owner", JOB, SCOPE)
    assert record["status"] == "completed" and record["ledger_id"] == "mai-exact"
    assert record["stop_requested"]
    assert store.request_stop("owner", JOB, SCOPE) == record
    with pytest.raises(JobConflict):
        store.checkpoint("owner", JOB, SCOPE, WORKER, "another_tool")
    with pytest.raises(JobConflict):
        store.finish("owner", JOB, SCOPE, WORKER, status="failed", stage="cannot_replace")


def test_foreign_worker_cannot_change_progress_or_result(tmp_path):
    store = accepted(tmp_path)
    store.claim("owner", JOB, SCOPE, WORKER)
    with pytest.raises(JobConflict):
        store.checkpoint("owner", JOB, SCOPE, "c" * 32, "tool")
    with pytest.raises(JobConflict):
        store.finish("owner", JOB, SCOPE, "c" * 32, status="completed", ledger_id="mai-foreign", stage="done")


def test_expiry_never_renews_or_permits_redispatch(tmp_path):
    store = accepted(tmp_path)
    expired = InvestigationJobStore(store.documents, clock=lambda: NOW + JOB_TTL_SECONDS + 1)
    with pytest.raises(JobNotFound):
        expired.read("owner", JOB, SCOPE)
    with pytest.raises(JobNotFound):
        expired.request_stop("owner", JOB, SCOPE)
    with pytest.raises(JobConflict):
        expired.accept("owner", JOB, SCOPE, objective="Private objective", timeout_seconds=8.0)


@pytest.mark.parametrize("job_id", ["", "../private", "job-a", f"job-{'A' * 32}", f"job-{'a' * 33}"])
def test_invalid_identity_never_touches_storage(tmp_path, job_id):
    store = InvestigationJobStore(OneLakeDocumentStore(tmp_path))
    with pytest.raises(JobNotFound):
        store.accept("owner", job_id, SCOPE, objective="Question", timeout_seconds=8.0)
    assert not list(tmp_path.glob("investigation-jobs/*.json"))


@pytest.mark.parametrize("corruption", [
    {"principal_subject": "foreign"}, {"job_id": f"job-{'c' * 32}"},
    {"status": "completed"}, {"worker_id": "c" * 32},
    {"scope": {"unknown": ["x"]}}, {"updated_at": NOW - 1},
    {"updated_at": NOW + 61}, {"status": "stopped"},
    {"ledger_id": "mai-unconfirmed"}, {"timeout_seconds": float("nan")},
])
def test_corrupt_records_are_unavailable_not_missing_or_recreated(tmp_path, corruption):
    store = accepted(tmp_path)
    name = job_document_name("owner", JOB)
    raw = store.documents.read_or_raise(name)
    store.documents.write(name, {**raw, **corruption}, expected_revision=raw["revision"])
    with pytest.raises(JobUnavailable):
        store.read("owner", JOB, SCOPE)
    with pytest.raises(JobUnavailable):
        store.accept("owner", JOB, SCOPE, objective="Private objective", timeout_seconds=8.0)


def test_unconfigured_storage_never_accepts_memory_only_dispatch():
    store = InvestigationJobStore(None)
    with pytest.raises(JobUnavailable):
        store.accept("owner", JOB, SCOPE, objective="Question", timeout_seconds=8.0)


def test_existing_empty_object_is_corrupt_not_missing_or_eligible_for_redispatch(tmp_path):
    documents = OneLakeDocumentStore(tmp_path)
    documents.create_only(job_document_name("owner", JOB), {})
    store = InvestigationJobStore(documents)
    with pytest.raises(JobUnavailable):
        store.read("owner", JOB, SCOPE)
    with pytest.raises(JobUnavailable):
        store.accept("owner", JOB, SCOPE, objective="Question", timeout_seconds=8.0)


def test_storage_failure_during_checkpoint_stops_further_work(tmp_path, monkeypatch):
    store = accepted(tmp_path)
    store.claim("owner", JOB, SCOPE, WORKER)
    monkeypatch.setattr(store.documents, "write", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unavailable")))
    with pytest.raises(JobUnavailable):
        store.checkpoint("owner", JOB, SCOPE, WORKER, "tool")


def test_execution_control_honors_stop_before_budget_and_never_kills_a_call(tmp_path):
    store = accepted(tmp_path)
    store.claim("owner", JOB, SCOPE, WORKER)
    control = InvestigationExecutionControl(store, "owner", JOB, SCOPE, WORKER, 8.0)
    control.checkpoint("before_tool")
    control.deadline = 0
    with pytest.raises(InvestigationBudgetExpired):
        control.checkpoint("after_tool")
    store.request_stop("owner", JOB, SCOPE)
    with pytest.raises(InvestigationStopped):
        control.checkpoint("after_tool")


def test_canonical_worker_checks_stop_after_tool_before_any_more_tools_or_synthesis(tmp_path, monkeypatch):
    """Isolate checkpoint placement; authorization is covered by route/policy suites."""
    from types import SimpleNamespace

    from operations import maf_orchestrator
    from operations.investigation_thread_store import InvestigationThreadStore
    from operations.orchestration_contract import (
        COVERAGE_CITATION_ID,
        CandidatePlan,
        EvidenceSnapshotV2,
        InvestigationRequest,
        SnapshotCoverage,
        SpecialistStep,
        ToolCallCandidate,
    )
    from operations.orchestration_service import OrchestrationService
    from operations.tools import ToolResult

    store = accepted(tmp_path)
    store.claim("owner", JOB, SCOPE, WORKER)
    control = InvestigationExecutionControl(store, "owner", JOB, SCOPE, WORKER, 30.0)
    request = InvestigationRequest(
        question="Show network topology", requested_scope=SCOPE.to_dict(),
        snapshot=EvidenceSnapshotV2(
            page_kind="network", page_id="network-topology",
            coverage=SnapshotCoverage(visible_count=0, total_count=0, complete=False),
        ),
    )
    candidate = CandidatePlan(steps=[SpecialistStep(
        specialist_id="network", tool_calls=[
            ToolCallCandidate(tool=name, arguments={}, citation_ids=[COVERAGE_CITATION_ID])
            for name in ("network_topology", "firewall_nsg_gaps")
        ],
    )], estimated_tokens=0, max_wall_seconds=5)
    calls = []
    def execute(name, *args, **kwargs):
        calls.append(name)
        store.request_stop("owner", JOB, SCOPE)
        return ToolResult(status="ok", data={"fixture": True})
    service = OrchestrationService(
        planner=lambda _: candidate, executor=execute, thread_store=InvestigationThreadStore(),
    )
    monkeypatch.setattr(maf_orchestrator, "authorize_canonical_execution", lambda **_: None)
    monkeypatch.setattr(service, "_synthesize", lambda *args, **kwargs: pytest.fail("No synthesis after stop"))
    with pytest.raises(InvestigationStopped):
        service.execute(
            request, context=SimpleNamespace(), principal_subject="owner",
            effective_scope=SCOPE, execution_control=control,
        )
    assert calls == ["network_topology"]
