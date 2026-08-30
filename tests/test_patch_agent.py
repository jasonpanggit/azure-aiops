"""Test Patch Agent contract validation.

Validates that the patch specialist agent emits properly formed findings
with correct domain-specific fields (kb_id, patch_priority, etc.).
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
    make_finding_with_uncited_resource,
    valid_patch_finding,
)


class TestPatchAgentContract:
    """Patch Agent output contract validation."""

    def test_valid_finding_accepted(self):
        """Valid patch finding with KB article and resources should parse."""
        json_text = make_finding_json("patch")
        findings = parse_specialist_findings(
            json_text,
            evidence_refs=EVIDENCE_REFS,
            resource_ids=RESOURCE_IDS,
            agent_id="patch",
        )
        assert len(findings) == 1
        assert findings[0]["finding_id"] == "PATCH-KB-001"
        assert findings[0]["kb_id"] == "KB-4567890"
        assert findings[0]["confidence"] == "high"

    def test_missing_kb_id_rejected(self):
        """Finding missing kb_id should raise FoundryAgentError."""
        json_text = make_finding_with_missing_field("patch", "kb_id")
        with pytest.raises(
            FoundryAgentError,
            match="patch specialist finding schema is invalid",
        ):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="patch",
            )

    def test_missing_resource_ids_rejected(self):
        """Finding missing resource_ids should raise FoundryAgentError."""
        json_text = make_finding_with_missing_field("patch", "resource_ids")
        with pytest.raises(
            FoundryAgentError,
            match="patch specialist finding schema is invalid",
        ):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="patch",
            )

    def test_uncited_resource_rejected(self):
        """Finding with uncited resource should raise FoundryAgentError."""
        json_text = make_finding_with_uncited_resource("patch")
        with pytest.raises(FoundryAgentError, match="uncited resource"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="patch",
            )

    def test_mutation_words_rejected(self):
        """Finding containing mutation instructions should raise FoundryAgentError."""
        json_text = make_finding_with_mutation_words("patch")
        with pytest.raises(
            FoundryAgentError, match="mutation instructions"
        ):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="patch",
            )

    def test_invalid_confidence_rejected(self):
        """Finding with invalid confidence should raise FoundryAgentError."""
        json_text = make_finding_with_invalid_enum(
            "patch", "confidence", "critical"
        )
        with pytest.raises(FoundryAgentError, match="confidence is invalid"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="patch",
            )

    def test_invalid_freshness_rejected(self):
        """Finding with invalid freshness should raise FoundryAgentError."""
        json_text = make_finding_with_invalid_enum(
            "patch", "freshness", "outdated"
        )
        with pytest.raises(FoundryAgentError, match="freshness is invalid"):
            parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="patch",
            )

    def test_confidence_enum_values_accepted(self):
        """All valid confidence values should be accepted."""
        import json

        for confidence_val in ["high", "medium", "low", "unknown"]:
            finding = valid_patch_finding()
            finding["confidence"] = confidence_val
            payload = {"findings": [finding]}
            json_text = json.dumps(payload)
            findings = parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="patch",
            )
            assert len(findings) == 1
            assert findings[0]["confidence"] == confidence_val

    def test_freshness_enum_values_accepted(self):
        """All valid freshness values should be accepted."""
        import json

        for freshness_val in ["fresh", "stale", "partial", "unavailable", "unknown"]:
            finding = valid_patch_finding()
            finding["freshness"] = freshness_val
            payload = {"findings": [finding]}
            json_text = json.dumps(payload)
            findings = parse_specialist_findings(
                json_text,
                evidence_refs=EVIDENCE_REFS,
                resource_ids=RESOURCE_IDS,
                agent_id="patch",
            )
            assert len(findings) == 1
            assert findings[0]["freshness"] == freshness_val
