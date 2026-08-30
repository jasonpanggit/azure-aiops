"use client";

import Link from "next/link";
import { useMemo } from "react";
import { CvssRadarChart } from "@/components/ui/CvssRadarChart";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { TablePagination } from "@/components/ui/TablePagination";
import { useTablePagination } from "@/lib/use-table-pagination";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { kbApi } from "@/lib/services";

/** KB drilldown: every CVE this security update resolves (via MSRC), CVSS per CVE, and affected assets still missing it. */
export default function KbDetailPage({ params }: { params: { id: string } }) {
  const { scope } = useScope();
  const detail = useApi(() => kbApi.detail(decodeURIComponent(params.id), scope), [params.id, scope]);

  const cves = useMemo(() => detail.data?.data.cves ?? [], [detail.data]);
  const cvesPaging = useTablePagination(cves);
  const findings = useMemo(() => detail.data?.data.findings ?? [], [detail.data]);
  const findingsPaging = useTablePagination(findings);

  if (detail.loading) {
    return (
      <div className="page-container">
        <StatePanel title="Building KB exposure view" message="Resolving associated CVEs and affected assets." tone="loading" />
      </div>
    );
  }
  if (detail.error || !detail.data) {
    return (
      <div className="page-container">
        <StatePanel
          title="KB detail is unavailable"
          message={detail.error?.message ?? "No KB detail was returned."}
          tone="error"
          action={<Link className="button" href="/exposure">Return to exposure</Link>}
        />
      </div>
    );
  }

  const data = detail.data.data;

  return (
    <div className="page-container">
      <div className="breadcrumb">
        <Link href="/exposure">Exposure</Link>
        <span>/</span>
        <span>{data.kb_id}</span>
      </div>
      <PageHeader
        eyebrow="Patch investigation"
        title={data.kb_id}
        description={data.title || "Security update"}
        actions={
          <Link
            className="button button-primary"
            href={`/remediation?kb=${encodeURIComponent(data.kb_id)}&cve=${encodeURIComponent(
              data.cve_ids[0] || ""
            )}&business_service=${encodeURIComponent(data.affected_business_services[0] || "")}`}
          >
            Create patch plan
          </Link>
        }
        metadata={
          <>
            <StatusBadge label={data.severity} tone={statusTone(data.severity)} />
            <span>{data.cve_ids.length} associated CVEs</span>
            <span>{data.affected_servers.length} affected servers</span>
          </>
        }
      />
      <EvidenceBar
        evidence={detail.data.evidence}
        knowledgeVersion={detail.data.knowledge_version}
        warnings={detail.data.warnings}
      />

      <section className="cve-summary-grid">
        <article className="card">
          <div className="card-header"><h2>Business impact</h2></div>
          <div className="card-body">
            <strong className="large-value">{data.affected_business_services.length}</strong>
            <p className="muted">{data.affected_business_services.join(", ") || "No service mapping available"}</p>
          </div>
        </article>
        <article className="card">
          <div className="card-header"><h2>Affected servers</h2></div>
          <div className="card-body">
            <strong className="large-value">{data.affected_servers.length}</strong>
            <p className="muted">{data.findings.filter((f) => f.reachable).length} reachable / internet-facing</p>
          </div>
        </article>
        <article className="card">
          <div className="card-header"><h2>Published</h2></div>
          <div className="card-body">
            <strong className="large-value">{data.published_at || "Unknown"}</strong>
            <p className="muted">MSRC Security Update Guide</p>
          </div>
        </article>
      </section>

      <section className="card exposure-findings-card">
        <div className="card-header">
          <div>
            <h2>Associated CVEs</h2>
            <p>CVE ids this security update resolves, mapped via the MSRC Security Update Guide (SUG) API.</p>
          </div>
        </div>
        {data.cves.length === 0 ? (
          <div className="card-body">
            <p className="muted">
              No CVE association found for this KB in MSRC&apos;s data. This is common for Servicing Stack Updates
              and other advisory-only releases that carry no CVE.
            </p>
          </div>
        ) : (
          <>
          <div className="table-scroll">
            <table className="operations-table">
              <thead>
                <tr>
                  <th>CVE</th>
                  <th>Severity</th>
                  <th>CVSS score</th>
                  <th>CVSS vector</th>
                </tr>
              </thead>
              <tbody>
                {cvesPaging.pageRows.map((cve) => (
                  <tr key={cve.cve_id}>
                    <td>
                      <Link className="table-primary-link" href={`/exposure/cves/${encodeURIComponent(cve.cve_id)}`}>
                        {cve.cve_id}
                      </Link>
                      <div className="table-secondary">{cve.title}</div>
                    </td>
                    <td><StatusBadge label={cve.cvss?.severity || cve.severity} tone={statusTone(cve.cvss?.severity || cve.severity)} compact /></td>
                    <td>{cve.cvss?.base_score ? cve.cvss.base_score.toFixed(1) : "—"}</td>
                    <td>
                      {cve.cvss?.vector ? (
                        <CvssRadarChart vector={cve.cvss.vector} radius={26} compact />
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <TablePagination
            total={cvesPaging.total}
            pageRows={cvesPaging.pageRows.length}
            page={cvesPaging.page}
            onPageChange={cvesPaging.setPage}
            pageSize={cvesPaging.pageSize}
            onPageSizeChange={cvesPaging.setPageSize}
            label="CVEs"
          />
          </>
        )}
      </section>

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
                <th>CVE</th>
                <th>Application / service</th>
                <th>Environment</th>
                <th>Reachability</th>
                <th>Owner</th>
              </tr>
            </thead>
            <tbody>
              {findingsPaging.pageRows.map((finding) => {
                const isKbProxy = finding.cve_id.startsWith("KB-");
                return (
                <tr key={finding.finding_id}>
                  <td><strong>{finding.server_id}</strong></td>
                  <td>
                    {isKbProxy ? (
                      <span>{finding.cve_id}</span>
                    ) : (
                      <Link className="table-primary-link" href={`/exposure/cves/${encodeURIComponent(finding.cve_id)}`}>
                        {finding.cve_id}
                      </Link>
                    )}
                  </td>
                  <td><strong>{finding.application || "Unmapped application"}</strong><div className="table-secondary">{finding.business_service || "Unmapped service"}</div></td>
                  <td>{finding.environment || "Unknown"}</td>
                  <td><StatusBadge label={finding.reachable ? finding.network_exposure || "Reachable" : "No path observed"} tone={finding.reachable ? "critical" : "neutral"} /></td>
                  <td>{finding.owner || "Owner unassigned"}</td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <TablePagination
          total={findingsPaging.total}
          pageRows={findingsPaging.pageRows.length}
          page={findingsPaging.page}
          onPageChange={findingsPaging.setPage}
          pageSize={findingsPaging.pageSize}
          onPageSizeChange={findingsPaging.setPageSize}
          label="findings"
        />
      </section>
    </div>
  );
}
