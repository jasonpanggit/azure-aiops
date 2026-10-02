"use client";

import Link from "next/link";
import { useState } from "react";

import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { buildChangesCopilotContext } from "@/lib/copilot/page-adapters";
import { formatDateTime, relativeTime, titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { operationsApi } from "@/lib/services";
import type { IncidentTimelineEvent } from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

function sourceLink(event: IncidentTimelineEvent): string | null {
  for (const key of ["source_url", "source_link", "deep_link", "url"]) {
    const value = event[key];
    if (typeof value === "string" && /^https?:\/\//.test(value)) return value;
  }
  return null;
}

/** Correlated change stream extracted from active Situation timelines. */
export default function ChangesPage() {
  const { scope } = useScope();
  const [copilotOpen, setCopilotOpen] = useState(false);
  const incidents = useApi(() => operationsApi.incidents(scope), [scope]);
  const changes = (incidents.data?.data.incidents ?? [])
    .flatMap((entry) =>
      entry.timeline
        .filter((event) => event.event_type.toLowerCase().includes("change"))
        .map((event) => ({ event, incident: entry.incident, services: entry.blast_radius.business_services }))
    )
    .sort((left, right) => Date.parse(right.event.timestamp) - Date.parse(left.event.timestamp));

  // Read-only contextual Copilot over the already-loaded correlation stream.
  // Correlation is advisory and never causal; no mutation authority (D-03, D-08, D-10).
  const changesCopilot = buildChangesCopilotContext({
    scope,
    changes: changes.map(({ event, incident, services }) => ({
      event_id: event.event_id,
      incident_id: incident.incident_id,
      incident_title: incident.title,
      event_type: event.event_type,
      summary: event.summary,
      source: event.source,
      timestamp: event.timestamp,
      business_services: services,
    })),
    loadedCount: changes.length,
    totalCount: changes.length,
    available: !incidents.error && Boolean(incidents.data),
    freshness: incidents.error || !incidents.data ? "unavailable" : "fresh",
    observedAt: incidents.data?.evidence?.[0]?.timestamp,
    evidence: incidents.data?.evidence ?? [],
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Change intelligence"
        title="What changed near active situations?"
        description="Review source events in temporal proximity to authorized situations. Proximity is a correlation signal, not a causal conclusion."
        metadata={<><span>{changes.length} correlated changes</span><span>Correlation is not confirmation</span></>}
        actions={
          <>
            <CopilotDrawerButton
              onClick={() => setCopilotOpen(true)}
              label="Ask Copilot about changes"
            />
            <Link className="button button-secondary" href="/changes/predeploy">Assess a proposed change</Link>
          </>
        }
      />

      <CopilotInsights
        snapshot={changesCopilot.snapshot}
        ready={!incidents.loading}
        requestedScope={changesCopilot.requestedScope}
        contextLabel="Change intelligence"
        onOpenCopilot={() => setCopilotOpen(true)}
      />
      <EvidenceBar evidence={incidents.data?.evidence} knowledgeVersion={incidents.data?.knowledge_version} warnings={incidents.data?.warnings} />
      {incidents.error ? (
        <StatePanel title="Change intelligence is unavailable" message={incidents.error.message} tone="error" />
      ) : incidents.loading ? (
        <StatePanel title="Correlating changes" message="Aligning observed changes to Situation timelines." tone="loading" />
      ) : changes.length === 0 ? (
        <StatePanel title="No correlated changes" message="No change events are linked to active Situations in this scope." />
      ) : (
        <div className="card timeline-card changes-timeline">
          <div className="card-body timeline">
            {changes.map(({ event, incident, services }) => (
              <div className="timeline-event" key={`${incident.incident_id}-${event.event_id}`}>
                <div className="timeline-marker" aria-hidden="true" />
                <time dateTime={event.timestamp} title={formatDateTime(event.timestamp)}>{relativeTime(event.timestamp)}<span className="timeline-exact-time">{formatDateTime(event.timestamp)}</span></time>
                <div>
                  <div className="timeline-event-labels">
                    <StatusBadge label={titleize(event.event_type)} tone="info" compact />
                    <StatusBadge label="Temporal proximity only" tone="warning" compact />
                  </div>
                  <strong>{event.summary}</strong>
                  <span>{services.join(", ") || "Service not mapped"} · Source: {event.source || "unavailable"}</span>
                  <span>Authorized situation: <Link className="table-primary-link" href={`/situations/${encodeURIComponent(incident.incident_id)}`}>{incident.title}</Link></span>
                  {event.evidence?.length ? (
                    <span>Evidence reference{event.evidence.length === 1 ? "" : "s"}: {event.evidence.join(", ")}</span>
                  ) : (
                    <span className="timeline-unavailable">Evidence unavailable from source</span>
                  )}
                  {sourceLink(event) ? (
                    <a className="table-primary-link" href={sourceLink(event) ?? undefined} target="_blank" rel="noreferrer">Open source record</a>
                  ) : (
                    <span className="timeline-unavailable">Source link unavailable</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Change intelligence"
        requestedScope={changesCopilot.requestedScope}
        snapshot={changesCopilot.snapshot}
        starterQuestions={changesCopilot.starterQuestions}
      />
    </div>
  );
}
