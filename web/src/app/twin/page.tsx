"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { RiskGauge } from "@/components/ui/RiskGauge";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { EntityGraph } from "@/components/twin/EntityGraph";
import { RetainedSnapshots } from "@/components/twin/RetainedSnapshots";
import { useScope } from "@/lib/scope-context";
import { twinApi } from "@/lib/services";
import { buildTwinCopilotContext } from "@/lib/copilot/page-adapters";
import type {
  Envelope,
  TwinComparison,
  TwinExport,
  TwinScenarioResult,
  TwinSnapshot,
  TwinTraversal,
} from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

const SCENARIOS = [
  "firewall_failure",
  "route_change",
  "subscription_outage",
  "cve_exploitation",
  "patch_deployment",
  "architecture_remediation",
] as const;

function entityCount(snapshot: Envelope<TwinSnapshot> | null, kind: string): number {
  return snapshot?.data.entities.filter((entity) => entity.kind === kind).length ?? 0;
}

function riskScore(snapshot: Envelope<TwinSnapshot> | null): number | null {
  const point = snapshot?.data.temporal.risk_trend[0];
  return typeof point?.risk_score === "number" ? point.risk_score : null;
}

/** Current and historical operating-state twin for impact, scenario, and traversal analysis. */
export default function OperationalTwinPage() {
  const { scope } = useScope();
  const [snapshot, setSnapshot] = useState<Envelope<TwinSnapshot> | null>(null);
  const [comparison, setComparison] = useState<Envelope<TwinComparison> | null>(null);
  const [scenarioType, setScenarioType] = useState<(typeof SCENARIOS)[number]>("firewall_failure");
  const [scenario, setScenario] = useState<Envelope<TwinScenarioResult> | null>(null);
  const [traversal, setTraversal] = useState<Envelope<TwinTraversal> | null>(null);
  const [exported, setExported] = useState<Envelope<TwinExport> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [exportExpanded, setExportExpanded] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [detailErrors, setDetailErrors] = useState<string[]>([]);
  const [copyError, setCopyError] = useState("");
  const [selectedResourceId, setSelectedResourceId] = useState("");
  const loadedScope = useRef<typeof scope | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    loadedScope.current = null;
    setSnapshot(null);
    setSelectedResourceId("");
    setComparison(null);
    setScenario(null);
    setTraversal(null);
    setExported(null);
    setDetailErrors([]);
    setCopyError("");
    Promise.allSettled([twinApi.graph(scope), twinApi.compare(scope)]).then(([graphResult, compareResult]) => {
      if (!active) return;
      if (graphResult.status === "fulfilled") {
        loadedScope.current = scope;
        setSnapshot(graphResult.value);
      } else {
        setError(graphResult.reason instanceof Error ? graphResult.reason.message : "Unable to load operational twin");
      }
      if (compareResult.status === "fulfilled") setComparison(compareResult.value);
      else setDetailErrors(["Temporal comparison is unavailable."]);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [scope, refresh]);

  const resources = useMemo(() => snapshot?.data.entities.filter((entity) => entity.kind === "resource") ?? [], [snapshot]);
  const selectedResource = resources.some((entity) => entity.id === selectedResourceId)
    ? selectedResourceId.replace(/^resource:/, "") : "";

  useEffect(() => {
    let active = true;
    setScenario(null);
    setTraversal(null);
    if (!selectedResource || loadedScope.current !== scope) return;
    Promise.allSettled([
      twinApi.scenario(scenarioType, selectedResource, scope),
      twinApi.traverse(selectedResource, scope),
    ]).then(([scenarioResult, traversalResult]) => {
      if (!active) return;
      if (scenarioResult.status === "fulfilled") setScenario(scenarioResult.value);
      if (traversalResult.status === "fulfilled") setTraversal(traversalResult.value);
      const labels = ["Scenario analysis", "Business traversal"];
      const errors = [scenarioResult, traversalResult]
        .flatMap((result, index) => result.status === "rejected" ? [`${labels[index]} is unavailable.`] : []);
      setDetailErrors(current => [...current.filter(message => !message.startsWith("Scenario") && !message.startsWith("Business")), ...errors]);
    });
    return () => { active = false; };
  }, [scenarioType, scope, selectedResource]);

  useEffect(() => {
    let active = true;
    setExported(null);
    if (!snapshot || loadedScope.current !== scope) return;
    twinApi.export(scope).then(result => {
      if (active) setExported(result);
    }).catch(() => {
      if (active) setDetailErrors(current => [...current, "Twin export is unavailable."]);
    });
    return () => { active = false; };
  }, [snapshot, scope]);

  const observedRisk = snapshot?.source_status?.live_operational_sources === "unavailable"
    ? null
    : riskScore(snapshot);

  // Read-only contextual Copilot over the already-loaded request-time twin.
  // Entity/relationship/temporal/scenario/traversal identities keep provenance
  // and bounds; unsupported edges and historical evidence stay uncertain rather
  // than asserted; no row carries mutation authority (D-03, D-04, D-08, D-09).
  const twinData = snapshot?.data ?? null;
  const twinAvailable = !error && Boolean(snapshot);
  const twinCopilot = buildTwinCopilotContext({
    scope,
    twinId: twinData?.twin_id ?? "operational-twin",
    version: twinData?.version,
    previousVersion: twinData?.previous_version,
    observedAt: twinData?.observed_at,
    liveObservedAt: snapshot?.live_observed_at,
    confidence: twinData?.confidence,
    riskScore: observedRisk,
    entities: (twinData?.entities ?? []).map((entity) => {
      const properties = entity.properties ?? {};
      const resourceId = typeof properties.resource_id === "string" ? properties.resource_id : undefined;
      const businessService = typeof properties.business_service === "string" ? properties.business_service : undefined;
      return {
        id: entity.id,
        kind: entity.kind,
        name: entity.name,
        version: entity.version,
        state: entity.state,
        confidence: entity.confidence,
        business_service: businessService,
        resource_id: resourceId,
      };
    }),
    entitiesTotal: twinData?.entities.length ?? 0,
    relationships: (twinData?.relationships ?? []).map((relationship) => ({
      id: relationship.id,
      source: relationship.source,
      target: relationship.target,
      type: relationship.type,
      confidence: relationship.confidence,
    })),
    relationshipsTotal: twinData?.relationships.length ?? 0,
    timeline: (twinData?.timeline ?? []).map((event) => ({
      timestamp: event.timestamp,
      type: event.type,
      entity: event.entity,
      summary: event.summary,
    })),
    timelineTotal: twinData?.timeline.length ?? 0,
    traversal: traversal
      ? {
          resource_id: traversal.data.resource_id,
          path: traversal.data.path.map((entity) => ({ id: entity.id, kind: entity.kind, name: entity.name })),
          business_consequence: traversal.data.business_consequence,
        }
      : null,
    scenario: scenario
      ? {
          scenario: scenario.data.scenario,
          target: scenario.data.target,
          likely_impact: scenario.data.likely_impact,
          risk_delta: scenario.data.risk_delta,
          analysis_kind: scenario.data.analysis_kind,
          truncated: scenario.data.truncated,
          impacted_count: scenario.data.impacted_total,
          assumptions: scenario.data.assumptions,
        }
      : null,
    selectedResourceId: selectedResource || null,
    available: twinAvailable,
    freshness: twinAvailable ? "fresh" : "unavailable",
    staleTemporalEvidence: comparison?.data.previous_version
      ? [`previous revision ${comparison.data.previous_version}`]
      : [],
    sourceStatus: snapshot?.source_status,
    evidence: snapshot?.evidence ?? [],
  });

  return (
    <main className="page-container operational-page twin-workspace" aria-label="Operational Digital Twin">
      <PageHeader
        eyebrow="Operational Digital Twin"
        title="Review mapped operational dependencies"
        description="A request-time composition of semantic relationships, topology, vulnerabilities, incidents and remediation candidates. Observation events are not proof of changes or outcomes."
        actions={
          <div className="twin-header-actions" aria-label="Twin actions">
            <CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about the twin" />
            <button className="button" type="button" disabled={loading} onClick={() => setRefresh(current => current + 1)}>
              Refresh current state
            </button>
            <button
              className="button"
              type="button"
              disabled={loading || !snapshot}
              onClick={async () => {
                setCopyError("");
                const payload = JSON.stringify(exported?.data ?? snapshot?.data ?? {}, null, 2);
                try {
                  if (!navigator.clipboard) throw new Error("Clipboard is unavailable in this browser.");
                  await navigator.clipboard.writeText(payload);
                } catch (reason) {
                  setCopyError(reason instanceof Error ? reason.message : "Unable to copy twin export.");
                }
              }}
            >
              Copy export
            </button>
          </div>
        }
      />

      <nav className="section-nav" aria-label="Twin sections">
        <a href="#twin-model">Twin model</a>
        <a href="#twin-traversal">Business impact</a>
        <a href="#twin-temporal">Observation timeline</a>
        <a href="#twin-scenario">Scenario review</a>
        <a href="#twin-dependencies">Current dependencies</a>
        <a href="#twin-export">Export</a>
      </nav>

      {error ? <StatePanel title="Twin unavailable" message={error} tone="error" /> : null}
      {detailErrors.length ? <StatePanel title="Some twin evidence is unavailable" message={detailErrors.join(" ")} tone="error" /> : null}
      {copyError ? <StatePanel title="Export not copied" message={copyError} tone="error" /> : null}
      {loading ? <StatePanel title="Loading twin" message="Composing live operational state with semantic graph context." tone="loading" /> : null}
      {snapshot ? (
        <EvidenceBar
          evidence={snapshot.evidence}
          knowledgeVersion={snapshot.knowledge_version}
          warnings={snapshot.warnings}
          liveObservedAt={snapshot.live_observed_at}
          sourceStatus={snapshot.source_status}
        />
      ) : null}

      <div className="predeploy-summary">
        <section className="card">
          <div className="card-header">
            <h2>Heuristic current index</h2>
          </div>
          <div className="card-body twin-current-index">
            {observedRisk === null ? <p className="muted">Risk evidence unavailable; no healthy score is asserted.</p> : <RiskGauge score={observedRisk} label="Heuristic index" detail="Not measured risk or reliability" />}
            <p className="muted">min(100, critical vulnerabilities × 20 + visible incidents × 12). A single current index is not a historical trend.</p>
          </div>
        </section>
        <section className="metric-grid" aria-label="Twin summary">
          <MetricCard label="Entities" value={snapshot?.data.entities.length ?? 0} detail="Canonical current-state nodes" />
          <MetricCard label="Dependencies" value={snapshot?.data.relationships.length ?? 0} detail="Semantic and topology links" />
          <MetricCard label="Observations" value={snapshot?.data.timeline.length ?? "—"} detail="Events, not verified changes" />
        </section>
      </div>

      {snapshot ? <EntityGraph key={snapshot.data.version} snapshot={snapshot.data} onSelectResource={setSelectedResourceId} /> : null}
      <RetainedSnapshots scope={scope} />

      <section className="workspace-grid twin-grid">
        <section id="twin-model" className="card">
          <div className="card-header"><div><h2>Twin model</h2><p>Canonical entities, relationships, versions, provenance, and confidence.</p></div><StatusBadge label={`${snapshot?.data.confidence ?? "unknown"} confidence`} tone={statusTone(snapshot?.data.confidence)} /></div>
          <div className="card-body">
          <label>
            Resource for impact analysis
            <select value={selectedResourceId} disabled={loading || resources.length === 0} onChange={(event) => setSelectedResourceId(event.target.value)}>
              <option value="">Select a resource</option>
              {resources.map(resource => <option key={resource.id} value={resource.id}>{resource.name} ({resource.id.replace(/^resource:/, "")})</option>)}
            </select>
          </label>
          <p className="muted">Choose an observed resource for traversal and hypothetical review. No resource is selected automatically.</p>
          <div className="entity-pill-row" aria-label="Twin entity counts">
            {["business_service", "application", "environment", "subscription", "resource", "vulnerability", "incident", "remediation", "owner"].map((kind) => (
              <span key={kind} className="entity-pill">
                {kind.replace("_", " ")} <strong>{entityCount(snapshot, kind)}</strong>
              </span>
            ))}
          </div>
          <p className="muted">
            Version {snapshot?.data.version ?? "unknown"} is derived at request time; AIOps supplies the semantic model while operational state remains live.
          </p>
          </div>
        </section>

        <section id="twin-traversal" className="card">
          <div className="card-header"><div><h2>Business impact traversal</h2><p>Resource to application, service, owner, and consequence.</p></div></div>
          <div className="card-body">
          {traversal ? (
            <>
              <p className="panel-lead">{traversal.data.resource_id}</p>
              <ol className="timeline-list">
                {traversal.data.path.map((entity) => (
                  <li key={entity.id}>
                    <strong>{entity.kind.replace("_", " ")}</strong>
                    <span>{entity.name}</span>
                  </li>
                ))}
              </ol>
              <p className="muted">Consequence: {traversal.data.business_consequence.join(" -> ")}</p>
            </>
          ) : (
            <p className="muted">{selectedResource ? "No resource traversal is available for this selection." : "Select a resource to inspect business impact."}</p>
          )}
          </div>
        </section>

        <section id="twin-scenario" className="card">
          <div className="card-header"><div><h2>Scenario review</h2><p>Hypothetical dependency review, not failure simulation or deployment authority.</p></div></div>
          <div className="card-body">
          <label className="field-label" htmlFor="scenario">
            Scenario
          </label>
          <select id="scenario" value={scenarioType} disabled={!selectedResource} onChange={(event) => setScenarioType(event.target.value as (typeof SCENARIOS)[number])}>
            {SCENARIOS.map((item) => (
              <option key={item} value={item}>
                {item.replaceAll("_", " ")}
              </option>
            ))}
          </select>
          <p className="panel-lead">{scenario?.data.likely_impact ?? "Select a resource and scenario to review mapped dependencies."}</p>
          <div className="split-kpis">
            <MetricCard label="Measured risk delta" value="—" detail="Not established by mapped links" />
            <MetricCard label="Related entities" value={scenario?.data.impacted_total ?? "—"} detail="Bounded mapped associations" />
          </div>
          {scenario ? <>
            <p className="muted">{scenario.data.truncated ? "Partial projection: traversal or display bounds reached." : "Within the disclosed traversal bounds."} Showing {scenario.data.impacted_entities.length} of {scenario.data.impacted_total} discovered entities.</p>
            <ul>{scenario.data.assumptions.map(assumption => <li key={assumption}>{assumption}</li>)}</ul>
          </> : null}
          </div>
        </section>

        <section id="twin-temporal" className="card">
          <div className="card-header"><div><h2>Observation timeline</h2><p>Source events and request-time observations; no inferred revision history.</p></div></div>
          <div className="card-body">
          <p className="panel-lead">{comparison?.data.summary ?? "No comparison loaded."}</p>
          <ol className="timeline-list">
            {(snapshot?.data.timeline ?? []).slice(0, 6).map((event, index) => (
              <li key={`${event.type}-${event.timestamp}-${index}`}>
                <strong>{event.type.replaceAll("_", " ")}</strong>
                <span>{event.summary}</span>
                <small>{event.timestamp}</small>
              </li>
            ))}
          </ol>
          </div>
        </section>

        <section id="twin-dependencies" className="card">
          <div className="card-header"><div><h2>Current dependencies</h2><p>Observed relationship counts. No historical counts are inferred.</p></div></div>
          <div className="card-body">
          <div className="compact-table" role="table" aria-label="Dependency evolution">
            {(snapshot?.data.temporal.dependency_evolution ?? []).slice(0, 8).map((row) => (
              <div className="compact-row" role="row" key={String(row.relationship_type)}>
                <span>{String(row.relationship_type).replaceAll("_", " ")}</span>
                <strong>{String(row.current_count)} current</strong>
                <small>Prior count unavailable</small>
              </div>
            ))}
          </div>
          </div>
        </section>

        <section className="card">
          <div className="card-header"><div><h2>Copilot grounding context</h2><p>Time-aware questions agents can answer from the twin.</p></div></div>
          <div className="card-body">
          <details className="source-section-details">
          <summary>View suggested questions</summary>
          <div className="recommended-action-list">
            {[
              "Which business services are affected if this route changes?",
              "What changed since the previous twin revision?",
              "Simulate CVE exploitation for internet-reachable resources.",
              "Draft a validation checklist for the selected remediation.",
            ].map((question) => (
              <span key={question}>{question}</span>
            ))}
          </div>
          </details>
          </div>
        </section>
      </section>

      <section className="workspace-grid">
        <section id="twin-export" className="card">
          <div className="card-header"><div><h2>Raw twin export</h2><p>Serializable twin state for audit, API consumers, and Copilot tooling.</p></div></div>
          <div className="card-body">
            <details className="twin-export-details" open={exportExpanded} onToggle={(event) => setExportExpanded(event.currentTarget.open)}>
              <summary>Inspect full twin export</summary>
              {exportExpanded && <div className="twin-export-data" tabIndex={0} role="region" aria-label="Raw twin export"><StructuredData value={exported?.data ?? snapshot?.data ?? {}} /></div>}
            </details>
          </div>
        </section>
      </section>

      <CopilotInsights
        snapshot={twinCopilot.snapshot}
        ready={!loading}
        requestedScope={twinCopilot.requestedScope}
        contextLabel="Operational twin"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Operational twin"
        requestedScope={twinCopilot.requestedScope}
        snapshot={twinCopilot.snapshot}
        starterQuestions={twinCopilot.starterQuestions}
      />
    </main>
  );
}
