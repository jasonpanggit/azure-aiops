"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { formatDateTime } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { situationsApi } from "@/lib/services";
import { buildSituationDetailCopilotContext } from "@/lib/copilot/page-adapters";
import type {
  DurableEvidence,
  DurableSituation,
  Envelope,
  SituationAuditEvent,
} from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";
import { SituationHandoverNotes } from "@/components/SituationHandoverNotes";
import { SituationEvidenceTimeline } from "@/components/SituationEvidenceTimeline";
import { situationEntityHref } from "@/lib/situations";

function allEvidence(situation: DurableSituation): DurableEvidence[] {
  return situation.evidence ?? [];
}

function linkedEntities(situation: DurableSituation) {
  return situation.links ?? [];
}

export default function SituationDetailPage({ params }: { params: { id: string } }) {
  const { scope } = useScope();
  return <SituationDetailContent key={`${JSON.stringify(scope)}:${params.id}`} situationId={params.id} />;
}

function SituationDetailContent({ situationId }: { situationId: string }) {
  const { scope } = useScope();
  const [situation, setSituation] = useState<Envelope<DurableSituation> | null>(null);
  const [audit, setAudit] = useState<Envelope<SituationAuditEvent[]> | null>(null);
  const [auditError, setAuditError] = useState("");
  const [error, setError] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState<DurableEvidence | null>(null);
  const [saved, setSaved] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const lastTrigger = useRef<HTMLButtonElement | null>(null);
  const drawer = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let active = true;
    setSituation(null);
    setAudit(null);
    setAuditError("");
    setError("");
    setSelectedEvidence(null);
    setSaved(false);
    Promise.allSettled([situationsApi.get(situationId, scope), situationsApi.audit(situationId, scope)])
      .then(([detail, events]) => {
        if (!active) return;
        if (detail.status === "rejected") {
          setError(detail.reason instanceof Error ? detail.reason.message : "Situation unavailable");
          return;
        }
        setSituation(detail.value);
        if (events.status === "fulfilled") {
          setAudit(events.value);
        } else {
          setAuditError(events.reason instanceof Error ? events.reason.message : "Audit service unavailable");
        }
      });
    return () => {
      active = false;
    };
  }, [scope, situationId]);

  useEffect(() => {
    if (!selectedEvidence) {
      lastTrigger.current?.focus();
      return;
    }
    drawer.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedEvidence(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedEvidence]);

  if (error) {
    return (
      <div className="page-container">
        <StatePanel
          title="Situation could not be opened"
          message={`${error}. Confirm the Situation is still visible in the current operating scope.`}
          tone="error"
          action={<Link className="button" href="/situations">Return to queue</Link>}
        />
      </div>
    );
  }

  if (!situation) {
    return (
      <div className="page-container">
        <StatePanel title="Loading Situation detail" message="Reading the durable situation record and service audit history." tone="loading" />
      </div>
    );
  }

  const record = situation.data;
  const evidence = allEvidence(record);
  const links = linkedEntities(record);
  const conflicts = evidence.filter((item) => item.quality === "contradictory");
  const latest = [...evidence].sort((left, right) => right.observed_at.localeCompare(left.observed_at))[0];
  const grouped = evidence.reduce<Record<string, DurableEvidence[]>>((groups, item) => {
    (groups[item.source_family] ??= []).push(item);
    return groups;
  }, {});
  const saveView = () => {
    window.localStorage.setItem(`aiops.situation-view.${record.situation_id}`, JSON.stringify({ scope, savedAt: new Date().toISOString() }));
    setSaved(true);
  };

  // Read-only contextual Copilot over the already-loaded durable brief. Timeline,
  // evidence/source trust, affected ARM resources, links, and the selected
  // situation identity stay bound; every row is non-actionable (D-03, D-08).
  const situationCopilot = buildSituationDetailCopilotContext({
    scope,
    situationId: record.situation_id,
    situation: {
      situation_id: record.situation_id,
      title: record.title,
      severity: record.severity,
      priority: record.priority,
      lifecycle_state: record.lifecycle_state,
      situation_type: record.situation_type,
      owner: record.owner,
      support_team: record.support_team,
      evidence_state: record.evidence_state,
      affected_resource_ids: record.affected_resource_ids,
      unknowns: record.unknowns,
      started_at: record.started_at,
      last_observed_at: record.last_observed_at,
    },
    evidence: evidence.map((item) => ({
      evidence_id: item.evidence_id,
      source_family: item.source_family,
      source_object_id: item.source_object_id,
      assertion: item.assertion,
      quality: item.quality,
      availability: item.availability,
      freshness: item.freshness,
      observed_at: item.observed_at,
      resource_ids: item.resource_ids,
    })),
    links: links.map((link) => ({
      link_id: link.link_id,
      entity_type: link.entity_type,
      entity_id: link.entity_id,
      relation: link.relation,
      quality: link.quality,
    })),
    sourceStatuses: (record.source_status ?? []).map((status) => ({
      source_family: status.source_family,
      availability: status.availability,
      freshness: status.freshness,
      observed_at: status.observed_at,
    })),
    auditEvents: (audit?.data ?? []).map((event) => ({
      event_id: event.event_id,
      actor: event.actor,
      action: event.action,
      timestamp: event.timestamp,
    })),
    auditAvailable: !auditError && audit != null,
    available: true,
    observedAt: record.last_observed_at,
    citations: situation.evidence ?? [],
  });

  return (
    <div className="page-container investigation-page">
      <div className="breadcrumb">
        <Link href="/situations">Situations</Link><span>/</span><code>{record.situation_id}</code>
      </div>
      <PageHeader
        eyebrow="Durable situation brief"
        title={record.title}
        description="Evidence-backed, authorized operational context. Source records remain read-only; handover annotations are governed separately."
        actions={
          <>
            <CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about this situation" />
            <button type="button" className="button" onClick={saveView}>Save view locally</button>
          </>
        }
        metadata={
          <>
            <StatusBadge label={record.lifecycle_state} tone={statusTone(record.lifecycle_state)} />
            <StatusBadge label={record.severity} tone={statusTone(record.severity)} />
            <StatusBadge label={record.priority} tone={statusTone(record.priority)} />
            <span>Owner: {record.owner || "Unassigned"}</span>
            {saved && <span role="status">Local view saved</span>}
          </>
        }
      />

      <CopilotInsights
        snapshot={situationCopilot.snapshot}
        requestedScope={situationCopilot.requestedScope}
        contextLabel={record.title || record.situation_id}
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      <section className="card" aria-label="Situation identity">
        <div className="card-body command-grid">
          <span>Situation ID <code tabIndex={0}>{record.situation_id}</code></span>
          <span>Scope <strong>{Object.entries(record.scope).map(([key, values]) => `${key}: ${values.join(", ")}`).join(" · ") || "Authorized scope"}</strong></span>
          <span>Started <time dateTime={record.started_at}>{formatDateTime(record.started_at)}</time></span>
          <span>Last observed <time dateTime={record.last_observed_at}>{formatDateTime(record.last_observed_at)}</time></span>
          <span>Affected resources <strong>{record.affected_resource_ids.length}</strong></span>
          <span>Read-only handoff <strong>View future-phase candidate</strong></span>
        </div>
      </section>

      <EvidenceBar
        durableEvidence={evidence}
        durableSourceStatus={record.source_status ?? []}
        warnings={record.warnings}
      />

      <section className="answer-grid" aria-label="Situation summary">
        <article className="answer-card answer-critical">
          <h2>What failed?</h2>
          <strong>{record.evidence_state === "contradictory" ? "Evidence conflicts" : record.evidence_state}</strong>
          <p>{record.warnings[0] ?? "No definitive failure has been asserted by the authorized evidence."}</p>
        </article>
        <article className="answer-card answer-high">
          <h2>What is at risk?</h2>
          <strong>{record.affected_resource_ids.length} affected resource{record.affected_resource_ids.length === 1 ? "" : "s"}</strong>
          <p>{record.owner || "Ownership is not assigned."}</p>
        </article>
        <article className="answer-card">
          <h2>What changed?</h2>
          <strong>{latest?.assertion || "No change assertion available"}</strong>
          <p>{latest ? `${latest.source_family} · ${formatDateTime(latest.observed_at)}` : "No evidence is available."}</p>
        </article>
      </section>

      {conflicts.length > 0 && (
        <section className="card callout callout-warning" aria-labelledby="conflicts-heading">
          <h2 id="conflicts-heading">Evidence conflicts</h2>
          <p>Evidence conflicts — review the source records before drawing a conclusion.</p>
          <p>{conflicts.length} contradictory source record{conflicts.length === 1 ? "" : "s"} remain visible.</p>
        </section>
      )}
      {record.unknowns.length > 0 && (
        <section className="card" aria-labelledby="unknown-heading">
          <h2 id="unknown-heading">What is not known</h2>
          <ul>{record.unknowns.map((unknown) => <li key={unknown}>{unknown}</li>)}</ul>
        </section>
      )}

      <section className="card" aria-labelledby="evidence-heading">
        <div className="card-header"><div><h2 id="evidence-heading">Evidence by source</h2><p>Every row retains source identity, provenance, freshness, quality, and ingestion facts.</p></div></div>
        <div className="card-body reasoning-stack">
          {Object.entries(grouped).map(([source, rows]) => (
            <section key={source} aria-labelledby={`source-${source}`}>
              <h3 id={`source-${source}`}>{source}</h3>
              {rows.map((item) => (
                <div className="reasoning-card" key={item.evidence_id}>
                  <strong>{item.assertion || item.source_object_id}</strong>
                  <span>{item.source_object_id} · {item.quality} · {item.availability} · {item.freshness} · {item.ingestion_status}</span>
                  <button type="button" className="button" onClick={(event) => { lastTrigger.current = event.currentTarget; setSelectedEvidence(item); }}>
                    View evidence details
                  </button>
                </div>
              ))}
            </section>
          ))}
          {evidence.length === 0 && <p>No evidence is visible in this scope.</p>}
        </div>
      </section>

      <section className="card" aria-labelledby="links-heading">
        <div className="card-header"><div><h2 id="links-heading">Linked entities</h2><p>Bounded links are labelled and retain unresolved quality.</p></div></div>
        <div className="card-body">
          <ul>{links.map(link => {
            const href = situationEntityHref(link, scope);
            return <li key={link.link_id}><strong>{link.entity_type}</strong> <code>{link.entity_id}</code> · {link.relation} · {link.quality}
              {href ? <> · <Link href={href}>Open {link.entity_type} context</Link></>
                : <span> · No verified supported destination</span>}
            </li>;
          })}</ul>
          {links.length === 0 && <p>No linked entities are visible in this scope.</p>}
        </div>
      </section>

      <SituationHandoverNotes key={`notes:${JSON.stringify(scope)}:${record.situation_id}:${record.run_id}`}
        scope={scope} situationId={record.situation_id} evidenceRunId={record.run_id} />
      <SituationEvidenceTimeline key={`timeline:${JSON.stringify(scope)}:${record.situation_id}:${record.run_id}`} evidence={evidence} />

      <section className="card audit-boundary" aria-labelledby="audit-heading">
        <div className="card-header"><div><h2 id="audit-heading">Audit history</h2><p>Source events recorded by the service. Handover annotations have their own server-attributed revision history; “Save view locally” stores only navigation preferences.</p></div></div>
        <div className="card-body">
        {auditError ? <p>Audit history unavailable from the service</p> : audit?.data.length ? audit.data.map((event) => (
            <article className="reasoning-card" key={event.event_id}>
              <strong>Recorded event · {event.action}</strong>
              <span>Event ID: <code>{event.event_id}</code> · Actor: {event.actor} · {formatDateTime(event.timestamp)}</span>
              <span>Scope snapshot: {JSON.stringify(event.scope_snapshot)} · Evidence: {event.evidence_ids.join(", ") || "none"} · Sources: {event.source_references.join(", ") || "none"}</span>
            </article>
          )) : <p>No audit events are visible in this scope.</p>}
        </div>
      </section>

      {selectedEvidence && (
        <aside className="card" aria-label="Evidence detail drawer" tabIndex={-1} ref={drawer}>
          <div className="card-header"><div><h2>Evidence detail</h2><p>Source and trust facts for operator review.</p></div><button type="button" className="button" onClick={() => setSelectedEvidence(null)}>Close</button></div>
          <div className="card-body">
            <dl>
              <dt>Source family/object ID</dt><dd>{selectedEvidence.source_family} / {selectedEvidence.source_object_id}</dd>
              <dt>Locator</dt><dd>{selectedEvidence.locator || "Source locator unavailable"}</dd>
              <dt>Observed / ingested</dt><dd>{selectedEvidence.observed_at} / {selectedEvidence.ingested_at}</dd>
              <dt>Watermark / status</dt><dd>{selectedEvidence.watermark || "unknown"} / {selectedEvidence.ingestion_status}</dd>
              <dt>Provenance / quality</dt><dd>{JSON.stringify(selectedEvidence.provenance)} / {selectedEvidence.quality}</dd>
              <dt>Availability / freshness / confidence</dt><dd>{selectedEvidence.availability} / {selectedEvidence.freshness} / {selectedEvidence.confidence}</dd>
            </dl>
          </div>
        </aside>
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel={record.title || record.situation_id}
        requestedScope={situationCopilot.requestedScope}
        snapshot={situationCopilot.snapshot}
        starterQuestions={situationCopilot.starterQuestions}
      />
    </div>
  );
}
