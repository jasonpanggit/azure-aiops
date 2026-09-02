"use client";

import { useMemo } from "react";
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
import { formatDefenderAsset } from "./asset-labels";
import type {
  DefenderOverview,
  DefenderAlert,
  DefenderAttackPath,
  DefenderSecureScoreControl,
  DefenderPostureFinding,
} from "@/lib/types";

/** Focused page for Defender security monitoring: overview, alerts, attack paths, controls, recommendations. */
export default function DefenderPosturePage() {
  const { scope } = useScope();

  const overview = useApi(() => vulnerabilityApi.defenderOverview(scope), [scope]);
  const alerts = useApi(() => vulnerabilityApi.defenderAlerts(scope), [scope]);
  const attackPaths = useApi(() => vulnerabilityApi.defenderAttackPaths(scope), [scope]);
  const controls = useApi(() => vulnerabilityApi.defenderSecureScoreControls(scope), [scope]);
  const recommendations = useApi(() => vulnerabilityApi.defenderPosture(scope), [scope]);

  const allLoading = useMemo(
    () =>
      overview.loading ||
      alerts.loading ||
      attackPaths.loading ||
      controls.loading ||
      recommendations.loading,
    [overview.loading, alerts.loading, attackPaths.loading, controls.loading, recommendations.loading]
  );

  const anyError = useMemo(
    () =>
      overview.error ||
      alerts.error ||
      attackPaths.error ||
      controls.error ||
      recommendations.error,
    [overview.error, alerts.error, attackPaths.error, controls.error, recommendations.error]
  );

  const alertRows = useMemo(() => (alerts.data?.data as DefenderAlert[]) ?? [], [alerts.data]);
  const {
    filteredRows: filteredAlerts,
    filters: alertFilters,
    resetFilters: resetAlertFilters,
  } = useColumnFilters(alertRows, [
    { id: "severity", label: "Severity", getValues: (alert) => alert.severity },
    { id: "status", label: "Status", getValues: (alert) => alert.status },
  ]);
  const alertPaging = useTablePagination(filteredAlerts);

  const attackPathRows = useMemo(() => (attackPaths.data?.data as DefenderAttackPath[]) ?? [], [attackPaths.data]);
  const attackPathPaging = useTablePagination(attackPathRows);

  const controlRows = useMemo(() => (controls.data?.data as DefenderSecureScoreControl[]) ?? [], [controls.data]);
  const controlPaging = useTablePagination(controlRows);

  const recommendationRows = useMemo(
    () => (recommendations.data?.data as DefenderPostureFinding[]) ?? [],
    [recommendations.data]
  );
  const {
    filteredRows: filteredRecommendations,
    filters: recommendationFilters,
    resetFilters: resetRecommendationFilters,
  } = useColumnFilters(recommendationRows, [
    { id: "severity", label: "Severity", getValues: (rec) => rec.severity },
    { id: "status", label: "Status", getValues: (rec) => rec.status },
    { id: "resource_type", label: "Resource type", getValues: (rec) => rec.resource_type },
  ]);
  const recommendationPaging = useTablePagination(filteredRecommendations);

  return (
    <div className="page-container">
      <PageHeader
        title="Defender posture"
        description="Monitor security alerts, attack paths, and security control compliance."
      />

      {allLoading && <StatePanel title="Loading" message="Loading Defender data…" tone="loading" />}
      {anyError && <StatePanel title="Error" message="Failed to load Defender data" tone="error" />}

      {!allLoading && !anyError && (
        <>
          {/* Overview metrics */}
          {overview.data?.data && (
            <section className="card">
              <div className="card-header">
                <h2>Security overview</h2>
              </div>
              <div className="card-body">
                <div className="metric-grid">
                  <MetricCard
                    label="Secure score"
                    value={`${(overview.data.data as DefenderOverview).secure_scores?.[0]?.percentage || 0}%`}
                    detail="Microsoft Defender security score"
                    tone="default"
                  />
                  <MetricCard
                    label="Active alerts"
                    value={alertRows.length}
                    detail="Current security incidents"
                    tone="warning"
                  />
                  <MetricCard
                    label="Attack paths"
                    value={attackPathRows.length}
                    detail="Potential attack chains"
                    tone="critical"
                  />
                  <MetricCard
                    label="Open recommendations"
                    value={recommendationRows.length}
                    detail="Unhealthy Defender assessments"
                    tone="warning"
                  />
                </div>
              </div>
            </section>
          )}

          {/* Security alerts */}
          {alertRows.length > 0 && (
            <section className="card queue-card">
              <div className="card-header">
                <h2>Security alerts</h2>
              </div>
              <TableColumnFilters
                filters={alertFilters}
                onReset={resetAlertFilters}
                resultCount={filteredAlerts.length}
                totalCount={alertRows.length}
              />
              <div className="table-scroll">
                <table className="operations-table exposure-table">
                  <thead>
                    <tr>
                      <th>Alert</th>
                      <th>Severity</th>
                      <th>Status</th>
                      <th>Resources affected</th>
                      <th>First seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alertPaging.pageRows.map((alert) => (
                      <tr key={alert.id}>
                        <td>
                          <strong>{alert.title}</strong>
                          {alert.description && <div className="table-secondary">{alert.description}</div>}
                        </td>
                        <td>
                          <StatusBadge label={alert.severity} tone={statusTone(alert.severity)} compact />
                        </td>
                        <td>
                          <StatusBadge label={alert.status} tone={statusTone(alert.status)} compact />
                        </td>
                        <td>{alert.resourceIds?.length || 0}</td>
                        <td className="table-secondary">
                          {alert.timeGenerated ? new Date(alert.timeGenerated).toLocaleDateString() : "N/A"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <TablePagination
                total={alertPaging.total}
                pageRows={alertPaging.pageRows.length}
                page={alertPaging.page}
                onPageChange={alertPaging.setPage}
                pageSize={alertPaging.pageSize}
                onPageSizeChange={alertPaging.setPageSize}
                label="alerts"
              />
            </section>
          )}

          {/* Attack paths */}
          {attackPathRows.length > 0 && (
            <section className="card queue-card">
              <div className="card-header">
                <h2>Attack paths</h2>
              </div>
              <div className="table-scroll">
                <table className="operations-table exposure-table">
                  <thead>
                    <tr>
                      <th>Path</th>
                      <th>Impact</th>
                      <th>Nodes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {attackPathPaging.pageRows.map((path) => (
                      <tr key={path.id}>
                        <td>
                          <strong>{path.title || "N/A"}</strong>
                          {path.description && <div className="table-secondary">{path.description}</div>}
                        </td>
                        <td>{path.potentialImpact || "N/A"}</td>
                        <td>{path.nodeCount || 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <TablePagination
                total={attackPathPaging.total}
                pageRows={attackPathPaging.pageRows.length}
                page={attackPathPaging.page}
                onPageChange={attackPathPaging.setPage}
                pageSize={attackPathPaging.pageSize}
                onPageSizeChange={attackPathPaging.setPageSize}
                label="attack paths"
              />
            </section>
          )}

          {/* Security controls */}
          {controlRows.length > 0 && (
            <section className="card queue-card">
              <div className="card-header">
                <h2>Security controls</h2>
              </div>
              <div className="table-scroll">
                <table className="operations-table exposure-table">
                  <thead>
                    <tr>
                      <th>Control</th>
                      <th>Score</th>
                      <th>Compliance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {controlPaging.pageRows.map((control) => (
                      <tr key={control.id}>
                        <td>{control.title || "N/A"}</td>
                        <td>
                          {control.currentScore}/{control.maxScore}
                        </td>
                        <td>{control.percentage ? `${control.percentage.toFixed(0)}%` : "N/A"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <TablePagination
                total={controlPaging.total}
                pageRows={controlPaging.pageRows.length}
                page={controlPaging.page}
                onPageChange={controlPaging.setPage}
                pageSize={controlPaging.pageSize}
                onPageSizeChange={controlPaging.setPageSize}
                label="controls"
              />
            </section>
          )}

          {/* Security recommendations */}
          {recommendationRows.length > 0 && (
            <section className="card queue-card">
              <div className="card-header">
                <h2>Security recommendations</h2>
                <p>Unhealthy Defender assessments across the discovered inventory.</p>
              </div>
              <TableColumnFilters
                filters={recommendationFilters}
                onReset={resetRecommendationFilters}
                resultCount={filteredRecommendations.length}
                totalCount={recommendationRows.length}
              />
              <div className="card-body">
                {recommendationPaging.pageRows.map((rec) => (
                  <details
                    key={rec.assessment_id}
                    style={{ marginBottom: "1rem", borderBottom: "1px solid var(--border-color)", paddingBottom: "1rem" }}
                  >
                    <summary style={{ cursor: "pointer", fontWeight: 500, display: "flex", alignItems: "center", gap: "0.5rem" }}>
                      <StatusBadge label={rec.severity} tone={statusTone(rec.severity)} compact />
                      {rec.recommendation || "Unnamed recommendation"}
                    </summary>
                    <div style={{ marginTop: "0.5rem", fontSize: "0.875rem", lineHeight: 1.5 }}>
                      <p>
                        <strong>Asset:</strong> {formatDefenderAsset(rec)}
                      </p>
                      <p>
                        <strong>Status:</strong> <StatusBadge label={rec.status} tone={statusTone(rec.status)} compact />
                      </p>
                      <p>
                        <strong>Description:</strong> {rec.description || "No description available"}
                      </p>
                      {rec.remediation && (
                        <p>
                          <strong>Remediation:</strong> {rec.remediation}
                        </p>
                      )}
                    </div>
                  </details>
                ))}
              </div>
              <TablePagination
                total={recommendationPaging.total}
                pageRows={recommendationPaging.pageRows.length}
                page={recommendationPaging.page}
                onPageChange={recommendationPaging.setPage}
                pageSize={recommendationPaging.pageSize}
                onPageSizeChange={recommendationPaging.setPageSize}
                label="recommendations"
              />
            </section>
          )}
        </>
      )}
    </div>
  );
}
