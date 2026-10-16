import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RetainedAssessments } from "./RetainedAssessments";
import type { AssessmentComparison, AssessmentHistory, AssessmentReceipt } from "@/lib/predeploy-history";

const api = vi.hoisted(() => ({ retained: vi.fn(), retain: vi.fn(), removeRetained: vi.fn(), compareRetained: vi.fn() }));
vi.mock("@/lib/services", () => ({ predeployApi: api }));
const scope = { subscription: ["a", "b"], region: ["eastus"] };
const current = { assessment_id: "c".repeat(32), artifact: { sha256: "c".repeat(64) } };
const receipt: AssessmentReceipt = {
  assessment_id: "a".repeat(32), artifact_sha256: "a".repeat(64), source: "terraform_plan",
  change_id: "plan-a", title: "", assessed_at: "2026-01-01T00:00:00Z", retained_at: "2026-01-01T00:01:00Z",
  risk_score: 20, risk_level: "Low", confidence: "low", verdict: "require_review",
  unknowns: ["Configuration is declared, not observed."], changes: [], impacted_resource_ids: [],
  business_services: [], traversal_truncated: false, network_review_digest: null,
};
const candidate: AssessmentReceipt = { ...receipt, assessment_id: "b".repeat(32), change_id: "plan-b" };
const history: AssessmentHistory = {
  schema_version: 1, actor: "owner", scope, revision: 2, updated_at: receipt.retained_at, receipts: [receipt, candidate],
};
const comparison: AssessmentComparison = {
  baseline: receipt, candidate, same_artifact: true, risk_score_delta: 0,
  added_declared_rows: [], removed_declared_rows: [], added_impacted_resource_ids: [],
  removed_impacted_resource_ids: [], interpretation: "Historical analysis, not verified revision lineage or deployment authority.",
};

function open() {
  fireEvent.click(screen.getByRole("button", { name: "Open retained assessments" }));
}

