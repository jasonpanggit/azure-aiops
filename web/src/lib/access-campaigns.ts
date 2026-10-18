/** Existing observed-access audiences, not Entra access-review definitions. */
export const REVIEW_AUDIENCES = ["service_owner", "security", "auditor"] as const;
export const ACCESS_RECOMMENDATIONS = ["retain_recommended", "revoke_recommended", "investigate"] as const;
export type ReviewAudience = (typeof REVIEW_AUDIENCES)[number];
export type AccessRecommendation = (typeof ACCESS_RECOMMENDATIONS)[number];

export interface CampaignCreate {
  title: string;
  audience: ReviewAudience;
  reviewer_subject: string;
  due_at: string;
  expected_revision: number;
}
export interface CampaignAddress { campaign_id: string; expected_revision: number }
export interface CampaignDecisionRequest extends CampaignAddress {
  principal_id: string;
  recommendation: AccessRecommendation;
  reason: string;
}
export interface CampaignClosure extends CampaignAddress { reason: string }
export interface CampaignRecordedDecision extends Omit<CampaignDecisionRequest, "campaign_id" | "expected_revision"> {
  actor: string;
  recorded_at: string;
}
export interface CampaignPrincipal {
  principal_id: string;
  principal_type: string;
  assignment_count: number;
  privileged: boolean;
  stale: boolean;
  roles: string[];
  widest_scope: string;
  widest_scope_breadth: string;
  last_changed: string;
  blast_radius: Record<string, number>;
}
export interface AccessCampaign {
  campaign_id: string;
  title: string;
  audience: ReviewAudience;
  reviewer_subject: string;
  created_by: string;
  created_at: string;
  due_at: string;
  status: "open" | "completed" | "cancelled";
  source_sha256: string;
  source_size_bytes: number;
  item_count: number;
  decided_count: number;
  overdue: boolean;
  generated_at: string;
  observed_at: string;
  warning_count: number;
  closure: { actor: string; reason: string; recorded_at: string } | null;
}
interface Capabilities {
  current_subject: string;
  can_manage: boolean;
  scope: Record<string, string[]>;
  revision: number;
}
export interface AccessCampaignCollection extends Capabilities {
  as_of: string;
  campaigns: AccessCampaign[];
}
export interface AccessCampaignDetail extends Capabilities {
  campaign: AccessCampaign;
  source_content: string;
  items: CampaignPrincipal[];
  decisions: CampaignRecordedDecision[];
}
