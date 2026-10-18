import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentInvestigationJob } from "./AgentInvestigationJob";
import { SCOPE_DIMENSIONS, type ScopeSelection } from "@/lib/scope";

const api = vi.hoisted(() => ({ startJob: vi.fn(), job: vi.fn(), stopJob: vi.fn(), ledger: vi.fn() }));
vi.mock("@/lib/services", () => ({ multiAgentApi: api }));
const JOB = `job-${"a".repeat(32)}`;
const scope = { subscription: ["sub-a"] };
const record = {
  revision: 1, job_id: JOB, scope, objective: "Review network", timeout_seconds: 30,
  created_at: 1800000000, updated_at: 1800000000, status: "accepted_outcome_unconfirmed",
  stage: "admitted", stop_requested: false, ledger_id: "",
  durability: "durable", liveness: "not_established", cancellation: "scheduling_only",
};
const envelope = <T,>(data: T, selected: ScopeSelection = scope) => ({ data, scope: selected, evidence: [], warnings: [], knowledge_version: "unknown" });

function setup(jobId = "", selected: ScopeSelection = scope) {
  const onResult = vi.fn(), onActiveChange = vi.fn();
  const props = { objective: "Review network", scope: selected, jobId, disabled: false, onResult, onActiveChange };
  return { ...render(<AgentInvestigationJob {...props} />), props, onResult, onActiveChange };
}

