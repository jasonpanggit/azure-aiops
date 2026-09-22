import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildGapsEnvelope,
  buildNetworkSummary,
  buildRuleFindingsEnvelope,
  buildTopologyEnvelope,
} from "@/test/network-fixtures";
import type {
  NetworkSummary,
  RuleFinding,
} from "@/lib/types";
import type { TopologyNodeData } from "@/lib/network-graph";
import type { TopologyExportContext } from "./TopologyGraph";

const graphProbe = vi.hoisted(() => ({
  canvas: null as HTMLDivElement | null,
  props: null as null | {
    topology?: ReturnType<typeof buildTopologyEnvelope>["data"]["topology"];
    onSelect?: (selection: {
      node: TopologyNodeData | null;
      edge: null;
    }) => void;
    onReady?: (handle: {
      exportPng: () => void;
      exportJson: () => void;
      focusCanvas: () => void;
    } | null) => void;
    findingSeverityByResource?: Map<
      string,
      { severity: string; count: number; title?: string }
    >;
    showUnattachedPrivateLinkCandidates?: boolean;
    exportContext?: TopologyExportContext;
  },
}));

vi.mock("next/dynamic", () => ({
  default: () =>
    function GraphDouble(props: typeof graphProbe.props) {
      graphProbe.props = props;
      props?.onReady?.({
        exportPng: vi.fn(),
        exportJson: vi.fn(),
        focusCanvas: () => graphProbe.canvas?.focus(),
      });
      const resource = props?.topology?.resources?.[0];
      const node: TopologyNodeData | null = resource
        ? {
            id: resource.id,
            label: resource.name,
            kind: "resource",
            icon: "",
            subscriptionId: resource.subscription_id,
            peerCount: 0,
            score: 0,
            signals: [],
            entityType: resource.entity_type,
            details: resource.details,
            observed: true,
          }
        : null;
      return (
        <div
          data-testid="topology-graph"
          role="application"
          aria-label="Interactive network topology graph"
          tabIndex={-1}
          ref={(element) => {
            graphProbe.canvas = element;
          }}
        >
          Topology graph
          {node && (
            <button
              type="button"
              onClick={() => props?.onSelect?.({ node, edge: null })}
            >
              Select first graph node
            </button>
          )}
        </div>
      );
    },
}));

import {
  FULL_DETAIL_GUARD_NODES,
  TopologyWorkspace,
} from "./TopologyWorkspace";

function summaryWithProjectedNodes(projectedNodes: number): NetworkSummary {
  return buildNetworkSummary({
    projected_full_node_count: projectedNodes,
    resource_counts: { private_endpoints: Math.floor(projectedNodes / 2) },
  });
}

function renderWorkspace(
  overrides: Partial<React.ComponentProps<typeof TopologyWorkspace>> = {},
) {
  const topology = buildTopologyEnvelope().data.topology;
  const onDetailLevelChange = vi.fn();
  const view = render(
    <TopologyWorkspace
      topology={topology}
      summary={summaryWithProjectedNodes(100)}
      detailLevel="summary"
      onDetailLevelChange={onDetailLevelChange}
      loading={false}
      error={null}
      {...overrides}
    />,
  );
  return { ...view, onDetailLevelChange };
}

