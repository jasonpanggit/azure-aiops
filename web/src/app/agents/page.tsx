"use client";

import { useEffect, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useScope } from "@/lib/scope-context";
import { multiAgentApi } from "@/lib/services";
import type { AutonomousAgent, Envelope, MultiAgentLedger } from "@/lib/types";

const DEFAULT_OBJECTIVE = "Investigate the highest-risk business service and recommend governed remediation.";

/** Human-controlled multi-agent investigation command surface. */
export default function MultiAgentInvestigationPage() {
  const { scope } = useScope();
  const [catalog, setCatalog] = useState<AutonomousAgent[]>([]);
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE);
  const [ledger, setLedger] = useState<Envelope<MultiAgentLedger> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [owner, setOwner] = useState("Service owner");

  useEffect(() => {
    let active = true;
    multiAgentApi.catalog(scope).then((result) => {
      if (active) setCatalog(result.data.agents);
    }).catch(() => {
      if (active) setCatalog([]);
    });
    return () => {
      active = false;
    };
  }, [scope]);

  async function runInvestigation() {
    const nextObjective = objective.trim();
    if (!nextObjective) return;
    setLoading(true);
    setError("");
    try {
      setLedger(await multiAgentApi.investigate(nextObjective, scope));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Investigation could not start.");
    } finally {
      setLoading(false);
    }
  }

  async function applyAction(action: string, payload: Record<string, unknown> = {}) {
    if (!ledger) return;
    setLedger(await multiAgentApi.action(ledger.data.ledger_id, action, payload, scope));
  }

  const evidence = ledger?.data.agent_runs.flatMap((run) => run.evidence) ?? [];
  const findings = ledger?.data.agent_runs.flatMap((run) => run.findings) ?? [];
  const activeAgents = ledger?.data.agent_runs.length ?? 0;

  return (
    <main className="page-container agents-workspace" aria-label="Multi-Agent Autonomous Investigation">
      <PageHeader
        eyebrow="Autonomous investigation"
        title="What can evidence reconciliation answer?"
        description="Coordinate specialized agents over governed tools while preserving authorization, evidence, human control, and a visible trust boundary."
        actions={
          <button className="button button-primary" type="button" onClick={runInvestigation} disabled={loading || !objective.trim()}>
            Run investigation
          </button>
        }
      />

      {error ? <StatePanel title="Investigation unavailable" message={error} tone="error" /> : null}
      {loading ? <StatePanel title="Coordinating agents" message="Selecting agents, running governed tools, reconciling evidence, and preparing synthesis." tone="loading" /> : null}

      <section className="card">
        <div className="card-header">
          <div>
            <h2>Objective and scope</h2>
            <p>All agents inherit the current workbench scope and the caller&apos;s authorization boundary.</p>
          </div>
          <StatusBadge label="Human controlled" tone="info" />
        </div>
        <div className="card-body agents-objective">
          <label>
            Investigation objective
            <textarea value={objective} onChange={(event) => setObjective(event.target.value)} rows={3} />
          </label>
          <div className="entity-pill-row" aria-label="Available specialized agents">
            {catalog.map((agent) => (
              <span key={agent.id} className="entity-pill" title={agent.role}>
                {agent.name}
              </span>
            ))}
          </div>
        </div>
      </section>

      {ledger ? (
        <>
          <EvidenceBar
            evidence={ledger.evidence.length ? ledger.evidence : evidence}
            warnings={ledger.warnings}
            knowledgeVersion={ledger.knowledge_version}
          />

          <section className="metric-grid" aria-label="Investigation metrics">
            <MetricCard label="Agents" value={activeAgents} detail="Specialists coordinated" />
            <MetricCard label="Findings" value={findings.length} detail="Evidence and unknowns recorded" />
            <MetricCard label="Groundedness" value={`${Math.round(ledger.data.evaluation.groundedness * 100)}%`} detail="Findings with evidence" tone={ledger.data.evaluation.groundedness >= 0.5 ? "success" : "warning"} />
            <MetricCard label="Latency" value={`${Math.round(ledger.data.evaluation.latency_ms)}ms`} detail="End-to-end orchestration" />
          </section>

          <section className="workspace-grid">
            <section className="card">
              <div className="card-header">
                <div><h2>Agent activity</h2><p>Tool usage and findings by specialist, without hidden chain-of-thought.</p></div>
                <StatusBadge label={ledger.data.status} tone={statusTone(ledger.data.status)} />
              </div>
              <div className="card-body agent-run-list">
                {ledger.data.agent_runs.map((run) => (
                  <article key={run.agent_id} className="agent-run-card">
                    <div className="reasoning-heading">
                      <div>
                        <strong>{run.agent_name}</strong>
                        <p className="muted">{run.tool_calls.map((call) => call.tool).join(", ") || "Synthesis only"}</p>
                      </div>
                      <StatusBadge label={run.status} tone={statusTone(run.status)} compact />
                    </div>
                    <ul>
                      {run.findings.map((finding) => (
                        <li key={finding.finding_id}>{finding.summary}</li>
                      ))}
                    </ul>
                  </article>
                ))}
              </div>
            </section>

            <section className="card">
              <div className="card-header"><div><h2>Evidence reconciliation</h2><p>Conflicts, stale evidence, missing providers, and unsupported conclusions.</p></div></div>
              <div className="card-body">
                <div className="split-kpis">
                  <MetricCard label="Evidence" value={ledger.data.reconciliation.evidence_count} detail="Cited evidence items" />
                  <MetricCard label="Confidence" value={ledger.data.reconciliation.reconciled_confidence} detail="After reconciliation" />
                </div>
                <StructuredData value={{
                  conflicts: ledger.data.reconciliation.conflicts,
                  stale_evidence: ledger.data.reconciliation.stale_evidence,
                  missing_providers: ledger.data.reconciliation.missing_providers,
                  unsupported_conclusions: ledger.data.reconciliation.unsupported_conclusions,
                }} />
              </div>
            </section>

            <section className="card">
              <div className="card-header"><div><h2>Final synthesis</h2><p>Evidence-backed conclusion and recommended next plan.</p></div><StatusBadge label={ledger.data.synthesis.confidence} tone={statusTone(ledger.data.synthesis.confidence)} /></div>
              <div className="card-body recommended-action-list">
                {ledger.data.synthesis.narration ? (
                  <span>
                    {ledger.data.synthesis.narration}
                    {ledger.data.synthesis.narrated_by ? <em className="muted"> (via {ledger.data.synthesis.narrated_by})</em> : null}
                  </span>
                ) : (
                  <span>{ledger.data.synthesis.summary}</span>
                )}
                {ledger.data.synthesis.narration_warning ? <span className="muted">{ledger.data.synthesis.narration_warning}</span> : null}
                <span>{ledger.data.synthesis.recommended_plan}</span>
                <span>{ledger.data.synthesis.required_decision}</span>
                {ledger.data.synthesis.unresolved_questions.map((question) => <span key={question}>Unresolved: {question}</span>)}
              </div>
            </section>

            <section className="card">
              <div className="card-header"><div><h2>Human-in-the-loop controls</h2><p>Operator decisions are appended to the ledger audit trail.</p></div></div>
              <div className="card-body agents-controls">
                <label>
                  Owner
                  <input value={owner} onChange={(event) => setOwner(event.target.value)} />
                </label>
                <div className="mode-toggle">
                  <button type="button" onClick={() => applyAction("request_more_evidence", { reason: "Need current provider evidence" })}>Request more evidence</button>
                  <button type="button" onClick={() => applyAction("accept_finding", { finding_id: findings[0]?.finding_id ?? "" })}>Accept finding</button>
                  <button type="button" onClick={() => applyAction("reject_finding", { finding_id: findings[0]?.finding_id ?? "", reason: "Insufficient evidence" })}>Reject finding</button>
                  <button type="button" onClick={() => applyAction("assign_owner", { owner })}>Assign owner</button>
                  <button type="button" onClick={() => applyAction("approve_plan", { approved_by: owner, guardrail: "governed handoff only" })}>Approve plan</button>
                  <button type="button" onClick={() => applyAction("stop_investigation", { reason: "Stopped by operator" })}>Stop investigation</button>
                </div>
                <StructuredData value={{ decisions: ledger.data.decisions, approvals: ledger.data.approvals, stop_reason: ledger.data.stop_reason }} />
              </div>
            </section>

            <section className="card">
              <div className="card-header"><div><h2>Evaluation</h2><p>Groundedness, scope isolation, tool correctness, convergence, latency, and cost.</p></div></div>
              <div className="card-body">
                <StructuredData value={ledger.data.evaluation} />
              </div>
            </section>

            <section className="card">
              <div className="card-header"><div><h2>Shared task ledger</h2><p>Objective, scope, evidence, findings, decisions, approvals, and outcome.</p></div></div>
              <div className="card-body">
                <StructuredData value={ledger.data} />
              </div>
            </section>
          </section>
        </>
      ) : (
        <StatePanel title="No investigation yet" message="Run an objective to coordinate specialist agents and build an auditable ledger." />
      )}
    </main>
  );
}
