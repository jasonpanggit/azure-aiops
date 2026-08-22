/**
 * The 9 scope dimensions the Operations API understands (src/api/scope.py
 * SCOPE_DIMENSIONS). Matching is case-insensitive server-side; an omitted
 * dimension is unconstrained.
 */
export const SCOPE_DIMENSIONS = [
  "business_service",
  "application",
  "environment",
  "subscription",
  "subscription_connection",
  "owner",
  "support_team",
  "region",
  "criticality",
] as const;

export type ScopeDimension = (typeof SCOPE_DIMENSIONS)[number];

/** Human-readable labels for the scope selector UI. */
export const SCOPE_DIMENSION_LABELS: Record<ScopeDimension, string> = {
  business_service: "Business Service",
  application: "Application",
  environment: "Environment",
  subscription: "Subscription",
  subscription_connection: "Subscription Connection",
  owner: "Owner",
  support_team: "Support Team",
  region: "Region",
  criticality: "Criticality",
};

/** Scope values selected by the user, each dimension holding zero or more values. */
export type ScopeSelection = Partial<Record<ScopeDimension, string[]>>;

export const emptyScope = (): ScopeSelection => ({});

/** Serializes a scope selection into repeated query parameters, e.g. `?subscription=a&subscription=b`. */
export function scopeToSearchParams(scope: ScopeSelection): URLSearchParams {
  const params = new URLSearchParams();
  for (const dim of SCOPE_DIMENSIONS) {
    const values = scope[dim];
    if (!values) continue;
    for (const value of values) {
      if (value) params.append(dim, value);
    }
  }
  return params;
}
