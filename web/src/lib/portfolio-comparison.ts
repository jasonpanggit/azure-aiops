import type { PortfolioService, ServicePortfolioObservation } from "./types";

/** A missing label is not a zero count or proof a service was created/deleted. */
export function comparePortfolio(before: ServicePortfolioObservation, after: ServicePortfolioObservation) {
  const left = new Map(before.services.map(row => [row.service_key, row]));
  const right = new Map(after.services.map(row => [row.service_key, row]));
  return Array.from(new Set([...before.services, ...after.services].map(row => row.service_key)))
    .map(key => {
      const earlier = left.get(key) ?? null;
      const later = right.get(key) ?? null;
      const row = later ?? earlier!;
      const fields = ["connection_rows", "mapped_rows", "missing_owner", "missing_support_team", "missing_environment",
        "subscription_count", "incident_associations", "critical_associations"] as const;
      return { key, earlier, later, name: row.kind === "unmapped" ? "Unmapped registry bucket" : row.name,
        changed: !earlier || !later || fields.some(field => earlier[field] !== later[field]) };
    }).sort((a, b) => a.name.localeCompare(b.name) || a.key.localeCompare(b.key));
}

/** Only arithmetic differences between two actually represented label rows. */
export function portfolioDelta(before: PortfolioService | null, after: PortfolioService | null, field: keyof Pick<PortfolioService,
  "connection_rows" | "mapped_rows" | "missing_owner" | "missing_support_team" | "missing_environment" | "incident_associations" | "critical_associations">) {
  if (!before || !after) return "Not comparable";
  const delta = after[field] - before[field];
  return `${delta > 0 ? "+" : ""}${delta}`;
}
