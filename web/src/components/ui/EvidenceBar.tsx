import type { EvidenceItem } from "@/lib/types";
import { formatDateTime, relativeTime } from "@/lib/format";
import { StatusBadge, statusTone } from "./StatusBadge";

export interface EvidenceBarProps {
  evidence?: EvidenceItem[];
  knowledgeVersion?: string;
  warnings?: string[];
  fallbackTimestamp?: string;
}

/** Makes evidence confidence, provenance, freshness, and warnings visible beside the decision surface. */
export function EvidenceBar({
  evidence = [],
  knowledgeVersion,
  warnings = [],
  fallbackTimestamp,
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
      {warnings.length > 0 && <div className="evidence-warning">{warnings.join(" · ")}</div>}
    </aside>
  );
}
