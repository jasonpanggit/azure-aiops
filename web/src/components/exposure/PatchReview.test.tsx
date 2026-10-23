import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_EXPOSURE_SORT, type ExposureQueryState } from "@/lib/exposure-query-state";
import type { ExposureFinding, PatchReviewHistory } from "@/lib/types";
import { PatchReview } from "./PatchReview";

const api = vi.hoisted(() => ({ patchReviews: vi.fn(), createPatchReview: vi.fn() }));
vi.mock("@/lib/services", () => ({ vulnerabilityApi: api }));
const query: ExposureQueryState = {
  scope: { subscription: ["sub-a"] }, filters: { active: true }, sort: DEFAULT_EXPOSURE_SORT,
  pageSize: 25, page: 1, cursor: null, cursorHistory: [], target: "", drawer: "", generation: "gen-one",
};
const row: ExposureFinding = { exposure_id: "finding-one", target_id: "vm-one", target_kind: "server", weakness_id: "KB600001",
  subscription_id: "sub-a", connection_ids: ["conn-one"], source_families: ["aum"], read_model_generation_id: "gen-one", completeness: "partial" };
const empty: PatchReviewHistory = { schema_version: 1, actor: "reader", scope: query.scope, revision: 0, batches: [] };
const saved: PatchReviewHistory = { ...empty, revision: 1, batches: [{
  batch_id: `prb-${"1".repeat(32)}`, captured_at: "2026-10-17T00:00:00Z", generation: "gen-one", owner: "Operations",
  note: "Review missing updates", source_observed_at: "", source_completeness: "partial",
  findings: [{ exposure_id: "finding-one", target_id: "vm-one", target_kind: "server", weakness_id: "KB600001", severity: "critical", sla_state: "unknown", completeness: "partial" }],
}] };
const envelope = (data: PatchReviewHistory) => ({ data, scope: data.scope, evidence: [], warnings: [] });
function fill() {
  fireEvent.click(screen.getByRole("checkbox", { name: "KB600001 — vm-one" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Batch review owner" }), { target: { value: "Operations" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Batch review explanation" }), { target: { value: "Review missing updates" } });
}
describe("Review-only patch batch", () => {
  beforeEach(() => {
    vi.clearAllMocks(); api.patchReviews.mockResolvedValue(envelope(empty)); api.createPatchReview.mockResolvedValue(envelope(saved));
  });
  it("requires selection and explicit declaration; never creates automatically", async () => {
    render(<PatchReview query={query} rows={[row]} ready />);
    await screen.findByText(/Patch review revision 0/);
    expect(api.createPatchReview).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Save review-only batch" })).toBeDisabled();
    fill(); fireEvent.click(screen.getByRole("button", { name: "Save review-only batch" }));
    await screen.findByText(/No patch was executed or approved/);
    expect(api.createPatchReview).toHaveBeenCalledWith(query, 0, ["finding-one"], "Operations", "Review missing updates");
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    fireEvent.click(screen.getByText("Inspect retained review-only batches"));
    expect(screen.getByText(/source observed: unreported/)).toBeVisible();
    expect(screen.getByText("Review missing updates")).toBeVisible();
  });
  it("discloses a large duplicate selection list without hiding readiness or read errors", async () => {
    render(<PatchReview query={query} rows={Array.from({ length: 6 }, (_, index) => ({
      ...row, exposure_id: `finding-${index}`, target_id: `vm-${index}`,
    }))} ready />);
    await screen.findByText(/Patch review revision 0/);
    expect(screen.getByRole("checkbox", { name: "KB600001 — vm-0" })).not.toBeVisible();
    fireEvent.click(screen.getByText("Select findings and prepare a review (0 selected; 6 available)"));
    expect(screen.getAllByRole("checkbox")).toHaveLength(6);
    fireEvent.click(screen.getByRole("checkbox", { name: "KB600001 — vm-0" }));
    expect(screen.getByText("Select findings and prepare a review (1 selected; 6 available)")).toBeVisible();
    expect(api.createPatchReview).not.toHaveBeenCalled();
  });
  it("recovers ambiguous reply by explicit read without automatic POST retry", async () => {
    api.createPatchReview.mockRejectedValueOnce(new Error("Reply lost"));
    render(<PatchReview query={query} rows={[row]} ready />);
    await screen.findByText(/Patch review revision 0/); fill();
    fireEvent.click(screen.getByRole("button", { name: "Save review-only batch" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/lost reply may still have persisted/);
    expect(screen.getByRole("button", { name: "Save review-only batch" })).toBeDisabled();
    api.patchReviews.mockResolvedValueOnce(envelope(saved));
    fireEvent.click(screen.getByRole("button", { name: "Reload patch review batches" }));
    await screen.findByText(/Patch review revision 1/);
    expect(api.createPatchReview).toHaveBeenCalledTimes(1);
  });
  it("rejects a successful-looking save for a different selection", async () => {
    api.createPatchReview.mockResolvedValueOnce(envelope({ ...saved, batches: [{ ...saved.batches[0], findings: [{ ...saved.batches[0].findings[0], exposure_id: "other" }] }] }));
    render(<PatchReview query={query} rows={[row]} ready />);
    await screen.findByText(/Patch review revision 0/); fill();
    fireEvent.click(screen.getByRole("button", { name: "Save review-only batch" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/exact selection/);
    expect(screen.getByText(/Patch review revision 0/)).toBeVisible();
  });
  it("cannot submit retained rows while current query is refreshing", async () => {
    render(<PatchReview query={query} rows={[row]} ready={false} />);
    await screen.findByText(/Patch review revision 0/);
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(api.createPatchReview).not.toHaveBeenCalled();
  });
  it("fences a late save when the query workspace unmounts", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    api.createPatchReview.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const view = render(<PatchReview query={query} rows={[row]} ready />);
    await screen.findByText(/Patch review revision 0/); fill();
    fireEvent.click(screen.getByRole("button", { name: "Save review-only batch" }));
    await waitFor(() => expect(api.createPatchReview).toHaveBeenCalledOnce());
    view.unmount(); await act(async () => resolve(envelope(saved)));
    expect(screen.queryByText(/Review batch retained/)).not.toBeInTheDocument();
  });
  it("reports read failure and does not enable a save", async () => {
    api.patchReviews.mockRejectedValueOnce(new Error("Storage unavailable"));
    render(<PatchReview query={query} rows={[row]} ready />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Storage unavailable");
    expect(screen.getByRole("checkbox")).toBeDisabled();
  });
});
