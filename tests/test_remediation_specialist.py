"""Test Remediation Agent contract validation."""

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
