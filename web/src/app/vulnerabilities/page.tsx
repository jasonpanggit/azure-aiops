import { redirect } from "next/navigation";

const CANONICAL_QUERY_KEYS = new Set([
  "tenant",
  "subscription",
  "resource_group",
  "business_service",
  "application",
  "environment",
  "region",
  "q",
  "severity",
  "target_kind",
  "source_family",
  "current_state",
  "sla_state",
  "completeness",
  "active",
  "sla_overdue",
  "sort_by",
  "sort_direction",
  "page_size",
  "row",
  "scroll",
  "generation",
]);

/** Preserves the legacy vulnerability route while consolidating the product under Exposure. */
export default function VulnerabilitiesPage({
  searchParams = {},
}: {
  searchParams?: Record<string, string | string[] | undefined>;
}) {
  const canonical = new URLSearchParams();
  for (const [key, rawValue] of Object.entries(searchParams)) {
    if (!CANONICAL_QUERY_KEYS.has(key)) continue;
    const values = Array.isArray(rawValue) ? rawValue : [rawValue];
    for (const value of values) {
      const normalized = value?.trim() ?? "";
      if (
        normalized &&
        normalized.length <= 2_048 &&
        !/[\u0000-\u001f\u007f]/.test(normalized)
      ) {
        canonical.append(key, normalized);
      }
    }
  }
  const suffix = canonical.toString();
  redirect(`/exposure/patch-priorities${suffix ? `?${suffix}` : ""}`);
}
