"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { useScope } from "@/lib/scope-context";
import { ScopeBookmarkError, scopedBookmark, scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { multiAgentApi } from "@/lib/services";
import type { AutonomousAgent, Envelope, MultiAgentLedger } from "@/lib/types";

const DEFAULT_OBJECTIVE = "Review current scoped risk and recommend a governed next decision.";

/** Human-controlled multi-agent investigation command surface. */
export default function MultiAgentInvestigationPage() {
  return <Suspense fallback={<StatePanel title="Preparing investigation" message="Reading the scoped investigation bookmark." tone="loading" />}><ScopedAgents /></Suspense>;
}

function ScopedAgents() {
  const { scope } = useScope();
  const search = useSearchParams();
  let effectiveScope: ScopeSelection;
  try { effectiveScope = scopedBookmark(search, scope); }
  catch (error) {
    if (!(error instanceof ScopeBookmarkError)) throw error;
    return <main className="page-container"><StatePanel title="Investigation bookmark unavailable" message={error.message} tone="error" /><Link className="button" href="/agents">Clear investigation bookmark</Link></main>;
  }
  const ledgerId = search.get("ledger_id") ?? "";
  const valid = !search.has("ledger_id") || (search.getAll("ledger_id").length === 1 && /^[A-Za-z0-9_-]{1,128}$/.test(ledgerId));
  const query = scopeToSearchParams(effectiveScope);
  if (!valid) return <main className="page-container"><StatePanel title="Investigation bookmark unavailable" message="Use one exact retained ledger identifier of at most 128 letters, digits, hyphens or underscores." tone="error" /><Link className="button" href={`/agents${query.size ? `?${query}` : ""}`}>Clear retained ledger selection</Link></main>;
  return <AgentsWorkspace key={`${JSON.stringify(effectiveScope)}::${ledgerId}`} scope={effectiveScope} ledgerId={ledgerId} />;
}

function AgentsWorkspace({ scope, ledgerId }: { scope: ScopeSelection; ledgerId: string }) {
  const [catalog, setCatalog] = useState<AutonomousAgent[]>([]);
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE);
  const [ledger, setLedger] = useState<Envelope<MultiAgentLedger> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [owner, setOwner] = useState("Service owner");
  const [selectedFindingId, setSelectedFindingId] = useState("");
  const [decisionReason, setDecisionReason] = useState("");
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [reviewUncertain, setReviewUncertain] = useState(false);
  const [reload, setReload] = useState(0);
  const requestId = useRef(0);

  useEffect(() => {
    let active = true;
    setCatalog([]);
    setCatalogLoading(true);
    setCatalogError("");
    setLedger(null);
    setSelectedFindingId("");
    setDecisionReason("");
    setError("");
    setReviewUncertain(false);
    setLoading(Boolean(ledgerId));
    if (ledgerId) {
      const id = ++requestId.current;
      multiAgentApi.ledger(ledgerId, scope).then(result => {
        if (!active || id !== requestId.current) return;
        if (result.data.ledger_id !== ledgerId) throw new Error("The response did not match the exact retained investigation. No replacement ledger was opened.");
        setLedger(result);
        setObjective(result.data.objective);
      }).catch((reason: unknown) => {
        if (active && id === requestId.current) setError(reason instanceof Error ? reason.message : "Retained investigation could not be read.");
      }).finally(() => {
        if (active && id === requestId.current) setLoading(false);
      });
    }
    multiAgentApi.catalog(scope).then((result) => {
      if (active) setCatalog(result.data.agents);
    }).catch((reason: unknown) => {
      if (active) setCatalogError(reason instanceof Error ? reason.message : "Agent catalog could not be loaded.");
    }).finally(() => {
      if (active) setCatalogLoading(false);
    });
    return () => {
      active = false;
      requestId.current += 1;
    };
  }, [scope, ledgerId, reload]);

  async function runInvestigation() {
    const nextObjective = objective.trim();
    if (!nextObjective || loading || ledgerId) return;
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    setSelectedFindingId("");
    setDecisionReason("");
    try {
      const result = await multiAgentApi.investigate(nextObjective, scope);
      if (id === requestId.current) setLedger(result);
    } catch (reason) {
      if (id === requestId.current) setError(reason instanceof Error ? reason.message : "Investigation could not start.");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }

  async function applyAction(action: string, payload: Record<string, unknown> = {}) {
    if (!ledger || loading || reviewUncertain) return;
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const result = await multiAgentApi.action(ledger.data.ledger_id, action, payload, scope);
      if (id === requestId.current) {
        if (result.data.ledger_id !== ledger.data.ledger_id) {
          setReviewUncertain(true);
          throw new Error("The action response did not match this retained investigation. Reload before further review.");
        }
        setLedger(result);
      }
    } catch (reason) {
      if (id === requestId.current) setError(reason instanceof Error ? reason.message : "Investigation action could not be completed.");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }

  const evidence = ledger?.data.agent_runs.flatMap((run) => run.evidence) ?? [];
  const reviewBlocked = loading || reviewUncertain;
  const findings = ledger?.data.agent_runs.flatMap((run) => run.findings) ?? [];
  const selectedFinding = findings.find((finding) => finding.finding_id === selectedFindingId);
  const activeAgents = ledger?.data.agent_runs.length ?? 0;
  const configuredAgents = catalog.filter(
    (agent) => agent.foundry?.configured,
  ).length;
  const inactiveCandidates = catalog.filter(
    (agent) => agent.foundry?.status === "available_inactive",
  ).length;
  const deterministicDegraded = ledger?.data.activation?.mode
    !== "foundry";
  const currentQuery = scopeToSearchParams(scope);
  const newInvestigationHref = `/agents${currentQuery.size ? `?${currentQuery}` : ""}`;
  const retainedQuery = new URLSearchParams(currentQuery);
  if (ledger) retainedQuery.set("ledger_id", ledger.data.ledger_id);

  return (
    <main className="page-container agents-workspace" aria-label="Multi-Agent Autonomous Investigation">
      <PageHeader
        eyebrow="Specialist investigation"
        title="What can evidence reconciliation answer?"
        description="Select specialist definitions and run governed local tools; Foundry activation status is shown explicitly and never inferred."
        actions={
          <button className="button button-primary" type="button" onClick={runInvestigation} disabled={loading || Boolean(ledgerId) || !objective.trim()}>
            Run deterministic investigation
          </button>
        }
      />

      {ledgerId || ledger ? <section className="callout agents-continuation" aria-label="Retained investigation continuation">
        <p>{ledgerId ? `Opening retained ledger ${ledgerId}.` : `Retained ledger ${ledger?.data.ledger_id}.`} Reading or reopening does not rerun tools, resume provider execution, or authorize an operational change.</p>
        <div className="button-row">
          {ledgerId ? <><button className="button" disabled={loading} onClick={() => setReload(value => value + 1)}>Reload retained investigation</button><Link className="button" href={newInvestigationHref}>Start a different investigation</Link></> : <Link className="button" href={`/agents?${retainedQuery}`}>Open retained investigation</Link>}
        </div>
      </section> : null}
      {error ? <StatePanel title="Investigation unavailable" message={error} tone="error" /> : null}
      {catalogError ? <StatePanel title="Agent catalog unavailable" message={catalogError} tone="error" /> : null}
      {loading ? <StatePanel title={ledgerId ? "Loading retained investigation" : "Running deterministic specialist plans"} message={ledgerId ? "Reading the exact retained ledger under current authorization; no tools are restarted." : "Selecting specialist definitions, running governed local tools, reconciling evidence, and preparing synthesis."} tone="loading" /> : null}

      <section className="card">
        <div className="card-header">
          <div>
            <h2>Objective and scope</h2>
            <p>All agents inherit the current workbench scope and the caller&apos;s authorization boundary.</p>
          </div>
          <StatusBadge label="Human controlled" tone="info" />
          <StatusBadge
            label={catalogLoading ? "Loading Foundry status"
              : catalogError ? "Foundry status unknown"
              : configuredAgents
              ? `${configuredAgents} Foundry active`
              : inactiveCandidates
              ? `${inactiveCandidates} Foundry available - inactive · deterministic fallback`
              : "Foundry unavailable · deterministic fallback"}
            tone={configuredAgents ? "success" : "warning"}
          />
        </div>
        <div className="card-body agents-objective">
          <label>
            Investigation objective
            <textarea value={objective} readOnly={Boolean(ledgerId)} onChange={(event) => setObjective(event.target.value)} rows={3} />
          </label>
          <div className="entity-pill-row" aria-label="Available specialized agents">
            {catalog.map((agent) => {
              const foundryStatus = agent.foundry?.status ?? "unavailable";
              const degradedReason = agent.foundry?.degraded_reason
                ?? "Foundry activation is unavailable.";
              const statusLabel = foundryStatus === "active"
                ? "Foundry active"
                : foundryStatus === "available_inactive"
                ? "Foundry available - inactive"
                : "Foundry unavailable";
              return (
                <span key={agent.id} className="entity-pill" title={`${agent.role} ${degradedReason}`}>
                  {agent.name}
                  <StatusBadge
                    label={statusLabel}
                    tone={foundryStatus === "active" ? "success" : "neutral"}
                    compact
                  />
                </span>
              );
            })}
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
            <MetricCard
              label={deterministicDegraded ? "Specialist plans" : "Agents"}
              value={activeAgents}
              detail={deterministicDegraded
                ? "Deterministic specialist plans"
                : "Activated Foundry agents"}
            />
            <MetricCard label="Findings" value={findings.length} detail="Evidence and unknowns recorded" />
            <MetricCard
              label="Groundedness"
              value={ledger.data.evaluation.groundedness_status === "unavailable"
                ? "Unavailable"
                : `${Math.round(ledger.data.evaluation.groundedness * 100)}%`}
              detail={ledger.data.evaluation.groundedness_reason || "Findings with retained citations"}
              tone={ledger.data.evaluation.groundedness >= 0.5 ? "success" : "warning"}
            />
            <MetricCard label="Citations" value={ledger.data.citations?.length ?? 0} detail="Retained evidence references" />
            <MetricCard label="Latency" value={`${Math.round(ledger.data.evaluation.latency_ms)}ms`} detail="End-to-end orchestration" />
          </section>

          <section className="workspace-grid">
            <section className="card">
              <div className="card-header">
                <div><h2>{deterministicDegraded ? "Specialist plan activity" : "Agent activity"}</h2><p>Tool usage and findings by specialist definition, without hidden chain-of-thought.</p></div>
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
                      <StatusBadge
                        label={run.execution_mode === "foundry"
                          ? "Foundry agent"
                          : "Deterministic local fallback"}
                        tone={run.execution_mode === "foundry" ? "success" : "warning"}
                        compact
                      />
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
              <div className="card-header"><div><h2>{deterministicDegraded ? "Deterministic synthesis" : "Final synthesis"}</h2><p>Citation-backed conclusion and recommended next plan.</p></div><StatusBadge label={ledger.data.synthesis.confidence} tone={statusTone(ledger.data.synthesis.confidence)} /></div>
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
              <div className="card-header"><div><h2>Human-in-the-loop controls</h2><p>Operator decisions are appended to the ledger audit trail. Stop records a review decision; it does not cancel an in-flight provider call.</p></div></div>
              <div className="card-body agents-controls">
                <label>
                  Finding to review
                  <select value={selectedFinding?.finding_id ?? ""} disabled={reviewBlocked} onChange={(event) => {
                    setSelectedFindingId(event.target.value);
                    setDecisionReason("");
                  }}>
                    <option value="">Select a finding</option>
                    {findings.map((finding) => (
                      <option key={finding.finding_id} value={finding.finding_id}>{finding.summary} ({finding.finding_id})</option>
                    ))}
                  </select>
                </label>
                {selectedFinding ? (
                  <div aria-label="Selected finding review">
                    <p>{selectedFinding.summary}</p>
                    <p>Finding {selectedFinding.finding_id} | {selectedFinding.confidence} confidence | {selectedFinding.evidence_count} evidence items</p>
                    <details><summary>Specialist-run evidence for this finding</summary><StructuredData value={ledger.data.agent_runs.find((run) => run.findings.some((finding) => finding.finding_id === selectedFinding.finding_id))?.evidence ?? []} /></details>
                  </div>
                ) : null}
                <label>
                  Finding decision reason
                  <textarea value={decisionReason} maxLength={1000} disabled={reviewBlocked} onChange={(event) => setDecisionReason(event.target.value)} rows={2} />
                </label>
                <label>
                  Owner
                  <input value={owner} disabled={reviewBlocked} onChange={(event) => setOwner(event.target.value)} />
                </label>
                <div className="mode-toggle">
                  <button type="button" disabled={reviewBlocked} onClick={() => applyAction("request_more_evidence", { reason: "Need current provider evidence" })}>Request more evidence</button>
                  <button type="button" disabled={reviewBlocked || !selectedFinding || !decisionReason.trim()} onClick={() => applyAction("accept_finding", { finding_id: selectedFindingId, reason: decisionReason.trim() })}>Accept finding</button>
                  <button type="button" disabled={reviewBlocked || !selectedFinding || !decisionReason.trim()} onClick={() => applyAction("reject_finding", { finding_id: selectedFindingId, reason: decisionReason.trim() })}>Reject finding</button>
                  <button type="button" disabled={reviewBlocked || !owner.trim()} onClick={() => applyAction("assign_owner", { owner })}>Assign owner</button>
                  <button type="button" disabled={reviewBlocked || !owner.trim()} onClick={() => applyAction("approve_plan", { approved_by: owner, guardrail: "governed handoff only" })}>Approve plan</button>
                  <button type="button" disabled={reviewBlocked} onClick={() => applyAction("stop_investigation", { reason: "Stopped by operator" })}>Stop investigation</button>
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
