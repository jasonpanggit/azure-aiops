"use client";

import Link from "next/link";
import { useState } from "react";
import { ChangeObservations } from "@/components/ChangeObservations";

import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { buildChangesCopilotContext, envelopeSourceStatus } from "@/lib/copilot/page-adapters";
import { formatDateTime, relativeTime, titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { operationsApi } from "@/lib/services";
import type { IncidentTimelineEvent } from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";
import { overviewHref } from "@/lib/overview";

function sourceLink(event: IncidentTimelineEvent): string | null {
  for (const key of ["source_url", "source_link", "deep_link", "url"]) {
    const value = event[key];
    if (typeof value === "string" && /^https?:\/\//.test(value)) return value;
  }
  return null;
}

/** Independent change projection and separately sourced legacy incident associations. */
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
    changes: changes.slice(0, 50).map(({ event, incident, services }) => ({
      event_id: event.event_id,
      incident_id: incident.incident_id,
      incident_title: incident.title,
      event_type: event.event_type,
      summary: event.summary,
      source: event.source,
      timestamp: event.timestamp,
      business_services: services,
    })),
    loadedCount: Math.min(50, changes.length),
    totalCount: changes.length,
    available: !incidents.error && Boolean(incidents.data),
    freshness: envelopeSourceStatus("changes/incident-timeline", incidents.error ? null : incidents.data).status,
    observedAt: incidents.data?.evidence?.[0]?.timestamp,
    evidence: incidents.data?.evidence ?? [],
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Change intelligence"
        title="What changed in the observed estate?"
        description="Review independent change observations and separately sourced incident timeline associations. Neither is a causal conclusion."
        metadata={<><span>Governed projections only</span><span>Correlation is not confirmation</span></>}
        actions={
          <>
            <CopilotDrawerButton
              onClick={() => setCopilotOpen(true)}
              label="Ask Copilot about timeline associations"
            />
            <Link className="button button-secondary" href={overviewHref("/changes/predeploy", scope)}>Assess a proposed change</Link>
          </>
        }
      />
      <ChangeObservations />
      <h2>Legacy incident timeline associations</h2>
      <p>Change-type events from at most 100 loaded incident report rows, not the durable Situation queue or the independent feed. The timeline Copilot uses only this report. No loaded association establishes causality or source completeness.</p>
      {incidents.data && !incidents.error && <p>{changes.length} change-type events in {incidents.data.data.incidents.length} loaded / {incidents.data.pagination?.total ?? "unreported"} reported incident rows; at most 50 events shown.</p>}
      <CopilotInsights
        snapshot={changesCopilot.snapshot}
        ready={!incidents.loading}
        requestedScope={changesCopilot.requestedScope}
        contextLabel="Incident timeline associations"
        onOpenCopilot={() => setCopilotOpen(true)}
      />
      <EvidenceBar evidence={incidents.data?.evidence} knowledgeVersion={incidents.data?.knowledge_version} warnings={incidents.data?.warnings} />
      {incidents.error ? (
        <StatePanel title="Incident timeline associations unavailable" message={incidents.error.message} tone="error" />
      ) : incidents.loading ? (
        <StatePanel title="Loading incident associations" message="Reading the independent legacy incident report." tone="loading" />
      ) : changes.length === 0 ? (
        <StatePanel title="No change associations in the loaded report" message="This does not establish that no independent changes occurred." />
      ) : (
        <div className="card timeline-card changes-timeline">
          <div className="card-body timeline">
            {changes.slice(0, 50).map(({ event, incident, services }) => (
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
                  <span>Incident report record: <Link className="table-primary-link" href={overviewHref(`/situations/${encodeURIComponent(incident.incident_id)}`, scope)}>{incident.title}</Link></span>
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
        contextLabel="Incident timeline associations"
        requestedScope={changesCopilot.requestedScope}
        snapshot={changesCopilot.snapshot}
        starterQuestions={changesCopilot.starterQuestions}
      />
    </div>
  );
}
