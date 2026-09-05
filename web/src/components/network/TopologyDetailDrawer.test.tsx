import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { TopologyNodeData } from "@/lib/network-graph";
import { buildGapsEnvelope, buildRuleFindingsEnvelope } from "@/test/network-fixtures";

import {
  TopologyDetailDrawer,
  type DrawerFindingsState,
} from "./TopologyDetailDrawer";

const NODE_ID =
  "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Network/networkSecurityGroups/nsg-a";

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
    expect(screen.queryByText(/never ingested/i)).not.toBeInTheDocument();
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