describe("TopologyWorkspace detail level", () => {
  beforeEach(() => {
    graphProbe.canvas = null;
    graphProbe.props = null;
  });

  it("renders the labelled Summary / Full detail control with the winning active class", () => {
    renderWorkspace();

    const group = screen.getByRole("group", { name: "Topology detail level" });
    const summary = within(group).getByRole("button", { name: "Summary" });
    const full = within(group).getByRole("button", { name: "Full detail" });

    expect(summary).toHaveAttribute("aria-pressed", "true");
    expect(summary).toHaveClass("segmented-active");
    expect(full).toHaveAttribute("aria-pressed", "false");
    expect(full).not.toHaveClass("active");
    expect(group.previousElementSibling).toHaveAttribute(
      "aria-label",
      "Highlight topology nodes by name",
    );
    expect(group.nextElementSibling).toHaveTextContent("Filter (hide non-matches)");
  });

  it("requests full detail directly below the measured ceiling and preserves filters", () => {
    const { rerender, onDetailLevelChange } = renderWorkspace();

    fireEvent.change(
      screen.getByRole("textbox", { name: "Highlight topology nodes by name" }),
      { target: { value: "hub" } },
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Filter (hide non-matches)" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Shared services" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Finding badges" }));
    fireEvent.click(screen.getByRole("button", { name: "Full detail" }));

    expect(onDetailLevelChange).toHaveBeenCalledWith("full");

    rerender(
      <TopologyWorkspace
        topology={buildTopologyEnvelope().data.topology}
        summary={summaryWithProjectedNodes(100)}
        detailLevel="full"
        onDetailLevelChange={onDetailLevelChange}
        loading={false}
        error={null}
      />,
    );

    expect(
      screen.getByRole("textbox", { name: "Highlight topology nodes by name" }),
    ).toHaveValue("hub");
    expect(
      screen.getByRole("checkbox", { name: "Filter (hide non-matches)" }),
    ).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Shared services" })).not.toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Finding badges" }),
    ).not.toBeChecked();
  });

  it("guards a projected graph above the measured ceiling until explicitly confirmed", () => {
    const { onDetailLevelChange } = renderWorkspace({
      summary: summaryWithProjectedNodes(FULL_DETAIL_GUARD_NODES + 1),
    });

    fireEvent.click(screen.getByRole("button", { name: "Full detail" }));

    expect(onDetailLevelChange).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      `Full detail renders about ${FULL_DETAIL_GUARD_NODES + 1} nodes`,
    );

    fireEvent.click(screen.getByRole("button", { name: "Load full detail" }));
    expect(onDetailLevelChange).toHaveBeenCalledWith("full");
  });

  it("also guards full detail when the last server topology build exceeded three seconds", () => {
    const { onDetailLevelChange } = renderWorkspace({
      summary: {
        ...summaryWithProjectedNodes(100),
        topology_build_duration_ms: 3_501,
      },
    });

    fireEvent.click(screen.getByRole("button", { name: "Full detail" }));

    expect(onDetailLevelChange).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "The last topology build took 3.5 seconds",
    );
  });

  it("uses the measured 1,500-node ceiling and never a larger literal", () => {
    expect(FULL_DETAIL_GUARD_NODES).toBe(1_500);
    expect(FULL_DETAIL_GUARD_NODES).toBeLessThanOrEqual(1_500);
  });

  it("keeps a populated real workspace mounted during a refetch", () => {
    renderWorkspace({ loading: true });

    expect(screen.getByTestId("topology-graph")).toBeInTheDocument();
    expect(
      screen.queryByText("Building cross-subscription topology"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Network topology" }),
    ).toHaveAttribute("aria-busy", "true");
  });

  it("keeps retained summary topology visible when the full-detail request fails", () => {
    renderWorkspace({
      detailLevel: "full",
      renderedDetailLevel: "summary",
      error: new Error("Full-detail request failed"),
    });

    expect(screen.getByTestId("topology-graph")).toBeInTheDocument();
    expect(screen.getByText("Rendering 2 of 2 nodes at summary detail.")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Full-detail request failed",
    );
    expect(
      screen.queryByText("Topology is unavailable"),
    ).not.toBeInTheDocument();
  });

  it("clears stale full-detail confirmation when the summary context changes without rendering NaN", () => {
    const { rerender } = renderWorkspace({
      scope: { subscription: ["sub-a"] },
      summary: {
        ...summaryWithProjectedNodes(100),
        topology_build_duration_ms: 3_501,
      },
    });

    fireEvent.click(screen.getByRole("button", { name: "Full detail" }));
    expect(
      screen.getByRole("button", { name: "Load full detail" }),
    ).toBeInTheDocument();

    rerender(
      <TopologyWorkspace
        topology={buildTopologyEnvelope().data.topology}
        summary={summaryWithProjectedNodes(100)}
        detailLevel="summary"
        onDetailLevelChange={vi.fn()}
        loading={false}
        error={null}
        scope={{ subscription: ["sub-a"] }}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Load full detail" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
  });

  it("clears stale full-detail confirmation when the operating scope changes", () => {
    const slowSummary = {
      ...summaryWithProjectedNodes(100),
      topology_build_duration_ms: 3_501,
    };
    const { rerender } = renderWorkspace({
      scope: { subscription: ["sub-a"] },
      summary: slowSummary,
    });

    fireEvent.click(screen.getByRole("button", { name: "Full detail" }));
    expect(
      screen.getByRole("button", { name: "Load full detail" }),
    ).toBeInTheDocument();

    rerender(
      <TopologyWorkspace
        topology={buildTopologyEnvelope().data.topology}
        summary={slowSummary}
        detailLevel="summary"
        onDetailLevelChange={vi.fn()}
        loading={false}
        error={null}
        scope={{ subscription: ["sub-b"] }}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Load full detail" }),
    ).not.toBeInTheDocument();
  });

  it("shows elapsed progress and an explicit cancel action for a long full-detail request", () => {
    vi.useFakeTimers();
    const onCancelDetailLoad = vi.fn();
    try {
      renderWorkspace({
        detailLevel: "full",
        loading: true,
        onCancelDetailLoad,
      });

      act(() => vi.advanceTimersByTime(3_100));

      expect(screen.getByRole("status")).toHaveTextContent(
        "Loading full detail — 3 seconds elapsed",
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Cancel full-detail load" }),
      );
      expect(onCancelDetailLoad).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders a private-link-only topology instead of the empty state", () => {
    const topology = buildTopologyEnvelope(1, 1).data.topology;
    topology.hubs = [];
    topology.spokes = [];
    topology.isolated = [];
    topology.resources = [
      {
        ...topology.resources![0],
        entity_type: "AIFoundryAccount",
        role: "private_link",
        details: { private_link_candidate: true },
      },
    ];

    renderWorkspace({ topology });

    expect(screen.getByTestId("topology-graph")).toBeInTheDocument();
    expect(
      screen.queryByText("No observed network topology"),
    ).not.toBeInTheDocument();
  });

  it("defaults unattached private-link candidates off with a count disclosure and opt-in toggle", () => {
    const topology = buildTopologyEnvelope(3, 3).data.topology;
    topology.resources![2] = {
      ...topology.resources![2],
      entity_type: "AIFoundryAccount",
      role: "private_link",
      details: { private_link_candidate: true },
    };

    renderWorkspace({ topology });

    const toggle = screen.getByRole("checkbox", {
      name: "Unattached private link candidates",
    });
    expect(toggle).not.toBeChecked();
    expect(
      screen.getByText(
        "1 unattached private link candidate hidden; enable the filter to show it.",
      ),
    ).toBeInTheDocument();
    expect(graphProbe.props?.showUnattachedPrivateLinkCandidates).toBe(false);

    fireEvent.click(toggle);

    expect(graphProbe.props?.showUnattachedPrivateLinkCandidates).toBe(true);
  });

  it("labels the dashed workload treatment as Private link candidate", () => {
    renderWorkspace();

    const legend = screen.getByLabelText("Topology legend");
    expect(within(legend).getByText("Private link candidate")).toHaveClass(
      "topology-legend-private-link",
    );
  });
});

describe("TopologyWorkspace badge coverage", () => {
  beforeEach(() => {
    graphProbe.props = null;
  });

  it("fans one finding out to its control and affected resources case-insensitively", () => {
    const control = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg";
    const subnetA = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/a";
    const subnetB = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/b";
    const topology = buildTopologyEnvelope().data.topology;
    topology.resources = [
      topology.resources![0],
      {
        ...topology.resources![0],
        id: control.toLowerCase(),
        name: "nsg",
        entity_type: "NetworkSecurityGroup",
      },
      {
        ...topology.resources![0],
        id: subnetA.toLowerCase(),
        name: "subnet-a",
        entity_type: "Subnet",
      },
      {
        ...topology.resources![0],
        id: subnetB.toLowerCase(),
        name: "subnet-b",
        entity_type: "Subnet",
      },
    ];
    const finding: RuleFinding = {
      ...buildRuleFindingsEnvelope(1).data.findings[0],
      control_id: control,
      affected_resource_ids: [subnetA.toUpperCase(), subnetB],
      severity: "critical",
    };

    renderWorkspace({ topology, ruleFindings: [finding] });

    const badges = graphProbe.props?.findingSeverityByResource;
    expect(badges).toHaveLength(3);
    expect(badges?.get(control.toLowerCase())).toMatchObject({
      count: 1,
      severity: "critical",
      title: "1 open finding (critical)",
    });
    expect(badges?.get(subnetA.toLowerCase())?.title).toBe(
      "1 open finding affecting this resource (critical)",
    );
  });

  it("counts a self-referential affected resource once and keeps both-role copy", () => {
    const finding = buildRuleFindingsEnvelope(1).data.findings[0];
    finding.affected_resource_ids = [finding.control_id.toUpperCase()];

    renderWorkspace({ ruleFindings: [finding] });

    expect(
      graphProbe.props?.findingSeverityByResource?.get(
        finding.control_id.toLowerCase(),
      ),
    ).toMatchObject({
      count: 1,
      title:
        "1 open finding on this control and 1 affecting this resource (critical)",
    });
  });

  describe("TopologyWorkspace disclosure and visual-only controls", () => {
    beforeEach(() => {
      graphProbe.props = null;
    });

    it("keeps drawer findings available when the visual badge toggle is off", () => {
      const topology = buildTopologyEnvelope(1, 1).data.topology;
      const finding = {
        ...buildRuleFindingsEnvelope(1).data.findings[0],
        control_id: topology.resources![0].id,
      };
      renderWorkspace({ topology, ruleFindings: [finding] });

      const toggle = screen.getByRole("checkbox", { name: "Finding badges" });
      expect(toggle.closest("label")).toHaveAttribute(
        "title",
        "Visual only — the details drawer always lists open findings.",
      );
      fireEvent.click(screen.getByRole("button", { name: "Select first graph node" }));
      fireEvent.click(toggle);

      expect(graphProbe.props?.findingSeverityByResource).toBeUndefined();
      expect(screen.getByText("Open findings (1)")).toBeInTheDocument();
    });

    it("announces an empty filter while retaining unfiltered and filter-hidden totals", () => {
      renderWorkspace();

      fireEvent.click(screen.getByRole("checkbox", { name: "Filter (hide non-matches)" }));
      fireEvent.change(
        screen.getByRole("textbox", { name: "Highlight topology nodes by name" }),
        { target: { value: "no-such-resource" } },
      );

      expect(screen.getByRole("status")).toHaveTextContent(
        'No resources match "no-such-resource". Clear the filter to see the 2 resources in scope.',
      );
      expect(screen.getByText("Rendering 2 of 2 nodes at summary detail.")).toBeInTheDocument();
      expect(screen.getByText("2 hidden by filter")).toBeInTheDocument();
    });

    it("renders complete reduction, peer-resolution, badge, and freshness text", () => {
      const topology = buildTopologyEnvelope(2, 2).data.topology;
      topology.coverage = { total: 9, returned: 2, truncated: true };
      topology.unresolved_peers = [
        {
          vnet_id: "/subscriptions/a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/not-ingested",
          peer_resolution: "not_ingested",
        },
        {
          vnet_id: "/subscriptions/a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/out-of-scope",
          peer_resolution: "excluded_by_scope",
        },
        {
          vnet_id: "/subscriptions/a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/observed",
          peer_resolution: "observed",
        },
      ];
      topology.unresolved_peer_vnet_ids = [
        ...topology.unresolved_peers.map((peer) => peer.vnet_id),
        "/subscriptions/a/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/legacy",
      ];
      topology.counts = {
        ...topology.counts,
        dropped_relationships: { attached_to: 2, resolves_for: 1 },
      };
      const finding = {
        ...buildRuleFindingsEnvelope(1).data.findings[0],
        control_id: topology.resources![0].id,
      };

      renderWorkspace({
        topology,
        ruleFindings: [finding],
        graphFreshness: "",
      });

      expect(screen.getByText("Rendering 6 of 9 nodes at summary detail.")).toBeInTheDocument();
      expect(screen.getByText("0 hidden by filter")).toBeInTheDocument();
      expect(
        screen.getByText(
          "3 relationships dropped (attached_to, resolves_for) — endpoints were not present in this scope.",
        ),
      ).toBeInTheDocument();
      expect(screen.getByText("1 peers not ingested")).toBeInTheDocument();
      expect(screen.getByText("1 peers outside current scope")).toBeInTheDocument();
      expect(screen.getByText("1 peers with unrecorded resolution")).toBeInTheDocument();
      expect(screen.getByText("1 nodes with open findings")).toBeInTheDocument();
      expect(
        screen.getByText(
          "Snapshot age unknown — no observation timestamp was recorded.",
        ),
      ).toBeInTheDocument();
    });

    it.each([undefined, "", "not-a-date", "1970-01-01T00:00:00Z"])(
      "uses the exact long-form unknown freshness predicate for %s",
      (graphFreshness) => {
        renderWorkspace({ graphFreshness });
        expect(
          screen.getByText(
            "Snapshot age unknown — no observation timestamp was recorded.",
          ),
        ).toBeInTheDocument();
      },
    );

    it("omits zero dropped relationships and zero peer-resolution items", () => {
      const topology = buildTopologyEnvelope().data.topology;
      topology.counts = { ...topology.counts, dropped_relationships: {} };
      topology.unresolved_peers = [];

      renderWorkspace({ topology, graphFreshness: "2026-01-01T00:00:00Z" });

      expect(screen.queryByText(/relationships dropped/)).not.toBeInTheDocument();
      expect(screen.queryByText(/peers not ingested/)).not.toBeInTheDocument();
      expect(screen.queryByText(/peers outside current scope/)).not.toBeInTheDocument();
      expect(screen.getByText(/Snapshot observed/)).toBeInTheDocument();
    });
  });

  it("preserves the legacy control-only badge set when affected ids are absent", () => {
    const finding = buildRuleFindingsEnvelope(1).data.findings[0];

    renderWorkspace({ ruleFindings: [finding] });

    const badges = graphProbe.props?.findingSeverityByResource;
    expect(badges).toHaveLength(1);
    expect(badges?.has(finding.control_id.toLowerCase())).toBe(true);
  });

  it("stops at four 500-item pages and discloses partial badge coverage", async () => {
    const loadGapsPage = vi.fn().mockResolvedValue(buildGapsEnvelope());
    const loadRuleFindingsPage = vi.fn(
      (offset: number, limit: number) =>
        Promise.resolve(buildRuleFindingsEnvelope(3_000, offset, limit)),
    );

    renderWorkspace({ loadGapsPage, loadRuleFindingsPage });

    expect(
      await screen.findByText("Badge coverage is partial."),
    ).toBeInTheDocument();
    expect(screen.getByText("Badges: 2000 of 3000 findings")).toBeInTheDocument();
    expect(loadRuleFindingsPage).toHaveBeenCalledTimes(4);
    expect(loadRuleFindingsPage).toHaveBeenNthCalledWith(4, 1_500, 500);
    expect(
      graphProbe.props?.exportContext?.coverage.badgeFetchExhausted,
    ).toBe(false);
  });

  it("loads until exhaustion below the budget and reports equal coverage", async () => {
    const loadGapsPage = vi.fn().mockResolvedValue(buildGapsEnvelope());
    const loadRuleFindingsPage = vi.fn(
      (offset: number, limit: number) =>
        Promise.resolve(buildRuleFindingsEnvelope(600, offset, limit)),
    );

    renderWorkspace({ loadGapsPage, loadRuleFindingsPage });

    await waitFor(() => expect(loadRuleFindingsPage).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Badge coverage is partial.")).not.toBeInTheDocument();
    expect(screen.getByText("Badges: 600 of 600 findings")).toBeInTheDocument();
  });

  it("confirms a resource clean after exhaustive badge loading despite visible-page truncation", async () => {
    const topology = buildTopologyEnvelope().data.topology;
    const routeTableId =
      "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Network/routeTables/rt-clean";
    topology.resources = [
      {
        ...topology.resources![0],
        id: routeTableId.toLowerCase(),
        name: "rt-clean",
        entity_type: "RouteTable",
      },
    ];
    const loadGapsPage = vi.fn(
      (offset: number, limit: number) =>
        Promise.resolve(buildGapsEnvelope(0, offset, limit)),
    );
    const loadRuleFindingsPage = vi.fn(
      (offset: number, limit: number) =>
        Promise.resolve(buildRuleFindingsEnvelope(83, offset, limit)),
    );

    renderWorkspace({
      topology,
      summary: buildNetworkSummary({
        gap_count: 0,
        rule_finding_count: 83,
      }),
      gaps: [],
      ruleFindings: buildRuleFindingsEnvelope(83, 0, 20).data.findings,
      loadGapsPage,
      loadRuleFindingsPage,
    });

    await waitFor(() => expect(loadRuleFindingsPage).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByText("Badges: 83 of 83 findings"),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Select first graph node" }),
    );

    expect(
      screen.getByRole("heading", { name: "Open findings (0)" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "No open findings for this resource. All 0 gaps and 83 rule findings in scope were checked.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/not confirmed clean/i)).not.toBeInTheDocument();
  });
});

describe("TopologyWorkspace export and selection honesty", () => {
  it("restores focus to the programmatically focusable canvas after closing the drawer", async () => {
    renderWorkspace();
    fireEvent.click(
      screen.getByRole("button", { name: "Select first graph node" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Close details" }));

    await waitFor(() =>
      expect(
        screen.getByRole("application", {
          name: "Interactive network topology graph",
        }),
      ).toHaveFocus(),
    );
  });

  it("shows a Partial badge beside honest JSON and PNG export controls", () => {
    const topology = buildTopologyEnvelope().data.topology;
    topology.coverage = {
      total: 2,
      returned: 2,
      truncated: true,
      nodes: { total: 2, returned: 2, truncated: false },
      relationships: { total: 9, returned: 1, truncated: true },
    };

    renderWorkspace({ topology });

    const png = screen.getByRole("button", {
      name: "Export PNG (image only)",
    });
    const json = screen.getByRole("button", { name: "Export JSON" });
    expect(png).toHaveAttribute(
      "title",
      "The image carries no scope or freshness metadata. Export JSON for an auditable record.",
    );
    expect(
      screen.getByText(
        "Partial topology — 2 of 2 nodes; 1 of 9 relationships",
      ),
    ).toBeInTheDocument();
    expect(png.closest(".topology-toolbar")).toContainElement(json);
    expect(png.closest(".topology-toolbar")).toContainElement(
      screen.getByText(
        "Partial topology — 2 of 2 nodes; 1 of 9 relationships",
      ),
    );
  });

  it("omits the Partial badge for complete coverage", () => {
    renderWorkspace();

    expect(screen.queryByText(/Partial topology —/)).not.toBeInTheDocument();
  });

  it("clears a selected node when a changed filter hides it", async () => {
    renderWorkspace();
    fireEvent.click(
      screen.getByRole("button", { name: "Select first graph node" }),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("checkbox", { name: "Filter (hide non-matches)" }),
    );
    fireEvent.change(
      screen.getByRole("textbox", {
        name: "Highlight topology nodes by name",
      }),
      { target: { value: "does-not-match-selected-node" } },
    );

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(
      screen
        .getByText(
          "Selection cleared — the selected resource is hidden by the current filter.",
        )
        .closest('[role="status"]'),
    ).not.toBeNull();
    expect(
      screen.getByRole("application", {
        name: "Interactive network topology graph",
      }),
    ).toHaveFocus();
  });

  it("clears selection immediately when the active scope changes", async () => {
    const onSelectionChange = vi.fn();
    const { rerender } = renderWorkspace({
      scope: { subscription: ["sub-a"] },
      onSelectionChange,
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Select first graph node" }),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(onSelectionChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        node: expect.objectContaining({ label: "vnet-0", entityType: "VNet" }),
      }),
    );

    rerender(
      <TopologyWorkspace
        topology={buildTopologyEnvelope().data.topology}
        summary={summaryWithProjectedNodes(100)}
        detailLevel="summary"
        loading={false}
        error={null}
        scope={{ subscription: ["sub-b"] }}
        onSelectionChange={onSelectionChange}
      />,
    );

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(onSelectionChange).toHaveBeenLastCalledWith({
      node: null,
      edge: null,
    });
  });

  it("clears selection when a detail response omits the selected node", async () => {
    const fullTopology = buildTopologyEnvelope(1, 1).data.topology;
    fullTopology.resources = [
      {
        ...fullTopology.resources![0],
        id: `${fullTopology.resources![0].id}/rules/rule-1`,
        name: "rule-1",
        entity_type: "NetworkSecurityRule",
      },
    ];
    const { rerender } = renderWorkspace({
      topology: fullTopology,
      detailLevel: "full",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Select first graph node" }),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    rerender(
      <TopologyWorkspace
        topology={buildTopologyEnvelope().data.topology}
        summary={summaryWithProjectedNodes(100)}
        detailLevel="summary"
        loading={false}
        error={null}
      />,
    );

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("clears selection when a refreshed topology retains the selected node", async () => {
    const initialTopology = buildTopologyEnvelope().data.topology;
    const { rerender } = renderWorkspace({ topology: initialTopology });
    fireEvent.click(
      screen.getByRole("button", { name: "Select first graph node" }),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    rerender(
      <TopologyWorkspace
        topology={{
          ...initialTopology,
          counts: { ...initialTopology.counts },
        }}
        summary={summaryWithProjectedNodes(100)}
        detailLevel="summary"
        loading={false}
        error={null}
      />,
    );

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });
});
