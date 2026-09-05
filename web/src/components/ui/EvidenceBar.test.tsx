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
});
