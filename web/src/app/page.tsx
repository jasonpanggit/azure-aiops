"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { SituationTable } from "@/components/SituationTable";
import { CopilotLauncher } from "@/components/ui/CopilotLauncher";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { useScope } from "@/lib/scope-context";
import { connectionsApi, networkApi, operationsApi, vulnerabilityApi } from "@/lib/services";
import { rankSituations } from "@/lib/situations";
import type {
  Envelope,
  IncidentReport,
  NetworkSummary,
  SubscriptionConnection,
  VulnerabilitySummary,
} from "@/lib/types";

interface DashboardState {
  incidents?: Envelope<IncidentReport>;
  network?: Envelope<NetworkSummary>;
  vulnerabilities?: Envelope<VulnerabilitySummary>;
  connections?: Envelope<SubscriptionConnection[]>;
  errors: string[];
}

/** Service-aware command center that ranks what needs operator attention now. */
export default function Home() {
  const { scope } = useScope();
  const [state, setState] = useState<DashboardState>({ errors: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.allSettled([
      operationsApi.incidents(scope, 0, 20),
      networkApi.summary(scope),
      vulnerabilityApi.summary(scope),
      connectionsApi.list(scope, 0, 100),
    ]).then((results) => {
      if (!active) return;
      const errors: string[] = [];
      const values = results.map((result, index) => {
        if (result.status === "fulfilled") return result.value;
        const surfaces = ["situations", "network", "exposure", "connections"];
        errors.push(`${surfaces[index]} data unavailable`);
        return undefined;
      });
      setState({
        incidents: values[0] as Envelope<IncidentReport> | undefined,
        network: values[1] as Envelope<NetworkSummary> | undefined,
        vulnerabilities: values[2] as Envelope<VulnerabilitySummary> | undefined,
        connections: values[3] as Envelope<SubscriptionConnection[]> | undefined,
        errors,
      });
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [scope]);

  const situations = useMemo(
    () => rankSituations(state.incidents?.data.incidents ?? []),
    [state.incidents]
  );
  const criticalSituations = situations.filter((situation) => situation.priority === "P1").length;
  const staleConnections =
    state.connections?.data.filter(
      (connection) => connection.health_status === "stale" || connection.sync_status === "failed"
    ).length ?? 0;
  const evidence = [
    ...(state.incidents?.evidence ?? []),
    ...(state.vulnerabilities?.evidence ?? []),
    ...(state.network?.evidence ?? []),
  ];

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="My operations"
        title="What needs attention now"
        description="Prioritized operational risk across services, applications, environments, subscriptions, and resources."
        actions={
          <Link className="button button-primary" href="/situations">
            Open Situation queue
          </Link>
        }
      />

      {loading ? (
        <StatePanel
          title="Building your operational picture"
          message="Correlating incidents, network controls, vulnerabilities, and subscription health."
          tone="loading"
        />
      ) : (
        <>
          <EvidenceBar
            evidence={evidence}
            knowledgeVersion={state.incidents?.knowledge_version}
            warnings={[
              ...(state.incidents?.warnings ?? []),
              ...(state.network?.warnings ?? []),
              ...(state.vulnerabilities?.warnings ?? []),
              ...state.errors,
            ]}
          />

          <CopilotLauncher
            starterQuestions={[
              "what needs attention right now",
              "which services have the highest risk",
              "what should be fixed first",
            ]}
          />

          <section className="dashboard-section">
            <div className="metric-grid">
              <MetricCard
                label="Critical situations"
                value={criticalSituations}
                detail={`${situations.length} active situations ranked by business impact`}
                tone={criticalSituations > 0 ? "critical" : "success"}
                action={
                  <Link className="inline-link" href="/situations">
                    Investigate now
                  </Link>
                }
              />
              <MetricCard
                label="Internet-reachable CVEs"
                value={state.vulnerabilities?.data.internet_exposed_count ?? "—"}
                detail={`${state.vulnerabilities?.data.reachable_server_count ?? 0} reachable servers require review`}
                tone={(state.vulnerabilities?.data.internet_exposed_count ?? 0) > 0 ? "critical" : "success"}
                action={
                  <Link className="inline-link" href="/exposure">
                    Review exposure
                  </Link>
                }
              />
              <MetricCard
                label="Network control gaps"
                value={state.network?.data.gap_count ?? "—"}
                detail={`${state.network?.data.rule_finding_count ?? 0} rule findings across observed paths`}
                tone={(state.network?.data.gap_count ?? 0) > 0 ? "warning" : "success"}
                action={
                  <Link className="inline-link" href="/network">
                    Analyze paths
                  </Link>
                }
              />
              <MetricCard
                label="Data coverage risk"
                value={staleConnections}
                detail={`${state.connections?.data.length ?? 0} onboarded subscription connections`}
                tone={staleConnections > 0 ? "warning" : "success"}
                action={
                  <Link className="inline-link" href="/connections">
                    Check integrations
                  </Link>
                }
              />
            </div>
          </section>

          <section className="dashboard-section">
            <div className="section-heading">
              <div>
                <h2>Priority situations</h2>
                <p>Ranked by severity, business blast radius, and recency—not alert volume.</p>
              </div>
              <Link className="section-link" href="/situations">
                View all
              </Link>
            </div>
            <div className="card">
              {situations.length > 0 ? (
                <SituationTable situations={situations.slice(0, 6)} compact />
              ) : (
                <StatePanel
                  title="No active situations in this scope"
                  message="No incident correlations are currently available. Data coverage and freshness remain visible below."
                />
              )}
            </div>
          </section>

          <section className="dashboard-grid">
            <article className="card">
              <div className="card-header">
                <div>
                  <h2>Service risk concentration</h2>
                  <p>Where active situations create the greatest operational exposure.</p>
                </div>
              </div>
              <div className="card-body service-risk-list">
                {Array.from(
                  situations.reduce((totals, situation) => {
                    for (const service of situation.businessServices.length
                      ? situation.businessServices
                      : ["Unmapped service"]) {
                      totals.set(service, (totals.get(service) ?? 0) + 1);
                    }
                    return totals;
                  }, new Map<string, number>())
                )
                  .sort((left, right) => right[1] - left[1])
                  .slice(0, 5)
                  .map(([service, count]) => (
                    <div className="service-risk-row" key={service}>
                      <div>
                        <strong>{service}</strong>
                        <span>{count} active situation{count === 1 ? "" : "s"}</span>
                      </div>
                      <StatusBadge label={count > 1 ? "Elevated risk" : "Monitor"} tone={count > 1 ? "high" : "warning"} />
                    </div>
                  ))}
                {situations.length === 0 && <span className="muted">No service risk is currently correlated.</span>}
              </div>
            </article>

            <article className="card">
              <div className="card-header">
                <div>
                  <h2>Operational data coverage</h2>
                  <p>Confidence in the evidence behind workbench recommendations.</p>
                </div>
              </div>
              <div className="card-body coverage-list">
                {(state.connections?.data ?? []).slice(0, 6).map((connection) => (
                  <div className="coverage-row" key={connection.connection_id}>
                    <div>
                      <strong>{connection.name}</strong>
                      <span>
                        {connection.business_service || "Unmapped service"} · {connection.environment || "No environment"}
                      </span>
                    </div>
                    <StatusBadge label={connection.health_status} tone={statusTone(connection.health_status)} />
                  </div>
                ))}
                {(state.connections?.data.length ?? 0) === 0 && (
                  <span className="muted">No subscription connections are visible in this scope.</span>
                )}
              </div>
            </article>
          </section>
        </>
      )}
    </div>
  );
}
