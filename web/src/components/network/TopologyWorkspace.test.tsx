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
  NetworkTopology,
  RuleFinding,
} from "@/lib/types";

const graphProbe = vi.hoisted(() => ({
  props: null as null | {
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
      return <div data-testid="topology-graph">Topology graph</div>;
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
    fireEvent.click(screen.getByRole("checkbox", { name: "Gap / rule badges" }));
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
      screen.getByRole("checkbox", { name: "Gap / rule badges" }),
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
