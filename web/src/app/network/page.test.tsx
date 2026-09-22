import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider, useScope } from "@/lib/scope-context";
import {
  buildGapsEnvelope,
  buildNetworkSummary,
  buildRuleFindingsEnvelope,
  buildTopologyEnvelope,
} from "@/test/network-fixtures";
import { ApiError } from "@/lib/types";
import type {
  FlowResult,
  NetworkDesignPolicy,
  NetworkTopologyResource,
} from "@/lib/types";
import type { ScopeSelection } from "@/lib/scope";

const mocks = vi.hoisted(() => ({
  topology: vi.fn(),
  summary: vi.fn(),
  hubDependents: vi.fn(),
  firewallBypass: vi.fn(),
  trafficFlow: vi.fn(),
  gaps: vi.fn(),
  ruleFindings: vi.fn(),
  policy: vi.fn(),
  updatePolicy: vi.fn(),
  previewPolicy: vi.fn(),
  buildNetworkCopilotContext: vi.fn(),
  investigateContext: vi.fn(),
}));

vi.mock("@/lib/services", () => ({
  networkApi: mocks,
  copilotApi: { investigateContext: mocks.investigateContext },
  buildCopilotSnapshot: vi.fn((value) => value),
  copilotEvidenceRows: vi.fn(() => []),
}));

vi.mock("@/lib/copilot/page-adapters", () => ({
  buildNetworkCopilotContext: mocks.buildNetworkCopilotContext,
}));

vi.mock("@/components/ui/CopilotDrawer", () => ({
  CopilotDrawer: () => null,
}));

vi.mock("@/components/network/TopologyWorkspace", () => ({
  TopologyWorkspace: ({
    topology,
    gaps,
    ruleFindings,
    detailLevel,
    onDetailLevelChange,
    onSelectionChange,
    findingsTruncated,
  }: {
    topology: unknown;
    gaps: unknown[];
    ruleFindings: unknown[];
    detailLevel: "summary" | "full";
    onDetailLevelChange: (detail: "summary" | "full") => void;
    onSelectionChange?: (selection: {
      node: {
        id: string;
        label: string;
        kind: string;
        entityType: string;
      } | null;
      edge: null;
    }) => void;
    findingsTruncated?: boolean;
  }) => (
    <div data-testid="topology-workspace">
      <span>{topology ? "Topology canvas" : "No topology"}</span>
      <span>{gaps.length} topology gaps</span>
      <span>{ruleFindings.length} topology findings</span>
      <span>Detail: {detailLevel}</span>
      <span data-testid="topology-workspace-page-truncation">
        {findingsTruncated === undefined
          ? "Page truncation not forwarded"
          : `Page truncation forwarded: ${String(findingsTruncated)}`}
      </span>
      <button type="button" onClick={() => onDetailLevelChange("full")}>
        Test full detail
      </button>
      <button
        type="button"
        onClick={() =>
          onSelectionChange?.({
            node: {
              id: "/subscriptions/sub-a/resourceGroups/rg-network/providers/Microsoft.Network/virtualNetworks/hub-vnet",
              label: "hub-vnet",
              kind: "hub",
              entityType: "VNet",
            },
            edge: null,
          })}
      >
        Select test topology node
      </button>
    </div>
  ),
}));

import NetworkPage from "./page";

const policy: NetworkDesignPolicy = {
  name: "Default policy",
  description: "Fixture policy",
  is_declared: true,
  source_path: "fixture",
  hub_vnet_names: [],
  require_firewall_in_hub: true,
  require_default_route_to_firewall: true,
  require_nsg_on_every_subnet: true,
  forbid_spoke_to_spoke_peering: true,
  forbid_public_ip_on_spoke_nics: true,
  require_private_endpoint_for_services: [],
  require_private_dns_zone_link: true,
  require_bidirectional_peering: true,
  approved_peerings: [],
  exempt_subnet_names: [],
  exempt_vnet_names: [],
  rules: [],
};

const declarativeRule = {
  rule_id: "subnets-need-vnet",
  name: "Subnets require a VNet",
  description: "Every subnet belongs to a VNet.",
  category: "custom",
  severity: "medium" as const,
  enabled: true,
  parameters: {
    target: "subnets",
    assert: [{ field: "vnet_id", exists: true }],
  },
  evaluated: true,
  declarative: true,
};

function policyEnvelope(overrides: Partial<NetworkDesignPolicy> = {}) {
  return {
    data: {
      ...policy,
      supported_targets: ["subnets", "vnets"],
      supported_operators: ["exists", "equals"],
      ...overrides,
    },
    evidence: [],
    scope: {},
    knowledge_version: "network-fixture-v1",
    warnings: [],
  };
}

function bypassEnvelope() {
  return {
    data: { gaps: [], count: 0 },
    evidence: [],
    scope: {},
    knowledge_version: "network-fixture-v1",
    warnings: [],
  };
}

function ScopeChangeButton() {
  const { setScope } = useScope();
  return (
    <button
      type="button"
      onClick={() => setScope({ subscription: ["sub-narrow"] })}
    >
      Narrow test scope
    </button>
  );
}

