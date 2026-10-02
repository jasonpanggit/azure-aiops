"use client";

import { useEffect, useMemo, useState } from "react";
import { SituationTable } from "@/components/SituationTable";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { useScope } from "@/lib/scope-context";
import { situationsApi } from "@/lib/services";
import { buildSituationsCopilotContext } from "@/lib/copilot/page-adapters";
import { rankDurableSituations, type SituationPriority } from "@/lib/situations";
import type { DurableSituation, Envelope } from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

/** Triage queue for ranked, service-aware operational Situations. */
export default function SituationsPage() {
  const { scope } = useScope();
  const [envelope, setEnvelope] = useState<Envelope<DurableSituation[]> | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [priority, setPriority] = useState<"all" | SituationPriority>("all");
  const [page, setPage] = useState(0);
  const [copilotOpen, setCopilotOpen] = useState(false);

  useEffect(() => {
    let active = true;
    setError("");
    setEnvelope(null);
    situationsApi
      .list(scope, query, priority === "all" ? "" : priority, page * 25, 25)
      .then((result) => active && setEnvelope(result))
      .catch((reason: unknown) => active && setError(reason instanceof Error ? reason.message : "Situations are unavailable"));
    return () => {
      active = false;
    };
  }, [page, priority, query, scope]);

  const situations = useMemo(() => {
    return rankDurableSituations(envelope?.data ?? []);
  }, [envelope]);

  const rankedDurableSituations = useMemo(() => {
    const bySituationId = new Map(
      (envelope?.data ?? []).map((situation) => [situation.situation_id, situation]),
    );
    return situations.flatMap((summary) => {
      const durable = bySituationId.get(summary.id);
      return durable ? [durable] : [];
    });
  }, [envelope, situations]);

  const situationsCopilot = buildSituationsCopilotContext({
    scope,
    situations: rankedDurableSituations,
    query,
    priority,
    page,
    pageSize: 25,
    totalCount: envelope?.pagination?.total ?? rankedDurableSituations.length,
    nextOffset: envelope?.pagination?.next_offset ?? null,
    selectedSituationId: null,
    available: Boolean(envelope) && !error,
    observedAt: envelope?.evidence?.[0]?.timestamp,
    evidence: envelope?.evidence ?? [],
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Operate"
        title="Which situations need triage?"
        description="Compare authorized situations by impact, blast radius, evidence confidence, and recency before opening an evidence-backed brief."
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about situations" />}
        metadata={
          <>
            <span>{envelope?.data.length ?? 0} in current scope</span>
            <span>Read-only investigation</span>
            <span>Remediation handoff is future-phase and read-only</span>
          </>
        }
      />

      <CopilotInsights
        snapshot={situationsCopilot.snapshot}
        ready={envelope !== null || Boolean(error)}
        requestedScope={situationsCopilot.requestedScope}
        contextLabel="Situations queue"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      {envelope && (
        <EvidenceBar
          evidence={envelope.evidence}
          knowledgeVersion={envelope.knowledge_version}
          warnings={envelope.warnings}
          fallbackTimestamp={envelope.evidence[0]?.timestamp}
        />
      )}

      <div className="queue-toolbar">
        <label className="search-field">
          <span>Search situations</span>
          <input
            type="search"
            value={query}
            onChange={(event) => { setQuery(event.target.value); setPage(0); }}
            placeholder="Service, application, owner, cause, or incident ID"
          />
        </label>
        <div className="segmented-control" aria-label="Priority filter">
          {(["all", "P1", "P2", "P3"] as const).map((value) => (
            <button
              type="button"
              key={value}
              className={priority === value ? "segmented-active" : ""}
              onClick={() => { setPriority(value); setPage(0); }}
            >
              {value === "all" ? "All priorities" : value}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <StatePanel
          title="Situation intelligence is unavailable"
          message={`${error}. The workbench will not present an empty queue as an all-clear state.`}
          tone="error"
        />
      ) : !envelope ? (
        <StatePanel
          title="Loading Situation queue"
          message="Correlating incident evidence and business impact."
          tone="loading"
        />
      ) : situations.length === 0 ? (
        <StatePanel
          title={query.trim() || priority !== "all" ? "No situations match these filters" : "No active situations in this scope"}
          message={
            query.trim() || priority !== "all"
              ? "Adjust the priority or search criteria. This result reflects the current operating scope."
              : "No durable situation records are currently available for the selected operating scope. This is not a source-health confirmation; review data coverage below."
          }
        />
      ) : (
        <div className="card queue-card">
          <SituationTable situations={situations} />
          {envelope.pagination && (
            <div className="table-footer">
              Showing {envelope.pagination.total === 0 ? 0 : envelope.pagination.offset + 1}–
              {Math.min(envelope.pagination.offset + envelope.data.length, envelope.pagination.total)} of {envelope.pagination.total}
              <span className="table-footer-actions">
                <button type="button" className="button" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</button>
                <button type="button" className="button" disabled={envelope.pagination.next_offset === null} onClick={() => setPage((value) => value + 1)}>Next</button>
              </span>
            </div>
          )}
        </div>
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Situations queue"
        requestedScope={situationsCopilot.requestedScope}
        snapshot={situationsCopilot.snapshot}
        starterQuestions={situationsCopilot.starterQuestions}
      />
    </div>
  );
}
