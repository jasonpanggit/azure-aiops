import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DurableEvidence } from "@/lib/types";
import { SituationEvidenceTimeline } from "./SituationEvidenceTimeline";

const earlier: DurableEvidence = {
  evidence_id: "earlier", source_family: "policy", source_object_id: "source-a", locator: "",
  resource_ids: ["resource-a", "resource-shared"], entity_ids: [], observed_at: "2026-10-15T01:00:00Z",
  ingested_at: "", watermark: "", ingestion_status: "succeeded", provenance: {}, freshness: "stale",
  quality: "contradictory", availability: "available", confidence: "medium",
  assertion: "Earlier observation", fingerprint: "first", situation_id: "situation-a",
};
const later: DurableEvidence = { ...earlier, evidence_id: "later", source_family: "monitor", observed_at: "2026-10-16T01:00:00Z",
  resource_ids: ["resource-b", "RESOURCE-SHARED"], assertion: "Later observation", quality: "complete", freshness: "fresh" };
describe("observed Situation timeline", () => {
  it("filters actual observations by source, quality and time without claiming a complete history", () => {
    render(<SituationEvidenceTimeline evidence={[earlier, later]} />);
    const events = within(screen.getByLabelText("Filtered observed events"));
    fireEvent.change(screen.getByLabelText("Timeline source"), { target: { value: "monitor" } });
    expect(events.queryByText("Earlier observation")).not.toBeInTheDocument();
    expect(events.getByText("Later observation")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Timeline quality"), { target: { value: "contradictory" } });
    expect(events.getByText("No observed evidence matches these timeline filters.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Timeline source"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Timeline quality"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Observed after (local time)"), { target: { value: "2026-10-20T00:00" } });
    expect(events.queryByText("Later observation")).not.toBeInTheDocument();
  });
  it("compares references and trust facts without asserting resources were added or removed", () => {
    render(<SituationEvidenceTimeline evidence={[earlier, later]} />);
    fireEvent.change(screen.getByLabelText("Earlier evidence"), { target: { value: "earlier" } });
    fireEvent.change(screen.getByLabelText("Later evidence"), { target: { value: "later" } });
    const comparison = within(screen.getByLabelText("Observed evidence comparison"));
    expect(comparison.getByText("Observed sequence only, not a causal conclusion.")).toBeInTheDocument();
    expect(comparison.getByText("resource-a")).toBeInTheDocument();
    expect(comparison.getByText("resource-b")).toBeInTheDocument();
    expect(comparison.queryByText("RESOURCE-SHARED")).not.toBeInTheDocument();
  });
  it("rejects reversed, unknown or identical observation times instead of inventing chronology", () => {
    render(<SituationEvidenceTimeline evidence={[earlier, later, { ...later, evidence_id: "unknown", observed_at: "" }]} />);
    fireEvent.change(screen.getByLabelText("Earlier evidence"), { target: { value: "later" } });
    fireEvent.change(screen.getByLabelText("Later evidence"), { target: { value: "earlier" } });
    expect(screen.getByRole("alert")).toHaveTextContent("chronological order");
    fireEvent.change(screen.getByLabelText("Earlier evidence"), { target: { value: "unknown" } });
    expect(screen.queryByLabelText("Observed evidence comparison")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Earlier evidence"), { target: { value: "earlier" } });
    expect(screen.getByRole("alert")).toHaveTextContent("distinct records");
  });
  it("does not infer ordering from equivalent timestamps or timezone-less source observations", () => {
    render(<SituationEvidenceTimeline evidence={[earlier,
      { ...later, observed_at: "2026-10-15T01:00:00+00:00" },
      { ...later, evidence_id: "naive", observed_at: "2026-10-15T01:00:00" }]} />);
    fireEvent.change(screen.getByLabelText("Earlier evidence"), { target: { value: "earlier" } });
    fireEvent.change(screen.getByLabelText("Later evidence"), { target: { value: "later" } });
    expect(screen.getByText("Coincident timestamps; no ordering can be established.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Later evidence"), { target: { value: "naive" } });
    expect(screen.getByRole("alert")).toHaveTextContent("known timestamps");
  });
});
