import { describe, expect, it } from "vitest";
import { validateKbEvidence } from "./kb-evidence";
import type { Envelope, KbDetail } from "./types";

const detail: KbDetail = {
  kb_id: "KB600001", generation: "silver-patch:one", title: "Update", published_at: "", severity: "critical",
  cve_ids: [], cves: [], affected_servers: ["vm-one"], affected_server_count: 103, affected_business_services: [], findings: [],
  installation_status_counts: { observed_targets: 1000, missing: 100, installation_failed: 3, installed: 800, other: 97 },
  target_status_observations: [{ target_id: "vm-one", status: "missing", observed_at: "" }],
  target_status_observations_truncated: true, update_guidance: { source: "msrc", product_ids: ["recorded-product"], dependency_capability: "not_collected" },
};
const envelope = (): Envelope<KbDetail> => ({ data: structuredClone(detail), scope: { subscription: ["sub-a"] }, evidence: [], warnings: [] });
describe("KB evidence identity and source units", () => {
  it("keeps full-snapshot counts distinct from one sampled target", () => {
    expect(validateKbEvidence(envelope(), "KB600001", { subscription: ["sub-a"] }).data.installation_status_counts?.installed).toBe(800);
  });
  it("keeps absent legacy counts unknown", () => {
    const value = envelope(); value.data.installation_status_counts = null;
    expect(validateKbEvidence(value, "KB600001", value.scope).data.installation_status_counts).toBeNull();
  });
  it.each(["kb", "scope", "generation", "total", "negative", "unsafe", "affected", "sample", "duplicate", "bound", "products"])("rejects inconsistent KB evidence: %s", damage => {
    const value = envelope(), counts = value.data.installation_status_counts!;
    if (damage === "kb") value.data.kb_id = "KB600002";
    if (damage === "scope") value.scope = {};
    if (damage === "generation") value.data.generation = "";
    if (damage === "total") counts.observed_targets = 1001;
    if (damage === "negative") counts.other = -1;
    if (damage === "unsafe") counts.observed_targets = Number.MAX_SAFE_INTEGER + 1;
    if (damage === "affected") value.data.affected_server_count = 999;
    if (damage === "sample") { counts.missing = 0; counts.other += 100; value.data.affected_server_count = 3; }
    if (damage === "duplicate") value.data.target_status_observations!.push(value.data.target_status_observations![0]);
    if (damage === "bound") value.data.target_status_observations_truncated = false;
    if (damage === "products") value.data.update_guidance!.product_ids = [""];
    expect(() => validateKbEvidence(value, "KB600001", { subscription: ["sub-a"] })).toThrow();
  });
});
