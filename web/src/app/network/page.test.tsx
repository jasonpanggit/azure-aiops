import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScopeProvider } from "@/lib/scope-context";
import {
  buildGapsEnvelope,
  buildNetworkSummary,
  buildRuleFindingsEnvelope,
  buildTopologyEnvelope,
} from "@/test/network-fixtures";
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

function policyEnvelope() {
  return {
    data: policy,
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
