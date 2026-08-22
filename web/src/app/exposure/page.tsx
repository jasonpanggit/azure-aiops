"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { CopilotLauncher } from "@/components/ui/CopilotLauncher";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { vulnerabilityApi } from "@/lib/services";

/** Service- and reachability-aware vulnerability prioritization workspace. */
export default function ExposurePage() {
  const { scope } = useScope();
  const [query, setQuery] = useState("");
  const [reachableOnly, setReachableOnly] = useState(false);
  const summary = useApi(() => vulnerabilityApi.summary(scope), [scope]);
  const exposures = useApi(() => vulnerabilityApi.exposures(scope), [scope]);
  const patches = useApi(() => vulnerabilityApi.patchPriorities(scope), [scope]);
  const sla = useApi(() => vulnerabilityApi.slaCompliance(scope), [scope]);

  const filteredPatches = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (patches.data?.data ?? []).filter((patch) => {
      if (reachableOnly && patch.reachable_server_count === 0) return false;
      if (!normalized) return true;
      return [patch.kb_id, patch.recommended_action, ...patch.cve_ids].some((value) =>
        String(value ?? "").toLowerCase().includes(normalized)
      );
    });
  }, [patches.data, query, reachableOnly]);

  const filteredCves = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (exposures.data?.data ?? []).filter((exposure) => {
      if (!exposure.cve_id.toUpperCase().startsWith("CVE-")) return false;
      if (reachableOnly && exposure.reachable_server_count === 0) return false;
      if (!normalized) return true;
      return [exposure.cve_id, exposure.missing_kb, exposure.recommended_patch, exposure.severity].some((value) =>
        String(value ?? "").toLowerCase().includes(normalized)
      );
    });
  }, [exposures.data, query, reachableOnly]);

  const bestPatch = patches.data?.data[0];
  const error = summary.error ?? exposures.error ?? patches.error;
  const loading = summary.loading || exposures.loading || patches.loading;

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Exposure management"
        title="Vulnerability exposure"
        description="Start with the patch KBs that reduce the most reachable business risk, then drill into the highest-priority CVEs those updates address."
        metadata={
          <>
            <span>{summary.data?.data.affected_business_service_count ?? 0} affected business services</span>
            <span>{summary.data?.data.affected_server_count ?? 0} affected servers</span>
            <span>Patch recommendations are advisory</span>
          </>
        }
      />

      <EvidenceBar
        evidence={[...(summary.data?.evidence ?? []), ...(exposures.data?.evidence ?? []), ...(patches.data?.evidence ?? [])]}
        knowledgeVersion={summary.data?.knowledge_version}
        warnings={[
          ...(summary.data?.warnings ?? []),
          ...(exposures.data?.warnings ?? []),
          ...(patches.data?.warnings ?? []),
        ]}
        fallbackTimestamp={summary.data?.data.freshness}
      />

      <CopilotLauncher
        starterQuestions={["which CVEs affect Payroll", "what should be patched first", "servers with failed patches"]}
      />

      <div className="metric-grid exposure-metrics">
        <MetricCard
          label="Critical CVEs"
          value={summary.data?.data.critical_count ?? "—"}
          detail={`${summary.data?.data.cve_count ?? 0} CVEs observed in the current scope`}
          tone={(summary.data?.data.critical_count ?? 0) > 0 ? "critical" : "success"}
        />
        <MetricCard
          label="Internet exposed"
          value={summary.data?.data.internet_exposed_count ?? "—"}
          detail="Findings with an observed Internet-reachable path"
          tone={(summary.data?.data.internet_exposed_count ?? 0) > 0 ? "critical" : "success"}
        />
        <MetricCard
          label="Reachable servers"
          value={summary.data?.data.reachable_server_count ?? "—"}
          detail="Affected hosts reachable over observed network paths"
          tone={(summary.data?.data.reachable_server_count ?? 0) > 0 ? "warning" : "success"}
        />
        <MetricCard
          label="Highest-value patch"
          value={bestPatch?.kb_id ?? "—"}
          detail={
            bestPatch
              ? `${Math.round(bestPatch.expected_risk_reduction)} expected risk reduction across ${bestPatch.affected_business_service_count} services`
              : "No patch priority available"
          }
          tone={bestPatch ? "success" : "default"}
        />
      </div>

      {bestPatch && (
        <section className="best-action-card">
          <div className="best-action-rank">01</div>
          <div>
            <span>Highest risk reduction per patch</span>
            <h2>{bestPatch.kb_id}</h2>
            <p>{bestPatch.recommended_action}</p>
          </div>
          <div className="best-action-facts">
            <div>
              <strong>{bestPatch.cve_ids.length}</strong>
              <span>CVEs removed</span>
            </div>
            <div>
              <strong>{bestPatch.reachable_server_count}</strong>
              <span>Reachable servers</span>
            </div>
            <div>
              <strong>{bestPatch.affected_business_service_count}</strong>
              <span>Business services</span>
            </div>
          </div>
          <Link className="button button-primary" href={`/exposure/kbs/${encodeURIComponent(bestPatch.kb_id)}`}>
            Open KB details
          </Link>
        </section>
      )}

      {sla.data?.data && (
        <section className="card">
          <div className="card-header">
            <div>
              <h2>SLA compliance &amp; aging</h2>
              <p>
                Snapshot-in-time view of currently open findings: how much is within its remediation SLA vs.
                overdue, and how long open findings have been outstanding.
              </p>
            </div>
          </div>
          <div className="card-body">
            <div className="metric-grid exposure-metrics">
              <MetricCard
                label="Overall compliance"
                value={
                  sla.data.data.overall_compliance_rate === null
                    ? "—"
                    : `${Math.round(sla.data.data.overall_compliance_rate * 100)}%`
                }
                detail={`${sla.data.data.compliant_count} of ${sla.data.data.tracked_count} tracked findings within SLA`}
                tone={(sla.data.data.overdue_count ?? 0) > 0 ? "warning" : "success"}
              />
              <MetricCard
                label="Overdue findings"
                value={sla.data.data.overdue_count}
                detail={`${sla.data.data.open_count} total open findings`}
                tone={(sla.data.data.overdue_count ?? 0) > 0 ? "critical" : "success"}
              />
            </div>
            <div className="table-scroll">
              <table className="operations-table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Open</th>
                    <th>Compliance</th>
                    <th>Overdue</th>
                    <th>Avg days open</th>
                    <th>Max days open</th>
                  </tr>
                </thead>
                <tbody>
                  {sla.data.data.by_severity.map((row) => (
                    <tr key={row.severity}>
                      <td><StatusBadge label={row.severity} tone={statusTone(row.severity)} compact /></td>
                      <td>{row.open_count}</td>
                      <td>
                        {row.compliance_rate === null ? "—" : `${Math.round(row.compliance_rate * 100)}%`}
                      </td>
                      <td>{row.overdue_count}</td>
                      <td>{row.avg_days_open}</td>
                      <td>{row.max_days_open}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="table-secondary" style={{ marginTop: "0.75rem" }}>
              Aging: {Object.entries(sla.data.data.aging_buckets).map(([bucket, count]) => `${bucket}: ${count}`).join(" · ")}
            </div>
          </div>
        </section>
      )}

      <div className="queue-toolbar">
        <label className="search-field">
          <span>Find exposure</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="CVE, KB, service scope, or severity"
          />
        </label>
        <label className="toggle-field">
          <input
            type="checkbox"
            checked={reachableOnly}
            onChange={(event) => setReachableOnly(event.target.checked)}
          />
          <span>Reachable only</span>
        </label>
      </div>

      {error ? (
        <StatePanel
          title="Exposure intelligence is unavailable"
          message={`${error.message}. The workbench will not treat missing vulnerability data as an all-clear state.`}
          tone="error"
        />
      ) : loading ? (
        <StatePanel
          title="Ranking vulnerability exposure"
          message="Combining KB patch state, CVE intelligence, network reachability, and business service criticality."
          tone="loading"
        />
      ) : filteredPatches.length === 0 && filteredCves.length === 0 ? (
        <StatePanel
          title="No exposure matches these filters"
          message="Adjust the search or reachability filter. Results reflect the current operating context."
        />
      ) : (
        <div className="exposure-landing-sections">
          <section className="card queue-card">
            <div className="card-header">
              <div>
                <h2>Patch priorities by KB</h2>
                <p>Operational patch queue. Open a KB to see the CVEs it resolves and the assets still missing it.</p>
              </div>
            </div>
            {filteredPatches.length === 0 ? (
              <div className="card-body">
                <p className="muted">No KB patch priorities match the current filters.</p>
              </div>
            ) : (
              <div className="table-scroll">
                <table className="operations-table exposure-table">
                  <thead>
                    <tr>
                      <th>Priority</th>
                      <th>KB</th>
                      <th>CVEs resolved</th>
                      <th>Reachability</th>
                      <th>Business impact</th>
                      <th>Risk reduction</th>
                      <th aria-label="Open" />
                    </tr>
                  </thead>
                  <tbody>
                    {filteredPatches.map((patch, index) => (
                      <tr key={patch.kb_id}>
                        <td>
                          <span className="rank-number">{String(index + 1).padStart(2, "0")}</span>
                        </td>
                        <td>
                          <Link className="table-primary-link" href={`/exposure/kbs/${encodeURIComponent(patch.kb_id)}`}>
                            {patch.kb_id}
                          </Link>
                          <div className="table-secondary">{patch.recommended_action}</div>
                        </td>
                        <td>
                          <strong>{patch.cve_ids.length}</strong>
                          <div className="table-secondary">{patch.cve_ids.slice(0, 3).join(", ") || "Advisory-only KB"}</div>
                        </td>
                        <td>
                          <StatusBadge
                            label={patch.reachable_server_count ? "Reachable" : "No path observed"}
                            tone={patch.reachable_server_count ? "warning" : "neutral"}
                          />
                          <div className="table-secondary">{patch.reachable_server_count} reachable servers</div>
                        </td>
                        <td>
                          <strong>{patch.affected_business_service_count} business services</strong>
                          <div className="table-secondary">
                            {patch.affected_application_count} apps · {patch.affected_server_count} servers
                          </div>
                        </td>
                        <td>
                          <strong>{Math.round(patch.expected_risk_reduction)}</strong>
                          <div className="risk-bar">
                            <span style={{ width: `${Math.min(100, Math.max(0, patch.expected_risk_reduction))}%` }} />
                          </div>
                        </td>
                        <td>
                          <Link className="table-open-link" href={`/exposure/kbs/${encodeURIComponent(patch.kb_id)}`} aria-label={`Open ${patch.kb_id}`}>
                            →
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="card queue-card">
            <div className="card-header">
              <div>
                <h2>High-priority CVEs</h2>
                <p>Security analysis queue. This table only includes real CVE identifiers; advisory-only KBs stay in the patch table above.</p>
              </div>
            </div>
            {filteredCves.length === 0 ? (
              <div className="card-body">
                <p className="muted">No CVEs match the current filters.</p>
              </div>
            ) : (
              <div className="table-scroll">
                <table className="operations-table exposure-table">
                  <thead>
                    <tr>
                      <th>Priority</th>
                      <th>CVE</th>
                      <th>Reachability</th>
                      <th>Business impact</th>
                      <th>Risk reduction</th>
                      <th>Patch KB</th>
                      <th aria-label="Open" />
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCves.map((exposure, index) => (
                      <tr key={exposure.cve_id}>
                        <td>
                          <span className="rank-number">{String(index + 1).padStart(2, "0")}</span>
                        </td>
                        <td>
                          <Link className="table-primary-link" href={`/exposure/cves/${encodeURIComponent(exposure.cve_id)}`}>
                            {exposure.cve_id}
                          </Link>
                          <div className="table-secondary">
                            <StatusBadge label={exposure.severity} tone={statusTone(exposure.severity)} compact />
                            <span>{exposure.exploit_signal || "No exploit signal"}</span>
                          </div>
                        </td>
                        <td>
                          <StatusBadge
                            label={exposure.internet_exposed ? "Internet exposed" : exposure.reachable_server_count ? "Reachable" : "No path observed"}
                            tone={exposure.internet_exposed ? "critical" : exposure.reachable_server_count ? "warning" : "neutral"}
                          />
                          <div className="table-secondary">{exposure.reachable_server_count} reachable servers</div>
                        </td>
                        <td>
                          <strong>{exposure.affected_business_service_count} business services</strong>
                          <div className="table-secondary">
                            {exposure.affected_application_count} apps · {exposure.affected_server_count} servers
                          </div>
                        </td>
                        <td>
                          <strong>{Math.round(exposure.expected_risk_reduction)}</strong>
                          <div className="risk-bar">
                            <span style={{ width: `${Math.min(100, Math.max(0, exposure.expected_risk_reduction))}%` }} />
                          </div>
                        </td>
                        <td>
                          <Link className="table-primary-link" href={`/exposure/kbs/${encodeURIComponent(exposure.missing_kb)}`}>
                            {exposure.missing_kb}
                          </Link>
                          <div className="table-secondary">{exposure.recommended_patch || "Recommended patch"}</div>
                        </td>
                        <td>
                          <Link className="table-open-link" href={`/exposure/cves/${encodeURIComponent(exposure.cve_id)}`} aria-label={`Open ${exposure.cve_id}`}>
                            →
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
