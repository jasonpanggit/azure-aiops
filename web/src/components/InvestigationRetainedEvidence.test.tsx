import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { InvestigationRetainedEvidence } from "./InvestigationRetainedEvidence";
import type { InvestigationEvidenceCapture, InvestigationEvidenceComparison, InvestigationTeamWorkspace } from "@/lib/investigation-workspaces";

const api = vi.hoisted(() => ({ evidence: vi.fn(), compare: vi.fn() }));
vi.mock("@/lib/investigation-workspaces", () => ({ investigationWorkspacesApi: api }));
const ID = `wrk-${"a".repeat(32)}`, CAP = `cap-${"d".repeat(32)}`;
const source = {
  tool: "business_service_context", status: "ok" as const,
  started_at: "2026-10-17T06:00:00Z", finished_at: "2026-10-17T06:00:01Z",
  data: { finding: "Retained source fact" }, evidence: [], warning: "Upstream coverage partial",
  coverage: "bounded-governed-read-subset" as const, knowledge_version: "source-v1",
};
const view = { title: "Payments", entry_type: "BusinessService" as const, subject: "Original Payments", mode: "engineer" as const };
const receipt: InvestigationEvidenceCapture = {
  schema_version: 1, contract: "investigation-tools-v1", workspace_id: ID, capture_id: CAP,
  actor: "owner", recorded_at: "2026-10-17T06:00:02Z", workspace_revision: 2,
  scope: { subscription: ["sub-a"] }, view, sources: [source],
};
const record = (overrides: Partial<InvestigationTeamWorkspace> = {}): InvestigationTeamWorkspace => ({
  workspace_id: ID, owner: "owner", scope: receipt.scope, latest_revision: 3,
  revision: {
    revision: 3, actor: "owner", recorded_at: receipt.recorded_at, change: "view_updated",
    view: { ...view, subject: "Different current subject" }, readers: ["reader"], editors: [], hypotheses: [], capture_id: CAP,
  },
  current_access: { readers: ["reader"], editors: [] }, can_edit: true, can_share: true,
  captures: [{ capture_id: CAP, digest: "f".repeat(64), workspace_revision: 2, actor: "owner", recorded_at: receipt.recorded_at }],
  history: [], ...overrides,
});
const compared: InvestigationEvidenceComparison = {
  workspace_id: ID, capture_id: CAP, reviewed_revision: 3, expected_revision: 3, finished_at: "2026-10-17T06:02:00Z",
  retained: receipt, current: {
    started_at: "2026-10-17T06:01:59Z", finished_at: "2026-10-17T06:02:00Z", view,
    sources: [{ ...source, data: { finding: "Current source fact" }, knowledge_version: "source-v2" }],
  },
  differences: [{ tool: source.tool, retained_status: "ok", current_status: "ok", data_changed: true, provenance_changed: false, retained_knowledge_version: "source-v1", current_knowledge_version: "source-v2" }],
};
const envelope = <T,>(data: T) => ({ data, warnings: [], scope: receipt.scope, evidence: [] });
const reopen = async () => {
  fireEvent.click(screen.getByRole("button", { name: "Reopen retained source version" }));
  await screen.findByText("Retained projection: revision 2");
};

