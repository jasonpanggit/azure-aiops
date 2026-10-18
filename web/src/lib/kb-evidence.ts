import { SCOPE_DIMENSIONS, type ScopeSelection } from "@/lib/scope";
import type { Envelope, KbDetail } from "@/lib/types";

/** Bind KB metadata to its effective identity; never infer aggregates from samples. */
export function validateKbEvidence(result: Envelope<KbDetail>, kbId: string, scope: ScopeSelection): Envelope<KbDetail> {
  const data = result.data;
  if (data.kb_id !== kbId || SCOPE_DIMENSIONS.some(dimension =>
    JSON.stringify([...(result.scope[dimension] ?? [])].sort()) !== JSON.stringify([...(scope[dimension] ?? [])].sort()))) {
    throw new Error("KB evidence does not match the requested update and exact scope.");
  }
  const counts = data.installation_status_counts, rows = data.target_status_observations;
  if (rows !== undefined && (!Array.isArray(rows) || rows.length > 100 || new Set(rows.map(row => row.target_id)).size !== rows.length
    || rows.some(row => !row.target_id?.trim() || typeof row.status !== "string" || typeof row.observed_at !== "string"))) {
    throw new Error("KB target observation identities or sample bounds are invalid.");
  }
  const guidance = data.update_guidance;
  if (guidance && (guidance.source !== "msrc" || guidance.dependency_capability !== "not_collected"
    || !Array.isArray(guidance.product_ids) || guidance.product_ids.some(value => typeof value !== "string" || !value.trim() || value.length > 256))) {
    throw new Error("KB provider guidance projection is invalid.");
  }
  if (counts) {
    const values = [counts.observed_targets, counts.missing, counts.installation_failed, counts.installed, counts.other];
    if (!data.generation || values.some(value => !Number.isSafeInteger(value) || value < 0)
      || counts.missing + counts.installation_failed + counts.installed + counts.other !== counts.observed_targets
      || data.affected_server_count !== counts.missing + counts.installation_failed
      || !Array.isArray(rows) || rows.length > 100 || rows.length > counts.observed_targets
      || new Set(rows.map(row => row.target_id)).size !== rows.length
      || data.target_status_observations_truncated !== (counts.observed_targets > rows.length)) {
      throw new Error("KB status evidence has inconsistent source counts or sample boundaries.");
    }
    const sample = { missing: 0, installation_failed: 0, installed: 0, other: 0 };
    rows.forEach(row => {
      if (!row.target_id?.trim() || typeof row.status !== "string" || typeof row.observed_at !== "string") throw new Error("KB target observation is invalid.");
      const status = row.status.toLowerCase();
      if (status === "missing" || status === "installation_failed" || status === "installed") sample[status] += 1;
      else sample.other += 1;
    });
    if (Object.entries(sample).some(([key, value]) => value > counts[key as keyof typeof sample])) {
      throw new Error("KB sampled statuses exceed the full snapshot distribution.");
    }
  }
  return result;
}
