import { render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider, useScope } from "@/lib/scope-context";

const api = vi.hoisted(() => ({
  summary: vi.fn(),
  exposures: vi.fn(),
  patchPriorities: vi.fn(),
  assetExposures: vi.fn(),
  defenderPosture: vi.fn(),
  defenderOverview: vi.fn(),
  defenderAlerts: vi.fn(),
  defenderAttackPaths: vi.fn(),
  defenderSecureScoreControls: vi.fn(),
  slaCompliance: vi.fn(),
  riskExceptions: vi.fn(),
  revokeRiskException: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  buildCopilotSnapshot: (input: Record<string, unknown>) => input,
  copilotEvidenceRows: () => [],
  vulnerabilityApi: api,
}));

vi.mock("@/components/exposure/PatchInventory", () => ({
  PatchInventory: () => <div>Patch inventory</div>,
}));

import ExposurePage from "./page";

const envelope = <T,>(data: T) => ({
  data,
  evidence: [],
  warnings: [],
  scope: {},
  knowledge_version: "graph-1",
});

function ScopedExposurePage() {
  const { setScope } = useScope();
  useEffect(() => {
    setScope({
      business_service: ["Payments"],
      subscription: ["sub-1"],
    });
  }, [setScope]);
  return <ExposurePage />;
}

