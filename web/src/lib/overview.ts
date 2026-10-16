import { scopeToSearchParams, type ScopeSelection } from "./scope";
import type { SubscriptionConnection } from "./types";

/** Preserve the incumbent v1 weights while making each input and deduction inspectable. */
export function overviewPosture(criticalSituations?: number, exposedFindings?: number, networkGaps?: number) {
  const contributors = [
    { id: "situations", label: "Loaded P1 situations", count: criticalSituations, weight: 18, path: "/situations" },
    { id: "exposure", label: "Internet-exposed vulnerability findings", count: exposedFindings, weight: 7, path: "/exposure" },
    { id: "network", label: "Network gaps", count: networkGaps, weight: 4, path: "/network" },
  ].map(row => {
    const count = typeof row.count === "number" && Number.isSafeInteger(row.count) && row.count >= 0 ? row.count : null;
    return { ...row, count, deduction: count === null ? null : count * row.weight };
  });
  const rawDeduction = contributors.reduce<number | null>((sum, row) =>
    sum === null || row.deduction === null ? null : sum + row.deduction, 0);
  return { contributors, rawDeduction, score: rawDeduction === null ? null : Math.max(0, 100 - rawDeduction) };
}

/** Retain all selected scope dimensions when following an evidence review link. */
export function overviewHref(path: string, scope: ScopeSelection, connection?: string): string {
  const params = scopeToSearchParams(scope);
  if (connection) { params.set("tab", "subscriptions"); params.set("connection", connection); }
  return `${path}${params.size ? `?${params}` : ""}`;
}

/** Registry readiness is not proof of publication, control coverage, or resource health. */
export function connectionReviewReasons(connection: SubscriptionConnection): string[] {
  const reasons: string[] = [];
  if (!connection.is_active) reasons.push("Connection disabled");
  if (connection.health_status !== "healthy") reasons.push(`Registry health: ${connection.health_status || "unreported"}`);
  if (connection.sync_status !== "succeeded") reasons.push(`Sync: ${connection.sync_status || "unreported"}`);
  if (!connection.last_successful_sync_at || !Number.isFinite(Date.parse(connection.last_successful_sync_at))) reasons.push("Successful-sync time unreported");
  if (!connection.business_service) reasons.push("Business service unmapped");
  if (!connection.owner) reasons.push("Owner unmapped");
  if (!connection.environment) reasons.push("Environment unmapped");
  return reasons;
}
