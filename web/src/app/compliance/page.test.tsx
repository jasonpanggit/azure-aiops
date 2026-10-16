import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { designPolicy, saveDesignPolicy, decideException, exposures, gaps, ruleFindings, topology, policyDeviations, securityDeviations, configurationDrift, complianceSummary, buildComplianceCopilotContext } = vi.hoisted(() => ({
  designPolicy: vi.fn(), saveDesignPolicy: vi.fn(), decideException: vi.fn(),
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
      designPolicy, saveDesignPolicy, decideException,
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
const savedPolicy = {
  revision: 0, policy_revision: 0, scope: {}, exceptions: [], audit: [],
  policy: {
    name: "Approved hub-spoke landing-zone baseline", requiredHubRouting: true,
    firewallInspectionRequired: true, environmentIsolationRequired: true,
    allowedPorts: "443, 1433, 5671", privateEndpointRequiredFor: "microsoft.sql, microsoft.storage, microsoft.keyvault, microsoft.web",
    requiredDnsZones: "privatelink.database.windows.net, privatelink.blob.core.windows.net, privatelink.vaultcore.azure.net",
    loggingRequired: true, ownerTag: "owner", allowCrossSubscriptionPeering: false,
  },
};

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
    designPolicy.mockResolvedValue(envelope(savedPolicy));
    saveDesignPolicy.mockImplementation((_revision, policy) => Promise.resolve(envelope({ ...savedPolicy, revision: 1, policy_revision: 1, policy })));
    decideException.mockImplementation(body => Promise.resolve(envelope({
      ...savedPolicy, revision: 2,
      exceptions: [{ ...body, active: true, revoked_at: "", approved_by: "authenticated-admin" }],
    })));
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

    await waitFor(() => expect(buildComplianceCopilotContext).toHaveBeenLastCalledWith(
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
    ));
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
    expect((await screen.findAllByText("Firewall bypass path")).length).toBeGreaterThan(0);
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
    expect(window.localStorage.getItem("aiops.architecture-policy.v1")).toBeNull();
    fireEvent.change(screen.getByLabelText("Policy change reason"), { target: { value: "Reviewed by architecture board" } });
    fireEvent.click(screen.getByRole("button", { name: "Save policy revision" }));
    await waitFor(() => expect(saveDesignPolicy).toHaveBeenCalledWith(0, expect.objectContaining({ name: "Payroll landing-zone policy" }), "Reviewed by architecture board", {}));
    await screen.findByText(/Policy saved/);

    fireEvent.change(screen.getByLabelText("Exception owner"), { target: { value: "Network CAB" } });
    fireEvent.change(screen.getByLabelText("Risk acceptance reason"), { target: { value: "Temporary migration exception" } });
    fireEvent.change(screen.getByLabelText("Expires at (00:00 UTC)"), { target: { value: "2026-12-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept selected risk" }));

    await waitFor(() => expect(decideException).toHaveBeenCalledWith(expect.objectContaining({
      expected_revision: 1, action: "accept", violationId: "public-sql-1",
      reason: "Temporary migration exception", expiresAt: "2026-12-31T00:00:00Z",
    }), {}));
    expect(await screen.findByText("Accepted risk")).toBeInTheDocument();
    expect(window.localStorage.getItem("aiops.architecture-exceptions.v1")).toBeNull();
  });

  it("never treats browser-local acceptance as approved and surfaces unavailable storage", async () => {
    window.localStorage.setItem("aiops.architecture-exceptions.v1", JSON.stringify([{ violationId: "gap-1", expiresAt: "2099-01-01" }]));
    designPolicy.mockRejectedValueOnce(new Error("Durable policy unavailable"));
    renderPage();
    expect(await screen.findByText(/Durable policy unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("No policy violations")).not.toBeInTheDocument();
    expect(screen.queryByText("Accepted risk")).not.toBeInTheDocument();
    expect(screen.queryByText("Accepted risk")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept selected risk" })).toBeDisabled();
    expect(screen.getByText(/Posture score unavailable until/)).toBeInTheDocument();
  });

  it("retains a rejected draft and shows revision conflicts rather than reporting a save", async () => {
    saveDesignPolicy.mockRejectedValueOnce(new Error("Policy changed; reload and review"));
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Policy pack name")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Policy pack name"), { target: { value: "Uncommitted draft" } });
    fireEvent.change(screen.getByLabelText("Policy change reason"), { target: { value: "Review" } });
    fireEvent.click(screen.getByRole("button", { name: "Save policy revision" }));
    expect(await screen.findByText("Policy changed; reload and review")).toBeInTheDocument();
    expect(screen.getByLabelText("Policy pack name")).toHaveValue("Uncommitted draft");
  });

  it("previews draft field and finding changes without changing current evidence or saving", async () => {
    renderPage();
    await screen.findByText(/Same-evidence preview/);
    fireEvent.click(screen.getByLabelText("Logging required"));
    const explanation = screen.getByRole("region", { name: "Policy change explanation" });
    expect(within(explanation).getByText(/draft changes 1 field/)).toBeInTheDocument();
    expect(within(explanation).getByText(/0 added, 1 removed, 0 reclassified/)).toBeInTheDocument();
    expect(within(explanation).getByText(/does not validate actual log delivery/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Missing logging evidence/ })).toBeInTheDocument();
    expect(saveDesignPolicy).not.toHaveBeenCalled();
    expect(decideException).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("Required hub routing"));
    expect(within(explanation).getByText(/does not re-evaluate routes/)).toBeInTheDocument();
    expect(within(explanation).getByText(/1 removed/)).toBeInTheDocument();
  });

  it("shows partial framework associations, exact provider controls and explicit unmapped evidence", async () => {
    const row = { deviation_id: "dev-1", kind: "policy", observed_at: "2026-10-16T06:00:00Z", severity: "high",
      control: "NS-1", status: "open", resource: "resource-1", application: "", business_service: "",
      environment: "", business_criticality: "", subscription: "sub-1" };
    policyDeviations.mockResolvedValue({ ...envelope([row, { ...row, deviation_id: "dev-2", control: "CIS 1.2" }]),
      pagination: { offset: 0, limit: 2, total: 101, next_offset: 2 } });
    renderPage();
    await screen.findByText(/2 loaded \/ 101 reported/);
    const framework = screen.getByRole("region", { name: "Framework evidence coverage" });
    expect(within(framework).getByText(/not a control audit/)).toBeInTheDocument();
    expect(within(framework).getByText("Unmapped provider controls (1)")).toBeInTheDocument();
    expect(within(framework).getAllByText("Not assessed").length).toBeGreaterThan(0);
    fireEvent.click(within(framework).getByRole("link", { name: "Review LT findings" }));
    expect(screen.getByRole("combobox", { name: "Local finding domain" })).toHaveValue("LT");
    expect(screen.getByRole("button", { name: /Missing logging evidence/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Any-any NSG rule/ })).not.toBeInTheDocument();
    expect(within(framework).getByRole("link", { name: "MCSB v1 catalog and mapping limitations" })).toHaveAttribute("href",
      "https://learn.microsoft.com/en-us/security/benchmark/azure/overview-mcsb-v1");
  });

  it("does not turn unavailable providers into zero deviations, no drift or passed framework coverage", async () => {
    policyDeviations.mockRejectedValue(new Error("Policy evidence unavailable"));
    securityDeviations.mockRejectedValue(new Error("Security evidence unavailable"));
    configurationDrift.mockRejectedValue(new Error("Drift evidence unavailable"));
    renderPage();
    await screen.findByText("Configuration drift unavailable");
    expect(screen.queryByText("No configuration drift")).not.toBeInTheDocument();
    expect(screen.queryByText("No open governed deviations in loaded pages")).not.toBeInTheDocument();
    expect(screen.getByText("Governed evidence incomplete")).toBeInTheDocument();
    const framework = screen.getByRole("region", { name: "Framework evidence coverage" });
    expect(within(framework).getAllByText("Unavailable")).toHaveLength(12);
    expect(within(framework).getAllByText("Evidence incomplete").length).toBeGreaterThan(0);
  });

  it("requires actual field changes after initial policy application before allowing another save", async () => {
    designPolicy.mockResolvedValue(envelope({ ...savedPolicy, revision: 5, policy_revision: 2 }));
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Policy pack name")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Policy change reason"), { target: { value: "Review" } });
    expect(screen.getByRole("button", { name: "Save policy revision" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Policy pack name"), { target: { value: "Changed title" } });
    expect(screen.getByRole("button", { name: "Save policy revision" })).toBeEnabled();
  });

  it("distinguishes recorded server diffs from historical unreported changes", async () => {
    designPolicy.mockResolvedValue(envelope({
      ...savedPolicy, audit: [
        { revision: 1, actor: "old-admin", at: "2026-10-15T06:00:00Z", action: "replace_policy", reason: "Historical" },
        { revision: 2, actor: "current-admin", at: "2026-10-16T06:00:00Z", action: "replace_policy", reason: "Changed logging",
          policy_diff: [{ field: "loggingRequired", before: true, after: false }], invalidated_exception_ids: ["exception-1"] },
      ],
    }));
    renderPage();
    await screen.findByText("Logging required: true → false");
    expect(screen.getByText("Historical field differences were not recorded for this revision.")).toBeInTheDocument();
    expect(screen.getByText("Historical exception invalidation count unreported.")).toBeInTheDocument();
    expect(screen.getByText("1 active exceptions invalidated by this save.")).toBeInTheDocument();
  });

  it("ignores a stale reload response after a newer policy save", async () => {
    let complete: (value: unknown) => void = () => { throw new Error("Reload has not started"); };
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Policy pack name")).toBeEnabled());
    designPolicy.mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    fireEvent.change(screen.getByLabelText("Policy pack name"), { target: { value: "New saved policy" } });
    fireEvent.change(screen.getByLabelText("Policy change reason"), { target: { value: "Review" } });
    fireEvent.click(screen.getByRole("button", { name: "Reload saved policy" }));
    await waitFor(() => expect(designPolicy).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "Save policy revision" }));
    await screen.findByText(/Policy saved/);
    await act(async () => { complete(envelope(savedPolicy)); });
    expect(screen.getByLabelText("Policy pack name")).toHaveValue("New saved policy");
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
