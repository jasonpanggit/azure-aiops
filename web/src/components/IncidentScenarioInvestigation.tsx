"use client";

import { useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { isCanonicalAzureResourceId } from "@/lib/services";
import type { CopilotEvidenceSnapshotV2 } from "@/lib/types";
import { useScope } from "@/lib/scope-context";

/** Explicit resource/window entry into the existing governed Copilot and ledger. */
export function IncidentScenarioInvestigation({
  resourceId = "",
  healthPage = false,
}: {
  resourceId?: string;
  healthPage?: boolean;
}) {
  const { scope } = useScope();
  const [resource, setResource] = useState(resourceId);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const pageKind = healthPage ? "resource_health" : "changes";
  const snapshot: CopilotEvidenceSnapshotV2 = {
    version: "2", page_kind: pageKind, page_id: "incident-change-investigation",
    selected_entities: isCanonicalAzureResourceId(resource) ? [{ type: "azure", resource_id: resource }] : [],
    filters: { ...(since.trim() ? { since: [since.trim()] } : {}), ...(until.trim() ? { until: [until.trim()] } : {}) },
    coverage: { visible_count: 0, total_count: 0, complete: false },
    freshness: [], evidence: [], material_claims: [],
  };
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const start = Date.parse(since);
    const end = Date.parse(until);
    const zoned = (value: string) => /(?:Z|[+-]\d{2}:\d{2})$/i.test(value);
    if (!isCanonicalAzureResourceId(resource) || !zoned(since) || !zoned(until)
      || !Number.isFinite(start) || !Number.isFinite(end) || end <= start || end - start > 7 * 86_400_000) {
      setError("Select one resource ARM id and an explicit timezone-qualified window of at most seven days.");
      return;
    }
    setError("");
    setOpen(true);
  }
  const argumentsFor = (scenario: string) => ({ scenario, resource_id: resource, since, until });
  return <section className="card" aria-label="Incident and change investigation">
    <div className="card-body">
      <h2>Investigate resource changes and incident impact</h2>
      <p>Read-only projection evidence, not complete activity history. Temporal proximity is not causality. Historical health and dependency coverage may be unavailable.</p>
      <form className="form-grid" onSubmit={submit}>
        <label className="form-field form-span"><span>Selected resource ARM id</span><input className="form-control" aria-label="Investigation resource ARM id" value={resource} readOnly={Boolean(resourceId)} maxLength={512} onChange={event => setResource(event.target.value.trim())} required /></label>
        <label className="form-field"><span>Investigation from (ISO timestamp with timezone)</span><input className="form-control" aria-label="Investigation from" value={since} maxLength={64} placeholder="2026-10-26T00:00:00Z" onChange={event => setSince(event.target.value)} required /></label>
        <label className="form-field"><span>Investigation through (ISO timestamp with timezone)</span><input className="form-control" aria-label="Investigation through" value={until} maxLength={64} placeholder="2026-10-26T01:00:00Z" onChange={event => setUntil(event.target.value)} required /></label>
        <div className="form-actions"><button type="submit" className="button button-secondary">Open bounded investigation</button></div>
        {error && <p className="form-span" role="alert">{error}</p>}
      </form>
      <CopilotDrawer
        open={open} onClose={() => setOpen(false)}
        contextLabel="Resource/window investigation" requestedScope={scope} snapshot={snapshot}
        starterQuestions={[
          { label: "Investigate recent changes in the selected window", specialistId: healthPage ? "resource_health_observability" : "change", tool: "incidents", toolArguments: argumentsFor("recent_change") },
          { label: "Build an incident impact brief for the selected window", specialistId: healthPage ? "resource_health_observability" : "incident", tool: "incidents", toolArguments: argumentsFor("incident_impact") },
        ]}
      />
    </div>
  </section>;
}
