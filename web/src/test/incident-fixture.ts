import type { IncidentFinding, IncidentReportEntry } from "@/lib/types";

/** Creates a complete incident fixture for Situation presentation tests. */
export function createIncidentFixture(
  overrides: Partial<IncidentReportEntry["incident"]> = {}
): IncidentReportEntry {
  const incident = {
    incident_id: "INC-1001",
    title: "Payroll database latency",
    severity: "critical",
    status: "investigating",
    started_at: "2025-03-01T10:00:00Z",
    ...overrides,
  };
  return {
    incident,
    root_cause_analysis: {
      probable_causes: [
        {
          evidence_id: "cause-1",
          classification: "database_capacity",
          summary: "Database capacity exhausted after deployment",
          confidence: 0.91,
          evidence: ["CPU saturation began after the release", "Database wait time exceeded the service objective"],
        },
      ],
      contributing_factors: [],
      confidence: 0.91,
      evidence: [],
      timeline: [],
      impacted_systems: [],
      reasoning_chain: ["Deployment completed", "Database CPU increased", "Payroll requests slowed"],
      contradicting_evidence: [],
      unknowns: [],
      next_steps: [],
      confirmed_cause: false,
      conclusion: "The deployment is the most probable trigger for database capacity exhaustion.",
    },
    blast_radius: {
      applications: ["Payroll API", "Payroll Web"],
      services: ["Payroll database"],
      business_services: ["Payroll"],
      owners: ["Payroll Product"],
      support_teams: ["Finance SRE"],
      subscriptions: [],
      network_paths: [],
      hub_dependencies: [],
      firewall_impact: [],
      nsg_impact: [],
      downstream_services: [],
      application_count: 2,
      service_count: 1,
      business_service_count: 1,
    },
    timeline: [
      {
        event_id: "change-1",
        event_type: "resource_change",
        timestamp: "2025-03-01T09:45:00Z",
        summary: "Payroll API release 2025.03.1 deployed",
        source: "Azure Resource Graph",
        evidence: ["deployment-42"],
      },
      {
        event_id: "alert-1",
        event_type: "alert",
        timestamp: "2025-03-01T10:00:00Z",
        summary: "Database latency breached the service objective",
        source: "Azure Monitor",
        evidence: ["alert-88"],
      },
    ],
    business_impact: {
      applications: ["Payroll API", "Payroll Web"],
      services: ["Payroll database"],
      business_services: ["Payroll"],
      owners: ["Payroll Product"],
      support_teams: ["Finance SRE"],
      risk_score: 95,
    },
  };
}

/** Creates the detail variant returned by the incident investigation endpoint. */
export function createIncidentFinding(): IncidentFinding {
  return {
    ...createIncidentFixture(),
    recommended_action: {
      suggested_action: "Scale the Payroll database and validate the release query plan.",
      impact: "Restore transaction latency while retaining rollback readiness.",
      confidence: 0.86,
      advisory_only: true,
    },
  };
}
