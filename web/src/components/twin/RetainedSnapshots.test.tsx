import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RetainedSnapshots } from "./RetainedSnapshots";
import type { TwinCapture, TwinCaptureComparison, TwinHistory, TwinScenarioPair } from "@/lib/twin-history";

const api = vi.hoisted(() => ({
  snapshots: vi.fn(), captureSnapshot: vi.fn(), removeSnapshot: vi.fn(), compareSnapshots: vi.fn(), retainedScenarios: vi.fn(),
}));
vi.mock("@/lib/services", () => ({ twinApi: api }));
const scope = { subscription: ["a", "b"], region: ["eastus"] };
const capture: TwinCapture = {
  snapshot_id: "a".repeat(32), snapshot_sha256: "c".repeat(64), retained_at: "2026-01-01T00:01:00Z",
  projection: {
    schema_version: 1, scope, composed_at: "2026-01-01T00:00:00Z",
    entities: [{ id: "resource:/exact/vm", name: "Worker", kind: "resource", state: "current", confidence: "high", attributes: {}, provenance: [] }],
    relationships: [], provenance: [{ source: "semantic_graph", confidence: "unknown" }], warnings: ["Optional source unavailable."],
  },
};
const candidate: TwinCapture = { ...capture, snapshot_id: "b".repeat(32) };
const history: TwinHistory = { schema_version: 1, actor: "owner", scope, revision: 2, updated_at: capture.retained_at, captures: [capture, candidate] };
const comparison: TwinCaptureComparison = {
  baseline_id: capture.snapshot_id, candidate_id: candidate.snapshot_id,
  baseline_sha256: capture.snapshot_sha256, candidate_sha256: candidate.snapshot_sha256,
  baseline_composed_at: capture.projection.composed_at, candidate_composed_at: candidate.projection.composed_at,
  entities: { added: [], removed: [], changed: [{ id: "resource:/exact/vm", before: capture.projection.entities[0], after: { ...capture.projection.entities[0], name: "Renamed" }, fields: ["name"] }] },
  relationships: { added: [], removed: [], changed: [] },
  warnings: { baseline: [], candidate: [] }, interpretation: "Safe declarations only, not verified changes.",
};
const review = {
  scenario: "firewall_failure", target: "resource:/exact/vm", version: capture.snapshot_sha256, likely_impact: "Review mapped dependencies.",
  risk_delta: null, analysis_kind: "bounded_topology_review", authority: "none", impacted_total: 1, truncated: false,
  traversal: { direction: "undirected", max_hops: 3, max_entities: 500 },
  impacted_entities: capture.projection.entities, assumptions: ["Review only, no execution."], warnings: ["Optional source unavailable."],
} as const;
const pair: TwinScenarioPair = {
  snapshot_id: capture.snapshot_id, snapshot_sha256: capture.snapshot_sha256, composed_at: capture.projection.composed_at, authority: "none",
  left: { ...review, traversal: { ...review.traversal }, assumptions: [...review.assumptions], warnings: [...review.warnings] },
  right: { ...review, scenario: "patch_deployment", traversal: { ...review.traversal }, assumptions: [...review.assumptions], warnings: [...review.warnings] },
  interpretation: "Same evidence, not measured scenario outcomes.",
};

async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Open retained snapshots" }));
  await screen.findByText("Revision 2. 2/10 captures in this exact personal scope.");
}
function select(name: string, value: string) {
  fireEvent.change(screen.getByRole("combobox", { name }), { target: { value } });
}

