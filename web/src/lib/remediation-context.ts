import type { RemediationPlan } from "./types";

/** Compare KB selectors without turning an unrelated weakness into an update. */
export function samePatch(left: string, right: string): boolean {
  const canonical = (value: string) => value.trim().toUpperCase().replace(/^KB-?/, "");
  return /^\d{4,20}$/.test(canonical(left)) && canonical(left) === canonical(right);
}

/** Require server-projected typed identity, never title or recommendation matching. */
export function matchesRemediationContext(plan: Pick<RemediationPlan, "remediation_context">, cve: string, kb: string): boolean {
  if (!cve && !kb) return true;
  const binding = plan.remediation_context;
  if (!binding || typeof binding.target_id !== "string" || !binding.target_id
    || !Array.isArray(binding.cve_ids) || !Array.isArray(binding.patch_ids)
    || binding.patch_ids.some(id => typeof id !== "string")) return false;
  return (!cve || (/^CVE-\d{4}-\d{4,}$/.test(cve) && binding.cve_ids.includes(cve)))
    && (!kb || (/^KB\d{4,20}$/.test(kb) && binding.patch_ids.some(id => samePatch(id, kb))));
}
