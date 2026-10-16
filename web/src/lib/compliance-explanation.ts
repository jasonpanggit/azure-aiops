import type { ComplianceDesignPolicy, ComplianceDeviation } from "./types";

const POLICY_FIELDS: Record<keyof ComplianceDesignPolicy, { label: string; effect: string }> = {
  name: { label: "Policy pack name", effect: "Metadata only; does not change the local finding rules." },
  requiredHubRouting: { label: "Required hub routing", effect: "Declared intent only. Network gaps use the server's independent Network design policy; this switch does not re-evaluate routes." },
  firewallInspectionRequired: { label: "Firewall inspection required", effect: "Rechecks forwarded-traffic flags on observed peerings; independent server gap findings are unchanged." },
  environmentIsolationRequired: { label: "Environment isolation required", effect: "Declared intent only. No environment-isolation evaluator is connected to this assessment switch." },
  allowedPorts: { label: "Allowed ports", effect: "Changes text-based rule classification only; this is not a port or reachability validation." },
  privateEndpointRequiredFor: { label: "Private endpoint required for", effect: "Changes type-matching checks for missing private-access evidence in the loaded topology." },
  requiredDnsZones: { label: "Required DNS zones", effect: "Changes text-matching checks for approved DNS-zone evidence; does not resolve DNS." },
  loggingRequired: { label: "Logging required", effect: "Includes or excludes missing-logging-evidence heuristics; does not validate actual log delivery." },
  ownerTag: { label: "Owner tag", effect: "Changes the preferred tag lookup when semantic ownership is absent; the observed owner tag remains a fallback." },
  allowCrossSubscriptionPeering: { label: "Allow cross-subscription peering", effect: "Includes or excludes observed cross-subscription peering findings; does not change peering or authorize traffic." },
};

/** Explain exact draft changes, including intents with no connected evaluator. */
export function explainPolicyChanges(before: ComplianceDesignPolicy, after: ComplianceDesignPolicy) {
  return (Object.keys(POLICY_FIELDS) as Array<keyof ComplianceDesignPolicy>)
    .filter(field => before[field] !== after[field])
    .map(field => ({ field, ...POLICY_FIELDS[field], before: before[field], after: after[field] }));
}

/** Look up only known policy-field labels; historical unknowns remain visible. */
export function policyFieldLabel(field: keyof ComplianceDesignPolicy): string {
  return POLICY_FIELDS[field]?.label ?? String(field);
}

type AssessmentFinding = {
  id: string; type: string; severity: string; title: string; detail: string; resource: string;
};

/** Match the observed PaaS setting, not a "public" word in arbitrary serialized metadata. */
export function hasExplicitPublicAccess(details: Record<string, unknown>): boolean {
  const settings = [details.public_network_access, details.publicNetworkAccess]
    .filter((value): value is string => typeof value === "string" && !!value.trim());
  return settings.length > 0 && settings.every(value => value.trim().toLowerCase() === "enabled");
}

/** Compare rules on the same supplied observations, never infer a historical cause. */
export function compareAssessment(before: AssessmentFinding[], after: AssessmentFinding[]) {
  const old = new Map(before.map(finding => [finding.id, finding]));
  const next = new Map(after.map(finding => [finding.id, finding]));
  return {
    added: after.filter(finding => !old.has(finding.id)),
    removed: before.filter(finding => !next.has(finding.id)),
    changed: after.filter(finding => {
      const previous = old.get(finding.id);
      return previous && ["type", "severity", "title", "detail", "resource"].some(
        key => previous[key as keyof AssessmentFinding] !== finding[key as keyof AssessmentFinding],
      );
    }),
  };
}

/** Pinned advisory MCSB v1 domains, not v2 preview or cross-framework equivalence. */
export const COMPLIANCE_DOMAINS = [
  { id: "NS", name: "Network security", path: "network-security" },
  { id: "IM", name: "Identity Management", path: "identity-management" },
  { id: "PA", name: "Privileged Access", path: "privileged-access" },
  { id: "DP", name: "Data Protection", path: "data-protection" },
  { id: "AM", name: "Asset Management", path: "asset-management" },
  { id: "LT", name: "Logging and Threat Detection", path: "logging-threat-detection" },
  { id: "IR", name: "Incident Response", path: "incident-response" },
  { id: "PV", name: "Posture and Vulnerability Management", path: "posture-vulnerability-management" },
  { id: "ES", name: "Endpoint Security", path: "endpoint-security" },
  { id: "BR", name: "Backup and Recovery", path: "backup-recovery" },
  { id: "DS", name: "DevOps Security", path: "devops-security" },
  { id: "GS", name: "Governance and Strategy", path: "governance-strategy" },
] as const;

export type ComplianceDomain = typeof COMPLIANCE_DOMAINS[number]["id"];
const LOCAL_DOMAINS: Record<string, ComplianceDomain> = {
  firewall_bypass: "NS", missing_udr: "NS", unapproved_peering: "NS",
  dev_uat_to_prod: "NS", any_any_rule: "NS", public_paas_exposure: "NS",
  missing_private_endpoint: "NS", dns_gap: "NS", missing_owner: "AM", logging_gap: "LT",
};

/** Associate only known local finding types with broad advisory domains. */
export function findingDomain(type: string): ComplianceDomain | undefined {
  return Object.hasOwn(LOCAL_DOMAINS, type) ? LOCAL_DOMAINS[type] : undefined;
}

/** Recognize an exact domain/control identifier, not keyword or cross-framework guesses. */
export function candidateControlDomain(control: string): ComplianceDomain | undefined {
  const match = /^(NS|IM|PA|DP|AM|LT|IR|PV|ES|BR|DS|GS)-[1-9]\d*$/.exec(control.trim().toUpperCase());
  return COMPLIANCE_DOMAINS.find(domain => domain.id === match?.[1])?.id;
}

/** Count distinct loaded observations; zero mapped rows never means a passed domain. */
export function frameworkEvidence(
  findings: AssessmentFinding[], acceptedIds: ReadonlySet<string>, deviations: ComplianceDeviation[],
) {
  const distinctFindings = Array.from(new Map(findings.map(finding => [finding.id, finding])).values());
  const distinctDeviations = Array.from(new Map(deviations.map(row => [`${row.kind}:${row.deviation_id}`, row])).values());
  return {
    domains: COMPLIANCE_DOMAINS.map(domain => {
      const local = distinctFindings.filter(finding => findingDomain(finding.type) === domain.id);
      const governed = distinctDeviations.filter(row => candidateControlDomain(row.control) === domain.id);
      return {
        ...domain, local, governed,
        acceptedCount: local.filter(finding => acceptedIds.has(finding.id)).length,
      };
    }),
    unmapped: distinctDeviations.filter(row => !candidateControlDomain(row.control)),
  };
}
