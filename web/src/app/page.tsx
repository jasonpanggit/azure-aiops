"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { SituationTable } from "@/components/SituationTable";
import { OverviewEvidence } from "@/components/OverviewEvidence";
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
import { connectionReviewReasons, overviewHref, overviewPosture } from "@/lib/overview";
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
  return <OverviewWorkspace key={JSON.stringify(scope)} />;
}

function OverviewWorkspace() {
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
  const connectionReviews = (state.connections?.data ?? []).map(connection => ({ connection, reasons: connectionReviewReasons(connection) }))
    .sort((a, b) => Number(b.reasons.length > 0) - Number(a.reasons.length > 0) || a.connection.name.localeCompare(b.connection.name));
  const attentionConnections = connectionReviews.filter(row => row.reasons.length > 0).length;
  const evidence = [
    ...(state.situations?.evidence ?? []),
    ...(state.vulnerabilities?.evidence ?? []),
    ...(state.network?.evidence ?? []),
    ...(state.connections?.evidence ?? []),
  ];
  const exposureCount = state.vulnerabilities?.data.internet_exposed_count ?? 0;
  const gapCount = state.network?.data.gap_count ?? 0;
  const posture = overviewPosture(state.situations ? criticalSituations : undefined,
    state.vulnerabilities?.data.internet_exposed_count, state.network?.data.gap_count);
  const postureScore = posture.score;
  const postureAvailable = postureScore !== null;
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
            <Link className="button button-primary" href={overviewHref("/situations", scope)}>
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
                {postureAvailable ? "Loaded heuristic posture is " : "Operational posture is "}
                <strong>{postureLabel.toLowerCase()}</strong>
              </h2>
              <p>
                A single view of service health, exploitable exposure, network controls, and evidence confidence across the selected operating scope.
              </p>
              <div className="command-center-actions">
                <Link className="button button-light" href={overviewHref(criticalSituations ? "/situations" : "/investigate", scope)}>
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
              ...(state.connections?.warnings ?? []),
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
                detail={state.situations ? `${situations.length} loaded situations ranked by priority and recency; lifecycle may include closed` : "Situation evidence unavailable"}
                tone={!state.situations ? "warning" : criticalSituations > 0 ? "critical" : "success"}
                action={
                  <Link className="inline-link" href={overviewHref("/situations", scope)}>
                    Investigate now
                  </Link>
                }
              />
              <MetricCard
                label="Internet-exposed findings"
                value={state.vulnerabilities?.data.internet_exposed_count ?? "—"}
                detail={state.vulnerabilities ? `${state.vulnerabilities.data.reachable_server_count} reachable findings in the legacy summary field; not distinct servers` : "Exposure evidence unavailable"}
                tone={!state.vulnerabilities ? "warning" : exposureCount > 0 ? "critical" : "success"}
                action={
                  <Link className="inline-link" href={overviewHref("/exposure", scope)}>
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
                  <Link className="inline-link" href={overviewHref("/network", scope)}>
                    Analyze paths
                  </Link>
                }
              />
              <MetricCard
                label="Connection reviews"
                value={state.connections ? attentionConnections : "—"}
                detail={state.connections ? `${state.connections.data.length} loaded registry rows; not publication coverage` : "Connection evidence unavailable"}
                tone={!state.connections || attentionConnections > 0 ? "warning" : "success"}
                action={
                  <Link className="inline-link" href={overviewHref("/connections", scope)}>
                    Check integrations
                  </Link>
                }
              />
            </div>
          </section>

          <OverviewEvidence posture={posture} scope={scope} sources={[
            { id: "situations", label: "Situations", path: "/situations", envelope: state.situations, loadedRows: state.situations?.data.length },
            { id: "exposure", label: "Exposure", path: "/exposure", envelope: state.vulnerabilities },
            { id: "network", label: "Network", path: "/network", envelope: state.network },
            { id: "connections", label: "Connections", path: "/connections", envelope: state.connections, loadedRows: state.connections?.data.length },
          ]} />

          <section className="dashboard-section">
            <div className="section-heading">
              <div>
                <h2>Priority situations</h2>
                <p>Loaded page ranked by assigned priority and recency, not a complete-estate or lifecycle-filtered queue.</p>
              </div>
              <Link className="section-link" href={overviewHref("/situations", scope)}>
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
                    { label: "Internet-exposed findings", value: exposureCount, tone: "critical" },
                    { label: "Network gaps", value: gapCount, tone: "warning" },
                    { label: "Connection reviews", value: attentionConnections, tone: "warning" },
                  ]}
                /> : <p className="muted">Signal concentration is unavailable until all source reads succeed.</p>}
              </div>
            </article>
            <article className="card">
              <div className="card-header">
                <div>
                  <h2>Loaded service associations</h2>
                  <p>Situation associations in this page; overlapping services are not unique incident counts.</p>
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
                        <span>{count} loaded situation{count === 1 ? "" : "s"}</span>
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
                {connectionReviews.slice(0, 6).map(({ connection, reasons }) => (
                  <div className="coverage-row" key={connection.connection_id}>
                    <div>
                      <strong>{connection.name}</strong>
                      <span>
                        {connection.business_service || "Unmapped service"} · {connection.environment || "No environment"}
                      </span>
                      <span>{reasons.length ? reasons.join(" · ") : "Registry reports healthy and sync succeeded; publication not verified"}</span>
                      <Link className="inline-link" href={overviewHref("/connections", scope, connection.is_active ? connection.connection_id : undefined)}>Review {connection.name}</Link>
                    </div>
                    <StatusBadge label={connection.health_status} tone={statusTone(connection.health_status)} />
                  </div>
                ))}
                {connectionReviews.length > 6 && <Link href={overviewHref("/connections", scope)}>Review all {connectionReviews.length} loaded connections</Link>}
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
                <Link className="section-link" href={overviewHref("/connections", scope)}>Manage</Link>
              </div>
              <div className="card-body">
                {state.connections ? <><CoverageDonut healthy={Math.max(0, state.connections.data.length - attentionConnections)} needsAttention={attentionConnections} />
                  <p className="muted">Loaded registry readiness only, not complete-estate, Fabric publication, or resource health coverage. Unknown and disabled states require review, not a healthy assumption.</p>
                </> : <p className="muted">Connection coverage is unavailable.</p>}
              </div>
            </article>
          </section>
        </>
      )}
    </div>
  );
}
