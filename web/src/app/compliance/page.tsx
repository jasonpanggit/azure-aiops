"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { CountBarChart } from "@/components/ui/CountBarChart";
import { DonutChart } from "@/components/ui/DonutChart";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { RiskGauge } from "@/components/ui/RiskGauge";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone, toneColor } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useApi } from "@/hooks/useApi";
import { buildComplianceCopilotContext } from "@/lib/copilot/page-adapters";
import { titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { complianceApi, isCanonicalAzureResourceId, networkApi, vulnerabilityApi } from "@/lib/services";
import type { ComplianceDesignPolicy, CompliancePolicyState, ComplianceDeviation, NetworkGap, NetworkTopology, RuleFinding, VulnerabilityExposure } from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";
import { compareAssessment, explainPolicyChanges, findingDomain, frameworkEvidence, hasExplicitPublicAccess, policyFieldLabel } from "@/lib/compliance-explanation";

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

type DesignPolicy = ComplianceDesignPolicy;
type PolicyException = CompliancePolicyState["exceptions"][number];

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
    if (hasExplicitPublicAccess(resource.details ?? {})) {
      rows.push({
        id: `public-${resource.id}`,
        type: "public_paas_exposure",
        severity: "critical",
        title: "Public PaaS exposure",
        detail: `${resource.name} reports public network access explicitly enabled. This setting alone does not establish internet reachability.`,
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
  const context = `Scope-level context, not a resource link: ${exposure.cve_id}: ${exposure.affected_server_count} affected servers, ${exposure.reachable_server_count} reachable`;
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
  return exception.active && !exception.revoked_at && Date.parse(exception.expiresAt) > Date.now();
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
  return <ComplianceWorkspace key={JSON.stringify(scope)} />;
}

function ComplianceWorkspace() {
  const { scope } = useScope();
  const policyRead = useApi(() => complianceApi.designPolicy(scope), [scope]);
  const [policyState, setPolicyState] = useState<CompliancePolicyState | null>(null);
  const [policyDraft, setPolicyDraft] = useState<DesignPolicy>(DEFAULT_POLICY);
  const [policyReason, setPolicyReason] = useState("");
  const [policyBusy, setPolicyBusy] = useState(false);
  const [policyError, setPolicyError] = useState("");
  const [policyNotice, setPolicyNotice] = useState("");
  const latestPolicyRevision = useRef(-1);
  const [, setExpiryTick] = useState(0);
  useEffect(() => {
    const nextExpiry = policyState?.exceptions
      .filter(item => item.active && !item.revoked_at)
      .map(item => Date.parse(item.expiresAt))
      .filter(at => at > Date.now())
      .sort((a, b) => a - b)[0];
    if (!nextExpiry) return;
    const timer = setTimeout(() => setExpiryTick(tick => tick + 1), Math.min(nextExpiry - Date.now() + 1, 2_147_483_647));
    return () => clearTimeout(timer);
  });
  useEffect(() => {
    if (policyRead.data) {
      if (policyRead.data.data.revision < latestPolicyRevision.current) return;
      latestPolicyRevision.current = policyRead.data.data.revision;
      setPolicyState(policyRead.data.data);
      setPolicyDraft(policyRead.data.data.policy);
    }
  }, [policyRead.data]);
  const topology = useApi(() => networkApi.topology(scope), [scope]);
  const gaps = useApi(() => networkApi.gaps(scope), [scope]);
  const findings = useApi(() => networkApi.ruleFindings(scope), [scope]);
  const exposures = useApi(() => vulnerabilityApi.exposures(scope), [scope]);
  const policyDeviations = useApi(() => complianceApi.policyDeviations(scope), [scope]);
  const securityDeviations = useApi(() => complianceApi.securityDeviations(scope), [scope]);
  const drift = useApi(() => complianceApi.configurationDrift(scope), [scope]);
  const summary = useApi(() => complianceApi.summary(scope), [scope]);
  const policy = policyState?.policy ?? DEFAULT_POLICY;
  const exceptions = policyState?.exceptions ?? [];
  const [selectedId, setSelectedId] = useState("");
  const [exceptionDraft, setExceptionDraft] = useState({ owner: "", reason: "", expiresAt: "" });
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [domainFilter, setDomainFilter] = useState("all");

  function evaluatePolicy(candidate: DesignPolicy): Violation[] {
    if (!policyState) return [];
    const allowedPorts = asCsv(candidate.allowedPorts);
    const rows = [
      ...(gaps.data?.data.gaps ?? []).map(fromGap),
      ...(findings.data?.data.findings ?? []).map((finding) => fromRule(finding, allowedPorts)),
      ...fromTopology(topology.data?.data.topology ?? null, candidate),
      ...fromPeerings(topology.data?.data.topology ?? null, candidate),
    ];
    return attachVulnerabilityContext(dedupeViolations(rows), exposures.data?.data ?? []);
  }
  const violations = evaluatePolicy(policy);
  const visibleViolations = domainFilter === "all" ? violations : violations.filter(row => findingDomain(row.type) === domainFilter);
  const selected = visibleViolations.find((violation) => violation.id === selectedId) ?? visibleViolations[0] ?? null;
  const acceptedIds = new Set(exceptions.filter(isExceptionActive).map((item) => item.violationId));
  const activeViolations = violations.filter((violation) => !acceptedIds.has(violation.id));
  const postureScore = scoreFor(violations, exceptions);
  const severityBreakdown = useMemo(() => {
    const order: Severity[] = ["critical", "high", "medium", "low"];
    const counts = new Map<Severity, number>();
    for (const violation of activeViolations) {
      counts.set(violation.severity, (counts.get(violation.severity) ?? 0) + 1);
    }
    return order
      .filter((key) => (counts.get(key) ?? 0) > 0)
      .map((key) => ({
        label: key.charAt(0).toUpperCase() + key.slice(1),
        value: counts.get(key) ?? 0,
        color: toneColor(statusTone(key)),
      }));
  }, [activeViolations]);
  const violationsByType = useMemo(() => {
    const counts = new Map<string, number>();
    for (const violation of activeViolations) {
      counts.set(violation.type, (counts.get(violation.type) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([type, value]) => ({ id: type, label: titleize(type), value }));
  }, [activeViolations]);
  const loading = topology.loading || gaps.loading || findings.loading || exposures.loading;
  const error = topology.error ?? gaps.error ?? findings.error ?? exposures.error;
  const assessmentReady = Boolean(policyState) && !policyRead.loading && !policyRead.error && !loading && !error;
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
  const draftChanges = policyState ? explainPolicyChanges(policy, policyDraft) : [];
  const draftViolations = evaluatePolicy(policyDraft);
  const draftImpact = compareAssessment(violations, draftViolations);
  const framework = frameworkEvidence(
    assessmentReady ? violations : [], acceptedIds, [
      ...(!policyDeviations.error ? policyDeviations.data?.data ?? [] : []),
      ...(!securityDeviations.error ? securityDeviations.data?.data ?? [] : []),
    ],
  );
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
    setPolicyDraft(next);
    setPolicyNotice("");
  }

  async function persistPolicy() {
    if (!policyState || policyBusy) return;
    setPolicyBusy(true);
    setPolicyError("");
    setPolicyNotice("");
    try {
      const result = await complianceApi.saveDesignPolicy(policyState.revision, policyDraft, policyReason.trim(), scope);
      if (result.data.revision < latestPolicyRevision.current) {
        setPolicyError("A newer policy revision was already loaded. Reload the saved policy before deciding.");
        return;
      }
      latestPolicyRevision.current = result.data.revision;
      setPolicyState(result.data);
      setPolicyDraft(result.data.policy);
      setPolicyReason("");
      setPolicyNotice("Policy saved. Previous exceptions require review against this policy revision.");
    } catch (error) {
      setPolicyError(error instanceof Error ? error.message : "Policy could not be saved.");
    } finally { setPolicyBusy(false); }
  }

  async function acceptRisk(action: "accept" | "revoke" = "accept") {
    if (!selected || !policyState || policyBusy) return;
    const expiry = Date.parse(`${exceptionDraft.expiresAt}T00:00:00Z`);
    if (!exceptionDraft.owner.trim() || !exceptionDraft.reason.trim() || (action === "accept" && (!Number.isFinite(expiry) || expiry <= Date.now()))) {
      setPolicyError("Provide an owner, reason, and future expiry for acceptance.");
      return;
    }
    setPolicyBusy(true);
    setPolicyError("");
    setPolicyNotice("");
    try {
      const result = await complianceApi.decideException({
        expected_revision: policyState.revision, action, violationId: selected.id,
        owner: exceptionDraft.owner.trim(), reason: exceptionDraft.reason.trim(),
        expiresAt: action === "accept" ? `${exceptionDraft.expiresAt}T00:00:00Z` : "",
      }, scope);
      if (result.data.revision < latestPolicyRevision.current) {
        setPolicyError("A newer policy decision was already loaded. Reload the saved policy before deciding.");
        return;
      }
      latestPolicyRevision.current = result.data.revision;
      setPolicyState(result.data);
      setExceptionDraft({ owner: "", reason: "", expiresAt: "" });
      setPolicyNotice(action === "accept" ? "Risk acceptance recorded by the authenticated approver." : "Risk acceptance revoked.");
    } catch (error) {
      setPolicyError(error instanceof Error ? error.message : "Risk decision could not be saved.");
    } finally { setPolicyBusy(false); }
  }

  return (
    <div className="page-container compliance-workspace">
      <PageHeader
        eyebrow="Architecture compliance"
        title="Which controls are out of alignment?"
        description="Compare discovered Azure architecture with the active policy pack, then inspect each finding, owner, exception, and source evidence."
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about posture" />}
        metadata={<><span>{policyState ? policy.name : "Assessment policy unavailable"}</span><span>{assessmentReady ? `${violations.length} evaluated violations` : "Assessment incomplete"}</span><span>{policyState ? `${exceptions.filter(isExceptionActive).length} active exceptions` : "Exceptions unavailable"}</span></>}
      />

      <CopilotInsights
        snapshot={complianceCopilot.snapshot}
        ready={assessmentReady}
        requestedScope={complianceCopilot.requestedScope}
        contextLabel="Security posture"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      <EvidenceBar evidence={evidence} knowledgeVersion={topology.data?.knowledge_version} warnings={[...(topology.data?.warnings ?? []), ...(gaps.data?.warnings ?? []), ...(findings.data?.warnings ?? []), ...(exposures.data?.warnings ?? []), ...(policyDeviations.data?.warnings ?? []), ...(securityDeviations.data?.warnings ?? [])]} />
      <p className="muted">Architecture assessment policy is stored for this exact scope. Browser-local policies and exceptions are not imported as approvals. These decisions never authorize remediation or change Azure policy.</p>
      {policyRead.loading ? <StatePanel title="Loading governed assessment policy" message="Reading durable policy and exception decisions." tone="loading" /> : null}
      {policyRead.error ? <StatePanel title="Governed assessment policy unavailable" message={`${policyRead.error.message}. No saved exceptions or healthy posture score are asserted.`} tone="error" /> : null}
      {policyError ? <StatePanel title="Policy decision was not saved" message={policyError} tone="error" /> : null}
      {policyNotice ? <p role="status">{policyNotice}</p> : null}

      <div className="predeploy-summary">
        <section className="card">
          <div className="card-header">
            <h2>Posture score</h2>
          </div>
          <div className="card-body risk-gauge-body">
            {assessmentReady ? <RiskGauge score={postureScore} invert detail="Accepted exceptions excluded from active penalty" /> : <p>Posture score unavailable until policy and evidence load.</p>}
          </div>
        </section>
        <section className="metric-grid compliance-metrics">
          <MetricCard label="Active violations" value={assessmentReady ? activeViolations.length : "—"} detail={assessmentReady ? `${violations.length - activeViolations.length} accepted by governed exception` : "Policy and evidence must load before assessment"} tone={!assessmentReady ? "default" : activeViolations.length ? "warning" : "success"} />
          <MetricCard label="Critical findings" value={assessmentReady ? activeViolations.filter((item) => item.severity === "critical").length : "—"} detail="Includes public exposure and any-any rules" tone={!assessmentReady ? "default" : activeViolations.some((item) => item.severity === "critical") ? "critical" : "success"} />
          <MetricCard label="Open governed deviations" value={governedLoading || governedError ? "—" : openGovernedDeviations.length} detail={governedLoading || governedError ? "Governed evidence incomplete" : changeSummary ? `${changeSummary.drifted_resource_count} drifted resources tracked by change intelligence; deviations count loaded pages` : "Policy/security deviations in loaded pages, not global totals"} tone={governedLoading || governedError ? "default" : criticalGovernedCount ? "critical" : openGovernedDeviations.length ? "warning" : "success"} />
        </section>
      </div>

      {assessmentReady && activeViolations.length > 0 && (
        <div className="card dashboard-charts-row">
          <div className="chart-card">
            <h3 className="chart-card-title">Severity mix (active violations)</h3>
            <DonutChart
              segments={severityBreakdown}
              centerValue={activeViolations.length}
              centerLabel="active"
            />
          </div>
          <div className="chart-card">
            <h3 className="chart-card-title">Violations by rule type</h3>
            <CountBarChart data={violationsByType} unit="rule type" />
          </div>
        </div>
      )}

      {error ? <StatePanel title="Compliance evaluation unavailable" message={error.message} tone="error" /> : null}
      {loading ? <StatePanel title="Evaluating architecture posture" message="Comparing discovered subscriptions, VNets, routes, peerings, rules, private endpoints, and shared services to policy." tone="loading" /> : null}


      <section className="card" aria-label="Framework evidence coverage">
        <div className="card-header"><div><h2>Framework evidence coverage</h2>
          <p>Advisory MCSB v1 domain associations, not a control audit, regulatory certification, or pass percentage.</p></div></div>
        <div className="card-body">
          <p>Local heuristic types map only to broad domains. Exact provider control-ID formats are candidate associations, not verified benchmark evaluations.
            {" "}Accepted risk remains observed evidence; it never makes a domain pass. Domains without mapped evidence are not assessed.</p>
          <p className="muted">Counts describe loaded observations only. Policy deviations: {policyDeviations.error ? "unavailable" : policyDeviations.loading ? "loading" : `${policyDeviations.data?.data.length ?? 0} loaded / ${policyDeviations.data?.pagination?.total ?? "unreported"} reported`}.
            {" "}Security deviations: {securityDeviations.error ? "unavailable" : securityDeviations.loading ? "loading" : `${securityDeviations.data?.data.length ?? 0} loaded / ${securityDeviations.data?.pagination?.total ?? "unreported"} reported`}.
            {" "}Local assessment: {assessmentReady ? "loaded evidence only; topology may be bounded" : "incomplete; counts withheld"}.</p>
          <a href="https://learn.microsoft.com/en-us/security/benchmark/azure/overview-mcsb-v1" target="_blank" rel="noreferrer">MCSB v1 catalog and mapping limitations</a>
          <div className="data-table-wrap"><table className="data-table">
            <caption>Partial domain mapping of loaded findings; zero does not mean compliant</caption>
            <thead><tr><th>Domain</th><th>Local findings</th><th>Accepted</th><th>Provider deviations</th><th>Evidence state</th></tr></thead>
            <tbody>{framework.domains.map(domain => <tr key={domain.id}>
              <td><a href={`https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-${domain.path}`} target="_blank" rel="noreferrer">{domain.id} · {domain.name}</a></td>
              <td>{assessmentReady ? domain.local.length : "—"}{domain.local.length > 0 && <>{" "}<a href="#compliance-findings" onClick={() => { setDomainFilter(domain.id); setSelectedId(domain.local[0].id); }}>Review {domain.id} findings</a></>}</td>
              <td>{assessmentReady ? domain.acceptedCount : "—"}</td>
              <td>{policyDeviations.error && securityDeviations.error ? "Unavailable" : policyDeviations.loading || securityDeviations.loading || policyDeviations.error || securityDeviations.error ? `${domain.governed.length} loaded; incomplete` : domain.governed.length}</td>
              <td>{domain.local.length + domain.governed.length > 0 ? "Advisory mapped evidence" : !assessmentReady || !policyDeviations.data || !securityDeviations.data || policyDeviations.error || securityDeviations.error ? "Evidence incomplete" : "Not assessed"}</td>
            </tr>)}</tbody>
          </table></div>
          <details><summary>Unmapped provider controls ({framework.unmapped.length})</summary>
            <p>Labels without a supported exact domain/control identifier are not guessed into a framework.</p>
            {framework.unmapped.length ? <StructuredData value={framework.unmapped} /> : <p>No unmapped controls in the currently loaded rows. Missing or unqueried pages remain unknown.</p>}
          </details>
          <details><summary>Mapped provider evidence references</summary>
            <StructuredData value={framework.domains.filter(domain => domain.governed.length).map(domain => ({ domain: domain.id, candidate_control_evidence: domain.governed }))} />
          </details>
        </div>
      </section>

      <section className="card compliance-violations-panel" id="compliance-findings">
        <div className="card-header">
          <div><h2>Violations</h2><p>Business-context posture findings with evidence, remediation, and exception state. Select a violation to expand its details inline.</p></div>
        </div>
        <label className="card-body compliance-domain-filter">Local finding domain
          <select aria-label="Local finding domain" value={domainFilter} onChange={event => setDomainFilter(event.target.value)}>
            <option value="all">All local domains</option>
            {framework.domains.map(domain => <option value={domain.id} key={domain.id}>{domain.id} · {domain.name}</option>)}
          </select>
        </label>
        <div className="compliance-list">
          {visibleViolations.length > 0 ? (
            <div className="compliance-list-header" aria-hidden="true">
              <span>Severity</span>
              <span>Finding</span>
              <span>Status</span>
            </div>
          ) : null}
          {visibleViolations.map((violation) => {
            const isSelected = selected?.id === violation.id;
            return (
              <div key={violation.id} className="compliance-row-group">
                <button
                  type="button"
                  className={`compliance-row ${isSelected ? "compliance-row-selected" : ""}`}
                  aria-expanded={isSelected}
                  onClick={() => setSelectedId(violation.id)}
                >
                  <StatusBadge label={violation.severity} tone={statusTone(violation.severity)} compact />
                  <div>
                    <strong>{violation.title}</strong>
                    <span>{titleize(violation.type)} - {violation.businessService || violation.resource || "business context pending"}</span>
                  </div>
                  {acceptedIds.has(violation.id) ? <StatusBadge label="Accepted risk" tone="warning" compact /> : <StatusBadge label="Open" tone="critical" compact />}
                </button>
                {isSelected ? (
                  <div className="card-body compliance-detail compliance-detail-inline">
                    <p>{violation.detail}</p>
                    <dl className="compliance-fact-list">
                      <dt>Application</dt><dd>{violation.application || "Not mapped"}</dd>
                      <dt>Business service</dt><dd>{violation.businessService || "Not mapped"}</dd>
                      <dt>Owner</dt><dd>{violation.owner}</dd>
                      <dt>Affected traffic</dt><dd>{violation.affectedTraffic}</dd>
                      <dt>Vulnerability exposure</dt><dd>{violation.vulnerabilityExposure}</dd>
                      <dt>Remediation candidate</dt><dd>{violation.remediation}</dd>
                    </dl>
                    <Link className="button button-primary" href={remediationHref(violation)}>Open remediation</Link>
                    <details>
                      <summary>Evidence</summary>
                      <StructuredData value={violation.evidence} />
                    </details>
                  </div>
                ) : null}
              </div>
            );
          })}
          {visibleViolations.length === 0 && assessmentReady ? <StatePanel title="No findings in loaded evidence" message="No local heuristic findings match this domain and policy in the loaded observations. This is not a complete control audit or compliance certification." /> : null}
        </div>
      </section>

      <div className="compliance-layout">
        <section className="card">
          <div className="card-header">
            <div><h2>Governed compliance deviations</h2><p>Policy and security baseline deviations from change intelligence, backed by evidence-linked ontology entities rather than keyword inference.</p></div>
          </div>
          {governedError ? <StatePanel title="Governed deviations unavailable" message={governedError.message} tone="error" /> : null}
          {governedLoading ? <StatePanel title="Loading change intelligence posture" message="Fetching policy deviations, security deviations, and configuration drift." tone="loading" /> : null}
          <div className="compliance-list">
            {openGovernedDeviations.length > 0 ? (
              <div className="compliance-list-header" aria-hidden="true">
                <span>Severity</span>
                <span>Deviation</span>
                <span>Status</span>
              </div>
            ) : null}
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
            {openGovernedDeviations.length === 0 && !governedLoading && !governedError ? <StatePanel title="No open governed deviations in loaded pages" message="No open policy or security baseline deviations are present in the loaded rows. Unqueried pages are not assessed." /> : null}
          </div>
        </section>

        <aside className="card">
          <div className="card-header">
            <div><h2>Configuration drift</h2><p>Resources whose observed configuration no longer matches the expected baseline.</p></div>
          </div>
          <div className="card-body compliance-detail">
            {driftRows.length > 0 ? (
              <StructuredData value={driftRows} />
            ) : drift.error ? <StatePanel title="Configuration drift unavailable" message={drift.error.message} tone="error" /> : (
              <StatePanel title={drift.loading ? "Loading drift data" : "No drift rows in loaded evidence"} message={drift.loading ? "Evaluating configuration drift." : "No drift rows were returned in this page; absent rows do not establish complete baseline conformance."} tone={drift.loading ? "loading" : undefined} />
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
          <section className="card-body compliance-policy-explanation" aria-label="Policy change explanation">
            <h3>Policy change explanation</h3>
            {policyState ? <>
              <p>Saved policy revision {policyState.policy_revision}, decision revision {policyState.revision}. The draft changes {draftChanges.length} field{draftChanges.length === 1 ? "" : "s"}.
                {" "}Preview compares both policies against the same currently loaded observations, not historical evidence or an inferred root cause.</p>
              {policyState.policy_revision === 0 && !draftChanges.length && <p>Saving applies the displayed default assessment policy as its first explicit policy revision.</p>}
              {draftChanges.length > 0 && <div className="data-table-wrap"><table className="data-table">
                <caption>Draft field differences; not yet saved</caption>
                <thead><tr><th>Field</th><th>Saved</th><th>Draft</th><th>Actual evaluation boundary</th></tr></thead>
                <tbody>{draftChanges.map(change => <tr key={change.field}>
                  <th scope="row">{change.label}</th><td>{String(change.before)}</td><td>{String(change.after)}</td><td>{change.effect}</td>
                </tr>)}</tbody>
              </table></div>}
              <p>{exceptions.filter(isExceptionActive).length} currently active exceptions would require review after a policy save, including metadata-only changes.</p>
              {assessmentReady ? <>
                <p>Same-evidence preview: {draftImpact.added.length} added, {draftImpact.removed.length} removed, {draftImpact.changed.length} reclassified local findings.
                  {" "}Current heuristic score {postureScore}; projected score {scoreFor(draftViolations, [])} after invalidating prior exceptions. These scores are not benchmark coverage.</p>
                <details><summary>Inspect draft finding changes</summary>
                  <ul>{[
                    ...draftImpact.added.map(row => ({ action: "Added", row })),
                    ...draftImpact.removed.map(row => ({ action: "Removed", row })),
                    ...draftImpact.changed.map(row => ({ action: "Reclassified", row })),
                  ].slice(0, 50).map(({ action, row }) => <li key={`${action}:${row.id}`}>{action}: {row.title} · {row.resource} · {row.severity}</li>)}</ul>
                  <p>Showing up to 50 changes in loaded observations. Draft findings are advisory and are not remediation approvals.</p>
                </details>
              </> : <p>Impact preview unavailable until the assessment policy and evidence finish loading successfully.</p>}
            </> : <p>Saved policy unavailable; no policy difference or impact is asserted.</p>}
          </section>
          <fieldset className="card-body compliance-policy-grid" disabled={!policyState || policyBusy}>
            <legend>Policy draft (not applied until saved)</legend>
            <label>Policy pack name<input value={policyDraft.name} onChange={(event) => savePolicy({ ...policyDraft, name: event.target.value })} /></label>
            <label>Allowed ports<input value={policyDraft.allowedPorts} onChange={(event) => savePolicy({ ...policyDraft, allowedPorts: event.target.value })} /></label>
            <label>Private endpoint required for<input value={policyDraft.privateEndpointRequiredFor} onChange={(event) => savePolicy({ ...policyDraft, privateEndpointRequiredFor: event.target.value })} /></label>
            <label>Required DNS zones<input value={policyDraft.requiredDnsZones} onChange={(event) => savePolicy({ ...policyDraft, requiredDnsZones: event.target.value })} /></label>
            <label>Owner tag<input value={policyDraft.ownerTag} onChange={(event) => savePolicy({ ...policyDraft, ownerTag: event.target.value })} /></label>
            <label><input type="checkbox" checked={policyDraft.requiredHubRouting} onChange={(event) => savePolicy({ ...policyDraft, requiredHubRouting: event.target.checked })} /> Required hub routing</label>
            <label><input type="checkbox" checked={policyDraft.firewallInspectionRequired} onChange={(event) => savePolicy({ ...policyDraft, firewallInspectionRequired: event.target.checked })} /> Firewall inspection required</label>
            <label><input type="checkbox" checked={policyDraft.environmentIsolationRequired} onChange={(event) => savePolicy({ ...policyDraft, environmentIsolationRequired: event.target.checked })} /> Environment isolation required</label>
            <label><input type="checkbox" checked={policyDraft.loggingRequired} onChange={(event) => savePolicy({ ...policyDraft, loggingRequired: event.target.checked })} /> Logging required</label>
            <label><input type="checkbox" checked={policyDraft.allowCrossSubscriptionPeering} onChange={(event) => savePolicy({ ...policyDraft, allowCrossSubscriptionPeering: event.target.checked })} /> Allow cross-subscription peering</label>
            <label>Policy change reason<textarea value={policyReason} maxLength={1000} onChange={event => setPolicyReason(event.target.value)} /></label>
            <button className="button button-primary" type="button" disabled={!policyReason.trim() || (!draftChanges.length && policyState?.policy_revision !== 0)} onClick={persistPolicy}>Save policy revision</button>
          </fieldset>
          <div className="card-body"><button type="button" disabled={policyBusy} onClick={policyRead.refetch}>Reload saved policy</button><p>Revision {policyState?.revision ?? "unavailable"}. Reloading replaces the draft; review again after a conflict.</p></div>
        </section>

        <aside className="card">
          <div className="card-header">
            <div><h2>Exceptions and risk acceptance</h2><p>Approve temporary exceptions with owner, reason, and expiry.</p></div>
          </div>
          <fieldset className="card-body compliance-policy-grid" disabled={!policyState || policyBusy}>
            <legend>Authenticated server decision</legend>
            <label>Exception owner<input value={exceptionDraft.owner} onChange={(event) => setExceptionDraft({ ...exceptionDraft, owner: event.target.value })} /></label>
            <label>Risk acceptance reason<textarea rows={3} value={exceptionDraft.reason} onChange={(event) => setExceptionDraft({ ...exceptionDraft, reason: event.target.value })} /></label>
            <label>Expires at (00:00 UTC)<input type="date" value={exceptionDraft.expiresAt} onChange={(event) => setExceptionDraft({ ...exceptionDraft, expiresAt: event.target.value })} /></label>
            <button type="button" className="button button-primary" disabled={!selected} onClick={() => acceptRisk()}>Accept selected risk</button>
            <button type="button" disabled={!selected || !acceptedIds.has(selected.id)} onClick={() => acceptRisk("revoke")}>Revoke selected acceptance</button>
            <StructuredData value={exceptions} />
          </fieldset>
          <details className="card-body"><summary>Policy and exception audit</summary><StructuredData value={policyState?.audit ?? []} /></details>
          <details className="card-body"><summary>Saved policy change explanations</summary>
            {policyState?.audit.filter(entry => entry.action === "replace_policy").map(entry => <section key={entry.revision} className="compliance-policy-audit-entry">
              <h3>Decision revision {entry.revision}</h3>
              <p>{entry.actor} · {entry.at} · {entry.reason}</p>
              {entry.policy_diff ? <ul>{entry.policy_diff.map(change => <li key={change.field}>{policyFieldLabel(change.field)}: {String(change.before)} → {String(change.after)}</li>)}</ul> : <p>Historical field differences were not recorded for this revision.</p>}
              <p>{entry.invalidated_exception_ids ? `${entry.invalidated_exception_ids.length} active exceptions invalidated by this save.` : "Historical exception invalidation count unreported."}</p>
              <p>This audit records a policy change, not a historical evidence comparison or execution approval.</p>
            </section>)}
          </details>
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