describe("ExposurePage Defender posture", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.summary.mockResolvedValue(envelope({
      open_finding_count: 1,
      affected_server_count: 1,
      affected_application_count: 1,
      affected_business_service_count: 1,
      reachable_server_count: 1,
      internet_exposed_count: 0,
      critical_count: 1,
      defender_finding_count: 1,
      defender_observed_server_count: 1,
      affected_asset_count: 1,
      defender_observed_asset_count: 1,
      defender_posture_count: 1,
      defender_recommendation_count: 1,
      defender_coverage_known: true,
    }));
    api.exposures.mockResolvedValue(envelope([{
      cve_id: "CVE-2026-0001",
      severity: "critical",
      affected_server_count: 1,
      affected_application_count: 1,
      affected_business_service_count: 1,
      reachable_server_count: 1,
      internet_exposed: false,
      exploit_signal: "",
      priority_score: 90,
      expected_risk_reduction: 80,
      recommended_patch: "Upgrade Contoso Server to 2.1",
      epss_score: 0,
      is_known_exploited: false,
      finding_ids: ["finding-1"],
      defender_finding_count: 1,
      defender_observed_server_count: 1,
      defender_recommendations: ["Remediate vulnerable software"],
    }]));
    api.patchPriorities.mockResolvedValue(envelope([]));
    api.assetExposures.mockResolvedValue(envelope([{
      asset_id: "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1",
      name: "vm-1",
      inventory_kind: "Azure VM",
      resource_type: "microsoft.compute/virtualmachines",
      business_service: "Payments",
      application: "Checkout",
      environment: "production",
      owner: "platform",
      region: "eastus",
      finding_count: 1,
      critical_count: 1,
      cve_ids: ["CVE-2026-0001"],
      missing_kbs: [],
      reachable: true,
      internet_exposed: false,
      network_exposure: "reachable",
      priority_score: 90,
      expected_risk_reduction: 80,
      finding_ids: ["finding-1"],
      defender_observed: true,
      defender_finding_count: 1,
      defender_recommendations: ["Remediate vulnerable software"],
      defender_software: ["Contoso Server 2.0"],
    }]));
    api.defenderPosture.mockResolvedValue(envelope([{
      assessment_id: "assessment-storage-1",
      asset_id: "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/data",
      asset_name: "data",
      resource_type: "microsoft.storage/storageaccounts",
      inventory_kind: "Storage",
      defender_plan: "Defender for Storage",
      status: "Unhealthy",
      severity: "high",
      recommendation: "Storage accounts should restrict network access",
      description: "Public network access is enabled.",
      remediation: "Disable public network access.",
      last_assessed_at: "2026-08-17T00:00:00Z",
      subscription_id: "sub-1",
    }]));
    api.defenderOverview.mockResolvedValue(envelope({
      active_alert_count: 1,
      critical_alert_count: 1,
      attack_path_count: 1,
      unhealthy_recommendation_count: 1,
      secure_scores: [{
        id: "score-1",
        subscription_id: "sub-1",
        currentScore: 40,
        maxScore: 80,
        percentage: 0.5,
        observedAt: "2026-08-17T00:00:00Z",
      }, {
        id: "score-2",
        subscription_id: "sub-2",
        currentScore: 60,
        maxScore: 80,
        percentage: 0.75,
        observedAt: "2026-08-17T00:00:00Z",
      }],
      top_controls: [],
      coverage: {
        alerts: { availability: "available", freshness: "fresh", quality: "complete", error: "", observed_at: "2026-08-17T00:00:00Z" },
        attack_paths: { availability: "available", freshness: "fresh", quality: "complete", error: "", observed_at: "2026-08-17T00:00:00Z" },
        secure_score: { availability: "available", freshness: "fresh", quality: "complete", error: "", observed_at: "2026-08-17T00:00:00Z" },
        recommendations: { availability: "available", freshness: "fresh", quality: "complete", error: "", observed_at: "2026-08-17T00:00:00Z" },
      },
    }));
    api.defenderAlerts.mockResolvedValue(envelope([{
      id: "alert-1",
      title: "Cryptominer detected",
      description: "Suspicious process observed.",
      status: "Active",
      severity: "Critical",
      intent: "Impact",
      productName: "Defender for Servers",
      timeGenerated: "2026-08-17T01:00:00Z",
      remediationSteps: ["Isolate the machine"],
      resourceIds: ["/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-1"],
      subscription_id: "sub-1",
    }]));
    api.defenderAttackPaths.mockResolvedValue(envelope([{
      id: "path-1",
      title: "Internet to storage",
      description: "",
      potentialImpact: "Sensitive data exposure",
      riskCategories: ["Data"],
      manualRemediationSteps: [],
      nodeCount: 2,
      connectionCount: 1,
      nodes: [
        { id: "internet", displayName: "Internet", nodeType: "IpAddress", resourceId: "", resolved: false },
        { id: "storage", displayName: "data", nodeType: "AzureResource", resourceId: "storage-id", resolved: true },
      ],
      connections: [],
      subscription_id: "sub-1",
    }]));
    api.defenderSecureScoreControls.mockResolvedValue(envelope([{
      id: "control-1",
      title: "Restrict management ports",
      currentScore: 2,
      maxScore: 8,
      percentage: 0.25,
      unhealthyResourceCount: 3,
      healthyResourceCount: 1,
      assessmentDefinitions: [],
      subscription_id: "sub-1",
    }]));
    api.slaCompliance.mockResolvedValue(envelope(null));
    api.riskExceptions.mockResolvedValue(envelope([]));
  });

  it("summarizes Defender and patch signals and links to the detail sub-pages", async () => {
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>
    );

    // The landing page is a lean summary: detail tables live on the
    // defender-posture and patch-priorities sub-pages.
    expect(await screen.findByRole("heading", { name: "Defender posture →" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Patch priorities →" })).toBeInTheDocument();

    expect(screen.getByRole("link", { name: /Defender posture/ })).toHaveAttribute("href", "/exposure/defender-posture");
    expect(screen.getByRole("link", { name: /Patch priorities/ })).toHaveAttribute("href", "/exposure/patch-priorities");

    expect(screen.getByText("Active alerts")).toBeInTheDocument();
    expect(screen.getByText("Attack paths")).toBeInTheDocument();
    expect(screen.getByText("Defender recommendations")).toBeInTheDocument();
  });

  it("renders SLA metrics as placeholders when compliance data is null", async () => {
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>
    );

    // slaCompliance resolves to a null envelope in this suite; the summary
    // must degrade to placeholders rather than throwing on a null payload.
    expect(await screen.findByText("Overall compliance")).toBeInTheDocument();
    expect(screen.getAllByText("SLA data unavailable").length).toBeGreaterThan(0);
  });

  it("retains the selected scope when requesting risk exceptions", async () => {
    render(
      <ScopeProvider>
        <ScopedExposurePage />
      </ScopeProvider>
    );

    await waitFor(() => {
      expect(api.riskExceptions).toHaveBeenLastCalledWith({
        business_service: ["Payments"],
        subscription: ["sub-1"],
      });
    });
  });
});
