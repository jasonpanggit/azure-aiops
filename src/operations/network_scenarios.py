"""Versioned, read-only scenario contract owned by the existing Network specialist."""

NETWORK_DESIGN_REVIEW = {
    "version": "1",
    "owner": "network",
    "page": "network",
    "scope": "effective_authorized_scope",
    "allowed_tools": ["firewall_nsg_gaps"],
    "arguments": {"category": "design_review"},
    "policy_version": "sha256_of_reviewed_policy",
    "parameters": {
        "design-review-private-access": ["resource_types", "exceptions"],
        "design-review-peering-integrity": ["require_gateway_transit", "exceptions"],
        "design-review-nsg-exposure": ["categories", "directions", "exceptions"],
    },
    "required_evidence": [
        "scoped_network_snapshot",
        "explicit_enabled_policy_rules",
        "provider_observed_at",
        "endpoint_approval_and_dns_bindings",
        "both_peering_sides_and_address_spaces",
        "ordered_nsg_rules",
    ],
    "limits": {"returned_assessments": 25, "tool_calls": 1},
    "output_schema": {
        "findings": "gaps[]",
        "assessment_statuses": ["violation", "observed", "unknown", "excepted"],
        "required": [
            "scenario_id",
            "policy_id",
            "policy_version",
            "check_id",
            "resource_id",
            "evidence_refs",
            "status",
            "detail",
        ],
    },
}
