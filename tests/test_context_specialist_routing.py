"""Routing tests for contextual (page drawer) specialist selection.

The drawer used to route on ``page_kind`` alone, so the question text was
never consulted: asking "what changed recently?" on the Network page ran the
network specialist and nothing else, and the operator got network findings
back regardless of what they asked.

Selection is now page-anchored *and* question-aware. These tests pin both
halves of that contract, plus the safety properties that make it acceptable
to widen: a bounded specialist count, deterministic selection, and no
admission of the tool-less synthesis agent.
"""

from __future__ import annotations

from operations.autonomous_investigation import (
    AGENTS,
    MAX_CONTEXT_SPECIALISTS,
    _select_context_specialists,
)
from operations.maf_orchestrator import select_specialists_for_turn

PAGE_SPECIALISTS = {
    "network": ("network",),
    "vulnerability": ("vulnerability", "patch"),
    "incident": ("incident", "change"),
    "governance": ("governance",),
}


def _select(page_kind: str, question: str) -> list[str]:
    return _select_context_specialists(
        page_kind=page_kind,
        question=question,
        page_specialists=PAGE_SPECIALISTS,
    )


def test_the_page_specialist_always_leads() -> None:
    """The drawer must keep answering as the specialist for the current page."""
    for question in (
        "What changed recently?",
        "Who owns this?",
        "How do I remediate it?",
        "",
    ):
        assert _select("network", question)[0] == "network", question


def test_a_change_question_on_the_network_page_reaches_the_change_specialist() -> None:
    """The exact case that made the drawer feel broken."""
    assert _select("network", "What changed recently that could explain this?") == [
        "network",
        "change",
    ]


def test_a_governance_question_on_the_network_page_reaches_governance() -> None:
    assert "governance" in _select("network", "Who owns this and is there an approval?")


def test_a_topic_free_question_stays_on_the_page_specialist() -> None:
    """No keyword match must not silently widen the investigation."""
    assert _select("network", "What depends on demo-vnet?") == ["network"]


def test_selection_never_exceeds_the_specialist_budget() -> None:
    """A question naming every topic must still respect the bound.

    The page mapping is the adversarial part: a page that maps to more
    specialists than the budget allows must be truncated. Relying on the
    keyword loop alone would not exercise this, because that loop stops at the
    bound on its own -- the cap on the returned list is what protects against
    an over-broad page mapping.
    """
    everything = (
        "network firewall cve exploit patch kb incident outage change "
        "deployment owner policy remediate rollback executive summary"
    )
    for page_kind in PAGE_SPECIALISTS:
        selected = _select(page_kind, everything)
        assert len(selected) <= MAX_CONTEXT_SPECIALISTS, page_kind

    overloaded = _select_context_specialists(
        page_kind="everything_page",
        question=everything,
        page_specialists={
            "everything_page": (
                "network",
                "vulnerability",
                "patch",
                "incident",
                "change",
                "governance",
                "remediation",
            )
        },
    )
    assert len(overloaded) == MAX_CONTEXT_SPECIALISTS


def test_the_synthesis_agent_is_never_selected() -> None:
    """executive_summary has no tools and depends on every other specialist."""
    assert "executive_summary" not in _select(
        "network", "Give me an executive summary decision"
    )


def test_no_specialist_is_selected_twice() -> None:
    """A page specialist that also matches the question must not run twice."""
    selected = _select("network", "Show me the network topology and firewall gaps")
    assert len(selected) == len(set(selected))


def test_an_unknown_page_kind_falls_back_to_the_question_alone() -> None:
    """An unmapped page must degrade to topic routing, not to nothing."""
    assert _select("brand_new_page", "Which CVEs are exploitable?") == ["vulnerability"]


def test_selection_is_deterministic() -> None:
    """Same inputs, same specialists, in the same order, every time."""
    question = "What changed and who owns it?"
    assert len({tuple(_select("network", question)) for _ in range(10)}) == 1


def test_every_selected_id_is_a_real_agent() -> None:
    known = {agent.id for agent in AGENTS}
    selected = _select("network", "cve patch change owner remediate")
    assert set(selected) <= known


def test_maf_orchestrator_routes_question_intent_before_page_anchor() -> None:
    """MAF mode makes Operations Copilot own intent selection across pages."""
    decision = select_specialists_for_turn(
        page_kind="network",
        question="Who owns demo-vnet and what approval policy applies?",
        page_specialists=PAGE_SPECIALISTS,
        catalog=AGENTS,
        limit=MAX_CONTEXT_SPECIALISTS,
    )

    assert decision.strategy == "question_first"
    assert decision.selected_ids == ("network", "governance")
    assert decision.runtime in {"microsoft-agent-framework", "maf-compatible"}


def test_maf_orchestrator_uses_page_only_when_question_has_no_specialist_intent() -> None:
    decision = select_specialists_for_turn(
        page_kind="network",
        question="Summarize what I am looking at",
        page_specialists=PAGE_SPECIALISTS,
        catalog=AGENTS,
        limit=MAX_CONTEXT_SPECIALISTS,
    )

    assert decision.strategy == "page_fallback"
    assert decision.selected_ids == ("network",)


def test_maf_mode_is_default_unless_deterministic_rollback_requested(monkeypatch) -> None:
    from operations.maf_orchestrator import maf_mode_enabled

    monkeypatch.delenv("AIOPS_AGENT_ORCHESTRATION_MODE", raising=False)
    assert maf_mode_enabled() is True

    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "maf")
    assert maf_mode_enabled() is True

    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "deterministic")
    assert maf_mode_enabled() is False
