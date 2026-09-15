import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { exposures, gaps, ruleFindings, topology, policyDeviations, securityDeviations, configurationDrift, complianceSummary, buildComplianceCopilotContext } = vi.hoisted(() => ({
  exposures: vi.fn(),
  gaps: vi.fn(),
  ruleFindings: vi.fn(),
  topology: vi.fn(),
  policyDeviations: vi.fn(),
  securityDeviations: vi.fn(),
  configurationDrift: vi.fn(),
  complianceSummary: vi.fn(),
  buildComplianceCopilotContext: vi.fn(),
}));

vi.mock("@/lib/services", async () => {
  const actual = await vi.importActual<typeof import("@/lib/services")>("@/lib/services");
  return {
    buildCopilotSnapshot: actual.buildCopilotSnapshot,
    copilotEvidenceRows: () => [],
    isCanonicalAzureResourceId: actual.isCanonicalAzureResourceId,
    networkApi: { topology, gaps, ruleFindings },
    vulnerabilityApi: { exposures },
    complianceApi: {
      policyDeviations,
      securityDeviations,
      configurationDrift,
      summary: complianceSummary,
    },
  };
});

vi.mock("@/lib/copilot/page-adapters", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/copilot/page-adapters")>();
  return {
    ...actual,
    buildComplianceCopilotContext,
  };
});

import CompliancePage from "./page";

const envelope = <T,>(data: T) => ({
  data,
  evidence: [{ source_engine: "ARG", source_table: "resources", timestamp: "2026-01-01T10:00:00Z", confidence: "high", freshness: "fresh" }],
  scope: {},
  knowledge_version: "graph-1",
});

const PRIVATE_ENDPOINT_TARGET = "/subscriptions/sub-1/resourceGroups/rg-network/providers/Microsoft.Network/privateEndpoints/cosmos-pe";

function renderPage() {
  return render(
    <ScopeProvider>
      <CompliancePage />
    </ScopeProvider>
  );
}

