"use client";

import { useState } from "react";
import Link from "next/link";
import { AttackPathGraphView } from "@/components/ui/AttackPathGraphView";
import { CvssRadarChart } from "@/components/ui/CvssRadarChart";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { vulnerabilityApi } from "@/lib/services";

/** CVE drilldown connecting affected services, reachable hosts, paths, owners, and patch guidance. */
export default function CveDetailPage({ params }: { params: { id: string } }) {
  const { scope } = useScope();
  const [refreshKey, setRefreshKey] = useState(0);
  const detail = useApi(
    () => vulnerabilityApi.cve(decodeURIComponent(params.id), scope),
    [params.id, scope, refreshKey]
  );
  const attackPath = useApi(
    () => vulnerabilityApi.attackPath(decodeURIComponent(params.id), scope),
    [params.id, scope]
  );
  const [acceptRiskOpen, setAcceptRiskOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [approvedBy, setApprovedBy] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  if (detail.loading) {
    return (
      <div className="page-container">
        <StatePanel title="Building CVE exposure view" message="Resolving services, servers, network paths, and patch guidance." tone="loading" />
      </div>
    );
  }
  if (detail.error || !detail.data) {
    return (
      <div className="page-container">
        <StatePanel
          title="CVE detail is unavailable"
          message={detail.error?.message ?? "No exposure detail was returned."}
          tone="error"
          action={<Link className="button" href="/exposure">Return to exposure</Link>}
        />
      </div>
    );
  }

  const data = detail.data.data;

  async function handleAcceptRisk() {
    if (!reason.trim()) {
      setSubmitError("A reason is required to accept risk.");
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      await vulnerabilityApi.acceptRisk({
        cve_id: data.cve.cve_id,
        reason: reason.trim(),
        approved_by: approvedBy.trim() || undefined,
        expires_at: expiresAt || undefined,
      });
      setAcceptRiskOpen(false);
      setReason("");
      setApprovedBy("");
      setExpiresAt("");
      setRefreshKey((key) => key + 1);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to submit risk exception.");
    } finally {
      setSubmitting(false);
    }
  }

  const acceptedFindings = data.findings.filter((finding) => finding.risk_accepted);

  return (
    <div className="page-container">
      <div className="breadcrumb">
        <Link href="/exposure">Exposure</Link>
        <span>/</span>
        <span>{data.cve.cve_id}</span>
      </div>
      <PageHeader
        eyebrow="Vulnerability investigation"
        title={data.cve.cve_id}
        description={data.cve.title || data.cve.description}
        actions={
          <>
            <button className="button" onClick={() => setAcceptRiskOpen((open) => !open)}>
              {acceptedFindings.length ? "Manage risk acceptance" : "Accept risk"}
            </button>
            <Link
              className="button button-primary"
              href={`/remediation?cve=${encodeURIComponent(data.cve.cve_id)}&kb=${encodeURIComponent(
                data.recommended_patch || data.cve.associated_kbs[0] || ""
              )}&business_service=${encodeURIComponent(data.affected_business_services[0] || "")}`}
            >
              Create patch plan
            </Link>
          </>
        }
        metadata={
          <>
            <StatusBadge label={data.cve.severity} tone={statusTone(data.cve.severity)} />
            {data.cve.is_known_exploited && (
              <StatusBadge label="Known Exploited (KEV)" tone="critical" />
            )}
            <span>{data.affected_business_services.length} affected business services</span>
            <span>{data.affected_servers.length} affected servers</span>
          </>
        }
      />
      <EvidenceBar
        evidence={detail.data.evidence}
        knowledgeVersion={detail.data.knowledge_version}
        warnings={detail.data.warnings}
      />

      {acceptedFindings.length > 0 && (
        <section className="card">
          <div className="card-header"><h2>Risk accepted</h2></div>
          <div className="card-body">
            <p className="muted">
              {acceptedFindings.length} of {data.findings.length} finding(s) have accepted risk and are
              excluded from open-exposure and priority metrics, but remain visible here for auditability.
            </p>
            <p className="muted">
              Reason: {acceptedFindings[0].risk_acceptance_reason || "—"}
              {acceptedFindings[0].risk_acceptance_expires_at &&
                ` · Expires ${acceptedFindings[0].risk_acceptance_expires_at}`}
            </p>
          </div>
        </section>
      )}

      {acceptRiskOpen && (
        <section className="card">
          <div className="card-header"><h2>Accept risk for {data.cve.cve_id}</h2></div>
          <div className="card-body">
            <p className="muted">
              This records an auditable exception; the finding stays visible but stops counting toward
              open-exposure and patch-priority metrics.
            </p>
            <label>
              Reason
              <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} />
            </label>
            <label>
              Approved by
              <input value={approvedBy} onChange={(event) => setApprovedBy(event.target.value)} />
            </label>
            <label>
              Expires at (optional, ISO-8601)
              <input value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} placeholder="2026-12-31T00:00:00Z" />
            </label>
            {submitError && <p className="error-text">{submitError}</p>}
            <div className="form-actions">
              <button className="button button-primary" disabled={submitting} onClick={handleAcceptRisk}>
                {submitting ? "Submitting…" : "Submit exception"}
              </button>
              <button className="button" onClick={() => setAcceptRiskOpen(false)} disabled={submitting}>
                Cancel
              </button>
            </div>
          </div>
        </section>
      )}

      <section className="cve-summary-grid">
        <article className="card">
          <div className="card-header"><h2>Business impact</h2></div>
          <div className="card-body">
            <strong className="large-value">{data.affected_business_services.length}</strong>
            <p className="muted">{data.affected_business_services.join(", ") || "No service mapping available"}</p>
          </div>
        </article>
        <article className="card">
          <div className="card-header"><h2>Recommended patch</h2></div>
          <div className="card-body">
            <strong className="large-value">{data.recommended_patch || "Not identified"}</strong>
            <p className="muted">
              {data.cve.associated_kbs.length ? (
                data.cve.associated_kbs.map((kb, index) => (
                  <span key={kb}>
                    {index > 0 && ", "}
                    <Link className="table-primary-link" href={`/exposure/kbs/${encodeURIComponent(kb)}`}>
                      {kb}
                    </Link>
                  </span>
                ))
              ) : (
                "No associated KBs"
              )}
            </p>
          </div>
        </article>
        <article className="card">
          <div className="card-header"><h2>CVSS</h2></div>
          <div className="card-body">
            <strong className="large-value">{data.cve.cvss?.base_score ? data.cve.cvss.base_score.toFixed(1) : "—"}</strong>
            <p className="muted">
              <StatusBadge label={data.cve.cvss?.severity || data.cve.severity} tone={statusTone(data.cve.cvss?.severity || data.cve.severity)} compact />
            </p>
            <p className="muted">{data.cve.cvss?.vector || "No CVSS vector available"}</p>
          </div>
        </article>
        <article className="card">
          <div className="card-header"><h2>Exploitability</h2></div>
          <div className="card-body exploit-signals">
            {data.exploitability_signals.map((signal) => (
              <div key={`${signal.source}-${signal.signal}`}>
                <StatusBadge label={signal.confidence} tone={statusTone(signal.confidence)} compact />
                <span>{signal.signal} · {signal.source}</span>
              </div>
            ))}
            {data.cve.exploit_references.length > 0 ? (
              <ul className="exploit-reference-list">
                {data.cve.exploit_references.map((reference) => (
                  <li key={reference.url}>
                    <StatusBadge label={reference.source} tone="critical" compact />{" "}
                    <a href={reference.url} target="_blank" rel="noopener noreferrer">
                      {reference.url}
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No public exploit/PoC references observed by NVD.</p>
            )}
          </div>
        </article>
        <article className="card">
          <div className="card-header"><h2>Real-world exploitation</h2></div>
          <div className="card-body">
            <strong className="large-value">
              {data.cve.epss_score ? `${(data.cve.epss_score * 100).toFixed(1)}%` : "—"}
            </strong>
            <p className="muted">
              EPSS score{data.cve.epss_percentile ? ` · ${(data.cve.epss_percentile * 100).toFixed(0)}th percentile` : ""}
            </p>
            {data.cve.is_known_exploited ? (
              <p className="muted">
                <StatusBadge label="CISA KEV" tone="critical" compact />{" "}
                Due {data.cve.kev_due_date || "unspecified"}
                {data.cve.kev_ransomware_use === "Known" && " · Known ransomware use"}
              </p>
            ) : (
              <p className="muted">Not in CISA KEV catalog</p>
            )}
          </div>
        </article>
      </section>

      <section className="card cvss-radar-card">
        <div>
          <div className="card-header"><h2>Description</h2></div>
          <p className="cve-description">{data.cve.description || data.cve.title || "No CVE description available."}</p>
        </div>
        {data.cve.cvss?.vector && <CvssRadarChart vector={data.cve.cvss.vector} />}
      </section>

      {attackPath.data?.data && attackPath.data.data.nodes.length > 0 && (
        <section className="card">
          <div className="card-header">
            <div>
              <h2>Attack path</h2>
              <p>
                Multi-hop path from the internet through observed firewall/NSG controls to each affected
                server, reusing the network engine&apos;s reachability decisions.
              </p>
            </div>
          </div>
          <div className="card-body">
            <AttackPathGraphView graph={attackPath.data.data} />
          </div>
        </section>
      )}

      <section className="card exposure-findings-card">
        <div className="card-header">
          <div>
            <h2>Affected and reachable assets</h2>
            <p>Every finding keeps ownership, environment, and firewall/NSG path together.</p>
          </div>
        </div>
        <div className="table-scroll">
          <table className="operations-table">
            <thead>
              <tr>
                <th>Server</th>
                <th>Application / service</th>
                <th>Environment</th>
                <th>Reachability</th>
                <th>Network controls</th>
                <th>Owner</th>
                <th>SLA</th>
                <th>Risk status</th>
              </tr>
            </thead>
            <tbody>
              {data.findings.map((finding) => (
                <tr key={finding.finding_id}>
                  <td><strong>{finding.server_id}</strong><div className="table-secondary"><Link className="table-primary-link" href={`/exposure/kbs/${encodeURIComponent(finding.missing_kb)}`}>{finding.missing_kb}</Link></div></td>
                  <td><strong>{finding.application || "Unmapped application"}</strong><div className="table-secondary">{finding.business_service || "Unmapped service"}</div></td>
                  <td>{finding.environment || "Unknown"}</td>
                  <td><StatusBadge label={finding.reachable ? finding.network_exposure || "Reachable" : "No path observed"} tone={finding.reachable ? "critical" : "neutral"} /></td>
                  <td>
                    <strong>{finding.firewall_path.join(" → ") || "No firewall observed"}</strong>
                    <div className="table-secondary">{finding.nsg_path.join(" → ") || "No NSG path resolved"}</div>
                  </td>
                  <td>{finding.owner || "Owner unassigned"}</td>
                  <td>
                    {finding.due_at ? (
                      <>
                        <StatusBadge label={finding.overdue ? "Overdue" : "On track"} tone={finding.overdue ? "critical" : "success"} compact />
                        <div className="table-secondary">{finding.days_open} days open</div>
                      </>
                    ) : (
                      <span className="muted">No SLA data</span>
                    )}
                  </td>
                  <td>
                    {finding.risk_accepted ? (
                      <StatusBadge label="Risk accepted" tone="neutral" compact />
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
