import type { DurableEvidence, DurableSourceStatus, EvidenceItem } from "@/lib/types";
import type { PageHeaderCompleteness } from "./PageHeader";
import { formatDateTime, relativeTime } from "@/lib/format";
import { StatusBadge, statusTone, type StatusTone } from "./StatusBadge";

const VISIBLE_WARNING_COUNT = 2;

export interface EvidenceBarProps {
  evidence?: EvidenceItem[];
  knowledgeVersion?: string;
  warnings?: string[];
  fallbackTimestamp?: string;
  graphFreshness?: string;
  liveObservedAt?: string;
  sourceStatus?: Record<string, string>;
  durableEvidence?: DurableEvidence[];
  durableSourceStatus?: DurableSourceStatus[];
  aggregateState?: PageHeaderCompleteness;
  confidenceSubject?: string;
  graphTimestampLabel?: string;
}

/** Keep this predicate identical to the long-form topology freshness guard:
 * absent, empty, unparseable, and at-or-before epoch are all unknown. */
function freshnessChip(value?: string): string {
  if (!value) return "Unknown";
  const ms = new Date(value).getTime();
  if (Number.isNaN(ms) || ms <= 0) return "Unknown";
  return relativeTime(value);
}

function sourceCoverage(statuses: Record<string, string>): { label: string; tone: StatusTone } | null {
  const states = Object.values(statuses).map(state => state.trim().toLowerCase());
  if (!states.length) return null;
  if (states.every(state => state === "unavailable")) {
    return { label: "Source coverage unavailable", tone: "critical" };
  }
  if (states.some(state => ["partial", "degraded", "stale", "unavailable"].includes(state))) {
    return { label: "Source coverage incomplete", tone: "warning" };
  }
  if (states.every(state => state === "ready")) {
    return { label: "Sources reporting ready", tone: "info" };
  }
  return { label: "Source coverage unknown", tone: "unknown" };
}

/** Makes evidence confidence, provenance, freshness, and warnings visible beside the decision surface,
 * rendered as a lightweight left-to-right chain (source → freshness → confidence) so the provenance
 * story reads as a connected sequence rather than a flat badge list. */
export function EvidenceBar({
  evidence = [],
  knowledgeVersion,
  warnings = [],
  fallbackTimestamp,
  graphFreshness,
  liveObservedAt,
  sourceStatus = {},
  durableEvidence = [],
  durableSourceStatus = [],
  aggregateState,
  confidenceSubject,
  graphTimestampLabel = "Graph",
}: EvidenceBarProps) {
  const latest = evidence[0];
  const uniqueWarnings = Array.from(
    new Set(warnings.map((warning) => warning.trim()).filter(Boolean)),
  );
  const visibleWarnings = uniqueWarnings.slice(0, VISIBLE_WARNING_COUNT);
  const additionalWarnings = uniqueWarnings.slice(VISIBLE_WARNING_COUNT);
  const timestamp = latest?.timestamp || fallbackTimestamp;
  const confidence = latest?.confidence || "unknown";
  const confidenceTone = confidence === "high" ? "info"
    : confidence === "medium" || confidence === "low" ? "warning" : "unknown";
  const coverage = aggregateState ? null : sourceCoverage(sourceStatus);
  const aggregateLabel =
    aggregateState?.state === "complete" && aggregateState.freshness === "current"
      ? null
      : aggregateState
        ? `${aggregateState.state.slice(0, 1).toUpperCase()}${aggregateState.state.slice(1)} evidence`
        : null;
  const tone = aggregateLabel
    ? statusTone(
        aggregateState?.state === "unavailable"
          ? "unavailable"
          : "degraded",
      )
    : coverage?.tone ?? confidenceTone;
  const segments = [
    latest?.source_engine
      ? { key: "source", label: "Source", value: latest.source_engine, title: `${latest.source_engine}${latest.source_table ? ` · ${latest.source_table}` : ""}` }
      : null,
    { key: "updated", label: "Updated", value: relativeTime(timestamp) },
    knowledgeVersion ? { key: "knowledge", label: "Knowledge", value: knowledgeVersion } : null,
    { key: "graph", label: graphTimestampLabel, value: freshnessChip(graphFreshness) },
    liveObservedAt ? { key: "live", label: "Live", value: relativeTime(liveObservedAt) } : null,
  ].filter((segment): segment is { key: string; label: string; value: string; title?: string } => segment !== null);

  return (
    <aside className={`evidence-bar evidence-bar-${tone}`} aria-label="Data trust and provenance">
      <div className="evidence-bar-primary">
        {coverage && <StatusBadge label={coverage.label} tone={coverage.tone} compact />}
        <StatusBadge
          label={
            aggregateLabel ??
            `${confidenceSubject || "Cited evidence"} · ${confidence} confidence`
          }
          tone={aggregateLabel ? tone : confidenceTone}
          compact
        />
        {segments.map((segment, index) => (
          <span className="evidence-chain-step" key={segment.key}>
            {index > 0 && <span className="evidence-chain-arrow" aria-hidden>›</span>}
            <span title={segment.title}>
              <strong>{segment.label}</strong> {segment.value}
            </span>
          </span>
        ))}
      </div>
      {coverage && (
        <span>Confidence describes cited evidence, not source completeness.</span>
      )}
      {timestamp && <time dateTime={timestamp}>{formatDateTime(timestamp)}</time>}
      {Object.keys(sourceStatus).length > 0 && (
        <div aria-label="Live source status">
          {Object.entries(sourceStatus).map(([source, status]) => (
            <span key={source}><strong>{source}</strong> {status}</span>
          ))}
        </div>
      )}
      {durableEvidence.length > 0 && (
        <div className="evidence-trust-grid" aria-label="Durable evidence trust details">
          {durableEvidence.map((item) => (
            <span key={item.evidence_id}>
              <strong>{item.source_family}</strong> {item.source_object_id} · {item.quality} ·{" "}
              {item.availability} · {item.freshness} · {item.ingestion_status} · watermark{" "}
              {item.watermark || "unknown"} · observed {item.observed_at} · ingested {item.ingested_at} ·{" "}
              {item.provenance?.source_system ? String(item.provenance.source_system) : "provenance recorded"} · confidence{" "}
              {item.confidence || "unknown"}
            </span>
          ))}
        </div>
      )}
      {durableSourceStatus.length > 0 && (
        <div className="evidence-trust-grid" aria-label="Durable source status details">
          {durableSourceStatus.map((source) => (
            <span key={source.source_family}>
              <strong>{source.source_family}</strong> · status {source.status || "unknown"} · provider{" "}
              {source.provider_status || "unknown"} · availability {source.availability || "unknown"} · quality{" "}
              {source.quality || "unknown"} · freshness {source.freshness || "unknown"} · observed{" "}
              {source.observed_at || "unknown"} · ingested {source.ingested_at || "unknown"} · watermark{" "}
              {source.watermark || "unknown"} · query version {source.query_version || "unknown"} · requested scope{" "}
              {JSON.stringify(source.requested_scope)}{source.error ? ` · provider error ${source.error}` : ""}
            </span>
          ))}
        </div>
      )}
      {uniqueWarnings.length > 0 && (
        <div className="evidence-warning" aria-label="Data warnings">
          <ul className="evidence-warning-list">
            {visibleWarnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
          {additionalWarnings.length > 0 && (
            <details className="evidence-warning-details">
              <summary>
                Show {additionalWarnings.length} more{" "}
                {additionalWarnings.length === 1 ? "warning" : "warnings"}
              </summary>
              <ul className="evidence-warning-list">
                {additionalWarnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </aside>
  );
}
