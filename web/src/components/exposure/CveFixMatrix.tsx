"use client";

import Link from "next/link";
import { SCOPE_DIMENSIONS } from "@/lib/scope";
import type { ScopeSelection } from "@/lib/scope";
import type { ExposureQueryState } from "@/lib/exposure-query-state";
import type { ExposureExternalCatalog, ExposureExternalCatalogItem, ExposureFinding, ExposurePage } from "@/lib/types";

type MatrixFinding = ExposureFinding & { missing_kb?: string };
const kb = (value: unknown) => typeof value === "string" && /^KB\d+$/i.test(value.trim()) ? value.trim().toUpperCase() : "";
const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())) : [];
const scopeMatches = (left: ScopeSelection, right: ScopeSelection) => SCOPE_DIMENSIONS.every(dimension =>
  JSON.stringify([...(left[dimension] ?? [])].sort()) === JSON.stringify([...(right[dimension] ?? [])].sort()));

/** Separates public update associations from loaded, authorized asset observations. */
export function CveFixMatrix({ cveId, catalog, catalogScope, page, pageScope, query, kbHref }: {
  cveId: string;
  catalog: ExposureExternalCatalog<ExposureExternalCatalogItem> | null;
  catalogScope: ScopeSelection;
  page: ExposurePage<MatrixFinding> | null;
  pageScope: ScopeSelection;
  query: ExposureQueryState;
  kbHref: (identifier: string) => string;
}) {
  const aligned = Boolean(catalog && page && catalog.item.cve_id.toUpperCase() === cveId.toUpperCase()
    && catalog.catalog_scope === "external_public_metadata" && catalog.environment_membership_included === false
    && catalog.generation === page.generation && (!query.generation || query.generation === page.generation)
    && scopeMatches(catalogScope, query.scope) && scopeMatches(pageScope, query.scope));
  const sources = aligned ? Object.values(catalog!.item.sources).filter(source => source.source.toLowerCase() === "msrc") : [];
  const sourceIds = sources.map(source => kb(source.payload?.kb_id) || kb(source.identifier)).filter(Boolean);
  const nvd = aligned ? Object.values(catalog!.item.sources).filter(source => source.source.toLowerCase() === "nvd") : [];
  const associations = nvd.flatMap(source => strings(source.payload?.associated_kbs)).map(kb).filter(Boolean);
  const findings = aligned ? page!.items.filter(row => row.weakness_id.toUpperCase() === cveId.toUpperCase()) : [];
  const identifiers = Array.from(new Set([...sourceIds, ...associations, ...findings.map(row => kb(row.missing_kb)).filter(Boolean)])).sort();
  return <section className="exposure-detail-section cve-fix-matrix" aria-label="CVE fix evidence matrix">
    <div className="card-header"><h2>Fix evidence matrix</h2></div>
    <p>Public KB associations are not asset applicability or an installation recommendation.
      Finding mappings cover only this loaded page, not every matching asset. No update is selected by alphabetical order.</p>
    <p>Applicability is unverified. Confirm product, OS/build, dependencies and current provider state before governed review.
      The table scrolls horizontally on narrow screens.</p>
    {!aligned ? <p role="status">Fix evidence is unavailable until catalog and findings match this CVE, scope and generation. Refresh the independent sources before comparing them.</p> : <>
      <p>Generation {page!.generation}; {page!.items.length} loaded of {page!.total_count} matching findings.
        Product versions, prerequisites, supersedence, reboot requirements and verified fixed versions are not supplied by this catalog contract.</p>
      <p>{findings.filter(row => !kb(row.missing_kb)).length} loaded findings have no recorded per-row KB association.
        An absent mapping is unknown, not proof that no update is needed.</p>
      {!identifiers.length ? <p>No recorded KB association is available in this catalog and loaded page. For image findings, review image provenance and workload ownership before considering a rebuild.</p> :
        <div className="data-table-wrap" tabIndex={0} role="region" aria-label="Fix evidence matrix, horizontally scrollable">
          <table className="data-table"><caption>Recorded KB and loaded finding associations</caption>
            <thead><tr><th>Update association</th><th>Provider evidence</th><th>Loaded finding mapping</th></tr></thead>
            <tbody>{identifiers.map(identifier => {
              const records = sources.filter(source => (kb(source.payload?.kb_id) || kb(source.identifier)) === identifier);
              const associationRecords = nvd.filter(source => strings(source.payload?.associated_kbs).some(value => kb(value) === identifier));
              const products = Array.from(new Set(records.flatMap(source => strings(source.payload?.product_ids)))).sort();
              const mapped = findings.filter(row => kb(row.missing_kb) === identifier);
              return <tr key={identifier}><td><Link className="table-primary-link" href={kbHref(identifier)}>{identifier}</Link>
                <p>Recorded product identifiers: <span>{products.length ? products.join(", ") : "Unknown; no product identifiers recorded"}</span></p></td>
                <td>{records.length ? records.map((source, index) => <p key={`${source.identifier}:${index}`} className="exposure-long-value">
                  MSRC {source.identifier}: {source.status}; {source.stale ? "stale" : "not marked stale"};
                  {" "}source observed {source.source_at || "unreported"}; last-known-good {source.has_last_known_good ? "retained" : "absent"}.
                </p>) : <p>No durable MSRC status; association only.</p>}
                  {associationRecords.map((source, index) => <p key={`nvd:${index}`} className="exposure-long-value">
                    NVD KB association: {source.status}; {source.stale ? "stale" : "not marked stale"}; source observed {source.source_at || "unreported"}.
                  </p>)}
                </td>
                <td>{mapped.length} loaded rows explicitly name this KB{mapped.length > 0 && <details><summary>Inspect mapped targets for {identifier}</summary>
                  <ul>{mapped.map(row => <li className="exposure-long-value" key={row.exposure_id}>{row.target_kind}: {row.target_id}; finding {row.exposure_id}; evidence {row.completeness}</li>)}</ul>
                </details>}</td></tr>;
            })}</tbody>
          </table>
        </div>}
    </>}
  </section>;
}