describe("personal retained assessment receipts", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.retained.mockResolvedValue({ data: structuredClone(history) });
    api.compareRetained.mockResolvedValue({ data: comparison });
  });

  it("loads only on demand and requires two explicit different same-format selections", async () => {
    render(<RetainedAssessments scope={scope} current={null} />);
    expect(api.retained).not.toHaveBeenCalled();
    open();
    await screen.findByText("Revision 2. 2/20 receipts in this exact personal scope.");
    const compare = screen.getByRole("button", { name: "Compare retained assessments" });
    expect(screen.getByRole("combobox", { name: "Baseline receipt" })).toHaveValue("");
    expect(compare).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Baseline receipt" }), { target: { value: receipt.assessment_id } });
    fireEvent.change(screen.getByRole("combobox", { name: "Candidate receipt" }), { target: { value: receipt.assessment_id } });
    expect(compare).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Candidate receipt" }), { target: { value: candidate.assessment_id } });
    fireEvent.click(compare);
    const result = await screen.findByRole("region", { name: "Declared assessment comparison" });
    expect(within(result).getByText(comparison.interpretation)).toBeInTheDocument();
    expect(api.compareRetained).toHaveBeenCalledWith(scope, receipt.assessment_id, candidate.assessment_id, expect.any(AbortSignal));
    expect(api.retain).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("combobox", { name: "Baseline receipt" }), { target: { value: "" } });
    expect(screen.queryByRole("region", { name: "Declared assessment comparison" })).not.toBeInTheDocument();
  });

  it("retains only the displayed assessment reference and reviewed collection revision", async () => {
    api.retain.mockResolvedValue({ data: { ...history, revision: 3, receipts: [...history.receipts, { ...receipt, ...current, artifact_sha256: current.artifact.sha256 }] } });
    render(<RetainedAssessments scope={scope} current={current} />);
    open();
    const retain = await screen.findByRole("button", { name: "Retain displayed assessment" });
    await waitFor(() => expect(retain).toBeEnabled());
    fireEvent.click(retain);
    await screen.findByText(`Assessment ${current.assessment_id} retained as a historical summary, not approval.`);
    expect(api.retain).toHaveBeenCalledWith(scope, current.assessment_id, current.artifact.sha256, 2, expect.any(AbortSignal));
    expect(screen.getByRole("button", { name: "Displayed assessment already retained" })).toBeDisabled();
  });

  it("requires explicit reload after uncertain write, never replaying it", async () => {
    api.retain.mockRejectedValue(new Error("Reviewed revision conflict"));
    render(<RetainedAssessments scope={scope} current={current} />);
    open();
    await waitFor(() => expect(screen.getByRole("button", { name: "Retain displayed assessment" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Retain displayed assessment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Reload retained assessments before explicitly retrying");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload retained assessments" }));
    await waitFor(() => expect(api.retained).toHaveBeenCalledTimes(2));
    expect(api.retain).toHaveBeenCalledTimes(1);
  });

  it("deletes explicitly against the reviewed revision without changing source assessments", async () => {
    api.removeRetained.mockResolvedValue({ data: { ...history, revision: 3, receipts: [candidate] } });
    render(<RetainedAssessments scope={scope} current={null} />);
    open();
    const remove = await screen.findByRole("button", { name: `Delete retained assessment ${receipt.assessment_id}` });
    fireEvent.click(remove);
    await screen.findByText("Retained receipt deleted. The source assessment and artifact were not changed.");
    expect(api.removeRetained).toHaveBeenCalledWith(scope, receipt.assessment_id, 2, expect.any(AbortSignal));
    expect(api.retain).not.toHaveBeenCalled();
  });

  it("does not describe failed recovery as empty or enable retention", async () => {
    api.retained.mockRejectedValue(new Error("Durable storage unavailable"));
    render(<RetainedAssessments scope={scope} current={current} />);
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("Durable storage unavailable");
    expect(screen.queryByText("No retained assessment receipts in this exact personal scope.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retain displayed assessment" })).not.toBeInTheDocument();
  });

  it("aborts late recovery and clears panel state after scope changes", async () => {
    let finish: (value: { data: AssessmentHistory }) => void = () => {};
    api.retained.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const view = render(<RetainedAssessments scope={scope} current={current} />);
    open();
    const signal: AbortSignal = api.retained.mock.calls[0][1];
    view.rerender(<RetainedAssessments scope={{ subscription: ["other"] }} current={null} />);
    expect(signal.aborted).toBe(true);
    await act(async () => finish({ data: history }));
    expect(screen.getByRole("button", { name: "Open retained assessments" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("blocks comparisons between different artifact formats", async () => {
    api.retained.mockResolvedValue({ data: { ...history, receipts: [receipt, { ...candidate, source: "arm_diff" }] } });
    render(<RetainedAssessments scope={scope} current={null} />);
    open();
    await screen.findByText("Revision 2. 2/20 receipts in this exact personal scope.");
    fireEvent.change(screen.getByRole("combobox", { name: "Baseline receipt" }), { target: { value: receipt.assessment_id } });
    fireEvent.change(screen.getByRole("combobox", { name: "Candidate receipt" }), { target: { value: candidate.assessment_id } });
    expect(screen.getByRole("button", { name: "Compare retained assessments" })).toBeDisabled();
    expect(api.compareRetained).not.toHaveBeenCalled();
  });

  it("does not apply or replay a late mutation after scope changes", async () => {
    let finish: (value: { data: AssessmentHistory }) => void = () => {};
    api.retain.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const view = render(<RetainedAssessments scope={scope} current={current} />);
    open();
    await waitFor(() => expect(screen.getByRole("button", { name: "Retain displayed assessment" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Retain displayed assessment" }));
    const signal: AbortSignal = api.retain.mock.calls[0][4];
    view.rerender(<RetainedAssessments scope={{ subscription: ["other"] }} current={null} />);
    expect(signal.aborted).toBe(true);
    await act(async () => finish({ data: history }));
    expect(screen.queryByText(/retained as a historical summary/)).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(api.retain).toHaveBeenCalledTimes(1);
  });
});