describe("Architecture Compliance and Security Posture Intelligence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    topology.mockResolvedValue(envelope({
      topology: {
        hubs: [],
        spokes: [],
        isolated: [],
        links: [{
          local_vnet_id: "vnet-dev",
          remote_vnet_id: "vnet-prod",
          local_connection_id: "dev",
          remote_connection_id: "prod",
          is_bidirectional: true,
          is_healthy: true,
          is_cross_subscription: true,
          local_state: "Connected",
          remote_state: "Connected",
          allow_forwarded_traffic: false,
          allow_gateway_transit: false,
          use_remote_gateways: false,
          remote_vnet_observed: true,
        }],
        shared_services: [],
        unresolved_peer_vnet_ids: [],
        connection_ids: ["prod"],
        counts: {},
        resources: [{
          id: "sql-1",
          name: "payroll-sql",
          entity_type: "microsoft.sql/servers",
          subscription_id: "sub-1",
          resource_group: "rg-payroll",
          location: "eastus",
          connection_id: "prod",
          environment: "prod",
          business_service: "Payroll",
          application: "Payroll API",
          owner: "",
          tags: {},
          details: { publicNetworkAccess: "Enabled" },
        }],
        relationships: [],
      },
      summary: { connection_count: 1 },
    }));
    gaps.mockResolvedValue(envelope({
      gaps: [{ gap_id: "gap-1", category: "routing", severity: "high", title: "Firewall bypass path", detail: "Spoke route bypasses hub firewall", resource_id: "route-1", resource_name: "route", resource_type: "routeTable", evidence: {}, recommendation: "Restore hub route", basis: "observed UDR", connection_id: "prod", subscription_id: "sub-1", environment: "prod" }],
      intended_design_declared: true,
      summary: {},
    }));
    ruleFindings.mockResolvedValue(envelope({
      findings: [{ finding_id: "rule-1", category: "nsg", severity: "high", rule_id: "nsg-rule-1", rule_name: "AnyAny", control: "nsg", control_id: "nsg-1", title: "Any-any NSG rule", detail: "0.0.0.0/0 to * on 3389", evidence: {}, recommendation: "Narrow source and port", connection_id: "prod", subscription_id: "sub-1", environment: "prod" }],
      summary: {},
    }));
    exposures.mockResolvedValue(envelope([{
      cve_id: "CVE-2026-0001",
      severity: "critical",
      missing_kb: "KB500",
      affected_server_count: 2,
      affected_application_count: 1,
      affected_business_service_count: 1,
      reachable_server_count: 1,
      exploit_signal: "known exploited",
      internet_exposed: true,
      critical_business_count: 1,
      priority_score: 90,
      expected_risk_reduction: 60,
      recommended_patch: "Install KB500",
      epss_score: 0.9,
      is_known_exploited: true,
      finding_ids: ["vf-1"],
    }]));
    policyDeviations.mockResolvedValue(envelope([]));
    securityDeviations.mockResolvedValue(envelope([]));
    configurationDrift.mockResolvedValue(envelope([]));
    complianceSummary.mockResolvedValue(envelope({}));
    buildComplianceCopilotContext.mockReturnValue({
      requestedScope: {},
      snapshot: {
        version: "1",
        page_kind: "governance",
        page_id: "compliance-posture",
        selected_resources: [],
        filters: {},
        freshness: [],
        scope: { declared: {}, authorized: true },
        evidence: [],
        question: "Summarize the visible page evidence.",
        rechecks: [],
      },
      starterQuestions: [],
    });
  });

  it("passes evaluated violations and governed evidence to the pure adapter", async () => {
    renderPage();

    await waitFor(() => expect(buildComplianceCopilotContext).toHaveBeenCalled());
    expect(buildComplianceCopilotContext).toHaveBeenLastCalledWith(
      expect.objectContaining({
        scope: {},
        policyName: "Approved hub-spoke landing-zone baseline",
        selectedId: null,
        violations: expect.arrayContaining([
          expect.objectContaining({ id: "gap-1" }),
          expect.objectContaining({ id: "rule-1" }),
        ]),
        governedDeviations: [],
      }),
    );
  });

  it("hands a canonical network finding to remediation as bounded review context", async () => {
    gaps.mockResolvedValue(envelope({
      gaps: [{
        gap_id: "gap-private-endpoint-policy",
        category: "private endpoint",
        severity: "high",
        title: "Private endpoint network policy gap",
        detail: "The selected private endpoint requires a network-owner review.",
        resource_id: PRIVATE_ENDPOINT_TARGET,
        resource_name: "cosmos-pe",
        resource_type: "microsoft.network/privateendpoints",
        evidence: { arbitrary: "must not cross the URL boundary" },
        recommendation: "Review private endpoint subnet policy and DNS linkage.",
        basis: "Observed private endpoint configuration",
        connection_id: "prod",
        subscription_id: "sub-1",
        environment: "prod",
      }],
      intended_design_declared: true,
      summary: {},
    }));

    renderPage();

    const href = (await screen.findByRole("link", { name: "Open remediation" })).getAttribute("href");
    const handoff = new URL(href ?? "", "https://aiops.invalid");
    expect(handoff.pathname).toBe("/remediation");
    expect(handoff.searchParams.get("resource_key")).toBe(PRIVATE_ENDPOINT_TARGET);
    expect(handoff.searchParams.get("review_source")).toBe("compliance");
    expect(handoff.searchParams.get("finding_type")).toBe("missing_private_endpoint");
    expect(handoff.searchParams.get("finding_severity")).toBe("high");
    expect(handoff.searchParams.get("finding_title")).toBe("Private endpoint network policy gap");
    expect(handoff.searchParams.get("recommendation")).toBe("Review private endpoint subnet policy and DNS linkage.");
    expect(Array.from(handoff.searchParams.keys()).sort()).toEqual([
      "finding_severity",
      "finding_title",
      "finding_type",
      "recommendation",
      "resource_key",
      "review_source",
    ]);
  });

  it("fails closed to a resource-only handoff when review text exceeds its bound", async () => {
    gaps.mockResolvedValue(envelope({
      gaps: [{
        gap_id: "gap-private-endpoint-policy",
        category: "private endpoint",
        severity: "high",
        title: "T".repeat(201),
        detail: "The selected private endpoint requires a network-owner review.",
        resource_id: PRIVATE_ENDPOINT_TARGET,
        resource_name: "cosmos-pe",
        resource_type: "microsoft.network/privateendpoints",
        evidence: {},
        recommendation: "Review private endpoint subnet policy and DNS linkage.",
        basis: "Observed private endpoint configuration",
        connection_id: "prod",
        subscription_id: "sub-1",
        environment: "prod",
      }],
      intended_design_declared: true,
      summary: {},
    }));

    renderPage();

    const href = (await screen.findByRole("link", { name: "Open remediation" })).getAttribute("href");
    const handoff = new URL(href ?? "", "https://aiops.invalid");
    expect(handoff.searchParams.get("resource_key")).toBe(PRIVATE_ENDPOINT_TARGET);
    expect(Array.from(handoff.searchParams.keys())).toEqual(["resource_key"]);
  });

  it("evaluates posture, maps violations to business context, and governs exceptions", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "Violations" })).toBeInTheDocument();
    expect(screen.getAllByText("Firewall bypass path").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Any-any NSG rule").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Public PaaS exposure").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /Public PaaS exposure/ }));
    await waitFor(() => expect(buildComplianceCopilotContext).toHaveBeenLastCalledWith(
      expect.objectContaining({ selectedId: "public-sql-1" }),
    ));
    expect(screen.getAllByText("Payroll").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/CVE-2026-0001/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Open remediation" })).toHaveAttribute("href", "/remediation");
    expect(screen.getByRole("button", { name: "Ask Copilot about posture" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Policy pack name"), { target: { value: "Payroll landing-zone policy" } });
    expect(window.localStorage.getItem("aiops.architecture-policy.v1")).toContain("Payroll landing-zone policy");

    fireEvent.change(screen.getByLabelText("Exception owner"), { target: { value: "Network CAB" } });
    fireEvent.change(screen.getByLabelText("Risk acceptance reason"), { target: { value: "Temporary migration exception" } });
    fireEvent.change(screen.getByLabelText("Expires at"), { target: { value: "2026-12-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept selected risk" }));

    await waitFor(() => expect(window.localStorage.getItem("aiops.architecture-exceptions.v1")).toContain("Temporary migration exception"));
    expect(screen.getByText("Accepted risk")).toBeInTheDocument();
  });

  it("deduplicates repeated topology resources before rendering violations", async () => {
    const duplicateResource = {
      id: "sql-duplicate",
      name: "payroll-sql",
      entity_type: "microsoft.sql/servers",
      subscription_id: "sub-1",
      resource_group: "rg-payroll",
      location: "eastus",
      connection_id: "prod",
      environment: "prod",
      business_service: "Payroll",
      application: "Payroll API",
      owner: "",
      tags: {},
      details: { publicNetworkAccess: "Enabled" },
    };
    topology.mockResolvedValue(envelope({
      topology: {
        hubs: [],
        spokes: [],
        isolated: [],
        links: [],
        shared_services: [],
        unresolved_peer_vnet_ids: [],
        connection_ids: ["prod"],
        counts: {},
        resources: [duplicateResource, { ...duplicateResource }],
        relationships: [],
      },
      summary: { connection_count: 1 },
    }));

    renderPage();

    await waitFor(() => expect(screen.getAllByText("Public PaaS exposure")).toHaveLength(1));
    expect(screen.getAllByText("Missing logging evidence")).toHaveLength(1);
  });
});
