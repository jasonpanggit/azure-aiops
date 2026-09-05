import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildNetworkSummary, buildTopologyEnvelope } from "@/test/network-fixtures";
import type { NetworkSummary } from "@/lib/types";

vi.mock("next/dynamic", () => ({
  default: () =>
    function GraphDouble() {
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
