"use client";

import { useExposureSection } from "@/hooks/useExposureSection";
import { exposureRetentionKey, type ExposureQueryState } from "@/lib/exposure-query-state";
import { vulnerabilityApi } from "@/lib/services";
import { validateExposureFacets } from "@/lib/exposure-facets";
import type { ExposureFacets } from "@/lib/types";
import { SourceSectionState } from "./SourceSectionState";

/** Independent whole-query aggregates, never accumulated cursor-page samples. */
export function PatchQueueSummary({ query }: { query: ExposureQueryState }) {
  const identity = exposureRetentionKey(query);
  const section = useExposureSection<ExposureFacets>({
    queryKey: `${identity}|queue-summary`, retentionKey: `${identity}|queue-summary`,
    load: async ({ signal }) => {
      const result = await vulnerabilityApi.exposureFacets(query, ["severity", "sla_state", "target_kind", "current_state"], { signal });
      validateExposureFacets(result, query);
      return result;
    },
    isEmpty: data => data.total_count === 0,
  });
  const data = section.data;
  return <section className="card queue-card" aria-label="Whole-query patch aggregates">
    <div className="card-header"><div><h2>Whole-query finding aggregates</h2>
      <p>All findings matching the selected filters in the loaded generation, not just this cursor page.</p></div></div>
    <div className="card-body">
      <SourceSectionState sourceName="Whole-query patch aggregates" itemLabel="findings" state={section}>
        {data && <>
          <p>{data.total_count.toLocaleString("en-US")} matching findings; generation {data.generation}.
            Counts are findings, not distinct machines, images, patches or vulnerabilities. Groups overlap across dimensions.
            Excluded source coverage is separate from this query total.</p>
          <div className="data-table-wrap" tabIndex={0} role="region" aria-label="Whole-query classification counts, horizontally scrollable">
            <table className="data-table"><caption>Authoritative filtered finding counts</caption>
              <thead><tr><th>Dimension</th><th>Classification</th><th>Matching findings</th></tr></thead>
              <tbody>{["severity", "sla_state", "target_kind", "current_state"].flatMap(group => {
                const rows = data.facets[group];
                if (!rows) return [<tr key={group}><th scope="row">{group}</th><td>Vocabulary unavailable</td><td>Unknown</td></tr>];
                const classified = rows.reduce((sum, row) => sum + row.count, 0);
                return [
                  ...rows.map(row => <tr key={`${group}:${row.value}`}><th scope="row">{group}</th><td>{row.value}</td><td>{row.count.toLocaleString("en-US")}</td></tr>),
                  ...(classified < data.total_count ? [<tr key={`${group}:unclassified`}><th scope="row">{group}</th><td>Not represented in this vocabulary</td><td>{(data.total_count - classified).toLocaleString("en-US")}</td></tr>] : []),
                  ...(!rows.length && !data.total_count ? [<tr key={`${group}:empty`}><th scope="row">{group}</th><td>No matching findings</td><td>0</td></tr>] : []),
                ];
              })}</tbody>
            </table>
          </div>
        </>}
      </SourceSectionState>
    </div>
  </section>;
}