describe("retained Twin snapshots and same-evidence reviews", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.snapshots.mockResolvedValue({ data: structuredClone(history) });
    api.compareSnapshots.mockResolvedValue({ data: structuredClone(comparison) });
    api.retainedScenarios.mockResolvedValue({ data: structuredClone(pair) });
  });

  it("loads only on demand, requires distinct explicit selections and renders actual before/after", async () => {
    render(<RetainedSnapshots scope={scope} />);
    expect(api.snapshots).not.toHaveBeenCalled();
    await open();
    expect(screen.getByRole("button", { name: "Compare selected captures" })).toBeDisabled();
    select("Baseline snapshot", capture.snapshot_id);
    select("Candidate snapshot", capture.snapshot_id);
    expect(screen.getByRole("button", { name: "Compare selected captures" })).toBeDisabled();
    select("Candidate snapshot", candidate.snapshot_id);
    fireEvent.click(screen.getByRole("button", { name: "Compare selected captures" }));
    await screen.findByText(comparison.interpretation);
    const table = screen.getByRole("region", { name: "Scrollable retained capture differences" });
    expect(within(table).getByText("Changed")).toBeInTheDocument();
    fireEvent.click(within(table).getByText("View before / after (name)"));
    expect(within(table).getByText("Renamed")).toBeInTheDocument();
    expect(api.compareSnapshots).toHaveBeenCalledWith(scope, capture.snapshot_id, candidate.snapshot_id, expect.any(AbortSignal));
    expect(api.captureSnapshot).not.toHaveBeenCalled();
    select("Baseline snapshot", "");
    expect(screen.queryByText(comparison.interpretation)).not.toBeInTheDocument();
  });

  it("captures only with the reviewed revision, never submitting a displayed graph", async () => {
    api.captureSnapshot.mockResolvedValue({ data: { ...history, revision: 3 } });
    render(<RetainedSnapshots scope={scope} />);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Capture fresh scoped snapshot" }));
    await screen.findByText(/A fresh server composition was retained/);
    expect(api.captureSnapshot).toHaveBeenCalledWith(scope, 2, expect.any(AbortSignal));
    expect(api.snapshots).toHaveBeenCalledTimes(1);
  });

  it("requires reload after an uncertain write and never automatically replays it", async () => {
    api.captureSnapshot.mockRejectedValue(new Error("Revision conflict"));
    render(<RetainedSnapshots scope={scope} />);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Capture fresh scoped snapshot" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Reload retained snapshots before explicitly retrying.");
    expect(screen.getByRole("button", { name: "Capture fresh scoped snapshot" })).toBeDisabled();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload retained snapshots" }));
    await screen.findByText("Revision 2. 2/10 captures in this exact personal scope.");
    expect(api.captureSnapshot).toHaveBeenCalledTimes(1);
  });

  it("requires explicit identified deletion confirmation at the reviewed revision", async () => {
    api.removeSnapshot.mockResolvedValue({ data: { ...history, revision: 3, captures: [candidate] } });
    render(<RetainedSnapshots scope={scope} />);
    await open();
    fireEvent.click(screen.getByRole("button", { name: `Delete snapshot ${capture.snapshot_id}` }));
    expect(api.removeSnapshot).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel deletion" }));
    expect(api.removeSnapshot).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: `Delete snapshot ${capture.snapshot_id}` }));
    fireEvent.click(screen.getByRole("button", { name: `Confirm delete snapshot ${capture.snapshot_id}` }));
    await screen.findByText("Snapshot deleted; source observations were not changed.");
    expect(api.removeSnapshot).toHaveBeenCalledWith(scope, capture.snapshot_id, 2, expect.any(AbortSignal));
  });

  it("reviews two explicit scenarios against one exact retained resource with shared digest and unknown risk", async () => {
    render(<RetainedSnapshots scope={scope} />);
    await open();
    expect(screen.getByRole("button", { name: "Compare scenarios" })).toBeDisabled();
    select("Scenario snapshot", capture.snapshot_id);
    select("Retained resource", "resource:/exact/vm");
    select("Right scenario", "firewall_failure");
    expect(screen.getByRole("button", { name: "Compare scenarios" })).toBeDisabled();
    select("Right scenario", "patch_deployment");
    fireEvent.click(screen.getByRole("button", { name: "Compare scenarios" }));
    await screen.findByText(pair.interpretation);
    expect(screen.getByText(`Both reviews bound to SHA-256 ${capture.snapshot_sha256}`)).toBeInTheDocument();
    expect(screen.getAllByText("Measured risk delta: not established. Authority: none.")).toHaveLength(2);
    expect(api.retainedScenarios).toHaveBeenCalledWith(scope, capture.snapshot_id, "firewall_failure", "patch_deployment", "resource:/exact/vm", expect.any(AbortSignal));
    select("Left scenario", "route_change");
    expect(screen.queryByText(pair.interpretation)).not.toBeInTheDocument();
    expect(api.retainedScenarios).toHaveBeenCalledTimes(1);
  });

  it("distinguishes failed reads from empty captures and requires explicit recovery", async () => {
    api.snapshots.mockRejectedValueOnce(new Error("Storage unavailable"));
    render(<RetainedSnapshots scope={scope} />);
    fireEvent.click(screen.getByRole("button", { name: "Open retained snapshots" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Storage unavailable");
    expect(screen.queryByText(/No retained snapshots/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Capture fresh scoped snapshot" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload retained snapshots" }));
    await screen.findByText("Revision 2. 2/10 captures in this exact personal scope.");
    expect(api.snapshots).toHaveBeenCalledTimes(2);
  });

  it.each(["recovery", "capture", "comparison", "scenarios"])("aborts and suppresses late %s on exact scope replacement", async operation => {
    let finish: (value: { data: TwinHistory | TwinCaptureComparison | TwinScenarioPair }) => void = () => {};
    const deferred = new Promise(resolve => { finish = resolve; });
    if (operation === "recovery") api.snapshots.mockReturnValueOnce(deferred);
    const view = render(<RetainedSnapshots scope={scope} />);
    if (operation === "recovery") fireEvent.click(screen.getByRole("button", { name: "Open retained snapshots" }));
    else {
      await open();
      if (operation === "capture") {
        api.captureSnapshot.mockReturnValueOnce(deferred);
        fireEvent.click(screen.getByRole("button", { name: "Capture fresh scoped snapshot" }));
      } else if (operation === "comparison") {
        api.compareSnapshots.mockReturnValueOnce(deferred);
        select("Baseline snapshot", capture.snapshot_id); select("Candidate snapshot", candidate.snapshot_id);
        fireEvent.click(screen.getByRole("button", { name: "Compare selected captures" }));
      } else {
        api.retainedScenarios.mockReturnValueOnce(deferred);
        select("Scenario snapshot", capture.snapshot_id); select("Retained resource", "resource:/exact/vm");
        fireEvent.click(screen.getByRole("button", { name: "Compare scenarios" }));
      }
    }
    const method = operation === "recovery" ? api.snapshots : operation === "capture" ? api.captureSnapshot : operation === "comparison" ? api.compareSnapshots : api.retainedScenarios;
    const signal: AbortSignal = method.mock.calls[0].at(-1);
    view.rerender(<RetainedSnapshots scope={{ subscription: ["foreign"] }} />);
    expect(signal.aborted).toBe(true);
    await act(async () => finish({ data: operation === "comparison" ? comparison : operation === "scenarios" ? pair : history }));
    expect(screen.getByRole("button", { name: "Open retained snapshots" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByText(pair.interpretation)).not.toBeInTheDocument();
    expect(method).toHaveBeenCalledTimes(1);
  });

  it("does not replay scenario selections after closing and reopening, and disables capture at capacity", async () => {
    const full = { ...history, revision: 10, captures: Array.from({ length: 10 }, (_, index) => ({ ...capture, snapshot_id: index.toString(16).repeat(32) })) };
    api.snapshots.mockResolvedValue({ data: full });
    render(<RetainedSnapshots scope={scope} />);
    fireEvent.click(screen.getByRole("button", { name: "Open retained snapshots" }));
    await screen.findByText("Revision 10. 10/10 captures in this exact personal scope.");
    expect(screen.getByRole("button", { name: "Capture fresh scoped snapshot" })).toBeDisabled();
    select("Scenario snapshot", full.captures[0].snapshot_id);
    fireEvent.click(screen.getByRole("button", { name: "Close retained snapshots" }));
    fireEvent.click(screen.getByRole("button", { name: "Open retained snapshots" }));
    await waitFor(() => expect(api.snapshots).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("combobox", { name: "Scenario snapshot" })).toHaveValue("");
    expect(api.retainedScenarios).not.toHaveBeenCalled();
  });

  it("paginates every safe difference instead of silently truncating the comparison", async () => {
    api.compareSnapshots.mockResolvedValue({ data: {
      ...comparison, entities: { added: Array.from({ length: 23 }, (_, index) => ({ ...capture.projection.entities[0], id: `resource:row-${index}` })), removed: [], changed: [] },
    } });
    render(<RetainedSnapshots scope={scope} />);
    await open();
    select("Baseline snapshot", capture.snapshot_id); select("Candidate snapshot", candidate.snapshot_id);
    fireEvent.click(screen.getByRole("button", { name: "Compare selected captures" }));
    await screen.findByText(comparison.interpretation);
    expect(screen.getByRole("table").querySelectorAll("tbody tr")).toHaveLength(20);
    expect(screen.queryByText("resource:row-22")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Next page/ }));
    expect(screen.getByRole("table").querySelectorAll("tbody tr")).toHaveLength(3);
    expect(screen.getByRole("cell", { name: "resource:row-22" })).toBeInTheDocument();
    expect(api.compareSnapshots).toHaveBeenCalledTimes(1);
  });

  it("clears a previously successful scenario result when a subsequent review fails", async () => {
    render(<RetainedSnapshots scope={scope} />);
    await open();
    select("Scenario snapshot", capture.snapshot_id); select("Retained resource", "resource:/exact/vm");
    fireEvent.click(screen.getByRole("button", { name: "Compare scenarios" }));
    await screen.findByText(pair.interpretation);
    api.retainedScenarios.mockRejectedValueOnce(new Error("Capture no longer exists"));
    fireEvent.click(screen.getByRole("button", { name: "Compare scenarios" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Capture no longer exists");
    expect(screen.queryByText(pair.interpretation)).not.toBeInTheDocument();
  });
});
