import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EvidenceBar } from "./EvidenceBar";

describe("EvidenceBar graph freshness", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each([
    ["absent", undefined],
    ["empty", ""],
    ["unparseable", "not-a-timestamp"],
    ["epoch", "1970-01-01T00:00:00.000Z"],
  ])("always renders Graph Unknown for %s freshness", (_case, graphFreshness) => {
    render(<EvidenceBar graphFreshness={graphFreshness} />);

    expect(screen.getByText("Graph").parentElement).toHaveTextContent("Graph Unknown");
    expect(screen.queryByText(/years ago/)).not.toBeInTheDocument();
  });

  it("uses relative time for a valid stamp and preserves the server confidence tone", () => {
    render(
      <EvidenceBar
        graphFreshness="2025-12-31T23:00:00Z"
        evidence={[
          {
            source_engine: "network.NetworkIntelligenceService",
            source_table: "ontology_entities",
            timestamp: "2025-12-31T23:00:00Z",
            confidence: "high",
            freshness: "fresh",
          },
        ]}
      />,
    );

    expect(screen.getByText("Graph").parentElement).toHaveTextContent("Graph 1 hour ago");
    expect(screen.getByLabelText("Data trust and provenance")).toHaveClass("evidence-bar-high");
  });

  it("qualifies confidence and graph observation labels when a surface supplies subjects", () => {
    render(
      <EvidenceBar
        confidenceSubject="Topology evidence"
        graphTimestampLabel="Topology graph observed"
        evidence={[
          {
            source_engine: "network.NetworkIntelligenceService",
            source_table: "ontology_entities",
            timestamp: "2025-12-31T23:00:00Z",
            confidence: "high",
            freshness: "fresh",
          },
        ]}
      />,
    );

    expect(screen.getByText("Topology evidence · high confidence")).toBeInTheDocument();
    expect(screen.getByText("Topology graph observed").parentElement).toHaveTextContent(
      "Topology graph observed Unknown",
    );
  });

  it("keeps warning overflow collapsed while preserving each unique warning", () => {
    render(
      <EvidenceBar
        warnings={[
          "First source is unavailable",
          "Second source is stale",
          "Third source is unconfigured",
          "Fourth source is degraded",
          "Third source is unconfigured",
          " ",
        ]}
      />,
    );

    const warningRegion = screen.getByLabelText("Data warnings");
    const warningLists = warningRegion.querySelectorAll(".evidence-warning-list");
    expect(warningLists).toHaveLength(2);
    expect(warningLists[0]?.querySelectorAll("li")).toHaveLength(2);

    const disclosureLabel = screen.getByText("Show 2 more warnings");
    const disclosure = disclosureLabel.closest("details");
    expect(disclosure).not.toHaveAttribute("open");
    expect(disclosure?.querySelectorAll("li")).toHaveLength(2);
    expect(disclosure).toHaveTextContent("Third source is unconfigured");
    expect(disclosure).toHaveTextContent("Fourth source is degraded");
  });
});
