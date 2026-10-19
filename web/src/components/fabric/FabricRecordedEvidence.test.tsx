import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FabricRecordedEvidence } from "./FabricRecordedEvidence";
import type { FabricRecordedEvidence as RecordedEvidence } from "@/lib/types";

const evidence: RecordedEvidence = {
  evidence_mode: "recorded_metadata",
  generation_kind: "source_partition",
  sources: [{
    scope: { subscription: ["sub-a"], subscription_connection: ["conn-a"] },
    partition_key: "partition-a",
    observed_at: "2026-10-19T12:00:00Z",
    freshness: "stale",
    recorded_status: "partial",
    provider_status: "failed",
    last_attempt: {
      status: "partial", generation_id: "attempt-new",
      attempted_at: "2026-10-19T12:00:00Z", reason_code: "provider_timeout",
    },
    last_good: {
      status: "recorded", generation_id: "retained-old",
      observed_at: "2026-10-19T11:00:00Z", reason_code: "source_last_good_recorded",
    },
    lineage_ref: "javascript:untrusted-reference",
  }],
};

function inspect() {
  fireEvent.click(screen.getByText("Inspect recorded source evidence for bronze_resources"));
  return screen.getByRole("region", { name: "Recorded source evidence: bronze_resources" });
}

describe("Recorded Fabric source evidence", () => {
  it("separates attempted and retained source generations without claiming serving activation", () => {
    render(<FabricRecordedEvidence tableName="bronze_resources" evidence={evidence} />);
    const region = inspect();
    expect(within(region).getByText("attempt-new")).toBeInTheDocument();
    expect(within(region).getByText("retained-old")).toBeInTheDocument();
    expect(within(region).getByText("provider_timeout")).toBeInTheDocument();
    expect(within(region).getByText("failed")).toBeInTheDocument();
    expect(within(region).getByText("stale")).toBeInTheDocument();
    expect(within(region).getByText(/subscription: sub-a · subscription_connection: conn-a/)).toBeInTheDocument();
    expect(within(region).getByText(/not an active serving product/)).toBeInTheDocument();
    expect(within(region).getByText("javascript:untrusted-reference")).toBeInTheDocument();
    expect(within(region).queryByRole("link")).not.toBeInTheDocument();
  });

  it("preserves unknown and null evidence without borrowing an attempt as last good", () => {
    const source = evidence.sources[0];
    render(<FabricRecordedEvidence tableName="bronze_resources" evidence={{
      ...evidence,
      sources: [{
        ...source,
        freshness: "unknown",
        last_good: { status: "unknown", generation_id: null, observed_at: null, reason_code: "no_recorded_source_last_good" },
      }],
    }} />);
    const region = inspect();
    expect(within(region).getAllByText("attempt-new")).toHaveLength(1);
    expect(within(region).queryByText("retained-old")).not.toBeInTheDocument();
    expect(within(region).getByText("no_recorded_source_last_good")).toBeInTheDocument();
    expect(within(region).getAllByText("Unreported")).toHaveLength(2);
  });

  it("supports legacy responses without receipts", () => {
    render(<FabricRecordedEvidence tableName="bronze_resources" />);
    expect(within(inspect()).getByText("Recorded source evidence unavailable")).toBeInTheDocument();
  });

  it("does not turn an empty receipt list into success", () => {
    render(<FabricRecordedEvidence tableName="bronze_resources" evidence={{ ...evidence, sources: [] }} />);
    expect(within(inspect()).getByText("No source-partition evidence recorded")).toBeInTheDocument();
  });

  it("paginates partitions without aggregating generation identities", () => {
    render(<FabricRecordedEvidence tableName="bronze_resources" evidence={{
      ...evidence, sources: Array.from({ length: 30 }, (_, i) => ({ ...evidence.sources[0], partition_key: `partition-${i}` })),
    }} />);
    const region = inspect();
    expect(within(region).getAllByText("attempt-new").length).toBeLessThan(30);
    expect(within(region).getByRole("list", { name: "bronze_resources source partitions" })).toBeInTheDocument();
  });
});
