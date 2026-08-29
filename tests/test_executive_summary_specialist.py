"""Test Executive Summary Agent contract validation.

Validates that the executive summary specialist agent emits properly formed findings
with cross-agent synthesis fields. Note: Executive summary findings do NOT require
resource_ids (synthesis role aggregates insights from all other agents).
"""

from __future__ import annotations

import pytest

from operations.foundry_agent import FoundryAgentError, parse_specialist_findings
from tests.foundry_test_fixtures import (
    EVIDENCE_REFS,
    RESOURCE_IDS,
    make_finding_json,
    make_finding_with_invalid_enum,
    make_finding_with_missing_field,
    make_finding_with_mutation_words,
    valid_executive_summary_finding,
)


class TestExecutiveSummaryAgentContract:
    """Executive Summary Agent output contract validation."""

    def test_valid_finding_accepted(self):
        """Valid executive summary finding should parse (no resource_ids)."""
        json_text = make_finding_json("executive_summary")
        findings = parse_specialist_findings(
            json_text,
            evidence_refs=EVIDENCE_REFS,
            resource_ids=RESOURCE_IDS,
            agent_id="executive_summary",
        )
        assert len(findings) == 1
        assert findings[0]["finding_id"] == "EXEC-SUMMARY-001"
        assert "resource_ids" not in findings[0]

    def test_missing_summary_rejected(self):
        """Finding missing summary should raise FoundryAgentError."""
        json_text = make_finding_with_missing_field("executive_summary", "summary")
        with pytest.raises(
            FoundryAgentError,
            match="executive_summary specialist finding schema is invalid",
        ):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="executive_summary",
            )

    def test_no_resource_ids_required(self):
        """Executive summary findings should not include resource_ids field."""
        import json

        finding = valid_executive_summary_finding()
        assert "resource_ids" not in finding
        payload = {"findings": [finding]}
        json_text = json.dumps(payload)
        findings = parse_specialist_findings(
            json_text,
            evidence_refs=EVIDENCE_REFS,
            resource_ids=RESOURCE_IDS,
            agent_id="executive_summary",
        )
        assert len(findings) == 1
        assert "resource_ids" not in findings[0]

    def test_missing_evidence_refs_rejected(self):
        """Finding missing evidence_refs should raise FoundryAgentError."""
        json_text = make_finding_with_missing_field(
            "executive_summary", "evidence_refs"
        )
        with pytest.raises(
            FoundryAgentError,
            match="executive_summary specialist finding schema is invalid",
        ):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="executive_summary",
            )

    def test_uncited_evidence_rejected(self):
        """Finding with uncited evidence ref should raise FoundryAgentError."""
        import json

        finding = valid_executive_summary_finding()
        finding["evidence_refs"] = ["unknown-ref"]
        payload = {"findings": [finding]}
        json_text = json.dumps(payload)
        with pytest.raises(FoundryAgentError, match="citation is missing or invalid"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="executive_summary",
            )

    def test_mutation_words_rejected(self):
        """Finding containing mutation instructions should raise FoundryAgentError."""
        json_text = make_finding_with_mutation_words("executive_summary")
        with pytest.raises(FoundryAgentError, match="mutation instructions"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="executive_summary",
            )

    def test_invalid_confidence_rejected(self):
        """Finding with invalid confidence should raise FoundryAgentError."""
        json_text = make_finding_with_invalid_enum(
            "executive_summary", "confidence", "speculative"
        )
        with pytest.raises(FoundryAgentError, match="confidence is invalid"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="executive_summary",
            )

    def test_confidence_enum_values_accepted(self):
        """All valid confidence values should be accepted."""
        import json

        for confidence_val in ["high", "medium", "low", "unknown"]:
            finding = valid_executive_summary_finding()
            finding["confidence"] = confidence_val
            payload = {"findings": [finding]}
            json_text = json.dumps(payload)
            findings = parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="executive_summary",
            )
            assert len(findings) == 1
            assert findings[0]["confidence"] == confidence_val
