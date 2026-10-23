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

  it("uses relative time and preserves confidence without treating high confidence as high severity", () => {
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
    expect(screen.getByLabelText("Data trust and provenance")).toHaveClass("evidence-bar-info");
    expect(screen.getByText("Cited evidence · high confidence")).toHaveClass("status-info");
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

  it.each([
    [{ logs: "unavailable" }, "Source coverage unavailable", "critical"],
    [{ logs: "unavailable", azure_vm: "ready" }, "Source coverage incomplete", "warning"],
    [{ logs: "partial" }, "Source coverage incomplete", "warning"],
    [{ logs: "degraded" }, "Source coverage incomplete", "warning"],
    [{ logs: "stale" }, "Source coverage incomplete", "warning"],
    [{ logs: " READY ", arc: "Partial" }, "Source coverage incomplete", "warning"],
    [{ logs: "unknown" }, "Source coverage unknown", "unknown"],
    [{ logs: "" }, "Source coverage unknown", "unknown"],
    [{ logs: "ready · 3 loaded" }, "Source coverage unknown", "unknown"],
    [{ logs: "ready" }, "Sources reporting ready", "info"],
  ] as const)("separates source coverage from high evidence confidence for %j", (sourceStatus, label, tone) => {
    render(<EvidenceBar
      evidence={[{ source_engine: "InventoryService", source_table: "inventory", timestamp: "", confidence: "high", freshness: "fresh" }]}
      sourceStatus={sourceStatus}
    />);
    expect(screen.getByText(label)).toHaveClass(`status-${tone}`);
    expect(screen.getByLabelText("Data trust and provenance")).toHaveClass(`evidence-bar-${tone}`);
    expect(screen.getByText("Cited evidence · high confidence")).toHaveClass("status-info");
    expect(screen.getByText("Confidence describes cited evidence, not source completeness.")).toBeInTheDocument();
    expect(screen.queryByText(/complete evidence/i)).not.toBeInTheDocument();
  });

  it.each(["low", "medium"] as const)("does not render %s confidence as a healthy-success signal", confidence => {
    render(<EvidenceBar evidence={[{ source_engine: "Test", source_table: "rows", timestamp: "", confidence, freshness: "fresh" }]} />);
    expect(screen.getByText(`Cited evidence · ${confidence} confidence`)).toHaveClass("status-warning");
  });

  it("does not infer source availability from warnings or timestamps", () => {
    render(<EvidenceBar warnings={["A source may be unavailable"]} fallbackTimestamp="2025-12-31T23:00:00Z" />);
    expect(screen.queryByText(/Source coverage/)).not.toBeInTheDocument();
    expect(screen.getByText("Cited evidence · unknown confidence")).toBeInTheDocument();
  });

  it("preserves domain aggregate evidence state over source-ready signals", () => {
    render(<EvidenceBar aggregateState={{ state: "partial", freshness: "stale" }} sourceStatus={{ logs: "ready" }} />);
    expect(screen.getByText("Partial evidence")).toHaveClass("status-warning");
    expect(screen.queryByText("Sources reporting ready")).not.toBeInTheDocument();
  });

  it("does not override explicit complete-and-current domain coverage with a derived source summary", () => {
    render(<EvidenceBar
      aggregateState={{ state: "complete", freshness: "current" }}
      sourceStatus={{ logs: "ready" }}
      evidence={[{ source_engine: "Test", source_table: "rows", timestamp: "", confidence: "high", freshness: "fresh" }]}
    />);
    expect(screen.queryByText(/Source coverage|Sources reporting ready/)).not.toBeInTheDocument();
    expect(screen.getByText("Cited evidence · high confidence")).toHaveClass("status-info");
  });
});
