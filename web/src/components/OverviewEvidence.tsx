import Link from "next/link";
import { overviewHref, type overviewPosture } from "@/lib/overview";
import type { ScopeSelection } from "@/lib/scope";
import type { Envelope } from "@/lib/types";

interface OverviewSource {
  id: string;
  label: string;
  path: string;
  envelope?: Envelope<unknown>;
  loadedRows?: number;
}

/** Explain current loaded evidence, never imply retained history or a complete-estate audit. */
export function OverviewEvidence({ posture, sources, scope }: {
  posture: ReturnType<typeof overviewPosture>;
  sources: OverviewSource[];
  scope: ScopeSelection;
}) {
  return <section className="card dashboard-section" aria-label="Overview score and evidence">
    <div className="card-header"><div><h2>Why this posture score?</h2>
      <p>Version 1 operator heuristic, not an SLA, compliance score, or measured probability of loss.</p></div></div>
    <div className="card-body">
      <p>Start at 100, subtract the contributions below, and floor the result at zero.
        Weights are fixed product rules, not learned risk estimates. Missing inputs withhold the score rather than count as zero.</p>
      <div className="data-table-wrap" tabIndex={0} role="region" aria-label="Weighted contributors, horizontally scrollable"><table className="data-table">
        <caption>Current weighted contributors; unlike units are not distinct resources</caption>
        <thead><tr><th>Contributor</th><th>Observed count</th><th>Weight</th><th>Raw deduction</th><th>Review</th></tr></thead>
        <tbody>{posture.contributors.map(row => <tr key={row.id}>
          <th scope="row">{row.label}</th><td>{row.count ?? "Unavailable"}</td><td>{row.weight}</td>
          <td>{row.deduction ?? "Unavailable"}</td><td><Link href={overviewHref(row.path, scope)}>Review {row.id}</Link></td>
        </tr>)}</tbody>
      </table></div>
      <div className="evidence-explanation-grid">
        <div>
          <h3>How to interpret the score</h3>
          <p>Raw deduction: {posture.rawDeduction ?? "unavailable"}; displayed score: {posture.score ?? "unavailable"}.
            {" "}Thresholds: controlled ≥80, needs attention 60–79, elevated &lt;60.
            Saturation at zero can hide further count increases; review the raw contributors.</p>
          <p>Situations use only the loaded page, while exposure and Network counts use their respective summaries.
            A vulnerability finding is not a distinct CVE or affected server. The sources may overlap and were not read atomically.
            Without a declared Network design policy, structural checks do not establish design conformance.
            Counts alone do not explain causality. Connection readiness does not contribute to this formula.</p>
        </div>
        <div>
          <h3>Evidence coverage and next checks</h3>
          <p>These are source-read and registry observations, not inventory completeness. Evidence freshness is reported by each source;
            no timestamp, evidence row, or warning is silently converted into coverage. Synchronization does not prove Fabric publication.</p>
          <p className="muted">On narrow screens, scroll each table horizontally to reach its review links.</p>
        </div>
      </div>
      <div className="data-table-wrap" tabIndex={0} role="region" aria-label="Source coverage, horizontally scrollable"><table className="data-table">
        <caption>Selected-scope reads; unqueried pages and unreported totals remain unknown</caption>
        <thead><tr><th>Source</th><th>Read / extent</th><th>Evidence freshness</th><th>Warnings</th><th>Next check</th></tr></thead>
        <tbody>{sources.map(({ id, label, path, envelope, loadedRows }) => {
          const extent = !envelope ? "Unavailable" : loadedRows === undefined ? "Summary returned; extent is source-defined"
            : `${loadedRows} loaded / ${envelope.pagination ? `${envelope.pagination.total} reported` : "total unreported"}${envelope.pagination?.next_offset != null || (envelope.pagination && envelope.pagination.total > loadedRows) ? "; partial page" : ""}`;
          const evidence = envelope?.evidence ?? [];
          const fresh = evidence.filter(row => row.freshness === "fresh").length;
          return <tr key={id}><th scope="row">{label}</th><td>{extent}</td>
            <td>{evidence.length ? `${fresh}/${evidence.length} evidence rows reported fresh; ${evidence.length - fresh} aging, stale, or unknown` : "Unreported"}</td>
            <td>{envelope ? envelope.warnings?.length ?? 0 : "Unavailable"}</td>
            <td><Link href={overviewHref(path, scope)}>Review {label.toLowerCase()} coverage</Link></td>
          </tr>;
        })}</tbody>
      </table></div>
    </div>
  </section>;
}
