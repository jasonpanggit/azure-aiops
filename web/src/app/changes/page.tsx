"use client";

import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { formatDateTime, titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { operationsApi } from "@/lib/services";

/** Correlated change stream extracted from active Situation timelines. */
export default function ChangesPage() {
  const { scope } = useScope();
  const incidents = useApi(() => operationsApi.incidents(scope), [scope]);
  const changes = (incidents.data?.data.incidents ?? [])
    .flatMap((entry) =>
      entry.timeline
        .filter((event) => event.event_type.toLowerCase().includes("change"))
        .map((event) => ({ event, incident: entry.incident, services: entry.blast_radius.business_services }))
    )
    .sort((left, right) => Date.parse(right.event.timestamp) - Date.parse(left.event.timestamp));

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Change intelligence"
        title="Correlated changes"
        description="Changes that occurred near active Situations, preserving correlation without presenting chronology as causation."
        metadata={<><span>{changes.length} correlated changes</span><span>Correlation is not confirmation</span></>}
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
                <time dateTime={event.timestamp}>{formatDateTime(event.timestamp)}</time>
                <div>
                  <StatusBadge label={titleize(event.event_type)} tone="info" compact />
                  <strong>{event.summary}</strong>
                  <span>{services.join(", ") || "Service not mapped"} · {incident.title} · {event.source}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
