"""Test Governance Agent contract validation."""

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


class TestGovernanceAgentContract:
    """Governance Agent output contract validation."""

    def test_valid_finding_accepted(self):
        """Valid governance finding with owner_id should parse."""
        json_text = make_finding_json("governance")
        findings = parse_specialist_findings(
            json_text,
            evidence_refs=EVIDENCE_REFS,
            resource_ids=RESOURCE_IDS,
            agent_id="governance",
        )
        assert len(findings) == 1
        assert findings[0]["finding_id"] == "GOV-001"
        assert findings[0]["owner_id"] == "team-platform"

    def test_missing_owner_id_rejected(self):
        """Finding missing owner_id should raise FoundryAgentError."""
        json_text = make_finding_with_missing_field("governance", "owner_id")
        with pytest.raises(
            FoundryAgentError,
            match="governance specialist finding schema is invalid",
        ):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="governance",
            )

    def test_uncited_resource_rejected(self):
        """Finding with uncited resource should raise FoundryAgentError."""
        json_text = make_finding_with_uncited_resource("governance")
        with pytest.raises(FoundryAgentError, match="uncited resource"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="governance",
            )

    def test_mutation_words_rejected(self):
        """Finding containing mutation instructions should raise FoundryAgentError."""
        json_text = make_finding_with_mutation_words("governance")
        with pytest.raises(FoundryAgentError, match="mutation instructions"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="governance",
            )

    def test_invalid_confidence_rejected(self):
        """Finding with invalid confidence should raise FoundryAgentError."""
        json_text = make_finding_with_invalid_enum(
            "governance", "confidence", "probable"
        )
        with pytest.raises(FoundryAgentError, match="confidence is invalid"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="governance",
            )
