import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RemediationRollouts } from "./RemediationRollouts";
import { controlRollout, createRollout, readRollouts, type RemediationRollout } from "@/lib/remediation-rollouts";

vi.mock("@/lib/remediation-rollouts", () => ({ readRollouts: vi.fn(), createRollout: vi.fn(), controlRollout: vi.fn() }));
const read = vi.mocked(readRollouts), create = vi.mocked(createRollout), control = vi.mocked(controlRollout);
const target = "/subscriptions/sub-1/resourcegroups/rg/providers/microsoft.compute/virtualmachines/vm-1";
const hash = "a".repeat(64);
const workflow = { plan: { plan_id: "plan-1" }, action: { can_operate: true }, preview: { execution_snapshot: {
  target_id: target, patch_ids: ["KB600001"], target_kind: "Azure VM", operation: "install_patches",
  action_version: "version-1", snapshot_hash: hash,
} } };
const record: RemediationRollout = {
  rollout_id: "RMO-" + "a".repeat(32), terms_hash: "b".repeat(64), revision: 0, opened_wave: 0, paused: false, retired: false, can_manage: true,
  created_by: "operator", created_at: "2026-10-17T00:00:00Z", updated_by: "operator", updated_at: "2026-10-17T00:00:00Z",
  terms: { title: "Exact targets", window_start: "2026-10-17T00:00:00Z", window_end: "2026-10-17T01:00:00Z", require_reconciled_evidence: true,
    members: [{ plan_id: "plan-1", target_id: target, action_version: "version-1", snapshot_hash: hash, patch_ids: ["KB600001"], wave: 1 }] },
  targets: [{ plan_id: "plan-1", target_id: target, wave: 1, status: "not_started", execution_id: "", admission_reason: "rollout_wave_not_open" }],
};

function response(rollouts: RemediationRollout[] = [], revision = 0) {
  return { data: { rollouts, revision }, evidence: [], warnings: [], scope: {}, knowledge_version: "" };
}

async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Open rollout planning" }));
  await screen.findByText(/authorized retained rollout/);
}

function fill() {
  fireEvent.click(screen.getByText("Create an exact-target rollout"));
  fireEvent.change(screen.getByLabelText("Rollout title"), { target: { value: "Reviewed targets" } });
  fireEvent.change(screen.getByLabelText("Window starts (local time)"), { target: { value: "2026-10-17T01:00" } });
  fireEvent.change(screen.getByLabelText("Window ends (local time)"), { target: { value: "2026-10-17T02:00" } });
  fireEvent.click(screen.getByRole("button", { name: "Add current exact preview" }));
}

