import type { Confidence, TwinScenarioResult } from "./types";

/** Safe historical declarations exclude raw semantic attributes, tags and provider payloads. */
export interface RetainedTwinEntity {
  id: string;
  kind: string;
  name: string;
  state: string;
  confidence: Confidence;
  attributes: Record<string, string>;
  provenance: Array<{ source: string; confidence: Confidence }>;
}

/** Retained links have confirmed retained endpoints, not inferred reachability. */
export interface RetainedTwinRelationship {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence: Confidence;
  provenance: Array<{ source: string; confidence: Confidence }>;
}

/** Immutable safe server capture with a consistency digest, not a source signature. */
export interface TwinCapture {
  snapshot_id: string;
  snapshot_sha256: string;
  retained_at: string;
  projection: {
    schema_version: 1;
    scope: Record<string, string[]>;
    composed_at: string;
    entities: RetainedTwinEntity[];
    relationships: RetainedTwinRelationship[];
    provenance: Array<{ source: string; confidence: Confidence }>;
    warnings: string[];
  };
}

/** Personal exact effective-scope CAS collection; captures are never silently evicted. */
export interface TwinHistory {
  schema_version: 1;
  actor: string;
  scope: Record<string, string[]>;
  revision: number;
  updated_at: string;
  captures: TwinCapture[];
}

/** Added/removed/changed safe declarations, not verified applied changes. */
export interface TwinDelta<T> {
  added: T[];
  removed: T[];
  changed: Array<{ id: string; before: T; after: T; fields: string[] }>;
}

/** Explicitly selected historical comparison independent of current providers. */
export interface TwinCaptureComparison {
  baseline_id: string;
  candidate_id: string;
  baseline_sha256: string;
  candidate_sha256: string;
  baseline_composed_at: string;
  candidate_composed_at: string;
  entities: TwinDelta<RetainedTwinEntity>;
  relationships: TwinDelta<RetainedTwinRelationship>;
  warnings: { baseline: string[]; candidate: string[] };
  interpretation: string;
}

/** Two review questions applied to exactly the same immutable mapped neighborhood. */
export interface TwinScenarioPair {
  snapshot_id: string;
  snapshot_sha256: string;
  composed_at: string;
  authority: "none";
  left: Omit<TwinScenarioResult, "impacted_entities"> & { impacted_entities: RetainedTwinEntity[]; warnings: string[] };
  right: Omit<TwinScenarioResult, "impacted_entities"> & { impacted_entities: RetainedTwinEntity[]; warnings: string[] };
  interpretation: string;
}
