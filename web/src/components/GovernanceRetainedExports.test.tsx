import { createHash, webcrypto } from "node:crypto";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditCaptureCollection, AuditCaptureDetail, AuditCaptureManifest } from "@/lib/audit-exports";
import { GovernanceRetainedExports } from "./GovernanceRetainedExports";

const api = vi.hoisted(() => ({
  retainedExports: vi.fn(), captureExport: vi.fn(), retainedExport: vi.fn(), removeExport: vi.fn(),
}));
vi.mock("@/lib/services", () => ({ governanceApi: api }));
const content = '{"warnings":["Observation time unknown"]}\n';
const row: AuditCaptureManifest = {
  export_id: "a".repeat(32), kind: "identity", captured_at: "2026-10-16T12:00:00Z",
  generated_at: "2026-10-16T11:59:00Z", observed_at: "", warning_count: 1,
  size_bytes: Buffer.byteLength(content), sha256: createHash("sha256").update(content).digest("hex"),
};
const collection: AuditCaptureCollection = {
  actor: "reader", scope: {}, schema_version: 1, revision: 4,
  captures: [row], redaction: "standard_secret_keys",
};
const detail: AuditCaptureDetail = { manifest: row, content, redaction: "standard_secret_keys" };
const response = <T,>(data: T) => ({ data, evidence: [], warnings: [], scope: {} });
async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Open retained evidence" }));
  await screen.findByRole("button", { name: "Review capture" });
}
async function reviewCapture() {
  fireEvent.change(screen.getByLabelText("Evidence kind"), { target: { value: "identity" } });
  fireEvent.click(screen.getByRole("button", { name: "Review capture" }));
}

