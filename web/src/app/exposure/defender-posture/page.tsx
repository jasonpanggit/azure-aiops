"use client";

import { useMemo } from "react";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { vulnerabilityApi } from "@/lib/services";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { MetricCard } from "@/components/ui/MetricCard";
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
                    value={alerts.data?.data ? (alerts.data.data as DefenderAlert[]).length : 0}
                    detail="Current security incidents"
                    tone="warning"
                  />
                  <MetricCard
                    label="Attack paths"
                    value={attackPaths.data?.data ? (attackPaths.data.data as DefenderAttackPath[]).length : 0}
                    detail="Potential attack chains"
                    tone="critical"
                  />
                </div>
              </div>
            </section>
          )}

          {/* Security alerts */}
          {alerts.data?.data && (alerts.data.data as DefenderAlert[]).length > 0 && (
            <section className="card">
              <div className="card-header">
                <h2>Security alerts</h2>
              </div>
              <div className="card-body">
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border-color)" }}>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Alert</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Resources affected</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>First seen</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(alerts.data.data as DefenderAlert[]).map((alert) => (
                        <tr key={alert.id} style={{ borderBottom: "1px solid var(--border-color)" }}>
                          <td style={{ padding: "0.5rem" }}>{alert.title}</td>
                          <td style={{ padding: "0.5rem" }}>{alert.resourceIds?.length || 0}</td>
                          <td style={{ padding: "0.5rem", fontSize: "0.875rem" }}>
                            {alert.timeGenerated
                              ? new Date(alert.timeGenerated).toLocaleDateString()
                              : "N/A"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {/* Attack paths */}
          {attackPaths.data?.data && (attackPaths.data.data as DefenderAttackPath[]).length > 0 && (
            <section className="card">
              <div className="card-header">
                <h2>Attack paths</h2>
              </div>
              <div className="card-body">
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border-color)" }}>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Path</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Impact</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Nodes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(attackPaths.data.data as DefenderAttackPath[]).map((path) => (
                        <tr key={path.id} style={{ borderBottom: "1px solid var(--border-color)" }}>
                          <td style={{ padding: "0.5rem" }}>{path.title || "N/A"}</td>
                          <td style={{ padding: "0.5rem" }}>{path.potentialImpact || "N/A"}</td>
                          <td style={{ padding: "0.5rem" }}>{path.nodeCount || 0}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {/* Security controls */}
          {controls.data?.data && (controls.data.data as DefenderSecureScoreControl[]).length > 0 && (
            <section className="card">
              <div className="card-header">
                <h2>Security controls</h2>
              </div>
              <div className="card-body">
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid var(--border-color)" }}>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Control</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Score</th>
                        <th style={{ padding: "0.5rem", textAlign: "left" }}>Compliance</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(controls.data.data as DefenderSecureScoreControl[]).map((control) => (
                        <tr key={control.id} style={{ borderBottom: "1px solid var(--border-color)" }}>
                          <td style={{ padding: "0.5rem" }}>{control.title || "N/A"}</td>
                          <td style={{ padding: "0.5rem" }}>
                            {control.currentScore}/{control.maxScore}
                          </td>
                          <td style={{ padding: "0.5rem" }}>
                            {control.percentage ? `${control.percentage.toFixed(0)}%` : "N/A"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {/* Security recommendations */}
          {recommendations.data?.data && (recommendations.data.data as DefenderPostureFinding[]).length > 0 && (
            <section className="card">
              <div className="card-header">
                <h2>Security recommendations</h2>
              </div>
              <div className="card-body">
                {(recommendations.data.data as DefenderPostureFinding[]).map((rec) => (
                  <details key={rec.assessment_id} style={{ marginBottom: "1rem", borderBottom: "1px solid var(--border-color)", paddingBottom: "1rem" }}>
                    <summary style={{ cursor: "pointer", fontWeight: 500 }}>
                      {rec.recommendation || "Unnamed recommendation"}
                    </summary>
                    <div style={{ marginTop: "0.5rem", fontSize: "0.875rem", lineHeight: 1.5 }}>
                      <p><strong>Asset:</strong> {rec.asset_name}</p>
                      <p><strong>Description:</strong> {rec.description || "No description available"}</p>
                    </div>
                  </details>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
