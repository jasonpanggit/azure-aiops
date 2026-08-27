"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useApi } from "@/hooks/useApi";
import { titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { networkApi, operationsApi, vulnerabilityApi } from "@/lib/services";
import type { NetworkGap, RemediationOpportunity, RemediationPlan, RuleFinding, VulnerabilityExposure } from "@/lib/types";

type BacklogKind = "plan" | "opportunity" | "network" | "vulnerability" | "patch" | "lifecycle" | "configuration" | "incident" | "identity";

interface BacklogItem {
  id: string;
  kind: BacklogKind;
  title: string;
  status: string;
  priority: string;
  businessService: string;
  resource: string;
  impact: string;
  riskReduction: number;
  downtimeRisk: string;
  complianceImprovement: number;
  debtReduction: number;
  evidence: unknown;
  source: unknown;
}

function planToBacklog(plan: RemediationPlan): BacklogItem {
  const action = plan.recommended_action ?? {};
  return {
    id: plan.plan_id,
    kind: "plan",
    title: plan.title || plan.plan_id,
    status: plan.status || "draft",
    priority: String(action.priority ?? plan.status ?? "review"),
    businessService: plan.business_service || "",
    resource: plan.resource || plan.application || "",
    impact: String(action.impact ?? action.summary ?? "Approval-ready remediation plan"),
    riskReduction: plan.simulation_result?.risk_reduction_percent ?? 0,
    downtimeRisk: String(plan.simulation_result?.downtime_risk ?? "requires maintenance window"),
    complianceImprovement: Number(plan.simulation_result?.compliance_improvement_percent ?? 0),
    debtReduction: plan.simulation_result?.operational_debt_reduction_percent ?? 0,
    evidence: plan,
    source: plan,
  };
}

function opportunityToBacklog(opportunity: RemediationOpportunity): BacklogItem {
  return {
    id: opportunity.opportunity_id || `${opportunity.category}-${opportunity.resource}`,
    kind: String(opportunity.category || "opportunity").includes("identity") ? "identity" : "opportunity",
    title: titleize(opportunity.category || "Remediation opportunity"),
    status: "candidate",
    priority: opportunity.priority || "review",
    businessService: String(opportunity.business_service ?? ""),
    resource: opportunity.resource || "Scope not identified",
    impact: opportunity.rationale?.[0] || "Candidate requires plan generation before approval.",
    riskReduction: Number(opportunity.expected_risk_reduction ?? 0),
    downtimeRisk: "unknown until simulated",
    complianceImprovement: 0,
    debtReduction: 0,
    evidence: opportunity,
    source: opportunity,
  };
}

function networkGapToBacklog(gap: NetworkGap): BacklogItem {
  return {
    id: gap.gap_id,
    kind: "network",
    title: gap.title,
    status: "candidate",
    priority: gap.severity,
    businessService: "",
    resource: gap.resource_id || gap.resource_name,
    impact: gap.detail || gap.recommendation,
    riskReduction: gap.severity === "critical" ? 75 : gap.severity === "high" ? 60 : 35,
    downtimeRisk: "medium - network path validation required",
    complianceImprovement: gap.severity === "critical" ? 55 : 30,
    debtReduction: 25,
    evidence: gap.evidence,
    source: gap,
  };
}

function ruleToBacklog(rule: RuleFinding): BacklogItem {
  return {
    id: rule.finding_id,
    kind: "configuration",
    title: rule.title,
    status: "candidate",
    priority: rule.severity,
    businessService: "",
    resource: rule.rule_id,
    impact: rule.detail || rule.recommendation,
    riskReduction: rule.severity === "critical" ? 70 : rule.severity === "high" ? 50 : 25,
    downtimeRisk: "low - rule blast radius review required",
    complianceImprovement: 45,
    debtReduction: 20,
    evidence: rule.evidence,
    source: rule,
  };
}

function exposureToBacklog(exposure: VulnerabilityExposure): BacklogItem {
  return {
    id: exposure.cve_id,
    kind: "vulnerability",
    title: `${exposure.cve_id}: ${exposure.recommended_patch}`,
    status: "candidate",
    priority: exposure.severity,
    businessService: "",
    resource: `${exposure.affected_server_count} affected servers`,
    impact: `${exposure.affected_business_service_count} business services affected; ${exposure.reachable_server_count} reachable servers.`,
    riskReduction: exposure.expected_risk_reduction,
    downtimeRisk: "maintenance window required for patching",
    complianceImprovement: exposure.is_known_exploited ? 70 : 40,
    debtReduction: 30,
    evidence: exposure.finding_ids,
    source: exposure,
  };
}

/** Approval-oriented remediation workspace that separates recommendations from execution. */
export default function RemediationPage() {
  return (
    <Suspense fallback={<div className="page-container"><div className="state-panel state-loading">Preparing remediation workspace…</div></div>}>
      <RemediationContent />
    </Suspense>
  );
}

function RemediationContent() {
  const { scope } = useScope();
  const searchParams = useSearchParams();
  const fromCve = searchParams.get("cve") ?? "";
  const fromKb = searchParams.get("kb") ?? "";
  const fromBusinessService = searchParams.get("business_service") ?? "";
  const fromIncident = searchParams.get("incident") ?? "";
  const plans = useApi(() => operationsApi.remediationPlans(scope), [scope]);
  const opportunities = useApi(() => operationsApi.remediationOpportunities(scope), [scope]);
  const networkGaps = useApi(() => networkApi.gaps(scope), [scope]);
  const ruleFindings = useApi(() => networkApi.ruleFindings(scope), [scope]);
  const exposures = useApi(() => vulnerabilityApi.exposures(scope), [scope]);
  const [selectedId, setSelectedId] = useState("");
  const [category, setCategory] = useState<BacklogKind | "all">("all");
  const [copilotOpen, setCopilotOpen] = useState(false);
  const allPlanRows = plans.data?.data.plans ?? [];
  const allOpportunityRows = opportunities.data?.data.opportunities ?? [];
  // Remediation plans/opportunities are resource- and business-service-driven,
  // not CVE/KB-specific (Prompt 7's patch findings and this engine remain
  // decoupled by design), so a CVE/KB drilldown links here scoped to the
  // affected business service — the closest concrete cross-reference this
  // engine can answer today.
  const planRows = fromBusinessService
    ? allPlanRows.filter((plan) => plan.business_service === fromBusinessService)
    : allPlanRows;
  const opportunityRows = fromBusinessService
    ? allOpportunityRows.filter((opportunity) => opportunity.business_service === fromBusinessService)
    : allOpportunityRows;
  const backlog = useMemo(() => {
    const rows = [
      ...planRows.map(planToBacklog),
      ...opportunityRows.map(opportunityToBacklog),
      ...(networkGaps.data?.data.gaps ?? []).map(networkGapToBacklog),
      ...(ruleFindings.data?.data.findings ?? []).map(ruleToBacklog),
      ...(exposures.data?.data ?? []).map(exposureToBacklog),
    ];
    const seeded: BacklogItem[] = [
      {
        id: fromIncident ? `incident-${fromIncident}` : "incident-readiness",
        kind: "incident",
        title: fromIncident ? `Resolve incident ${fromIncident}` : "Incident remediation readiness",
        status: "candidate",
        priority: fromIncident ? "high" : "medium",
        businessService: fromBusinessService,
        resource: fromIncident || "incident queue",
        impact: "Convert incident commander findings into a governed remediation handoff.",
        riskReduction: fromIncident ? 65 : 20,
        downtimeRisk: "depends on selected change",
        complianceImprovement: 15,
        debtReduction: 20,
        evidence: { incident: fromIncident },
        source: { incident: fromIncident },
      },
      {
        id: "lifecycle-debt",
        kind: "lifecycle",
        title: "Address lifecycle and supportability debt",
        status: "candidate",
        priority: "medium",
        businessService: fromBusinessService,
        resource: "lifecycle inventory",
        impact: "Upgrade or retire stale runtime and platform versions before they become incident drivers.",
        riskReduction: 30,
        downtimeRisk: "planned maintenance required",
        complianceImprovement: 25,
        debtReduction: 60,
        evidence: { source: "semantic lifecycle metadata" },
        source: { category: "lifecycle" },
      },
      {
        id: "identity-governance",
        kind: "identity",
        title: "Review identity and access remediation",
        status: "candidate",
        priority: "medium",
        businessService: fromBusinessService,
        resource: "identity assignments",
        impact: "Validate least-privilege access and approval boundaries for remediation execution.",
        riskReduction: 25,
        downtimeRisk: "low",
        complianceImprovement: 35,
        debtReduction: 20,
        evidence: { source: "governance policy" },
        source: { category: "identity" },
      },
    ];
    return [...rows, ...seeded]
      .filter((item) => category === "all" || item.kind === category)
      .sort((left, right) => right.riskReduction - left.riskReduction);
  }, [planRows, opportunityRows, networkGaps.data, ruleFindings.data, exposures.data, category, fromBusinessService, fromIncident]);
  const selected = backlog.find((item) => item.id === selectedId) ?? backlog[0] ?? null;
  const pending = backlog.length;
  const evidencePack = selected ? {
    plan: selected.source,
    evidence: selected.evidence,
    sourceEvidence: [
      ...(plans.data?.evidence ?? []),
      ...(opportunities.data?.evidence ?? []),
      ...(networkGaps.data?.evidence ?? []),
      ...(ruleFindings.data?.evidence ?? []),
      ...(exposures.data?.evidence ?? []),
    ],
    review_boundary: "Approval, execution, and outcome capture are unavailable in Phase 1.",
  } : {};
  const loading = plans.loading || opportunities.loading || networkGaps.loading || ruleFindings.loading || exposures.loading;
  const error = plans.error ?? opportunities.error ?? networkGaps.error ?? ruleFindings.error ?? exposures.error;

  return (
    <div className="page-container remediation-center">
      <PageHeader
        eyebrow="Governed remediation center"
        title="What can be reviewed next?"
        description="Review evidence-backed remediation candidates in the current scope. Phase 1 does not approve, execute, or record outcomes for changes."
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about remediation" />}
        metadata={
          <>
            <span>Future-phase candidates only</span>
            <span>No approval or execution in Phase 1</span>
            <span>Evidence remains reviewable</span>
          </>
        }
      />
      <EvidenceBar
        evidence={[...(plans.data?.evidence ?? []), ...(opportunities.data?.evidence ?? []), ...(networkGaps.data?.evidence ?? []), ...(ruleFindings.data?.evidence ?? []), ...(exposures.data?.evidence ?? [])]}
        knowledgeVersion={plans.data?.knowledge_version}
        warnings={[...(plans.data?.warnings ?? []), ...(opportunities.data?.warnings ?? []), ...(networkGaps.data?.warnings ?? []), ...(ruleFindings.data?.warnings ?? []), ...(exposures.data?.warnings ?? [])]}
      />

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel={fromBusinessService || "Remediation"}
        starterQuestions={[
          { label: "What should be fixed first?", tool: "remediation_opportunities", toolArguments: {} },
          { label: "Highest risk-reduction remediation plans", tool: "remediation_plans", toolArguments: {} },
          ...(fromBusinessService
            ? [
                {
                  label: `Tell me about the ${fromBusinessService} business service.`,
                  tool: "business_service_context",
                  toolArguments: { name: fromBusinessService },
                },
              ]
            : [{ label: "What changed before the outage?", tool: "incidents", toolArguments: {} }]),
        ]}
      />

      {(fromCve || fromKb || fromIncident) && (
        <div className="callout" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <span>
            Filtered from{" "}
            {fromCve && (
              <Link className="table-primary-link" href={`/exposure/cves/${encodeURIComponent(fromCve)}`}>
                {fromCve}
              </Link>
            )}
            {fromCve && fromKb && " / "}
            {fromKb && (
              <Link className="table-primary-link" href={`/exposure/kbs/${encodeURIComponent(fromKb)}`}>
                {fromKb}
              </Link>
            )}
            {fromIncident && `Incident ${fromIncident}`}
            {fromIncident && (fromCve || fromKb || fromBusinessService) ? " · " : ""}
            {fromBusinessService
              ? `showing plans and opportunities for the "${fromBusinessService}" business service.`
              : "this environment has no business-service mapping for that handoff, so all plans are shown."}
          </span>
          <Link className="button" href="/remediation">Clear filter</Link>
        </div>
      )}

      <div className="metric-grid remediation-metrics">
        <MetricCard label="Unified backlog" value={backlog.length} detail={`${pending} future-phase candidates in this scope`} />
        <MetricCard label="Network candidates" value={(networkGaps.data?.data.gaps.length ?? 0) + (ruleFindings.data?.data.findings.length ?? 0)} detail="Firewall, NSG, UDR, peering, private endpoint, and inspection-path fixes" />
        <MetricCard
          label="Highest simulated reduction"
          value={`${Math.round(Math.max(0, ...backlog.map((item) => item.riskReduction)))}%`}
          detail="Projected current-to-future risk delta"
          tone="success"
        />
        <MetricCard
          label="Execution boundary"
          value="Read-only"
          detail="Approval and execution are deferred to a future phase"
          tone="warning"
        />
      </div>

      <div className="segmented-control remediation-filter" aria-label="Remediation category filter">
        {(["all", "network", "vulnerability", "patch", "configuration", "incident", "identity", "lifecycle"] as const).map((value) => (
          <button type="button" key={value} className={category === value ? "segmented-active" : ""} onClick={() => setCategory(value)}>
            {value === "all" ? "All" : titleize(value)}
          </button>
        ))}
      </div>

      {error ? (
        <StatePanel
          title="Remediation intelligence is unavailable"
          message={error.message ?? "No remediation response was returned."}
          tone="error"
        />
      ) : loading ? (
        <StatePanel title="Reading remediation candidates" message="Joining source evidence with projected impact; approval and execution remain unavailable." tone="loading" />
      ) : (
        <div className="remediation-layout">
          <section className="card">
            <div className="card-header">
              <div>
                <h2>Unified remediation backlog</h2>
                <p>Network, vulnerability, patch, lifecycle, configuration, incident, and identity candidates in one governed queue.</p>
              </div>
            </div>
            <div className="plan-list">
              {backlog.map((item) => {
                const decision = item.status;
                return (
                <article className={`plan-row ${selected?.id === item.id ? "plan-row-selected" : ""}`} key={item.id}>
                  <div className="plan-row-heading">
                    <div>
                      <StatusBadge label={decision || "draft"} tone={statusTone(decision)} />
                      <StatusBadge label={titleize(item.kind)} tone="info" compact />
                      <h3>{item.title}</h3>
                      <p>{item.businessService || item.resource || "Scope not mapped"}</p>
                    </div>
                    <div className="plan-risk">
                      <strong>{Math.round(item.riskReduction)}%</strong>
                      <span>risk reduction</span>
                    </div>
                  </div>
                  <p>{item.impact}</p>
                  <button type="button" className="button" onClick={() => setSelectedId(item.id)}>Review plan</button>
                  <div className="plan-actions">
                    <button type="button" className="button button-secondary" onClick={() => setSelectedId(item.id)}>View future-phase candidate</button>
                  </div>
                </article>
              )})}
              {backlog.length === 0 && <StatePanel title="No remediation backlog" message="No governed remediation candidates exist in this scope." />}
            </div>
          </section>

          <aside className="card">
            <div className="card-header">
              <div>
                <h2>Evidence and projected impact</h2>
                <p>Affected entities, source evidence, and projected impact are reviewable; no change is executed here.</p>
              </div>
            </div>
            <div className="card-body remediation-plan-detail">
              {selected ? (
                <>
                  <h3>{selected.title}</h3>
                  <div className="simulation-grid">
                    <MetricCard label="Projected risk reduction" value={`${Math.round(selected.riskReduction)}%`} detail="Current vs projected risk" tone="success" />
                    <MetricCard label="Downtime risk" value={selected.downtimeRisk} detail="Requires maintenance-window review" tone="warning" />
                    <MetricCard label="Compliance improvement" value={`${Math.round(selected.complianceImprovement)}%`} detail="Policy/SLA uplift estimate" />
                    <MetricCard label="Debt reduction" value={`${Math.round(selected.debtReduction)}%`} detail="Operational-debt reduction estimate" />
                  </div>
                  <section className="remediation-section">
                    <h4>Plan steps</h4>
                    <ol>
                      <li>Confirm affected entities and owner accountability.</li>
                      <li>Review the source evidence and affected entities.</li>
                      <li>Carry this candidate into a future approval workflow.</li>
                      <li>Validate live state only after an approved change exists.</li>
                    </ol>
                  </section>
                  <section className="remediation-section">
                    <h4>Dependencies and maintenance window</h4>
                    <p>Dependencies: owner sign-off, CAB approval, affected-path validation, rollback owner. Window: schedule by service criticality and downtime risk.</p>
                  </section>
                  <section className="remediation-section">
                    <h4>Future-phase validation boundary</h4>
                    <p>Live execution, approval, validation, and rollback recording are unavailable in this Phase 1 read-only surface.</p>
                  </section>
                </>
              ) : <StatePanel title="No plan selected" message="Select a backlog item to generate a governed plan." />}
            </div>
          </aside>
        </div>
      )}

      {selected && (
        <section className="card evidence-pack-card">
          <details>
            <summary>CAB-ready evidence pack</summary>
            <div className="evidence-pack">
              <StructuredData value={evidencePack} />
            </div>
          </details>
        </section>
      )}

      {selected && (
        <div className="remediation-governance-grid">
          <section className="card">
            <div className="card-header">
              <div>
                <h2>Future-phase decision boundary</h2>
                <p>Approval and decision history are not available from this Phase 1 read-only surface.</p>
              </div>
              <StatusBadge label="Review only" tone="info" />
            </div>
            <div className="card-body remediation-form-grid">
              <p className="callout callout-warning">Approval workflow unavailable in Phase 1. Use the evidence pack above as a read-only handoff to the future approval surface.</p>
              <details>
                <summary>View candidate evidence pack</summary>
                <StructuredData value={evidencePack} />
              </details>
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <div>
                <h2>Future-phase execution handoff</h2>
                <p>Execution channels and outcome capture are intentionally not active in Phase 1.</p>
              </div>
            </div>
            <div className="card-body remediation-form-grid">
              <p className="callout callout-warning">No execution, approval, rollback, or realized-outcome controls are available from this read-only candidate view.</p>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
