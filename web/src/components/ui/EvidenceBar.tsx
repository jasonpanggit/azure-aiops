import type { DurableEvidence, EvidenceItem } from "@/lib/types";
import { formatDateTime, relativeTime } from "@/lib/format";
import { StatusBadge, statusTone } from "./StatusBadge";

export interface EvidenceBarProps {
  evidence?: EvidenceItem[];
  knowledgeVersion?: string;
  warnings?: string[];
  fallbackTimestamp?: string;
  durableEvidence?: DurableEvidence[];
}

/** Makes evidence confidence, provenance, freshness, and warnings visible beside the decision surface. */
export function EvidenceBar({
  evidence = [],
  knowledgeVersion,
  warnings = [],
  fallbackTimestamp,
  durableEvidence = [],
}: EvidenceBarProps) {
  const latest = evidence[0];
  const timestamp = latest?.timestamp || fallbackTimestamp;
  const confidence = latest?.confidence || "unknown";

  return (
    <aside className="evidence-bar" aria-label="Data trust and provenance">
      <div className="evidence-bar-primary">
        <StatusBadge label={`${confidence} confidence`} tone={statusTone(confidence)} compact />
        <span>
          <strong>Updated</strong> {relativeTime(timestamp)}
        </span>
        {latest?.source_engine && (
          <span title={`${latest.source_engine}${latest.source_table ? ` · ${latest.source_table}` : ""}`}>
            <strong>Source</strong> {latest.source_engine}
          </span>
        )}
        {knowledgeVersion && (
          <span>
            <strong>Knowledge</strong> {knowledgeVersion}
          </span>
        )}
      </div>
      {timestamp && <time dateTime={timestamp}>{formatDateTime(timestamp)}</time>}
      {durableEvidence.length > 0 && (
        <div className="evidence-trust-grid" aria-label="Durable evidence trust details">
          {durableEvidence.map((item) => (
            <span key={item.evidence_id}>
              <strong>{item.source_family}</strong> {item.source_object_id} · {item.quality} · {item.availability} · {item.freshness} · {item.ingestion_status} · watermark {item.watermark || "unknown"} · observed {item.observed_at} · ingested {item.ingested_at} · {item.provenance?.source_system ? String(item.provenance.source_system) : "provenance recorded"}
            </span>
          ))}
        </div>
      )}
      {warnings.length > 0 && <div className="evidence-warning">{warnings.join(" · ")}</div>}
    </aside>
  );
}
