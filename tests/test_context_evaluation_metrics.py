"""The contextual investigation must report quality metrics it can measure.

Autonomous investigations reported ``groundedness`` and ``tool_correctness``,
but the contextual path -- the one that actually serves the page drawer --
reported only counters and wall clock. So the path an operator uses every day
was the one whose answer quality could not be measured, only asserted. That is
how a prompt bug survived long enough to make every specialist look broken.

These tests pin the definitions, so the two paths stay comparable and a
regression in evidence-backing shows up as a number.
"""

from __future__ import annotations

from api.auth import StaticTokenAuthenticator
from api.dependencies import ApiContext
from api.rbac import Authorizer, Grant, Principal
from api.scope import Scope
from api.telemetry import ApiTelemetry
from onboarding.service import SubscriptionOnboardingService
from operations.autonomous_investigation import run_context_investigation
from operations.page_context import PageSnapshot

TOKEN = "test-token-long-enough-to-pass"


def _context(tmp_path):
    return ApiContext(
        onboarding=SubscriptionOnboardingService(tmp_path / "aiops"),
        authenticator=StaticTokenAuthenticator(
            {TOKEN: Principal(subject="operator@example.com", grants=(Grant("admin"),))}
        ),
        authorizer=Authorizer(),
        telemetry=ApiTelemetry(),
    )


def _snapshot(question: str = "What depends on demo-vnet?") -> PageSnapshot:
    return PageSnapshot.model_validate({
        "page_kind": "network",
        "page_id": "network-topology",
        "question": question,
        "scope": {"declared": {"subscription": ["sub-prod"]}},
    })


def _run(tmp_path, question: str = "What depends on demo-vnet?"):
    return run_context_investigation(
        _snapshot(question),
        context=_context(tmp_path),
        scope=Scope.from_mapping({"subscription": ["sub-prod"]}),
        principal_subject="operator@example.com",
    )


def test_contextual_evaluation_reports_groundedness(tmp_path) -> None:
    """Without this the drawer's answer quality cannot be scored at all."""
    evaluation = _run(tmp_path)["evaluation"]
    assert "groundedness" in evaluation
    if evaluation["groundedness"] is not None:
        assert 0.0 <= evaluation["groundedness"] <= 1.0


def test_contextual_evaluation_reports_tool_correctness(tmp_path) -> None:
    evaluation = _run(tmp_path)["evaluation"]
    assert "tool_correctness" in evaluation
    if evaluation["tool_correctness"] is not None:
        assert 0.0 <= evaluation["tool_correctness"] <= 1.0


def test_groundedness_is_scored_over_specialist_findings(tmp_path) -> None:
    """The score must reflect what the specialists found, not what was posted.

    Top-level `findings` are derived from the submitted page snapshot, so a
    caller that posts no evidence rows leaves it empty. Scoring that would
    report 0.0 for an investigation whose specialists returned fully
    evidence-backed answers -- measuring the caller, not the agent.
    """
    ledger = _run(tmp_path)
    specialist_findings = [
        f for run in ledger["agent_runs"] for f in run.get("findings", [])
    ]
    expected = (
        round(
            len([f for f in specialist_findings if f.get("evidence_count", 0) > 0])
            / len(specialist_findings),
            3,
        )
        if specialist_findings
        else None
    )
    assert ledger["evaluation"]["groundedness"] == expected


def test_an_unmeasured_run_reports_none_not_zero(tmp_path) -> None:
    """No findings means unmeasured, which is not the same as ungrounded.

    Collapsing both to 0.0 makes a run that produced nothing look like a
    failing one, which is the misreading these metrics exist to prevent.
    """
    from operations.autonomous_investigation import _quality_metrics

    assert _quality_metrics([], [])["groundedness"] is None
    assert _quality_metrics([], [])["tool_correctness"] is None
    assert _quality_metrics([{"findings": []}], [])["groundedness"] is None


def test_tool_correctness_matches_the_undenied_fraction(tmp_path) -> None:
    ledger = _run(tmp_path)
    calls = ledger["tool_calls"]
    expected = (
        round(sum(c.get("status") != "denied" for c in calls) / len(calls), 3)
        if calls
        else None
    )
    assert ledger["evaluation"]["tool_correctness"] == expected


def test_tool_correctness_actually_penalises_denied_calls(tmp_path, monkeypatch) -> None:
    """A denied call must lower the score, not be counted as correct.

    Recomputing the fraction from the ledger cannot catch a metric that
    ignores ``denied`` entirely: the test and the implementation move
    together and both report 1.0. This forces real denied calls through the
    real investigation, so a metric that ignores them fails.
    """
    import operations.autonomous_investigation as investigation
    from operations.tools import ToolResult

    real_call_tool = investigation.call_tool
    seen: list[str] = []

    def deny_every_other(tool_name, *args, **kwargs):
        seen.append(tool_name)
        if len(seen) % 2 == 0:
            return ToolResult(status="denied", data={}, warning="scope denied")
        return real_call_tool(tool_name, *args, **kwargs)

    monkeypatch.setattr(investigation, "call_tool", deny_every_other)

    ledger = _run(tmp_path, "Are there CVEs and who owns this?")
    calls = ledger["tool_calls"]
    denied = [c for c in calls if c.get("status") == "denied"]
    assert denied, "fixture must produce at least one denied call to be meaningful"

    score = ledger["evaluation"]["tool_correctness"]
    assert score < 1.0, f"denied calls must lower the score, got {score}"
    assert score == round((len(calls) - len(denied)) / len(calls), 3)


def test_the_existing_counters_are_preserved(tmp_path) -> None:
    """Adding metrics must not drop the ones consumers already read."""
    evaluation = _run(tmp_path)["evaluation"]
    for key in ("step_count", "tool_calls", "specialists", "wall_clock_ms",
                "hidden_reasoning_exposed"):
        assert key in evaluation, key


def test_metrics_are_present_even_when_no_tools_resolve(tmp_path) -> None:
    """A context with no providers must still score, not divide by zero.

    This is the common case in a fresh tenant, and a crash here would take out
    the drawer rather than degrade it.
    """
    evaluation = _run(tmp_path, "Who owns this and is there an approval?")["evaluation"]
    assert "groundedness" in evaluation
    assert "tool_correctness" in evaluation
    assert "findings_scored" in evaluation
