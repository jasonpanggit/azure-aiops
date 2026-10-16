import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FlatInventoryResource, ResourceHealthHistory as History, RetainedHealthObservation } from "@/lib/types";
import { ResourceHealthHistory } from "./ResourceHealthHistory";

const api = vi.hoisted(() => ({ history: vi.fn(), captureHistory: vi.fn() }));
vi.mock("@/lib/services", () => ({ resourceHealthApi: api }));
const scope = { subscription: ["sub-a"] };
const resource: FlatInventoryResource = {
  family: "compute", resource_id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-a",
  resource_name: "vm-a", resource_type: "microsoft.compute/virtualmachines",
  subscription_id: "sub-a", resource_group: "rg", environment: "test",
};
const observation = (index: number): RetainedHealthObservation => ({
  observation_id: `${index}1111111-1111-4111-8111-111111111111`,
  captured_at: `2026-10-15T12:00:0${index}Z`,
  started_at: index === 0 ? "2026-10-15T11:59:50Z" : "2026-10-15T12:00:00Z",
  finished_at: `2026-10-15T12:00:0${index}Z`,
  resource_observed_at: index === 0 ? "2026-10-15T11:59:55Z" : "2026-10-15T11:59:58Z",
  snapshot_observed_at: index === 0 ? "2026-10-15T11:59:56Z" : "2026-10-15T11:59:59Z",
  classification: "healthy", cached: index > 0, cache_ttl_seconds: 120,
  warning_count: 1, unavailable_metric_count: 2,
  metrics: {
    cpu_percent: index === 0 ? 50 : 0, memory_percent: null, disk_free_percent: null,
    network_in_bytes: index === 0 ? 1024 : 4096, network_out_bytes: 0,
    disk_read_bytes: null, disk_write_bytes: null, os_disk_queue_depth: 0,
  },
});
const empty: History = { schema_version: 1, actor: "reader", scope, resource_id: resource.resource_id, revision: 0, observations: [] };
const history: History = { ...empty, revision: 2, observations: [observation(0), observation(1)] };
const envelope = (data: History) => ({ data, scope: data.scope, evidence: [], warnings: [] });

describe("Resource Health retained collections", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.history.mockResolvedValue(envelope(history));
    api.captureHistory.mockResolvedValue(envelope({ ...history, revision: 3, observations: [...history.observations, observation(2)] }));
  });

  it("distinguishes missing metrics, real zero, arithmetic and source semantics", async () => {
    render(<ResourceHealthHistory scope={scope} resource={resource} onClose={vi.fn()} />);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("-50.0 pp")).toBeInTheDocument();
    expect(within(table).getByText("+3.0 KB")).toBeInTheDocument();
    expect(within(table).getAllByText("Not comparable")).toHaveLength(4);
    expect(within(table).getAllByText("0.0%")).toHaveLength(1);
    expect(screen.getByText(/byte values are not rates/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Retained health: vm-a" })).toHaveFocus();
    fireEvent.click(screen.getByText("Inspect retained collection provenance"));
    expect(screen.getByText(/Cached provider collection; cache TTL 120s/)).toBeInTheDocument();
    expect(api.captureHistory).not.toHaveBeenCalled();
    expect(api.history).toHaveBeenCalledWith(resource.resource_id, scope, expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("requires two receipts and captures only the explicit reviewed revision", async () => {
    api.history.mockResolvedValueOnce(envelope(empty));
    api.captureHistory.mockResolvedValueOnce(envelope({ ...empty, revision: 1, observations: [observation(0)] }));
    render(<ResourceHealthHistory scope={scope} resource={resource} onClose={vi.fn()} />);
    await screen.findByText(/History revision 0/);
    expect(screen.getByText(/Two retained receipts are needed/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Capture available reading" }));
    await screen.findByText(/Server collection retained/);
    expect(api.captureHistory).toHaveBeenCalledWith(resource.resource_id, scope, 0, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByText(/History revision 1/)).toBeInTheDocument();
  });

  it("identifies cached duplicates without treating them as independent samples", async () => {
    api.history.mockResolvedValueOnce(envelope({ ...history, revision: 3, observations: [...history.observations, observation(2)] }));
    render(<ResourceHealthHistory scope={scope} resource={resource} onClose={vi.fn()} />);
    await screen.findByRole("table");
    expect(screen.getByText(/identical provider collection timestamps/)).toBeInTheDocument();
  });

  it("does not present the same receipt as a comparison", async () => {
    render(<ResourceHealthHistory scope={scope} resource={resource} onClose={vi.fn()} />);
    await screen.findByRole("table");
    fireEvent.change(screen.getByRole("combobox", { name: "Reference receipt" }), { target: { value: observation(1).observation_id } });
    expect(screen.getByText("Choose two different receipts.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("recovers a storage failure without acquiring a provider collection", async () => {
    api.history.mockRejectedValueOnce(new Error("Storage unavailable"));
    render(<ResourceHealthHistory scope={scope} resource={resource} onClose={vi.fn()} />);
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Capture available reading" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload retained health" }));
    await screen.findByRole("table");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.captureHistory).not.toHaveBeenCalled();
  });

  it("withholds uncertain revision after a failed capture until an explicit reload", async () => {
    api.captureHistory.mockRejectedValueOnce(new Error("History changed"));
    render(<ResourceHealthHistory scope={scope} resource={resource} onClose={vi.fn()} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Capture available reading" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Capture was not confirmed. Reload before retrying.");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Capture available reading" })).toBeDisabled();
    expect(screen.queryByText(/Server collection retained/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload retained health" }));
    await screen.findByRole("table");
    expect(api.captureHistory).toHaveBeenCalledOnce();
  });

  it.each(["scope", "resource"] as const)("discards old %s data and late capture responses immediately", async change => {
    let resolve!: (result: ReturnType<typeof envelope>) => void;
    api.captureHistory.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const { rerender } = render(<ResourceHealthHistory scope={scope} resource={resource} onClose={vi.fn()} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Capture available reading" }));
    await waitFor(() => expect(api.captureHistory).toHaveBeenCalledOnce());
    const oldSignal = api.captureHistory.mock.calls[0][3].signal as AbortSignal;
    const nextScope = change === "scope" ? { subscription: ["sub-b"] } : scope;
    const nextResource = change === "resource" ? { ...resource, resource_id: `${resource.resource_id}-b`, resource_name: "vm-b" } : resource;
    api.history.mockReturnValueOnce(new Promise(() => {}));
    rerender(<ResourceHealthHistory scope={nextScope} resource={nextResource} onClose={vi.fn()} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(oldSignal.aborted).toBe(true);
    await act(async () => resolve(envelope({ ...history, revision: 3 })));
    expect(screen.queryByText(/Server collection retained/)).not.toBeInTheDocument();
    expect(screen.queryByText(/History revision 3/)).not.toBeInTheDocument();
    expect(api.history).toHaveBeenLastCalledWith(nextResource.resource_id, nextScope, expect.anything());
  });

  it("prevents duplicate capture submission and aborts unconfirmed captures on unmount", async () => {
    let resolve!: (result: ReturnType<typeof envelope>) => void;
    api.captureHistory.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const { unmount } = render(<ResourceHealthHistory scope={scope} resource={resource} onClose={vi.fn()} />);
    await screen.findByRole("table");
    const capture = screen.getByRole("button", { name: "Capture available reading" });
    fireEvent.click(capture); fireEvent.click(capture);
    expect(api.captureHistory).toHaveBeenCalledOnce();
    const signal = api.captureHistory.mock.calls[0][3].signal as AbortSignal;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(envelope(history)));
  });
});
