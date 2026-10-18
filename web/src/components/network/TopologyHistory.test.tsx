import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NetworkTopologyHistory, NetworkTopologyComparison, RetainedTopologyNode } from "@/lib/types";
import { TopologyHistory } from "./TopologyHistory";

const api = vi.hoisted(() => ({
  topologyHistory: vi.fn(), captureTopology: vi.fn(), compareTopology: vi.fn(),
}));
vi.mock("@/lib/services", () => ({ networkApi: api }));
const scope = { subscription: ["sub-a"] };
const node: RetainedTopologyNode = {
  id: "/subscriptions/sub-a/vnet/a", name: "Existing VNet", entity_type: "VNet", role: "isolated",
  subscription_id: "sub-a", resource_group: "network", location: "eastus", connection_id: "connection-a",
  environment: "prod", business_service: "Payments", application: "Portal", owner: "Platform",
};
const first = {
  capture_id: "11111111-1111-4111-8111-111111111111", started_at: "2026-10-16T12:00:00Z",
  finished_at: "2026-10-16T12:00:01Z", source_observed_at: "",
  nodes: [node], edges: [], omitted_boundary_peering_count: 1, dropped_relationship_count: 2,
};
const second = { ...first, capture_id: "22222222-2222-4222-8222-222222222222", finished_at: "2026-10-16T12:01:01Z" };
const empty: NetworkTopologyHistory = { schema_version: 1, actor: "reader", scope, revision: 0, captures: [] };
const saved: NetworkTopologyHistory = { ...empty, revision: 2, captures: [first, second] };
const compared: NetworkTopologyComparison = {
  baseline_id: first.capture_id, target_id: second.capture_id,
  total: 1, counts: { added: 0, no_longer_observed: 0, changed: 1 },
  changes: [{
    kind: "node", id: node.id, change: "changed", changed_fields: ["role"],
    before: node, after: { ...node, role: "hub" },
  }],
};
const envelope = <T,>(data: T) => ({ data });

