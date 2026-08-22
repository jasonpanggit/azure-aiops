import {
  SCOPE_DIMENSIONS,
  type ScopeDimension,
} from "./scope";
import type { SubscriptionConnection } from "./types";

export interface ScopeOption {
  value: string;
  label: string;
}

export type ScopeOptions = Record<ScopeDimension, ScopeOption[]>;

function emptyOptions(): ScopeOptions {
  return {
    business_service: [],
    application: [],
    environment: [],
    subscription: [],
    subscription_connection: [],
    owner: [],
    support_team: [],
    region: [],
    criticality: [],
  };
}

function emptySeenValues(): Record<ScopeDimension, Set<string>> {
  return {
    business_service: new Set(),
    application: new Set(),
    environment: new Set(),
    subscription: new Set(),
    subscription_connection: new Set(),
    owner: new Set(),
    support_team: new Set(),
    region: new Set(),
    criticality: new Set(),
  };
}

function addOption(
  options: ScopeOptions,
  seen: Record<ScopeDimension, Set<string>>,
  dimension: ScopeDimension,
  value: string | null | undefined,
  label = value
) {
  const normalized = value?.trim();
  if (!normalized) return;
  const key = normalized.toLocaleLowerCase();
  if (seen[dimension].has(key)) return;
  seen[dimension].add(key);
  options[dimension].push({ value: normalized, label: label?.trim() || normalized });
}

/** Builds selectable operating-context values from accessible subscription connection metadata. */
export function buildScopeOptions(connections: SubscriptionConnection[]): ScopeOptions {
  const options = emptyOptions();
  const seen = emptySeenValues();

  for (const connection of connections) {
    addOption(options, seen, "business_service", connection.business_service);
    addOption(options, seen, "application", connection.application);
    addOption(options, seen, "environment", connection.environment);
    addOption(
      options,
      seen,
      "subscription",
      connection.subscription_id,
      `${connection.name} · ${connection.subscription_id}`
    );
    addOption(
      options,
      seen,
      "subscription_connection",
      connection.connection_id,
      `${connection.name} (${connection.connection_id})`
    );
    addOption(options, seen, "owner", connection.owner);
    addOption(options, seen, "support_team", connection.support_team);
    addOption(options, seen, "region", connection.region);
    addOption(options, seen, "criticality", connection.criticality);
  }

  for (const dimension of SCOPE_DIMENSIONS) {
    options[dimension].sort((left, right) =>
      left.label.localeCompare(right.label, undefined, { sensitivity: "base" })
    );
  }
  return options;
}
