import type { ProposedResourceChange } from "./types";

/** Historical declared analysis only; source artifacts and full analysis are excluded. */
export interface AssessmentReceipt {
  assessment_id: string;
  artifact_sha256: string;
  source: string;
  change_id: string;
  title: string;
  assessed_at: string;
  retained_at: string;
  risk_score: number;
  risk_level: string;
  confidence: string;
  verdict: string;
  unknowns: string[];
  changes: ProposedResourceChange[];
  impacted_resource_ids: string[];
  business_services: string[];
  traversal_truncated: boolean;
  network_review_digest: string | null;
}

/** Exact authenticated subject/effective-scope collection with reviewed CAS revision. */
export interface AssessmentHistory {
  schema_version: number;
  actor: string;
  scope: Record<string, string[]>;
  revision: number;
  updated_at: string;
  receipts: AssessmentReceipt[];
}

/** Comparison of explicitly selected receipts, not verified revision lineage or outcomes. */
export interface AssessmentComparison {
  baseline: AssessmentReceipt;
  candidate: AssessmentReceipt;
  same_artifact: boolean;
  risk_score_delta: number;
  added_declared_rows: ProposedResourceChange[];
  removed_declared_rows: ProposedResourceChange[];
  added_impacted_resource_ids: string[];
  removed_impacted_resource_ids: string[];
  interpretation: string;
}
