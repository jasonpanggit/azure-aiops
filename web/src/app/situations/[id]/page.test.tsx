import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider } from "@/lib/scope-context";

const { get, audit } = vi.hoisted(() => ({ get: vi.fn(), audit: vi.fn() }));

vi.mock("@/lib/services", () => ({
  situationsApi: { get, audit },
}));

import SituationDetailPage from "./page";

const evidence = {
  evidence_id: "evidence://one",
  source_family: "defender",
  source_object_id: "defender-1",
  locator: "https://portal.azure.com/evidence",
  resource_ids: ["/subscriptions/sub-a/db"],
  entity_ids: [],
  observed_at: "2026-08-25T01:00:00Z",
  ingested_at: "2026-08-25T01:05:00Z",
  watermark: "2026-08-25T01:00:00Z",
  ingestion_status: "succeeded",
  provenance: { source_system: "Defender for Cloud" },
  freshness: "fresh",
  quality: "contradictory",
  availability: "available",
  confidence: "medium",
  assertion: "Database exposure detected",
  fingerprint: "fp",
  situation_id: "situation://one",
};

const situation = {
  situation_id: "situation://one",
  resource_id: "situation://one",
  title: "Database exposure",
  situation_type: "exposure",
  lifecycle_state: "open",
  severity: "high",
  priority: "P2",
  scope: { subscription: ["sub-a"] },
  owner: "Security",
  support_team: "Platform",
  affected_resource_ids: ["/subscriptions/sub-a/db"],
  linked_evidence_ids: ["evidence://one"],
  started_at: "2026-08-25T01:00:00Z",
  last_observed_at: "2026-08-25T01:05:00Z",
  evidence_state: "contradictory",
  warnings: [],
  contradiction_ids: ["evidence://one"],
  unknowns: ["Service ownership is not known."],
  run_id: "run-1",
  evidence: [evidence],
  source_status: [
    {
      source_family: "defender",
      run_id: "run-1",
      status: "succeeded",
      observed_at: "2026-08-25T01:00:00Z",
      ingested_at: "2026-08-25T01:05:00Z",
      watermark: "wm-1",
      query_version: "defender-v2",
      requested_scope: { subscription: ["sub-a"] },
      provider_status: "ok",
      freshness: "fresh",
      availability: "available",
      quality: "complete",
      error: "",
    },
    {
      source_family: "policy",
      run_id: "run-1",
      status: "failed",
      observed_at: "",
      ingested_at: "2026-08-25T01:05:00Z",
      watermark: "",
      query_version: "policy-v2",
      requested_scope: { subscription: ["sub-a"] },
      provider_status: "unavailable",
      freshness: "unknown",
      availability: "unavailable",
      quality: "degraded",
      error: "Policy provider offline",
    },
    {
      source_family: "monitor",
      run_id: "run-1",
      status: "succeeded",
      observed_at: "",
      ingested_at: "",
      watermark: "",
      query_version: "",
      requested_scope: {},
      provider_status: "ok",
      freshness: "unknown",
      availability: "unknown",
      quality: "unknown",
      error: "",
    },
  ],
  links: [{
    link_id: "link://one",
    situation_id: "situation://one",
    entity_type: "Exposure",
    entity_id: "exposure-1",
    relation: "relates_to",
    quality: "unresolved",
    provenance: {},
  }],
};

describe("durable Situation detail", () => {
  beforeEach(() => {
    get.mockReset();
    audit.mockReset();
    get.mockResolvedValue({ data: situation, evidence: [], scope: {} });
    audit.mockResolvedValue({
      data: [{
        event_id: "audit://one",
        actor: "system:ingestion",
        action: "evidence.ingested",
        scope_snapshot: { subscription: ["sub-a"] },
        timestamp: "2026-08-25T01:05:00Z",
        situation_id: "situation://one",
        evidence_ids: ["evidence://one"],
        source_references: ["defender-1"],
        run_id: "run-1",
      }],
      evidence: [],
      scope: {},
    });
  });

  it("reads durable detail and service audit with qualified trust states", async () => {
    render(<ScopeProvider><SituationDetailPage params={{ id: "situation://one" }} /></ScopeProvider>);

    expect(await screen.findByRole("heading", { name: "What failed?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What is at risk?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What changed?" })).toBeInTheDocument();
    expect(screen.getByText("Evidence conflicts — review the source records before drawing a conclusion.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What is not known" })).toBeInTheDocument();
    expect(screen.getAllByText(/defender-1/).length).toBeGreaterThan(0);
    const sourceStatusDetails = screen.getByLabelText("Durable source status details");
    expect(sourceStatusDetails).toHaveTextContent("defender");
    expect(sourceStatusDetails).toHaveTextContent("status succeeded");
    expect(sourceStatusDetails).toHaveTextContent("watermark wm-1");
    expect(sourceStatusDetails).toHaveTextContent("policy");
    expect(sourceStatusDetails).toHaveTextContent("availability unavailable");
    expect(sourceStatusDetails).toHaveTextContent("quality degraded");
    expect(sourceStatusDetails).toHaveTextContent("Policy provider offline");
    expect(sourceStatusDetails).toHaveTextContent("monitor");
    expect(sourceStatusDetails).toHaveTextContent("availability unknown");
    expect(sourceStatusDetails).toHaveTextContent("quality unknown");
    expect(screen.getByText("Recorded event · evidence.ingested")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("situation://one", {});
    expect(audit).toHaveBeenCalledWith("situation://one", {});
  });

  it("opens and closes the evidence drawer with Escape and keeps local save separate", async () => {
    render(<ScopeProvider><SituationDetailPage params={{ id: "situation://one" }} /></ScopeProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "View evidence details" }));
    expect(screen.getByRole("heading", { name: "Evidence detail" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Evidence detail" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Save view locally" }));
    expect(window.localStorage.getItem("aiops.situation-view.situation://one")).toContain("savedAt");
    expect(screen.getByText("View future-phase candidate")).toBeInTheDocument();
  });

  it("shows the empty audit state from the service", async () => {
    audit.mockResolvedValueOnce({ data: [], evidence: [], scope: {} });
    render(<ScopeProvider><SituationDetailPage params={{ id: "situation://one" }} /></ScopeProvider>);
    expect(await screen.findByText("No audit events are visible in this scope.")).toBeInTheDocument();
  });

  it("shows audit service failure separately from successful empty history", async () => {
    audit.mockRejectedValueOnce(new Error("audit backend offline"));
    render(<ScopeProvider><SituationDetailPage params={{ id: "situation://one" }} /></ScopeProvider>);

    expect(await screen.findByText("Audit history unavailable from the service")).toBeInTheDocument();
    expect(screen.queryByText("No audit events are visible in this scope.")).not.toBeInTheDocument();
  });
});
