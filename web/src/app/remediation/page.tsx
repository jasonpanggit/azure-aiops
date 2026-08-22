"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { CopilotLauncher } from "@/components/ui/CopilotLauncher";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useApi } from "@/hooks/useApi";
import { titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { operationsApi } from "@/lib/services";

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
  const pending = planRows.filter((plan) => !["completed", "closed"].includes(plan.status?.toLowerCase())).length;

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Decision support"
        title="Remediation"
        description="Compare risk reduction, blast radius, approval requirements, and rollback readiness before authorizing a change."
        metadata={
          <>
            <span>Recommendations are read-only</span>
            <span>Operator approval required</span>
            <span>Rollback evidence retained</span>
          </>
        }
      />
      <EvidenceBar
        evidence={[...(plans.data?.evidence ?? []), ...(opportunities.data?.evidence ?? [])]}
        knowledgeVersion={plans.data?.knowledge_version}
        warnings={[...(plans.data?.warnings ?? []), ...(opportunities.data?.warnings ?? [])]}
      />

      <CopilotLauncher
        contextLabel={fromBusinessService}
        starterQuestions={["what should be fixed first", "what changed before the outage", "highest risk-reduction remediation plans"]}
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
        <MetricCard label="Action plans" value={planRows.length} detail={`${pending} awaiting review or completion`} />
        <MetricCard label="Opportunities" value={opportunityRows.length} detail="Ranked by operational risk reduction" />
        <MetricCard
          label="Highest simulated reduction"
          value={`${Math.round(Math.max(0, ...planRows.map((plan) => plan.simulation_result?.risk_reduction_percent ?? 0)))}%`}
          detail="Expected risk reduction before execution"
          tone="success"
        />
        <MetricCard
          label="Approval boundary"
          value="Human"
          detail="No recommendation is executed automatically"
          tone="warning"
        />
      </div>

      {plans.error || opportunities.error ? (
        <StatePanel
          title="Remediation intelligence is unavailable"
          message={(plans.error ?? opportunities.error)?.message ?? "No remediation response was returned."}
          tone="error"
        />
      ) : plans.loading || opportunities.loading ? (
        <StatePanel title="Evaluating remediation options" message="Simulating impact, approvals, and rollback readiness." tone="loading" />
      ) : (
        <div className="remediation-layout">
          <section className="card">
            <div className="card-header">
              <div>
                <h2>Action plans</h2>
                <p>Governed plans with impact simulation and explicit approval state.</p>
              </div>
            </div>
            <div className="plan-list">
              {planRows.map((plan) => (
                <article className="plan-row" key={plan.plan_id}>
                  <div className="plan-row-heading">
                    <div>
                      <StatusBadge label={plan.status || "draft"} tone={statusTone(plan.status)} />
                      <h3>{plan.title || plan.plan_id}</h3>
                      <p>{plan.business_service || plan.application || plan.resource || "Scope not mapped"}</p>
                    </div>
                    <div className="plan-risk">
                      <strong>{Math.round(plan.simulation_result?.risk_reduction_percent ?? 0)}%</strong>
                      <span>risk reduction</span>
                    </div>
                  </div>
                  <details>
                    <summary>Review plan evidence</summary>
                    <StructuredData value={plan} />
                  </details>
                  <div className="plan-actions">
                    <button type="button" className="button">Review rollback</button>
                    <button type="button" className="button button-primary">Request approval</button>
                  </div>
                </article>
              ))}
              {planRows.length === 0 && <StatePanel title="No action plans" message="No governed remediation plans exist in this scope." />}
            </div>
          </section>

          <aside className="card">
            <div className="card-header">
              <div>
                <h2>Top opportunities</h2>
                <p>Candidate actions that have not yet become governed plans.</p>
              </div>
            </div>
            <div className="opportunity-list">
              {opportunityRows.map((opportunity, index) => (
                <article key={opportunity.opportunity_id ?? `${opportunity.resource}-${index}`}>
                  <span className="rank-number">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <StatusBadge label={opportunity.priority || "candidate"} tone={statusTone(opportunity.priority)} compact />
                    <h3>{titleize(opportunity.category || "Remediation opportunity")}</h3>
                    <p>{opportunity.resource || opportunity.rationale?.[0] || "Operational scope not identified"}</p>
                  </div>
                </article>
              ))}
              {opportunityRows.length === 0 && <div className="card-body muted">No remediation opportunities are available.</div>}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
