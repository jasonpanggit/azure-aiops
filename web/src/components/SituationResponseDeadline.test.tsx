import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SituationResponseDeadline } from "./SituationResponseDeadline";
import type { SituationResponseDeadline as Deadline } from "@/lib/types";

const api = vi.hoisted(() => ({ deadline: vi.fn(), declareDeadline: vi.fn() }));
vi.mock("@/lib/services", () => ({ situationsApi: api }));
const scope = { subscription: ["sub-a"], support_team: ["SRE"] };
const declaration = {
  situation_id: "case", evidence_run_id: "run-1", due_at: "2026-10-20T00:00:00Z",
  reason: "Review before migration", actor: "admin-a", declared_at: "2026-10-17T12:00:00Z", revision: 1,
};
const state: Deadline = {
  state: "unknown", reason: "No declared response deadline in this exact scope",
  evaluated_at: "2026-10-17T12:00:00Z", policy_revision: 0, declaration: null,
  authority: "none", interpretation: "Not contractual SLA evidence.", can_write: true,
};
const props = { scope, situationId: "case", evidenceRunId: "run-1" };
function fields(due = "2026-10-20T00:00:00Z") {
  fireEvent.change(screen.getByLabelText("Deadline (UTC ISO timestamp)"), { target: { value: due } });
  fireEvent.change(screen.getByLabelText("Declaration or removal reason"), { target: { value: "Explicit reviewed commitment" } });
}
async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Open response review" }));
  await screen.findByText("Response-review state: unknown");
}

describe("explicit Situation response review", () => {
  beforeEach(() => {
    api.deadline.mockReset().mockResolvedValue({ data: state });
    api.declareDeadline.mockReset().mockResolvedValue({ data: { ...state, state: "due", policy_revision: 1, declaration } });
  });
  it("reads only on demand with exact scope; starts without a default date or reason", async () => {
    render(<SituationResponseDeadline {...props} />);
    expect(api.deadline).not.toHaveBeenCalled();
    await open();
    expect(api.deadline).toHaveBeenCalledWith("case", scope, expect.any(AbortSignal));
    expect(screen.getByLabelText("Deadline (UTC ISO timestamp)")).toHaveValue("");
    expect(screen.getByLabelText("Declaration or removal reason")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Save response deadline" })).toBeDisabled();
    expect(api.declareDeadline).not.toHaveBeenCalled();
  });
  it("saves only explicit UTC input, reviewed run and revision with attribution", async () => {
    render(<SituationResponseDeadline {...props} />); await open(); fields();
    fireEvent.click(screen.getByRole("button", { name: "Save response deadline" }));
    await screen.findByText("Response-review state: due");
    expect(api.declareDeadline).toHaveBeenCalledWith("case", scope, {
      expected_revision: 0, evidence_run_id: "run-1", due_at: "2026-10-20T00:00:00.000Z", reason: "Explicit reviewed commitment",
    }, expect.any(AbortSignal));
    expect(screen.getByText(/admin-a at/)).toBeInTheDocument();
    expect(screen.getByLabelText("Deadline (UTC ISO timestamp)")).toHaveValue("");
  });
  it.each(["2026-10-20T12:00", "2026-02-30T00:00:00Z", "2026-10-20"])("rejects ambiguous or invalid time %s before any write", async due => {
    render(<SituationResponseDeadline {...props} />); await open(); fields(due);
    fireEvent.click(screen.getByRole("button", { name: "Save response deadline" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("explicit UTC");
    expect(api.declareDeadline).not.toHaveBeenCalled();
  });
  it("requires confirmation and a reason to clear; retains the current reviewed run", async () => {
    api.deadline.mockResolvedValue({ data: { ...state, declaration, policy_revision: 4 } });
    api.declareDeadline.mockResolvedValue({ data: { ...state, policy_revision: 5 } });
    render(<SituationResponseDeadline {...props} />); await open();
    expect(screen.getByRole("button", { name: "Remove response deadline" })).toBeDisabled();
    fields("");
    fireEvent.click(screen.getByRole("button", { name: "Remove response deadline" }));
    expect(api.declareDeadline).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm response deadline removal" }));
    await screen.findByText(/declaration removed/);
    expect(api.declareDeadline.mock.calls[0][2]).toEqual({
      expected_revision: 4, evidence_run_id: "run-1", due_at: null, reason: "Explicit reviewed commitment",
    });
  });
  it.each(["changed; reload before retrying", "storage unavailable"])("never replays uncertain writes after %s", async message => {
    api.declareDeadline.mockRejectedValue(new Error(message));
    render(<SituationResponseDeadline {...props} />); await open(); fields();
    fireEvent.click(screen.getByRole("button", { name: "Save response deadline" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("reload before explicitly retrying");
    expect(screen.queryByRole("button", { name: "Save response deadline" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload response review" }));
    await screen.findByText("Response-review state: unknown");
    expect(api.declareDeadline).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Deadline (UTC ISO timestamp)")).toHaveValue("");
  });
  it("reader sees a declaration without mutation controls", async () => {
    api.deadline.mockResolvedValue({ data: { ...state, can_write: false, declaration } });
    render(<SituationResponseDeadline {...props} />); await open();
    expect(screen.getByText(/Read-only\. Administrator/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Deadline (UTC ISO timestamp)")).not.toBeInTheDocument();
  });
  it.each(["scope", "case", "run", "close"])("aborts and ignores late reads across %s transitions", async transition => {
    let resolve!: (value: { data: Deadline }) => void;
    api.deadline.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const { rerender } = render(<SituationResponseDeadline {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Open response review" }));
    await waitFor(() => expect(api.deadline).toHaveBeenCalledTimes(1));
    const signal = api.deadline.mock.calls[0][2] as AbortSignal;
    if (transition === "close") fireEvent.click(screen.getByRole("button", { name: "Close response review" }));
    else rerender(<SituationResponseDeadline {...props} {...(
      transition === "scope" ? { scope: { subscription: ["sub-b"] } } : transition === "case" ? { situationId: "new-case" } : { evidenceRunId: "run-2" }
    )} />);
    expect(signal.aborted).toBe(true);
    await act(async () => resolve({ data: { ...state, declaration } }));
    expect(screen.queryByText("Review before migration")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open response review" })).toBeInTheDocument();
  });
  it("aborts and ignores a late successful write after close", async () => {
    let resolve!: (value: { data: Deadline }) => void;
    api.declareDeadline.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    render(<SituationResponseDeadline {...props} />); await open(); fields();
    fireEvent.click(screen.getByRole("button", { name: "Save response deadline" }));
    await waitFor(() => expect(api.declareDeadline).toHaveBeenCalledTimes(1));
    const signal = api.declareDeadline.mock.calls[0][3] as AbortSignal;
    fireEvent.click(screen.getByRole("button", { name: "Close response review" }));
    expect(signal.aborted).toBe(true);
    await act(async () => resolve({ data: { ...state, declaration } }));
    expect(screen.queryByText(/declaration saved/)).not.toBeInTheDocument();
  });
});