describe("Durable background investigation control", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/agents");
    vi.spyOn(crypto, "randomUUID").mockReturnValue("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");
    api.startJob.mockResolvedValue(envelope(record));
    api.job.mockResolvedValue(envelope({ ...record, status: "running", stage: "tool:network:network_topology" }));
    api.stopJob.mockResolvedValue(envelope({ ...record, status: "running", stop_requested: true }));
    api.ledger.mockResolvedValue(envelope({ ledger_id: "mai-exact", scope, objective: record.objective }));
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it("writes a known-ID recovery bookmark before its one admission request", async () => {
    api.startJob.mockImplementationOnce((id, objective, selected) => {
      expect(window.location.search).toContain(`job_id=${JOB}`);
      expect([id, objective, selected]).toEqual([JOB, record.objective, scope]);
      return Promise.resolve(envelope(record));
    });
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Start background investigation" }));
    expect(await screen.findByText("Accepted - outcome unconfirmed")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open request recovery link" })).toHaveAttribute("href", `/agents?subscription=sub-a&job_id=${JOB}`);
    expect(api.startJob).toHaveBeenCalledTimes(1);
    expect(api.ledger).not.toHaveBeenCalled();
    expect(screen.getByText(/provider cancellation is not supported/)).toBeVisible();
  });

  it("recovers a lost admission reply only by exact-ID reads, never another POST", async () => {
    api.startJob.mockRejectedValueOnce(new Error("Synthetic lost reply"));
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Start background investigation" }));
    expect(await screen.findByText(/Admission is unconfirmed/)).toBeVisible();
    expect(screen.getByText(JOB)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Check exact request" }));
    expect(await screen.findByText("Last reported running")).toBeVisible();
    expect(api.startJob).toHaveBeenCalledTimes(1);
    expect(api.job.mock.calls[0].slice(0, 2)).toEqual([JOB, scope]);
  });

  it("reopens exact metadata without admission, provider acquisition or automatic polling", async () => {
    setup(JOB);
    expect(await screen.findByText("Last reported running")).toBeVisible();
    expect(api.startJob).not.toHaveBeenCalled();
    expect(api.ledger).not.toHaveBeenCalled();
    expect(api.job).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Resume status updates" })).toBeVisible();
  });

  it("distinguishes stop request from stopped scheduling and never claims remote cancellation", async () => {
    setup(JOB);
    await screen.findByText("Last reported running");
    fireEvent.click(screen.getByRole("button", { name: "Stop new scheduling" }));
    expect(await screen.findByText(/Stop requested\. Completion may win/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Stop new scheduling" })).toBeDisabled();
    expect(api.stopJob).toHaveBeenCalledWith(JOB, scope);
    expect(api.startJob).not.toHaveBeenCalled();
    api.job.mockResolvedValueOnce(envelope({ ...record, status: "stopped", stop_requested: true, stage: "stopped_at_safe_boundary" }));
    fireEvent.click(screen.getByRole("button", { name: "Check exact request" }));
    expect(await screen.findByText("New scheduling stopped")).toBeVisible();
    expect(screen.getByText(/new scheduling acknowledged stopped/)).toBeVisible();
    expect(api.ledger).not.toHaveBeenCalled();
  });

  it("loads only the exact completed ledger and keeps read failure recoverable without redispatch", async () => {
    api.job.mockResolvedValue(envelope({ ...record, status: "completed", ledger_id: "mai-exact" }));
    api.ledger.mockRejectedValueOnce(new Error("Synthetic retained ledger unavailable"));
    const { onResult } = setup(JOB);
    expect(await screen.findByText("Synthetic retained ledger unavailable")).toBeVisible();
    expect(onResult).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Check exact request" }));
    await waitFor(() => expect(onResult).toHaveBeenCalledTimes(1));
    expect(api.ledger).toHaveBeenLastCalledWith("mai-exact", scope);
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it.each([
    { job_id: `job-${"b".repeat(32)}` },
    { scope: { subscription: ["foreign"] } },
    { status: "completed", ledger_id: "" },
    { status: "toString" },
    { updated_at: NaN },
  ])("refuses foreign or invalid job metadata: %j", async change => {
    api.job.mockResolvedValueOnce(envelope({ ...record, ...change }));
    const { onResult } = setup(JOB);
    expect(await screen.findByText("Investigation request unconfirmed")).toBeVisible();
    expect(onResult).not.toHaveBeenCalled();
    expect(api.ledger).not.toHaveBeenCalled();
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("rejects an unrelated completed ledger without losing the exact job identity", async () => {
    api.job.mockResolvedValueOnce(envelope({ ...record, status: "completed", ledger_id: "mai-exact" }));
    api.ledger.mockResolvedValueOnce(envelope({ ledger_id: "mai-foreign", scope }));
    const { onResult } = setup(JOB);
    expect(await screen.findByText(/retained ledger did not match this exact request/)).toBeVisible();
    expect(onResult).not.toHaveBeenCalled();
    expect(screen.getByText(JOB)).toBeVisible();
  });

  it("fences an old job read across a new exact selection and aborts on unmount", async () => {
    let finish: (value: unknown) => void = () => {};
    api.job.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const { rerender, unmount, props, onResult } = setup(JOB);
    const firstSignal = api.job.mock.calls[0][2].signal;
    const next = `job-${"b".repeat(32)}`;
    api.job.mockResolvedValueOnce(envelope({ ...record, job_id: next, status: "failed" }));
    rerender(<AgentInvestigationJob {...props} jobId={next} />);
    expect(await screen.findByText("Execution or retention failed")).toBeVisible();
    await act(async () => { finish(envelope({ ...record, status: "completed", ledger_id: "mai-exact" })); });
    expect(onResult).not.toHaveBeenCalled();
    expect(api.ledger).not.toHaveBeenCalled();
    expect(firstSignal.aborted).toBe(true);
    unmount();
    expect(api.job.mock.calls[1][2].signal.aborted).toBe(true);
  });

  it("clears an explicitly removed job selection instead of retaining an old recovery identity", async () => {
    const { rerender, props } = setup(JOB);
    await screen.findByText("Last reported running");
    rerender(<AgentInvestigationJob {...props} jobId="" />);
    expect(await screen.findByRole("button", { name: "Start background investigation" })).toBeEnabled();
    expect(screen.queryByText(JOB)).not.toBeInTheDocument();
    expect(api.startJob).not.toHaveBeenCalled();
  });

  it("bounds automatic polling and resumes only metadata reads on explicit request", async () => {
    vi.useFakeTimers();
    setup();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Start background investigation" })); });
    for (let index = 0; index < 60; index += 1) await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(api.job).toHaveBeenCalledTimes(60);
    expect(screen.getByText(/Automatic status reads paused after 60 checks/)).toBeVisible();
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(api.job).toHaveBeenCalledTimes(60);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Check exact request" })); });
    expect(api.job).toHaveBeenCalledTimes(61);
    expect(api.startJob).toHaveBeenCalledTimes(1);
  });

  it("retains every selected dimension and repeated value in admission and recovery links", async () => {
    const selected = Object.fromEntries(SCOPE_DIMENSIONS.map(key => [key, [`${key}-a`, `${key}-b`]]));
    api.startJob.mockResolvedValueOnce(envelope({ ...record, scope: selected }, selected));
    setup("", selected);
    fireEvent.click(screen.getByRole("button", { name: "Start background investigation" }));
    await screen.findByText("Accepted - outcome unconfirmed");
    expect(api.startJob.mock.calls[0][2]).toEqual(selected);
    const link = new URL(screen.getByRole("link", { name: "Open request recovery link" }).getAttribute("href")!, "http://localhost");
    for (const dimension of SCOPE_DIMENSIONS) expect(link.searchParams.getAll(dimension)).toEqual(selected[dimension]);
  });
});
