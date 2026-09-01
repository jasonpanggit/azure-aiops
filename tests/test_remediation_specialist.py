"""Test Remediation Agent contract validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from operations.foundry_agent import FoundryAgentError, parse_specialist_findings
from tests.foundry_test_fixtures import (
    EVIDENCE_REFS,
    RESOURCE_IDS,
    make_finding_json,
    make_finding_with_invalid_enum,
    make_finding_with_missing_field,
    make_finding_with_mutation_words,
    make_finding_with_uncited_resource,
)


class TestRemediationAgentContract:
    """Remediation Agent output contract validation."""

    def test_valid_finding_accepted(self):
        """Valid remediation finding with remediation_id should parse."""
        json_text = make_finding_json("remediation")
        findings = parse_specialist_findings(
            json_text,
            evidence_refs=EVIDENCE_REFS,
            resource_ids=RESOURCE_IDS,
            agent_id="remediation",
        )
        assert len(findings) == 1
        assert findings[0]["finding_id"] == "REM-001"
        assert findings[0]["remediation_id"] == "REM-2024-00789"

    def test_missing_remediation_id_rejected(self):
        """Finding missing remediation_id should raise FoundryAgentError."""
        json_text = make_finding_with_missing_field("remediation", "remediation_id")
        with pytest.raises(
            FoundryAgentError,
            match="remediation specialist finding schema is invalid",
        ):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="remediation",
            )

    def test_uncited_resource_rejected(self):
        """Finding with uncited resource should raise FoundryAgentError."""
        json_text = make_finding_with_uncited_resource("remediation")
        with pytest.raises(FoundryAgentError, match="uncited resource"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="remediation",
            )

    def test_mutation_words_rejected(self):
        """Finding containing mutation instructions should raise FoundryAgentError."""
        json_text = make_finding_with_mutation_words("remediation")
        with pytest.raises(FoundryAgentError, match="mutation instructions"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="remediation",
            )

    def test_invalid_confidence_rejected(self):
        """Finding with invalid confidence should raise FoundryAgentError."""
        json_text = make_finding_with_invalid_enum(
            "remediation", "confidence", "certain"
        )
        with pytest.raises(FoundryAgentError, match="confidence is invalid"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="remediation",
            )


from operations.autonomous_investigation import _select_context_specialists


def test_missing_urgency_fields_rejected():
    import json
    finding = {
        "finding_id": "REM-001",
        "resource_ids": list(RESOURCE_IDS)[:1],
        "remediation_id": "REM-2024-00789",
        "evidence_refs": list(EVIDENCE_REFS)[:2],
        "confidence": "high",
        "uncertainty": [],
        "freshness": "fresh",
        "actionable": True,
        "next_check": "Review governed rollout in staging",
        "summary": "Business impact requires action now",
        "pros": ["Reduces customer-facing blast radius"],
        "cons": ["Needs maintenance window"],
        "urgency_reasoning": "Checkout is customer-facing and on an active path.",
    }
    finding.pop("cons")
    with pytest.raises(FoundryAgentError, match="schema is invalid"):
        parse_specialist_findings(json.dumps({"findings": [finding]}), evidence_refs=EVIDENCE_REFS, resource_ids=RESOURCE_IDS, agent_id="remediation")


def test_prompt_requires_business_consequence_and_no_change_option():
    prompt = Path("src/operations/foundry_prompts/remediation_prompt.txt").read_text()
    assert "business consequence" in prompt.casefold()
    assert "technical severity alone" in prompt.casefold()
    assert "no change is a valid and valuable outcome" in prompt.casefold()
    for disposition in ("act_now", "schedule", "defer", "not_applicable", "escalate"):
        assert disposition in prompt


def test_prompt_forbids_ungoverned_actions_and_execution():
    prompt = Path("src/operations/foundry_prompts/remediation_prompt.txt").read_text().casefold()
    assert "typed governed catalog entry" in prompt
    assert "defender remediation prose" in prompt
    assert "never acts" in prompt
    assert "human approves" in prompt
    assert "correlated cases" in prompt
    assert "raw defender evidence" in prompt


def test_remediation_page_routes_cross_domain_questions_to_matching_specialists():
    page_specialists = {
        "remediation_page": ("remediation",),
        "remediation": ("remediation", "governance"),
    }
    assert _select_context_specialists(page_kind="remediation_page", question="What remediation option best protects Checkout?", page_specialists=page_specialists)[0] == "remediation"
    ids = _select_context_specialists(page_kind="remediation_page", question="Who owns this service and what policy exception applies?", page_specialists=page_specialists)
    assert "governance" in ids
    ids = _select_context_specialists(page_kind="remediation_page", question="Which CVE evidence makes waiting risky?", page_specialists=page_specialists)
    assert "vulnerability" in ids
