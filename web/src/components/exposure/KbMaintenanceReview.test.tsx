import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { KbReviewDeclaration, KbReviewHistory } from "@/lib/types";
import { KbMaintenanceReview } from "./KbMaintenanceReview";

const api = vi.hoisted(() => ({ reviews: vi.fn(), createReview: vi.fn() }));
vi.mock("@/lib/services", () => ({ kbApi: api }));
const scope = { subscription: ["sub-a"] };
const declaration: KbReviewDeclaration = {
  generation: "silver-patch:one", owner: "Operations", window_start: "2026-10-20T01:00:00Z",
  window_end: "2026-10-20T02:00:00Z", dependency_kbs: ["KB6000000"], disposition: "needs_review", note: "Check prerequisites",
};
const empty: KbReviewHistory = { schema_version: 1, actor: "reader", scope, kb_id: "KB6000001", revision: 0, reviews: [] };
const saved: KbReviewHistory = { ...empty, revision: 1, reviews: [{
  ...declaration, expected_revision: 0, review_id: `kbr-${"1".repeat(32)}`, recorded_at: "2026-10-17T00:00:00Z",
  source_observed_at: "2026-10-16T00:00:00Z", source_completeness: "partial", source_freshness: "stale",
}] };
const envelope = (data: KbReviewHistory) => ({ data, scope: data.scope, evidence: [], warnings: [] });
function fill() {
  for (const [name, value] of [
    ["Declared review owner", declaration.owner], ["Proposed window start (ISO 8601 with time zone)", declaration.window_start],
    ["Proposed window end (ISO 8601 with time zone)", declaration.window_end], ["Unverified dependency KB references", "KB6000000"],
    ["Maintenance review explanation", declaration.note],
  ]) fireEvent.change(screen.getByRole("textbox", { name }), { target: { value } });
}
function mount(generation: string | undefined = "silver-patch:one") {
  return render(<KbMaintenanceReview kbId="KB6000001" scope={scope} generation={generation} />);
}

describe("KB private maintenance declarations", () => {
  beforeEach(() => {
    vi.clearAllMocks(); api.reviews.mockResolvedValue(envelope(empty)); api.createReview.mockResolvedValue(envelope(saved));
  });
  it("only writes an explicit valid declaration against Silver generation and retains independent clocks", async () => {
    mount(); await screen.findByText(/KB review revision 0/);
    expect(api.createReview).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Retain maintenance review" })).toBeDisabled();
    fill(); fireEvent.click(screen.getByRole("button", { name: "Retain maintenance review" }));
    await screen.findByText(/Maintenance review retained. No window was scheduled/);
    expect(api.createReview).toHaveBeenCalledWith("KB6000001", scope, 0, declaration);
    fireEvent.click(screen.getByText("Inspect retained maintenance reviews"));
    expect(screen.getByText("Check prerequisites")).toBeVisible();
    expect(screen.getByText(/2026-10-16T00:00:00Z \/ partial \/ stale/)).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Maintenance review explanation" })).toHaveValue("");
  });
  it("locks an ambiguous write until explicit retained reload without POST replay", async () => {
    api.createReview.mockRejectedValueOnce(new Error("Reply lost"));
    mount(); await screen.findByText(/KB review revision 0/); fill();
    fireEvent.click(screen.getByRole("button", { name: "Retain maintenance review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/lost reply may have persisted/);
    expect(screen.getByRole("textbox", { name: "Declared review owner" })).toBeDisabled();
    api.reviews.mockResolvedValueOnce(envelope(saved));
    fireEvent.click(screen.getByRole("button", { name: "Reload KB maintenance reviews" }));
    await screen.findByText(/KB review revision 1/);
    expect(api.createReview).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("textbox", { name: "Declared review owner" })).toBeEnabled();
  });
  it.each([
    ["scope", { ...saved, scope: { subscription: ["outside"] } }],
    ["KB", { ...saved, kb_id: "KB6000002" }],
    ["actor", { ...saved, actor: "other" }],
    ["declaration", { ...saved, reviews: [{ ...saved.reviews[0], owner: "Other" }] }],
    ["revision", { ...saved, reviews: [{ ...saved.reviews[0], expected_revision: 1 }] }],
  ])("rejects successful-looking wrong %s replies", async (_, value) => {
    api.createReview.mockResolvedValueOnce(envelope(value));
    mount(); await screen.findByText(/KB review revision 0/); fill();
    fireEvent.click(screen.getByRole("button", { name: "Retain maintenance review" }));
    await screen.findByRole("alert");
    expect(screen.getByText(/KB review revision 0/)).toBeVisible();
    expect(screen.queryByText(/Maintenance review retained/)).not.toBeInTheDocument();
  });
  it.each([
    ["Proposed window start (ISO 8601 with time zone)", "2026-10-20T01:00:00"],
    ["Proposed window end (ISO 8601 with time zone)", "2026-10-19T01:00:00Z"],
    ["Unverified dependency KB references", "KB6000001"],
    ["Unverified dependency KB references", "KB6000000, KB6000000"],
    ["Unverified dependency KB references", "https://example.test"],
  ])("disables invalid %s", async (name, value) => {
    mount(); await screen.findByText(/KB review revision 0/); fill();
    fireEvent.change(screen.getByRole("textbox", { name }), { target: { value } });
    expect(screen.getByRole("button", { name: "Retain maintenance review" })).toBeDisabled();
    expect(api.createReview).not.toHaveBeenCalled();
  });
  it("retained reads work when metadata generation is unavailable", async () => {
    api.reviews.mockResolvedValueOnce(envelope(saved));
    render(<KbMaintenanceReview kbId="KB6000001" scope={scope} />);
    await screen.findByText(/KB review revision 1/);
    expect(screen.getByText(/new reviews are disabled/)).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Declared review owner" })).toBeDisabled();
    fireEvent.click(screen.getByText("Inspect retained maintenance reviews"));
    expect(screen.getByText("Check prerequisites")).toBeVisible();
  });
  it("does not turn a failed read into empty history or enable writing", async () => {
    api.reviews.mockRejectedValueOnce(new Error("Storage unavailable"));
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent("Storage unavailable");
    expect(screen.queryByText(/KB review revision 0/)).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Declared review owner" })).toBeDisabled();
  });
  it("rejects a reload that rewrites retained history", async () => {
    api.reviews.mockResolvedValueOnce(envelope(saved));
    mount(); await screen.findByText(/KB review revision 1/);
    api.reviews.mockResolvedValueOnce(envelope({ ...saved, reviews: [{ ...saved.reviews[0], note: "Rewritten" }] }));
    fireEvent.click(screen.getByRole("button", { name: "Reload KB maintenance reviews" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/immutable history/);
    fireEvent.click(screen.getByText("Inspect retained maintenance reviews"));
    expect(screen.getByText("Check prerequisites")).toBeVisible();
  });
  it("fences late writes after an identity remount", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    api.createReview.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const view = mount(); await screen.findByText(/KB review revision 0/); fill();
    fireEvent.click(screen.getByRole("button", { name: "Retain maintenance review" }));
    await waitFor(() => expect(api.createReview).toHaveBeenCalledOnce());
    view.unmount(); await act(async () => resolve(envelope(saved)));
    expect(screen.queryByText(/Maintenance review retained/)).not.toBeInTheDocument();
  });
});
