import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TopologyNodeData } from "@/lib/network-graph";
import { networkApi } from "@/lib/services";
import { buildGapsEnvelope, buildRuleFindingsEnvelope } from "@/test/network-fixtures";

import {
  TopologyDetailDrawer,
  type DrawerFindingsState,
} from "./TopologyDetailDrawer";

const NODE_ID =
  "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg-a";

afterEach(() => {
  vi.restoreAllMocks();
});

function node(overrides: Partial<TopologyNodeData> = {}): TopologyNodeData {
  return {
    id: NODE_ID,
    label: "nsg-a",
    kind: "resource",
    icon: "",
    subscriptionId: "sub-a",
    peerCount: 0,
    score: 0,
    signals: [],
    entityType: "NetworkSecurityGroup",
    details: {},
    observed: true,
    ...overrides,
  };
}

function findings(
  overrides: Partial<DrawerFindingsState> = {},
): DrawerFindingsState {
  return {
    gaps: [],
    ruleFindings: [],
    gapTotal: 4,
    ruleFindingTotal: 7,
    mapped: 11,
    total: 11,
    truncated: false,
    exhausted: true,
    loading: false,
    error: null,
    onRetry: vi.fn(),
    ...overrides,
  };
}

function renderDrawer(
  selectedNode = node(),
  state = findings(),
  onClose = vi.fn(),
) {
  return {
    onClose,
    ...render(
      <TopologyDetailDrawer
        node={selectedNode}
        edge={null}
        onClose={onClose}
        findings={state}
        detailLevel="summary"
      />,
    ),
  };
}

