import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider } from "@/lib/scope-context";
import {
  buildGapsEnvelope,
  buildNetworkSummary,
  buildRuleFindingsEnvelope,
  buildTopologyEnvelope,
} from "@/test/network-fixtures";
import { ApiError } from "@/lib/types";
import type { NetworkDesignPolicy } from "@/lib/types";

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
}));

vi.mock("@/lib/services", () => ({
  networkApi: mocks,
  buildCopilotSnapshot: vi.fn((value) => value),
  copilotEvidenceRows: vi.fn(() => []),
}));

vi.mock("@/components/ui/CopilotDrawer", () => ({
  CopilotDrawer: () => null,
}));

vi.mock("@/components/network/TopologyWorkspace", () => ({
  TopologyWorkspace: ({
    topology,
    gaps,
    ruleFindings,
  }: {
    topology: unknown;
    gaps: unknown[];
    ruleFindings: unknown[];
  }) => (
    <div data-testid="topology-workspace">
      <span>{topology ? "Topology canvas" : "No topology"}</span>
      <span>{gaps.length} topology gaps</span>
      <span>{ruleFindings.length} topology findings</span>
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

function renderPage() {
  return render(
    <ScopeProvider>
      <NetworkPage />
    </ScopeProvider>,
  );
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
}

describe("Network page honest totals and server pagination", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    primeSuccessfulLoaders();
  });

  it("renders summary totals rather than capped array lengths and discloses both incomplete collections", async () => {
    renderPage();

    const riskyRules = await screen.findByText("Broad or risky rules");
    const metric = riskyRules.closest("article");
    expect(metric).not.toBeNull();
    expect(within(metric!).getByText("620")).toBeInTheDocument();
    expect(within(metric!).getByText("340 structural or design gaps")).toBeInTheDocument();
    expect(screen.getByText("Results are incomplete.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Showing 100 of 340 inspection gaps and 100 of 620 rule findings. Metric totals are complete; the lists below are not.",
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

  it("requests an explicit first server page and advances gaps by one page", async () => {
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(mocks.gaps).toHaveBeenCalledWith({}, { limit: 100, offset: 0 });
      expect(mocks.ruleFindings).toHaveBeenCalledWith({}, { limit: 100, offset: 0 });
    });

    await user.click(screen.getByRole("tab", { name: "Inspection gaps" }));
    expect(await screen.findByText("Showing 1–100 of 340 inspection gaps")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Rows per page for inspection gaps" })).toHaveValue("100");

    await user.click(screen.getByRole("button", { name: "Next page" }));

    await waitFor(() => {
      expect(mocks.gaps).toHaveBeenCalledWith({}, { limit: 100, offset: 100 });
      expect(mocks.gaps).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Showing 101–200 of 340 inspection gaps")).toBeInTheDocument();
  });

  it("renders the rule-findings server range and advances exactly once", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("tab", { name: "Rule findings" }));
    expect(await screen.findByText("Showing 1–100 of 620 rule findings")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Rows per page for rule findings" })).toHaveValue("100");

    await user.click(screen.getByRole("button", { name: "Next page" }));

    await waitFor(() => {
      expect(mocks.ruleFindings).toHaveBeenCalledWith({}, { limit: 100, offset: 100 });
      expect(mocks.ruleFindings).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Showing 101–200 of 620 rule findings")).toBeInTheDocument();
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
      await screen.findByText("Showing 101–200 of 340 inspection gaps");
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
      await screen.findByText("Showing 101–200 of 620 rule findings");
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
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Preview found 0 gaps under this rule. The saved policy is unchanged.",
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
        expect(screen.getByRole("status")).toHaveTextContent(
          "Rule saved. Inspection gaps 340 → 339.",
        ),
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
        expect(screen.getByRole("status")).toHaveTextContent(
          "Saved. Derived analysis has not refreshed yet — retry in a moment.",
        ),
      { timeout: 1_500 },
    );
    expect(screen.queryByText(/Inspection gaps 340 → 340/)).not.toBeInTheDocument();
  });
});
