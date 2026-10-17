import Link from "next/link";
import { encodeExposureQueryState, type ExposureQueryState } from "@/lib/exposure-query-state";
import type { ExposureFacets } from "@/lib/types";

/** Transparent advisory ordering, not a risk score, workflow gate or execution plan. */
export function ExposureDecision({ data, sourceStatus, query }: { data: ExposureFacets | null; sourceStatus: string; query: ExposureQueryState }) {
  const count = (group: string, value: string) => data?.facets[group]
    ? data.facets[group].find(row => row.value.toLowerCase() === value)?.count ?? 0 : null;
  const critical = count("severity", "critical"), high = count("severity", "high"), overdue = count("sla_state", "overdue");
  const classifiedSla = data?.facets.sla_state?.reduce((sum, row) => sum + (["overdue", "within_sla"].includes(row.value.toLowerCase()) ? row.count : 0), 0);
  const unclassified = classifiedSla === undefined || !data ? null : Math.max(0, data.total_count - classifiedSla);
  const completeness = data?.contract.completeness;
  const filtered = (filters: ExposureQueryState["filters"]) => `/exposure/patch-priorities?${encodeExposureQueryState({ ...query, filters })}`;
  return <section className="card queue-card exposure-decision" aria-label="Exposure review order">
    <div className="card-header"><div><h2>Decide what to review first</h2>
      <p>Evidence quality first, then reported severity and recorded SLA. No combined risk score is invented.</p></div></div>
    <div className="card-body">
      <p>This advisory order uses only the loaded generation {data?.generation ?? "(unavailable)"} and source state {sourceStatus}.
        Counts can overlap and do not imply exploitability, business impact, an executable fix or a verified outcome.</p>
      <ol className="exposure-decision-list">
        <li><div><h3>Qualify evidence coverage</h3>
          <p>Evidence {completeness?.state ?? "unavailable"}; represented connections {completeness?.represented_connections ?? "unknown"} / {completeness?.expected_connections ?? "unknown"}.
            {" "}Missing or excluded evidence is not safe exposure. {unclassified === null ? "SLA classification coverage is unavailable." : `${unclassified} findings lack an exact overdue/within_sla classification.`}</p>
        </div><a className="button" href="#exposure-recovery">Inspect recovery review</a></li>
        <li><div><h3>Review reported critical findings</h3><p>{critical ?? "Unknown"} critical findings in the loaded severity vocabulary. Severity alone does not prove active exploitation.</p></div>
          <Link className="button" href={filtered({ severity: "critical" })}>Review critical findings</Link></li>
        <li><div><h3>Review recorded overdue findings</h3><p>{overdue ?? "Unknown"} findings have the exact overdue classification. Indeterminate and unreported SLA states are not compliant.</p></div>
          <Link className="button" href={filtered({ sla_state: "overdue" })}>Review overdue findings</Link></li>
        <li><div><h3>Review reported high findings</h3><p>{high ?? "Unknown"} high findings remain a separate severity queue; no remediation dependency or automatic scheduling is implied.</p></div>
          <Link className="button" href={filtered({ severity: "high" })}>Review high findings</Link></li>
      </ol>
    </div>
  </section>;
}
