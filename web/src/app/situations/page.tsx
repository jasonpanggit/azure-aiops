"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SituationTable } from "@/components/SituationTable";
import { SavedViews } from "@/components/SavedViews";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { useScope } from "@/lib/scope-context";
import { scopeToSearchParams } from "@/lib/scope";
import { downloadJson } from "@/lib/download-json";
import { situationsApi } from "@/lib/services";
import { buildSituationsCopilotContext } from "@/lib/copilot/page-adapters";
import { rankDurableSituations, type SituationPriority } from "@/lib/situations";
import type { DurableSituation, Envelope } from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

/** Triage queue for ranked, service-aware operational Situations. */
export default function SituationsPage() {
  return <Suspense fallback={null}><SituationsPageContent /></Suspense>;
}

function SituationsPageContent() {
  const { scope } = useScope();
  const params = useSearchParams();
  const router = useRouter();
  const urlQuery = (params.get("q") || "").slice(0, 256);
  const rawPriority = params.get("priority");
  const urlPriority = rawPriority === "P1" || rawPriority === "P2" || rawPriority === "P3" ? rawPriority : "all";
  const urlOwner = (params.get("assigned_owner") || "").slice(0, 256);
  const urlState = (params.get("lifecycle_state") || "").slice(0, 64);
  const rawAge = params.get("older_than_hours") || "";
  const urlAge = ["24", "168", "720"].includes(rawAge) ? rawAge : "";
  const rawSort = params.get("sort");
  const urlSort = rawSort === "oldest" || rawSort === "newest" ? rawSort : "default";
  const rawPage = Number(params.get("page") || 1);
  const urlPage = Number.isSafeInteger(rawPage) && rawPage > 0 && rawPage <= 4001 ? rawPage - 1 : 0;
  const [envelope, setEnvelope] = useState<Envelope<DurableSituation[]> | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState(urlQuery);
  const [priority, setPriority] = useState<"all" | SituationPriority>(urlPriority);
  const [page, setPage] = useState(urlPage);
  const [reloadRevision, setReloadRevision] = useState(0);
  const [owner, setOwner] = useState(urlOwner);
  const [lifecycleState, setLifecycleState] = useState(urlState);
  const [age, setAge] = useState(urlAge);
  const [sort, setSort] = useState<"default" | "oldest" | "newest">(urlSort);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState(false);
  const exportRequest = useRef(0);
  const previousScope = useRef(JSON.stringify(scope));
  const [copilotOpen, setCopilotOpen] = useState(false);

  useEffect(() => {
    setQuery(urlQuery); setPriority(urlPriority); setPage(urlPage);
    setOwner(urlOwner); setLifecycleState(urlState); setAge(urlAge); setSort(urlSort);
  }, [urlQuery, urlPriority, urlPage, urlOwner, urlState, urlAge, urlSort]);

  const updateView = useCallback((patch: Partial<{ query: string; priority: typeof priority; page: number; owner: string; lifecycleState: string; age: string; sort: typeof sort }>) => {
    const next = { query, priority, owner, lifecycleState, age, sort, page: 0, ...patch };
    setQuery(next.query); setPriority(next.priority); setPage(next.page);
    setOwner(next.owner); setLifecycleState(next.lifecycleState); setAge(next.age); setSort(next.sort);
    const saved = scopeToSearchParams(scope);
    if (next.query) saved.set("q", next.query);
    if (next.priority !== "all") saved.set("priority", next.priority);
    if (next.owner) saved.set("assigned_owner", next.owner);
    if (next.lifecycleState) saved.set("lifecycle_state", next.lifecycleState);
    if (next.age) saved.set("older_than_hours", next.age);
    if (next.sort !== "default") saved.set("sort", next.sort);
    if (next.page) saved.set("page", String(next.page + 1));
    const suffix = saved.toString();
    router.replace(`/situations${suffix ? `?${suffix}` : ""}`, { scroll: false });
  }, [scope, query, priority, owner, lifecycleState, age, sort, router]);

  useEffect(() => {
    const key = JSON.stringify(scope);
    if (previousScope.current !== key) {
      previousScope.current = key;
      updateView({ page: 0 });
    }
  }, [scope, updateView]);

  const viewKey = JSON.stringify({ scope, query, priority, page, owner, lifecycleState, age, sort, reloadRevision });
  useEffect(() => {
    exportRequest.current += 1;
    setSelectedIds(new Set()); setExportError(""); setExporting(false);
  }, [viewKey]);

  useEffect(() => {
    let active = true;
    setError("");
    setEnvelope(null);
    const args = [scope, query, priority === "all" ? "" : priority, page * 25, 25] as const;
    const request = owner || lifecycleState || age || sort !== "default"
      ? situationsApi.list(...args, { owner, lifecycle_state: lifecycleState, older_than_hours: age ? Number(age) : null, sort })
      : situationsApi.list(...args);
    request
      .then((result) => active && setEnvelope(result))
      .catch((reason: unknown) => active && setError(reason instanceof Error ? reason.message : "Situations are unavailable"));
    return () => {
      active = false;
    };
  }, [page, priority, query, scope, owner, lifecycleState, age, sort, reloadRevision]);

  const situations = useMemo(() => {
    const ranked = rankDurableSituations(envelope?.data ?? []);
    if (sort === "default") return ranked;
    const order = new Map((envelope?.data ?? []).map((row, index) => [row.situation_id, index]));
    return ranked.sort((a, b) => (order.get(a.id) ?? 0) - (order.get(b.id) ?? 0));
  }, [envelope, sort]);

  async function exportHandoff() {
    const id = ++exportRequest.current;
    setExporting(true); setExportError("");
    try {
      const result = await situationsApi.handoff(scope, (envelope?.data ?? [])
        .filter(row => selectedIds.has(row.situation_id))
        .map(row => ({ situation_id: row.situation_id, run_id: row.run_id })));
      if (id === exportRequest.current) downloadJson("situation-handoff.json", result.data);
    } catch (reason) {
      if (id === exportRequest.current) setExportError(reason instanceof Error ? reason.message : "Handoff export failed");
    } finally {
      if (id === exportRequest.current) setExporting(false);
    }
  }

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
            <span>{envelope?.data.length ?? 0} loaded in current scope</span>
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

      <SavedViews scope={scope} atFirstPage={page === 0} onRestoreCurrent={() => setReloadRevision(value => value + 1)} current={{
        kind: "situations", query, priority, assigned_owner: owner, lifecycle_state: lifecycleState,
        older_than_hours: age === "24" ? 24 : age === "168" ? 168 : age === "720" ? 720 : null, sort,
      }} />

      <div className="queue-toolbar situations-queue-toolbar">
        <label className="search-field">
          <span>Search situations</span>
          <input
            type="search"
            value={query}
            onChange={(event) => updateView({ query: event.target.value })}
            maxLength={256}
            placeholder="Service, application, owner, cause, or incident ID"
          />
        </label>
        <div className="segmented-control" aria-label="Priority filter">
          {(["all", "P1", "P2", "P3"] as const).map((value) => (
            <button
              type="button"
              key={value}
              className={priority === value ? "segmented-active" : ""}
              onClick={() => updateView({ priority: value })}
            >
              {value === "all" ? "All priorities" : value}
            </button>
          ))}
        </div>
        <label className="form-field"><span>Assigned owner</span><input className="form-control" value={owner} maxLength={256} onChange={event => updateView({ owner: event.target.value })} placeholder="Exact owner" /></label>
        <label className="form-field"><span>Lifecycle state</span><input className="form-control" value={lifecycleState} maxLength={64} onChange={event => updateView({ lifecycleState: event.target.value })} placeholder="Exact observed state" /></label>
        <label className="form-field"><span>Observed age</span><select className="form-control" value={age} onChange={event => updateView({ age: event.target.value })}>
          <option value="">Any age</option><option value="24">At least 24 hours</option><option value="168">At least 7 days</option><option value="720">At least 30 days</option>
        </select></label>
        <label className="form-field"><span>Queue order</span><select className="form-control" value={sort} onChange={event => updateView({ sort: event.target.value === "oldest" ? "oldest" : event.target.value === "newest" ? "newest" : "default" })}>
          <option value="default">Priority, then newest</option><option value="oldest">Oldest first</option><option value="newest">Newest first</option>
        </select></label>
      </div>
      <p>Bookmark the URL to restore this triage view. Age uses observed start timestamps, not an SLA deadline; overdue status requires sourced SLA evidence.</p>
      <button type="button" className="button" disabled={!selectedIds.size || exporting} onClick={() => void exportHandoff()}>
        {exporting ? "Exporting handoff..." : `Export selected handoff (${selectedIds.size}/25)`}
      </button>
      {exportError && <StatePanel title="Handoff export is unavailable" message={exportError} tone="error" />}

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
          title={query.trim() || priority !== "all" || owner || lifecycleState || age ? "No situations match these filters" : "No active situations in this scope"}
          message={
            query.trim() || priority !== "all" || owner || lifecycleState || age
              ? "Adjust the priority or search criteria. This result reflects the current operating scope."
              : "No durable situation records are currently available for the selected operating scope. This is not a source-health confirmation; review data coverage below."
          }
        />
      ) : (
        <div className="card queue-card">
          <SituationTable situations={situations} showFilters={false} paginate={false} selectedIds={selectedIds} onSelect={id => setSelectedIds(current => {
            const next = new Set(current);
            if (next.has(id)) next.delete(id);
            else if (next.size < 25) next.add(id);
            return next;
          })} />
          {envelope.pagination && (
            <div className="table-footer">
              Showing {envelope.pagination.total === 0 ? 0 : envelope.pagination.offset + 1}–
              {Math.min(envelope.pagination.offset + envelope.data.length, envelope.pagination.total)} of {envelope.pagination.total}
              <span className="table-footer-actions">
                <button type="button" className="button" disabled={page === 0} onClick={() => updateView({ page: Math.max(0, page - 1) })}>Previous</button>
                <button type="button" className="button" disabled={envelope.pagination.next_offset === null} onClick={() => updateView({ page: page + 1 })}>Next</button>
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
