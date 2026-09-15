"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { RiskGauge } from "@/components/ui/RiskGauge";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useApi } from "@/hooks/useApi";
import { buildComplianceCopilotContext } from "@/lib/copilot/page-adapters";
import { titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { complianceApi, isCanonicalAzureResourceId, networkApi, vulnerabilityApi } from "@/lib/services";
import type { ComplianceDeviation, NetworkGap, NetworkTopology, RuleFinding, VulnerabilityExposure } from "@/lib/types";

type ViolationType =
  | "firewall_bypass"
  | "missing_udr"
  | "unapproved_peering"
  | "dev_uat_to_prod"
  | "any_any_rule"
  | "public_paas_exposure"
  | "missing_private_endpoint"
  | "dns_gap"
  | "missing_owner"
  | "logging_gap";

type Severity = "critical" | "high" | "medium" | "low";

interface DesignPolicy {
  name: string;
  requiredHubRouting: boolean;
  firewallInspectionRequired: boolean;
  environmentIsolationRequired: boolean;
  allowedPorts: string;
  privateEndpointRequiredFor: string;
  requiredDnsZones: string;
  loggingRequired: boolean;
  ownerTag: string;
  allowCrossSubscriptionPeering: boolean;
}

interface PolicyException {
  violationId: string;
  owner: string;
  reason: string;
  expiresAt: string;
}

interface Violation {
  id: string;
  type: ViolationType;
  severity: Severity;
  title: string;
  detail: string;
  resource: string;
  application: string;
  businessService: string;
  owner: string;
  affectedTraffic: string;
  vulnerabilityExposure: string;
  remediation: string;
  evidence: unknown;
}

const POLICY_KEY = "aiops.architecture-policy.v1";
const EXCEPTION_KEY = "aiops.architecture-exceptions.v1";
const COMPLIANCE_REVIEW_TITLE_MAX = 200;
const COMPLIANCE_REVIEW_RECOMMENDATION_MAX = 1_000;

const DEFAULT_POLICY: DesignPolicy = {
  name: "Approved hub-spoke landing-zone baseline",
  requiredHubRouting: true,
  firewallInspectionRequired: true,
  environmentIsolationRequired: true,
  allowedPorts: "443, 1433, 5671",
  privateEndpointRequiredFor: "microsoft.sql, microsoft.storage, microsoft.keyvault, microsoft.web",
  requiredDnsZones: "privatelink.database.windows.net, privatelink.blob.core.windows.net, privatelink.vaultcore.azure.net",
  loggingRequired: true,
  ownerTag: "owner",
  allowCrossSubscriptionPeering: false,
};

function loadPolicy(): DesignPolicy {
  if (typeof window === "undefined") return DEFAULT_POLICY;
  try {
    return { ...DEFAULT_POLICY, ...JSON.parse(window.localStorage.getItem(POLICY_KEY) || "{}") };
  } catch {
    return DEFAULT_POLICY;
  }
}

function loadExceptions(): PolicyException[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(EXCEPTION_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function includesAny(text: string, terms: string[]): boolean {
  const lower = text.toLowerCase();
  return terms.some((term) => lower.includes(term));
}

function asCsv(value: string): string[] {
  return value.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean);
}

function severityWeight(severity: Severity): number {
  if (severity === "critical") return 22;
  if (severity === "high") return 14;
  if (severity === "medium") return 8;
  return 3;
}

function violationTypeFromGap(gap: NetworkGap): ViolationType {
  const text = `${gap.category} ${gap.title} ${gap.detail} ${gap.recommendation}`.toLowerCase();
  if (includesAny(text, ["bypass", "inspection"])) return "firewall_bypass";
  if (includesAny(text, ["udr", "route"])) return "missing_udr";
  if (includesAny(text, ["peering", "peer"])) return "unapproved_peering";
  if (includesAny(text, ["private endpoint", "private access"])) return "missing_private_endpoint";
  if (includesAny(text, ["dns", "zone"])) return "dns_gap";
  return "firewall_bypass";
}

function fromGap(gap: NetworkGap): Violation {
  const type = violationTypeFromGap(gap);
  return {
    id: gap.gap_id,
    type,
    severity: gap.severity,
    title: gap.title,
    detail: gap.detail,
    resource: gap.resource_id || gap.resource_name,
    application: "",
    businessService: "",
    owner: "Unassigned",
    affectedTraffic: gap.basis,
    vulnerabilityExposure: "Not directly linked",
    remediation: gap.recommendation || remediationFor(type),
    evidence: gap,
  };
}

function fromRule(finding: RuleFinding, allowedPorts: string[]): Violation {
  const text = `${finding.category} ${finding.title} ${finding.detail} ${finding.rule_name} ${JSON.stringify(finding.evidence)}`.toLowerCase();
  const anyAny = includesAny(text, ["any-any", "any to any", "0.0.0.0/0", "internet", "*"]);
  const unapprovedPort = allowedPorts.length > 0 && /\b(\d{2,5})\b/.test(text) && !allowedPorts.some((port) => text.includes(port));
  const type: ViolationType = anyAny ? "any_any_rule" : unapprovedPort ? "dev_uat_to_prod" : "firewall_bypass";
  return {
    id: finding.finding_id,
    type,
    severity: anyAny ? "critical" : finding.severity,
    title: finding.title,
    detail: finding.detail,
    resource: finding.rule_id,
    application: "",
    businessService: "",
    owner: "Unassigned",
    affectedTraffic: finding.rule_name,
    vulnerabilityExposure: "Not directly linked",
    remediation: finding.recommendation || remediationFor(type),
    evidence: finding,
  };
}

function fromTopology(topology: NetworkTopology | null, policy: DesignPolicy): Violation[] {
  if (!topology?.resources) return [];
  const requiredPrivate = asCsv(policy.privateEndpointRequiredFor);
  const dnsZones = asCsv(policy.requiredDnsZones);
  return topology.resources.flatMap((resource) => {
    const type = resource.entity_type.toLowerCase();
    const details = JSON.stringify(resource.details ?? {}).toLowerCase();
    const tags = resource.tags ?? {};
    const owner = resource.owner || tags[policy.ownerTag] || tags.owner || "";
    const rows: Violation[] = [];
    if (!owner) {
      rows.push({
        id: `owner-${resource.id}`,
        type: "missing_owner",
        severity: "medium",
        title: "Missing accountable owner",
        detail: `${resource.name} has no mapped owner tag or semantic owner.`,
        resource: resource.id,
        application: resource.application,
        businessService: resource.business_service,
        owner: "Unassigned",
        affectedTraffic: "Ownership and escalation path",
        vulnerabilityExposure: "Unknown until owner mapping is complete",
        remediation: "Map resource ownership in tags or semantic metadata.",
        evidence: resource,
      });
    }
    if (requiredPrivate.some((required) => type.includes(required)) && !details.includes("private")) {
      rows.push({
        id: `pe-${resource.id}`,
        type: "missing_private_endpoint",
        severity: "high",
        title: "Missing private endpoint requirement",
        detail: `${resource.name} matches private-access policy but no private endpoint evidence was observed.`,
        resource: resource.id,
        application: resource.application,
        businessService: resource.business_service,
        owner: owner || "Unassigned",
        affectedTraffic: "PaaS access path",
        vulnerabilityExposure: "May increase exposure surface",
        remediation: "Add private endpoint and disable public network access after validation.",
        evidence: resource,
      });
    }
    if (includesAny(details, ["publicnetworkaccess\":\"enabled", "public_ip", "internetfacing", "public"])) {
      rows.push({
        id: `public-${resource.id}`,
        type: "public_paas_exposure",
        severity: "critical",
        title: "Public PaaS exposure",
        detail: `${resource.name} has public exposure indicators in discovered configuration.`,
        resource: resource.id,
        application: resource.application,
        businessService: resource.business_service,
        owner: owner || "Unassigned",
        affectedTraffic: "Internet to service",
        vulnerabilityExposure: "Correlate with CVE exposure before approving exception",
        remediation: "Disable public access or isolate behind approved private endpoint.",
        evidence: resource,
      });
    }
    if (policy.loggingRequired && !includesAny(details, ["diagnostic", "loganalytics", "workspace", "flowlog"])) {
      rows.push({
        id: `logging-${resource.id}`,
        type: "logging_gap",
        severity: "low",
        title: "Missing logging evidence",
        detail: `${resource.name} has no diagnostic/logging evidence in discovered properties.`,
        resource: resource.id,
        application: resource.application,
        businessService: resource.business_service,
        owner: owner || "Unassigned",
        affectedTraffic: "Operational evidence trail",
        vulnerabilityExposure: "Not directly linked",
        remediation: "Enable diagnostic settings or network flow logging as applicable.",
        evidence: resource,
      });
    }
    if (dnsZones.length > 0 && requiredPrivate.some((required) => type.includes(required)) && !dnsZones.some((zone) => details.includes(zone))) {
      rows.push({
        id: `dns-${resource.id}`,
        type: "dns_gap",
        severity: "medium",
        title: "Private DNS dependency gap",
        detail: `${resource.name} requires private DNS linkage but no approved zone evidence was observed.`,
        resource: resource.id,
        application: resource.application,
        businessService: resource.business_service,
        owner: owner || "Unassigned",
        affectedTraffic: "Private endpoint name resolution",
        vulnerabilityExposure: "Can force fallback to public endpoint",
        remediation: "Link approved private DNS zone and validate resolution.",
        evidence: resource,
      });
    }
    return rows;
  });
}

function fromPeerings(topology: NetworkTopology | null, policy: DesignPolicy): Violation[] {
  if (!topology) return [];
  return topology.links.flatMap((link) => {
    const rows: Violation[] = [];
    if (!policy.allowCrossSubscriptionPeering && link.is_cross_subscription) {
      rows.push({
        id: `peering-${link.local_vnet_id}-${link.remote_vnet_id}`,
        type: "unapproved_peering",
        severity: "high",
        title: "Unapproved cross-subscription peering",
        detail: `${link.local_vnet_id} peers with ${link.remote_vnet_id}.`,
        resource: link.local_vnet_id,
        application: "",
        businessService: "",
        owner: "Network owner",
        affectedTraffic: "Cross-subscription VNet traffic",
        vulnerabilityExposure: "Review reachable CVEs on both sides",
        remediation: "Remove peering or record approved exception with owner and expiry.",
        evidence: link,
      });
    }
    if (!link.allow_forwarded_traffic && policy.firewallInspectionRequired) {
      rows.push({
        id: `inspection-${link.local_vnet_id}-${link.remote_vnet_id}`,
        type: "firewall_bypass",
        severity: "medium",
        title: "Hub inspection path may not be restored",
        detail: "Peering does not allow forwarded traffic while firewall inspection is required.",
        resource: link.local_vnet_id,
        application: "",
        businessService: "",
        owner: "Network owner",
        affectedTraffic: "Spoke to shared service",
        vulnerabilityExposure: "Not directly linked",
        remediation: "Correct peering flags and route through approved hub inspection path.",
        evidence: link,
      });
    }
    return rows;
  });
}

function attachVulnerabilityContext(violations: Violation[], exposures: VulnerabilityExposure[]): Violation[] {
  const exposure = exposures[0];
  if (!exposure) return violations;
  const context = `${exposure.cve_id}: ${exposure.affected_server_count} affected servers, ${exposure.reachable_server_count} reachable`;
  return violations.map((violation) => ({
    ...violation,
    vulnerabilityExposure: violation.vulnerabilityExposure === "Not directly linked"
      ? context
      : `${violation.vulnerabilityExposure}; ${context}`,
  }));
}

function dedupeViolations(violations: Violation[]): Violation[] {
  const seen = new Set<string>();
  return violations.filter((violation) => {
    if (seen.has(violation.id)) return false;
    seen.add(violation.id);
    return true;
  });
}

/** Build the remediation deep link for a violation.
 *
 * The remediation page filters by `resource_key`/`resource` only -- it has no
 * `business_service` filter, so the previous `?business_service=` link was
 * silently ignored (and was usually empty anyway, because gap/rule/peering
 * violations carry no business service). Only send a resource filter when the
 * violation actually names a canonical Azure resource; a rule id or synthetic
 * key would filter the plan list down to nothing.
 */
function remediationHref(violation: Violation): string {
  if (!isCanonicalAzureResourceId(violation.resource)) return "/remediation";

  const params = new URLSearchParams({ resource_key: violation.resource });
  const title = violation.title.trim();
  const recommendation = violation.remediation.trim();
  if (
    title
    && title.length <= COMPLIANCE_REVIEW_TITLE_MAX
    && recommendation
    && recommendation.length <= COMPLIANCE_REVIEW_RECOMMENDATION_MAX
  ) {
    params.set("review_source", "compliance");
    params.set("finding_type", violation.type);
    params.set("finding_severity", violation.severity);
    params.set("finding_title", title);
    params.set("recommendation", recommendation);
  }
  return `/remediation?${params.toString()}`;
}

function remediationFor(type: ViolationType): string {
  const map: Record<ViolationType, string> = {
    firewall_bypass: "Restore approved hub firewall inspection path.",
    missing_udr: "Add or correct UDR to the approved next hop.",
    unapproved_peering: "Remove peering or record an approved exception.",
    dev_uat_to_prod: "Deny DEV/UAT-to-PROD access except approved ports and identities.",
    any_any_rule: "Narrow source, destination, protocol, and port scope.",
    public_paas_exposure: "Disable public access and require private endpoint.",
    missing_private_endpoint: "Add private endpoint and validate DNS.",
    dns_gap: "Link required private DNS zones.",
    missing_owner: "Map accountable owner and support team.",
    logging_gap: "Enable diagnostic logging and retention.",
  };
  return map[type];
}

function isExceptionActive(exception: PolicyException): boolean {
  return Boolean(exception.expiresAt) && Date.parse(exception.expiresAt) > Date.now();
}

function scoreFor(violations: Violation[], exceptions: PolicyException[]): number {
  const accepted = new Set(exceptions.filter(isExceptionActive).map((item) => item.violationId));
  const penalty = violations
    .filter((violation) => !accepted.has(violation.id))
    .reduce((total, violation) => total + severityWeight(violation.severity), 0);
  return Math.max(0, 100 - penalty);
}

export default function CompliancePage() {
  const { scope } = useScope();
  const topology = useApi(() => networkApi.topology(scope), [scope]);
  const gaps = useApi(() => networkApi.gaps(scope), [scope]);
  const findings = useApi(() => networkApi.ruleFindings(scope), [scope]);
  const exposures = useApi(() => vulnerabilityApi.exposures(scope), [scope]);
  const policyDeviations = useApi(() => complianceApi.policyDeviations(scope), [scope]);
  const securityDeviations = useApi(() => complianceApi.securityDeviations(scope), [scope]);
  const drift = useApi(() => complianceApi.configurationDrift(scope), [scope]);
  const summary = useApi(() => complianceApi.summary(scope), [scope]);
  const [policy, setPolicy] = useState<DesignPolicy>(() => loadPolicy());
  const [exceptions, setExceptions] = useState<PolicyException[]>(() => loadExceptions());
  const [selectedId, setSelectedId] = useState("");
  const [exceptionDraft, setExceptionDraft] = useState({ owner: "", reason: "", expiresAt: "" });
  const [copilotOpen, setCopilotOpen] = useState(false);

  const violations = useMemo(() => {
    const allowedPorts = asCsv(policy.allowedPorts);
    const rows = [
      ...(gaps.data?.data.gaps ?? []).map(fromGap),
      ...(findings.data?.data.findings ?? []).map((finding) => fromRule(finding, allowedPorts)),
      ...fromTopology(topology.data?.data.topology ?? null, policy),
      ...fromPeerings(topology.data?.data.topology ?? null, policy),
    ];
    return attachVulnerabilityContext(dedupeViolations(rows), exposures.data?.data ?? []);
  }, [gaps.data, findings.data, topology.data, exposures.data, policy]);
  const selected = violations.find((violation) => violation.id === selectedId) ?? violations[0] ?? null;
  const acceptedIds = new Set(exceptions.filter(isExceptionActive).map((item) => item.violationId));
  const activeViolations = violations.filter((violation) => !acceptedIds.has(violation.id));
  const postureScore = scoreFor(violations, exceptions);
  const loading = topology.loading || gaps.loading || findings.loading || exposures.loading;
  const error = topology.error ?? gaps.error ?? findings.error ?? exposures.error;
  const evidence = [
    ...(topology.data?.evidence ?? []),
    ...(gaps.data?.evidence ?? []),
    ...(findings.data?.evidence ?? []),
    ...(exposures.data?.evidence ?? []),
    ...(policyDeviations.data?.evidence ?? []),
    ...(securityDeviations.data?.evidence ?? []),
    ...(drift.data?.evidence ?? []),
  ];

  const governedDeviations: ComplianceDeviation[] = [
    ...(policyDeviations.data?.data ?? []),
    ...(securityDeviations.data?.data ?? []),
  ];
  const openGovernedDeviations = governedDeviations.filter((row) => row.status?.toLowerCase() !== "resolved");
  const criticalGovernedCount = openGovernedDeviations.filter((row) => row.severity?.toLowerCase() === "critical").length;
  const driftRows = drift.data?.data ?? [];
  const governedLoading = policyDeviations.loading || securityDeviations.loading || drift.loading || summary.loading;
  const governedError = policyDeviations.error ?? securityDeviations.error ?? drift.error ?? summary.error;
  const changeSummary = summary.data?.data.summary;
  const complianceCopilot = buildComplianceCopilotContext({
    scope,
    policyName: policy.name,
    selectedId: selectedId || null,
    violations,
    governedDeviations: openGovernedDeviations,
    evidence,
    sourceEnvelopes: {
      topology: topology.data,
      network_gaps: gaps.data,
      network_rule_findings: findings.data,
      vulnerability_exposure: exposures.data,
      policy_deviations: policyDeviations.data,
      security_deviations: securityDeviations.data,
      configuration_drift: drift.data,
      compliance_summary: summary.data,
    },
  });

  function savePolicy(next: DesignPolicy) {
    setPolicy(next);
    window.localStorage.setItem(POLICY_KEY, JSON.stringify(next));
  }

  function acceptRisk() {
    if (!selected || !exceptionDraft.owner.trim() || !exceptionDraft.reason.trim() || !exceptionDraft.expiresAt) return;
    const next = [
      { violationId: selected.id, owner: exceptionDraft.owner.trim(), reason: exceptionDraft.reason.trim(), expiresAt: exceptionDraft.expiresAt },
      ...exceptions.filter((item) => item.violationId !== selected.id),
    ];
    setExceptions(next);
    window.localStorage.setItem(EXCEPTION_KEY, JSON.stringify(next));
    setExceptionDraft({ owner: "", reason: "", expiresAt: "" });
  }

  return (
    <div className="page-container compliance-workspace">
      <PageHeader
        eyebrow="Architecture compliance"
        title="Which controls are out of alignment?"
        description="Compare discovered Azure architecture with the active policy pack, then inspect each finding, owner, exception, and source evidence."
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about posture" />}
        metadata={<><span>{policy.name}</span><span>{violations.length} evaluated violations</span><span>{exceptions.filter(isExceptionActive).length} active exceptions</span></>}
      />

      <EvidenceBar evidence={evidence} knowledgeVersion={topology.data?.knowledge_version} warnings={[...(topology.data?.warnings ?? []), ...(gaps.data?.warnings ?? []), ...(findings.data?.warnings ?? []), ...(exposures.data?.warnings ?? []), ...(policyDeviations.data?.warnings ?? []), ...(securityDeviations.data?.warnings ?? [])]} />

      <div className="predeploy-summary">
        <section className="card">
          <div className="card-header">
            <h2>Posture score</h2>
          </div>
          <div className="card-body risk-gauge-body">
            <RiskGauge score={postureScore} invert detail="Accepted exceptions excluded from active penalty" />
          </div>
        </section>
        <section className="metric-grid compliance-metrics">
          <MetricCard label="Active violations" value={activeViolations.length} detail={`${violations.length - activeViolations.length} accepted by governed exception`} tone={activeViolations.length ? "warning" : "success"} />
          <MetricCard label="Critical findings" value={activeViolations.filter((item) => item.severity === "critical").length} detail="Includes public exposure and any-any rules" tone={activeViolations.some((item) => item.severity === "critical") ? "critical" : "success"} />
          <MetricCard label="Open governed deviations" value={openGovernedDeviations.length} detail={changeSummary ? `${changeSummary.drifted_resource_count} drifted resources tracked by change intelligence` : "Policy and security baseline deviations"} tone={criticalGovernedCount ? "critical" : openGovernedDeviations.length ? "warning" : "success"} />
        </section>
      </div>

      {error ? <StatePanel title="Compliance evaluation unavailable" message={error.message} tone="error" /> : null}
      {loading ? <StatePanel title="Evaluating architecture posture" message="Comparing discovered subscriptions, VNets, routes, peerings, rules, private endpoints, and shared services to policy." tone="loading" /> : null}


      <div className="compliance-layout">
        <section className="card">
          <div className="card-header">
            <div><h2>Violations</h2><p>Business-context posture findings with evidence, remediation, and exception state.</p></div>
          </div>
          <div className="compliance-list">
            {violations.map((violation) => (
              <button type="button" key={violation.id} className={`compliance-row ${selected?.id === violation.id ? "compliance-row-selected" : ""}`} onClick={() => setSelectedId(violation.id)}>
                <StatusBadge label={violation.severity} tone={statusTone(violation.severity)} compact />
                <div>
                  <strong>{violation.title}</strong>
                  <span>{titleize(violation.type)} - {violation.businessService || violation.resource || "business context pending"}</span>
                </div>
                {acceptedIds.has(violation.id) ? <StatusBadge label="Accepted risk" tone="warning" compact /> : <StatusBadge label="Open" tone="critical" compact />}
              </button>
            ))}
            {violations.length === 0 && !loading ? <StatePanel title="No policy violations" message="Current discovered architecture satisfies the active policy pack." /> : null}
          </div>
        </section>

        <aside className="card">
          <div className="card-header">
            <div><h2>Violation context</h2><p>Owner, affected traffic, CVE exposure, evidence, and remediation candidate.</p></div>
          </div>
          <div className="card-body compliance-detail">
            {selected ? (
              <>
                <h3>{selected.title}</h3>
                <p>{selected.detail}</p>
                <dl className="compliance-fact-list">
                  <dt>Application</dt><dd>{selected.application || "Not mapped"}</dd>
                  <dt>Business service</dt><dd>{selected.businessService || "Not mapped"}</dd>
                  <dt>Owner</dt><dd>{selected.owner}</dd>
                  <dt>Affected traffic</dt><dd>{selected.affectedTraffic}</dd>
                  <dt>Vulnerability exposure</dt><dd>{selected.vulnerabilityExposure}</dd>
                  <dt>Remediation candidate</dt><dd>{selected.remediation}</dd>
                </dl>
                <Link className="button button-primary" href={remediationHref(selected)}>Open remediation</Link>
                <details>
                  <summary>Evidence</summary>
                  <StructuredData value={selected.evidence} />
                </details>
              </>
            ) : <StatePanel title="No violation selected" message="Select a violation to review evidence and remediation." />}
          </div>
        </aside>
      </div>

      <div className="compliance-layout">
        <section className="card">
          <div className="card-header">
            <div><h2>Governed compliance deviations</h2><p>Policy and security baseline deviations from change intelligence, backed by evidence-linked ontology entities rather than keyword inference.</p></div>
          </div>
          {governedError ? <StatePanel title="Governed deviations unavailable" message={governedError.message} tone="error" /> : null}
          {governedLoading ? <StatePanel title="Loading change intelligence posture" message="Fetching policy deviations, security deviations, and configuration drift." tone="loading" /> : null}
          <div className="compliance-list">
            {openGovernedDeviations.map((row) => (
              <div key={row.deviation_id} className="compliance-row">
                <StatusBadge label={row.severity} tone={statusTone(row.severity)} compact />
                <div>
                  <strong>{titleize(row.kind)} - {row.control}</strong>
                  <span>{row.business_service || row.application || row.resource || "business context pending"}</span>
                </div>
                <StatusBadge label={row.status} tone={row.status?.toLowerCase() === "open" ? "critical" : "warning"} compact />
              </div>
            ))}
            {openGovernedDeviations.length === 0 && !governedLoading ? <StatePanel title="No open governed deviations" message="Change intelligence reports no open policy or security baseline deviations for this scope." /> : null}
          </div>
        </section>

        <aside className="card">
          <div className="card-header">
            <div><h2>Configuration drift</h2><p>Resources whose observed configuration no longer matches the expected baseline.</p></div>
          </div>
          <div className="card-body compliance-detail">
            {driftRows.length > 0 ? (
              <StructuredData value={driftRows} />
            ) : (
              <StatePanel title={drift.loading ? "Loading drift data" : "No configuration drift"} message={drift.loading ? "Evaluating configuration drift." : "All tracked resources match their expected configuration."} tone={drift.loading ? "loading" : undefined} />
            )}
          </div>
        </aside>
      </div>

      <div className="compliance-layout">
        <section className="card">
          <div className="card-header">
            <div><h2>Policy administration</h2><p>Governed customer-specific policy pack for architecture compliance.</p></div>
            <StatusBadge label="Customer governed" tone="warning" />
          </div>
          <div className="card-body compliance-policy-grid">
            <label>Policy pack name<input value={policy.name} onChange={(event) => savePolicy({ ...policy, name: event.target.value })} /></label>
            <label>Allowed ports<input value={policy.allowedPorts} onChange={(event) => savePolicy({ ...policy, allowedPorts: event.target.value })} /></label>
            <label>Private endpoint required for<input value={policy.privateEndpointRequiredFor} onChange={(event) => savePolicy({ ...policy, privateEndpointRequiredFor: event.target.value })} /></label>
            <label>Required DNS zones<input value={policy.requiredDnsZones} onChange={(event) => savePolicy({ ...policy, requiredDnsZones: event.target.value })} /></label>
            <label>Owner tag<input value={policy.ownerTag} onChange={(event) => savePolicy({ ...policy, ownerTag: event.target.value })} /></label>
            <label><input type="checkbox" checked={policy.requiredHubRouting} onChange={(event) => savePolicy({ ...policy, requiredHubRouting: event.target.checked })} /> Required hub routing</label>
            <label><input type="checkbox" checked={policy.firewallInspectionRequired} onChange={(event) => savePolicy({ ...policy, firewallInspectionRequired: event.target.checked })} /> Firewall inspection required</label>
            <label><input type="checkbox" checked={policy.environmentIsolationRequired} onChange={(event) => savePolicy({ ...policy, environmentIsolationRequired: event.target.checked })} /> Environment isolation required</label>
            <label><input type="checkbox" checked={policy.loggingRequired} onChange={(event) => savePolicy({ ...policy, loggingRequired: event.target.checked })} /> Logging required</label>
            <label><input type="checkbox" checked={policy.allowCrossSubscriptionPeering} onChange={(event) => savePolicy({ ...policy, allowCrossSubscriptionPeering: event.target.checked })} /> Allow cross-subscription peering</label>
          </div>
        </section>

        <aside className="card">
          <div className="card-header">
            <div><h2>Exceptions and risk acceptance</h2><p>Approve temporary exceptions with owner, reason, and expiry.</p></div>
          </div>
          <div className="card-body compliance-policy-grid">
            <label>Exception owner<input value={exceptionDraft.owner} onChange={(event) => setExceptionDraft({ ...exceptionDraft, owner: event.target.value })} /></label>
            <label>Risk acceptance reason<textarea rows={3} value={exceptionDraft.reason} onChange={(event) => setExceptionDraft({ ...exceptionDraft, reason: event.target.value })} /></label>
            <label>Expires at<input type="date" value={exceptionDraft.expiresAt} onChange={(event) => setExceptionDraft({ ...exceptionDraft, expiresAt: event.target.value })} /></label>
            <button type="button" className="button button-primary" disabled={!selected} onClick={acceptRisk}>Accept selected risk</button>
            <StructuredData value={exceptions} />
          </div>
        </aside>
      </div>

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Security posture"
        requestedScope={complianceCopilot.requestedScope}
        snapshot={complianceCopilot.snapshot}
        starterQuestions={complianceCopilot.starterQuestions}
      />
    </div>
  );
}
