import {
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

const graphProbe = vi.hoisted(() => ({
  props: null as null | {
    topology?: ReturnType<typeof buildTopologyEnvelope>["data"]["topology"];
    onSelect?: (selection: {
      node: TopologyNodeData | null;
      edge: null;
    }) => void;
    findingSeverityByResource?: Map<
      string,
      { severity: string; count: number; title?: string }
    >;
  },
}));

vi.mock("next/dynamic", () => ({
  default: () =>
    function GraphDouble(props: typeof graphProbe.props) {
      graphProbe.props = props;
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
        <div data-testid="topology-graph">
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
  return buildNetworkSummary({ resource_counts: { projected: projectedNodes } });
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

  it("uses the measured 1,500-node ceiling and never a larger literal", () => {
    expect(FULL_DETAIL_GUARD_NODES).toBe(1_500);
    expect(FULL_DETAIL_GUARD_NODES).toBeLessThanOrEqual(1_500);
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
});
