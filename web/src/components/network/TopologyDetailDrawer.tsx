"use client";

import { useEffect, useRef } from "react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { titleize } from "@/lib/format";
import { shortName, type TopologyEdgeData, type TopologyNodeData } from "@/lib/network-graph";
import { networkApi } from "@/lib/services";
import type { NetworkGap, RuleFinding } from "@/lib/types";

const KIND_LABEL: Record<string, string> = {
  hub: "Connectivity hub VNet",
  spoke: "Spoke VNet",
  isolated: "Isolated VNet",
  service: "Shared service",
  resource: "Network resource",
};

function unresolvedKindLabel(
  resolution: TopologyNodeData["peerResolution"],
): string {
  if (resolution === "not_ingested") return "Peer VNet — not ingested";
  if (resolution === "excluded_by_scope") {
    return "Peer VNet — outside current scope";
  }
  return "Peer VNet — resolution not recorded";
}

function edgeTitle(edge: TopologyEdgeData): string {
  const arrow = edge.kind === "service" || edge.kind === "relationship" ? "→" : "↔";
  return `${shortName(edge.source)} ${arrow} ${shortName(edge.target)}`;
}

interface TopologyDetailDrawerProps {
  node: TopologyNodeData | null;
  edge: TopologyEdgeData | null;
  onClose: () => void;
  /** Open gaps/rule findings for the selected node's resource id, so a red/orange
   * badge on the canvas can be explained rather than just colour-coded. */
  findings?: { gaps: NetworkGap[]; ruleFindings: RuleFinding[] };
}

/**
 * Side drawer describing the element selected on the topology canvas. Hub
 * dependants are fetched lazily so the canvas itself stays cheap to render.
 */
