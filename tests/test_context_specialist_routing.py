"""Routing tests for contextual (page drawer) specialist selection.

The drawer used to route on ``page_kind`` alone, so the question text was
never consulted: asking "what changed recently?" on the Network page ran the
network specialist and nothing else, and the operator got network findings
back regardless of what they asked.

Selection is page-anchored *and* question-aware. Question intent may narrow
the manifest's page owners or use an explicit reviewed cross-domain grant, but
it may never add an unrelated globally matched specialist.
"""

from __future__ import annotations

import pytest

from operations.autonomous_investigation import (
    AGENTS,
    MAX_CONTEXT_SPECIALISTS,
    _select_context_specialists,
)
from operations.maf_orchestrator import select_specialists_for_turn
from operations.specialist_manifest import load_specialist_manifest

PAGE_SPECIALISTS = load_specialist_manifest().page_mapping_projection()


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


def test_a_change_question_on_the_network_page_stays_page_safe() -> None:
    assert _select("network", "What changed recently that could explain this?") == [
        "network"
    ]


def test_a_governance_question_on_the_network_page_uses_the_reviewed_grant() -> None:
    assert _select("network", "Who owns this and is there an approval?") == [
        "network",
        "governance",
    ]


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


def test_an_unknown_page_kind_fails_closed() -> None:
    assert _select("brand_new_page", "Which CVEs are exploitable?") == []


def test_selection_is_deterministic() -> None:
    """Same inputs, same specialists, in the same order, every time."""
    question = "What changed and who owns it?"
    assert len({tuple(_select("network", question)) for _ in range(10)}) == 1


def test_every_selected_id_is_a_real_agent() -> None:
    known = {agent.id for agent in AGENTS}
    selected = _select("network", "cve patch change owner remediate")
    assert set(selected) <= known


def test_maf_orchestrator_intersects_question_intent_with_page_contract() -> None:
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


def test_reviewed_cross_domain_grants_are_exact_and_unrelated_terms_do_not_broaden() -> None:
    cases = (
        (
            "network",
            "Are there CVEs on the hosts behind this hub?",
            ("network", "vulnerability"),
        ),
        (
            "network",
            "Who owns this and is there an approval?",
            ("network", "governance"),
        ),
        (
            "vulnerability",
            "How do I remediate this exposure safely with a rollback?",
            ("vulnerability", "remediation"),
        ),
        (
            "finops",
            "Is the cost spike explained by a resource-health incident?",
            ("finops", "resource_health_observability"),
        ),
    )
    for page_kind, question, expected in cases:
        decision = select_specialists_for_turn(
            page_kind=page_kind,
            question=question,
            page_specialists=PAGE_SPECIALISTS,
            catalog=AGENTS,
            limit=MAX_CONTEXT_SPECIALISTS,
        )
        assert decision.selected_ids == expected

    unrelated = select_specialists_for_turn(
        page_kind="network",
        question="Show cost, identity, patch, and deployment details.",
        page_specialists=PAGE_SPECIALISTS,
        catalog=AGENTS,
        limit=MAX_CONTEXT_SPECIALISTS,
    )
    assert unrelated.selected_ids == ("network",)


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


@pytest.mark.parametrize(
    ("question", "expected"),
    (
        (
            "Summarise the top cross-domain risks for leadership.",
            ("vulnerability", "incident"),
        ),
        (
            "Give a cited cross-domain risk brief for the payments service.",
            ("vulnerability", "incident"),
        ),
        (
            "Produce a one-paragraph situation report for the payments service.",
            ("incident", "governance"),
        ),
    ),
)
def test_explicit_overview_synthesis_delegates_to_multiple_domains(
    question,
    expected,
) -> None:
    decision = select_specialists_for_turn(
        page_kind="overview",
        question=question,
        page_specialists=PAGE_SPECIALISTS,
        catalog=AGENTS,
        limit=MAX_CONTEXT_SPECIALISTS,
    )

    assert decision.selected_ids == expected
    assert "executive_summary" not in decision.selected_ids


def test_reported_page_routes_use_exact_ordered_safe_sets() -> None:
    cases = (
        (
            "services",
            "Which services have the highest vulnerability risk?",
            ("resource_health_observability", "governance"),
        ),
        (
            "twin",
            "Which vulnerable services are at risk in this twin?",
            ("network", "resource_health_observability"),
        ),
        (
            "changes_predeploy",
            "Which impacted services carry vulnerability exposure for this change?",
            ("change",),
        ),
        (
            "identity",
            "The identity provider is partial; who owns this scope and access?",
            ("identity_access",),
        ),
    )

    for page_kind, question, expected in cases:
        decision = select_specialists_for_turn(
            page_kind=page_kind,
            question=question,
            page_specialists=PAGE_SPECIALISTS,
            catalog=AGENTS,
            limit=MAX_CONTEXT_SPECIALISTS,
        )
        assert decision.selected_ids == expected, page_kind
        assert set(decision.selected_ids) <= set(PAGE_SPECIALISTS[page_kind])


def test_free_form_no_hint_questions_preserve_each_integrated_page_safe_set() -> None:
    manifest = load_specialist_manifest()
    tool_bearing_ids = {
        specialist.id
        for specialist in manifest.specialists
        if specialist.operations_mcp_tools and specialist.id != "executive_summary"
    }
    for page_kind, specialists in PAGE_SPECIALISTS.items():
        expected = tuple(
            specialist_id
            for specialist_id in specialists
            if specialist_id in tool_bearing_ids
        )[:MAX_CONTEXT_SPECIALISTS]
        if not expected:
            continue
        decision = select_specialists_for_turn(
            page_kind=page_kind,
            question="Summarize what I am looking at",
            page_specialists=PAGE_SPECIALISTS,
            catalog=AGENTS,
            limit=MAX_CONTEXT_SPECIALISTS,
        )
        assert decision.selected_ids == expected, page_kind


def test_maf_mode_is_default_unless_deterministic_rollback_requested(monkeypatch) -> None:
    from operations.maf_orchestrator import maf_mode_enabled

    monkeypatch.delenv("AIOPS_AGENT_ORCHESTRATION_MODE", raising=False)
    assert maf_mode_enabled() is True

    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "maf")
    assert maf_mode_enabled() is True

    monkeypatch.setenv("AIOPS_AGENT_ORCHESTRATION_MODE", "deterministic")
    assert maf_mode_enabled() is False