function renderPage(withScopeControl = false) {
  return render(
    <ScopeProvider>
      <NetworkPage />
      {withScopeControl && <ScopeChangeButton />}
    </ScopeProvider>,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function endpointResource(
  id: string,
  name: string,
  entityType: string,
  subscriptionId = "sub-a",
  resourceGroup = "rg-network",
): NetworkTopologyResource {
  return {
    id,
    name,
    entity_type: entityType,
    subscription_id: subscriptionId,
    resource_group: resourceGroup,
    location: "eastus",
    connection_id: `conn-${subscriptionId}`,
    environment: "test",
    business_service: "",
    application: "",
    owner: "",
    tags: {},
    details: {},
  };
}

function topologyWithEndpoints(
  resources: NetworkTopologyResource[],
  relationships: Array<{
    id: string;
    source: string;
    target: string;
    relationship_type: string;
    label: string;
    details: Record<string, unknown>;
  }> = [],
) {
  const envelope = buildTopologyEnvelope(0, 0);
  envelope.data.topology.resources = resources;
  envelope.data.topology.relationships = relationships;
  return envelope;
}

function flowEnvelope(
  source: string,
  destination: string,
  overrides: Partial<FlowResult> = {},
) {
  const endpoint = (raw: string, isInternet = false) => ({
    raw,
    ip_address: "",
    subnet_id: "",
    vnet_id: "",
    nsg_id: "",
    resource_id: raw,
    environment: "",
    name: isInternet ? "Internet" : raw,
    is_internet: isInternet,
    resolved: true,
  });
  const data: FlowResult = {
    query: {
      source,
      destination,
      port: 443,
      protocol: "TCP",
      environment_scope: "",
    },
    source: endpoint(source),
    destination: endpoint(
      destination,
      destination.toLowerCase() === "internet" || destination.includes("."),
    ),
    verdict: "allowed",
    hops: [],
    missing_enforcement_points: [],
    unknowns: [],
    path_summary: `${source} => ${destination}: allowed`,
    ...overrides,
  };
  return {
    data,
    evidence: [],
    scope: {},
    knowledge_version: "network-fixture-v1",
    warnings: [],
  };
}

function primeSuccessfulLoaders(gapTotal = 340, findingTotal = 620) {
  const topology = buildTopologyEnvelope();
  topology.data.summary = buildNetworkSummary({
    gap_count: gapTotal,
    rule_finding_count: findingTotal,
  });
  mocks.topology.mockResolvedValue(topology);
  mocks.gaps.mockImplementation(
    (_scope, options: { offset: number; limit: number } = { offset: 0, limit: 100 }) =>
      Promise.resolve(buildGapsEnvelope(gapTotal, options.offset, options.limit)),
  );
  mocks.ruleFindings.mockImplementation(
    (_scope, options: { offset: number; limit: number } = { offset: 0, limit: 100 }) =>
      Promise.resolve(buildRuleFindingsEnvelope(findingTotal, options.offset, options.limit)),
  );
  mocks.firewallBypass.mockResolvedValue(bypassEnvelope());
  mocks.policy.mockResolvedValue(policyEnvelope());
  mocks.buildNetworkCopilotContext.mockReturnValue({
    requestedScope: {},
    snapshot: {
      version: "1",
      page_kind: "network",
      page_id: "network-topology",
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
  mocks.investigateContext.mockReturnValue(new Promise(() => undefined));
}

describe("Network path endpoint selectors", () => {
  const subnetA =
    "/subscriptions/sub-a/resourcegroups/rg-a/providers/microsoft.network/virtualnetworks/vnet-a/subnets/apps";
  const subnetB =
    "/subscriptions/sub-b/resourcegroups/rg-b/providers/microsoft.network/virtualnetworks/vnet-b/subnets/apps";
  const subnetC =
    "/subscriptions/sub-a/resourcegroups/rg-network/providers/microsoft.network/virtualnetworks/vnet-c/subnets/apps";
  const nic =
    "/subscriptions/sub-a/resourcegroups/rg-a/providers/microsoft.network/networkinterfaces/vm-a-nic";
  const vm =
    "/subscriptions/sub-a/resourcegroups/rg-a/providers/microsoft.compute/virtualmachines/vm-a";

  beforeEach(() => {
    vi.clearAllMocks();
    primeSuccessfulLoaders();
    mocks.buildNetworkCopilotContext.mockReturnValue({
      requestedScope: {},
      snapshot: {
        version: "1",
        page_kind: "network",
        page_id: "network-topology",
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
    mocks.topology.mockResolvedValue(
      topologyWithEndpoints(
        [
          endpointResource(subnetA, "apps", "Subnet"),
          endpointResource(subnetB, "apps", "Subnet", "sub-b", "rg-b"),
          endpointResource(subnetC, "apps", "Subnet"),
          endpointResource(nic, "vm-a-nic", "NetworkInterface"),
          endpointResource(vm, "vm-a", "VirtualMachine"),
          endpointResource(
            "/subscriptions/sub-a/resourcegroups/rg-a/providers/microsoft.network/networksecuritygroups/apps-nsg",
            "apps-nsg",
            "NetworkSecurityGroup",
          ),
        ],
        [
          {
            id: "nic-attached-to-vm",
            source: nic,
            target: vm,
            relationship_type: "attached_to",
            label: "attached to workload",
            details: {},
          },
        ],
      ),
    );
    mocks.trafficFlow.mockResolvedValue(flowEnvelope(subnetA, subnetB));
  });

  it("offers only scoped resolver-safe resources with canonical values and disambiguated labels", async () => {
    renderPage();

    const source = await screen.findByRole("combobox", {
      name: "Source endpoint",
    });
    expect(
      within(source).getByRole("option", {
        name: "apps — Subnet · sub-a / rg-network / vnet-a",
      }),
    ).toHaveValue(subnetA);
    expect(
      within(source).getByRole("option", {
        name: "apps — Subnet · sub-b / rg-b / vnet-b",
      }),
    ).toHaveValue(subnetB);
    expect(
      within(source).getByRole("option", {
        name: "apps — Subnet · sub-a / rg-network / vnet-c",
      }),
    ).toHaveValue(subnetC);
    expect(
      within(source).getByRole("option", {
        name: "vm-a — Virtual Machine",
      }),
    ).toHaveValue(vm);
    expect(
      within(source).queryByRole("option", { name: /apps-nsg/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Destination endpoint" }),
    ).not.toBe(source);
  });

  it("submits selected resources by canonical ARM ID", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Source endpoint" }),
      subnetA,
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Destination endpoint" }),
      subnetB,
    );
    await user.click(screen.getByRole("button", { name: "Analyze path" }));

    await waitFor(() =>
      expect(mocks.trafficFlow).toHaveBeenCalledWith({
        source: subnetA,
        destination: subnetB,
        port: 443,
        protocol: "TCP",
        scope: {},
      }),
    );
  });

  it("reveals manual inputs only in manual mode and sends Internet unchanged", async () => {
    const user = userEvent.setup();
    mocks.trafficFlow.mockResolvedValue(flowEnvelope(subnetA, "internet"));
    renderPage();

    const source = await screen.findByRole("combobox", {
      name: "Source endpoint",
    });
    const destination = screen.getByRole("combobox", {
      name: "Destination endpoint",
    });
    expect(
      screen.queryByRole("textbox", { name: "Manual source endpoint" }),
    ).not.toBeInTheDocument();

    await user.selectOptions(source, "__enter_manually__");
    await user.type(
      screen.getByRole("textbox", { name: "Manual source endpoint" }),
      "10.0.0.4",
    );
    await user.selectOptions(source, subnetA);
    expect(
      screen.queryByRole("textbox", { name: "Manual source endpoint" }),
    ).not.toBeInTheDocument();

    await user.selectOptions(destination, "__enter_manually__");
    await user.type(
      screen.getByRole("textbox", { name: "Manual destination endpoint" }),
      "internet",
    );
    await user.click(screen.getByRole("button", { name: "Analyze path" }));

    await waitFor(() =>
      expect(mocks.trafficFlow).toHaveBeenCalledWith(
        expect.objectContaining({
          source: subnetA,
          destination: "internet",
        }),
      ),
    );

    await user.selectOptions(source, "__enter_manually__");
    await user.type(
      screen.getByRole("textbox", { name: "Manual source endpoint" }),
      "Internet",
    );
    await user.selectOptions(destination, subnetB);
    await user.click(screen.getByRole("button", { name: "Analyze path" }));

    await waitFor(() =>
      expect(mocks.trafficFlow).toHaveBeenLastCalledWith(
        expect.objectContaining({
          source: "Internet",
          destination: subnetB,
        }),
      ),
    );
  });

  it("presents Internet as a resolved external endpoint", async () => {
    const user = userEvent.setup();
    mocks.trafficFlow.mockResolvedValue(flowEnvelope(subnetA, "Internet"));
    renderPage();

    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Source endpoint" }),
      subnetA,
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Destination endpoint" }),
      "__enter_manually__",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Manual destination endpoint" }),
      "Internet",
    );
    await user.click(screen.getByRole("button", { name: "Analyze path" }));

    const destination = await screen.findByRole("article", {
      name: "Destination endpoint",
    });
    expect(destination).toHaveTextContent("External network endpoint");
    expect(destination).toHaveTextContent("Resolved");
    expect(destination).not.toHaveTextContent("Endpoint unresolved");
  });

  it("presents a public FQDN as a resolved external endpoint", async () => {
    const user = userEvent.setup();
    mocks.trafficFlow.mockResolvedValue(flowEnvelope(subnetA, "www.google.com"));
    renderPage();

    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Source endpoint" }),
      subnetA,
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Destination endpoint" }),
      "__enter_manually__",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Manual destination endpoint" }),
      "www.google.com",
    );
    await user.click(screen.getByRole("button", { name: "Analyze path" }));

    const destination = await screen.findByRole("article", {
      name: "Destination endpoint",
    });
    expect(destination).toHaveTextContent("External network endpoint");
    expect(destination).toHaveTextContent("External");
    expect(destination).toHaveTextContent("Resolved");
    expect(destination).not.toHaveTextContent("Environment unknown");
    expect(destination).not.toHaveTextContent("Endpoint unresolved");
  });

  it("shows partial resolution instead of a false fully-resolved claim", async () => {
    const user = userEvent.setup();
    mocks.trafficFlow.mockResolvedValue(
      flowEnvelope(subnetA, "Internet", {
        verdict: "indeterminate",
        unknowns: [],
      }),
    );
    renderPage();

    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Source endpoint" }),
      subnetA,
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Destination endpoint" }),
      "__enter_manually__",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Manual destination endpoint" }),
      "Internet",
    );
    await user.click(screen.getByRole("button", { name: "Analyze path" }));

    expect(await screen.findByText("Path partially resolved")).toBeInTheDocument();
    expect(screen.queryByText("Path fully resolved")).not.toBeInTheDocument();
    expect(screen.queryByText("No unresolved path elements.")).not.toBeInTheDocument();
    expect(screen.getByText(/observed controls were insufficient/i)).toBeInTheDocument();
  });

  it("explains relevant firewall rules when Internet is too broad for one decision", async () => {
    const user = userEvent.setup();
    mocks.trafficFlow.mockResolvedValue(
      flowEnvelope(subnetA, "Internet", {
        verdict: "indeterminate",
        unknowns: [
          "Internet is a destination category, not a specific host. Enter a public FQDN or IP to determine which observed firewall rule applies.",
        ],
        hops: [
          {
            stage: "firewall",
            control: "azure_firewall",
            control_id: "/firewalls/hub",
            decision: "unknown",
            rule_id: "",
            rule_name: "",
            priority: null,
            reason:
              "Internet is a destination category, not a specific host. Enter a public FQDN or IP to determine which observed firewall rule applies.",
            rule_analysis: [
              {
                collection_name: "application-rules",
                group_priority: 200,
                collection_priority: 100,
                rule_name: "allow-google",
                rule_type: "ApplicationRule",
                action: "Allow",
                protocols: ["Https"],
                destination_ports: ["443"],
                destinations: ["FQDN: www.google.com"],
                applicability: "specific_destination_required",
              },
            ],
          },
        ],
      }),
    );
    renderPage();

    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Source endpoint" }),
      subnetA,
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Destination endpoint" }),
      "__enter_manually__",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Manual destination endpoint" }),
      "Internet",
    );
    await user.click(screen.getByRole("button", { name: "Analyze path" }));

    expect(
      await screen.findByText("What the firewall rules allow or deny"),
    ).toBeInTheDocument();
    expect(screen.getByText("Allow — allow-google")).toBeInTheDocument();
    expect(
      screen.getByText(/group priority 200 · collection priority 100/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Destinations: FQDN: www.google.com/)).toBeInTheDocument();
    expect(
      screen.getByText(/specific public FQDN or IP is required/i),
    ).toBeInTheDocument();
  });

  it("names skipped controls in plain language and hides empty qualification panels", async () => {
    const user = userEvent.setup();
    mocks.trafficFlow.mockResolvedValue(
      flowEnvelope(subnetA, "Internet", {
        missing_enforcement_points: ["hub Azure Firewall"],
      }),
    );
    renderPage();

    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Source endpoint" }),
      subnetA,
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Destination endpoint" }),
      "__enter_manually__",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Manual destination endpoint" }),
      "Internet",
    );
    await user.click(screen.getByRole("button", { name: "Analyze path" }));

    expect(await screen.findByText("Controls this path skips")).toBeInTheDocument();
    expect(
      screen.getByText("This traffic is not inspected by: hub Azure Firewall."),
    ).toBeInTheDocument();
    expect(screen.getByText("Skips firewall inspection")).toBeInTheDocument();
    // A fully resolved path must not render a panel announcing unknowns.
    expect(screen.queryByText("What could not be determined")).not.toBeInTheDocument();
    expect(screen.queryByText("Known unknowns")).not.toBeInTheDocument();
  });

  it("reloads scoped options, clears selected resources, preserves active manual text, and resets results", async () => {
    const user = userEvent.setup();
    const narrowSubnet =
      "/subscriptions/sub-narrow/resourcegroups/rg-narrow/providers/microsoft.network/virtualnetworks/vnet/subnets/apps";
    mocks.topology.mockImplementation((scope: ScopeSelection) =>
      Promise.resolve(
        scope.subscription?.includes("sub-narrow")
          ? topologyWithEndpoints([
              endpointResource(
                narrowSubnet,
                "narrow-apps",
                "Subnet",
                "sub-narrow",
                "rg-narrow",
              ),
            ])
          : topologyWithEndpoints([
              endpointResource(subnetA, "apps", "Subnet"),
            ]),
      ),
    );
    mocks.trafficFlow.mockResolvedValue(flowEnvelope(subnetA, "internet"));
    renderPage(true);

    const source = await screen.findByRole("combobox", {
      name: "Source endpoint",
    });
    const destination = screen.getByRole("combobox", {
      name: "Destination endpoint",
    });
    await user.selectOptions(source, subnetA);
    await user.selectOptions(destination, "__enter_manually__");
    await user.type(
      screen.getByRole("textbox", { name: "Manual destination endpoint" }),
      "internet",
    );
    await user.click(screen.getByRole("button", { name: "Analyze path" }));
    expect(await screen.findByText("Reachability verdict")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Narrow test scope" }));

    await waitFor(() =>
      expect(
        within(source).getByRole("option", { name: "narrow-apps — Subnet" }),
      ).toHaveValue(narrowSubnet),
    );
    expect(source).toHaveValue("");
    expect(
      screen.getByRole("textbox", { name: "Manual destination endpoint" }),
    ).toHaveValue("internet");
    expect(screen.queryByText("Reachability verdict")).not.toBeInTheDocument();
    expect(mocks.topology).toHaveBeenLastCalledWith(
      { subscription: ["sub-narrow"] },
      { detail: "summary" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("reports scoped option failures without an unscoped fallback while preserving manual analysis", async () => {
    const user = userEvent.setup();
    mocks.topology.mockRejectedValue(new Error("scoped topology unavailable"));
    mocks.trafficFlow.mockResolvedValue(flowEnvelope("10.0.0.4", "internet"));
    renderPage();

    expect(
      await screen.findByRole("heading", {
        name: "Endpoint options are unavailable",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No unscoped resource list was substituted",
    );
    const source = screen.getByRole("combobox", { name: "Source endpoint" });
    const destination = screen.getByRole("combobox", {
      name: "Destination endpoint",
    });
    expect(within(source).getAllByRole("option")).toHaveLength(2);

    await user.selectOptions(source, "__enter_manually__");
    await user.type(
      screen.getByRole("textbox", { name: "Manual source endpoint" }),
      "10.0.0.4",
    );
    await user.selectOptions(destination, "__enter_manually__");
    await user.type(
      screen.getByRole("textbox", { name: "Manual destination endpoint" }),
      "internet",
    );
    await user.click(screen.getByRole("button", { name: "Analyze path" }));

    await waitFor(() => expect(mocks.trafficFlow).toHaveBeenCalledTimes(1));
  });

  it("announces scoped option loading and empty states", async () => {
    const pending = deferred<ReturnType<typeof buildTopologyEnvelope>>();
    mocks.topology.mockReturnValue(pending.promise);
    renderPage();

    expect(
      await screen.findByRole("heading", {
        name: "Loading scoped endpoint options",
      }),
    ).toBeInTheDocument();

    await act(async () => pending.resolve(topologyWithEndpoints([])));

    expect(
      await screen.findByRole("heading", {
        name: "No selectable network endpoints",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyze path" })).toBeDisabled();
  });

  it("warns when endpoint options are partial because relationships were truncated", async () => {
    const partial = topologyWithEndpoints([
      endpointResource(subnetA, "apps", "Subnet"),
    ]);
    partial.data.topology.coverage = {
      total: 1,
      returned: 1,
      truncated: false,
      nodes: { total: 1, returned: 1, truncated: false },
      relationships: { total: 2, returned: 1, truncated: true },
    };
    mocks.topology.mockResolvedValue(partial);
    renderPage();

    expect(
      await screen.findByRole("heading", {
        name: "Endpoint options are partial",
      }),
    ).toBeInTheDocument();
  });

  it("ignores an in-flight verdict after the endpoint query changes", async () => {
    const user = userEvent.setup();
    const pending = deferred<ReturnType<typeof flowEnvelope>>();
    mocks.trafficFlow.mockReturnValue(pending.promise);
    renderPage();

    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Source endpoint" }),
      subnetA,
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Destination endpoint" }),
      subnetB,
    );
    await user.click(screen.getByRole("button", { name: "Analyze path" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Destination endpoint" }),
      "__enter_manually__",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Manual destination endpoint" }),
      "internet",
    );
    await act(async () => pending.resolve(flowEnvelope(subnetA, subnetB)));

    expect(screen.queryByText("Reachability verdict")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Analyze path" })).toBeEnabled();
  });

  it("keeps analysis disabled until both endpoints exist and while a request is pending", async () => {
    const user = userEvent.setup();
    const pending = deferred<ReturnType<typeof flowEnvelope>>();
    mocks.trafficFlow.mockReturnValue(pending.promise);
    renderPage();

    const analyze = screen.getByRole("button", { name: "Analyze path" });
    expect(analyze).toBeDisabled();
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Source endpoint" }),
      subnetA,
    );
    expect(analyze).toBeDisabled();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Destination endpoint" }),
      subnetB,
    );
    expect(analyze).toBeEnabled();

    await user.click(analyze);
    expect(screen.getByRole("button", { name: "Analyzing…" })).toBeDisabled();
    await act(async () => pending.resolve(flowEnvelope(subnetA, subnetB)));
  });
});

describe("Network page honest totals and server pagination", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    primeSuccessfulLoaders();
    mocks.buildNetworkCopilotContext.mockReturnValue({
      requestedScope: {},
      snapshot: {
        version: "1",
        page_kind: "network",
        page_id: "network-topology",
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

  it("passes loaded topology collections and active pagination to the pure adapter", async () => {
    renderPage();

    await waitFor(() => expect(mocks.buildNetworkCopilotContext).toHaveBeenCalled());
    expect(mocks.buildNetworkCopilotContext).toHaveBeenLastCalledWith(
      expect.objectContaining({
        scope: {},
        tab: "flow",
        gapOffset: 0,
        gapLimit: 20,
        findingOffset: 0,
        findingLimit: 20,
        topology: expect.objectContaining({ data: expect.any(Object) }),
        gaps: expect.objectContaining({ data: expect.any(Object) }),
        findings: expect.objectContaining({ data: expect.any(Object) }),
        bypass: expect.objectContaining({ data: expect.any(Object) }),
      }),
    );
  });

  it("renders insights first without blocking page content while the request is unresolved", async () => {
    const pending = deferred<never>();
    mocks.investigateContext.mockReturnValue(pending.promise);

    renderPage();

    const insights = screen.getByRole("heading", { name: "Topology insights" });
    const evidence = await screen.findByLabelText("Data trust and provenance");
    expect(screen.getByText("Reviewing the bounded topology evidence…")).toBeInTheDocument();
    expect(screen.getByText("Observed network")).toBeInTheDocument();
    expect(
      insights.compareDocumentPosition(evidence) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("passes graph selection to the adapter and the top insight request", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Topology" }));
    await user.click(screen.getByRole("button", { name: "Select test topology node" }));

    await waitFor(() =>
      expect(mocks.buildNetworkCopilotContext).toHaveBeenLastCalledWith(
        expect.objectContaining({
          selection: expect.objectContaining({
            node: expect.objectContaining({
              label: "hub-vnet",
              entityType: "VNet",
            }),
          }),
        }),
      ),
    );
    await waitFor(() =>
      expect(mocks.investigateContext).toHaveBeenLastCalledWith(
        expect.objectContaining({
          question: expect.stringContaining("Selected selector: /subscriptions/sub-a/"),
        }),
      ),
    );
  });

  describe("Network page topology detail requests", () => {
    beforeEach(() => {
      vi.clearAllMocks();
      primeSuccessfulLoaders();
    });

    it("requests summary explicitly and sends every later chosen detail level", async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() =>
        expect(mocks.topology).toHaveBeenCalledWith(
          {},
          { detail: "summary" },
          { signal: expect.any(AbortSignal) },
        ),
      );
      await user.click(screen.getByRole("tab", { name: "Topology" }));
      await user.click(screen.getByRole("button", { name: "Test full detail" }));

      await waitFor(() =>
        expect(mocks.topology).toHaveBeenLastCalledWith(
          {},
          { detail: "full" },
          { signal: expect.any(AbortSignal) },
        ),
      );
    });

    it("retains the populated summary canvas and metrics while full detail is in flight", async () => {
      const user = userEvent.setup();
      const full = deferred<ReturnType<typeof buildTopologyEnvelope>>();
      mocks.topology
        .mockResolvedValueOnce(buildTopologyEnvelope())
        .mockImplementationOnce(() => full.promise);
      renderPage();

      await user.click(await screen.findByRole("tab", { name: "Topology" }));
      expect(screen.getByTestId("topology-workspace")).toHaveTextContent(
        "Topology canvas",
      );
      await user.click(screen.getByRole("button", { name: "Test full detail" }));
      await waitFor(() => expect(mocks.topology).toHaveBeenCalledTimes(2));

      expect(screen.getByTestId("topology-workspace")).toHaveTextContent(
        "Topology canvas",
      );
      expect(
        screen.getByTestId("topology-workspace").parentElement,
      ).toHaveAttribute("aria-busy", "true");
      expect(
        screen.getByText("Observed network").closest("article"),
      ).toHaveTextContent("1 / 1");

      await act(async () => {
        full.resolve(buildTopologyEnvelope());
        await full.promise;
      });
    });
  });

  it("keeps ordinary server-page ranges inside their owning tabs without a page warning", async () => {
    renderPage();

    const riskyRules = await screen.findByText("Broad or risky rules");
    const metric = riskyRules.closest("article");
    expect(metric).not.toBeNull();
    expect(within(metric!).getByText("620")).toBeInTheDocument();
    expect(within(metric!).getByText("340 structural or design gaps")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", {
        name: "Incomplete network analysis results",
      }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Inspection gaps" }));
    expect(
      await screen.findByText("Showing 1–20 of 340 inspection gaps"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Rule findings" }));
    expect(
      await screen.findByText("Showing 1–20 of 620 rule findings"),
    ).toBeInTheDocument();
  });

  it("does not forward visible-page truncation into exhaustive topology finding coverage", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("tab", { name: "Topology" }));

    expect(
      screen.getByTestId("topology-workspace-page-truncation"),
    ).toHaveTextContent("Page truncation not forwarded");
  });

  it("keeps backend pagination warnings out of provenance because the owning tabs show ranges", async () => {
    const gapEnvelope = buildGapsEnvelope(77, 0, 20);
    gapEnvelope.warnings = [
      "Results are truncated; narrow the scope or use pagination for a complete view.",
      "Showing 20 of 77 inspection gaps; use pagination for the complete result",
    ];
    mocks.gaps.mockResolvedValue(gapEnvelope);
    mocks.ruleFindings.mockResolvedValue(buildRuleFindingsEnvelope(6, 0, 20));

    renderPage();

    const provenance = await screen.findByLabelText("Data trust and provenance");
    expect(provenance).not.toHaveTextContent("Results are truncated");
    expect(provenance).not.toHaveTextContent("Showing 20 of 77 inspection gaps");
    expect(
      screen.queryByRole("status", { name: "Incomplete network analysis results" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Inspection gaps" }));
    expect(
      await screen.findByText("Showing 1–20 of 77 inspection gaps"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Rule findings" }));
    expect(
      await screen.findByText("Showing 1–6 of 6 rule findings"),
    ).toBeInTheDocument();
  });

  it("keeps an available collection range in its tab when the companion collection is unavailable", async () => {
    const gapEnvelope = buildGapsEnvelope(77, 0, 20);
    gapEnvelope.warnings = [
      "Showing 20 of 77 inspection gaps; use pagination for the complete result",
    ];
    mocks.gaps.mockResolvedValue(gapEnvelope);
    mocks.ruleFindings.mockRejectedValue(new Error("rule findings unavailable"));

    renderPage();

    expect(
      await screen.findByLabelText("Data trust and provenance"),
    ).not.toHaveTextContent("Showing 20 of 77 inspection gaps");
    expect(screen.queryByText("Results are incomplete.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Inspection gaps" }));
    expect(
      await screen.findByText("Showing 1–20 of 77 inspection gaps"),
    ).toBeInTheDocument();
  });

  it("qualifies trust dimensions and describes the bypass finding population", async () => {
    const topology = buildTopologyEnvelope(1, 1);
    topology.data.summary = buildNetworkSummary({
      hub_count: 1,
      spoke_count: 0,
    });
    const bypass = bypassEnvelope();
    bypass.data.count = 2;
    mocks.topology.mockResolvedValue(topology);
    mocks.firewallBypass.mockResolvedValue(bypass);

    renderPage();

    const provenance = await screen.findByLabelText("Data trust and provenance");
    expect(provenance).toHaveTextContent("Topology evidence · high confidence");
    expect(provenance).toHaveTextContent("Topology graph observed Unknown");
    const bypassMetric = screen.getByText("Inspection bypass findings").closest("article");
    expect(bypassMetric).not.toBeNull();
    expect(bypassMetric).toHaveTextContent("2");
    expect(bypassMetric).toHaveTextContent(
      "Subnet route and public-IP findings that may avoid firewall inspection",
    );
    expect(bypassMetric).not.toHaveTextContent("Spokes");
  });

  it("renders server-authored topology integrity warnings", async () => {
    const topology = buildTopologyEnvelope();
    topology.data.topology.warnings = [
      "2 topology relationships were omitted because their endpoints were outside this scope",
    ];
    mocks.topology.mockResolvedValue(topology);

    renderPage();

    expect(
      await screen.findByText(
        "2 topology relationships were omitted because their endpoints were outside this scope",
      ),
    ).toBeInTheDocument();
  });

  it("uses an unknown placeholder rather than zero while totals are loading", () => {
    mocks.topology.mockReturnValue(new Promise(() => undefined));
    mocks.gaps.mockReturnValue(new Promise(() => undefined));
    mocks.ruleFindings.mockReturnValue(new Promise(() => undefined));
    mocks.firewallBypass.mockReturnValue(new Promise(() => undefined));

    renderPage();

    const metrics = document.querySelector(".network-metrics");
    expect(metrics).not.toBeNull();
    expect(metrics).not.toHaveTextContent(/\b0\b/);
    expect(within(metrics as HTMLElement).getAllByText("—").length).toBeGreaterThan(0);
  });

  it("does not fabricate zero coverage for an unavailable companion collection", async () => {
    mocks.gaps.mockRejectedValue(new Error("gaps unavailable"));
    renderPage();

    await waitFor(() => expect(mocks.gaps).toHaveBeenCalled());
    expect(screen.queryByText("Results are incomplete.")).not.toBeInTheDocument();
    expect(screen.queryByText(/0 of 0 inspection gaps/)).not.toBeInTheDocument();
  });

  it("requests an explicit first server page and advances gaps by one page", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(mocks.gaps).toHaveBeenCalledWith({}, { limit: 20, offset: 0 });
      expect(mocks.ruleFindings).toHaveBeenCalledWith({}, { limit: 20, offset: 0 });
    });

    await user.click(screen.getByRole("tab", { name: "Inspection gaps" }));
    expect(await screen.findByText("Showing 1–20 of 340 inspection gaps")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Rows per page for inspection gaps" })).toHaveValue("20");

    await user.click(screen.getByRole("button", { name: "Next page" }));

    await waitFor(() => {
      expect(mocks.gaps).toHaveBeenCalledWith({}, { limit: 20, offset: 20 });
      expect(mocks.gaps).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Showing 21–40 of 340 inspection gaps")).toBeInTheDocument();
  });

  it("renders the rule-findings server range and advances exactly once", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Rule findings" }));
    expect(await screen.findByText("Showing 1–20 of 620 rule findings")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Rows per page for rule findings" })).toHaveValue("20");

    await user.click(screen.getByRole("button", { name: "Next page" }));

    await waitFor(() => {
      expect(mocks.ruleFindings).toHaveBeenCalledWith({}, { limit: 20, offset: 20 });
      expect(mocks.ruleFindings).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Showing 21–40 of 620 rule findings")).toBeInTheDocument();
  });

  it("resets both server pagers before loading a changed scope", async () => {
    const user = userEvent.setup();
    mocks.gaps.mockImplementation(
      (scope: ScopeSelection, options: { offset: number; limit: number }) =>
        Promise.resolve(
          buildGapsEnvelope(
            scope.subscription?.[0] === "sub-narrow" ? 1 : 340,
            options.offset,
            options.limit,
          ),
        ),
    );
    mocks.ruleFindings.mockImplementation(
      (scope: ScopeSelection, options: { offset: number; limit: number }) =>
        Promise.resolve(
          buildRuleFindingsEnvelope(
            scope.subscription?.[0] === "sub-narrow" ? 1 : 620,
            options.offset,
            options.limit,
          ),
        ),
    );
    renderPage(true);

    await user.click(await screen.findByRole("tab", { name: "Inspection gaps" }));
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("Showing 21–40 of 340 inspection gaps");
    await user.click(screen.getByRole("button", { name: "Narrow test scope" }));

    await waitFor(() =>
      expect(mocks.gaps).toHaveBeenLastCalledWith(
        { subscription: ["sub-narrow"] },
        { limit: 20, offset: 0 },
      ),
    );
    expect(mocks.ruleFindings).toHaveBeenLastCalledWith(
      { subscription: ["sub-narrow"] },
      { limit: 20, offset: 0 },
    );
    expect(
      screen.queryByText("No inspection gaps detected"),
    ).not.toBeInTheDocument();
  });
});

describe("Network page loader recovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    primeSuccessfulLoaders(2, 2);
  });

  it.each([
    {
      tab: "Topology",
      loader: "topology",
      heading: "Topology is unavailable",
      retryName: "Retry loading topology",
    },
    {
      tab: "Inspection gaps",
      loader: "gaps",
      heading: "Inspection gaps are unavailable",
      retryName: "Retry loading inspection gaps",
    },
    {
      tab: "Rule findings",
      loader: "ruleFindings",
      heading: "Rule findings are unavailable",
      retryName: "Retry loading rule findings",
    },
    {
      tab: "Design policy",
      loader: "policy",
      heading: "Design policy is unavailable",
      retryName: "Retry loading design policy",
    },
  ] as const)(
    "offers a uniquely named Retry that refetches only $loader",
    async ({ tab, loader, heading, retryName }) => {
      const user = userEvent.setup();
      const failing = mocks[loader];
      failing.mockRejectedValueOnce(new Error(`${loader} failed`));
      renderPage();

      await user.click(await screen.findByRole("tab", { name: tab }));
      expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
      const retry = screen.getByRole("button", { name: retryName });
      expect(retry).toHaveTextContent("Retry");

      const callsBeforeRetry = Object.fromEntries(
        ["topology", "gaps", "ruleFindings", "policy"].map((name) => [
          name,
          mocks[name as keyof typeof mocks].mock.calls.length,
        ]),
      );
      failing.mockResolvedValue(
        loader === "topology"
          ? buildTopologyEnvelope()
          : loader === "gaps"
            ? buildGapsEnvelope(2)
            : loader === "ruleFindings"
              ? buildRuleFindingsEnvelope(2)
              : policyEnvelope(),
      );

      await user.click(retry);
      await waitFor(
        () => expect(failing.mock.calls.length).toBe(callsBeforeRetry[loader] + 1),
        { timeout: 1_500 },
      );
      for (const other of ["topology", "gaps", "ruleFindings", "policy"] as const) {
        if (other !== loader) {
          expect(mocks[other].mock.calls.length).toBe(callsBeforeRetry[other]);
        }
      }
    },
  );
});

describe("Network page policy round-trip", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    primeSuccessfulLoaders();
    mocks.policy.mockResolvedValue(
      policyEnvelope({
        rules: [
          {
            rule_id: "internet-via-firewall",
            name: "Internet via firewall",
            description: "Route internet traffic through the firewall.",
            category: "routing",
            severity: "high",
            enabled: true,
            parameters: {},
            evaluated: true,
          },
          {
            rule_id: "nsg-on-every-subnet",
            name: "NSG on every subnet",
            description: "Require subnet protection.",
            category: "security",
            severity: "high",
            enabled: true,
            parameters: {},
            evaluated: true,
          },
        ],
      }),
    );
    mocks.updatePolicy.mockResolvedValue(policyEnvelope());
    mocks.previewPolicy.mockResolvedValue({
      ...policyEnvelope(),
      data: {
        policy: policyEnvelope({ rules: [declarativeRule] }).data,
        gaps: [],
        summary: buildNetworkSummary({ gap_count: 339 }),
      },
    });
  });

  describe("Network page provenance and keyboard contracts", () => {
    beforeEach(() => {
      vi.clearAllMocks();
      primeSuccessfulLoaders();
      mocks.policy.mockResolvedValue(
        policyEnvelope({
          rules: [
            { ...declarativeRule, rule_id: "custom-one", name: "Custom one" },
            { ...declarativeRule, rule_id: "custom-two", name: "Custom two" },
          ],
        }),
      );
      mocks.updatePolicy.mockResolvedValue(policyEnvelope());
      mocks.previewPolicy.mockResolvedValue({
        ...policyEnvelope(),
        data: {
          policy: policyEnvelope({ rules: [declarativeRule] }).data,
          gaps: [],
          summary: buildNetworkSummary(),
        },
      });
    });

    it.each([
      [
        { state: "not_ingested", observed_flow_count: 0 },
        "Flow logs: not ingested — findings are configuration-derived",
      ],
      [
        { state: "ingested_not_analyzed", observed_flow_count: 8 },
        "Flow logs: ingested, not yet analyzed — findings remain configuration-derived",
      ],
      [
        { state: "analyzed", observed_flow_count: 42 },
        "Flow logs: 42 observed flows analyzed",
      ],
    ])("renders the server-derived flow provenance state %#", async (provenance, expected) => {
      const topology = buildTopologyEnvelope();
      Object.assign(topology.data.topology, { flow_log_provenance: provenance });
      mocks.topology.mockResolvedValue(topology);

      renderPage();

      expect(await screen.findByText(expected)).toBeInTheDocument();
      expect(screen.queryByText(["No flow", " logs assumed"].join(""))).not.toBeInTheDocument();
    });

    it("tab-walks every introduced policy control in DOM order with unique accessible names", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByRole("tab", { name: "Design policy" }));
      await user.click(await screen.findByRole("button", { name: "Add rule" }));

      const controlNames = [
        "Analyzer template",
        "Rule ID",
        "Name",
        "Category",
        "Severity",
        "Description",
        "Rule assertion (JSON)",
        "Preview rule",
        "Save rule",
        "Delete Custom one",
        "Delete Custom two",
      ];
      const controls = [
        screen.getByRole("combobox", { name: controlNames[0] }),
        ...controlNames.slice(1, 4).map((name) => screen.getByRole("textbox", { name })),
        screen.getByRole("combobox", { name: controlNames[4] }),
        ...controlNames.slice(5, 7).map((name) => screen.getByRole("textbox", { name })),
        ...controlNames.slice(7).map((name) => screen.getByRole("button", { name })),
      ];

      (document.activeElement as HTMLElement | null)?.blur();
      const reached: HTMLElement[] = [];
      for (let step = 0; step < 40 && reached.length < controls.length; step += 1) {
        await user.tab();
        const active = document.activeElement as HTMLElement;
        if (controls.includes(active) && !reached.includes(active)) reached.push(active);
      }

      expect(reached).toEqual(controls);
      expect(reached.every((control) => control.tabIndex <= 0)).toBe(true);
      expect(reached.every((control) => control.style.outline !== "none" && control.style.outline !== "0")).toBe(true);
      expect(new Set(controlNames).size).toBe(controlNames.length);

      await user.click(screen.getByRole("button", { name: "Delete Custom one" }));
      expect(screen.getByRole("button", { name: "Confirm delete Custom one" })).toHaveTextContent("Confirm delete");
      expect(screen.getByText(/Deleting Custom one stops it from producing findings/)).toHaveAttribute("aria-live", "polite");
    });

    it("tab-walks the server pagers and preserves distinct labels in each rendered view", async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(await screen.findByRole("tab", { name: "Inspection gaps" }));
      await user.click(screen.getByRole("button", { name: "Next page" }));
      await screen.findByText("Showing 21–40 of 340 inspection gaps");
      const gapPager = [
        screen.getByRole("combobox", { name: "Rows per page for inspection gaps" }),
        screen.getByRole("button", { name: "Previous page" }),
        screen.getByRole("button", { name: "Next page" }),
      ];
      for (const control of gapPager) {
        for (let step = 0; document.activeElement !== control && step < 30; step += 1) await user.tab();
        expect(control).toHaveFocus();
        expect(control.tabIndex).toBeLessThanOrEqual(0);
      }

      await user.click(screen.getByRole("tab", { name: "Rule findings" }));
      await user.click(screen.getByRole("button", { name: "Next page" }));
      await screen.findByText("Showing 21–40 of 620 rule findings");
      const findingPager = [
        screen.getByRole("combobox", { name: "Rows per page for rule findings" }),
        screen.getByRole("button", { name: "Previous page" }),
        screen.getByRole("button", { name: "Next page" }),
      ];
      for (const control of findingPager) {
        for (let step = 0; document.activeElement !== control && step < 30; step += 1) await user.tab();
        expect(control).toHaveFocus();
        expect(control.tabIndex).toBeLessThanOrEqual(0);
      }
    });
  });

  it("coalesces rapid successful mutations and refreshes every derived loader without reloading the page", async () => {
    const user = userEvent.setup();
    const refreshedFindings = buildRuleFindingsEnvelope(619);
    refreshedFindings.data.findings = refreshedFindings.data.findings.slice(0, 99);
    mocks.ruleFindings
      .mockResolvedValueOnce(buildRuleFindingsEnvelope(620))
      .mockResolvedValue(refreshedFindings);
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("switch", { name: "Disable Internet via firewall" }));
    await user.click(screen.getByRole("switch", { name: "Disable NSG on every subnet" }));
    await user.click(screen.getByRole("tab", { name: "Topology" }));

    expect(screen.getByTestId("topology-workspace")).toHaveTextContent("100 topology findings");
    await waitFor(
      () => {
        expect(mocks.topology).toHaveBeenCalledTimes(2);
        expect(mocks.gaps).toHaveBeenCalledTimes(2);
        expect(mocks.ruleFindings).toHaveBeenCalledTimes(2);
      },
      { timeout: 1_500 },
    );
    expect(screen.getByTestId("topology-workspace")).toHaveTextContent("99 topology findings");
    expect(screen.getByRole("heading", { name: "Topology & traffic paths" })).toBeInTheDocument();
  });

  it("announces an asynchronous policy save failure", async () => {
    const user = userEvent.setup();
    mocks.updatePolicy.mockRejectedValueOnce(new Error("policy save timed out"));
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(
      await screen.findByRole("switch", {
        name: "Disable Internet via firewall",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "policy save timed out",
    );
  });

  it("announces policy form validation failures", async () => {
    const user = userEvent.setup();
    mocks.updatePolicy.mockRejectedValueOnce(
      new Error("rule persistence unavailable"),
    );
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    await user.type(
      screen.getByRole("textbox", { name: "Rule ID" }),
      "rule-save-error",
    );
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Rule");
    await user.click(screen.getByRole("button", { name: "Save rule" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "rule persistence unavailable",
    );
  });

  it("renders exactly one assertive policy validation alert at a time", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    await user.click(screen.getByRole("button", { name: "Preview rule" }));
    expect(screen.getAllByRole("alert")).toHaveLength(1);

    await user.type(screen.getByRole("textbox", { name: "Rule ID" }), "bad-json");
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Bad JSON");
    fireEvent.change(screen.getByRole("textbox", { name: "Rule assertion (JSON)" }), {
      target: { value: "{" },
    });
    await user.click(screen.getByRole("button", { name: "Preview rule" }));

    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Nothing has been sent to the server",
    );
  });

  it("uses the exact policy empty-state next-step copy", async () => {
    mocks.policy.mockResolvedValue(policyEnvelope({ rules: [] }));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));

    expect(
      await screen.findByText(
        "No design rules are configured for this estate. Add a rule to start checking for gaps.",
      ),
    ).toBeInTheDocument();
  });

  it("discloses the number of preview gaps omitted after the first five", async () => {
    const preview = buildGapsEnvelope(7);
    mocks.previewPolicy.mockResolvedValue({
      ...policyEnvelope(),
      data: {
        policy: policyEnvelope({ rules: [declarativeRule] }).data,
        gaps: preview.data.gaps,
        summary: buildNetworkSummary({ gap_count: 7 }),
      },
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    await user.type(screen.getByRole("textbox", { name: "Rule ID" }), declarativeRule.rule_id);
    await user.type(screen.getByRole("textbox", { name: "Name" }), declarativeRule.name);
    fireEvent.change(screen.getByRole("textbox", { name: "Rule assertion (JSON)" }), {
      target: { value: JSON.stringify(declarativeRule.parameters) },
    });
    await user.click(screen.getByRole("button", { name: "Preview rule" }));

    expect(await screen.findByText("and 2 more")).toBeInTheDocument();
  });

  it("retains the populated topology and metric totals while a policy-triggered refetch is in flight", async () => {
    const user = userEvent.setup();
    let resolveTopology: ((value: ReturnType<typeof buildTopologyEnvelope>) => void) | undefined;
    let topologyCall = 0;
    mocks.topology.mockImplementation(() => {
      topologyCall += 1;
      if (topologyCall === 1) return Promise.resolve(buildTopologyEnvelope());
      return new Promise((resolve) => {
        resolveTopology = resolve;
      });
    });

    renderPage();
    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("switch", { name: "Disable Internet via firewall" }));
    await user.click(screen.getByRole("tab", { name: "Topology" }));

    const canvas = screen.getByTestId("topology-workspace");
    await waitFor(() => expect(canvas.parentElement).toHaveAttribute("aria-busy", "true"), { timeout: 1_500 });
    expect(canvas).toBeInTheDocument();
    expect(screen.getByText("Broad or risky rules").closest("article")).toHaveTextContent("620");

    await act(async () => resolveTopology?.(buildTopologyEnvelope()));
  });

  it("previews and saves a free-form declarative rule through the server contract", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    await user.clear(screen.getByRole("textbox", { name: "Rule ID" }));
    await user.type(screen.getByRole("textbox", { name: "Rule ID" }), declarativeRule.rule_id);
    await user.clear(screen.getByRole("textbox", { name: "Name" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), declarativeRule.name);
    const assertion = screen.getByRole("textbox", { name: "Rule assertion (JSON)" });
    fireEvent.change(assertion, { target: { value: JSON.stringify(declarativeRule.parameters) } });

    await user.click(screen.getByRole("button", { name: "Preview rule" }));
    await waitFor(() =>
      expect(mocks.previewPolicy).toHaveBeenCalledWith(
        expect.objectContaining({
          rules: [expect.objectContaining({ rule_id: declarativeRule.rule_id, parameters: declarativeRule.parameters })],
        }),
        {},
      ),
    );
    await waitFor(() =>
      expect(
        screen
          .getAllByRole("status")
          .some((status) =>
            status.textContent?.includes(
              "Preview found 0 gaps under this rule. The saved policy is unchanged.",
            ),
          ),
      ).toBe(true),
    );

    await user.click(screen.getByRole("button", { name: "Save rule" }));
    await waitFor(() =>
      expect(mocks.updatePolicy).toHaveBeenCalledWith(
        expect.objectContaining({
          rules: [expect.objectContaining({ rule_id: declarativeRule.rule_id, parameters: declarativeRule.parameters })],
        }),
      ),
    );
  });

  it("renders a server semantic-validation reason beside the assertion and blocks save", async () => {
    const user = userEvent.setup();
    mocks.previewPolicy.mockResolvedValue({
      ...policyEnvelope(),
      data: {
        policy: policyEnvelope({
          rules: [{ ...declarativeRule, evaluated: false, invalid_reason: "operator eval is not supported" }],
        }).data,
        gaps: [],
        summary: buildNetworkSummary({ gap_count: 340 }),
      },
    });
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    await user.clear(screen.getByRole("textbox", { name: "Rule ID" }));
    await user.type(screen.getByRole("textbox", { name: "Rule ID" }), declarativeRule.rule_id);
    await user.clear(screen.getByRole("textbox", { name: "Name" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), declarativeRule.name);
    const assertion = screen.getByRole("textbox", { name: "Rule assertion (JSON)" });
    fireEvent.change(assertion, { target: { value: JSON.stringify(declarativeRule.parameters) } });
    await user.click(screen.getByRole("button", { name: "Preview rule" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("operator eval is not supported");
    expect(alert).toHaveTextContent("nothing was saved");
    expect(assertion).toHaveAttribute("aria-invalid", "true");
    expect(assertion).toHaveAttribute("aria-describedby", alert.id);
    expect(assertion.closest("label")?.previousElementSibling).toBe(alert);

    await user.click(screen.getByRole("button", { name: "Save rule" }));
    expect(mocks.updatePolicy).not.toHaveBeenCalled();
  });

  it("rejects malformed JSON locally and sends no preview or save request", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    await user.type(screen.getByRole("textbox", { name: "Rule ID" }), declarativeRule.rule_id);
    await user.type(screen.getByRole("textbox", { name: "Name" }), declarativeRule.name);
    const assertion = screen.getByRole("textbox", { name: "Rule assertion (JSON)" });
    fireEvent.change(assertion, { target: { value: "{" } });
    await user.click(screen.getByRole("button", { name: "Preview rule" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing has been sent to the server");
    expect(mocks.previewPolicy).not.toHaveBeenCalled();
    expect(mocks.updatePolicy).not.toHaveBeenCalled();
  });

  it("forwards every well-formed JSON value to server-only semantic validation", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    await user.type(screen.getByRole("textbox", { name: "Rule ID" }), declarativeRule.rule_id);
    await user.type(screen.getByRole("textbox", { name: "Name" }), declarativeRule.name);
    fireEvent.change(screen.getByRole("textbox", { name: "Rule assertion (JSON)" }), {
      target: { value: "null" },
    });
    await user.click(screen.getByRole("button", { name: "Preview rule" }));

    await waitFor(() =>
      expect(mocks.previewPolicy).toHaveBeenCalledWith(
        expect.objectContaining({
          rules: [expect.objectContaining({ parameters: null })],
        }),
        {},
      ),
    );
  });

  it("renders a PATCH semantic rejection beside the retained assertion", async () => {
    const user = userEvent.setup();
    mocks.updatePolicy.mockRejectedValue(
      new ApiError(400, "invalid_request", "operator eval is not supported"),
    );
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    await user.type(screen.getByRole("textbox", { name: "Rule ID" }), declarativeRule.rule_id);
    await user.type(screen.getByRole("textbox", { name: "Name" }), declarativeRule.name);
    const assertion = screen.getByRole("textbox", { name: "Rule assertion (JSON)" });
    const body = JSON.stringify(declarativeRule.parameters);
    fireEvent.change(assertion, { target: { value: body } });
    await user.click(screen.getByRole("button", { name: "Save rule" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("operator eval is not supported");
    expect(alert).toHaveTextContent("nothing was saved");
    expect(assertion).toHaveValue(body);
    expect(assertion).toHaveAttribute("aria-invalid", "true");
  });

  it("reports a saved rule delta from the pre- and post-refetch summary totals", async () => {
    const user = userEvent.setup();
    mocks.gaps
      .mockResolvedValueOnce(buildGapsEnvelope(340))
      .mockResolvedValue(buildGapsEnvelope(339));
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    await user.type(screen.getByRole("textbox", { name: "Rule ID" }), declarativeRule.rule_id);
    await user.type(screen.getByRole("textbox", { name: "Name" }), declarativeRule.name);
    fireEvent.change(screen.getByRole("textbox", { name: "Rule assertion (JSON)" }), {
      target: { value: JSON.stringify(declarativeRule.parameters) },
    });
    await user.click(screen.getByRole("button", { name: "Save rule" }));

    await waitFor(
      () =>
        expect(
          screen.getByText("Rule saved. Inspection gaps 340 → 339."),
        ).toBeInTheDocument(),
      { timeout: 1_500 },
    );
  });

  it("warns when the server identifies an unchanged cached analysis after save", async () => {
    const user = userEvent.setup();
    const cached = buildGapsEnvelope(340);
    cached.warnings = ["Analysis response was served from a cached policy revision"];
    mocks.gaps.mockResolvedValueOnce(buildGapsEnvelope(340)).mockResolvedValue(cached);
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    await user.type(screen.getByRole("textbox", { name: "Rule ID" }), declarativeRule.rule_id);
    await user.type(screen.getByRole("textbox", { name: "Name" }), declarativeRule.name);
    fireEvent.change(screen.getByRole("textbox", { name: "Rule assertion (JSON)" }), {
      target: { value: JSON.stringify(declarativeRule.parameters) },
    });
    await user.click(screen.getByRole("button", { name: "Save rule" }));

    await waitFor(
      () =>
        expect(
          screen.getByText(
            "Saved. Derived analysis has not refreshed yet — retry in a moment.",
          ),
        ).toBeInTheDocument(),
      { timeout: 1_500 },
    );
    expect(screen.queryByText(/Inspection gaps 340 → 340/)).not.toBeInTheDocument();
  });

  it("settles policy refresh state when derived gap analysis fails", async () => {
    const user = userEvent.setup();
    mocks.gaps
      .mockResolvedValueOnce(buildGapsEnvelope(340))
      .mockRejectedValueOnce(new Error("gap refresh timed out"));
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Design policy" }));
    await user.click(await screen.findByRole("button", { name: "Add rule" }));
    await user.type(
      screen.getByRole("textbox", { name: "Rule ID" }),
      declarativeRule.rule_id,
    );
    await user.type(
      screen.getByRole("textbox", { name: "Name" }),
      declarativeRule.name,
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "Rule assertion (JSON)" }),
      { target: { value: JSON.stringify(declarativeRule.parameters) } },
    );
    await user.click(screen.getByRole("button", { name: "Save rule" }));

    expect(
      await screen.findByText(
        "Policy was saved, but derived analysis could not be refreshed — gap refresh timed out.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Refreshing derived analysis…"),
    ).not.toBeInTheDocument();
  });
});
