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

/** Restore route scope only when it preserves or narrows every current selector constraint. */
export function scopedBookmark(params: Pick<URLSearchParams, "getAll">, current: ScopeSelection): ScopeSelection {
  const result = { ...current };
  for (const dimension of SCOPE_DIMENSIONS) {
    const values = params.getAll(dimension);
    if (!values.length) continue;
    const trimmed = values.map(value => value.trim());
    if (values.some(value => !value.trim() || /[\0\r\n]/.test(value))) {
      throw new Error("The bookmarked scope contains an invalid value. Clear the bookmark or correct its scope.");
    }
    const selected = new Set((current[dimension] ?? []).map(value => value.trim().toLowerCase()));
    if (selected.size && trimmed.some(value => !selected.has(value.toLowerCase()))) {
      throw new Error("The bookmarked scope is outside the current selected scope. Clear the bookmark or change the operating context.");
    }
    result[dimension] = Array.from(new Map(trimmed.map(value => [value.toLowerCase(), value])).values());
  }
  return result;
}
