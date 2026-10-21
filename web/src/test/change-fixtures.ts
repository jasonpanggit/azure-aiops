import type { ChangeAssessment, ChangeAssessmentSummary, IncidentReport } from "@/lib/types";

const timestamp = "2026-09-06T08:00:00Z";
const resourceId = "/subscriptions/sub-layout/resourceGroups/payments/providers/Microsoft.Network/networkSecurityGroups/payments-nsg";

/** Build populated, advisory assessment data for component and browser coverage. */
export function buildChangeAssessment(): ChangeAssessment {
  const impacted = ["payments-nsg", "payments-api"].map((name, depth) => ({
    resource_id: depth === 0 ? resourceId : `${resourceId}/dependents/${name}`,
    resource_type: depth === 0 ? "NetworkSecurityGroup" : "Application",
    name, application: "Payments API", business_service: "Payments", environment: "Production",
    subscription: "sub-layout", owner: "Payments SRE", support_team: "Payments operations",
    region: "australiaeast", criticality: "high", depth,
    relationship: depth === 0 ? "changed" : "depends_on", depends_on: depth === 0 ? [] : [resourceId],
    observed_at: timestamp,
  }));
  return {
    assessment_id: "assessment-layout", assessed_at: timestamp, source_engine: "declared-configuration",
    change: {
      change_id: "change-layout", source: "terraform_plan", title: "Review payments network change",
      author: "operator", submitted_at: timestamp, repository: "", target_environment: "Production",
      target_subscriptions: ["sub-layout"], effective_change_count: 1, ingestion_warnings: [],
      resource_changes: [{
        address: "azurerm_network_security_group.payments", action: "update",
        resource_type: "NetworkSecurityGroup", resource_id: resourceId, name: "payments-nsg",
        provider: "azurerm", changed_properties: ["security_rule"], is_destructive: false, source_ref: "plan",
      }],
    },
    state_comparison: {
      comparisons: [], counts: {}, compared_count: 1, discovered_count: 1, consistent: false,
      unknowns: ["Current traffic has not been observed."],
    },
    blast_radius: {
      impacted_resources: impacted, total_impacted_count: 4, directly_changed_count: 1,
      applications: ["Payments API"], business_services: ["Payments"], subscriptions: ["sub-layout"],
      environments: ["Production"], owners: ["Payments SRE"], support_teams: ["Payments operations"],
      regions: ["australiaeast"], network_controls_in_path: [resourceId], vulnerable_resources_in_path: [],
      max_depth_reached: 1, truncated: true, unknowns: ["Traversal is incomplete."],
      interpretation: "Predicted dependencies, not confirmed impact. Traversal is incomplete.", confirmed_impact: false,
    },
    simulation: {
      effects: Array.from({ length: 23 }, (_, index) => ({
        domain: "network", address: `payments-rule-${index}`, effect: `rule_change_${index}`,
        severity: "high", detail: `Predicted rule effect ${index}; validate traffic before deployment.`,
        basis: "declared configuration", requires_validation: true,
      })),
      simulated_domains: ["network"], by_domain: { network: 23 }, by_severity: { high: 23 },
      highest_severity: "high", unclassified_addresses: [], unknowns: ["Traffic logs unavailable."],
      basis: "declared configuration", interpretation: "Simulation is a prediction, not an observed outcome.", confirmed_outcome: false,
    },
    risk: {
      score: 72, level: "high", factors: { network: 1 }, contributing_factors: { network: 1 },
      evidence: Array.from({ length: 23 }, (_, index) => ({
        factor: `network_factor_${index}`, observation: `Declared rule requires review ${index}.`,
        source: "terraform_plan",
      })),
      confidence: "low", confidence_rationale: "Missing live traffic limits confidence.",
      unknowns: ["Current traffic has not been observed."], justification: "Declared network rules require review.",
      interpretation: "Risk is advisory, not a causal conclusion.", confirmed_cause: false,
    },
    cab_recommendation: {
      verdict: "approve_with_conditions", summary: "Review payments impact with the accountable owner.",
      conditions: ["Validate traffic before deployment."], required_approvals: ["network_owner"],
      triggers: [{ trigger: "network_change", reason: "Shared dependencies may be affected." }],
      risk_score: 72, risk_level: "high", confidence: "low", unknowns: ["Traffic logs unavailable."],
      interpretation: "Recommendation only; approval remains a separate operator decision.", confirmed_cause: false,
    },
    scope: { subscription: ["sub-layout"] }, scope_excluded_resource_count: 2, confirmed_cause: false,
  };
}

/** Build enough scoped history to exercise the existing assessment pagination. */
export function buildChangeHistory(): ChangeAssessmentSummary[] {
  return Array.from({ length: 23 }, (_, index) => ({
    assessment_id: `assessment-${index}`, change_id: `change-${index}`, source: "terraform_plan",
    title: `Recorded assessment ${index}`, author: "operator", assessed_at: timestamp,
    target_environment: "Production", resource_change_count: 1, risk_score: 72,
    risk_level: "high", confidence: "low", verdict: "approve_with_conditions",
    total_impacted_count: 4, business_services: ["Payments"],
  }));
}

/** Build observed timeline changes without asserting that they caused the incident. */
export function buildChangeReport(count = 23): IncidentReport {
  return {
    report_type: "summary", audience_summaries: {}, operational_patterns: [], freshness: timestamp, read_only: true,
    incidents: [{
      incident: { incident_id: "INC-layout", title: "Payments latency investigation", severity: "high", status: "active", started_at: timestamp },
      root_cause_analysis: {
        probable_causes: [], contributing_factors: [], confidence: 0.5, evidence: [], timeline: [],
        impacted_systems: [], reasoning_chain: [], contradicting_evidence: [], unknowns: ["Cause not established."],
        next_steps: [], confirmed_cause: false, conclusion: "Investigation required.",
      },
      blast_radius: {
        applications: ["Payments API"], services: [], business_services: ["Payments"], owners: ["Payments SRE"],
        support_teams: [], subscriptions: ["sub-layout"], network_paths: [], hub_dependencies: [],
        firewall_impact: [], nsg_impact: [], downstream_services: [], application_count: 1,
        service_count: 0, business_service_count: 1,
      },
      business_impact: { applications: ["Payments API"], services: [], business_services: ["Payments"], owners: ["Payments SRE"], support_teams: [] },
      timeline: Array.from({ length: count }, (_, index) => ({
        event_id: `change-event-${index}`, event_type: "ConfigurationChange",
        timestamp: new Date(Date.parse(timestamp) - index * 60_000).toISOString(),
        summary: `Observed payments change ${index}`, source: "Azure Activity",
        evidence: index === 0 ? [] : [`activity-record-${index}`],
        ...(index === 0 ? {} : { source_url: `https://example.test/activity/${index}` }),
      })),
    }],
  };
}