describe("Explicit governed rollout workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    read.mockResolvedValue(response());
    create.mockResolvedValue({ data: record, evidence: [], warnings: [], scope: {}, knowledge_version: "" });
    control.mockResolvedValue({ data: record, evidence: [], warnings: [], scope: {}, knowledge_version: "" });
  });

  it("acquires stored data only on demand and never executes when reading or closing", async () => {
    render(<RemediationRollouts scope={{ subscription: ["sub-1"] }} workflow={workflow} onChanged={vi.fn()} />);
    expect(read).not.toHaveBeenCalled();
    await open();
    expect(read).toHaveBeenCalledWith({ subscription: ["sub-1"] });
    fireEvent.click(screen.getByRole("button", { name: "Close rollout planning" }));
    expect(create).not.toHaveBeenCalled(); expect(control).not.toHaveBeenCalled();
  });

  it("requires explicit review and posts exact identities with aware UTC times", async () => {
    const changed = vi.fn();
    render(<RemediationRollouts scope={{ region: ["west"] }} workflow={workflow} onChanged={changed} />);
    await open(); fill();
    expect(screen.getByRole("button", { name: "Save immutable rollout terms" })).toBeDisabled();
    expect(screen.getByText(/KB600001/)).toBeVisible();
    fireEvent.click(screen.getByRole("checkbox", { name: /I reviewed/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save immutable rollout terms" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ region: ["west"] }, {
      title: "Reviewed targets", window_start: new Date("2026-10-17T01:00").toISOString(), window_end: new Date("2026-10-17T02:00").toISOString(),
      require_reconciled_evidence: true, expected_revision: 0,
      targets: [{ plan_id: "plan-1", preview_snapshot_hash: hash, selected_patch_ids: ["KB600001"], wave: 1 }],
    }));
    expect(changed).toHaveBeenCalledOnce(); expect(control).not.toHaveBeenCalled();
  });

  it("keeps different target previews and resets review on a wave edit", async () => {
    const view = render(<RemediationRollouts scope={{}} workflow={workflow} onChanged={vi.fn()} />);
    await open(); fill();
    view.rerender(<RemediationRollouts scope={{}} workflow={{ ...workflow, plan: { plan_id: "plan-2" }, preview: { execution_snapshot: { ...workflow.preview.execution_snapshot, target_id: target + "-2" } } }} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Add current exact preview" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /I reviewed/ }));
    fireEvent.change(screen.getByLabelText("Wave for target 2"), { target: { value: "2" } });
    expect(screen.getByRole("checkbox", { name: /I reviewed/ })).not.toBeChecked();
    expect(screen.getAllByRole("button", { name: /Remove target/ })).toHaveLength(2);
  });

  it("requires an explicit confirmation before opening a wave", async () => {
    read.mockResolvedValue(response([record], 3));
    render(<RemediationRollouts scope={{}} workflow={null} onChanged={vi.fn()} />);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Review opening wave 1" }));
    expect(control).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("region", { name: "Review rollout admission change" })).getByRole("button", { name: "Confirm admission change" }));
    await waitFor(() => expect(control).toHaveBeenCalledWith({}, record.rollout_id, { action: "open", wave: 1, expected_revision: 0 }));
    expect(create).not.toHaveBeenCalled();
  });

  it("keeps read-only records readable without showing admission authority", async () => {
    read.mockResolvedValue(response([{ ...record, can_manage: false }]));
    render(<RemediationRollouts scope={{}} workflow={{ ...workflow, action: { can_operate: false } }} onChanged={vi.fn()} />);
    await open();
    expect(screen.queryByRole("button", { name: "Review opening wave 1" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Create an exact-target rollout"));
    expect(screen.getByRole("button", { name: "Add current exact preview" })).toBeDisabled();
  });

  it("locks uncertain mutations until an explicit successful reload", async () => {
    control.mockRejectedValue(new Error("Synthetic response lost"));
    read.mockResolvedValue(response([record]));
    render(<RemediationRollouts scope={{}} workflow={null} onChanged={vi.fn()} />);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Review pausing admissions" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm admission change" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Change not confirmed");
    expect(screen.getByRole("button", { name: "Review opening wave 1" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload stored rollouts" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Review opening wave 1" })).toBeEnabled());
    expect(control).toHaveBeenCalledOnce();
  });

  it("discards a late old-scope mutation and its callbacks", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof controlRollout>>) => void;
    control.mockImplementation(() => new Promise(done => { resolve = done; }));
    read.mockResolvedValue(response([record]));
    const changed = vi.fn();
    const view = render(<RemediationRollouts scope={{ subscription: ["old"] }} workflow={null} onChanged={changed} />);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Review pausing admissions" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm admission change" }));
    read.mockResolvedValue(response());
    view.rerender(<RemediationRollouts scope={{ subscription: ["new"] }} workflow={null} onChanged={changed} />);
    await screen.findByText(/0 authorized retained/);
    await act(async () => resolve({ data: record, evidence: [], warnings: [], scope: {}, knowledge_version: "" }));
    expect(changed).not.toHaveBeenCalled();
    expect(screen.queryByText("Exact targets")).not.toBeInTheDocument();
  });

  it("reports unavailable storage without fabricating an empty collection", async () => {
    read.mockRejectedValue(new Error("Storage unavailable"));
    render(<RemediationRollouts scope={{}} workflow={workflow} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Open rollout planning" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Storage unavailable");
    expect(screen.queryByText(/0 authorized retained/)).not.toBeInTheDocument();
  });

  it("distinguishes a confirmed mutation from a failed follow-up read without replay", async () => {
    read.mockResolvedValueOnce(response([record])).mockRejectedValueOnce(new Error("Read unavailable"));
    const changed = vi.fn();
    render(<RemediationRollouts scope={{}} workflow={null} onChanged={changed} />);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Review pausing admissions" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm admission change" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Change saved, but follow-up read failed");
    expect(changed).toHaveBeenCalledOnce();
    expect(control).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Review pausing admissions" })).toBeDisabled();
  });

  it("cannot add an already bound preview and preserves exact plan navigation", async () => {
    read.mockResolvedValue(response([record]));
    render(<RemediationRollouts scope={{ support_team: ["operations"], criticality: ["high"] }} workflow={{
      ...workflow, preview: { execution_snapshot: { ...workflow.preview.execution_snapshot, rollout: { rollout_id: record.rollout_id, terms_hash: record.terms_hash, wave: 1 } } },
    }} onChanged={vi.fn()} />);
    await open();
    fireEvent.click(screen.getByText("Create an exact-target rollout"));
    expect(screen.getByRole("button", { name: "Add current exact preview" })).toBeDisabled();
    fireEvent.click(screen.getByText("Exact terms and stored target progress"));
    const href = screen.getByRole("link", { name: "Review target workflow" }).getAttribute("href");
    const query = new URL(href!, "http://localhost").searchParams;
    expect(query.get("plan_id")).toBe("plan-1");
    expect(query.get("support_team")).toBe("operations");
    expect(query.get("criticality")).toBe("high");
    expect(create).not.toHaveBeenCalled();
    expect(control).not.toHaveBeenCalled();
  });

  it("requires explicit retirement confirmation and never reopens retired terms", async () => {
    read.mockResolvedValueOnce(response([record])).mockResolvedValue(response([{ ...record, retired: true, paused: true }], 1));
    render(<RemediationRollouts scope={{}} workflow={null} onChanged={vi.fn()} />);
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Review retiring settled terms" }));
    expect(control).not.toHaveBeenCalled();
    expect(screen.getByRole("region", { name: "Review rollout admission change" })).toHaveTextContent("replacement declarations and new approvals are required");
    fireEvent.click(screen.getByRole("button", { name: "Confirm admission change" }));
    await waitFor(() => expect(control).toHaveBeenCalledWith({}, record.rollout_id, { action: "retire", wave: 0, expected_revision: 0 }));
    expect(await screen.findByText(/Terms retired;/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Review resuming admissions" })).not.toBeInTheDocument();
  });
});