describe("retained investigation source evidence", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.evidence.mockResolvedValue(envelope(receipt));
    api.compare.mockResolvedValue(envelope(compared));
  });

  it("does not acquire or read evidence merely because a workspace contains retained metadata", () => {
    const retain = vi.fn();
    render(<InvestigationRetainedEvidence workspace={record()} busy={false} onRetain={retain} />);
    expect(api.evidence).not.toHaveBeenCalled();
    expect(api.compare).not.toHaveBeenCalled();
    expect(retain).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Acquire current and compare projections" })).toBeDisabled();
  });

  it("reopens exactly the reviewed version with explicit source coverage and no current acquisition", async () => {
    render(<InvestigationRetainedEvidence workspace={record()} busy={false} onRetain={vi.fn()} />);
    await reopen();
    expect(api.evidence).toHaveBeenCalledWith(ID, CAP, 3, receipt.scope, expect.any(AbortSignal));
    expect(api.compare).not.toHaveBeenCalled();
    expect(screen.getByText(/Original Payments/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("business_service_context: ok", { exact: true }));
    expect(screen.getByText("Retained source fact")).toBeVisible();
    expect(screen.getByText(/Source observation: Unreported/)).toBeVisible();
    expect(screen.getByText("Upstream coverage partial")).toBeVisible();
    expect(screen.getByText(/not a full page or estate snapshot/)).toBeInTheDocument();
  });

  it("keeps retained and current payloads separate and compares only after explicit action", async () => {
    render(<InvestigationRetainedEvidence workspace={record()} busy={false} onRetain={vi.fn()} />);
    await reopen();
    fireEvent.click(screen.getByRole("button", { name: "Acquire current and compare projections" }));
    await screen.findByText("Current comparison (not retained)");
    expect(api.compare).toHaveBeenCalledWith(ID, CAP, 3, 3, receipt.scope, expect.any(AbortSignal));
    expect(screen.getByText(/Bounded payload changed/)).toBeInTheDocument();
    expect(screen.getByText(/source-v1 to source-v2/)).toBeInTheDocument();
    expect(screen.getByText("Retained source fact")).toBeInTheDocument();
    expect(screen.getByText("Current source fact")).toBeInTheDocument();
    expect(screen.getByText(/Unchanged projections do not establish unchanged estate conditions/)).toBeInTheDocument();
  });

  it("labels failed-source comparison as unknown, not no change or no findings", async () => {
    api.compare.mockResolvedValueOnce(envelope({
      ...compared,
      current: { ...compared.current, sources: [{ ...source, status: "unavailable", data: null, warning: "Provider unavailable" }] },
      differences: [{ ...compared.differences[0], current_status: "unavailable", data_changed: null }],
    }));
    render(<InvestigationRetainedEvidence workspace={record()} busy={false} onRetain={vi.fn()} />);
    await reopen();
    fireEvent.click(screen.getByRole("button", { name: "Acquire current and compare projections" }));
    await screen.findByText("Current comparison (not retained)");
    expect(screen.getByText(/Unknown · ok to unavailable/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("business_service_context: unavailable", { exact: true }));
    expect(screen.getByText(/does not mean no findings/)).toBeVisible();
  });

  it("retains at a known generated identity and keeps it after an unconfirmed outcome", async () => {
    const retain = vi.fn().mockResolvedValue(false);
    const recordWithoutCapture = record({ captures: [], revision: { ...record().revision, capture_id: null } });
    render(<InvestigationRetainedEvidence workspace={recordWithoutCapture} busy={false} onRetain={retain} />);
    fireEvent.click(screen.getByRole("button", { name: "Retain current source projections" }));
    await waitFor(() => expect(retain).toHaveBeenCalledOnce());
    const identity = retain.mock.calls[0][0];
    expect(identity).toMatch(/^cap-[0-9a-f]{32}$/);
    expect(screen.getByRole("textbox", { name: "Capture identity" })).toHaveValue(identity);
    expect(api.evidence).not.toHaveBeenCalled();
    expect(api.compare).not.toHaveBeenCalled();
  });

  it("allows readers to inspect and explicitly compare, never retain new versions", async () => {
    render(<InvestigationRetainedEvidence workspace={record({ can_edit: false, can_share: false })} busy={false} onRetain={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Retain current source projections" })).toBeDisabled();
    await reopen();
    expect(screen.getByRole("button", { name: "Acquire current and compare projections" })).toBeEnabled();
  });

  it("blocks historical writes but preserves explicit historical inspection and current comparison", async () => {
    render(<InvestigationRetainedEvidence workspace={record({ latest_revision: 4 })} busy={false} onRetain={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Retain current source projections" })).toBeDisabled();
    await reopen();
    fireEvent.click(screen.getByRole("button", { name: "Acquire current and compare projections" }));
    await waitFor(() => expect(api.compare).toHaveBeenCalledWith(ID, CAP, 3, 4, receipt.scope, expect.any(AbortSignal)));
  });

  it("rejects a mismatched receipt and does not enable comparison", async () => {
    api.evidence.mockResolvedValueOnce(envelope({ ...receipt, capture_id: `cap-${"e".repeat(32)}` }));
    render(<InvestigationRetainedEvidence workspace={record()} busy={false} onRetain={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Reopen retained source version" }));
    await screen.findByText("Retained evidence unavailable");
    expect(screen.queryByText("Retained projection: revision 2")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Acquire current and compare projections" })).toBeDisabled();
  });

  it("rejects a comparison under an unexpected reviewed revision", async () => {
    api.compare.mockResolvedValueOnce(envelope({ ...compared, reviewed_revision: 2 }));
    render(<InvestigationRetainedEvidence workspace={record()} busy={false} onRetain={vi.fn()} />);
    await reopen();
    fireEvent.click(screen.getByRole("button", { name: "Acquire current and compare projections" }));
    await screen.findByText("Retained evidence unavailable");
    expect(screen.queryByText("Current comparison (not retained)")).not.toBeInTheDocument();
    expect(screen.getByText("Retained projection: revision 2")).toBeInTheDocument();
  });

  it("fences a late read after the owning workspace panel is unmounted", async () => {
    let finish!: (value: unknown) => void;
    api.evidence.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const panel = render(<InvestigationRetainedEvidence workspace={record()} busy={false} onRetain={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Reopen retained source version" }));
    const signal = api.evidence.mock.calls[0][4];
    panel.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => finish(envelope(receipt)));
    expect(screen.queryByText("Retained projection: revision 2")).not.toBeInTheDocument();
  });

  it("clears prior projections on explicit capture selection, without fetching or retaining", async () => {
    render(<InvestigationRetainedEvidence workspace={record()} busy={false} onRetain={vi.fn()} />);
    await reopen();
    fireEvent.change(screen.getByRole("combobox", { name: "Retained source version" }), { target: { value: "" } });
    expect(screen.queryByText("Retained projection: revision 2")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Capture identity" })).toHaveValue("");
    expect(api.evidence).toHaveBeenCalledOnce();
    expect(api.compare).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Retain current source projections" })).toBeEnabled();
  });

  it("shows read/conflict failures without replacing retained evidence or retrying", async () => {
    api.compare.mockRejectedValueOnce(new Error("Workspace changed during comparison"));
    render(<InvestigationRetainedEvidence workspace={record()} busy={false} onRetain={vi.fn()} />);
    await reopen();
    fireEvent.click(screen.getByRole("button", { name: "Acquire current and compare projections" }));
    await screen.findByText("Retained evidence unavailable");
    expect(screen.getByText("Retained projection: revision 2")).toBeInTheDocument();
    expect(screen.queryByText("Current comparison (not retained)")).not.toBeInTheDocument();
    expect(api.compare).toHaveBeenCalledOnce();
  });
});
