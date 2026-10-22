"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { TablePagination } from "@/components/ui/TablePagination";
import { useApi } from "@/hooks/useApi";
import { formatDateTime } from "@/lib/format";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { useScope } from "@/lib/scope-context";
import { inventoryApi } from "@/lib/services";
import type { InventoryResourceQuery } from "@/lib/types";

const PAGE_SIZE = 25;
const FACETS = ["family", "resource_type", "resource_group"] as const;
const LABELS = { family: "Family", resource_type: "Resource type", resource_group: "Resource group" };

function AssetDetail({ resourceId, scope }: { resourceId: string; scope: ScopeSelection }) {
  const detail = useApi(() => inventoryApi.asset(resourceId, scope), []);
  const response = detail.data;
  if (detail.loading) return <StatePanel title="Loading asset" message="Resolving the exact identity in your current scope." tone="loading" />;
  if (detail.error) return <StatePanel title="Asset unavailable" message={detail.error.message} tone="error" action={<button type="button" onClick={detail.refetch}>Retry asset</button>} />;
  if (!response) return null;
  const data = response.data;
  const row = data.resource;
  const facts = [
    ["Resource identity", row.resource_id], ["Family", row.family], ["Resource type", row.resource_type],
    ["Subscription", row.subscription_id], ["Resource group", row.resource_group],
    ["Environment", row.environment], ["Location", row.location],
    ["SKU", row.sku], ["Tier", row.tier], ["Runtime", row.runtime],
    ["Provisioning state", row.provisioning_state],
    ["OS", [row.os_name, row.os_version].filter(Boolean).join(" ")],
    ["Source", row.source_type], ["Observed", row.observed_at ? formatDateTime(row.observed_at) : ""],
    ["Management group", row.containment.management_group_id],
  ];
  return (
    <section className="panel" aria-label="Exact inventory asset">
      <h2>{row.resource_name || row.resource_id}</h2>
      <p className="muted">Published observation, not a live resource-health assessment. Missing fields are not inferred.</p>
      <dl className="inventory-asset-facts">
        {facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || "Not reported"}</dd></div>)}
      </dl>
      <p className="muted">Publication generation: {data.generation_id || "Not reported"} · Query contract: {data.query_version}</p>
      <EvidenceBar evidence={response.evidence} warnings={response.warnings} />
    </section>
  );
}

