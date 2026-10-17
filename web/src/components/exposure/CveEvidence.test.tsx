import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_EXPOSURE_SORT, type ExposureQueryState } from "@/lib/exposure-query-state";
import type { CveEvidenceHistory, CveEvidenceReceipt, CveEvidenceBundle } from "@/lib/types";
import { CveEvidence } from "./CveEvidence";

const api = vi.hoisted(() => ({ cveEvidence: vi.fn(), captureCveEvidence: vi.fn(), cveEvidenceBundle: vi.fn() }));
const download = vi.hoisted(() => ({ verifyEvidenceBytes: vi.fn(), downloadEvidenceJson: vi.fn() }));
vi.mock("@/lib/services", () => ({ vulnerabilityApi: api }));
vi.mock("@/lib/audit-exports", () => download);
const CVE = "CVE-2026-2001";
const query: ExposureQueryState = { scope: { subscription: ["sub-a"] }, filters: { weakness_id: CVE },
  sort: DEFAULT_EXPOSURE_SORT, pageSize: 25, page: 1, cursor: null, cursorHistory: [], target: "", drawer: "", generation: "gen-one" };
const empty: CveEvidenceHistory = { schema_version: 1, actor: "reader", scope: query.scope, cve_id: CVE, revision: 0, receipts: [] };
const receipt: CveEvidenceReceipt = {
  receipt_id: `cve-${"1".repeat(32)}`, cve_id: CVE, actor: "reader", scope: query.scope, captured_at: "2026-10-17T00:00:00Z",
  generation: "gen-one", query_fingerprint: "a".repeat(64), sha256: "b".repeat(64), filters: query.filters,
  page_size: 25, cursor_page: false, sort_by: "priority_score", sort_direction: "desc", total_count: 100,
  source_completeness: "partial", source_observed_at: "2026-10-16T22:00:00Z",
  findings: [{ exposure_id: "finding-one", target_id: "vm-one", weakness_id: CVE, target_kind: "server", completeness: "partial", severity: "critical", sla_state: "unknown" }],
  sources: [{ source: "epss", identifier: CVE, status: "succeeded", stale: false, has_last_known_good: true, source_at: "2026-10-16T21:00:00Z",
    safe_error_code: "", severity: "", cvss_score: null, cvss_vector: "", epss_score: 0.5, kev_listed: null, kb_ids: [], product_ids: [] }],
};
const saved: CveEvidenceHistory = { ...empty, revision: 1, receipts: [receipt] };
const envelope = <T,>(data: T) => ({ data, scope: query.scope, evidence: [], warnings: [] });
const capture = () => screen.getByRole("button", { name: "Capture CVE evidence" });
const bundle = (): CveEvidenceBundle => ({ content: JSON.stringify(receipt), manifest: {
  receipt_id: receipt.receipt_id, cve_id: CVE, receipt_sha256: receipt.sha256, sha256: "c".repeat(64), size_bytes: new TextEncoder().encode(JSON.stringify(receipt)).length,
} });

