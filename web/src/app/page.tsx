"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { SituationTable } from "@/components/SituationTable";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { CoverageDonut, OperationsSignalChart } from "@/components/ui/OperationsSignalChart";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { buildOverviewCopilotContext } from "@/lib/copilot/page-adapters";
import { useScope } from "@/lib/scope-context";
import { connectionsApi, networkApi, situationsApi, vulnerabilityApi } from "@/lib/services";
import { rankDurableSituations } from "@/lib/situations";
import type {
  Envelope,
  NetworkSummary,
  SubscriptionConnection,
  VulnerabilitySummary,
} from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

interface DashboardState {
  situations?: Envelope<import("@/lib/types").DurableSituation[]>;
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
  const [copilotOpen, setCopilotOpen] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.allSettled([
      situationsApi.list(scope, "", "", 0, 100),
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
        situations: values[0] as Envelope<import("@/lib/types").DurableSituation[]> | undefined,
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
    () => rankDurableSituations(state.situations?.data ?? []),
    [state.situations]
  );
  const criticalSituations = situations.filter((situation) => situation.priority === "P1").length;
  const staleConnections =
    state.connections?.data.filter(
      (connection) => connection.health_status === "stale" || connection.sync_status === "failed"
    ).length ?? 0;
  const evidence = [
    ...(state.situations?.evidence ?? []),
    ...(state.vulnerabilities?.evidence ?? []),
    ...(state.network?.evidence ?? []),
  ];
  const exposureCount = state.vulnerabilities?.data.internet_exposed_count ?? 0;
  const gapCount = state.network?.data.gap_count ?? 0;
  const postureAvailable = Boolean(state.situations && state.vulnerabilities && state.network);
  const postureScore = postureAvailable
    ? Math.max(0, Math.min(100, 100 - criticalSituations * 18 - exposureCount * 7 - gapCount * 4))
    : null;
  const postureLabel = postureScore === null ? "Not assessed" : postureScore >= 80 ? "Controlled" : postureScore >= 60 ? "Needs attention" : "Elevated";
  const postureTone = postureScore === null ? "warning" : postureScore >= 80 ? "success" : postureScore >= 60 ? "warning" : "critical";
  const scopeLabel =
    scope.business_service?.[0] ??
    scope.application?.[0] ??
    scope.environment?.[0] ??
    scope.subscription_connection?.[0] ??
    scope.subscription?.[0] ??
    "All authorized environments";
  const overviewCopilot = buildOverviewCopilotContext({
    scope,
    situations: state.situations,
    network: state.network,
    vulnerabilities: state.vulnerabilities,
    connections: state.connections,
    visibleSituationIds: situations.map((situation) => situation.id),
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="My operations"
        title="What needs attention now"
        description="Prioritized operational risk across services, applications, environments, subscriptions, and resources."
        actions={
          <>
            <CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot what needs attention" />
            <Link className="button button-primary" href="/situations">
              Open Situation queue
            </Link>
          </>
        }
      />

      <CopilotInsights
        snapshot={overviewCopilot.snapshot}
        ready={!loading}
        requestedScope={overviewCopilot.requestedScope}
        contextLabel="Operations overview"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      {loading ? (
        <StatePanel
          title="Building your operational picture"
          message="Correlating incidents, network controls, vulnerabilities, and subscription health."
          tone="loading"
        />
      ) : (
        <>
          <section className={`command-center-hero command-center-${postureTone}`} aria-label="Operational posture">
            <div className="command-center-glow" aria-hidden="true" />
            <div className="command-center-copy">
              <div className="command-center-kicker">
                <span className="live-pulse" /> Live operational posture
              </div>
              <h2>
                {postureAvailable ? "Your environment is " : "Operational posture is "}
                <strong>{postureLabel.toLowerCase()}</strong>
              </h2>
              <p>
                A single view of service health, exploitable exposure, network controls, and evidence confidence across the selected operating scope.
              </p>
              <div className="command-center-actions">
                <Link className="button button-light" href={criticalSituations ? "/situations" : "/investigate"}>
                  {criticalSituations ? "Investigate top situation" : "Run an investigation"}
                </Link>
                <span className="command-center-updated">Scope: {scopeLabel}</span>
              </div>
            </div>
            <div className="posture-orbit" aria-label={postureScore === null ? "Posture score unavailable" : `Posture score ${postureScore} out of 100`}>
              <div className="posture-orbit-ring" />
              <div className="posture-score">{postureScore ?? "—"}</div>
              <div className="posture-score-label">posture score</div>
            </div>
            <div className="command-center-facts">
              <div><span>Priority situations</span><strong>{state.situations ? situations.length : "—"}</strong></div>
              <div><span>Reachable exposure</span><strong>{state.vulnerabilities ? exposureCount : "—"}</strong></div>
              <div><span>Evidence signals</span><strong>{evidence.length}</strong></div>
            </div>
          </section>

          <EvidenceBar
            evidence={evidence}
            knowledgeVersion={state.situations?.knowledge_version}
            warnings={[
              ...(state.situations?.warnings ?? []),
              ...(state.network?.warnings ?? []),
              ...(state.vulnerabilities?.warnings ?? []),
              ...state.errors,
            ]}
          />

          <CopilotDrawer
            open={copilotOpen}
            onClose={() => setCopilotOpen(false)}
            contextLabel="Operations overview"
            requestedScope={overviewCopilot.requestedScope}
            snapshot={overviewCopilot.snapshot}
            starterQuestions={overviewCopilot.starterQuestions}
          />

          <section className="dashboard-section">
            <div className="metric-grid">
              <MetricCard
                label="Critical situations"
                value={state.situations ? criticalSituations : "—"}
                detail={state.situations ? `${situations.length} active situations ranked by business impact` : "Situation evidence unavailable"}
                tone={!state.situations ? "warning" : criticalSituations > 0 ? "critical" : "success"}
                action={
                  <Link className="inline-link" href="/situations">
                    Investigate now
                  </Link>
                }
              />
              <MetricCard
                label="Internet-reachable CVEs"
                value={state.vulnerabilities?.data.internet_exposed_count ?? "—"}
                detail={state.vulnerabilities ? `${state.vulnerabilities.data.reachable_server_count} reachable servers require review` : "Exposure evidence unavailable"}
                tone={!state.vulnerabilities ? "warning" : exposureCount > 0 ? "critical" : "success"}
                action={
                  <Link className="inline-link" href="/exposure">
                    Review exposure
                  </Link>
                }
              />
              <MetricCard
                label="Network control gaps"
                value={state.network?.data.gap_count ?? "—"}
                detail={state.network ? `${state.network.data.rule_finding_count} rule findings across observed paths` : "Network evidence unavailable"}
                tone={!state.network || gapCount > 0 ? "warning" : "success"}
                action={
                  <Link className="inline-link" href="/network">
                    Analyze paths
                  </Link>
                }
              />
              <MetricCard
                label="Data coverage risk"
                value={state.connections ? staleConnections : "—"}
                detail={state.connections ? `${state.connections.data.length} onboarded subscription connections` : "Connection evidence unavailable"}
                tone={!state.connections || staleConnections > 0 ? "warning" : "success"}
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
                  title={state.situations ? "No active situations in this scope" : "Situation evidence unavailable"}
                  message={state.situations ? "No incident correlations are currently available. Data coverage and freshness remain visible below." : "Situation data could not be loaded. An empty queue has not been confirmed."}
                />
              )}
            </div>
          </section>

          <section className="dashboard-grid">
            <article className="card dashboard-visual-card">
              <div className="card-header">
                <div>
                  <h2>Signal concentration</h2>
                  <p>Where operator attention is concentrated right now.</p>
                </div>
                <span className="visual-card-kicker">Live scope</span>
              </div>
              <div className="card-body">
                {postureAvailable && state.connections ? <OperationsSignalChart
                  signals={[
                    { label: "Priority situations", value: criticalSituations, tone: "critical" },
                    { label: "Reachable exposure", value: exposureCount, tone: "critical" },
                    { label: "Network gaps", value: gapCount, tone: "warning" },
                    { label: "Stale connections", value: staleConnections, tone: "warning" },
                  ]}
                /> : <p className="muted">Signal concentration is unavailable until all source reads succeed.</p>}
              </div>
            </article>
            <article className="card">
              <div className="card-header">
                <div>
                  <h2>Service risk concentration</h2>
                  <p>Where active situations create the greatest operational exposure.</p>
                </div>
              </div>
              <div className="card-body service-risk-list">
                {(() => {
                  const totals = Array.from(
                    situations.reduce((acc, situation) => {
                      for (const service of situation.businessServices.length
                        ? situation.businessServices
                        : ["Unmapped service"]) {
                        acc.set(service, (acc.get(service) ?? 0) + 1);
                      }
                      return acc;
                    }, new Map<string, number>())
                  )
                    .sort((left, right) => right[1] - left[1])
                    .slice(0, 5);
                  const maxCount = Math.max(1, ...totals.map(([, count]) => count));
                  return totals.map(([service, count]) => (
                    <div className="service-risk-row" key={service}>
                      <div className="service-risk-bar" style={{ width: `${(count / maxCount) * 100}%` }} aria-hidden />
                      <div>
                        <strong>{service}</strong>
                        <span>{count} active situation{count === 1 ? "" : "s"}</span>
                      </div>
                      <StatusBadge label={count > 1 ? "Elevated risk" : "Monitor"} tone={count > 1 ? "high" : "warning"} />
                    </div>
                  ));
                })()}
                {situations.length === 0 && <span className="muted">{state.situations ? "No service risk is currently correlated." : "Service risk cannot be assessed without situation evidence."}</span>}
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
                  <span className="muted">{state.connections ? "No subscription connections are visible in this scope." : "Subscription connection evidence is unavailable."}</span>
                )}
              </div>
            </article>
            <article className="card dashboard-visual-card">
              <div className="card-header">
                <div>
                  <h2>Connection coverage</h2>
                  <p>Health of the data sources behind recommendations.</p>
                </div>
                <Link className="section-link" href="/connections">Manage</Link>
              </div>
              <div className="card-body">
                {state.connections ? <CoverageDonut healthy={Math.max(0, state.connections.data.length - staleConnections)} needsAttention={staleConnections} /> : <p className="muted">Connection coverage is unavailable.</p>}
              </div>
            </article>
          </section>
        </>
      )}
    </div>
  );
}
