"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { vulnerabilityApi } from "@/lib/services";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { MetricCard } from "@/components/ui/MetricCard";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import type { PatchPriority, RiskException, VulnerabilityExposure } from "@/lib/types";

/** Focused page for patch remediation: SLA compliance, patch inventory, CVE exposure, risk exceptions. */
export default function PatchPrioritiesPage() {
  const { scope } = useScope();
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedExceptions, setSelectedExceptions] = useState<Set<string>>(new Set());
  const [bulkRevoking, setBulkRevoking] = useState(false);
  const [exceptionsToken, setExceptionsToken] = useState(0);

  const patchPriorities = useApi(() => vulnerabilityApi.patchPriorities(scope), [scope]);
  const slaCompliance = useApi(() => vulnerabilityApi.slaCompliance(scope), [scope]);
  const exposures = useApi(() => vulnerabilityApi.exposures(scope), [scope]);
  const riskExceptions = useApi(() => vulnerabilityApi.riskExceptions(scope), [scope, exceptionsToken]);

  const allLoading = useMemo(
    () =>
      patchPriorities.loading ||
      slaCompliance.loading ||
      exposures.loading ||
      riskExceptions.loading,
    [patchPriorities.loading, slaCompliance.loading, exposures.loading, riskExceptions.loading]
  );

  const anyError = useMemo(
    () =>
      patchPriorities.error ||
      slaCompliance.error ||
      exposures.error ||
      riskExceptions.error,
    [patchPriorities.error, slaCompliance.error, exposures.error, riskExceptions.error]
  );

  const patchRows = useMemo(() => (patchPriorities.data?.data as PatchPriority[]) ?? [], [patchPriorities.data]);
  const filteredPatches = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return patchRows;
    return patchRows.filter((p) =>
      [p.kb_id, p.recommended_action, ...p.cve_ids].some((value) => value?.toLowerCase().includes(query))
    );
  }, [patchRows, searchQuery]);
  const {
    filteredRows: columnFilteredPatches,
    filters: patchFilters,
    resetFilters: resetPatchFilters,
  } = useColumnFilters(filteredPatches, [
    { id: "overdue", label: "Overdue", getValues: (patch) => (patch.overdue_count > 0 ? "Overdue" : "On track") },
  ]);
  const patchPaging = useTablePagination(columnFilteredPatches);

  const exposureRows = useMemo(() => (exposures.data?.data as VulnerabilityExposure[]) ?? [], [exposures.data]);
  const {
    filteredRows: columnFilteredExposures,
    filters: exposureFilters,
    resetFilters: resetExposureFilters,
  } = useColumnFilters(exposureRows, [
    { id: "severity", label: "Severity", getValues: (exposure) => exposure.severity },
  ]);
  const exposurePaging = useTablePagination(columnFilteredExposures);

  const exceptionRows = useMemo(() => (riskExceptions.data?.data as RiskException[]) ?? [], [riskExceptions.data]);

  const revokeException = useCallback(
    async (exceptionId: string) => {
      try {
        await vulnerabilityApi.revokeRiskException(exceptionId);
        setExceptionsToken((token) => token + 1);
        setSelectedExceptions((prev) => {
          const next = new Set(prev);
          next.delete(exceptionId);
          return next;
        });
      } catch (err) {
        console.error("Failed to revoke exception:", err);
      }
    },
    []
  );

  const revokeBulk = useCallback(async () => {
    setBulkRevoking(true);
    for (const id of Array.from(selectedExceptions)) {
      await revokeException(id);
    }
    setBulkRevoking(false);
  }, [selectedExceptions, revokeException]);

  return (
    <div className="page-container">
      <PageHeader
        title="Patch priorities"
        description="Manage patch remediation queue, track SLA compliance, and review CVE exposure."
      />

      {allLoading && <StatePanel title="Loading" message="Loading patch data…" tone="loading" />}
      {anyError && <StatePanel title="Error" message="Failed to load patch data" tone="error" />}

      {!allLoading && !anyError && (
        <>
          {slaCompliance.data?.data && (
            <section className="card">
              <div className="card-header">
                <h2>Patch SLA status</h2>
              </div>
              <div className="card-body">
                <div className="metric-grid">
                  <MetricCard
                    label="Total patches pending"
                    value={Object.keys(slaCompliance.data.data).length || 0}
                    detail="In remediation queue"
                    tone="default"
                  />
                </div>
              </div>
            </section>
          )}

          <section className="card queue-card">
            <div className="card-header">
              <div>
                <h2>Patch inventory</h2>
                <p>{filteredPatches.length} patches in remediation queue</p>
              </div>
            </div>
            <div className="card-body">
              <input
                type="text"
                placeholder="Search by KB ID, action, or CVE…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  width: "100%",
                  padding: "0.5rem",
                  marginBottom: "1rem",
                  border: "1px solid var(--border-color)",
                  borderRadius: "4px",
                }}
              />
            </div>
            {columnFilteredPatches.length === 0 ? (
              <div className="card-body">
                <p className="muted">No patches match the current filters.</p>
              </div>
            ) : (
              <>
                <TableColumnFilters
                  filters={patchFilters}
                  onReset={resetPatchFilters}
                  resultCount={columnFilteredPatches.length}
                  totalCount={filteredPatches.length}
                />
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
                      {patchPaging.pageRows.map((patch, index) => (
                        <tr key={patch.kb_id}>
                          <td>
                            <span className="rank-number">
                              {String(patchPaging.page * patchPaging.pageSize + index + 1).padStart(2, "0")}
                            </span>
                          </td>
                          <td>
                            <Link className="table-primary-link" href={`/exposure/kbs/${encodeURIComponent(patch.kb_id)}`}>
                              {patch.kb_id}
                            </Link>
                            <div className="table-secondary">{patch.recommended_action}</div>
                          </td>
                          <td>
                            <strong>{patch.cve_ids?.length || 0}</strong>
                            <div className="table-secondary">
                              {patch.cve_ids?.length ? (
                                patch.cve_ids.slice(0, 3).map((cveId, i) => (
                                  <span key={cveId}>
                                    {i > 0 && ", "}
                                    <Link className="table-primary-link" href={`/exposure/cves/${encodeURIComponent(cveId)}`}>
                                      {cveId}
                                    </Link>
                                  </span>
                                ))
                              ) : (
                                "Advisory-only KB"
                              )}
                            </div>
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
                            <Link
                              className="table-secondary"
                              href={`/remediation?kb=${encodeURIComponent(patch.kb_id)}`}
                              style={{ marginRight: "0.75rem" }}
                            >
                              Remediate
                            </Link>
                            <Link
                              className="table-open-link"
                              href={`/exposure/kbs/${encodeURIComponent(patch.kb_id)}`}
                              aria-label={`Open ${patch.kb_id}`}
                            >
                              →
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            <TablePagination
              total={patchPaging.total}
              pageRows={patchPaging.pageRows.length}
              page={patchPaging.page}
              onPageChange={patchPaging.setPage}
              pageSize={patchPaging.pageSize}
              onPageSizeChange={patchPaging.setPageSize}
              label="KBs"
            />
          </section>

          <section className="card queue-card">
            <div className="card-header">
              <div>
                <h2>CVE exposure</h2>
                <p>{exposureRows.length} CVEs mapped to open findings</p>
              </div>
            </div>
            {columnFilteredExposures.length === 0 ? (
              <div className="card-body">
                <p className="muted">No CVEs match the current filters.</p>
              </div>
            ) : (
              <>
                <TableColumnFilters
                  filters={exposureFilters}
                  onReset={resetExposureFilters}
                  resultCount={columnFilteredExposures.length}
                  totalCount={exposureRows.length}
                />
                <div className="table-scroll">
                  <table className="operations-table exposure-table">
                    <thead>
                      <tr>
                        <th>CVE</th>
                        <th>Severity</th>
                        <th>Affected servers</th>
                        <th>Patch KB</th>
                        <th aria-label="Open" />
                      </tr>
                    </thead>
                    <tbody>
                      {exposurePaging.pageRows.map((exposure) => (
                        <tr key={exposure.cve_id}>
                          <td>
                            <Link className="table-primary-link" href={`/exposure/cves/${encodeURIComponent(exposure.cve_id)}`}>
                              {exposure.cve_id}
                            </Link>
                          </td>
                          <td>
                            <StatusBadge label={exposure.severity} tone={statusTone(exposure.severity)} compact />
                          </td>
                          <td>{exposure.affected_server_count}</td>
                          <td>
                            {exposure.missing_kb ? (
                              <Link className="table-primary-link" href={`/exposure/kbs/${encodeURIComponent(exposure.missing_kb)}`}>
                                {exposure.missing_kb}
                              </Link>
                            ) : (
                              <span>No KB mapped</span>
                            )}
                          </td>
                          <td>
                            <Link
                              className="table-open-link"
                              href={`/exposure/cves/${encodeURIComponent(exposure.cve_id)}`}
                              aria-label={`Open ${exposure.cve_id}`}
                            >
                              →
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            <TablePagination
              total={exposurePaging.total}
              pageRows={exposurePaging.pageRows.length}
              page={exposurePaging.page}
              onPageChange={exposurePaging.setPage}
              pageSize={exposurePaging.pageSize}
              onPageSizeChange={exposurePaging.setPageSize}
              label="CVEs"
            />
          </section>

          {exceptionRows.length > 0 && (
            <section className="card">
              <div className="card-header">
                <h2>Risk exceptions</h2>
                <p>{selectedExceptions.size} selected</p>
              </div>
              <div className="card-body">
                {selectedExceptions.size > 0 && (
                  <div style={{ marginBottom: "1rem" }}>
                    <button
                      onClick={revokeBulk}
                      disabled={bulkRevoking}
                      style={{
                        padding: "0.5rem 1rem",
                        backgroundColor: "var(--danger-color)",
                        color: "white",
                        border: "none",
                        borderRadius: "4px",
                        cursor: bulkRevoking ? "not-allowed" : "pointer",
                        opacity: bulkRevoking ? 0.5 : 1,
                      }}
                    >
                      {bulkRevoking ? "Revoking…" : `Revoke ${selectedExceptions.size} selected`}
                    </button>
                  </div>
                )}
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border-color)" }}>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>
                          <input
                            type="checkbox"
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedExceptions(new Set(exceptionRows.map((ex) => ex.exception_id)));
                              } else {
                                setSelectedExceptions(new Set());
                              }
                            }}
                            checked={selectedExceptions.size === exceptionRows.length && exceptionRows.length > 0}
                          />
                        </th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Server</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>CVE</th>
                      </tr>
                    </thead>
                    <tbody>
                      {exceptionRows.map((exception) => (
                        <tr key={exception.exception_id} style={{ borderBottom: "1px solid var(--border-color)" }}>
                          <td style={{ padding: "0.5rem" }}>
                            <input
                              type="checkbox"
                              checked={selectedExceptions.has(exception.exception_id)}
                              onChange={(e) => {
                                setSelectedExceptions((prev) => {
                                  const next = new Set(prev);
                                  if (e.target.checked) {
                                    next.add(exception.exception_id);
                                  } else {
                                    next.delete(exception.exception_id);
                                  }
                                  return next;
                                });
                              }}
                            />
                          </td>
                          <td style={{ padding: "0.5rem" }}>{exception.server_id || "N/A"}</td>
                          <td style={{ padding: "0.5rem", fontSize: "0.875rem" }}>
                            <Link className="table-primary-link" href={`/exposure/cves/${encodeURIComponent(exception.cve_id)}`}>
                              {exception.cve_id}
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