describe("personal retained audit evidence", () => {
  beforeEach(() => {
    vi.clearAllMocks(); vi.stubGlobal("crypto", webcrypto);
    api.retainedExports.mockResolvedValue(response(collection));
    api.captureExport.mockResolvedValue(response({ ...collection, revision: 5 }));
    api.removeExport.mockResolvedValue(response({ ...collection, revision: 5, captures: [] }));
    api.retainedExport.mockResolvedValue(response(detail));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("reads only on demand and requires kind selection and explicit capture confirmation", async () => {
    render(<GovernanceRetainedExports scope={{ subscription: ["a"] }} />);
    expect(api.retainedExports).not.toHaveBeenCalled();
    await open();
    expect(screen.getByRole("button", { name: "Review capture" })).toBeDisabled();
    expect(screen.getByText(/Source observation: Unknown/)).toHaveTextContent("1 source warnings as captured");
    await reviewCapture();
    expect(api.captureExport).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Capture current evidence" }));
    await screen.findByText(/Current evidence captured/);
    expect(api.captureExport).toHaveBeenCalledWith({ subscription: ["a"] }, "identity", 4, expect.any(AbortSignal));
    expect(screen.getByText(/Revision 5/)).toBeInTheDocument();
  });

  it("verifies content before enabling exact-content download and revokes its object URL", async () => {
    const create = vi.fn<(blob: Blob) => string>(() => "blob:verified"); const revoke = vi.fn();
    vi.stubGlobal("URL", { createObjectURL: create, revokeObjectURL: revoke });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<GovernanceRetainedExports scope={{}} />);
    await open();
    expect(screen.queryByRole("button", { name: "Download verified JSON" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Verify and open Identity" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download verified JSON" }));
    expect(screen.getByLabelText("Verified captured JSON")).toHaveTextContent("Observation time unknown");
    expect(create.mock.calls[0][0]).toBeInstanceOf(Blob);
    expect(create.mock.calls[0][0].size).toBe(row.size_bytes);
    expect(click).toHaveBeenCalledOnce(); expect(revoke).toHaveBeenCalledWith("blob:verified");
    expect(document.querySelector("a[download]")).toBeNull(); click.mockRestore();
  });

  it.each(["checksum", "byte count", "selected manifest"])("blocks download after a %s mismatch", async mismatch => {
    api.retainedExport.mockResolvedValue(response({
      ...detail,
      content: mismatch === "checksum" ? content.replace("warnings", "WARNINGS") : content + (mismatch === "byte count" ? " " : ""),
      manifest: mismatch === "selected manifest" ? { ...row, export_id: "b".repeat(32) } : row,
    }));
    render(<GovernanceRetainedExports scope={{}} />); await open();
    fireEvent.click(screen.getByRole("button", { name: "Verify and open Identity" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(mismatch);
    expect(screen.queryByRole("button", { name: "Download verified JSON" })).not.toBeInTheDocument();
  });

  it("requires confirmed revision-bound removal and does not revoke downloaded files", async () => {
    render(<GovernanceRetainedExports scope={{}} />); await open();
    fireEvent.click(screen.getByRole("button", { name: "Review removal of Identity" }));
    expect(api.removeExport).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }));
    await screen.findByText("Stored copy removed. Downloaded copies are not revoked.");
    expect(api.removeExport).toHaveBeenCalledWith({}, row.export_id, 4, expect.any(AbortSignal));
    expect(screen.getByText(/No retained audit evidence/)).toBeInTheDocument();
  });

  it("keeps recovery available at exhausted revisions and never offers automatic eviction at capacity", async () => {
    api.retainedExports.mockResolvedValueOnce(response({ ...collection, revision: Number.MAX_SAFE_INTEGER }));
    render(<GovernanceRetainedExports scope={{}} />); await open();
    expect(screen.getByRole("button", { name: "Review capture" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Review removal of Identity" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Verify and open Identity" }));
    await screen.findByRole("button", { name: "Download verified JSON" });
    api.retainedExports.mockResolvedValueOnce(response({
      ...collection, captures: Array.from({ length: 10 }, (_, i) => ({ ...row, export_id: String(i).padStart(32, "0") })),
    }));
    fireEvent.click(screen.getByRole("button", { name: "Reload retained evidence" }));
    await screen.findByLabelText("Evidence kind");
    fireEvent.change(screen.getByLabelText("Evidence kind"), { target: { value: "identity" } });
    expect(screen.getByRole("button", { name: "Review capture" })).toBeDisabled();
    expect(api.captureExport).not.toHaveBeenCalled();
  });

  it("reports browser download failure and still releases the object URL", async () => {
    const revoke = vi.fn();
    vi.stubGlobal("URL", { createObjectURL: () => "blob:failed", revokeObjectURL: revoke });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => { throw new Error("Browser download blocked"); });
    render(<GovernanceRetainedExports scope={{}} />); await open();
    fireEvent.click(screen.getByRole("button", { name: "Verify and open Identity" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download verified JSON" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Browser download blocked");
    expect(revoke).toHaveBeenCalledWith("blob:failed");
    expect(document.querySelector("a[download]")).toBeNull(); click.mockRestore();
  });

  it("requires reload after unconfirmed removal while preserving independent recovery", async () => {
    api.removeExport.mockRejectedValueOnce(new Error("Removal could not be confirmed"));
    render(<GovernanceRetainedExports scope={{}} />); await open();
    fireEvent.click(screen.getByRole("button", { name: "Review removal of Identity" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }));
    await screen.findByText(/No request will be replayed automatically/);
    fireEvent.click(screen.getByRole("button", { name: "Verify and open Identity" }));
    await screen.findByRole("button", { name: "Download verified JSON" });
    expect(screen.getByRole("alert")).toHaveTextContent("locked until you reload");
    expect(screen.getByLabelText("Evidence kind")).toBeDisabled();
    expect(api.removeExport).toHaveBeenCalledTimes(1);
  });

  it.each(["Conflict", "Storage unavailable"])("locks uncertain writes after %s until explicit reload, with no replay", async message => {
    api.captureExport.mockRejectedValueOnce(new Error(message));
    render(<GovernanceRetainedExports scope={{}} />); await open(); await reviewCapture();
    fireEvent.click(screen.getByRole("button", { name: "Capture current evidence" }));
    await screen.findByText(/No request will be replayed automatically/);
    expect(screen.getByLabelText("Evidence kind")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload retained evidence" }));
    await screen.findByLabelText("Evidence kind");
    expect(api.captureExport).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Evidence kind")).toHaveValue("");
  });

  it("does not substitute empty success after a failed read", async () => {
    api.retainedExports.mockRejectedValueOnce(new Error("Storage unavailable"));
    render(<GovernanceRetainedExports scope={{}} />);
    fireEvent.click(screen.getByRole("button", { name: "Open retained evidence" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No empty collection");
    expect(screen.queryByLabelText("Evidence kind")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload retained evidence" }));
    await screen.findByLabelText("Evidence kind");
  });

  it("aborts close and scope changes and discards late captures", async () => {
    let resolve!: (value: ReturnType<typeof response<AuditCaptureCollection>>) => void;
    api.captureExport.mockImplementationOnce(() => new Promise(value => { resolve = value; }));
    const view = render(<GovernanceRetainedExports scope={{ subscription: ["a"] }} />);
    await open(); await reviewCapture();
    fireEvent.click(screen.getByRole("button", { name: "Capture current evidence" }));
    const signal = api.captureExport.mock.calls[0][3] as AbortSignal;
    view.rerender(<GovernanceRetainedExports scope={{ subscription: ["b"] }} />);
    expect(signal.aborted).toBe(true);
    await act(async () => { resolve(response({ ...collection, revision: 999 })); });
    expect(screen.queryByText(/Revision 999/)).not.toBeInTheDocument();
    await open();
    api.retainedExport.mockReturnValueOnce(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: "Verify and open Identity" }));
    await waitFor(() => expect(api.retainedExport).toHaveBeenCalled());
    const detailSignal = api.retainedExport.mock.calls[0][2] as AbortSignal;
    fireEvent.click(screen.getByRole("button", { name: "Close retained evidence" }));
    expect(detailSignal.aborted).toBe(true);
  });
});
