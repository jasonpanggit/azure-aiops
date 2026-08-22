"use client";

import { useEffect, useMemo, useState } from "react";
import { SituationTable } from "@/components/SituationTable";
import { CopilotLauncher } from "@/components/ui/CopilotLauncher";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { useScope } from "@/lib/scope-context";
import { operationsApi } from "@/lib/services";
import { rankSituations, type SituationPriority } from "@/lib/situations";
import type { Envelope, IncidentReport } from "@/lib/types";

/** Triage queue for ranked, service-aware operational Situations. */
export default function SituationsPage() {
  const { scope } = useScope();
  const [envelope, setEnvelope] = useState<Envelope<IncidentReport> | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [priority, setPriority] = useState<"all" | SituationPriority>("all");

  useEffect(() => {
    let active = true;
    setError("");
    operationsApi
      .incidents(scope, 0, 100)
      .then((result) => active && setEnvelope(result))
      .catch((reason: unknown) => active && setError(reason instanceof Error ? reason.message : "Situations are unavailable"));
    return () => {
      active = false;
    };
  }, [scope]);

  const situations = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return rankSituations(envelope?.data.incidents ?? []).filter((situation) => {
      if (priority !== "all" && situation.priority !== priority) return false;
      if (!normalized) return true;
      return [
        situation.title,
        situation.id,
        situation.owner,
        situation.supportTeam,
        situation.cause,
        ...situation.businessServices,
        ...situation.applications,
      ].some((value) => value.toLowerCase().includes(normalized));
    });
  }, [envelope, priority, query]);

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Operate"
        title="Situations"
        description="Correlated operational work ranked by business impact, blast radius, evidence confidence, and recency."
        metadata={
          <>
            <span>{envelope?.data.incidents.length ?? 0} active</span>
            <span>Read-only investigation</span>
            <span>Operator approval required for remediation</span>
          </>
        }
      />

      {envelope && (
        <EvidenceBar
          evidence={envelope.evidence}
          knowledgeVersion={envelope.knowledge_version}
          warnings={envelope.warnings}
          fallbackTimestamp={envelope.data.freshness}
        />
      )}

      <CopilotLauncher
        starterQuestions={["which incidents are highest priority", "what changed before the outage", "what should be fixed first"]}
      />

      <div className="queue-toolbar">
        <label className="search-field">
          <span>Search situations</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Service, application, owner, cause, or incident ID"
          />
        </label>
        <div className="segmented-control" aria-label="Priority filter">
          {(["all", "P1", "P2", "P3"] as const).map((value) => (
            <button
              type="button"
              key={value}
              className={priority === value ? "segmented-active" : ""}
              onClick={() => setPriority(value)}
            >
              {value === "all" ? "All priorities" : value}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <StatePanel
          title="Situation intelligence is unavailable"
          message={`${error}. The workbench will not present an empty queue as an all-clear state.`}
          tone="error"
        />
      ) : !envelope ? (
        <StatePanel
          title="Loading Situation queue"
          message="Correlating incident evidence and business impact."
          tone="loading"
        />
      ) : situations.length === 0 ? (
        <StatePanel
          title="No Situations match these filters"
          message="Adjust the priority or search criteria. This result reflects the current operating scope."
        />
      ) : (
        <div className="card queue-card">
          <SituationTable situations={situations} />
          {envelope.pagination && (
            <div className="table-footer">
              Showing {envelope.pagination.offset + 1}–
              {Math.min(envelope.pagination.offset + envelope.pagination.limit, envelope.pagination.total)} of{" "}
              {envelope.pagination.total}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
