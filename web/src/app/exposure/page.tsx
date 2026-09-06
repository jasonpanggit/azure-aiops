"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { OperationsSignalChart } from "@/components/ui/OperationsSignalChart";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { buildCopilotSnapshot, copilotEvidenceRows, vulnerabilityApi } from "@/lib/services";

/**
 * Exposure overview / landing page. This is deliberately a lean summary —
 * headline KPIs, the highest-value action, and pointers into the two
 * dedicated detail views (Defender posture, Patch priorities), which own the
 * full tables, filters, and pagination for their respective signal families.
 * Duplicating those tables here would defeat the purpose of the page split.
 */
export default function ExposurePage() {
  const { scope } = useScope();
  const [copilotOpen, setCopilotOpen] = useState(false);

  const summary = useApi(() => vulnerabilityApi.summary(scope), [scope]);
  const authoritativeExposures = useApi(
    () => vulnerabilityApi.authoritativeExposures(scope),
    [scope],
  );
  const patches = useApi(() => vulnerabilityApi.patchPriorities(scope, {}), [scope]);
  const servers = useApi(() => vulnerabilityApi.assetExposures(scope, {}), [scope]);
  const defenderOverview = useApi(() => vulnerabilityApi.defenderOverview(scope), [scope]);
  const sla = useApi(() => vulnerabilityApi.slaCompliance(scope), [scope]);
  const riskExceptions = useApi(() => vulnerabilityApi.riskExceptions(scope), [scope]);

  const bestPatch = patches.data?.data[0];
  const serverInventoryCounts = useMemo(() => {
    return (servers.data?.data ?? []).reduce<Record<string, number>>((counts, server) => {
      counts[server.inventory_kind] = (counts[server.inventory_kind] ?? 0) + 1;
      return counts;
    }, {});
  }, [servers.data]);
  const serverInventorySummary = Object.entries(serverInventoryCounts)
    .map(([kind, count]) => `${kind}: ${count}`)
    .join(" · ");

  const expiringExceptionCount = useMemo(() => {
    const cutoff = Date.now() + 7 * 24 * 60 * 60 * 1000;
    let count = 0;
    for (const exception of riskExceptions.data?.data ?? []) {
      if (!exception.expires_at) continue;
      const expiresAt = Date.parse(exception.expires_at);
      if (!Number.isNaN(expiresAt) && expiresAt <= cutoff) count += 1;
    }
    return count;
  }, [riskExceptions.data]);

  // Named per-source so a single failing call doesn't block rendering of
  // sections whose own data loaded successfully.
  const sourceErrors = [
    { label: "Summary", error: summary.error },
    { label: "Authoritative exposure findings", error: authoritativeExposures.error },
    { label: "Patch priorities", error: patches.error },
    { label: "Asset exposures", error: servers.error },
    { label: "Defender secure score", error: defenderOverview.error },
    { label: "SLA compliance", error: sla.error },
    { label: "Risk exceptions", error: riskExceptions.error },
  ].filter((entry): entry is { label: string; error: Error } => entry.error != null);
  const fatalError = summary.error ?? servers.error;
  const loading = summary.loading || patches.loading || servers.loading || defenderOverview.loading || sla.loading;

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Exposure management"
        title="Which exposure should be reduced first?"
        description="Prioritize Defender for Cloud exposure across servers, containers, databases, storage, applications, and the rest of the discovered subscription inventory."
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about exposure" />}
        metadata={
          <>
            <span>{summary.data?.data.affected_business_service_count ?? 0} affected business services</span>
            <span>{summary.data?.data.affected_asset_count ?? 0} affected assets</span>
            <span>{summary.data?.data.defender_observed_asset_count ?? 0} Defender-observed vulnerable assets</span>
            <span>{serverInventorySummary || "Subscription inventory grouped by resource type"}</span>
            <span>Patch recommendations are advisory</span>
          </>
        }
      />

      <EvidenceBar
        evidence={[
          ...(summary.data?.evidence ?? []),
          ...(authoritativeExposures.data?.evidence ?? []),
          ...(patches.data?.evidence ?? []),
          ...(servers.data?.evidence ?? []),
          ...(defenderOverview.data?.evidence ?? []),
          ...(sla.data?.evidence ?? []),
        ]}
        knowledgeVersion={summary.data?.knowledge_version}
        warnings={[
          ...(summary.data?.warnings ?? []),
          ...(authoritativeExposures.data?.warnings ?? []),
          ...(patches.data?.warnings ?? []),
          ...(servers.data?.warnings ?? []),
          ...(defenderOverview.data?.warnings ?? []),
          ...(sla.data?.warnings ?? []),
        ]}
        fallbackTimestamp={summary.data?.data.freshness}
      />

      {fatalError ? (
        <StatePanel
          title="Exposure intelligence is unavailable"
          message={`${fatalError.message}. The workbench will not treat missing vulnerability data as an all-clear state.`}
          tone="error"
        />
      ) : loading ? (
        <StatePanel
          title="Ranking vulnerability exposure"
          message="Combining KB patch state, CVE intelligence, network reachability, and business service criticality."
          tone="loading"
        />
      ) : (
        <>
          {sourceErrors.length > 0 && (
            <StatePanel
              title="Some exposure sources are degraded"
              message={`${sourceErrors.map((entry) => `${entry.label}: ${entry.error.message}`).join(" · ")}. Sections below reflect only the sources that loaded.`}
              tone="error"
            />
          )}

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
              label="Exposed inventory"
              value={servers.data?.pagination?.total ?? servers.data?.data.length ?? "—"}
              detail={serverInventorySummary || "Affected resources across the subscription inventory"}
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

          <section className="card dashboard-visual-card exposure-signal-card">
            <div className="card-header">
              <div>
                <h2>Exposure profile</h2>
                <p>Prioritization signals across the authorized environment.</p>
              </div>
              <span className="visual-card-kicker">Decision view</span>
            </div>
            <div className="card-body">
              <OperationsSignalChart
                signals={[
                  { label: "Critical CVEs", value: summary.data?.data.critical_count ?? 0, tone: "critical" },
                  { label: "Internet exposed", value: summary.data?.data.internet_exposed_count ?? 0, tone: "critical" },
                  { label: "Reachable assets", value: summary.data?.data.reachable_server_count ?? 0, tone: "warning" },
                  { label: "Affected services", value: summary.data?.data.affected_business_service_count ?? 0, tone: "info" },
                ]}
              />
            </div>
          </section>

          <section className="card queue-card">
            <div className="card-header">
              <div>
                <h2>Authoritative exposure findings</h2>
                <p>
                  Scoped identities from the persisted Exposure generation, with
                  source coverage kept visible.
                </p>
              </div>
            </div>
            <div className="card-body">
              {authoritativeExposures.loading ? (
                <StatePanel
                  title="Loading authoritative exposure findings"
                  message="Reading the current governed Exposure generation."
                  tone="loading"
                />
              ) : authoritativeExposures.error ? (
                <StatePanel
                  title="Authoritative exposure findings are unavailable"
                  message={`${authoritativeExposures.error.message}. Other exposure sections remain usable.`}
                  tone="error"
                />
              ) : authoritativeExposures.data ? (
                <>
                  <div className="detail-grid">
                    <div>
                      <span>Generation</span>
                      <strong>
                        Generation{" "}
                        {authoritativeExposures.data.data.read_model_generation_id}
                      </strong>
                    </div>
                    <div>
                      <span>Coverage</span>
                      <strong>
                        {authoritativeExposures.data.data.completeness.state
                          .slice(0, 1)
                          .toUpperCase()}
                        {authoritativeExposures.data.data.completeness.state.slice(1)}
                        {" · "}
                        {
                          authoritativeExposures.data.data.completeness
                            .represented_connections
                        }{" "}
                        of{" "}
                        {
                          authoritativeExposures.data.data.completeness
                            .expected_connections
                        }{" "}
                        connections
                      </strong>
                    </div>
                    <div>
                      <span>Loaded findings</span>
                      <strong>
                        {authoritativeExposures.data.data.returned_count} of{" "}
                        {authoritativeExposures.data.data.total_count}
                      </strong>
                    </div>
                  </div>
                  <div className="chip-row" aria-label="Exposure source attribution">
                    {authoritativeExposures.data.data.source_attribution.map(
                      (source) => (
                        <span
                          className="chip"
                          key={source.source_family}
                        >
                          {source.source_family === "aum" ? "AUM" : "Defender"}{" "}
                          {source.finding_count} findings
                        </span>
                      ),
                    )}
                  </div>
                  <ul className="evidence-list">
                    {authoritativeExposures.data.data.findings.map((finding) => (
                      <li key={finding.exposure_id}>
                        <strong>{finding.exposure_id}</strong>
                        <span>
                          {finding.weakness_id} ·{" "}
                          {finding.source_families
                            .map((source) =>
                              source === "aum" ? "AUM" : "Defender",
                            )
                            .join(" + ")}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <StatePanel
                  title="No authoritative exposure findings"
                  message="The current scoped generation contains no findings."
                  tone="empty"
                />
              )}
            </div>
          </section>

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

          <div className="exposure-landing-sections">
            <Link href="/exposure/defender-posture" className="card queue-card exposure-summary-link">
              <div className="card-header">
                <div>
                  <h2>Defender posture →</h2>
                  <p>Active alerts, attack paths, secure-score controls, and unhealthy recommendations across enabled Defender plans.</p>
                </div>
              </div>
              <div className="card-body">
                <div className="metric-grid exposure-metrics">
                  <MetricCard
                    label="Active alerts"
                    value={defenderOverview.data?.data.active_alert_count ?? "—"}
                    detail={`${defenderOverview.data?.data.critical_alert_count ?? 0} critical alerts`}
                    tone={(defenderOverview.data?.data.critical_alert_count ?? 0) > 0 ? "critical" : "warning"}
                  />
                  <MetricCard
                    label="Attack paths"
                    value={defenderOverview.data?.data.attack_path_count ?? "—"}
                    detail="Exploitable routes reported by Defender CSPM"
                    tone={(defenderOverview.data?.data.attack_path_count ?? 0) > 0 ? "critical" : "success"}
                  />
                  <MetricCard
                    label="Defender recommendations"
                    value={summary.data?.data.defender_posture_count ?? summary.data?.data.defender_recommendation_count ?? "—"}
                    detail="Unhealthy recommendations across protected resource families"
                    tone={(summary.data?.data.defender_posture_count ?? summary.data?.data.defender_recommendation_count ?? 0) > 0 ? "warning" : "success"}
                  />
                  <MetricCard
                    label="Signal coverage"
                    value={`${Object.values(defenderOverview.data?.data.coverage ?? {}).filter((state) => state.availability === "available").length}/4`}
                    detail="Unavailable sources remain unknown, never healthy"
                    tone={Object.values(defenderOverview.data?.data.coverage ?? {}).some((state) => state.availability !== "available") ? "warning" : "success"}
                  />
                </div>
              </div>
            </Link>

            <Link href="/exposure/patch-priorities" className="card queue-card exposure-summary-link">
              <div className="card-header">
                <div>
                  <h2>Patch priorities →</h2>
                  <p>SLA compliance, the patch/CVE inventory, and active risk exceptions.</p>
                </div>
              </div>
              <div className="card-body">
                <div className="metric-grid exposure-metrics">
                  <MetricCard
                    label="Overall compliance"
                    value={
                      sla.data?.data?.overall_compliance_rate == null
                        ? "—"
                        : `${Math.round(sla.data.data.overall_compliance_rate * 100)}%`
                    }
                    detail={sla.data?.data ? `${sla.data.data.compliant_count} of ${sla.data.data.tracked_count} tracked findings within SLA` : "SLA data unavailable"}
                    tone={(sla.data?.data?.overdue_count ?? 0) > 0 ? "warning" : "success"}
                  />
                  <MetricCard
                    label="Overdue findings"
                    value={sla.data?.data?.overdue_count ?? "—"}
                    detail={sla.data?.data ? `${sla.data.data.open_count} total open findings` : "SLA data unavailable"}
                    tone={(sla.data?.data?.overdue_count ?? 0) > 0 ? "critical" : "success"}
                  />
                  <MetricCard
                    label="Active risk exceptions"
                    value={riskExceptions.data?.data?.length ?? "—"}
                    detail={expiringExceptionCount > 0 ? `${expiringExceptionCount} expiring within 7 days` : "None expiring soon"}
                    tone={expiringExceptionCount > 0 ? "warning" : "default"}
                  />
                </div>
              </div>
            </Link>
          </div>
        </>
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Vulnerability exposure"
        snapshot={buildCopilotSnapshot({
          pageKind: "vulnerability",
          pageId: "exposure",
          scope,
          filters: {},
          evidence: copilotEvidenceRows("vulnerability", [
            ...(summary.data?.evidence ?? []),
            ...(authoritativeExposures.data?.evidence ?? []),
            ...(patches.data?.evidence ?? []),
            ...(servers.data?.evidence ?? []),
          ], [
            ...(authoritativeExposures.data?.data.findings ?? []),
            ...(patches.data?.data ?? []),
            ...(servers.data?.data ?? []),
          ]),
        })}
        starterQuestions={[
          { label: "Which CVEs affect our highest-risk service?", tool: "cve_exposure", toolArguments: {} },
          { label: "What should be patched first?", tool: "cve_exposure", toolArguments: {} },
          { label: "Which Defender plans have the most open recommendations?", tool: "cve_exposure", toolArguments: {} },
        ]}
      />
    </div>
  );
}
