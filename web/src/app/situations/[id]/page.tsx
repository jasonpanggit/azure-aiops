"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { StructuredData } from "@/components/ui/StructuredData";
import { formatDateTime, relativeTime, titleize } from "@/lib/format";
import { operationsApi } from "@/lib/services";
import { toSituationSummary } from "@/lib/situations";
import type { Envelope, IncidentCause, IncidentDetail, IncidentTimelineEvent } from "@/lib/types";

function latestChange(timeline: IncidentTimelineEvent[]): IncidentTimelineEvent | undefined {
  return timeline
    .filter((event) => event.event_type.toLowerCase().includes("change"))
    .sort((left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp))[0];
}

function rawEvidenceRecord(item: IncidentCause | IncidentTimelineEvent): Record<string, unknown> {
  return Object.fromEntries(Object.entries(item).filter(([, value]) => value !== undefined));
}

/** Evidence-backed investigation workspace that answers the five core operator questions. */
export default function SituationDetailPage({ params }: { params: { id: string } }) {
  const [envelope, setEnvelope] = useState<Envelope<IncidentDetail> | null>(null);
  const [error, setError] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    let active = true;
    operationsApi
      .incident(decodeURIComponent(params.id))
      .then((result) => active && setEnvelope(result))
      .catch((reason: unknown) => active && setError(reason instanceof Error ? reason.message : "Situation unavailable"));
    return () => {
      active = false;
    };
  }, [params.id]);

  const summary = useMemo(
    () => (envelope ? toSituationSummary(envelope.data.finding) : null),
    [envelope]
  );

  if (error) {
    return (
      <div className="page-container">
        <StatePanel
          title="Situation could not be opened"
          message={`${error}. Confirm the Situation is still visible in the current operating scope.`}
          tone="error"
          action={
            <Link className="button" href="/situations">
              Return to queue
            </Link>
          }
        />
      </div>
    );
  }

  if (!envelope || !summary) {
    return (
      <div className="page-container">
        <StatePanel
          title="Preparing investigation"
          message="Loading evidence, blast radius, ownership, correlated changes, and remediation guidance."
          tone="loading"
        />
      </div>
    );
  }

  const finding = envelope.data.finding;
  const rootCause = finding.root_cause_analysis;
  const timeline = [...(finding.timeline ?? rootCause.timeline ?? [])].sort(
    (left, right) => Date.parse(right.timestamp) - Date.parse(left.timestamp)
  );
  const change = latestChange(timeline);
  const action = finding.recommended_action;
  const blast = finding.blast_radius;

  return (
    <div className="page-container investigation-page">
      <div className="breadcrumb">
        <Link href="/situations">Situations</Link>
        <span>/</span>
        <span>{summary.id}</span>
      </div>
      <PageHeader
        eyebrow={`${summary.priority} Situation`}
        title={summary.title}
        description={`${summary.id} · Started ${relativeTime(summary.startedAt)} · ${summary.businessServices[0] ?? "Service not mapped"}`}
        actions={
          <>
            <Link className="button" href={`/copilot?situation=${encodeURIComponent(summary.id)}`}>
              Ask Copilot
            </Link>
            <Link className="button button-primary" href={`/remediation?incident=${encodeURIComponent(summary.id)}`}>
              Create action plan
            </Link>
          </>
        }
        metadata={
          <>
            <StatusBadge label={summary.status} tone={statusTone(summary.status)} />
            <StatusBadge label={`${Math.round(summary.confidence * 100)}% cause confidence`} tone="info" />
            <span>Advisory only</span>
          </>
        }
      />

      <EvidenceBar
        evidence={envelope.evidence}
        knowledgeVersion={envelope.knowledge_version}
        warnings={envelope.warnings}
        fallbackTimestamp={envelope.data.freshness}
      />

      <section className="answer-grid" aria-label="Situation executive summary">
        <article className="answer-card answer-critical">
          <span className="answer-number">01</span>
          <h2>What failed?</h2>
          <strong>{summary.cause}</strong>
          <p>{rootCause.conclusion || `${summary.title} is ${summary.status.toLowerCase()}.`}</p>
        </article>
        <article className="answer-card answer-high">
          <span className="answer-number">02</span>
          <h2>What is at risk?</h2>
          <strong>{summary.businessServices.join(", ") || "Business service not mapped"}</strong>
          <p>
            {summary.applications.length} application{summary.applications.length === 1 ? "" : "s"} across{" "}
            {finding.blast_radius.service_count} service{finding.blast_radius.service_count === 1 ? "" : "s"}.
          </p>
        </article>
        <article className="answer-card">
          <span className="answer-number">03</span>
          <h2>Who owns it?</h2>
          <strong>{summary.owner}</strong>
          <p>{summary.supportTeam}</p>
        </article>
        <article className="answer-card">
          <span className="answer-number">04</span>
          <h2>What changed?</h2>
          <strong>{change?.summary ?? "No correlated change"}</strong>
          <p>{change ? `${formatDateTime(change.timestamp)} · ${change.source}` : "No change evidence was linked."}</p>
        </article>
        <article className="answer-card answer-action">
          <span className="answer-number">05</span>
          <h2>How do I fix it?</h2>
          <strong>{action?.suggested_action ?? "Review the probable cause and validate the affected service."}</strong>
          <p>{action?.impact ?? "Recommended actions remain advisory until an operator approves execution."}</p>
        </article>
      </section>

      <div className="investigation-grid">
        <section className="card">
          <div className="card-header">
            <div>
              <h2>Root-cause candidates</h2>
              <p>Confidence-ranked evidence, contradictions, unknowns, and advisory next steps.</p>
            </div>
            <StatusBadge
              label={rootCause.confirmed_cause ? "Confirmed cause" : "Probable cause"}
              tone={rootCause.confirmed_cause ? "success" : "warning"}
            />
          </div>
          <div className="card-body reasoning-stack">
            {rootCause.probable_causes.map((cause, index) => (
              <div className="reasoning-card" key={cause.evidence_id ?? index}>
                <div className="reasoning-heading">
                  <strong>{cause.summary ?? titleize(cause.classification ?? `Cause ${index + 1}`)}</strong>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <StatusBadge
                      label={`${Math.round((cause.confidence ?? cause.causal_score ?? 0) * 100)}%`}
                      tone="info"
                      compact
                    />
                    <button type="button" className="button" onClick={() => setSelectedEvidence(rawEvidenceRecord(cause))}>
                      View evidence
                    </button>
                  </div>
                </div>
                {cause.evidence && (
                  <ul>
                    {cause.evidence.slice(0, 4).map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
            {rootCause.contradicting_evidence.length > 0 && (
              <div>
                <h3>Contradicting evidence</h3>
                <ul>
                  {rootCause.contradicting_evidence.map((item, index) => (
                    <li key={String(item.evidence_id ?? index)}>
                      <button type="button" className="table-primary-link" onClick={() => setSelectedEvidence(item)}>
                        {String(item.summary ?? item.evidence_type ?? `Contradiction ${index + 1}`)}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {rootCause.unknowns.length > 0 && (
              <div>
                <h3>Unknowns</h3>
                <ul>
                  {rootCause.unknowns.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
            {rootCause.next_steps.length > 0 && (
              <div>
                <h3>Next steps</h3>
                <ol className="reasoning-chain">
                  {rootCause.next_steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
              </div>
            )}
            {rootCause.reasoning_chain.length > 0 && (
              <ol className="reasoning-chain">
                {rootCause.reasoning_chain.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            )}
          </div>
        </section>

        <aside className="card">
          <div className="card-header">
            <div>
              <h2>Network-aware blast radius</h2>
              <p>Business dependencies plus observed subscription and network context.</p>
            </div>
          </div>
          <div className="card-body blast-radius">
            <div>
              <span>Business services</span>
              <strong>{finding.blast_radius.business_service_count}</strong>
              <p>{finding.blast_radius.business_services.join(", ") || "Not mapped"}</p>
            </div>
            <div>
              <span>Applications</span>
              <strong>{finding.blast_radius.application_count}</strong>
              <p>{finding.blast_radius.applications.join(", ") || "None identified"}</p>
            </div>
            <div>
              <span>Services</span>
              <strong>{finding.blast_radius.service_count}</strong>
              <p>{finding.blast_radius.services.join(", ") || "None identified"}</p>
            </div>
            <div>
              <span>Subscriptions</span>
              <p>{blast.subscriptions.join(", ") || blast.notes?.join(", ") || "Not observed"}</p>
            </div>
            <div>
              <span>Network paths</span>
              <ul>
                {blast.network_paths.map((path) => <li key={path}>{path}</li>)}
                {blast.network_paths.length === 0 && <li>Not observed</li>}
              </ul>
            </div>
            <div>
              <span>Hub dependencies</span>
              <p>{blast.hub_dependencies.join(", ") || "None observed"}</p>
            </div>
            <div>
              <span>Firewall impact</span>
              <ul>
                {blast.firewall_impact.map((item, index) => (
                  <li key={String(item.finding_id ?? index)}>{String(item.title ?? item.rule_name ?? "Firewall finding")}</li>
                ))}
                {blast.firewall_impact.length === 0 && <li>No firewall findings linked</li>}
              </ul>
            </div>
            <div>
              <span>NSG impact</span>
              <ul>
                {blast.nsg_impact.map((item, index) => (
                  <li key={String(item.finding_id ?? index)}>{String(item.title ?? item.rule_name ?? "NSG finding")}</li>
                ))}
                {blast.nsg_impact.length === 0 && <li>No NSG findings linked</li>}
              </ul>
            </div>
            <div>
              <span>Downstream services</span>
              <p>{blast.downstream_services.join(", ") || "None observed"}</p>
            </div>
          </div>
        </aside>
      </div>

      <section className="card timeline-card">
        <div className="card-header">
          <div>
            <h2>Correlated timeline</h2>
            <p>Signals, alerts, changes, patch failures, lifecycle events, and exposure evidence in sequence.</p>
          </div>
        </div>
        <div className="card-body timeline">
          {timeline.map((event) => (
            <button
              type="button"
              className="timeline-event"
              key={event.event_id}
              onClick={() => setSelectedEvidence(rawEvidenceRecord(event))}
              style={{ textAlign: "left", background: "transparent", border: 0, padding: 0 }}
            >
              <div className="timeline-marker" aria-hidden="true" />
              <time dateTime={event.timestamp}>{formatDateTime(event.timestamp)}</time>
              <div>
                <StatusBadge label={titleize(event.event_type)} tone={event.event_type.includes("Change") ? "info" : "neutral"} compact />
                <strong>{event.summary}</strong>
                <span>{event.source}</span>
              </div>
            </button>
          ))}
          {timeline.length === 0 && <span className="muted">No timeline events are available.</span>}
        </div>
      </section>

      {selectedEvidence && (
        <aside className="card" aria-label="Evidence drawer">
          <div className="card-header">
            <div>
              <h2>Evidence drawer</h2>
              <p>Full evidence record for operator review.</p>
            </div>
            <button type="button" className="button" onClick={() => setSelectedEvidence(null)}>
              Close
            </button>
          </div>
          <div className="card-body">
            <StructuredData value={selectedEvidence} />
          </div>
        </aside>
      )}
    </div>
  );
}