describe("Retained topology history", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.topologyHistory.mockResolvedValue(envelope(saved));
    api.captureTopology.mockResolvedValue(envelope({ ...saved, revision: 3, captures: [...saved.captures, { ...second, capture_id: "33333333-3333-4333-8333-333333333333" }] }));
    api.compareTopology.mockResolvedValue(envelope(compared));
  });

  it("reads history without capture and compares only after explicit review", async () => {
    render(<TopologyHistory scope={scope} />);
    await screen.findByText("2 of 5 retained captures · history revision 2");
    expect(api.captureTopology).not.toHaveBeenCalled();
    expect(api.compareTopology).not.toHaveBeenCalled();
    expect(screen.getByText(/Separate capture requests do not prove independent/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compare retained captures" }));
    await screen.findByRole("region", { name: "Retained topology differences" });
    expect(api.compareTopology).toHaveBeenCalledWith(scope, first.capture_id, second.capture_id, 0, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    fireEvent.click(screen.getByText("Review before and after"));
    expect(screen.getAllByText("Existing VNet")).toHaveLength(2);
    expect(screen.getByText("hub")).toBeInTheDocument();
    expect(screen.getByText(/Absence means not represented.*not deleted/)).toBeInTheDocument();
    expect(screen.getAllByText(/Source observed: Not reported/)).toHaveLength(2);
  });

  it("captures only the reviewed revision and never compares automatically", async () => {
    render(<TopologyHistory scope={scope} />);
    await screen.findByText(/history revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Capture current topology" }));
    await screen.findByText(/Scoped topology projection retained/);
    expect(api.captureTopology).toHaveBeenCalledWith(scope, 2, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(api.compareTopology).not.toHaveBeenCalled();
    expect(screen.getByText(/history revision 3/)).toBeInTheDocument();
  });

  it("has truthful empty and single-capture states", async () => {
    api.topologyHistory.mockResolvedValueOnce(envelope(empty));
    const view = render(<TopologyHistory scope={scope} />);
    await screen.findByText(/No retained topology in this scope/);
    expect(screen.queryByRole("button", { name: "Compare retained captures" })).not.toBeInTheDocument();
    api.captureTopology.mockResolvedValueOnce(envelope({ ...saved, revision: 1, captures: [first] }));
    fireEvent.click(screen.getByRole("button", { name: "Capture current topology" }));
    await screen.findByText("Capture another observation before comparing.");
    expect(screen.getByText(/1 boundary peerings withheld; 2 relationships not projected/)).toBeInTheDocument();
    view.unmount();
  });

  it("rejects same or reversed pairs and clears stale comparison on selection", async () => {
    render(<TopologyHistory scope={scope} />);
    await screen.findByText(/history revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Compare retained captures" }));
    await screen.findByRole("region", { name: "Retained topology differences" });
    fireEvent.change(screen.getByRole("combobox", { name: "Earlier capture" }), { target: { value: second.capture_id } });
    expect(screen.queryByRole("region", { name: "Retained topology differences" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare retained captures" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Later capture" }), { target: { value: first.capture_id } });
    expect(screen.getByRole("button", { name: "Compare retained captures" })).toBeDisabled();
  });

  it("paginates on the server and resets paging for a new selected pair", async () => {
    api.compareTopology.mockResolvedValue(envelope({ ...compared, total: 51 }));
    render(<TopologyHistory scope={scope} />);
    await screen.findByText(/history revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Compare retained captures" }));
    await screen.findByRole("region", { name: "Retained topology differences" });
    expect(screen.getByRole("button", { name: "Previous differences" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next differences" }));
    await waitFor(() => expect(api.compareTopology).toHaveBeenLastCalledWith(scope, first.capture_id, second.capture_id, 50, expect.anything()));
    await screen.findByText("Differences 51–51 of 51");
    expect(screen.getByRole("button", { name: "Next differences" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous differences" }));
    await waitFor(() => expect(api.compareTopology).toHaveBeenLastCalledWith(scope, first.capture_id, second.capture_id, 0, expect.anything()));
  });

  it("requires explicit reload after an unconfirmed capture and blocks duplicate writes", async () => {
    let reject: (reason: Error) => void = () => {};
    api.captureTopology.mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail; }));
    render(<TopologyHistory scope={scope} />);
    await screen.findByText(/history revision 2/);
    const capture = screen.getByRole("button", { name: "Capture current topology" });
    fireEvent.click(capture); fireEvent.click(capture);
    expect(api.captureTopology).toHaveBeenCalledTimes(1);
    await act(async () => reject(new Error("Revision conflict")));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Revision conflict.*Reload topology history/);
    expect(screen.getByRole("button", { name: "Capture current topology" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload topology history" }));
    await screen.findByText(/history revision 2/);
  });

  it("recovers read and comparison failures without extra capture", async () => {
    api.topologyHistory.mockRejectedValueOnce(new Error("Storage unavailable"));
    render(<TopologyHistory scope={scope} />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Reload topology history" }));
    await screen.findByText(/history revision 2/);
    api.compareTopology.mockRejectedValueOnce(new Error("Capture no longer retained"));
    fireEvent.click(screen.getByRole("button", { name: "Compare retained captures" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Capture no longer retained.*Reload history/);
    fireEvent.click(screen.getByRole("button", { name: "Compare retained captures" }));
    await screen.findByRole("region", { name: "Retained topology differences" });
    expect(api.captureTopology).not.toHaveBeenCalled();
  });

  it("isolates a scope change immediately and ignores late capture contents", async () => {
    let resolve: (value: unknown) => void = () => {};
    api.captureTopology.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const view = render(<TopologyHistory scope={scope} />);
    await screen.findByText(/history revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Capture current topology" }));
    const signal: AbortSignal = api.captureTopology.mock.calls[0][2].signal;
    api.topologyHistory.mockResolvedValueOnce(envelope({ ...empty, scope: { region: ["westus"] } }));
    view.rerender(<TopologyHistory scope={{ region: ["westus"] }} />);
    expect(screen.queryByRole("combobox", { name: "Earlier capture" })).not.toBeInTheDocument();
    await screen.findByText(/No retained topology in this scope/);
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(envelope(saved)));
    expect(screen.queryByRole("combobox", { name: "Earlier capture" })).not.toBeInTheDocument();
  });

  it("aborts pending comparisons when unmounted", async () => {
    api.compareTopology.mockReturnValueOnce(new Promise(() => {}));
    const view = render(<TopologyHistory scope={scope} />);
    await screen.findByText(/history revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Compare retained captures" }));
    const signal: AbortSignal = api.compareTopology.mock.calls[0][4].signal;
    view.unmount();
    expect(signal.aborted).toBe(true);
  });

  it("reports zero differences without claiming no infrastructure changes", async () => {
    api.compareTopology.mockResolvedValueOnce(envelope({ ...compared, changes: [], total: 0, counts: { added: 0, changed: 0, no_longer_observed: 0 } }));
    render(<TopologyHistory scope={scope} />);
    await screen.findByText(/history revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Compare retained captures" }));
    await screen.findByText(/not proof that the estate did not change/);
    expect(screen.queryByRole("region", { name: "Retained topology differences" })).not.toBeInTheDocument();
  });

  it("keeps difference tables keyboard-scrollable", async () => {
    render(<TopologyHistory scope={scope} />);
    await screen.findByText(/history revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Compare retained captures" }));
    const region = await screen.findByRole("region", { name: "Retained topology differences" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(within(region).getAllByText(node.id)).toHaveLength(3);
  });
});
