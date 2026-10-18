import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InventoryExportManifest } from "@/lib/types";
import { InventoryExport } from "./InventoryExport";

const api = vi.hoisted(() => ({ current: vi.fn(), create: vi.fn(), batch: vi.fn(), cancel: vi.fn() }));
const downloadCsv = vi.hoisted(() => vi.fn());
vi.mock("@/lib/services", () => ({ inventoryExportApi: api }));
vi.mock("@/lib/csv", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/csv")>(), downloadCsv,
}));

const columns = ["family", "resource_name", "resource_type", "resource_id", "subscription_id", "resource_group", "environment", "location", "observed_at"];
const manifest: InventoryExportManifest = {
  schema_version: 1, export_id: "11111111-1111-4111-8111-111111111111",
  actor: "reader", scope: { subscription: ["sub-a"] }, revision: 1, status: "ready",
  generation_id: "retained-generation-1", query_version: "v1", observed_at: "2026-10-16T06:00:00Z",
  created_at: "2026-10-16T07:00:00Z", expires_at: "2026-10-17T07:00:00Z", total: 501,
  sha256: "a".repeat(64), columns, batch_size: 500, resume_basis: "captured_rows_not_active_generation",
};
const envelope = <T,>(data: T) => ({ data, evidence: [], scope: {}, warnings: [] });
const scope = { subscription: ["sub-a"] };
const props = { scope, generationId: "active-generation-2", viewQuery: "subscription=sub-a&azureSearch=App", initialId: "", initialOffset: 0 };
const row = Object.fromEntries(columns.map(key => [key, key === "resource_name" ? "=formula" : "fixture"]));
const batch = (offset = 0) => ({
  manifest, resources: Array.from({ length: offset === 0 ? 500 : 1 }, () => row),
  offset, next_offset: offset === 0 ? 500 : null,
});

