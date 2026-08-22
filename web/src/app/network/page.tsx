"use client";

import { useMemo, useState } from "react";
import { CopilotLauncher } from "@/components/ui/CopilotLauncher";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { TopologyWorkspace } from "@/components/network/TopologyWorkspace";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { titleize } from "@/lib/format";
import { presentVerdict } from "@/lib/flow-verdict";
import { useScope } from "@/lib/scope-context";
import { networkApi } from "@/lib/services";
import type { FlowResult, RuleFinding } from "@/lib/types";

type NetworkTab = "flow" | "topology" | "gaps" | "rules";

/** Network decision workspace for cross-environment reachability, inspection, and rule analysis. */
export default function NetworkPage() {
  const { scope } = useScope();
  const [tab, setTab] = useState<NetworkTab>("flow");
  const topology = useApi(() => networkApi.topology(scope), [scope]);
  const gaps = useApi(() => networkApi.gaps(scope), [scope]);
  const findings = useApi(() => networkApi.ruleFindings(scope), [scope]);
  const bypass = useApi(() => networkApi.firewallBypass(scope), [scope]);

  const summary = topology.data?.data.summary;
  const evidence = [
    ...(topology.data?.evidence ?? []),
    ...(gaps.data?.evidence ?? []),
    ...(findings.data?.evidence ?? []),
  ];
  const warnings = [
    ...(topology.data?.warnings ?? []),
    ...(gaps.data?.warnings ?? []),
    ...(findings.data?.warnings ?? []),
  ];

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Network intelligence"
        title="Topology & traffic paths"
        description="Ask whether one environment can reach another, identify every deciding control, and expose paths that bypass inspection."
        metadata={
          <>
            <span>{summary?.connection_count ?? 0} subscription connections</span>
            <span>Configuration-derived analysis</span>
            <span>No flow logs assumed</span>
          </>
        }
      />

      <EvidenceBar
        evidence={evidence}
        knowledgeVersion={topology.data?.knowledge_version}
        warnings={warnings}
      />

      <CopilotLauncher
        starterQuestions={["can UAT reach PROD", "which services depend on the hub firewall", "show inspection bypass paths"]}
      />

      <div className="metric-grid network-metrics">
        <MetricCard
          label="Observed network"
          value={`${summary?.hub_count ?? 0} / ${summary?.spoke_count ?? 0}`}
          detail="Hub / spoke VNets across the current scope"
        />
        <MetricCard
          label="Inspection bypass"
          value={bypass.data?.data.count ?? "—"}
          detail="Spokes with a path that may avoid firewall inspection"
          tone={(bypass.data?.data.count ?? 0) > 0 ? "critical" : "success"}
        />
        <MetricCard
          label="Unhealthy peerings"
          value={summary?.unhealthy_peering_count ?? "—"}
          detail={`${summary?.cross_subscription_peering_count ?? 0} cross-subscription peerings`}
          tone={(summary?.unhealthy_peering_count ?? 0) > 0 ? "warning" : "success"}
        />
        <MetricCard
          label="Broad or risky rules"
          value={findings.data?.data.findings.length ?? "—"}
          detail={`${gaps.data?.data.gaps.length ?? 0} structural or design gaps`}
          tone={(findings.data?.data.findings.length ?? 0) > 0 ? "warning" : "success"}
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

      <div className="workspace-tabs" role="tablist" aria-label="Network analysis views">
        {(
          [
            ["flow", "Path analysis"],
            ["topology", "Topology"],
            ["gaps", "Inspection gaps"],
            ["rules", "Rule findings"],
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
        <TopologyWorkspace
          topology={topology.data?.data.topology ?? null}
          loading={topology.loading}
          error={topology.error}
          gaps={gaps.data?.data.gaps ?? []}
          ruleFindings={findings.data?.data.findings ?? []}
        />
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
        />
      )}
      {tab === "rules" && (
        <FindingList
          title="Rule tightening opportunities"
          description="Configuration-derived findings. “Unused” means no structural path was observed, not that no traffic occurred."
          items={(findings.data?.data.findings ?? []).map((finding) => ruleListItem(finding))}
          loading={findings.loading}
          error={findings.error}
        />
      )}
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
}: {
  title: string;
  description: string;
  items: FindingListItem[];
  loading: boolean;
  error: Error | null;
}) {
  if (loading) return <StatePanel title={`Loading ${title.toLowerCase()}`} message="Evaluating observed network configuration." tone="loading" />;
  if (error) return <StatePanel title={`${title} are unavailable`} message={error.message} tone="error" />;
  if (items.length === 0) return <StatePanel title={`No ${title.toLowerCase()} detected`} message="No matching findings exist in the current scope." />;

  return (
    <section className="network-workspace card">
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
    </section>
  );
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
