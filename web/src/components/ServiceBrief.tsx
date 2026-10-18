import Link from "next/link";
import { useState } from "react";
import type { Envelope, SemanticContext } from "@/lib/types";
import type { ScopeSelection } from "@/lib/scope";
import { overviewHref } from "@/lib/overview";
import { serviceBrief, serviceDependencies, serviceDependencyHref, serviceSourceState } from "@/lib/service-brief";

interface Source {
  data: Envelope<SemanticContext> | null;
  error: Error | null;
}

/** Typed service briefing and review prerequisites over actual loaded evidence. */
export function ServiceBrief({ context, risk, impact, scope }: { context: Source; risk: Source; impact: Source; scope: ScopeSelection }) {
  const contextState = serviceSourceState(context.data, context.error);
  const riskState = serviceSourceState(risk.data, risk.error);
  const impactState = serviceSourceState(impact.data, impact.error);
  const brief = serviceBrief(contextState.available ? context.data?.data : undefined, riskState.available ? risk.data?.data : undefined);
  const dependencies = serviceDependencies(contextState.available ? context.data?.data : undefined, impactState.available ? impact.data?.data : undefined);
  const [relation, setRelation] = useState("all");
  const [query, setQuery] = useState("");
  const matches = dependencies.filter(row => (relation === "all" || row.relation === relation) && row.name.toLowerCase().includes(query.toLowerCase().trim()));
  const prerequisites = [
    { label: "Accountable owner", state: brief.owner ? "Reported" : "Missing or ambiguous", detail: brief.owner || "Review connection or semantic ownership", href: "/connections" },
    { label: "Support escalation", state: brief.supportTeam ? "Reported" : "Missing or ambiguous", detail: brief.supportTeam || "No unambiguous support team reported", href: "/connections" },
    { label: "Service context source", state: contextState.state, detail: context.error?.message || "Context evidence, not runtime health", href: "/connections" },
    { label: "Risk evidence", state: riskState.state, detail: risk.error?.message || "Heuristic risk evidence, not reliability", href: "/exposure" },
    { label: "Dependency evidence", state: impactState.state, detail: impact.error?.message || "Reported relationships, not tested failover", href: "/twin" },
  ];
  return <>
    <section className="card service-brief" aria-label="Typed service brief">
      <div className="card-header"><div><h2>Service brief</h2><p>Known facts first. Unmapped or ambiguous values stay unreported.</p></div></div>
      <div className="card-body">
        <dl className="inventory-export-metadata">{[
          ["Accountable owner", brief.owner], ["Support team", brief.supportTeam],
          ["Environment", brief.environment], ["Criticality", brief.criticality], ["Lifecycle", brief.lifecycle],
        ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || "Unreported or ambiguous"}</dd></div>)}</dl>
        <p>Semantic risk score: {riskState.available ? brief.riskScore ?? "unreported" : "unavailable"}; level: {riskState.available ? brief.riskLevel || "unreported" : "unavailable"}.
          {" "}This is a source-defined heuristic, not availability, SLO attainment, or error budget.</p>
        {brief.factors.length > 0 && <details><summary>Reported risk factors</summary><ul>{brief.factors.map(([name, value]) => <li key={name}>{name}: {value}</li>)}</ul></details>}
        <p>Service availability, latency, SLO target/window, and error-budget telemetry are not supplied by these context contracts. Incident and registry counts cannot substitute for those measures.</p>
        <p><Link href={`${overviewHref("/services", scope)}#component-request-reliability`}>Review declared component request targets and measured telemetry in Services</Link>. That separate evidence is not service-wide uptime or included in this brief.</p>
      </div>
    </section>
    <section className="card service-brief" aria-label="Service review readiness">
      <div className="card-header"><div><h2>Operational review prerequisites</h2><p>Evidence readiness for an operator review, never execution or production-readiness approval.</p></div></div>
      <div className="card-body"><p className="service-scroll-hint">More columns may be off-screen. Scroll horizontally, or focus the table and use arrow keys.</p><div className="data-table-wrap" tabIndex={0} role="region" aria-label="Service prerequisites, horizontally scrollable">
        <table className="data-table"><caption>Reported and missing prerequisites; no inferred pass</caption>
          <thead><tr><th>Prerequisite</th><th>Evidence state</th><th>Detail</th><th>Next review</th></tr></thead>
          <tbody>{prerequisites.map(row => <tr key={row.label}><th scope="row">{row.label}</th><td>{row.state}</td><td>{row.detail}</td><td><Link href={overviewHref(row.href, scope)}>Review {row.label.toLowerCase()}</Link></td></tr>)}</tbody>
        </table>
      </div><p>A reported owner is not proof of on-call coverage. Freshness requires reported fresh evidence, not a successful request. No runbook, rollback, or tested failover approval is asserted.</p></div>
    </section>
    <section className="card service-brief" aria-label="Navigable service dependencies">
      <div className="card-header"><div><h2>Explore reported relationships</h2><p>Keep the source relation and entity type; inspect context without authorizing changes.</p></div></div>
      <div className="card-body">
        <div className="overview-history-controls">
          <label>Relationship <select value={relation} onChange={event => setRelation(event.target.value)}>
            <option value="all">All loaded relationships</option>
            {Array.from(new Set(dependencies.map(row => row.relation))).map(value => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
          </select></label>
          <label>Find dependency <input value={query} maxLength={256} onChange={event => setQuery(event.target.value)} /></label>
        </div>
        <p>{matches.length} matching / {dependencies.length} loaded relationship observations; at most 50 shown. Upstream source limits remain unknown unless reported. Duplicate relations are not unique resources.</p>
        {dependencies.length === 0 && <p>No relationships available in these loaded sources; this does not establish independence or complete mapping.</p>}
        <ul>{matches.slice(0, 50).map(row => {
          const href = serviceDependencyHref(row, scope);
          return <li key={`${row.relation}:${row.entityType}:${row.id}`}>
            {href ? <Link href={href}>{row.name}</Link> : <strong>{row.name}</strong>}
            {" "}· {row.relation.replaceAll("_", " ")} · {row.entityType || "type unreported"} · {row.identity === "explicit" ? "explicit source identity" : "name-only reference; lookup reauthorizes"}
            {!href && " · no supported identity-bound destination"}
          </li>;
        })}</ul>
      </div>
    </section>
  </>;
}
