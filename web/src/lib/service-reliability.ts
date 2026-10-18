/** Administrator declarations and bounded component measurements, not service uptime. */
export interface ServiceObjective {
  resource_id: string;
  business_service: string;
  success_target_basis_points: number;
  window_hours: 1 | 24 | 168;
}

export interface ServiceObjectivePolicy {
  schema_version: 1;
  scope: Record<string, string[]>;
  revision: number;
  updated_at: string;
  updated_by: string;
  objectives: ServiceObjective[];
}

export interface ServiceComponent {
  resource_id: string;
  resource_name: string;
  business_service: string;
  subscription_id: string;
  subscription_connection: string;
  observed_at: string;
}

export interface ServiceRequestMetrics {
  resource_id: string;
  business_service: string;
  objective: ServiceObjective;
  objective_policy_revision: number;
  window_started_at: string;
  window_finished_at: string;
  source: string;
  aggregate: {
    record_count: number;
    represented_count: number;
    failed_count: number;
    unknown_success_records: number;
    invalid_weight_records: number;
    sampled_records: number;
    invalid_duration_records: number;
    p95_duration_ms: number | null;
    first_observed_at: string | null;
    last_observed_at: string | null;
  };
  request_success_percent: number | null;
  p95_observed_record_duration_ms: number | null;
  allowed_failed_requests: number | null;
  remaining_failed_request_budget: number | null;
  consumed_budget_percent: number | null;
  sampling_estimated: boolean;
  authority: "none";
  interpretation: string;
}
