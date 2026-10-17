import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ExposureRecoveryEvent, ExposureRecoveryReview, ExposureRecoveryState } from "@/lib/types";
import { ExposureRecovery } from "./ExposureRecovery";

const api = vi.hoisted(() => ({ exposureRecovery: vi.fn(), reviewExposureRecovery: vi.fn() }));
vi.mock("@/lib/services", () => ({ vulnerabilityApi: api }));
const scope = { subscription: ["sub-a"] };
const observationId = `exo-${"1".repeat(32)}`;
const empty: ExposureRecoveryState = {
  schema_version: 1, actor: "reader", scope, revision: 0, events: [],
  candidates: [{ observation_id: observationId, reason: "connection_coverage", explanation: "Recorded connection coverage: 1 / 2.", generation: "gen-one", captured_at: "2026-10-17T00:00:00Z", review: null }],
};
const envelope = (data: ExposureRecoveryState) => ({ data, scope: data.scope, evidence: [], warnings: [] });
const reviewed = (payload: ExposureRecoveryReview, state = empty): ExposureRecoveryState => {
  const event: ExposureRecoveryEvent = { ...payload, event_id: `exr-${String(state.revision + 1).padStart(32, "0")}`, actor: "reader", recorded_at: "2026-10-17T01:00:00Z" };
  return { ...state, revision: state.revision + 1, events: [...state.events, event], candidates: state.candidates.map(row => ({ ...row, review: event })) };
};
const fill = () => {
  fireEvent.change(screen.getByRole("textbox", { name: "Review owner" }), { target: { value: "Operations" } });
  fireEvent.change(screen.getByLabelText("Review target date"), { target: { value: "2026-11-01" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Review explanation" }), { target: { value: "Investigate excluded connection" } });
};
describe("Exposure recovery review", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.exposureRecovery.mockResolvedValue(envelope(empty));
    api.reviewExposureRecovery.mockImplementation((_scope, payload: ExposureRecoveryReview) => Promise.resolve(envelope(reviewed(payload))));
  });
  it("reads retained candidates without automatically queueing, and explicitly declares a review", async () => {
    render(<ExposureRecovery scope={scope} historyRevision={1} />);
    await screen.findByText(/Recovery revision 0/);
    expect(api.reviewExposureRecovery).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Queue recovery review" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Review disposition" })).not.toHaveTextContent("Review closed");
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Queue recovery review" }));
    await screen.findByText(/Review declaration retained/);
    expect(api.reviewExposureRecovery).toHaveBeenCalledWith(scope, {
      expected_revision: 0, observation_id: observationId, reason: "connection_coverage",
      disposition: "queued", owner: "Operations", target_date: "2026-11-01", note: "Investigate excluded connection",
    });
    expect(screen.getByRole("textbox", { name: "Review explanation" })).toHaveValue("");
    fireEvent.click(screen.getByText("Inspect immutable review activity for this gap"));
    expect(screen.getByText("Investigate excluded connection")).toBeVisible();
    expect(screen.getByText(/Closing a review never repairs/)).toBeVisible();
  });
  it("requires reload after an ambiguous write; lost reply recovery never replays the POST", async () => {
    const payload: ExposureRecoveryReview = { expected_revision: 0, observation_id: observationId, reason: "connection_coverage", disposition: "queued", owner: "Operations", target_date: "2026-11-01", note: "Investigate excluded connection" };
    api.reviewExposureRecovery.mockRejectedValueOnce(new Error("Reply lost"));
    render(<ExposureRecovery scope={scope} historyRevision={1} />);
    await screen.findByText(/Recovery revision 0/); fill();
    fireEvent.click(screen.getByRole("button", { name: "Queue recovery review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/lost reply may still have persisted/);
    expect(screen.getByRole("button", { name: "Queue recovery review" })).toBeDisabled();
    api.exposureRecovery.mockResolvedValueOnce(envelope(reviewed(payload)));
    fireEvent.click(screen.getByRole("button", { name: "Reload recovery review" }));
    await screen.findByText(/Recovery revision 1/);
    expect(api.reviewExposureRecovery).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Save recovery review" })).toBeInTheDocument();
  });
  it("keeps closure a review event and preserves the evidence candidate", async () => {
    const payload: ExposureRecoveryReview = { expected_revision: 0, observation_id: observationId, reason: "connection_coverage", disposition: "queued", owner: "", target_date: "", note: "Queued" };
    const first = reviewed(payload);
    api.exposureRecovery.mockResolvedValueOnce(envelope(first));
    api.reviewExposureRecovery.mockImplementationOnce((_scope, next: ExposureRecoveryReview) => Promise.resolve(envelope(reviewed(next, first))));
    render(<ExposureRecovery scope={scope} historyRevision={1} />);
    await screen.findByText(/Recovery revision 1/);
    fireEvent.change(screen.getByRole("combobox", { name: "Review disposition" }), { target: { value: "review_closed" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Review explanation" }), { target: { value: "Reviewed, source unchanged" } });
    fireEvent.click(screen.getByRole("button", { name: "Save recovery review" }));
    await screen.findByText(/Recovery revision 2/);
    expect(screen.getByText(/1 recorded gap candidates/)).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Review disposition" })).toHaveValue("review_closed");
  });
  it("does not call absence of retained gaps current health", async () => {
    api.exposureRecovery.mockResolvedValueOnce(envelope({ ...empty, candidates: [] }));
    render(<ExposureRecovery scope={scope} historyRevision={0} />);
    expect(await screen.findByText(/absence here is not a current health claim/)).toBeVisible();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
  it("handles initial read failure explicitly and permits only reload", async () => {
    api.exposureRecovery.mockRejectedValueOnce(new Error("Storage unavailable"));
    render(<ExposureRecovery scope={scope} historyRevision={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Storage unavailable");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload recovery review" }));
    await screen.findByText(/Recovery revision 0/);
  });
  it("fences a late review after selected scope changes", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    api.reviewExposureRecovery.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const view = render(<ExposureRecovery scope={scope} historyRevision={1} />);
    await screen.findByText(/Recovery revision 0/); fill();
    fireEvent.click(screen.getByRole("button", { name: "Queue recovery review" }));
    await waitFor(() => expect(api.reviewExposureRecovery).toHaveBeenCalledOnce());
    const nextScope = { subscription: ["sub-b"] };
    api.exposureRecovery.mockResolvedValueOnce(envelope({ ...empty, scope: nextScope, candidates: [] }));
    view.rerender(<ExposureRecovery scope={nextScope} historyRevision={0} />);
    await screen.findByText(/No retained gap candidates/);
    await act(async () => resolve(envelope(reviewed({ expected_revision: 0, observation_id: observationId, reason: "connection_coverage", disposition: "queued", owner: "", target_date: "", note: "Old scope" }))));
    expect(screen.queryByText(/Review declaration retained/)).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
  it("rejects foreign scope responses before attaching history", async () => {
    api.exposureRecovery.mockResolvedValueOnce({ ...envelope(empty), scope: {} });
    render(<ExposureRecovery scope={scope} historyRevision={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/scope does not match/);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
  it("rejects success-shaped response that changes the reviewed declaration", async () => {
    api.reviewExposureRecovery.mockImplementationOnce((_scope, next: ExposureRecoveryReview) => Promise.resolve(envelope(reviewed({ ...next, owner: "other" }))));
    render(<ExposureRecovery scope={scope} historyRevision={1} />);
    await screen.findByText(/Recovery revision 0/); fill();
    fireEvent.click(screen.getByRole("button", { name: "Queue recovery review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/does not match/);
    expect(screen.getByText(/Recovery revision 0/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Queue recovery review" })).toBeDisabled();
  });
});
