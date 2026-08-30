"""Test Change Agent contract validation."""

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


class TestChangeAgentContract:
    """Change Agent output contract validation."""

    def test_valid_finding_accepted(self):
        """Valid change finding with change_id should parse."""
        json_text = make_finding_json("change")
        findings = parse_specialist_findings(
            json_text,
            evidence_refs=EVIDENCE_REFS,
            resource_ids=RESOURCE_IDS,
            agent_id="change",
        )
        assert len(findings) == 1
        assert findings[0]["finding_id"] == "CHG-001"
        assert findings[0]["change_id"] == "CHG-2024-00456"

    def test_missing_change_id_rejected(self):
        """Finding missing change_id should raise FoundryAgentError."""
        json_text = make_finding_with_missing_field("change", "change_id")
        with pytest.raises(
            FoundryAgentError,
            match="change specialist finding schema is invalid",
        ):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="change",
            )

    def test_uncited_resource_rejected(self):
        """Finding with uncited resource should raise FoundryAgentError."""
        json_text = make_finding_with_uncited_resource("change")
        with pytest.raises(FoundryAgentError, match="uncited resource"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="change",
            )

    def test_mutation_words_rejected(self):
        """Finding containing mutation instructions should raise FoundryAgentError."""
        json_text = make_finding_with_mutation_words("change")
        with pytest.raises(FoundryAgentError, match="mutation instructions"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="change",
            )

    def test_invalid_confidence_rejected(self):
        """Finding with invalid confidence should raise FoundryAgentError."""
        json_text = make_finding_with_invalid_enum(
            "change", "confidence", "definite"
        )
        with pytest.raises(FoundryAgentError, match="confidence is invalid"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="change",
            )