describe("Retained inventory exports", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.current.mockResolvedValue(envelope({ export: manifest }));
    api.batch.mockImplementation((_scope, _id, offset) => Promise.resolve(envelope(batch(offset))));
    api.cancel.mockResolvedValue(envelope({ export: { ...manifest, status: "cancelled", revision: 2 } }));
  });

  it("recovers a retained generation and downloads separate validated immutable batches", async () => {
    render(<InventoryExport {...props} />);
    await screen.findByText("retained-generation-1");
    expect(screen.getByRole("button", { name: "Capture resource export" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Download selected batch (CSV)" }));
    await waitFor(() => expect(downloadCsv).toHaveBeenCalledTimes(1));
    expect(api.batch).toHaveBeenCalledWith(scope, manifest.export_id, 0);
    expect(downloadCsv.mock.calls[0][0]).toContain(`"'=formula"`);
    expect(downloadCsv.mock.calls[0][1]).toBe(`inventory-${manifest.export_id}-0.csv`);
    expect(screen.getByRole("combobox", { name: "Captured batch" })).toHaveValue("500");
    expect(screen.getByRole("link", { name: "Resume selected batch in URL" })).toHaveAttribute("href",
      `/inventory?subscription=sub-a&azureSearch=App&tab=azure&export_id=${manifest.export_id}&export_offset=500`);
    expect(screen.getByRole("status")).toHaveTextContent("not a saved-file receipt");
    fireEvent.click(screen.getByRole("button", { name: "Download selected batch (CSV)" }));
    await waitFor(() => expect(downloadCsv).toHaveBeenCalledTimes(2));
    expect(api.batch).toHaveBeenLastCalledWith(scope, manifest.export_id, 500);
    expect(api.create).not.toHaveBeenCalled();
  });

  it("resumes a bookmarked batch while the active provider is unavailable", async () => {
    render(<InventoryExport {...props} generationId="" initialId={manifest.export_id} initialOffset={500} />);
    await screen.findByText("retained-generation-1");
    expect(screen.getByRole("combobox", { name: "Captured batch" })).toHaveValue("500");
    expect(screen.getByText(/Existing retained batches can still be recovered/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download selected batch (CSV)" }));
    await waitFor(() => expect(downloadCsv).toHaveBeenCalledOnce());
    expect(api.batch).toHaveBeenCalledWith(scope, manifest.export_id, 500);
  });

  it("requires explicit recovery instead of silently substituting another bookmarked capture", async () => {
    render(<InventoryExport {...props} initialId="22222222-2222-4222-8222-222222222222" />);
    await screen.findByText(/bookmarked capture is unavailable/);
    expect(screen.queryByRole("button", { name: "Download selected batch (CSV)" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload current capture" }));
    await screen.findByText("retained-generation-1");
    expect(screen.getByRole("combobox", { name: "Captured batch" })).toHaveValue("0");
  });

  it("creates only the current reviewed generation after proving no active capture exists", async () => {
    api.current.mockResolvedValue(envelope({ export: null }));
    api.create.mockResolvedValue(envelope({ export: { ...manifest, generation_id: props.generationId } }));
    render(<InventoryExport {...props} />);
    const button = screen.getByRole("button", { name: "Capture resource export" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    await screen.findByText(props.generationId);
    expect(api.create).toHaveBeenCalledWith(scope, props.generationId);
  });

  it("retains the failed batch offset for explicit retry without claiming a download", async () => {
    api.batch.mockRejectedValueOnce(new Error("Capture expired; reload"));
    render(<InventoryExport {...props} initialOffset={500} />);
    await screen.findByText("retained-generation-1");
    fireEvent.click(screen.getByRole("button", { name: "Download selected batch (CSV)" }));
    await screen.findByText("Capture expired; reload");
    expect(downloadCsv).not.toHaveBeenCalled();
    expect(screen.getByRole("combobox", { name: "Captured batch" })).toHaveValue("500");
    fireEvent.click(screen.getByRole("button", { name: "Download selected batch (CSV)" }));
    await waitFor(() => expect(downloadCsv).toHaveBeenCalledOnce());
    expect(api.batch).toHaveBeenLastCalledWith(scope, manifest.export_id, 500);
  });

  it.each(["generation", "offset", "rows", "scope", "total"])("rejects mismatched %s batch before download", async (field) => {
    const response = structuredClone(batch());
    if (field === "generation") response.manifest.generation_id = "wrong-generation";
    if (field === "offset") response.offset = 500;
    if (field === "rows") response.resources.pop();
    if (field === "scope") response.manifest.scope = { subscription: ["sub-b"] };
    if (field === "total") response.manifest.total = 502;
    api.batch.mockResolvedValue(envelope(response));
    render(<InventoryExport {...props} />);
    await screen.findByText("retained-generation-1");
    fireEvent.click(screen.getByRole("button", { name: "Download selected batch (CSV)" }));
    await screen.findByText(/returned batch does not match/);
    expect(downloadCsv).not.toHaveBeenCalled();
    expect(screen.getByRole("combobox", { name: "Captured batch" })).toHaveValue("0");
  });

  it("cancels the reviewed revision and suppresses a late pending download", async () => {
    let finish: (response: unknown) => void = () => { throw new Error("Download has not started"); };
    api.batch.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<InventoryExport {...props} />);
    await screen.findByText("retained-generation-1");
    fireEvent.click(screen.getByRole("button", { name: "Download selected batch (CSV)" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel retained export" }));
    await screen.findByText(/cancelled ·/);
    expect(api.cancel).toHaveBeenCalledWith(scope, manifest.export_id, 1);
    await act(async () => { finish(envelope(batch())); });
    expect(downloadCsv).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Download selected batch (CSV)" })).not.toBeInTheDocument();
    expect(screen.getByText(/cannot revoke in-flight requests or downloaded files/)).toBeInTheDocument();
  });

  it("withholds a pending old-scope download immediately on scope replacement", async () => {
    let finish: (response: unknown) => void = () => { throw new Error("Download has not started"); };
    api.batch.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const view = render(<InventoryExport {...props} />);
    await screen.findByText("retained-generation-1");
    fireEvent.click(screen.getByRole("button", { name: "Download selected batch (CSV)" }));
    api.current.mockResolvedValue(envelope({ export: null }));
    view.rerender(<InventoryExport {...props} scope={{ subscription: ["sub-b"] }} />);
    expect(screen.queryByText("retained-generation-1")).not.toBeInTheDocument();
    await act(async () => { finish(envelope(batch())); });
    expect(downloadCsv).not.toHaveBeenCalled();
    expect(api.current).toHaveBeenLastCalledWith({ subscription: ["sub-b"] });
  });

  it("requires reload after a cancellation conflict rather than exposing a stale download", async () => {
    api.cancel.mockRejectedValue(new Error("Revision changed; reload"));
    render(<InventoryExport {...props} />);
    await screen.findByText("retained-generation-1");
    fireEvent.click(screen.getByRole("button", { name: "Cancel retained export" }));
    await screen.findByText("Revision changed; reload");
    expect(screen.queryByRole("button", { name: "Download selected batch (CSV)" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Capture resource export" })).toBeDisabled();
  });
});