describe("TopologyDetailDrawer findings states", () => {
  it("always renders Open findings for an unrecognised selected node", () => {
    renderDrawer(node({ entityType: "FutureNetworkThing" }), findings({ loading: true }));

    expect(screen.getByRole("heading", { name: "Open findings" })).toBeInTheDocument();
    expect(screen.getByText("Checking open findings…")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Open findings" }).closest("section")).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("renders the findings-present count and grouped records", () => {
    const gap = { ...buildGapsEnvelope(1).data.gaps[0], resource_id: NODE_ID };
    const rule = {
      ...buildRuleFindingsEnvelope(1).data.findings[0],
      control_id: NODE_ID,
    };

    renderDrawer(node(), findings({ gaps: [gap], ruleFindings: [rule] }));

    expect(screen.getByRole("heading", { name: "Open findings (2)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Gaps on this resource" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Findings on this control" })).toBeInTheDocument();
  });

  it("claims confirmed clean only for successful exhaustive untruncated loaders", () => {
    renderDrawer();

    expect(screen.getByRole("heading", { name: "Open findings (0)" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "No open findings for this resource. All 4 gaps and 7 rule findings in scope were checked.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/not confirmed clean/i)).not.toBeInTheDocument();
  });

  it.each([
    ["truncated coverage", { truncated: true }],
    ["unexhausted badge fetch", { exhausted: false }],
  ])("renders possibly incomplete without a count for %s", (_label, override) => {
    renderDrawer(node(), findings(override));

    expect(screen.getByRole("heading", { name: "Open findings" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Open findings \(/ })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveClass("callout-warning");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Findings for this resource may be incomplete. 11 of 11 findings were loaded. This resource is not confirmed clean.",
    );
  });

  it("renders unavailable with a unique R-5 Retry that invokes one request", () => {
    const onRetry = vi.fn();
    renderDrawer(
      node(),
      findings({
        error: new Error("gap service timed out"),
        onRetry,
      }),
    );

    expect(screen.getByRole("heading", { name: "Open findings" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveClass("callout-critical");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Findings are unavailable — gap service timed out. This resource is not confirmed clean.",
    );

    const retry = screen.getByRole("button", {
      name: "Retry loading findings for nsg-a",
    });
    expect(retry).toHaveTextContent("Retry");
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("TopologyDetailDrawer peer copy and keyboard behavior", () => {
  it.each([
    [
      "not_ingested" as const,
      "This peer was never ingested.",
      "Its subscription is not onboarded, so topology beyond this point is unknown.",
    ],
    [
      "excluded_by_scope" as const,
      "This peer is outside the current scope.",
      "It was ingested and is present in the estate, but the active scope selection excludes it. Widen the scope to see it.",
    ],
    [
      "unknown" as const,
      "Why this peer is missing is not recorded.",
      "This response did not say whether the VNet was never ingested or excluded by the current scope.",
    ],
  ])("renders reasoned peer copy for %s", (peerResolution, heading, sentence) => {
    renderDrawer(
      node({
        kind: "unresolved",
        observed: false,
        peerResolution,
        entityType: undefined,
      }),
    );

    expect(screen.getByText(heading)).toBeInTheDocument();
    expect(screen.getByText(sentence)).toBeInTheDocument();
  });

  it("uses undetermined copy when the legacy peer has no resolution", () => {
    renderDrawer(
      node({
        kind: "unresolved",
        observed: false,
        peerResolution: undefined,
        entityType: undefined,
      }),
    );

    expect(screen.getByText("Peer VNet — resolution not recorded")).toBeInTheDocument();
    expect(screen.queryByText("This peer was never ingested.")).not.toBeInTheDocument();
  });

  it("handles Escape before the full-screen listener", () => {
    const fullscreenEscape = vi.fn();

    function Harness() {
      const [selected, setSelected] = useState<TopologyNodeData | null>(node());
      return (
        <>
          <TopologyDetailDrawer
            node={selected}
            edge={null}
            onClose={() => setSelected(null)}
            findings={findings()}
            detailLevel="summary"
          />
          <span data-testid="drawer-state">{selected ? "open" : "closed"}</span>
        </>
      );
    }

    render(<Harness />);
    window.addEventListener("keydown", fullscreenEscape);
    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.getByTestId("drawer-state")).toHaveTextContent("closed");
    expect(fullscreenEscape).not.toHaveBeenCalled();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(fullscreenEscape).toHaveBeenCalledTimes(1);
    window.removeEventListener("keydown", fullscreenEscape);
  });
});

describe("TopologyDetailDrawer on-demand facts", () => {
  it("withholds summary rules until requested, then renders a paginated 50-row page", async () => {
    const items = Array.from({ length: 50 }, (_, index) => ({
      id: `rule-${index}`,
      name: `rule-${index}`,
      priority: 100 + index,
    }));
    const request = vi
      .spyOn(networkApi, "topologyResourceDetails")
      .mockResolvedValue({
        data: {
          resource_id: NODE_ID,
          detail_type: "rules",
          items,
          coverage: { total: 61, returned: 50, truncated: true },
        },
        evidence: [],
        scope: {},
        pagination: { offset: 0, limit: 50, total: 61, next_offset: 50 },
      });

    renderDrawer(node({ id: `${NODE_ID}/summary-rules` }));

    expect(request).not.toHaveBeenCalled();
    expect(
      screen.getByText("Rule detail was not loaded at summary detail."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load rules" }));

    await screen.findByText("rule-49");
    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith(`${NODE_ID}/summary-rules`, 0, 50);
    expect(screen.getByText("Showing 1–50 of 61 rules")).toBeInTheDocument();
    expect(screen.queryByText("rule-50")).not.toBeInTheDocument();
  });

  it.each([
    ["RouteTable", "Load routes", "Route detail was not loaded at summary detail."],
    [
      "FirewallPolicy",
      "Load rule collections",
      "Rule collection detail was not loaded at summary detail.",
    ],
  ])("offers an honest withheld state for %s", (entityType, button, disclosure) => {
    renderDrawer(node({ entityType, id: `${NODE_ID}/${entityType}` }));

    expect(screen.getByText(disclosure)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: button })).toBeInTheDocument();
  });

  it("disables the in-flight control and ignores a second press", async () => {
    let resolveRequest!: (value: Awaited<ReturnType<typeof networkApi.topologyResourceDetails>>) => void;
    const pending = new Promise<
      Awaited<ReturnType<typeof networkApi.topologyResourceDetails>>
    >((resolve) => {
      resolveRequest = resolve;
    });
    const request = vi
      .spyOn(networkApi, "topologyResourceDetails")
      .mockReturnValue(pending);
    renderDrawer(node({ id: `${NODE_ID}/loading` }));

    const load = screen.getByRole("button", { name: "Load rules" });
    fireEvent.click(load);
    expect(load).toBeDisabled();
    expect(load.closest("section")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText("Loading rules…")).toBeInTheDocument();
    fireEvent.click(load);
    expect(request).toHaveBeenCalledTimes(1);

    resolveRequest({
      data: {
        resource_id: `${NODE_ID}/loading`,
        detail_type: "rules",
        items: [],
        coverage: { total: 0, returned: 0, truncated: false },
      },
      evidence: [],
      scope: {},
      pagination: { offset: 0, limit: 50, total: 0, next_offset: null },
    });
    expect(
      await screen.findByText("No NSG rules were observed for this resource."),
    ).toBeInTheDocument();
  });

  it("keeps the drawer open on failure with a unique R-6 Retry", async () => {
    const request = vi
      .spyOn(networkApi, "topologyResourceDetails")
      .mockRejectedValueOnce(new Error("details timed out"))
      .mockResolvedValueOnce({
        data: {
          resource_id: `${NODE_ID}/error`,
          detail_type: "rules",
          items: [],
          coverage: { total: 0, returned: 0, truncated: false },
        },
        evidence: [],
        scope: {},
        pagination: { offset: 0, limit: 50, total: 0, next_offset: null },
      });
    renderDrawer(
      node({ id: `${NODE_ID}/error`, label: "nsg-error" }),
      findings({ error: new Error("findings timed out") }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Load rules" }));
    expect(await screen.findByText(/Rules could not be loaded — details timed out/)).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    const findingsRetry = screen.getByRole("button", {
      name: "Retry loading findings for nsg-error",
    });
    const detailsRetry = screen.getByRole("button", {
      name: "Retry loading rules for nsg-error",
    });
    expect(findingsRetry).not.toBe(detailsRetry);
    fireEvent.click(detailsRetry);
    await screen.findByText("No NSG rules were observed for this resource.");
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("keeps focus stable when drill-down completes and reuses the session cache", async () => {
    const request = vi
      .spyOn(networkApi, "topologyResourceDetails")
      .mockResolvedValue({
        data: {
          resource_id: `${NODE_ID}/cached`,
          detail_type: "rules",
          items: [{ id: "cached-rule", name: "cached-rule" }],
          coverage: { total: 1, returned: 1, truncated: false },
        },
        evidence: [],
        scope: {},
        pagination: { offset: 0, limit: 50, total: 1, next_offset: null },
      });
    const view = renderDrawer(node({ id: `${NODE_ID}/cached`, label: "cached" }));
    const close = screen.getByRole("button", { name: "Close details" });
    close.focus();
    fireEvent.click(screen.getByRole("button", { name: "Load rules" }));

    await screen.findByText("cached-rule");
    expect(document.activeElement).toBe(close);
    view.unmount();

    renderDrawer(node({ id: `${NODE_ID}/cached`, label: "cached" }));
    expect(screen.getByText("cached-rule")).toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("renders private endpoint and private-link service facts without silent unknowns", () => {
    const { unmount } = renderDrawer(
      node({
        entityType: "PrivateEndpoint",
        id: `${NODE_ID}/private-endpoint`,
        details: {
          target_resource_id: "/subscriptions/sub-b/resourceGroups/rg/providers/Microsoft.Sql/servers/sql-a",
          target_out_of_scope: true,
          connection_state: "Approved",
          subnet_id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet-a/subnets/private",
        },
      }),
    );

    expect(screen.getByText("Private link candidate")).toBeInTheDocument();
    expect(screen.getByText("Target resource is outside the collected scope.")).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText(/subnets\/private/)).toBeInTheDocument();
    const publicAccessFact = screen.getByText("Public network access").closest("div");
    expect(publicAccessFact).not.toBeNull();
    expect(within(publicAccessFact!).getByText("Unknown")).toHaveClass("status-unknown");
    unmount();

    renderDrawer(
      node({
        entityType: "PrivateLinkService",
        id: `${NODE_ID}/private-link-service`,
        details: {
          alias: "pls-a.eastus.azure.privatelinkservice",
          load_balancer_id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/loadBalancers/lb-a",
          public_network_access: "Disabled",
        },
      }),
    );
    expect(screen.getByText("pls-a.eastus.azure.privatelinkservice")).toBeInTheDocument();
    expect(screen.getByText(/loadBalancers\/lb-a/)).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
  });
});
