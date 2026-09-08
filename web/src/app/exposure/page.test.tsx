import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider, useScope } from "@/lib/scope-context";

const api = vi.hoisted(() => ({
  summary: vi.fn(),
  exposureOverview: vi.fn(),
  exposures: vi.fn(),
  authoritativeExposures: vi.fn(),
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

function overviewEnvelope(
  state: "complete" | "healthy-empty" | "partial" | "stale" | "unavailable" = "complete",
) {
  const freshnessState = state === "stale" ? "stale" : "current";
  return {
    data: {
      total_count: 4,
      generation: "generation-overview-22",
      applied: {
        scope: { subscription: ["sub-1"] },
        filters: [],
        sort: { field: "priority_score", direction: "desc" },
      },
      completeness: {
        state,
        represented_connections: 1,
        expected_connections: 2,
        represented: 3,
        total: 4,
        excluded: 1,
        excluded_reasons: ["Defender West connection unavailable"],
      },
      freshness: {
        state: freshnessState,
        as_of: "2026-09-06T08:00:00Z",
        source_family: "aum",
        threshold_seconds: 3600,
      },
      contract: {
        version: "1.0.0",
        query: {
          scope: { subscription: ["sub-1"] },
          generation: "generation-overview-22",
          filters: [],
          sort: { field: "priority_score", direction: "desc" },
          target_kind: "all",
        },
        counts: {
          unit: "findings",
          returned: 3,
          represented: 3,
          total: 4,
          excluded: 1,
        },
        units: {
          finding_count: "count",
          priority_score: "score",
          sla_age: "seconds",
        },
        completeness: {
          state,
          represented_connections: 1,
          expected_connections: 2,
          represented: 3,
          total: 4,
          excluded: 1,
          excluded_reasons: ["Defender West connection unavailable"],
        },
        freshness: {
          state: freshnessState,
          as_of: "2026-09-06T08:00:00Z",
          source_family: "aum",
          threshold_seconds: 3600,
        },
        evidence_refs: [{ source_family: "aum", source_id: "finding-1" }],
        deep_link_action: {
          action_id: "open_exposure_detail",
          kind: "deep_link",
          path_field: "detail_path",
          fallback_path_template: "/exposure/{target_kind}/{exposure_id}",
        },
        safe_error: null,
      },
    },
    evidence: [{
      source_engine: "Azure Update Manager",
      source_table: "gold_exposure_current",
      timestamp: "2026-09-06T08:00:00Z",
      confidence: "high",
      freshness: freshnessState === "stale" ? "stale" : "fresh",
      freshness_threshold_seconds: 3600,
      freshness_source_family: "aum",
    }],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-overview-22",
    pagination: { limit: 50, total: 4, next_cursor: null },
  };
}

function pending<T>() {
  return new Promise<T>(() => undefined);
}

const patchPriority = {
  priority_id: "priority-1",
  priority_type: "kb",
  source_label: "Azure Update Manager",
  source_names: ["aum"],
  kb_id: "KB600001",
  cve_ids: ["CVE-2026-0001"],
  software_observations: ["Contoso Server 2.0"],
  defender_recommendations: [],
  affected_server_count: 1,
  affected_application_count: 1,
  affected_business_service_count: 1,
  reachable_server_count: 1,
  expected_risk_reduction: 82,
  priority_score: 91,
  overdue_count: 0,
  max_days_open: 1,
  recommended_action: "Install KB600001",
};

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
    api.exposureOverview.mockResolvedValue(overviewEnvelope());
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
    api.authoritativeExposures.mockResolvedValue(envelope({
      findings: [
        {
          exposure_id: "exposure:aum-only:vm-a:cve-2026-1001",
          target_id: "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-a",
          target_kind: "server",
          weakness_id: "CVE-2026-1001",
          subscription_id: "sub-1",
          connection_ids: ["connection-aum-east"],
          source_families: ["aum"],
          read_model_generation_id: "exposure-generation-0001",
          completeness: "complete",
        },
        {
          exposure_id: "exposure:defender-only:vm-b:cve-2026-1002",
          target_id: "/subscriptions/sub-2/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-b",
          target_kind: "server",
          weakness_id: "CVE-2026-1002",
          subscription_id: "sub-2",
          connection_ids: ["connection-defender-west"],
          source_families: ["defender"],
          read_model_generation_id: "exposure-generation-0001",
          completeness: "complete",
        },
        {
          exposure_id: "exposure:merged:vm-shared:cve-2026-1003",
          target_id: "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.HybridCompute/machines/vm-shared",
          target_kind: "server",
          weakness_id: "CVE-2026-1003",
          subscription_id: "sub-1",
          connection_ids: ["connection-aum-east", "connection-defender-west"],
          source_families: ["aum", "defender"],
          read_model_generation_id: "exposure-generation-0001",
          completeness: "complete",
        },
        {
          exposure_id: "exposure:image:platform-api:cve-2026-2001",
          target_id: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          target_kind: "container_image",
          weakness_id: "CVE-2026-2001",
          subscription_id: "sub-2",
          connection_ids: ["connection-defender-west"],
          source_families: ["defender"],
          read_model_generation_id: "exposure-generation-0001",
          completeness: "complete",
        },
      ],
      read_model_generation_id: "exposure-generation-0001",
      returned_count: 4,
      total_count: 4,
      completeness: {
        state: "partial",
        represented_connections: 2,
        expected_connections: 3,
      },
      source_attribution: [
        { source_family: "aum", finding_count: 2 },
        { source_family: "defender", finding_count: 3 },
      ],
    }));
    api.patchPriorities.mockResolvedValue(envelope([patchPriority]));
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
    api.slaCompliance.mockResolvedValue(envelope({
      open_count: 2,
      tracked_count: 2,
      compliant_count: 1,
      overdue_count: 1,
      overall_compliance_rate: 0.5,
      by_severity: [],
      aging_buckets: {},
      freshness: "2026-09-06T08:00:00Z",
    }));
    api.riskExceptions.mockResolvedValue(envelope([{
      exception_id: "exception-1",
      cve_id: "CVE-2026-0001",
      server_id: "server-1",
      reason: "Compensating control",
      approved_by: "security@example.com",
      created_at: "2026-09-01T00:00:00Z",
      expires_at: "2026-09-10T00:00:00Z",
    }]));
  });

  it("summarizes Defender and patch signals and links to the detail sub-pages", async () => {
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>
    );

    // The landing page is a lean summary: detail tables live on the
    // defender-posture and patch-priorities sub-pages.
    expect(await screen.findByRole("heading", { name: "Defender overview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Patch priority preview" })).toBeInTheDocument();

    expect(screen.getByRole("link", { name: /Defender posture/ })).toHaveAttribute("href", "/exposure/defender-posture");
    expect(
      screen
        .getAllByRole("link", { name: /Patch priorities/ })
        .some((link) => link.getAttribute("href") === "/exposure/patch-priorities"),
    ).toBe(true);

    expect(screen.getByText("Active alerts")).toBeInTheDocument();
    expect(screen.getByText("Attack paths")).toBeInTheDocument();
    expect(screen.getByText("Defender recommendations")).toBeInTheDocument();
  });

  it("keeps the Overview lean and does not render the full patch inventory", async () => {
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>
    );

    expect(await screen.findByRole("heading", { name: "Patch priority preview" })).toBeInTheDocument();
    expect(screen.queryByText("Patch inventory")).not.toBeInTheDocument();
  });

  it("renders a proven null SLA response as healthy-empty rather than zero", async () => {
    api.slaCompliance.mockResolvedValue(envelope(null));
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>
    );

    expect(
      await screen.findByText("No SLA reports reported by Exposure SLA"),
    ).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
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

  it("does not duplicate the authoritative operational finding list on Overview", async () => {
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>
    );

    await screen.findByRole("heading", { name: "Exposure summary" });
    for (const exposureId of [
      "exposure:aum-only:vm-a:cve-2026-1001",
      "exposure:defender-only:vm-b:cve-2026-1002",
      "exposure:merged:vm-shared:cve-2026-1003",
      "exposure:image:platform-api:cve-2026-2001",
    ]) {
      expect(screen.queryByText(exposureId)).not.toBeInTheDocument();
    }
    expect(api.authoritativeExposures).not.toHaveBeenCalled();
  });

  it("renders all six independently stateful Overview sections", async () => {
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>,
    );

    for (const sourceName of [
      "Exposure summary",
      "Patch priority preview",
      "Exposure asset counts",
      "Defender overview",
      "Exposure SLA",
      "Risk exceptions",
    ]) {
      const section = await screen.findByLabelText(`${sourceName} state`);
      expect(section).toHaveAttribute("aria-busy", "false");
      expect(within(section).getByText("Current")).toBeInTheDocument();
      expect(within(section).getByText(/Source family: aum/)).toBeInTheDocument();
      expect(within(section).getByText(/Freshness threshold: 3,600 seconds/)).toBeInTheDocument();
      expect(within(section).getByText(/Observed: 2026-09-06T08:00:00Z/)).toBeInTheDocument();
      expect(within(section).getByText(/1 of 2 connections represented/)).toBeInTheDocument();
      expect(within(section).getByText(/loaded/)).toBeInTheDocument();
      expect(within(section).getAllByText(/\d+ total/).length).toBeGreaterThan(0);
      expect(within(section).getByText(/1 excluded/)).toBeInTheDocument();
      expect(
        within(section).getByText("Defender West connection unavailable"),
      ).toBeInTheDocument();
    }
  });

  it("uses the most conservative section state in the header and evidence bar", async () => {
    api.exposureOverview.mockResolvedValue(overviewEnvelope("partial"));
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>,
    );

    const headerStatus = await screen.findByRole("status", {
      name: "Which exposure should be reduced first? evidence status",
    });
    await waitFor(() =>
      expect(headerStatus).toHaveTextContent("Partial operational context"),
    );
    expect(headerStatus).toHaveTextContent("1 of 2 connections represented");
    expect(headerStatus).toHaveTextContent("3 represented");
    expect(headerStatus).toHaveTextContent("4 total");
    expect(headerStatus).toHaveTextContent("1 excluded");
    expect(headerStatus).toHaveTextContent("Defender West connection unavailable");
    expect(screen.queryByTestId("page-header-signal-dot")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Data trust and provenance")).toHaveTextContent(
      "Partial evidence",
    );
  });

  it.each([
    ["summary", "Exposure summary", null],
    ["patchPriorities", "Patch priority preview", []],
    ["assetExposures", "Exposure asset counts", []],
    ["defenderOverview", "Defender overview", null],
    ["slaCompliance", "Exposure SLA", null],
    ["riskExceptions", "Risk exceptions", []],
  ])(
    "keeps healthy siblings visible while %s is healthy-empty",
    async (method, sourceName, emptyValue) => {
      api[method as keyof typeof api].mockResolvedValue(envelope(emptyValue));
      render(
        <ScopeProvider>
          <ExposurePage />
        </ScopeProvider>,
      );

      expect(
        await screen.findByText(new RegExp(`reported by ${sourceName}$`)),
      ).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Defender overview" })).toBeInTheDocument();
      expect(screen.queryByText("Exposure intelligence is unavailable")).not.toBeInTheDocument();
    },
  );

  it.each([
    ["summary", "Exposure summary"],
    ["patchPriorities", "Patch priority preview"],
    ["assetExposures", "Exposure asset counts"],
    ["defenderOverview", "Defender overview"],
    ["slaCompliance", "Exposure SLA"],
    ["riskExceptions", "Risk exceptions"],
  ])(
    "isolates a %s error without hiding usable siblings",
    async (method, sourceName) => {
      api[method as keyof typeof api].mockRejectedValue(
        new Error(`${sourceName} provider failed`),
      );
      render(
        <ScopeProvider>
          <ExposurePage />
        </ScopeProvider>,
      );

      expect(await screen.findByText(`${sourceName} is unavailable`)).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Defender overview" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Patch priority preview" })).toBeInTheDocument();
      expect(screen.queryByText("Exposure intelligence is unavailable")).not.toBeInTheDocument();
    },
  );

  it.each([
    ["summary", "Exposure summary"],
    ["patchPriorities", "Patch priority preview"],
    ["assetExposures", "Exposure asset counts"],
    ["defenderOverview", "Defender overview"],
    ["slaCompliance", "Exposure SLA"],
    ["riskExceptions", "Risk exceptions"],
  ])("keeps siblings usable while %s is loading", async (method, sourceName) => {
    api[method as keyof typeof api].mockReturnValue(pending());
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>,
    );

    expect(await screen.findByText(`Loading ${sourceName}`)).toBeInTheDocument();
    if (method === "patchPriorities") {
      expect(await screen.findByText("Active alerts")).toBeInTheDocument();
    } else {
      expect(await screen.findByText("KB600001")).toBeInTheDocument();
    }
    expect(screen.getByRole("heading", { name: "Defender overview" })).toBeInTheDocument();
  });

  it("preserves same-scope patch preview LKG and retry focus after refresh failure", async () => {
    api.exposureOverview.mockResolvedValue(overviewEnvelope("stale"));
    api.patchPriorities
      .mockResolvedValueOnce(envelope([patchPriority]))
      .mockRejectedValueOnce(new Error("Patch refresh failed"));
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>,
    );

    expect(await screen.findByText("KB600001")).toBeInTheDocument();
    const retry = screen.getByRole("button", {
      name: "Retry Patch priority preview",
    });
    retry.focus();
    fireEvent.click(retry);

    await waitFor(() => {
      expect(api.patchPriorities).toHaveBeenCalledTimes(2);
    });
    expect(document.activeElement).toBe(retry);
    expect(screen.getByText("KB600001")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Patch priority preview state"),
    ).toHaveTextContent("Patch refresh failed");
  });

  it("renders unknown summary values as em dashes with explanatory detail", async () => {
    api.summary.mockResolvedValue(envelope({}));
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>,
    );

    const criticalMetric = await screen.findByText("Critical CVEs");
    const card = criticalMetric.closest("article");
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByLabelText("Critical CVEs value")).toHaveTextContent("—");
    expect(card).toHaveTextContent("CVE total unavailable");
    expect(card).not.toHaveTextContent("0 CVEs");
  });

  it("shows whole-page unavailability only when every authorized section has failed", async () => {
    for (const method of [
      "summary",
      "patchPriorities",
      "assetExposures",
      "defenderOverview",
      "slaCompliance",
      "riskExceptions",
    ] as const) {
      api[method].mockRejectedValue(new Error(`${method} unavailable`));
    }
    render(
      <ScopeProvider>
        <ExposurePage />
      </ScopeProvider>,
    );

    expect(
      await screen.findByText("Exposure intelligence is unavailable"),
    ).toBeInTheDocument();
  });
});