export function TopologyDetailDrawer({ node, edge, onClose, findings }: TopologyDetailDrawerProps) {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const open = Boolean(node || edge);

  useEffect(() => {
    if (!open) return undefined;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <aside className="topology-drawer" role="dialog" aria-modal="false" aria-label="Topology element details">
      <div className="topology-drawer-header">
        <div>
          <span>
            {node
              ? node.kind === "unresolved"
                ? unresolvedKindLabel(node.peerResolution)
                : (KIND_LABEL[node.kind] ?? "Network node")
              : edge!.kind === "service"
                ? "Shared service link"
                : edge!.kind === "relationship"
                  ? titleize(edge!.relationshipType ?? "relationship")
                : "Peering link"}
          </span>
          <h2>{node ? node.label : edgeTitle(edge!)}</h2>
        </div>
        <button type="button" className="topology-drawer-close" onClick={onClose} ref={closeRef} aria-label="Close details">
          ×
        </button>
      </div>
      <div className="topology-drawer-body">
        {node ? <NodeDetail node={node} findings={findings} /> : <EdgeDetail edge={edge!} />}
      </div>
    </aside>
  );
}

function NodeDetail({ node, findings }: { node: TopologyNodeData; findings?: { gaps: NetworkGap[]; ruleFindings: RuleFinding[] } }) {
  const heading = node.entityType ? titleize(node.entityType) : node.serviceKind ? titleize(node.serviceKind) : titleize(node.kind);
  return (
    <>
      {!node.observed && (
        <div
          className={`callout ${
            node.peerResolution === "excluded_by_scope"
              ? "callout-info"
              : "callout-warning"
          }`}
          role="status"
        >
          <strong>
            {node.peerResolution === "not_ingested"
              ? "This peer was never ingested."
              : node.peerResolution === "excluded_by_scope"
                ? "This peer is outside the current scope."
                : "Why this peer is missing is not recorded."}
          </strong>
          <span>
            {node.peerResolution === "not_ingested"
              ? "Its subscription is not connected, so topology beyond this point is unknown."
              : node.peerResolution === "excluded_by_scope"
                ? "It was ingested and is present in the estate, but the active scope selection excludes it. Widen the scope to see it."
                : "This response did not say whether the VNet was never ingested or excluded by the current scope."}
          </span>
        </div>
      )}

      <dl className="topology-detail-list">
        <Fact label="Kind" value={heading} />
        <Fact label="Subscription" value={node.subscriptionId || "Unknown"} mono />
        {node.resourceGroup && <Fact label="Resource group" value={node.resourceGroup} mono />}
        {node.location && <Fact label="Location" value={node.location} />}
        {node.environment && <Fact label="Environment" value={node.environment} />}
        {node.businessService && <Fact label="Business service" value={node.businessService} />}
        {node.owner && <Fact label="Owner" value={node.owner} />}
        {node.connectionId && <Fact label="Connection" value={node.connectionId} mono />}
        {node.kind !== "service" && <Fact label="Peer count" value={String(node.peerCount)} />}
        {node.kind === "service" && node.consumerCount !== undefined && (
          <Fact label="Consumers" value={String(node.consumerCount)} />
        )}
        {node.score > 0 && <Fact label="Role score" value={node.score.toFixed(2)} />}
        <Fact label="Resource id" value={node.id} mono />
      </dl>

      {node.signals.length > 0 && (
        <section className="topology-detail-section">
          <h3>Classification signals</h3>
          <div className="topology-signal-row">
            {node.signals.map((signal) => (
              <StatusBadge key={signal} label={titleize(signal)} tone="info" compact />
            ))}
          </div>
        </section>
      )}
      {node.kind === "unresolved" && (
        <section className="topology-detail-section">
          <h3>Peer resolution</h3>
          <StatusBadge
            label={
              node.peerResolution === "not_ingested"
                ? "Not ingested"
                : node.peerResolution === "excluded_by_scope"
                  ? "Outside current scope"
                  : "Peer resolution unknown"
            }
            tone={
              node.peerResolution === "excluded_by_scope"
                ? "info"
                : node.peerResolution === "unknown" || !node.peerResolution
                  ? "unknown"
                  : "warning"
            }
            compact
          />
        </section>
      )}

      <OpenFindings findings={findings} />

      <NodeSpecificDetails node={node} />
      {node.kind === "hub" && <HubDependents vnetId={node.id} />}
    </>
  );
}

const SEVERITY_TONE: Record<string, "critical" | "warning" | "info"> = {
  critical: "critical",
  high: "warning",
  medium: "warning",
  low: "info",
};

/** Renders the actual open gap/rule-finding records behind a node's severity
 * badge, so clicking a red-dotted node explains why it is flagged. */
function OpenFindings({ findings }: { findings?: { gaps: NetworkGap[]; ruleFindings: RuleFinding[] } }) {
  const gaps = findings?.gaps ?? [];
  const ruleFindings = findings?.ruleFindings ?? [];
  if (gaps.length === 0 && ruleFindings.length === 0) return null;

  return (
    <section className="topology-detail-section">
      <h3>Open findings ({gaps.length + ruleFindings.length})</h3>
      <div className="topology-finding-list">
        {gaps.map((gap) => (
          <article key={gap.gap_id} className="topology-finding-item">
            <div className="topology-finding-header">
              <StatusBadge label={titleize(gap.severity)} tone={SEVERITY_TONE[gap.severity] ?? "info"} compact />
              <strong>{gap.title}</strong>
            </div>
            <span>{gap.detail}</span>
            {gap.recommendation && <small>Recommendation: {gap.recommendation}</small>}
            {gap.basis && <small className="muted">Basis: {gap.basis}</small>}
          </article>
        ))}
        {ruleFindings.map((finding) => (
          <article key={finding.finding_id} className="topology-finding-item">
            <div className="topology-finding-header">
              <StatusBadge label={titleize(finding.severity)} tone={SEVERITY_TONE[finding.severity] ?? "info"} compact />
              <strong>{finding.title}</strong>
            </div>
            <span>
              {finding.control} · {finding.rule_name}
            </span>
            <small>{finding.detail}</small>
            {finding.recommendation && <small>Recommendation: {finding.recommendation}</small>}
          </article>
        ))}
      </div>
    </section>
  );
}

function NodeSpecificDetails({ node }: { node: TopologyNodeData }) {
  const details = node.details ?? {};
  if (node.entityType === "AzureFirewall") {
    return <RuleTable title="Firewall rules" items={asRecords(details.rules)} empty="No firewall rules were observed for this firewall." />;
  }
  if (node.entityType === "NetworkSecurityGroup") {
    return <RuleTable title="NSG rules" items={asRecords(details.rules)} empty="No NSG rules were observed." />;
  }
  if (node.entityType === "RouteTable") {
    return <RuleTable title="Routes" items={asRecords(details.routes)} empty="No user-defined routes were observed." />;
  }
  if (node.entityType === "FirewallPolicy") {
    return (
      <>
        <RuleTable title="Rule collections" items={asRecords(details.rule_collections)} empty="No rule collections were observed." />
        <FactSection title="Policy facts" details={details} include={["base_policy_id", "threat_intel_mode", "rule_count"]} />
      </>
    );
  }
  if (node.entityType === "FirewallRuleCollection") {
    return <RuleTable title="Firewall rules" items={asRecords(details.rules)} empty="No rules were observed in this collection." />;
  }
  if (node.entityType === "FirewallRule" || node.entityType === "NetworkSecurityRule" || node.entityType === "Route") {
    return <FactSection title={`${titleize(node.entityType)} details`} details={details} />;
  }
  if (node.entityType === "Subnet") {
    return <FactSection title="Subnet configuration" details={details} include={["address_prefixes", "nsg_id", "route_table_id", "nat_gateway_id", "service_endpoints"]} />;
  }
  if (node.entityType === "PrivateEndpoint") {
    return <FactSection title="Private endpoint configuration" details={details} include={["target_resource_id", "group_ids", "private_ips", "private_dns_zone_ids", "connection_state"]} />;
  }
  if (node.entityType === "LoadBalancer" || node.entityType === "ApplicationGateway") {
    return <FactSection title={`${titleize(node.entityType)} configuration`} details={details} include={["sku", "frontend_ips", "public_ips", "backend_resource_ids", "waf_enabled"]} />;
  }
  return <FactSection title="Resource details" details={details} collapsed />;
}

function HubDependents({ vnetId }: { vnetId: string }) {
  const dependents = useApi(() => networkApi.hubDependents(vnetId), [vnetId]);

  return (
    <section className="topology-detail-section">
      <h3>Dependent networks</h3>
      {dependents.loading && <span className="muted">Loading dependencies…</span>}
      {dependents.error && <span className="muted">Dependencies are unavailable: {dependents.error.message}</span>}
      {!dependents.loading && !dependents.error && (
        <div className="topology-dependent-list">
          {(dependents.data?.data.dependent_vnets ?? []).map((item) => (
            <div key={item.vnet_id}>
              <strong>{item.name || shortName(item.vnet_id)}</strong>
              <span>
                {item.business_service || "Service not mapped"} · {item.environment || "Environment unknown"}
              </span>
              <StatusBadge
                label={item.observed ? "Observed" : "Resolution unknown"}
                tone={item.observed ? "success" : "unknown"}
                compact
              />
            </div>
          ))}
          {(dependents.data?.data.dependent_vnets ?? []).length === 0 && (
            <span className="muted">No dependent networks were observed.</span>
          )}
        </div>
      )}
    </section>
  );
}

function EdgeDetail({ edge }: { edge: TopologyEdgeData }) {
  if (edge.kind === "relationship") {
    return (
      <>
        <dl className="topology-detail-list">
          <Fact label="Relationship" value={titleize(edge.relationshipType ?? edge.label)} />
          <Fact label="Source" value={edge.source} mono />
          <Fact label="Target" value={edge.target} mono />
          <Fact label="Cross-subscription" value={edge.crossSubscription ? "Yes" : "No"} />
        </dl>
        <FactSection title="Relationship details" details={edge.details ?? {}} collapsed />
      </>
    );
  }

  if (edge.kind === "service") {
    return (
      <dl className="topology-detail-list">
        <Fact label="Relationship" value="Shared service consumed by this VNet" />
        <Fact label="Service" value={shortName(edge.source)} mono />
        <Fact label="Consumer VNet" value={shortName(edge.target)} mono />
        <Fact label="Cross-subscription" value={edge.crossSubscription ? "Yes" : "No"} />
      </dl>
    );
  }

  return (
    <>
      <div className="topology-drawer-verdict">
        <StatusBadge
          label={
            edge.kind === "healthy"
              ? "Peering connected"
              : edge.kind === "unresolved"
                ? edge.peerResolution === "not_ingested"
                  ? "Remote VNet not ingested"
                  : edge.peerResolution === "excluded_by_scope"
                    ? "Remote VNet outside current scope"
                    : "Remote VNet resolution not recorded"
                : "Peering not connected"
          }
          tone={edge.kind === "healthy" ? "success" : edge.kind === "unresolved" ? "warning" : "critical"}
        />
        {!edge.bidirectional && <StatusBadge label="One-way — observed from a single side" tone="warning" />}
      </div>
      <dl className="topology-detail-list">
        <Fact label="Local state" value={edge.localState || "Unknown"} />
        <Fact label="Remote state" value={edge.remoteState || "Unknown"} />
        <Fact label="Cross-subscription" value={edge.crossSubscription ? "Yes" : "No"} />
        <Fact label="Allow forwarded traffic" value={edge.allowForwardedTraffic ? "Yes" : "No"} />
        <Fact label="Allow gateway transit" value={edge.allowGatewayTransit ? "Yes" : "No"} />
        <Fact label="Use remote gateways" value={edge.useRemoteGateways ? "Yes" : "No"} />
        <Fact label="Local VNet" value={edge.source} mono />
        <Fact label="Remote VNet" value={edge.target} mono />
      </dl>
    </>
  );
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="topology-detail-fact">
      <dt>{label}</dt>
      <dd className={mono ? "topology-mono" : undefined}>{value}</dd>
    </div>
  );
}

