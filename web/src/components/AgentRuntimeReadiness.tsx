"use client";

import { useState } from "react";
import { useApi } from "@/hooks/useApi";
import { formatDateTime } from "@/lib/format";
import type { ScopeSelection } from "@/lib/scope";
import { multiAgentApi } from "@/lib/services";
import type { AutonomousAgent } from "@/lib/types";
import { StatePanel } from "./ui/StatePanel";
import { StatusBadge, statusTone } from "./ui/StatusBadge";

const declaredBoolean = (value: boolean | null) => value === true ? "Yes" : value === false ? "No" : "Not reported";

/** Separate activation metadata from independently sourced cached provider state. */
export function AgentRuntimeReadiness({ scope, agents, catalogLoading, catalogError }: {
  scope: ScopeSelection;
  agents: AutonomousAgent[];
  catalogLoading: boolean;
  catalogError: string;
}) {
  const [open, setOpen] = useState(false);
  return <details className="card agents-readiness" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Runtime readiness and version evidence</summary>
    {open ? <ReadinessReport key={JSON.stringify(scope)} scope={scope} agents={agents} catalogLoading={catalogLoading} catalogError={catalogError} /> : null}
  </details>;
}

function ReadinessReport({ scope, agents, catalogLoading, catalogError }: {
  scope: ScopeSelection;
  agents: AutonomousAgent[];
  catalogLoading: boolean;
  catalogError: string;
}) {
  const report = useApi(signal => multiAgentApi.runtimeReadiness(scope, { signal }), [JSON.stringify(scope)]);
  return <div className="card-body">
    <p>Activation is catalog metadata, not connectivity proof. Provider states are cached in this API process; no live Foundry, APIM or MCP probe runs here. Neither source proves tools executed or every resource in this scope is covered.</p>
    <details className="agents-readiness-declarations"><summary>Specialist activation declarations</summary>
    <p className="muted">Source: /agents/catalog. Active versions and validated inactive candidates are separate. A manifest default is not proof of a deployed version.</p>
    {catalogLoading ? <StatePanel title="Reading activation metadata" message="Waiting for the independent specialist catalog." tone="loading" /> : catalogError ? <StatePanel title="Activation metadata unavailable" message={catalogError} tone="error" /> : agents.length ? <ul className="agents-readiness-list">
      {agents.map(agent => <li key={agent.id}>
        <strong>{agent.name}</strong>
        <StatusBadge label={agent.foundry?.status ?? "Not reported"} tone="neutral" compact />
        <p>Activation source: {agent.foundry?.activation_source || "Not reported"}. Active version: {agent.foundry?.configured && agent.foundry.status === "active" ? agent.foundry.version || "Not pinned" : "Not active"}. Pin required: {agent.foundry?.version_pinning_required === undefined ? "Not reported" : agent.foundry.version_pinning_required ? "Yes" : "No"}.</p>
        {agent.foundry?.candidate ? <p>Inactive candidate: {agent.foundry.candidate.name}, provider version {agent.foundry.candidate.provider_version_id}; validated {formatDateTime(agent.foundry.candidate.validated_at)} from {agent.foundry.candidate.source_revision}.</p> : null}
        {agent.foundry?.degraded_reason ? <p>{agent.foundry.degraded_reason}</p> : null}
      </li>)}
    </ul> : <StatePanel title="No specialist activation metadata" message="The catalog returned no declarations; runtime readiness is not inferred." tone="partial" />}
    </details>
    <h2>Cached provider observations</h2>
    <button className="button" type="button" disabled={report.loading} onClick={report.refetch}>Reload cached provider report</button>
    {report.loading ? <StatePanel title="Reading cached provider state" message="Reading existing cached observations without starting a provider refresh." tone="loading" /> : report.error ? <StatePanel title="Provider observations unavailable" message={report.error.message} tone="error" /> : report.data ? <>
      <p className="muted">Source: {report.data.data.source}. Report assembled {report.data.data.reported_at}; this is not the time a provider was checked. Provider timestamps retain their reported timezone.</p>
      <ul className="agents-readiness-list">
        {Object.entries(report.data.data.providers).map(([name, provider]) => <li key={name}>
          <strong>{name}</strong>
          <StatusBadge label={provider?.state ?? "Not reported"} tone={provider?.state === "ready" ? "info" : statusTone(provider?.state ?? "unknown")} compact />
          {provider ? <>
            <p>Configured: {declaredBoolean(provider.configured)}. Loaded: {declaredBoolean(provider.loaded)}. Cache key changed: {declaredBoolean(provider.cache_key_stale)}.</p>
            <p>Last successful load: {provider.last_success_at || "Not reported"}. Last load attempt: {provider.last_attempt_at || "Not reported"}.</p>
            <p>Source freshness: {provider.freshness || "Not reported"}. Ontology version: {provider.ontology_version || "Not reported"}.</p>
            {provider.degraded_reason ? <p>{provider.degraded_reason}</p> : null}
          </> : <p>No cached observation was reported for this provider; configured or ready cannot be inferred.</p>}
        </li>)}
      </ul>
      {report.data.warnings?.map((warning, index) => <p className="muted" key={`${index}:${warning}`}>{warning}</p>)}
    </> : <StatePanel title="No cached provider report" message="No provider readiness can be inferred." tone="partial" />}
  </div>;
}
