"use client";

import { useMemo, useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
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
import { buildCopilotSnapshot, copilotEvidenceRows, networkApi } from "@/lib/services";
import type { FlowResult, NetworkGap, NetworkPolicyRule, NetworkSeverity, NetworkSummary, RuleFinding } from "@/lib/types";

type NetworkTab = "flow" | "topology" | "gaps" | "rules" | "policy";

/** Network decision workspace for cross-environment reachability, inspection, and rule analysis. */
export default function NetworkPage() {
  const { scope } = useScope();
  const [tab, setTab] = useState<NetworkTab>("flow");
  const [copilotOpen, setCopilotOpen] = useState(false);
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
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about network paths" />}
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
      {tab === "policy" && <DesignPolicyWorkspace />}

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
          evidence: copilotEvidenceRows("network", evidence, [
            ...(gaps.data?.data.gaps ?? []),
            ...(findings.data?.data.findings ?? []),
          ]),
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

/** Analyzer-backed rule options. The ids must match the backend check registry. */
const ANALYZER_RULES = [
  ["internet-via-firewall", "Internet access must traverse the firewall"],
  ["nsg-override-default-outbound", "NSGs must override default outbound"],
  ["private-endpoints-preferred", "Private endpoints should be used when possible"],
  ["nsg-on-every-subnet", "Every subnet should have an NSG"],
  ["approved-peerings-only", "Only approved peerings should exist"],
  ["bidirectional-peering", "Peerings should be bidirectional"],
  ["private-dns-zone-link", "Private DNS zones should be linked"],
  ["no-orphan-firewall-rules", "Firewall rules should not be orphaned"],
  ["documented-dependencies", "Dependencies should be documented"],
  ["hub-firewall-present", "Hub VNets should have a firewall"],
] as const;

const BUILTIN_RULE_IDS: Set<string> = new Set(ANALYZER_RULES.map(([ruleId]) => ruleId));

const NEW_RULE_SEVERITIES: NetworkSeverity[] = ["low", "medium", "high", "critical"];

interface NewRuleForm {
  rule_id: string;
  name: string;
  description: string;
  category: string;
  severity: NetworkSeverity;
}

const EMPTY_NEW_RULE: NewRuleForm = {
  rule_id: ANALYZER_RULES[0][0],
  name: ANALYZER_RULES[0][1],
  description: "",
  category: "custom",
  severity: "medium",
};

/** Editable rule-based network design policy. Gap analysis is checked against
 * this policy, so toggling, adding, or deleting a rule here immediately changes
 * what the "Inspection gaps" tab reports on the next load — there is no
 * separate publish step. */
function DesignPolicyWorkspace() {
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
      })
      .catch((reason: unknown) => setSaveError(reason instanceof Error ? reason.message : "Updating the policy failed"))
      .finally(() => setSavingId(null));
  }

  function deleteRule(rule: NetworkPolicyRule) {
    setSavingId(rule.rule_id);
    setSaveError("");
    networkApi
      .updatePolicy({ remove_rule_ids: [rule.rule_id] })
      .then(() => {
        setRemoved((current) => new Set(current).add(rule.rule_id));
        setAdded((current) => current.filter((item) => item.rule_id !== rule.rule_id));
      })
      .catch((reason: unknown) => setSaveError(reason instanceof Error ? reason.message : "Deleting the rule failed"))
      .finally(() => setSavingId(null));
  }

  function submitNewRule() {
    const rule_id = newRule.rule_id.trim();
    const name = newRule.name.trim();
    if (!BUILTIN_RULE_IDS.has(rule_id) || !name) {
      setAddError("Select a supported analyzer and provide a name.");
      return;
    }
    setAddError("");
    setSavingId(rule_id);
    const rule: NetworkPolicyRule = {
      rule_id,
      name,
      description: newRule.description.trim(),
      category: newRule.category.trim() || "custom",
      severity: newRule.severity,
      enabled: true,
      parameters: {},
    };
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
      })
      .catch((reason: unknown) => setAddError(reason instanceof Error ? reason.message : "Adding the rule failed"))
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
    });
    setPreview(null);
    setAddError("");
    setShowAddForm(true);
  }

  function previewRule() {
    const rule_id = newRule.rule_id.trim();
    const name = newRule.name.trim();
    if (!BUILTIN_RULE_IDS.has(rule_id) || !name) {
      setAddError("Select a supported analyzer and provide a name before previewing.");
      return;
    }
    setPreviewing(true);
    setAddError("");
    networkApi
      .previewPolicy(
        {
          rules: [
            {
              rule_id,
              name,
              description: newRule.description.trim(),
              category: newRule.category.trim() || "custom",
              severity: newRule.severity,
              enabled: true,
              parameters: {},
            },
          ],
        },
        scope
      )
      .then((result) => setPreview({ gaps: result.data.gaps, summary: result.data.summary }))
      .catch((reason: unknown) => setAddError(reason instanceof Error ? reason.message : "Previewing the rule failed"))
      .finally(() => setPreviewing(false));
  }

  if (policy.loading) {
    return <StatePanel title="Loading design policy" message="Fetching the rule-based network design policy." tone="loading" />;
  }
  if (policy.error) {
    return <StatePanel title="Design policy is unavailable" message={policy.error.message} tone="error" />;
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
              Analyzer
              <select
                value={newRule.rule_id}
                onChange={(event) => {
                  const selected = ANALYZER_RULES.find(([ruleId]) => ruleId === event.target.value);
                  setNewRule((current) => ({
                    ...current,
                    rule_id: event.target.value,
                    name: selected?.[1] ?? current.name,
                  }));
                }}
                required
              >
                {ANALYZER_RULES.map(([ruleId, label]) => (
                  <option key={ruleId} value={ruleId}>
                    {label}
                  </option>
                ))}
              </select>
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
              Preview found <strong>{preview.gaps.length}</strong> gap{preview.gaps.length === 1 ? "" : "s"}.
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
          const isBuiltin = BUILTIN_RULE_IDS.has(rule.rule_id);
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
                {!isBuiltin && (
                  <button
                    type="button"
                    className="button button-quiet button-danger policy-delete-btn"
                    disabled={savingId === rule.rule_id}
                    onClick={() => deleteRule(rule)}
                  >
                    Delete
                  </button>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
