"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { TablePagination } from "@/components/ui/TablePagination";
import { TopologyWorkspace } from "@/components/network/TopologyWorkspace";
import type { TopologyDetailLevel } from "@/components/network/TopologyWorkspace";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { titleize } from "@/lib/format";
import { presentVerdict } from "@/lib/flow-verdict";
import { useScope } from "@/lib/scope-context";
import { buildCopilotSnapshot, copilotEvidenceRows, networkApi } from "@/lib/services";
import { ApiError } from "@/lib/types";
import type { CopilotEvidenceRow, FlowResult, NetworkGap, NetworkPolicyRule, NetworkSeverity, NetworkSummary, RuleFinding } from "@/lib/types";

type NetworkTab = "flow" | "topology" | "gaps" | "rules" | "policy";
const NETWORK_PAGE_SIZE = 100;

/** Network decision workspace for cross-environment reachability, inspection, and rule analysis. */
export default function NetworkPage() {
  const { scope } = useScope();
  const [tab, setTab] = useState<NetworkTab>("flow");
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [gapPage, setGapPage] = useState(0);
  const [gapPageSize, setGapPageSize] = useState(NETWORK_PAGE_SIZE);
  const [findingPage, setFindingPage] = useState(0);
  const [findingPageSize, setFindingPageSize] = useState(NETWORK_PAGE_SIZE);
  const [topologyDetail, setTopologyDetail] =
    useState<TopologyDetailLevel>("summary");
  const [policyFeedback, setPolicyFeedback] = useState<{ tone: "success" | "warning"; message: string } | null>(null);
  const [pendingPolicyRefresh, setPendingPolicyRefresh] = useState<{
    beforeGapTotal: number;
    previousGaps: unknown;
    successMessage?: string;
    saved: boolean;
  } | null>(null);
  const topology = useApi(
    () => networkApi.topology(scope, { detail: topologyDetail }),
    [scope, topologyDetail],
  );
  const gaps = useApi(
    () => networkApi.gaps(scope, { limit: gapPageSize, offset: gapPage * gapPageSize }),
    [scope, gapPage, gapPageSize],
  );
  const findings = useApi(
    () => networkApi.ruleFindings(scope, { limit: findingPageSize, offset: findingPage * findingPageSize }),
    [scope, findingPage, findingPageSize],
  );
  const bypass = useApi(() => networkApi.firewallBypass(scope), [scope]);

  const summary = topology.data?.data.summary;
  const gapTotal = gaps.data?.data.summary.gap_count;
  const findingTotal = findings.data?.data.summary.rule_finding_count;
  const gapCoverage = gaps.data?.data.coverage;
  const findingCoverage = findings.data?.data.coverage;
  const flowLogProvenance = topology.data?.data.topology.flow_log_provenance;
  const loadBadgeGapsPage = useCallback(
    (offset: number, limit: number) => networkApi.gaps(scope, { offset, limit }),
    [scope],
  );
  const loadBadgeRuleFindingsPage = useCallback(
    (offset: number, limit: number) =>
      networkApi.ruleFindings(scope, { offset, limit }),
    [scope],
  );

  function refreshDerivedAnalysis(options: { saved?: boolean; successMessage?: string } = {}) {
    setPolicyFeedback(null);
    setPendingPolicyRefresh({
      beforeGapTotal: gapTotal ?? 0,
      previousGaps: gaps.data,
      successMessage: options.successMessage,
      saved: options.saved ?? false,
    });
    topology.refetch();
    gaps.refetch();
    findings.refetch();
  }

  useEffect(() => {
    if (!pendingPolicyRefresh || gaps.loading || !gaps.data || gaps.data === pendingPolicyRefresh.previousGaps) return;
    const afterGapTotal = gaps.data.data.summary.gap_count;
    const serverSignalsCached =
      Boolean((gaps.data.data as { analysis_cached?: boolean; cached_analysis?: boolean }).analysis_cached) ||
      Boolean((gaps.data.data as { analysis_cached?: boolean; cached_analysis?: boolean }).cached_analysis) ||
      Boolean(gaps.data.warnings?.some((warning) => /cache|stale|not refreshed/i.test(warning)));
    if (pendingPolicyRefresh.saved && afterGapTotal === pendingPolicyRefresh.beforeGapTotal && serverSignalsCached) {
      setPolicyFeedback({
        tone: "warning",
        message: "Saved. Derived analysis has not refreshed yet — retry in a moment.",
      });
    } else if (pendingPolicyRefresh.saved) {
      setPolicyFeedback({
        tone: "success",
        message: `Rule saved. Inspection gaps ${pendingPolicyRefresh.beforeGapTotal} → ${afterGapTotal}.`,
      });
    } else {
      setPolicyFeedback({
        tone: "success",
        message: pendingPolicyRefresh.successMessage ?? "Policy updated. Gaps and badges updated.",
      });
    }
    setPendingPolicyRefresh(null);
  }, [gaps.data, gaps.loading, pendingPolicyRefresh]);
  const evidence = [
    ...(topology.data?.evidence ?? []),
    ...(gaps.data?.evidence ?? []),
    ...(findings.data?.evidence ?? []),
    ...(bypass.data?.evidence ?? []),
  ];
  const warnings = [
    ...(topology.data?.warnings ?? []),
    ...(gaps.data?.warnings ?? []),
    ...(findings.data?.warnings ?? []),
    ...(bypass.data?.warnings ?? []),
  ];
  const bypassGaps = bypass.data?.data.gaps ?? [];
  const networkCopilotRecords = [
    {
      check: "topology",
      compliant: true,
      summary,
      connection_ids: topology.data?.data.topology.connection_ids ?? [],
      unresolved_peer_vnet_ids: topology.data?.data.topology.unresolved_peer_vnet_ids ?? [],
    },
    ...(gaps.data?.data.gaps ?? []).map(networkGapEvidence),
    ...(findings.data?.data.findings ?? []).map(ruleFindingEvidence),
  ];
  const networkCopilotEvidence = [
    ...copilotEvidenceRows("source", evidence),
    ...copilotEvidenceRows("network", [], networkCopilotRecords),
    ...bypassGaps.map(firewallBypassEvidence),
  ];

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Network intelligence"
        title="Topology & traffic paths"
        description="Ask whether one environment can reach another, identify every deciding control, and expose paths that bypass inspection."
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about network paths" />}
        metadata={
          <>
            <span>{summary ? summary.connection_count : "—"} subscription connections</span>
            <span>Configuration-derived analysis</span>
            <span>{flowLogProvenanceText(flowLogProvenance)}</span>
          </>
        }
      />

      <EvidenceBar
        evidence={evidence}
        knowledgeVersion={topology.data?.knowledge_version}
        graphFreshness={topology.data?.graph_freshness}
        warnings={warnings}
      />

      <div className="metric-grid network-metrics">
        <MetricCard
          label="Observed network"
          value={summary ? `${summary.hub_count} / ${summary.spoke_count}` : "—"}
          detail="Hub / spoke VNets across the current scope"
        />
        <MetricCard
          label="Inspection bypass"
          value={bypass.data?.data.count ?? "—"}
          detail="Spokes with a path that may avoid firewall inspection"
          tone={bypass.data ? (bypass.data.data.count > 0 ? "critical" : "success") : "default"}
        />
        <MetricCard
          label="Unhealthy peerings"
          value={summary?.unhealthy_peering_count ?? "—"}
          detail={summary ? `${summary.cross_subscription_peering_count} cross-subscription peerings` : "— cross-subscription peerings"}
          tone={summary ? (summary.unhealthy_peering_count > 0 ? "warning" : "success") : "default"}
        />
        <MetricCard
          label="Broad or risky rules"
          value={findingTotal ?? "—"}
          detail={`${gapTotal ?? "—"} structural or design gaps`}
          tone={findingTotal == null ? "default" : findingTotal > 0 ? "warning" : "success"}
        />
      </div>

      {!gaps.loading && gaps.data && !gaps.data.data.intended_design_declared && (
        <div className="callout callout-warning">
          <strong>Intended design is not declared.</strong>
          <span>
            The workbench can prove observed structure and rule decisions, but cannot label deviations from an approved
            hub-spoke policy until that intent is mapped.
          </span>
        </div>
      )}

      {gaps.data && findings.data && (gapCoverage?.truncated || findingCoverage?.truncated) && (
        <div className="callout callout-warning topology-coverage">
          <strong>Results are incomplete.</strong>
          <span>
            Showing {gapCoverage?.returned ?? gaps.data?.data.gaps.length ?? 0} of{" "}
            {gapCoverage?.total ?? gapTotal ?? 0} inspection gaps and{" "}
            {findingCoverage?.returned ?? findings.data?.data.findings.length ?? 0} of{" "}
            {findingCoverage?.total ?? findingTotal ?? 0} rule findings. Metric totals are complete; the lists below are not.
          </span>
        </div>
      )}

      <div className="workspace-tabs" role="tablist" aria-label="Network analysis views">
        {(
          [
            ["flow", "Path analysis"],
            ["topology", "Topology"],
            ["gaps", "Inspection gaps"],
            ["rules", "Rule findings"],
            ["policy", "Design policy"],
          ] as Array<[NetworkTab, string]>
        ).map(([value, label]) => (
          <button
            type="button"
            role="tab"
            aria-selected={tab === value}
            className={tab === value ? "workspace-tab-active" : ""}
            onClick={() => setTab(value)}
            key={value}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "flow" && <TrafficFlowWorkspace />}
      {tab === "topology" && (
        topology.error && !topology.data ? (
          <StatePanel
            title="Topology is unavailable"
            message={`${topology.error.message}. No topology has been inferred for this scope.`}
            tone="error"
            action={<RetryButton label="Retry loading topology" loading={topology.loading} onClick={topology.refetch} />}
          />
        ) : (
          <section aria-busy={topology.loading}>
            <TopologyWorkspace
              topology={topology.data?.data.topology ?? null}
              summary={topology.data?.data.summary ?? null}
              detailLevel={topologyDetail}
              onDetailLevelChange={setTopologyDetail}
              loading={topology.loading}
              error={topology.error}
              gaps={gaps.data?.data.gaps ?? []}
              ruleFindings={findings.data?.data.findings ?? []}
              loadGapsPage={loadBadgeGapsPage}
              loadRuleFindingsPage={loadBadgeRuleFindingsPage}
              findingsLoading={gaps.loading || findings.loading}
              findingsError={gaps.error ?? findings.error}
              findingsTruncated={Boolean(
                gaps.data?.data.coverage?.truncated ||
                  findings.data?.data.coverage?.truncated,
              )}
              onRetryFindings={
                gaps.error ? gaps.refetch : findings.error ? findings.refetch : gaps.refetch
              }
              scope={topology.data?.scope ?? null}
              evidence={topology.data?.evidence ?? null}
              warnings={topology.data?.warnings ?? null}
              knowledgeVersion={topology.data?.knowledge_version ?? null}
              graphFreshness={topology.data?.graph_freshness}
            />
          </section>
        )
      )}
      {tab === "gaps" && (
        <FindingList
          title="Inspection and design gaps"
          description="Paths and structures that reduce visibility or violate declared intent."
          items={(gaps.data?.data.gaps ?? []).map((gap) => ({
            id: gap.gap_id,
            severity: gap.severity,
            title: gap.title,
            context: gap.resource_name || gap.resource_id,
            detail: gap.detail,
            recommendation: gap.recommendation,
            basis: gap.basis,
          }))}
          loading={gaps.loading}
          error={gaps.error}
          errorTitle="Inspection gaps are unavailable"
          errorMessage={gaps.error ? `${gaps.error.message}. Absence of findings below does not mean the estate is clean.` : ""}
          emptyTitle="No inspection gaps detected"
          emptyMessage="Every rule in the design policy was evaluated against the current scope and produced no finding."
          pagination={gaps.data?.pagination}
          page={gapPage}
          pageSize={gapPageSize}
          label="inspection gaps"
          onPageChange={setGapPage}
          onPageSizeChange={(size) => {
            setGapPage(0);
            setGapPageSize(size);
          }}
          onRetry={gaps.refetch}
        />
      )}
      {tab === "rules" && (
        <FindingList
          title="Rule tightening opportunities"
          description="Configuration-derived findings. “Unused” means no structural path was observed, not that no traffic occurred."
          items={(findings.data?.data.findings ?? []).map((finding) => ruleListItem(finding))}
          loading={findings.loading}
          error={findings.error}
          errorTitle="Rule findings are unavailable"
          errorMessage={findings.error ? `${findings.error.message}. Absence of findings below does not mean the estate is clean.` : ""}
          emptyTitle="No rule findings detected"
          emptyMessage="Every observed NSG, firewall, and route rule was evaluated and none was flagged."
          pagination={findings.data?.pagination}
          page={findingPage}
          pageSize={findingPageSize}
          label="rule findings"
          onPageChange={setFindingPage}
          onPageSizeChange={(size) => {
            setFindingPage(0);
            setFindingPageSize(size);
          }}
          onRetry={findings.refetch}
        />
      )}
      {tab === "policy" && (
        <DesignPolicyWorkspace
          onPolicyChanged={refreshDerivedAnalysis}
          feedback={policyFeedback}
          refreshing={pendingPolicyRefresh !== null}
        />
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Network topology"
        snapshot={buildCopilotSnapshot({
          pageKind: "network",
          pageId: "network-topology",
          scope,
          filters: { tab: [tab] },
          selectedResources: topology.data?.data.topology.hubs.slice(0, 50).map((hub) => ({
            resource_id: hub.vnet_id,
            resource_type: "Microsoft.Network/virtualNetworks",
            name: hub.name,
          })) ?? [],
          evidence: networkCopilotEvidence,
        })}
        starterQuestions={[
          {
            label: "Can UAT reach PROD?",
            tool: "traffic_flow",
            toolArguments: { source: "UAT", destination: "PROD" },
          },
          ...(topology.data?.data.topology.hubs[0]
            ? [
                {
                  label: `What depends on ${topology.data.data.topology.hubs[0].name}?`,
                  tool: "hub_dependents",
                  toolArguments: { vnet_id: topology.data.data.topology.hubs[0].vnet_id },
                },
              ]
            : []),
          { label: "Show inspection bypass paths.", tool: "firewall_nsg_gaps", toolArguments: {} },
        ]}
      />
    </div>
  );
}

function TrafficFlowWorkspace() {
  const { scope } = useScope();
  const [source, setSource] = useState("");
  const [destination, setDestination] = useState("");
  const [port, setPort] = useState("443");
  const [protocol, setProtocol] = useState("TCP");
  const [result, setResult] = useState<FlowResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function analyze() {
    if (!source.trim() || !destination.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    networkApi
      .trafficFlow({
        source: source.trim(),
        destination: destination.trim(),
        port: port ? Number(port) : undefined,
        protocol,
        scope,
      })
      .then((envelope) => setResult(envelope.data))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Path analysis failed"))
      .finally(() => setLoading(false));
  }

  return (
    <section className="network-workspace">
      <div className="flow-query-panel">
        <div className="flow-query-heading">
          <div>
            <h2>Can this source reach this destination?</h2>
            <p>Resolve Azure resources, IPs, subnets, or environment endpoints through every observed enforcement point.</p>
          </div>
          <span className="flow-example">Example: UAT app → PROD database · TCP 1433</span>
        </div>
        <div className="flow-query-form">
          <label>
            <span>Source</span>
            <input
              className="form-control"
              value={source}
              onChange={(event) => setSource(event.target.value)}
              placeholder="UAT resource, IP, subnet, or VNet"
            />
          </label>
          <span className="flow-arrow" aria-hidden="true">
            →
          </span>
          <label>
            <span>Destination</span>
            <input
              className="form-control"
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
              placeholder="PROD resource, IP, subnet, or VNet"
            />
          </label>
          <label className="flow-port">
            <span>Port</span>
            <input
              className="form-control"
              type="number"
              min="1"
              max="65535"
              value={port}
              onChange={(event) => setPort(event.target.value)}
            />
          </label>
          <label className="flow-protocol">
            <span>Protocol</span>
            <select className="form-control" value={protocol} onChange={(event) => setProtocol(event.target.value)}>
              <option>TCP</option>
              <option>UDP</option>
              <option>Any</option>
            </select>
          </label>
          <button type="button" className="button button-primary" disabled={!source.trim() || !destination.trim() || loading} onClick={analyze}>
            {loading ? "Analyzing…" : "Analyze path"}
          </button>
        </div>
      </div>

      {error && (
        <StatePanel
          title="Path analysis is unavailable"
          message={`${error}. No reachability verdict has been inferred.`}
          tone="error"
        />
      )}
      {!error && loading && (
        <StatePanel
          title="Tracing enforcement path"
          message="Resolving endpoints, peerings, routes, firewalls, NSGs, and deciding rules."
          tone="loading"
        />
      )}
      {!error && !loading && !result && (
        <div className="network-prompt-state">
          <div>
            <span>1</span>
            <strong>Resolve</strong>
            <p>Map source and destination to observed Azure topology.</p>
          </div>
          <div>
            <span>2</span>
            <strong>Trace</strong>
            <p>Follow routes, peerings, firewall, and NSG enforcement.</p>
          </div>
          <div>
            <span>3</span>
            <strong>Explain</strong>
            <p>Name the exact rule that allows, denies, or leaves the path unknown.</p>
          </div>
        </div>
      )}
      {result && <FlowResultView result={result} />}
    </section>
  );
}

function FlowResultView({ result }: { result: FlowResult }) {
  const presentation = useMemo(() => presentVerdict(result.verdict), [result.verdict]);
  const tone = result.verdict === "allowed" ? "success" : result.verdict === "denied" ? "critical" : "warning";
  const bypass = result.missing_enforcement_points.length > 0;

  return (
    <div className="flow-result">
      <div className={`flow-verdict flow-verdict-${result.verdict}`}>
        <div>
          <span>Reachability verdict</span>
          <h2>{presentation.label}</h2>
          <p>{result.path_summary}</p>
        </div>
        <div className="flow-verdict-facts">
          <StatusBadge label={bypass ? "Inspection gap detected" : "Enforcement observed"} tone={bypass ? "critical" : "success"} />
          <StatusBadge
            label={result.unknowns.length ? `${result.unknowns.length} unknowns` : "Path fully resolved"}
            tone={result.unknowns.length ? "warning" : "success"}
          />
        </div>
      </div>

      {presentation.caveat && <div className="callout callout-warning">{presentation.caveat}</div>}

      <div className="endpoint-pair">
        <EndpointCard label="Source" endpoint={result.source} />
        <div className={`endpoint-verdict-line endpoint-${tone}`} aria-hidden="true">
          →
        </div>
        <EndpointCard label="Destination" endpoint={result.destination} />
      </div>

      <section className="card">
        <div className="card-header">
          <div>
            <h2>Deciding enforcement path</h2>
            <p>Controls are shown in evaluation order. The deciding rule is never hidden behind a generic verdict.</p>
          </div>
        </div>
        <div className="card-body control-path">
          {result.hops.map((hop, index) => (
            <div className="control-hop" key={`${hop.stage}-${hop.rule_id}-${index}`}>
              <div className="control-index">{index + 1}</div>
              <div className="control-hop-main">
                <div>
                  <span>{titleize(hop.stage)}</span>
                  <strong>{hop.control || "Observed network control"}</strong>
                </div>
                <StatusBadge label={hop.decision || "evaluated"} tone={statusTone(hop.decision)} />
              </div>
              <div className="control-rule">
                <span>Deciding rule</span>
                <strong>{hop.rule_name || "No explicit rule resolved"}</strong>
                <code>{hop.rule_id || hop.control_id || "Identifier unavailable"}</code>
              </div>
              <div className="control-reason">
                <span>Why</span>
                <p>{hop.reason}</p>
                {hop.priority !== null && <small>Priority {hop.priority}</small>}
              </div>
            </div>
          ))}
          {result.hops.length === 0 && (
            <StatePanel
              title="No enforcement hops resolved"
              message="The verdict is incomplete because no ordered control path could be established."
              tone="error"
            />
          )}
        </div>
      </section>

      {(result.missing_enforcement_points.length > 0 || result.unknowns.length > 0) && (
        <div className="flow-qualification-grid">
          <div className="callout callout-critical">
            <strong>Inspection gaps</strong>
            <span>
              {result.missing_enforcement_points.length
                ? result.missing_enforcement_points.join(", ")
                : "No missing enforcement points reported."}
            </span>
          </div>
          <div className="callout callout-warning">
            <strong>Known unknowns</strong>
            <span>{result.unknowns.length ? result.unknowns.join(", ") : "No unresolved path elements."}</span>
          </div>
        </div>
      )}
    </div>
  );
}

function EndpointCard({ label, endpoint }: { label: string; endpoint: FlowResult["source"] }) {
  return (
    <article className="endpoint-card">
      <span>{label}</span>
      <strong>{endpoint.name || endpoint.raw}</strong>
      <p>{endpoint.ip_address || endpoint.subnet_id || endpoint.vnet_id || "Endpoint unresolved"}</p>
      <div>
        <StatusBadge label={endpoint.environment || "Environment unknown"} tone="info" compact />
        <StatusBadge label={endpoint.resolved ? "Resolved" : "Unresolved"} tone={endpoint.resolved ? "success" : "warning"} compact />
      </div>
    </article>
  );
}

interface FindingListItem {
  id: string;
  severity: string;
  title: string;
  context: string;
  detail: string;
  recommendation: string;
  basis?: string;
}

function FindingList({
  title,
  description,
  items,
  loading,
  error,
  errorTitle,
  errorMessage,
  emptyTitle,
  emptyMessage,
  pagination,
  page,
  pageSize,
  label,
  onPageChange,
  onPageSizeChange,
  onRetry,
}: {
  title: string;
  description: string;
  items: FindingListItem[];
  loading: boolean;
  error: Error | null;
  errorTitle: string;
  errorMessage: string;
  emptyTitle: string;
  emptyMessage: string;
  pagination?: import("@/lib/types").Pagination | null;
  page: number;
  pageSize: number;
  label: string;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  onRetry: () => void;
}) {
  if (loading && items.length === 0) return <StatePanel title={`Loading ${title.toLowerCase()}`} message="Evaluating observed network configuration." tone="loading" />;
  if (error && items.length === 0) {
    return (
      <StatePanel
        title={errorTitle}
        message={errorMessage}
        tone="error"
        action={<RetryButton label={`Retry loading ${label}`} loading={loading} onClick={onRetry} />}
      />
    );
  }
  if (items.length === 0) return <StatePanel title={emptyTitle} message={emptyMessage} />;

  return (
    <section className="network-workspace card" aria-busy={loading}>
      <div className="card-header">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      <div className="finding-list">
        {items.map((item) => (
          <article className="finding-row" key={item.id}>
            <StatusBadge label={item.severity} tone={statusTone(item.severity)} compact />
            <div>
              <h3>{item.title}</h3>
              <span>{item.context}</span>
              <p>{item.detail}</p>
              <div className="recommendation-line">
                <strong>Recommended</strong>
                <span>{item.recommendation}</span>
              </div>
              {item.basis && <small>Evidence basis: {item.basis}</small>}
            </div>
          </article>
        ))}
      </div>
      <TablePagination
        pagination={pagination}
        pageRows={items.length}
        page={page}
        onPageChange={onPageChange}
        pageSize={pageSize}
        onPageSizeChange={onPageSizeChange}
        label={label}
      />
    </section>
  );
}

function RetryButton({ label, loading, onClick }: { label: string; loading: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className="button"
      aria-label={label}
      aria-busy={loading}
      disabled={loading}
      onClick={onClick}
    >
      Retry
    </button>
  );
}

function flowLogProvenanceText(provenance?: import("@/lib/types").FlowLogProvenance): string {
  if (provenance?.state === "analyzed") {
    return `Flow logs: ${provenance.observed_flow_count} observed flows analyzed`;
  }
  if (provenance?.state === "ingested_not_analyzed") {
    return "Flow logs: ingested, not yet analyzed — findings remain configuration-derived";
  }
  return "Flow logs: not ingested — findings are configuration-derived";
}

function ruleListItem(finding: RuleFinding): FindingListItem {
  return {
    id: finding.finding_id,
    severity: finding.severity,
    title: finding.title,
    context: `${finding.control} · ${finding.rule_name}`,
    detail: finding.detail,
    recommendation: finding.recommendation,
    basis: "Observed Azure control configuration",
  };
}

function networkGapEvidence(gap: NetworkGap): Record<string, unknown> {
  return {
    check: gap.category,
    finding: gap.title,
    issue: gap.detail,
    compliant: false,
    severity: gap.severity,
    resource_id: gap.resource_id,
    resource_name: gap.resource_name,
    resource_type: gap.resource_type,
    recommendation: gap.recommendation,
    basis: gap.basis,
    connection_id: gap.connection_id,
    subscription_id: gap.subscription_id,
    environment: gap.environment,
    vnet_id: gap.vnet_id,
    evidence: gap.evidence,
  };
}

function ruleFindingEvidence(finding: RuleFinding): Record<string, unknown> {
  return {
    check: finding.category,
    finding: finding.title,
    issue: finding.detail,
    compliant: false,
    severity: finding.severity,
    rule_id: finding.rule_id,
    rule_name: finding.rule_name,
    control: finding.control,
    control_id: finding.control_id,
    recommendation: finding.recommendation,
    connection_id: finding.connection_id,
    subscription_id: finding.subscription_id,
    environment: finding.environment,
    evidence: finding.evidence,
  };
}

function firewallBypassEvidence(gap: NetworkGap, index: number): CopilotEvidenceRow {
  return {
    evidence_id: `network:firewall-bypass:${gap.gap_id || index}`,
    resource_id: gap.resource_id,
    section: "firewall",
    status: "ok",
    data: {
      ...networkGapEvidence(gap),
      check: "firewall",
      finding: gap.title || "Firewall inspection bypass path",
      issue: gap.detail || "Spoke traffic can bypass the hub firewall inspection path.",
    },
  };
}

const NEW_RULE_SEVERITIES: NetworkSeverity[] = ["low", "medium", "high", "critical"];

interface NewRuleForm {
  rule_id: string;
  name: string;
  description: string;
  category: string;
  severity: NetworkSeverity;
  assertion: string;
}

const EMPTY_NEW_RULE: NewRuleForm = {
  rule_id: "",
  name: "",
  description: "",
  category: "custom",
  severity: "medium",
  assertion: JSON.stringify(
    {
      target: "subnets",
      assert: [{ field: "vnet_id", exists: true }],
    },
    null,
    2,
  ),
};

/** Editable rule-based network design policy. Gap analysis is checked against
 * this policy, so toggling, adding, or deleting a rule here immediately changes
 * what the "Inspection gaps" tab reports on the next load — there is no
 * separate publish step. */
function DesignPolicyWorkspace({
  onPolicyChanged,
  feedback,
  refreshing,
}: {
  onPolicyChanged: (options?: { saved?: boolean; successMessage?: string }) => void;
  feedback: { tone: "success" | "warning"; message: string } | null;
  refreshing: boolean;
}) {
  const { scope } = useScope();
  const policy = useApi(() => networkApi.policy(scope), [scope]);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [added, setAdded] = useState<NetworkPolicyRule[]>([]);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [newRule, setNewRule] = useState<NewRuleForm>(EMPTY_NEW_RULE);
  const [addError, setAddError] = useState("");
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ gaps: NetworkGap[]; summary: NetworkSummary } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [semanticError, setSemanticError] = useState("");
  const [validatedAssertion, setValidatedAssertion] = useState("");
  const [deleteConfirmation, setDeleteConfirmation] = useState<string | null>(null);

  useEffect(() => {
    if (!policy.loading && policy.data) {
      setPending({});
      setRemoved(new Set());
      setAdded([]);
    }
  }, [policy.data, policy.loading]);

  function parsedParameters(): { ok: true; value: unknown } | { ok: false } {
    try {
      return { ok: true, value: JSON.parse(newRule.assertion) };
    } catch (reason: unknown) {
      const detail = reason instanceof Error ? reason.message : "The assertion could not be parsed.";
      setSemanticError(`That is not valid JSON — ${detail}. Nothing has been sent to the server.`);
      setValidatedAssertion("");
      return { ok: false };
    }
  }

  function authoredRule(parameters: unknown): NetworkPolicyRule {
    return {
      rule_id: newRule.rule_id.trim(),
      name: newRule.name.trim(),
      description: newRule.description.trim(),
      category: newRule.category.trim() || "custom",
      severity: newRule.severity,
      enabled: true,
      parameters: parameters as Record<string, unknown>,
    };
  }

  function toggleRule(rule: NetworkPolicyRule) {
    const nextEnabled = !(pending[rule.rule_id] ?? rule.enabled);
    setSavingId(rule.rule_id);
    setSaveError("");
    networkApi
      .updatePolicy({
        rules: [
          {
            rule_id: rule.rule_id,
            name: rule.name,
            description: rule.description,
            category: rule.category,
            severity: rule.severity,
            enabled: nextEnabled,
            parameters: rule.parameters,
          },
        ],
      })
      .then(() => {
        setPending((current) => ({ ...current, [rule.rule_id]: nextEnabled }));
        policy.refetch();
        onPolicyChanged({
          successMessage: `${rule.name} ${nextEnabled ? "enabled" : "disabled"}. Gaps and badges updated.`,
        });
      })
      .catch((reason: unknown) => setSaveError(reason instanceof Error ? reason.message : "Updating the policy failed"))
      .finally(() => setSavingId(null));
  }

  function deleteRule(rule: NetworkPolicyRule) {
    if (deleteConfirmation !== rule.rule_id) {
      setDeleteConfirmation(rule.rule_id);
      window.setTimeout(() => {
        setDeleteConfirmation((current) => current === rule.rule_id ? null : current);
      }, 5_000);
      return;
    }
    setDeleteConfirmation(null);
    setSavingId(rule.rule_id);
    setSaveError("");
    networkApi
      .updatePolicy({ remove_rule_ids: [rule.rule_id] })
      .then(() => {
        setRemoved((current) => new Set(current).add(rule.rule_id));
        setAdded((current) => current.filter((item) => item.rule_id !== rule.rule_id));
        policy.refetch();
        onPolicyChanged({ successMessage: `${rule.name} removed from the policy. Gaps and badges updated.` });
      })
      .catch((reason: unknown) => setSaveError(reason instanceof Error ? reason.message : "Deleting the rule failed"))
      .finally(() => setSavingId(null));
  }

  function submitNewRule() {
    const rule_id = newRule.rule_id.trim();
    const name = newRule.name.trim();
    if (!rule_id || !name) {
      setAddError("Provide a rule id and name. Nothing was saved; your edits are still in the form.");
      return;
    }
    if (semanticError && validatedAssertion === newRule.assertion) return;
    const parsed = parsedParameters();
    if (!parsed.ok) return;
    setAddError("");
    setSemanticError("");
    setSavingId(rule_id);
    const rule = authoredRule(parsed.value);
    networkApi
      .updatePolicy({ rules: [rule] })
      .then(() => {
        setAdded((current) => [...current.filter((item) => item.rule_id !== rule_id), rule]);
        setRemoved((current) => {
          const next = new Set(current);
          next.delete(rule_id);
          return next;
        });
        setNewRule(EMPTY_NEW_RULE);
        setEditingRuleId(null);
        setShowAddForm(false);
        policy.refetch();
        onPolicyChanged({ saved: true });
      })
      .catch((reason: unknown) => {
        const detail = reason instanceof Error ? reason.message : "Adding the rule failed";
        if (reason instanceof ApiError && reason.code === "invalid_request") {
          setSemanticError(`This rule is not valid — ${detail}. Fix the assertion and preview again; nothing was saved.`);
          setValidatedAssertion(newRule.assertion);
          return;
        }
        setAddError(`The rule was not saved — ${detail}. Nothing was persisted; your edits are still in the form.`);
      })
      .finally(() => setSavingId(null));
  }

  function editRule(rule: NetworkPolicyRule) {
    setEditingRuleId(rule.rule_id);
    setNewRule({
      rule_id: rule.rule_id,
      name: rule.name,
      description: rule.description,
      category: rule.category,
      severity: rule.severity,
      assertion: JSON.stringify(rule.parameters, null, 2),
    });
    setPreview(null);
    setAddError("");
    setSemanticError("");
    setShowAddForm(true);
  }

  function previewRule() {
    const rule_id = newRule.rule_id.trim();
    const name = newRule.name.trim();
    if (!rule_id || !name) {
      setAddError("Provide a rule id and name before previewing. No policy change was made.");
      return;
    }
    const parsed = parsedParameters();
    if (!parsed.ok) return;
    setPreviewing(true);
    setAddError("");
    setSemanticError("");
    networkApi
      .previewPolicy(
        {
          rules: [authoredRule(parsed.value)],
        },
        scope
      )
      .then((result) => {
        const previewedRule = result.data.policy.rules.find((rule) => rule.rule_id === rule_id);
        if (previewedRule?.invalid_reason) {
          setSemanticError(`This rule is not valid — ${previewedRule.invalid_reason}. Fix the assertion and preview again; nothing was saved.`);
          setValidatedAssertion(newRule.assertion);
          setPreview(null);
          return;
        }
        setValidatedAssertion(newRule.assertion);
        setPreview({ gaps: result.data.gaps, summary: result.data.summary });
      })
      .catch((reason: unknown) =>
        setSemanticError(
          `Preview could not run — ${reason instanceof Error ? reason.message : "Previewing the rule failed"}. No policy change was made; nothing was saved.`,
        ),
      )
      .finally(() => setPreviewing(false));
  }

  if (policy.loading) {
    return <StatePanel title="Loading design policy" message="Fetching the rule-based network design policy." tone="loading" />;
  }
  if (policy.error) {
    return (
      <StatePanel
        title="Design policy is unavailable"
        message={`${policy.error.message}. Rules cannot be listed or edited, and the gaps below were evaluated against an unknown policy.`}
        tone="error"
        action={<RetryButton label="Retry loading design policy" loading={policy.loading} onClick={policy.refetch} />}
      />
    );
  }

  const serverRules = policy.data?.data.rules ?? [];
  const byId = new Map(serverRules.map((rule) => [rule.rule_id, rule]));
  for (const rule of added) byId.set(rule.rule_id, rule);
  const rules = Array.from(byId.values()).filter((rule) => !removed.has(rule.rule_id));

  return (
    <section className="network-workspace card">
      <div className="card-header">
        <div>
          <h2>Rule-based network design policy</h2>
          <p>
            Rules define what gap analysis checks for. Disabling a rule stops it from producing findings; it does not
            change the observed topology.
          </p>
        </div>
        <button
          type="button"
          className="button"
          onClick={() => {
            setShowAddForm((current) => !current);
            setEditingRuleId(null);
            setPreview(null);
          }}
        >
          {showAddForm ? "Cancel" : "Add rule"}
        </button>
      </div>
      {saveError && <div className="callout callout-critical">{saveError}</div>}
      {feedback && (
        <div className={`callout callout-${feedback.tone}`} role="status">
          {feedback.message}
        </div>
      )}
      {refreshing && <div role="status">Refreshing derived analysis…</div>}
      {policy.data?.warnings && policy.data.warnings.length > 0 && (
        <div className="callout callout-warning">{policy.data.warnings.join(" ")}</div>
      )}
      {showAddForm && (
        <form
          className="policy-add-form"
          onSubmit={(event) => {
            event.preventDefault();
            submitNewRule();
          }}
        >
          {addError && <div className="callout callout-critical">{addError}</div>}
          <div className="policy-add-form-grid">
            <label>
              Analyzer template
              <select
                value=""
                onChange={(event) => {
                  const selected = policy.data?.data.rules.find((rule) => rule.rule_id === event.target.value);
                  setNewRule((current) => ({
                    ...current,
                    rule_id: event.target.value,
                    name: selected?.name ?? current.name,
                    description: selected?.description ?? current.description,
                    assertion: selected ? JSON.stringify(selected.parameters, null, 2) : current.assertion,
                  }));
                }}
              >
                <option value="">Custom declarative rule</option>
                {(policy.data?.data.rules ?? []).map((rule) => (
                  <option key={rule.rule_id} value={rule.rule_id}>
                    {rule.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Rule ID
              <input
                type="text"
                value={newRule.rule_id}
                onChange={(event) => setNewRule((current) => ({ ...current, rule_id: event.target.value }))}
                placeholder="subnets-need-owner"
                required
              />
            </label>
            <label>
              Name
              <input
                type="text"
                value={newRule.name}
                onChange={(event) => setNewRule((current) => ({ ...current, name: event.target.value }))}
                placeholder="Human-readable rule name"
                required
              />
            </label>
            <label>
              Category
              <input
                type="text"
                value={newRule.category}
                onChange={(event) => setNewRule((current) => ({ ...current, category: event.target.value }))}
                placeholder="custom"
              />
            </label>
            <label>
              Severity
              <select
                value={newRule.severity}
                onChange={(event) => setNewRule((current) => ({ ...current, severity: event.target.value as NetworkSeverity }))}
              >
                {NEW_RULE_SEVERITIES.map((severity) => (
                  <option key={severity} value={severity}>
                    {titleize(severity)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="policy-add-form-description">
            Description
            <textarea
              value={newRule.description}
              onChange={(event) => setNewRule((current) => ({ ...current, description: event.target.value }))}
              placeholder="What does this rule check for?"
              rows={2}
            />
          </label>
          {semanticError && (
            <div id="policy-assertion-error" className="callout callout-critical" role="alert">
              {semanticError}
            </div>
          )}
          <label className="policy-add-form-description">
            Rule assertion (JSON)
            <textarea
              className="topology-mono"
              value={newRule.assertion}
              onChange={(event) => {
                setNewRule((current) => ({ ...current, assertion: event.target.value }));
                setSemanticError("");
                setValidatedAssertion("");
              }}
              rows={6}
              spellCheck={false}
              aria-invalid={semanticError ? "true" : undefined}
              aria-describedby={semanticError ? "policy-assertion-error" : "policy-assertion-help"}
            />
          </label>
          <small id="policy-assertion-help">
            Supported targets: {(policy.data?.data.supported_targets ?? []).join(", ") || "not reported"}. Supported
            operators: {(policy.data?.data.supported_operators ?? []).join(", ") || "not reported"}.
          </small>
          <div className="button-row">
            <button type="button" className="button" onClick={previewRule} disabled={previewing || savingId === newRule.rule_id.trim()}>
              {previewing ? "Previewing…" : "Preview rule"}
            </button>
            <button type="submit" className="button button-primary" disabled={savingId === newRule.rule_id.trim()}>
              {savingId === newRule.rule_id.trim() ? "Saving…" : editingRuleId ? "Save changes" : "Save rule"}
            </button>
          </div>
          {preview && (
            <div className="callout callout-info" role="status">
              Preview found <strong>{preview.gaps.length}</strong> gap{preview.gaps.length === 1 ? "" : "s"} under this rule.
              {" "}The saved policy is unchanged.
              {preview.gaps.length > 0 && (
                <ul>
                  {preview.gaps.slice(0, 5).map((gap) => <li key={gap.gap_id}>{gap.title}: {gap.resource_name}</li>)}
                </ul>
              )}
            </div>
          )}
        </form>
      )}
      <div className="finding-list">
        {rules.length === 0 && (
          <StatePanel title="No policy rules declared" message="No design rules are configured for this estate." />
        )}
        {rules.map((rule) => {
          const enabled = pending[rule.rule_id] ?? rule.enabled;
          return (
            <article className="finding-row" key={rule.rule_id}>
              <StatusBadge label={rule.severity} tone={statusTone(rule.severity)} compact />
              <div>
                <h3>{rule.name}</h3>
                <span>{titleize(rule.category)}</span>
                <p>{rule.description}</p>
              </div>
              <div className="recommendation-line">
                <label className={`policy-switch${enabled ? " is-enabled" : ""}${savingId === rule.rule_id ? " is-saving" : ""}`}>
                  <input
                    type="checkbox"
                    role="switch"
                    checked={enabled}
                    disabled={savingId === rule.rule_id}
                    onChange={() => toggleRule(rule)}
                    aria-label={`${enabled ? "Disable" : "Enable"} ${rule.name}`}
                  />
                  <span className="policy-switch-track" aria-hidden="true">
                    <span className="policy-switch-thumb" />
                  </span>
                  <span className="policy-switch-label">
                    {savingId === rule.rule_id ? "Saving…" : enabled ? "Enabled" : "Disabled"}
                  </span>
                </label>
                <span className="policy-switch-hint">
                  {rule.evaluated === false
                    ? "No gap check implements this rule — it is not evaluated"
                    : enabled
                      ? "Rule is checked during gap analysis"
                      : "Rule is excluded from gap analysis"}
                </span>
                <button type="button" className="button button-quiet" onClick={() => editRule(rule)} disabled={savingId === rule.rule_id}>
                  Edit
                </button>
                <button
                  type="button"
                  className="button button-quiet button-danger policy-delete-btn"
                  disabled={savingId === rule.rule_id}
                  onClick={() => deleteRule(rule)}
                  onBlur={() => setDeleteConfirmation((current) => current === rule.rule_id ? null : current)}
                  aria-label={deleteConfirmation === rule.rule_id ? `Confirm delete ${rule.name}` : `Delete ${rule.name}`}
                >
                  {deleteConfirmation === rule.rule_id ? "Confirm delete" : "Delete"}
                </button>
                {deleteConfirmation === rule.rule_id && (
                  <span aria-live="polite">
                    Deleting {rule.name} stops it from producing findings. Press again to confirm.
                  </span>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
