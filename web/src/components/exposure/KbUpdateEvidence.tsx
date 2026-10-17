"use client";

import type { KbDetail } from "@/lib/types";

/** Explain recorded update guidance and latest-snapshot status without applicability claims. */
export function KbUpdateEvidence({ kbId, detail }: { kbId: string; detail: KbDetail | null }) {
  const counts = detail?.installation_status_counts;
  const source = Object.values(detail?.enrichment?.sources ?? {}).find(row => row.source.toLowerCase() === "msrc" && row.identifier.toUpperCase() === kbId);
  const products = detail?.update_guidance?.product_ids ?? [];
  return <section className="exposure-detail-section kb-update-evidence" aria-label="KB update evidence">
    <div className="card-header"><h2>Update prerequisites and recorded posture</h2></div>
    <div className="card-body">
      <p>Metadata describes the latest authorized Silver KB snapshot, independently of the filtered finding page.
        Missing records, product names in titles and public KB associations do not establish asset applicability.</p>
      <dl className="exposure-definition-grid">
        <div><dt>Snapshot generation</dt><dd className="exposure-long-value">{detail?.generation || "Unreported"}</dd></div>
        <div><dt>Snapshot coverage / freshness</dt><dd>{detail?.snapshot ? `${detail.snapshot.completeness} / ${detail.snapshot.freshness}` : "Unknown"}</dd></div>
        <div><dt>Snapshot source observed</dt><dd>{detail?.snapshot?.as_of || "Unreported"}</dd></div>
        <div><dt>MSRC status</dt><dd>{source ? `${source.status}; ${source.stale ? "stale" : "not marked stale"}; last-known-good ${source.has_last_known_good ? "retained" : "absent"}` : "Unreported"}</dd></div>
        <div><dt>MSRC source observed</dt><dd>{source?.source_at || "Unreported"}</dd></div>
        <div><dt>Recorded product identifiers</dt><dd className="exposure-long-value">{products.length ? products.join(", ") : "Unknown; no product identifiers recorded"}</dd></div>
      </dl>
      <div className="data-table-wrap" tabIndex={0} role="region" aria-label="Update dependency evidence, horizontally scrollable">
        <table className="data-table"><caption>Provider dependency evidence: not collected by the current catalog contract</caption>
          <thead><tr><th>Required review</th><th>Recorded evidence</th></tr></thead><tbody>
            <tr><th scope="row">Prerequisite updates / servicing stack</th><td>Unknown; not supplied by this source projection</td></tr>
            <tr><th scope="row">Supersedes / superseded by</th><td>Unknown; no provider relationship graph is available</td></tr>
            <tr><th scope="row">Reboot and OS/build requirements</th><td>Unknown; requires product-specific provider review</td></tr>
          </tbody>
        </table>
      </div>
      <p>Unknown is not “no prerequisites” or “no reboot needed”. Inspect the
        {" "}<a href={`https://support.microsoft.com/help/${kbId.replace(/^KB/, "")}`} target="_blank" rel="noreferrer">Microsoft support article for {kbId}</a>
        {" "}and <a href="https://msrc.microsoft.com/update-guide/" target="_blank" rel="noreferrer">Microsoft Security Update Guide</a>.
        These reference links are not fetched, attested or validated by this portal.</p>
      <h3>Recorded installation status distribution</h3>
      <p>Distinct targets within this KB snapshot, before the 100-row sample bound. Source “installed” is a recorded inventory status,
        not proof that this portal executed an update, verified a fix or checked post-deploy health. Other statuses remain unclassified.</p>
      {!counts ? <p role="status">Whole-snapshot status counts are unavailable. Do not derive installation coverage from the loaded sample.</p> :
        <dl className="exposure-definition-grid">
          <div><dt>Observed targets</dt><dd>{counts.observed_targets}</dd></div>
          <div><dt>Missing</dt><dd>{counts.missing}</dd></div>
          <div><dt>Installation failed</dt><dd>{counts.installation_failed}</dd></div>
          <div><dt>Recorded installed</dt><dd>{counts.installed}</dd></div>
          <div><dt>Other / unclassified</dt><dd>{counts.other}</dd></div>
        </dl>}
      {detail?.target_status_observations && <details>
        <summary>Inspect sampled target status observations</summary>
        <p>{detail.target_status_observations.length} loaded / {counts?.observed_targets ?? "unknown"} observed targets;
          {" "}{detail.target_status_observations_truncated === true ? "sample is truncated" : detail.target_status_observations_truncated === false ? "complete snapshot sample" : "sample extent unknown"}.
          These are latest recorded observations, not retained verification history.</p>
        <ul>{detail.target_status_observations.map(row => <li className="exposure-long-value" key={row.target_id}>
          {row.target_id}: {row.status}; source observed {row.observed_at || "unreported"}</li>)}</ul>
      </details>}
      <p>Tables scroll horizontally on narrow screens. Maintenance review and subsequent verification require separate, explicitly sourced records.</p>
    </div>
  </section>;
}