function asRecords(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item));
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.map(formatValue).join(", ") : "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function FactSection({
  title,
  details,
  include,
  collapsed = false,
}: {
  title: string;
  details: Record<string, unknown>;
  include?: string[];
  collapsed?: boolean;
}) {
  const entries = (include ?? Object.keys(details)).filter((key) => details[key] !== undefined && details[key] !== "" && key !== "tags");
  if (!entries.length) return null;
  const body = (
    <dl className="topology-detail-list">
      {entries.map((key) => (
        <Fact key={key} label={titleize(key)} value={formatValue(details[key])} mono={String(details[key]).includes("/subscriptions/")} />
      ))}
    </dl>
  );
  if (collapsed) {
    return (
      <details className="topology-detail-section">
        <summary>{title}</summary>
        {body}
      </details>
    );
  }
  return (
    <section className="topology-detail-section">
      <h3>{title}</h3>
      {body}
    </section>
  );
}

function RuleTable({ title, items, empty }: { title: string; items: Record<string, unknown>[]; empty: string }) {
  return (
    <section className="topology-detail-section">
      <h3>{title}</h3>
      {items.length === 0 ? (
        <span className="muted">{empty}</span>
      ) : (
        <div className="topology-rule-list">
          {items.map((item, index) => (
            <article key={String(item.id ?? item.name ?? index)}>
              <strong>{formatValue(item.name)}</strong>
              <span>
                {[
                  item.priority ? `Priority ${formatValue(item.priority)}` : "",
                  item.direction ? formatValue(item.direction) : "",
                  item.access ?? item.action ? formatValue(item.access ?? item.action) : "",
                  item.protocol ?? item.protocols ? formatValue(item.protocol ?? item.protocols) : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              <small>
                {[
                  item.source_address ?? item.source_addresses ? `Source: ${formatValue(item.source_address ?? item.source_addresses)}` : "",
                  item.destination_address ?? item.destination_addresses ?? item.destination_fqdns
                    ? `Destination: ${formatValue(item.destination_address ?? item.destination_addresses ?? item.destination_fqdns)}`
                    : "",
                  item.destination_port ?? item.destination_ports ? `Ports: ${formatValue(item.destination_port ?? item.destination_ports)}` : "",
                  item.next_hop_type ? `Next hop: ${formatValue(item.next_hop_type)} ${formatValue(item.next_hop_ip)}` : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
