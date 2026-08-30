"""Test Foundry Incident Specialist contract validation.

Validates that the incident specialist agent emits properly formed findings
with incident-specific fields (incident_id, timeline, etc.).
Note: Incident findings do NOT require resource_ids (incidents span multiple resources).
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
    valid_incident_finding,
)


class TestIncidentSpecialistContract:
    """Foundry Incident Specialist output contract validation."""

    def test_valid_finding_accepted(self):
        """Valid incident finding with incident_id should parse (no resource_ids)."""
        json_text = make_finding_json("incident")
        findings = parse_specialist_findings(
            json_text,
            evidence_refs=EVIDENCE_REFS,
            resource_ids=RESOURCE_IDS,
            agent_id="incident",
        )
        assert len(findings) == 1
        assert findings[0]["finding_id"] == "INC-001"
        assert findings[0]["incident_id"] == "INC-2024-00123"
        assert "resource_ids" not in findings[0]

    def test_missing_incident_id_rejected(self):
        """Finding missing incident_id should raise FoundryAgentError."""
        json_text = make_finding_with_missing_field("incident", "incident_id")
        with pytest.raises(
            FoundryAgentError,
            match="incident specialist finding schema is invalid",
        ):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="incident",
            )

    def test_no_resource_ids_required(self):
        """Incident findings should not include resource_ids field."""
        import json

        finding = valid_incident_finding()
        assert "resource_ids" not in finding
        payload = {"findings": [finding]}
        json_text = json.dumps(payload)
        findings = parse_specialist_findings(
            json_text,
            evidence_refs=EVIDENCE_REFS,
            resource_ids=RESOURCE_IDS,
            agent_id="incident",
        )
        assert len(findings) == 1
        assert "resource_ids" not in findings[0]

    def test_missing_evidence_refs_rejected(self):
        """Finding missing evidence_refs should raise FoundryAgentError."""
        json_text = make_finding_with_missing_field("incident", "evidence_refs")
        with pytest.raises(
            FoundryAgentError,
            match="incident specialist finding schema is invalid",
        ):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="incident",
            )

    def test_uncited_evidence_rejected(self):
        """Finding with uncited evidence ref should raise FoundryAgentError."""
        import json

        finding = valid_incident_finding()
        finding["evidence_refs"] = ["unknown-ref"]
        payload = {"findings": [finding]}
        json_text = json.dumps(payload)
        with pytest.raises(FoundryAgentError, match="citation is missing or invalid"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="incident",
            )

    def test_mutation_words_rejected(self):
        """Finding containing mutation instructions should raise FoundryAgentError."""
        json_text = make_finding_with_mutation_words("incident")
        with pytest.raises(
            FoundryAgentError, match="mutation instructions"
        ):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="incident",
            )

    def test_invalid_confidence_rejected(self):
        """Finding with invalid confidence should raise FoundryAgentError."""
        json_text = make_finding_with_invalid_enum(
            "incident", "confidence", "likely"
        )
        with pytest.raises(FoundryAgentError, match="confidence is invalid"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="incident",
            )

    def test_confidence_enum_values_accepted(self):
        """All valid confidence values should be accepted."""
        import json

        for confidence_val in ["high", "medium", "low", "unknown"]:
            finding = valid_incident_finding()
            finding["confidence"] = confidence_val
            payload = {"findings": [finding]}
            json_text = json.dumps(payload)
            findings = parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="incident",
            )
            assert len(findings) == 1
            assert findings[0]["confidence"] == confidence_val

    def test_freshness_enum_values_accepted(self):
        """All valid freshness values should be accepted."""
        import json

        for freshness_val in ["fresh", "stale", "partial", "unavailable", "unknown"]:
            finding = valid_incident_finding()
            finding["freshness"] = freshness_val
            payload = {"findings": [finding]}
            json_text = json.dumps(payload)
            findings = parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="incident",
            )
            assert len(findings) == 1
            assert findings[0]["freshness"] == freshness_val
