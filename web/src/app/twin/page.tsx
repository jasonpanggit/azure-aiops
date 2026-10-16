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

function firstResource(snapshot: Envelope<TwinSnapshot> | null): string {
  const resource = snapshot?.data.entities.find((entity) => entity.kind === "resource");
  return resource?.id.replace(/^resource:/, "") ?? "";
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
  const [refresh, setRefresh] = useState(0);
  const [detailErrors, setDetailErrors] = useState<string[]>([]);
  const [copyError, setCopyError] = useState("");
  const loadedScope = useRef<typeof scope | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    loadedScope.current = null;
    setSnapshot(null);
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

  const selectedResource = useMemo(() => firstResource(snapshot), [snapshot]);

  useEffect(() => {
    if (!selectedResource || loadedScope.current !== scope) return;
    let active = true;
    setScenario(null);
    setTraversal(null);
    setExported(null);
    Promise.allSettled([
      twinApi.scenario(scenarioType, selectedResource, scope),
      twinApi.traverse(selectedResource, scope),
      twinApi.export(scope),
    ]).then(([scenarioResult, traversalResult, exportResult]) => {
      if (!active) return;
      if (scenarioResult.status === "fulfilled") setScenario(scenarioResult.value);
      if (traversalResult.status === "fulfilled") setTraversal(traversalResult.value);
      if (exportResult.status === "fulfilled") setExported(exportResult.value);
      const labels = ["Scenario analysis", "Business traversal", "Twin export"];
      const errors = [scenarioResult, traversalResult, exportResult]
        .flatMap((result, index) => result.status === "rejected" ? [`${labels[index]} is unavailable.`] : []);
      setDetailErrors(current => [...current.filter(message => message.startsWith("Temporal")), ...errors]);
    });
    return () => {
      active = false;
    };
  }, [scenarioType, scope, selectedResource]);

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
          impacted_count: scenario.data.impacted_entities.length,
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
    <main className="page-container twin-workspace" aria-label="Operational Digital Twin">
      <PageHeader
        eyebrow="Operational Digital Twin"
        title="Current and historical model of operational reality"
        description="A request-time twin that connects semantic relationships with live topology, vulnerabilities, incidents, and governed remediation outcomes."
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

      <CopilotInsights
        snapshot={twinCopilot.snapshot}
        ready={!loading}
        requestedScope={twinCopilot.requestedScope}
        contextLabel="Operational twin"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

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
            <h2>Risk trend</h2>
          </div>
          <div className="card-body risk-gauge-body">
            {observedRisk === null ? <p className="muted">Risk evidence unavailable; no healthy score is asserted.</p> : <RiskGauge score={observedRisk} label="Scenario-weighted risk" detail="Current twin risk signal" />}
          </div>
        </section>
        <section className="metric-grid" aria-label="Twin summary">
          <MetricCard label="Entities" value={snapshot?.data.entities.length ?? 0} detail="Canonical current-state nodes" />
          <MetricCard label="Dependencies" value={snapshot?.data.relationships.length ?? 0} detail="Semantic and topology links" />
          <MetricCard label="Changes" value={snapshot?.data.temporal.change_history.length ?? 0} detail="Temporal events in the latest revision" />
        </section>
      </div>

      <section className="workspace-grid twin-grid">
        <section className="card">
          <div className="card-header"><div><h2>Twin model</h2><p>Canonical entities, relationships, versions, provenance, and confidence.</p></div><StatusBadge label={`${snapshot?.data.confidence ?? "unknown"} confidence`} tone={statusTone(snapshot?.data.confidence)} /></div>
          <div className="card-body">
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

        <section className="card">
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
            <p className="muted">No resource traversal is available for the current scope.</p>
          )}
          </div>
        </section>

        <section className="card">
          <div className="card-header"><div><h2>Temporal view</h2><p>Current state, previous revision, change history, and risk trend.</p></div></div>
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

        <section className="card">
          <div className="card-header"><div><h2>Scenario analysis</h2><p>Impact of failure, exploitation, patching, and architecture changes.</p></div></div>
          <div className="card-body">
          <label className="field-label" htmlFor="scenario">
            Scenario
          </label>
          <select id="scenario" value={scenarioType} onChange={(event) => setScenarioType(event.target.value as (typeof SCENARIOS)[number])}>
            {SCENARIOS.map((item) => (
              <option key={item} value={item}>
                {item.replaceAll("_", " ")}
              </option>
            ))}
          </select>
          <p className="panel-lead">{scenario?.data.likely_impact ?? "Select a scenario to estimate impact."}</p>
          <div className="split-kpis">
            <MetricCard label="Risk delta" value={scenario?.data.risk_delta ?? "—"} detail="Estimated change" />
            <MetricCard label="Impacted" value={scenario?.data.impacted_entities.length ?? "—"} detail="Related twin entities" />
          </div>
          </div>
        </section>

        <section className="card">
          <div className="card-header"><div><h2>Dependency evolution</h2><p>Relationship count changes by dependency type.</p></div></div>
          <div className="card-body">
          <div className="compact-table" role="table" aria-label="Dependency evolution">
            {(snapshot?.data.temporal.dependency_evolution ?? []).slice(0, 8).map((row) => (
              <div className="compact-row" role="row" key={String(row.relationship_type)}>
                <span>{String(row.relationship_type).replaceAll("_", " ")}</span>
                <strong>{String(row.current_count)} current</strong>
                <small>{String(row.previous_count)} prior</small>
              </div>
            ))}
          </div>
          </div>
        </section>

        <section className="card">
          <div className="card-header"><div><h2>Copilot grounding context</h2><p>Time-aware questions agents can answer from the twin.</p></div></div>
          <div className="card-body">
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
          </div>
        </section>
      </section>

      <section className="workspace-grid">
        <section className="card">
          <div className="card-header"><div><h2>Raw twin export</h2><p>Serializable twin state for audit, API consumers, and Copilot tooling.</p></div></div>
          <div className="card-body">
          <StructuredData value={exported?.data ?? snapshot?.data ?? {}} />
          </div>
        </section>
      </section>

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
