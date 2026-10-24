"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useApi } from "@/hooks/useApi";
import { buildChangesCopilotContext, envelopeSourceStatus } from "@/lib/copilot/page-adapters";
import { formatDateTime } from "@/lib/format";
import { overviewHref } from "@/lib/overview";
import { useScope } from "@/lib/scope-context";
import { scopeToSearchParams } from "@/lib/scope";
import { operationsApi } from "@/lib/services";
import type { ChangeStateCell } from "@/lib/types";
import { CopilotDrawer } from "./ui/CopilotDrawer";
import { CopilotDrawerButton } from "./ui/CopilotDrawerButton";
import { EvidenceBar } from "./ui/EvidenceBar";
import { StatePanel } from "./ui/StatePanel";
import { StatusBadge } from "./ui/StatusBadge";
import { TablePagination } from "./ui/TablePagination";

const FILTERS = ["q", "category", "source", "since", "until", "order"] as const;
const PAGE_SIZE = 25;

function cellText(cell: ChangeStateCell): string {
  if (cell.status === "reported") return String(cell.value);
  return cell.status === "withheld" ? "Withheld: unsupported value" : "Unreported";
}

function contextExcerpt(value: string, maximum: number): string {
  return value.slice(0, maximum).replace(/[\uD800-\uDBFF]$/, "");
}

/** Independent governed observations retain their own failure, query, scope and Copilot boundaries. */
export function ChangeObservations() {
  const { scope } = useScope();
  const params = useSearchParams();
  return <ObservationWorkspace key={`${JSON.stringify(scope)}:${params.toString()}`} />;
}

