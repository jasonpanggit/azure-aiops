import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import type { FabricPublicationEvidence as Evidence, FabricPublicationStage } from "@/lib/types";
import { FabricPublicationEvidence } from "./FabricPublicationEvidence";

const stages: FabricPublicationStage[] = [
  "acquired", "validated", "persisted", "registered", "active", "consumer_query_verified",
];

function receipt(): Evidence {
  const stage = {
    status: "unknown" as const, evidence_mode: "not_recorded" as const,
    reason_code: "no_stage_qualification_recorded", last_attempt: null, last_good: null,
  };
  return {
    contract: "fabric-product-publication/1", table_name: "bronze_resources",
    evidence_mode: "not_recorded", publication_attempt: null,
    stages: Object.fromEntries(stages.map(key => [key, { ...stage }])) as Evidence["stages"],
  };
}

it("keeps older APIs and missing receipts explicitly unavailable", () => {
  render(<FabricPublicationEvidence tableName="bronze_resources" />);
  expect(screen.getByText("Publication stages unavailable")).toBeInTheDocument();
  expect(screen.queryByText("Completion recorded")).not.toBeInTheDocument();
});

it("shows all six stages independently and never describes unknown as complete", () => {
  render(<FabricPublicationEvidence tableName="bronze_resources" evidence={receipt()} />);
  expect(screen.getAllByText(/Unknown/)).toHaveLength(6);
  expect(screen.getByText("Acquisition completeness")).toBeInTheDocument();
  expect(screen.getByText("Cloud registration")).toBeInTheDocument();
  expect(screen.getByText("Active readable product")).toBeInTheDocument();
  expect(screen.getByText("Consumer query qualification")).toBeInTheDocument();
});

it("does not promote retained last-good after a failed attempt", () => {
  const evidence = receipt();
  evidence.publication_attempt = {
    attempt_id: "attempt-2", source_generation: "new", publication_run_id: null,
    status: "failed", attempted_at: "2026-10-26T14:00:00Z",
    observed_at: "2026-10-26T15:00:00Z", scope: { subscription: ["sub-a"] },
  };
  evidence.stages.persisted.last_good = {
    attempt_id: "attempt-1", source_generation: "last-good",
    publication_run_id: "old-publication", observed_at: "2026-10-25T14:00:00Z",
    scope: { subscription: ["sub-a"] },
  };
  render(<FabricPublicationEvidence tableName="bronze_resources" evidence={evidence} />);
  expect(screen.getByText(/Publication attempt: failed/)).toBeInTheDocument();
  expect(screen.getByText(/Last-good source generation: last-good/)).toBeInTheDocument();
  expect(screen.queryByText("Completion recorded")).not.toBeInTheDocument();
});

it("rejects a receipt for another product", () => {
  render(<FabricPublicationEvidence tableName="gold_exposure_facts" evidence={receipt()} />);
  expect(screen.getByText("Unsupported publication evidence")).toBeInTheDocument();
});

it("shows persistence without claiming activation or querying", () => {
  const evidence = receipt();
  const fact = {
    attempt_id: "a", source_generation: "source-1", publication_run_id: "publication-1",
    observed_at: "2026-10-26T14:00:00Z", scope: { subscription: ["sub-a"] },
  };
  evidence.evidence_mode = "recorded_publisher_outcome";
  evidence.publication_attempt = { ...fact, status: "completed", attempted_at: fact.observed_at };
  evidence.stages.persisted = {
    status: "recorded", evidence_mode: "recorded_publisher_outcome", reason_code: "publisher_completed",
    last_attempt: fact, last_good: fact,
  };
  render(<FabricPublicationEvidence tableName="bronze_resources" evidence={evidence} />);
  const panel = screen.getByRole("region", { name: "Publication stages: bronze_resources", hidden: true });
  expect(within(panel).getAllByText(/Completion recorded/)).toHaveLength(1);
  expect(within(panel).getAllByText(/Unknown/)).toHaveLength(5);
  expect(screen.getByText(/not current table inventory/)).toBeInTheDocument();
});

it("rejects completion without a completed publication attempt", () => {
  const evidence = receipt();
  evidence.stages.persisted.status = "recorded";
  render(<FabricPublicationEvidence tableName="bronze_resources" evidence={evidence} />);
  expect(screen.getByText("Unsupported publication evidence")).toBeInTheDocument();
});

it("rejects fabricated activation facts and malformed retained facts", () => {
  const evidence = receipt();
  evidence.stages.active.last_good = {
    attempt_id: "a", source_generation: "source-1", publication_run_id: "publication-1",
    observed_at: "invalid", scope: { subscription: ["sub-a"] },
  };
  render(<FabricPublicationEvidence tableName="bronze_resources" evidence={evidence} />);
  expect(screen.getByText("Unsupported publication evidence")).toBeInTheDocument();
  expect(screen.queryByText("Completion recorded")).not.toBeInTheDocument();
});
