"use client";

import { useCallback, useMemo, useState } from "react";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { vulnerabilityApi } from "@/lib/services";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { MetricCard } from "@/components/ui/MetricCard";
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

  const filteredPatches = useMemo(() => {
    if (!patchPriorities.data?.data) return [];
    const query = searchQuery.toLowerCase();
    return (patchPriorities.data.data as PatchPriority[]).filter((p) =>
      p.kb_id.toLowerCase().includes(query)
    );
  }, [patchPriorities.data, searchQuery]);

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
          {/* SLA compliance metrics */}
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

          {/* Patch inventory with search */}
          {patchPriorities.data?.data && (patchPriorities.data.data as PatchPriority[]).length > 0 && (
            <section className="card">
              <div className="card-header">
                <h2>Patch inventory</h2>
                <p>{filteredPatches.length} patches in remediation queue</p>
              </div>
              <div className="card-body">
                <input
                  type="text"
                  placeholder="Search by KB ID…"
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
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border-color)" }}>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>KB ID</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>CVE Count</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Affected Servers</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Priority Score</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Overdue</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPatches.map((patch) => (
                        <tr key={patch.kb_id} style={{ borderBottom: "1px solid var(--border-color)" }}>
                          <td style={{ padding: "0.5rem", fontSize: "0.875rem" }}>
                            {patch.kb_id}
                          </td>
                          <td style={{ padding: "0.5rem" }}>{patch.cve_ids?.length || 0}</td>
                          <td style={{ padding: "0.5rem" }}>{patch.affected_server_count}</td>
                          <td style={{ padding: "0.5rem" }}>
                            {patch.priority_score?.toFixed(2) || "N/A"}
                          </td>
                          <td style={{ padding: "0.5rem" }}>
                            {patch.overdue_count > 0 ? (
                              <span style={{ color: "var(--critical-color)" }}>{patch.overdue_count}</span>
                            ) : (
                              "0"
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {/* CVE exposure */}
          {exposures.data?.data && (exposures.data.data as VulnerabilityExposure[]).length > 0 && (
            <section className="card">
              <div className="card-header">
                <h2>CVE exposure</h2>
              </div>
              <div className="card-body">
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border-color)" }}>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>CVE ID</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Affected Servers</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(exposures.data.data as VulnerabilityExposure[]).map((exposure) => (
                        <tr key={exposure.cve_id} style={{ borderBottom: "1px solid var(--border-color)" }}>
                          <td style={{ padding: "0.5rem", fontSize: "0.875rem" }}>
                            {exposure.cve_id}
                          </td>
                          <td style={{ padding: "0.5rem" }}>{exposure.affected_server_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {/* Risk exceptions */}
          {riskExceptions.data?.data && (riskExceptions.data.data as RiskException[]).length > 0 && (
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
                                setSelectedExceptions(
                                  new Set(
                                    (riskExceptions.data?.data as RiskException[]).map(
                                      (ex) => ex.exception_id
                                    )
                                  )
                                );
                              } else {
                                setSelectedExceptions(new Set());
                              }
                            }}
                            checked={
                              selectedExceptions.size ===
                              (riskExceptions.data?.data as RiskException[]).length
                            }
                          />
                        </th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Server</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>CVE</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(riskExceptions.data.data as RiskException[]).map((exception) => (
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
                            {exception.cve_id}
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
