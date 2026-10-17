import { describe, expect, it } from "vitest";
import type { KbObservation, KbObservationHistory } from "@/lib/types";
import { compareKbTargets, validateKbObservations } from "./kb-observations";

const scope = { subscription: ["sub-a"] };
const observation: KbObservation = {
  observation_id: `kbo-${"1".repeat(32)}`, captured_at: "2026-10-17T00:00:00Z", generation: "silver-patch:one",
  source_observed_at: "", completeness: "partial", freshness: "unknown",
  counts: { observed_targets: 2, missing: 1, installation_failed: 0, installed: 1, other: 0 },
  targets: [{ target_id: "vm-one", status: "missing", observed_at: "" }], targets_truncated: true, msrc: null,
};
const history: KbObservationHistory = { schema_version: 1, actor: "reader", scope, kb_id: "KB6000001", revision: 1, observations: [observation] };
const envelope = (data: KbObservationHistory) => ({ data, scope: data.scope, evidence: [], warnings: [] });
describe("KB observation replay validation", () => {
  it("preserves independent unknown clocks, populations and absence of catalog", () => {
    expect(validateKbObservations(envelope(history), "KB6000001", scope, null)).toEqual(history);
    const unknown = { ...history, observations: [{ ...observation, counts: null, targets_truncated: null }] };
    expect(validateKbObservations(envelope(unknown), "KB6000001", scope, null)).toEqual(unknown);
  });
  it.each([
    { ...observation, captured_at: "2026-10-17T00:00:00" },
    { ...observation, targets_truncated: false },
    { ...observation, targets: [...observation.targets, ...observation.targets] },
    { ...observation, counts: { ...observation.counts!, missing: -1 } },
    { ...observation, counts: { ...observation.counts!, missing: 0, installed: 2 } },
    { ...observation, counts: null, targets_truncated: false },
    { ...observation, targets: [{ target_id: " ", status: "missing", observed_at: "" }] },
  ])("rejects invalid retained source boundaries", row => {
    expect(() => validateKbObservations(envelope({ ...history, observations: [row] }), "KB6000001", scope, null)).toThrow();
  });
  it("separates status differences from one-sided membership without classifying resolution", () => {
    const second = { ...observation, targets: [{ target_id: "different-sample", status: "installed", observed_at: "" }] };
    expect(compareKbTargets(observation, second)).toEqual({ changes: [], firstOnly: ["vm-one"], secondOnly: ["different-sample"] });
  });
});