function ObservationWorkspace() {
  const { scope } = useScope();
  const params = useSearchParams();
  const router = useRouter();
  const [copilotOpen, setCopilotOpen] = useState(false);
  const filters = Object.fromEntries(FILTERS.map(key => [key, params.get(`change_${key}`) ?? ""]));
  const rawPage = params.get("change_page") ?? "0";
  const page = Number(rawPage);
  const invalid = !/^\d+$/.test(rawPage) || !Number.isSafeInteger(page) || page > 1_000_000
    || Boolean(filters.order && !["newest", "oldest"].includes(filters.order))
    || [...FILTERS, "page"].some(key => params.getAll(`change_${key}`).length > 1);
  const feed = useApi(signal => invalid
    ? Promise.reject(new Error("Invalid change bookmark. Correct the filters or clear them."))
    : operationsApi.changeObservations(scope, { ...filters, offset: String(page * PAGE_SIZE), limit: String(PAGE_SIZE) }, signal), []);
  const available = !feed.loading && !feed.error && Boolean(feed.data);
  const current = available ? feed.data : null;
  const rows = current?.data.observations ?? [];
  const context = buildChangesCopilotContext({
    scope, filters: { view: ["independent_observations"], ...Object.fromEntries(Object.entries(filters).filter(([, value]) => value).map(([key, value]) => [key, [value]])) },
    records: rows.map((row, index) => ({
      identity: row.observation_id, namespace: "change", kind: "observed_change",
      evidenceIdentity: "observation", source: "changes/independent-observations",
      observedAt: row.changed_at, priority: index,
      data: {
        change_id: contextExcerpt(row.change_id, 128), summary: contextExcerpt(row.summary, 128), category: row.category,
        change_source: contextExcerpt(row.source, 64), resource_name: contextExcerpt(row.resource_name, 64),
        business_service: contextExcerpt(row.business_service, 64), environment: contextExcerpt(row.environment, 64),
        text_truncated: row.summary.length > 128 || row.change_id.length > 128 || [row.source, row.resource_name, row.business_service, row.environment].some(value => value.length > 64),
        text_extent: "Bounded contextual excerpts; full projected text remains in the portal.",
        comparison_basis: "allowlisted_change_states", confirmed_cause: false,
        configuration: row.configuration,
      },
    })),
    evidence: current?.evidence ?? [],
    coverage: [{ key: "independent_changes", visibleCount: rows.length, totalCount: current?.pagination?.total ?? 0, available }],
    sourceStatuses: [envelopeSourceStatus("changes/independent-observations", current)],
  });
  function navigate(values: Record<string, string>, nextPage = 0) {
    const query = scopeToSearchParams(scope);
    for (const key of FILTERS) if (values[key]) query.set(`change_${key}`, values[key]);
    if (nextPage) query.set("change_page", String(nextPage));
    router.push(`/changes${query.size ? `?${query}` : ""}`, { scroll: false });
  }
  return <section className="change-observations" aria-labelledby="change-observations-title">
    <div className="section-header">
      <h2 id="change-observations-title">Independent change observations</h2>
      <div className="button-row">
        <button type="button" className="button button-secondary" onClick={feed.refetch} disabled={feed.loading}>Reload independent changes</button>
        <CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about loaded observations" />
      </div>
    </div>
    <p>Changes from the governed projection, including events with no incident association. This is not a complete Azure activity history; no source success implies causal confirmation or execution approval.</p>
    <form className="change-filters" onSubmit={event => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      navigate(Object.fromEntries(FILTERS.map(key => [key, String(data.get(key) ?? "").trim()])));
    }}>
      <label htmlFor="change-query">Find observed changes<input id="change-query" name="q" type="search" maxLength={200} defaultValue={filters.q} placeholder="Change, resource, application or service" /></label>
      <label htmlFor="change-category">Category<select id="change-category" name="category" defaultValue={filters.category}>
        <option value="">All categories</option>
        {Array.from(new Set([filters.category, ...(feed.data?.data.facets.category ?? [])])).filter(Boolean).map(value => <option key={value} value={value}>{value}{feed.data && !feed.data.data.facets.category.includes(value) ? " (not in loaded suggestions)" : ""}</option>)}
      </select></label>
      <label htmlFor="change-source">Source<input id="change-source" name="source" list="change-source-options" maxLength={256} defaultValue={filters.source} placeholder="Any source" />
        <datalist id="change-source-options">{(feed.data?.data.facets.source ?? []).map(value => <option key={value} value={value} />)}</datalist>
      </label>
      <label htmlFor="change-since">From (ISO timestamp with timezone)<input id="change-since" name="since" maxLength={64} defaultValue={filters.since} placeholder="2026-10-01T00:00:00Z" /></label>
      <label htmlFor="change-until">Through (ISO timestamp with timezone)<input id="change-until" name="until" maxLength={64} defaultValue={filters.until} placeholder="2026-10-16T23:59:59Z" /></label>
      <label htmlFor="change-order">Observation order<select id="change-order" name="order" defaultValue={filters.order || "newest"}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label>
      <div className="button-row"><button className="button button-primary" type="submit">Apply change filters</button><Link className="button button-secondary" href={overviewHref("/changes", scope)}>Clear change filters</Link></div>
    </form>
    <EvidenceBar evidence={current?.evidence} knowledgeVersion={current?.knowledge_version} warnings={current?.warnings} />
    {feed.error ? <StatePanel title="Independent changes unavailable" message={feed.error.message} tone="error" /> : feed.loading
      ? <StatePanel title="Loading independent changes" message="Reading the authorized change projection, independently of incident timelines." tone="loading" />
      : <>
        <p>{feed.data?.pagination?.total ?? 0} matching observations in {feed.data?.data.authorized_count ?? 0} authorized projection rows. Counts and filters apply before server pagination; not estate totals.</p>
        {feed.data?.data.facet_metadata.source.truncated && <p>Source suggestions show {feed.data.data.facet_metadata.source.returned} of {feed.data.data.facet_metadata.source.total} distinct authorized source labels. An exact typed source still searches the full projection.</p>}
        {!rows.length ? <StatePanel title="No matching observations in the loaded projection" message="This does not establish that no changes occurred. Adjust filters or review a previous page." />
          : <ol className="change-observation-list">{rows.map(row => <li key={row.observation_id}>
            <div className="change-observation-summary">
              <div className="timeline-event-labels"><StatusBadge label={row.category} tone="info" compact /><time dateTime={row.changed_at}>{formatDateTime(row.changed_at)}</time></div>
              <h3>{row.summary}</h3>
              <p>Resource: {row.resource_name} · {row.change_type}</p>
            </div>
            <details><summary>Observation identity and mapping</summary>
              <dl className="observation-metadata">
                <div><dt>Change ID</dt><dd>{row.change_id}</dd></div>
                <div><dt>Source</dt><dd>{row.source}</dd></div>
                <div><dt>Application</dt><dd>{row.application}</dd></div>
                <div><dt>Service</dt><dd>{row.business_service}</dd></div>
                <div><dt>Environment</dt><dd>{row.environment}</dd></div>
              </dl>
            </details>
            <details><summary>Compare reported configuration states</summary>
              <p>Allowlisted fields from this change only, not the current baseline. Missing states are unreported, never inferred additions or removals. Other property names and values are withheld.</p>
              {row.configuration.fields.length ? <><p>Scroll horizontally to inspect all columns.</p><div className="table-scroll" role="region" aria-label={`Configuration states for ${row.change_id}`} tabIndex={0}>
                <table className="operations-table"><caption>Reported before/after states</caption>
                  <thead><tr><th>Field</th><th>Before</th><th>After</th><th>Comparison</th></tr></thead>
                  <tbody>{row.configuration.fields.map(field => <tr key={field.field}><td>{field.field}</td><td>{cellText(field.before)}</td><td>{cellText(field.after)}</td><td>{field.comparison === "not_comparable" ? "Not comparable" : field.comparison === "changed" ? "Changed" : "Unchanged"}</td></tr>)}</tbody>
                </table>
              </div></> : <p>No allowlisted configuration fields reported.</p>}
              <p>{row.configuration.withheld_field_count} other property names withheld.</p>
            </details>
          </li>)}</ol>}
        {rows.length > 0 ? <TablePagination pagination={feed.data?.pagination} pageRows={rows.length} page={page} pageSize={PAGE_SIZE} onPageChange={next => navigate(filters, next)} label="matching projected changes" />
          : page > 0 ? <button type="button" className="button button-secondary" onClick={() => navigate(filters, page - 1)}>Review previous change page</button> : null}
      </>}
    <CopilotDrawer open={copilotOpen} onClose={() => setCopilotOpen(false)} contextLabel="Independent change observations" requestedScope={context.requestedScope} snapshot={context.snapshot} starterQuestions={context.starterQuestions} />
  </section>;
}