function AssetExplorer({ scope, filters, page, resourceId }: {
  scope: ScopeSelection; filters: InventoryResourceQuery; page: number; resourceId: string;
}) {
  const router = useRouter();
  const [draft, setDraft] = useState(filters.q || "");
  const result = useApi(() => inventoryApi.resources(scope, page * PAGE_SIZE, PAGE_SIZE, filters), []);
  const response = result.data;
  const data = response?.data;
  function href(next: InventoryResourceQuery, nextPage = 0, selected = "") {
    const query = scopeToSearchParams(scope);
    Object.entries(next).forEach(([key, value]) => { if (value) query.set(key, value); });
    if (nextPage) query.set("page", String(nextPage + 1));
    if (selected) query.set("resource_id", selected);
    return `/inventory/assets?${query.toString()}`;
  }
  return (
    <main className="page-shell inventory-page">
      <PageHeader title="Inventory assets" description="Explore published OS and Azure resource observations using server-scoped filters. Counts describe the published projection, not complete estate coverage."
        actions={<Link className="button" href={`/inventory?${scopeToSearchParams(scope)}`}>Grouped inventory</Link>} />
      <form className="inventory-filters" onSubmit={(event) => { event.preventDefault(); if (draft === (filters.q || "")) result.refetch(); else router.push(href({ ...filters, q: draft })); }}>
        <label>Search asset<input value={draft} maxLength={256} onChange={(event) => setDraft(event.target.value)} placeholder="Name, identity or resource type" /></label>
        {FACETS.map((key) => {
          const options = data?.facets?.[key] || [];
          const selected = filters[key];
          return <label key={key}>{LABELS[key]}<select aria-label={LABELS[key]} value={selected || ""} onChange={(event) => router.push(href({ ...filters, [key]: event.target.value }))}>
            <option value="">All authorized {LABELS[key].toLowerCase()} values</option>
            {selected && !options.some((option) => option.value === selected) && <option value={selected}>{selected} (not represented)</option>}
            {options.map((option) => <option key={option.value} value={option.value}>{option.value} ({option.count})</option>)}
          </select></label>;
        })}
        <button type="submit" className="button button-primary">Apply search</button>
        <Link className="button" href={href({})}>Reset filters</Link>
      </form>
      {resourceId && <><div className="detail-actions"><Link href={href(filters, page)} className="button">Close asset</Link></div>
        <AssetDetail key={resourceId} resourceId={resourceId} scope={scope} /></>}
      {result.loading && <StatePanel title="Loading published assets" message="Applying scope and filters before pagination." tone="loading" />}
      {result.error && <StatePanel title="Inventory assets unavailable" message={result.error.message} tone="error" action={<button type="button" onClick={result.refetch}>Retry inventory</button>} />}
      {!result.loading && !result.error && data && response && <>
        <p className="muted">{result.data?.pagination?.total ?? 0} matching observations · {data.represented_count ?? "Unreported"} authorized observations before filters. Facets cover the authorized projection, not just this page.</p>
        {data.resources.length === 0 ? <StatePanel title="No matching published assets" message="Adjust the filters or verify publication coverage. An empty result does not prove an empty estate." /> :
          <section className="data-table-wrap" aria-label="Published assets"><div className="table-scroll" tabIndex={0} role="region" aria-label="Published asset records"><table className="data-table"><thead><tr><th>Asset</th><th>Family / type</th><th>Subscription / resource group</th></tr></thead>
            <tbody>{data.resources.map((row) => <tr key={`${row.family}:${row.resource_id}`} aria-selected={resourceId.toLowerCase() === row.resource_id.toLowerCase()}>
              <td><Link className="table-primary-link" href={href(filters, page, row.resource_id)}>{row.resource_name || row.resource_id}</Link><span className="table-subtitle resource-id-cell">{row.resource_id}</span></td>
              <td>{row.family}<span className="table-subtitle">{row.resource_type}</span></td><td>{row.subscription_id}<span className="table-subtitle">{row.resource_group || "Not reported"}</span></td>
            </tr>)}</tbody></table></div>
            <TablePagination pagination={result.data?.pagination} pageRows={data.resources.length} page={page} pageSize={PAGE_SIZE} onPageChange={(next) => router.push(href(filters, next))} label="observations" />
          </section>}
        <p className="muted">Publication generation: {data.generation_id || "Not reported"} · Query contract: {data.query_version}</p>
        {Object.entries(data.family_availability).map(([family, status]) => <p key={family} className="muted">{family}: {status.state} · {status.row_count} authorized observations represented</p>)}
        <EvidenceBar evidence={response.evidence} warnings={response.warnings} />
      </>}
    </main>
  );
}

/** Bookmarkable authorized cross-family inventory exploration and exact asset lookup. */
export default function InventoryAssetsPage() {
  const { scope } = useScope();
  const params = useSearchParams();
  const filters: InventoryResourceQuery = Object.fromEntries(["q", ...FACETS].map((key) => [key, params.get(key) || ""]));
  const resourceId = params.get("resource_id") || "";
  const rawPage = params.get("page") || "1";
  const invalid = !/^[1-9]\d{0,3}$/.test(rawPage) || Number(rawPage) > 4001 ||
    Object.values(filters).some((value) => value.length > 256 || /[\u0000-\u001f\u007f]/.test(value)) ||
    resourceId.length > 2048 || /[\u0000-\u001f\u007f]/.test(resourceId);
  if (invalid) return <StatePanel title="Unsupported inventory bookmark" message="Filter or identity values are invalid. Open Inventory and select an authorized asset again." tone="error" />;
  return <AssetExplorer key={`${JSON.stringify(scope)}:${params.toString()}`} scope={scope} filters={filters} page={Number(rawPage) - 1} resourceId={resourceId} />;
}
