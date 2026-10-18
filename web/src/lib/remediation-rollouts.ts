import { apiRequest } from "./api-client";
import { scopeToSearchParams, type ScopeSelection } from "./scope";

/** One exact server-resolved target declaration, not an execution request. */
export interface RolloutTarget {
  plan_id: string;
  preview_snapshot_hash: string;
  selected_patch_ids: string[];
  wave: number;
}

/** Immutable terms and explicitly opened admission, never a scheduled job. */
export interface RemediationRollout {
  rollout_id: string;
  terms_hash: string;
  revision: number;
  opened_wave: number;
  paused: boolean;
  retired: boolean;
  can_manage: boolean;
  created_by: string;
  created_at: string;
  updated_by: string;
  updated_at: string;
  terms: {
    title: string;
    window_start: string;
    window_end: string;
    require_reconciled_evidence: boolean;
    members: Array<{ plan_id: string; target_id: string; action_version: string; snapshot_hash: string; patch_ids: string[]; wave: number }>;
  };
  targets: Array<{ plan_id: string; target_id: string; wave: number; status: string; execution_id: string; admission_reason: string }>;
}

/** Revision is the server's shared execution-document revision, not a local counter. */
export interface RolloutCollection {
  revision: number;
  rollouts: RemediationRollout[];
}

/** Read stored authorized terms without provider polling. */
export function readRollouts(scope: ScopeSelection, signal?: AbortSignal) {
  return apiRequest<RolloutCollection>("/remediation/rollouts", { query: scopeToSearchParams(scope), signal });
}

/** Reserve exact targets and invalidate prior approvals; does not dispatch work. */
export function createRollout(scope: ScopeSelection, body: {
  title: string; window_start: string; window_end: string; require_reconciled_evidence: boolean;
  targets: RolloutTarget[]; expected_revision: number;
}) {
  return apiRequest<RemediationRollout>("/remediation/rollouts", { method: "POST", query: scopeToSearchParams(scope), body });
}

/** Explicitly change admission; every target still requires its own approved run. */
export function controlRollout(scope: ScopeSelection, id: string, body: {
  action: "open" | "pause" | "resume" | "retire"; wave: number; expected_revision: number;
}) {
  return apiRequest<RemediationRollout>(`/remediation/rollouts/${encodeURIComponent(id)}/admission`, { method: "POST", query: scopeToSearchParams(scope), body });
}
