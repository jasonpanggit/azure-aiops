import { SCOPE_DIMENSIONS, type ScopeSelection } from "@/lib/scope";
import type { Envelope, KbObservation, KbObservationHistory } from "@/lib/types";

/** Validate exact retained identity and population/sample boundaries before display. */
export function validateKbObservations(result: Envelope<KbObservationHistory>, kbId: string, scope: ScopeSelection, previous: KbObservationHistory | null) {
  const data = result.data;
  const agrees = (returned: ScopeSelection) => SCOPE_DIMENSIONS.every(dimension =>
    JSON.stringify([...(returned[dimension] ?? [])].sort()) === JSON.stringify([...(scope[dimension] ?? [])].sort()));
  if (!agrees(result.scope) || !agrees(data.scope) || data.kb_id !== kbId || data.schema_version !== 1 || !data.actor
    || !Number.isInteger(data.revision) || data.revision < 0 || data.revision > 20 || !Array.isArray(data.observations)
    || data.observations.length !== data.revision || new Set(data.observations.map(row => row.observation_id)).size !== data.revision) {
    throw new Error("KB observation identity or revision is inconsistent.");
  }
  for (const row of data.observations) {
    if (!/^kbo-[a-f0-9]{32}$/.test(row.observation_id) || !row.generation || row.generation.length > 256
      || !/(Z|[+-]\d\d:\d\d)$/.test(row.captured_at) || !Number.isFinite(Date.parse(row.captured_at))
      || !row.completeness || row.completeness === "unavailable" || !row.freshness || typeof row.source_observed_at !== "string"
      || !Array.isArray(row.targets) || row.targets.length > 100 || new Set(row.targets.map(target => target.target_id)).size !== row.targets.length
      || row.targets.some(target => !target.target_id?.trim() || target.target_id.length > 2048 || !target.status?.trim()
        || target.status.length > 128 || typeof target.observed_at !== "string")) {
      throw new Error("KB source observation attribution or target sample is invalid.");
    }
    if (row.msrc !== null && (!row.msrc || !row.msrc.status || typeof row.msrc.stale !== "boolean"
      || typeof row.msrc.has_last_known_good !== "boolean" || typeof row.msrc.source_at !== "string")) {
      throw new Error("KB retained catalog availability is inconsistent.");
    }
    if (row.counts === null) {
      if (row.targets_truncated !== null) throw new Error("Unknown KB population cannot establish sample completeness.");
    } else {
      const counts = row.counts;
      if (!counts || [counts.observed_targets, counts.missing, counts.installation_failed, counts.installed, counts.other]
        .some(value => !Number.isSafeInteger(value) || value < 0)
        || counts.missing + counts.installation_failed + counts.installed + counts.other !== counts.observed_targets
        || counts.observed_targets < row.targets.length || row.targets_truncated !== (counts.observed_targets > row.targets.length)) {
        throw new Error("KB retained source counts or sample boundaries are inconsistent.");
      }
      const sample = { missing: 0, installation_failed: 0, installed: 0, other: 0 };
      for (const target of row.targets) {
        const status = target.status.toLowerCase();
        if (status === "missing" || status === "installation_failed" || status === "installed") sample[status]++;
        else sample.other++;
      }
      if (Object.entries(sample).some(([key, value]) => value > counts[key as keyof typeof sample])) throw new Error("KB sampled statuses exceed retained population.");
    }
  }
  if (previous && (data.actor !== previous.actor || data.revision < previous.revision
    || JSON.stringify(data.observations.slice(0, previous.revision)) !== JSON.stringify(previous.observations))) {
    throw new Error("KB observation response changed retained attribution or immutable history.");
  }
  return data;
}

/** Compare common sampled identities separately from membership; no resolved/new claims. */
export function compareKbTargets(first: KbObservation, second: KbObservation) {
  const left = new Map(first.targets.map(row => [row.target_id, row]));
  const right = new Map(second.targets.map(row => [row.target_id, row]));
  return {
    changes: first.targets.filter(row => right.has(row.target_id) && row.status !== right.get(row.target_id)!.status)
      .map(row => ({ target_id: row.target_id, before: row, after: right.get(row.target_id)! })),
    firstOnly: first.targets.filter(row => !right.has(row.target_id)).map(row => row.target_id),
    secondOnly: second.targets.filter(row => !left.has(row.target_id)).map(row => row.target_id),
  };
}