describe("Private retained CVE evidence", () => {
  beforeEach(() => {
    vi.clearAllMocks(); api.cveEvidence.mockResolvedValue(envelope(empty));
    api.captureCveEvidence.mockResolvedValue(envelope(saved));
    api.cveEvidenceBundle.mockResolvedValue(envelope(bundle()));
    download.verifyEvidenceBytes.mockResolvedValue(undefined);
  });
  it("reads without acquisition and requires a generation-ready explicit capture", async () => {
    const view = render(<CveEvidence cveId={CVE} query={query} ready={false} />);
    await screen.findByText(/CVE evidence revision 0/);
    expect(capture()).toBeDisabled(); expect(api.captureCveEvidence).not.toHaveBeenCalled();
    view.rerender(<CveEvidence cveId={CVE} query={query} ready />);
    fireEvent.click(capture());
    await screen.findByText(/Server evidence receipt retained/);
    expect(api.captureCveEvidence).toHaveBeenCalledTimes(1);
    expect(api.captureCveEvidence).toHaveBeenCalledWith(CVE, query, 0);
    fireEvent.click(screen.getByText(new RegExp(`${receipt.receipt_id} —`)));
    expect(screen.getByText(/finding source observed 2026-10-16T22/)).toBeVisible();
  });
  it("recovers a lost reply by retained reload, never an automatic write replay", async () => {
    api.captureCveEvidence.mockRejectedValueOnce(new Error("Reply lost"));
    render(<CveEvidence cveId={CVE} query={query} ready />);
    await screen.findByText(/CVE evidence revision 0/);
    fireEvent.click(capture()); await screen.findByRole("alert"); expect(capture()).toBeDisabled();
    api.cveEvidence.mockResolvedValueOnce(envelope(saved));
    fireEvent.click(screen.getByRole("button", { name: "Reload CVE receipts" }));
    await screen.findByText(/CVE evidence revision 1/);
    expect(api.captureCveEvidence).toHaveBeenCalledTimes(1);
    expect(capture()).toBeEnabled();
  });
  it.each(["scope", "cve", "actor", "revision", "checksum", "generation", "filter", "count", "prior"])("rejects capture metadata corruption: %s", async damage => {
    const bad = structuredClone(saved);
    if (damage === "scope") bad.scope = {};
    if (damage === "cve") bad.cve_id = "CVE-2026-9999";
    if (damage === "actor") bad.receipts[0].actor = "someone-else";
    if (damage === "revision") bad.revision = 3;
    if (damage === "checksum") bad.receipts[0].sha256 = "invalid";
    if (damage === "generation") bad.receipts[0].generation = "other";
    if (damage === "filter") bad.receipts[0].filters.weakness_id = "CVE-2026-9999";
    if (damage === "count") bad.receipts[0].total_count = 0;
    if (damage === "prior") { api.cveEvidence.mockResolvedValueOnce(envelope(saved)); bad.revision = 2; bad.receipts.push({ ...receipt, receipt_id: `cve-${"2".repeat(32)}` }); bad.receipts[0].total_count = 111; }
    api.captureCveEvidence.mockResolvedValueOnce(envelope(bad));
    render(<CveEvidence cveId={CVE} query={query} ready />);
    await screen.findByText(/CVE evidence revision/);
    fireEvent.click(capture());
    await screen.findByRole("alert"); expect(capture()).toBeDisabled();
    expect(screen.queryByText(/Server evidence receipt retained/)).not.toBeInTheDocument();
  });
  it("separates source/field changes and page membership without claiming remediation", async () => {
    const second = { ...receipt, receipt_id: `cve-${"2".repeat(32)}`, generation: "gen-two", captured_at: "2026-10-17T01:00:00Z",
      total_count: 105, cursor_page: true, sources: [{ ...receipt.sources[0], epss_score: 0.6, stale: true, status: "failed" }],
      findings: [{ ...receipt.findings[0], severity: "high" }, { ...receipt.findings[0], exposure_id: "finding-two" }] };
    api.cveEvidence.mockResolvedValueOnce(envelope({ ...saved, revision: 2, receipts: [receipt, second] }));
    render(<CveEvidence cveId={CVE} query={query} ready />);
    await screen.findByText(/CVE evidence revision 2/);
    fireEvent.change(screen.getByLabelText("Earlier selection"), { target: { value: receipt.receipt_id } });
    fireEvent.change(screen.getByLabelText("Later selection"), { target: { value: second.receipt_id } });
    expect(screen.getByText(/difference 5/)).toBeVisible();
    expect(screen.getByText(/Page membership differences are not new\/resolved/)).toBeVisible();
    expect(screen.getByText("Retained fields differ")).toBeVisible();
    fireEvent.click(screen.getByText(`Inspect source comparison epss:${CVE}`));
    expect(screen.getByText(/"epss_score": 0.6/)).toBeVisible();
    expect(screen.getByText(/cursor positions can change observations/)).toBeVisible();
  });
  it("rejects comparison across different query selections", async () => {
    const second = { ...receipt, receipt_id: `cve-${"2".repeat(32)}`, query_fingerprint: "d".repeat(64) };
    api.cveEvidence.mockResolvedValueOnce(envelope({ ...saved, revision: 2, receipts: [receipt, second] }));
    render(<CveEvidence cveId={CVE} query={query} ready />);
    await screen.findByText(/CVE evidence revision 2/);
    fireEvent.change(screen.getByLabelText("Earlier selection"), { target: { value: receipt.receipt_id } });
    fireEvent.change(screen.getByLabelText("Later selection"), { target: { value: second.receipt_id } });
    expect(screen.getByText(/identical filters, sort and page size/)).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it("verifies and downloads the same exact bytes, not a reserialized projection", async () => {
    api.cveEvidence.mockResolvedValueOnce(envelope(saved));
    const exact = { ...bundle(), content: JSON.stringify(receipt, null, 2) };
    api.cveEvidenceBundle.mockResolvedValueOnce(envelope(exact));
    render(<CveEvidence cveId={CVE} query={query} ready />);
    await screen.findByText(/CVE evidence revision 1/); fireEvent.click(screen.getByText(new RegExp(`${receipt.receipt_id} —`)));
    fireEvent.click(screen.getByRole("button", { name: /Download verified bundle/ }));
    await waitFor(() => expect(download.downloadEvidenceJson).toHaveBeenCalledWith(exact.content, `${CVE}-${receipt.receipt_id}.json`));
    expect(download.verifyEvidenceBytes).toHaveBeenCalledWith(exact.content, exact.manifest);
  });
  it.each(["checksum", "scope", "identity", "payload", "browser"])("blocks unsafe export: %s", async damage => {
    api.cveEvidence.mockResolvedValueOnce(envelope(saved)); const bad = envelope(bundle());
    if (damage === "scope") bad.scope = {};
    if (damage === "identity") bad.data.manifest.cve_id = "CVE-2026-9999";
    if (damage === "payload") bad.data.content = JSON.stringify({ ...receipt, total_count: 500 });
    if (damage === "checksum") download.verifyEvidenceBytes.mockRejectedValueOnce(new Error("Checksum differs"));
    if (damage === "browser") download.downloadEvidenceJson.mockImplementationOnce(() => { throw new Error("Browser refused download"); });
    api.cveEvidenceBundle.mockResolvedValueOnce(bad);
    render(<CveEvidence cveId={CVE} query={query} ready />);
    await screen.findByText(/CVE evidence revision 1/); fireEvent.click(screen.getByText(new RegExp(`${receipt.receipt_id} —`)));
    fireEvent.click(screen.getByRole("button", { name: /Download verified bundle/ }));
    await screen.findByRole("alert");
    if (damage !== "browser") expect(download.downloadEvidenceJson).not.toHaveBeenCalled();
  });
  it("fences a late export after the identity workspace unmounts", async () => {
    api.cveEvidence.mockResolvedValueOnce(envelope(saved));
    let resolve!: (value: ReturnType<typeof envelope<CveEvidenceBundle>>) => void;
    api.cveEvidenceBundle.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const view = render(<CveEvidence cveId={CVE} query={query} ready />);
    await screen.findByText(/CVE evidence revision 1/); fireEvent.click(screen.getByText(new RegExp(`${receipt.receipt_id} —`)));
    fireEvent.click(screen.getByRole("button", { name: /Download verified bundle/ }));
    view.unmount(); await act(async () => resolve(envelope(bundle())));
    expect(download.downloadEvidenceJson).not.toHaveBeenCalled();
  });
  it("keeps capacity and read failures explicit", async () => {
    api.cveEvidence.mockResolvedValueOnce(envelope({ ...empty, revision: 20, receipts: Array.from({ length: 20 }, (_, index) => ({
      ...receipt, receipt_id: `cve-${String(index).padStart(32, "0")}`,
    })) }));
    const view = render(<CveEvidence cveId={CVE} query={query} ready />);
    await screen.findByText(/CVE evidence revision 20/); expect(capture()).toBeDisabled(); view.unmount();
    api.cveEvidence.mockRejectedValueOnce(new Error("Storage unavailable"));
    render(<CveEvidence cveId={CVE} query={query} ready />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Storage unavailable");
    expect(capture()).toBeDisabled();
    expect(within(screen.getByRole("region", { name: "Retained CVE evidence" })).getByRole("button", { name: "Reload CVE receipts" })).toBeEnabled();
  });
});
