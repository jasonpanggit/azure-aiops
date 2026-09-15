"use client";

import { useId, useState } from "react";
import { ChevronDownRegular, ChevronRightRegular } from "@fluentui/react-icons";
import type { CanonicalCopilotCitation } from "@/lib/types";
import { StatusBadge } from "@/components/ui/StatusBadge";

const CITATION_STATUS_TONE: Record<string, "success" | "warning" | "critical" | "info"> = {
  ok: "success",
  empty: "info",
  unavailable: "warning",
  denied: "critical",
};

/** Canonical Copilot citation with optional server-classified evidence age. */
export type CopilotCitation = CanonicalCopilotCitation & {
  observation_status?: unknown;
};

/** Props for the shared per-answer Copilot citation disclosure. */
export interface CopilotCitationsProps {
  citations: readonly CopilotCitation[];
  ariaLabel: string;
}

function serverEvidenceState(observationStatus: unknown): {
  label: string;
  tone: "success" | "warning" | "info";
} | null {
  if (typeof observationStatus !== "string") return null;
  switch (observationStatus.trim().toLowerCase()) {
    case "historical":
    case "historical_scope_restricted":
      return { label: "Historical evidence", tone: "warning" };
    case "revalidated":
    case "rechecked":
      return { label: "Revalidated evidence", tone: "success" };
    case "current":
      return { label: "Current evidence", tone: "info" };
    default:
      return null;
  }
}

/**
 * Renders one answer's citations behind an accessible disclosure that starts
 * collapsed while retaining source, status, provenance, and evidence age.
 */
export function CopilotCitations({
  citations,
  ariaLabel,
}: CopilotCitationsProps) {
  const [expanded, setExpanded] = useState(false);
  const disclosureId = useId();
  const label = `Citations (${citations.length})`;

  if (citations.length === 0) return null;

  return (
    <section className="copilot-citations" aria-label={ariaLabel}>
      <button
        type="button"
        className="copilot-citations-toggle"
        aria-expanded={expanded}
        aria-controls={disclosureId}
        onClick={() => setExpanded((current) => !current)}
      >
        {expanded
          ? <ChevronDownRegular aria-hidden />
          : <ChevronRightRegular aria-hidden />}
        <span>{label}</span>
      </button>
      <div
        id={disclosureId}
        className="copilot-citations-panel"
        hidden={!expanded}
      >
        <ul>
          {citations.map((citation) => {
            const evidenceState = serverEvidenceState(citation.observation_status);
            return (
              <li key={citation.citation_id}>
                <div className="copilot-citation">
                  <div className="copilot-citation-header">
                    <span>{citation.source}</span>
                    {citation.status ? (
                      <StatusBadge
                        label={citation.status}
                        tone={CITATION_STATUS_TONE[citation.status] ?? "neutral"}
                        compact
                      />
                    ) : null}
                  </div>
                  <dl className="copilot-citation-metadata">
                    <div>
                      <dt>Citation ID</dt>
                      <dd><code>{citation.citation_id}</code></dd>
                    </div>
                    <div>
                      <dt>Resource</dt>
                      <dd><code>{citation.resource_id || "Not supplied"}</code></dd>
                    </div>
                    <div>
                      <dt>Observed</dt>
                      <dd>
                        {citation.observed_at
                          ? <time dateTime={citation.observed_at}>{citation.observed_at}</time>
                          : "Not supplied"}
                      </dd>
                    </div>
                  </dl>
                  {evidenceState ? (
                    <StatusBadge
                      label={evidenceState.label}
                      tone={evidenceState.tone}
                      compact
                    />
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
