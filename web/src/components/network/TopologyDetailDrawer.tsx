"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TablePagination } from "@/components/ui/TablePagination";
import { useApi } from "@/hooks/useApi";
import { titleize } from "@/lib/format";
import { shortName, type TopologyEdgeData, type TopologyNodeData } from "@/lib/network-graph";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { networkApi } from "@/lib/services";
import type {
  Envelope,
  NetworkGap,
  NetworkTopologyResourceDetails,
  RuleFinding,
} from "@/lib/types";

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
  findings?: DrawerFindingsState;
  detailLevel?: "summary" | "full";
  visibleNodeIds?: ReadonlySet<string>;
  scope?: ScopeSelection;
}

export interface DrawerFindingsState {
  gaps: NetworkGap[];
  ruleFindings: RuleFinding[];
  gapTotal: number;
  ruleFindingTotal: number;
  mapped: number;
  total: number;
  truncated: boolean;
  exhausted: boolean;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
}

/**
 * Side drawer describing the element selected on the topology canvas. Hub
 * dependants are fetched lazily so the canvas itself stays cheap to render.
 */
export function TopologyDetailDrawer({
  node,
  edge,
  onClose,
  findings,
  detailLevel = "full",
  visibleNodeIds,
  scope = {},
}: TopologyDetailDrawerProps) {
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const open = Boolean(node || edge);
  const selectionId = node?.id ?? edge?.id ?? "";

  useEffect(() => {
    if (!open) return undefined;
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        onCloseRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, selectionId]);

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
        {node ? (
          <NodeDetail
            node={node}
            findings={findings}
            detailLevel={detailLevel}
            visibleNodeIds={visibleNodeIds}
            scope={scope}
          />
        ) : (
          <EdgeDetail edge={edge!} />
        )}
      </div>
    </aside>
  );
}

function NodeDetail({
  node,
  findings,
  detailLevel,
  visibleNodeIds,
  scope,
}: {
  node: TopologyNodeData;
  findings?: DrawerFindingsState;
  detailLevel: "summary" | "full";
  visibleNodeIds?: ReadonlySet<string>;
  scope: ScopeSelection;
}) {
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
              ? "Its subscription is not onboarded, so topology beyond this point is unknown."
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

      <OpenFindings node={node} findings={findings} />

      <PrivateLinkFacts node={node} visibleNodeIds={visibleNodeIds} />
      <NodeSpecificDetails
        key={`${node.id}:${scopeCacheKey(scope)}`}
        node={node}
        detailLevel={detailLevel}
        scope={scope}
      />
      {node.kind === "hub" && <HubDependents vnetId={node.id} scope={scope} />}
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
function OpenFindings({
  node,
  findings,
}: {
  node: TopologyNodeData;
  findings?: DrawerFindingsState;
}) {
  const gaps = findings?.gaps ?? [];
  const ruleFindings = findings?.ruleFindings ?? [];
  const directRuleFindings = ruleFindings.filter(
    (finding) => finding.control_id.toLowerCase() === node.id.toLowerCase(),
  );
  const affectedRuleFindings = ruleFindings.filter(
    (finding) =>
      finding.control_id.toLowerCase() !== node.id.toLowerCase() &&
      (finding.affected_resource_ids ?? []).some(
        (resourceId) => resourceId.toLowerCase() === node.id.toLowerCase(),
      ),
  );
  const findingCount =
    gaps.length + directRuleFindings.length + affectedRuleFindings.length;
  const resourceName = node.label || "the selected resource";

  if (findings?.error) {
    return (
      <section className="topology-detail-section">
        <h3>Open findings</h3>
        <div className="callout callout-critical" role="alert">
          <span>
            Findings are unavailable — {findings.error.message}. This resource
            is not confirmed clean.
          </span>
          <button
            type="button"
            className="button button-secondary"
            aria-label={`Retry loading findings for ${resourceName}`}
            onClick={findings.onRetry}
          >
            Retry
          </button>
        </div>
      </section>
    );
  }

  if (findingCount === 0 && findings?.loading) {
    return (
      <section className="topology-detail-section" aria-busy="true">
        <h3>Open findings</h3>
        <span className="muted">Checking open findings…</span>
      </section>
    );
  }

  if (findingCount === 0 && (!findings || findings.truncated || !findings.exhausted)) {
    return (
      <section className="topology-detail-section">
        <h3>Open findings</h3>
        <div className="callout callout-warning" role="status">
          Findings for this resource may be incomplete. {findings?.mapped ?? 0}{" "}
          of {findings?.total ?? 0} findings were loaded. This resource is not
          confirmed clean.
        </div>
      </section>
    );
  }

  if (findingCount === 0) {
    return (
      <section className="topology-detail-section">
        <h3>Open findings (0)</h3>
        <span className="muted">
          No open findings for this resource. All {findings!.gapTotal} gaps and{" "}
          {findings!.ruleFindingTotal} rule findings in scope were checked.
        </span>
      </section>
    );
  }

  return (
    <section className="topology-detail-section">
      <h3>Open findings ({findingCount})</h3>
      <div className="topology-finding-list">
        {gaps.length > 0 && (
          <FindingGroup title="Gaps on this resource">
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
          </FindingGroup>
        )}
        {directRuleFindings.length > 0 && (
          <FindingGroup title="Findings on this control">
            {directRuleFindings.map((finding) => (
              <RuleFindingItem key={finding.finding_id} finding={finding} />
            ))}
          </FindingGroup>
        )}
        {affectedRuleFindings.length > 0 && (
          <FindingGroup title="Findings affecting this resource">
            {affectedRuleFindings.map((finding) => (
              <RuleFindingItem key={finding.finding_id} finding={finding} />
            ))}
          </FindingGroup>
        )}
      </div>
    </section>
  );
}

function FindingGroup({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function RuleFindingItem({ finding }: { finding: RuleFinding }) {
  return (
    <article className="topology-finding-item">
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
  );
}

type DrillDownKind = "rules" | "routes" | "rule_collections";

interface DrillDownDefinition {
  kind: DrillDownKind;
  title: string;
  button: string;
  loading: string;
  disclosure: string;
  empty: string;
  label: string;
}

const DRILL_DOWN_BY_ENTITY: Record<string, DrillDownDefinition> = {
  AzureFirewall: {
    kind: "rules",
    title: "Firewall rules",
    button: "Load rules",
    loading: "Loading rules…",
    disclosure: "Rule detail was not loaded at summary detail.",
    empty: "No firewall rules were observed for this resource.",
    label: "rules",
  },
  NetworkSecurityGroup: {
    kind: "rules",
    title: "NSG rules",
    button: "Load rules",
    loading: "Loading rules…",
    disclosure: "Rule detail was not loaded at summary detail.",
    empty: "No NSG rules were observed for this resource.",
    label: "rules",
  },
  RouteTable: {
    kind: "routes",
    title: "Routes",
    button: "Load routes",
    loading: "Loading routes…",
    disclosure: "Route detail was not loaded at summary detail.",
    empty: "No user-defined routes were observed for this resource.",
    label: "routes",
  },
  FirewallPolicy: {
    kind: "rule_collections",
    title: "Rule collections",
    button: "Load rule collections",
    loading: "Loading rule collections…",
    disclosure: "Rule collection detail was not loaded at summary detail.",
    empty: "No rule collections were observed for this resource.",
    label: "rule collections",
  },
  FirewallRuleCollection: {
    kind: "rules",
    title: "Firewall rules",
    button: "Load rules",
    loading: "Loading rules…",
    disclosure: "Rule detail was not loaded at summary detail.",
    empty: "No rules were observed in this collection.",
    label: "rules",
  },
};

const DETAIL_PAGE_SIZE = 50;
const PRIVATE_LINK_ENTITY_TYPES = new Set([
  "PrivateEndpoint",
  "PrivateLinkService",
  "PrivateLinkResource",
  "FabricCapacity",
  "AIFoundryAccount",
]);
const detailCache = new Map<
  string,
  Envelope<NetworkTopologyResourceDetails>
>();
const detailRequests = new Map<
  string,
  Promise<Envelope<NetworkTopologyResourceDetails>>
>();

function scopeCacheKey(scope: ScopeSelection): string {
  const query = scopeToSearchParams(scope);
  query.sort();
  return query.toString();
}

function detailCacheKey(
  nodeId: string,
  scope: ScopeSelection,
  offset: number,
): string {
  return `${nodeId.toLowerCase()}::${scopeCacheKey(scope)}::${offset}`;
}

function requestDetailPage(
  nodeId: string,
  scope: ScopeSelection,
  offset: number,
): Promise<Envelope<NetworkTopologyResourceDetails>> {
  const key = detailCacheKey(nodeId, scope, offset);
  const cached = detailCache.get(key);
  if (cached) return Promise.resolve(cached);
  const pending = detailRequests.get(key);
  if (pending) return pending;

  const request = networkApi
    .topologyResourceDetails(nodeId, scope, offset, DETAIL_PAGE_SIZE)
    .then((response) => {
      detailCache.set(key, response);
      return response;
    });
  detailRequests.set(key, request);
  const clearPending = () => {
    if (detailRequests.get(key) === request) {
      detailRequests.delete(key);
    }
  };
  void request.then(clearPending, clearPending);
  return request;
}

function NodeSpecificDetails({
  node,
  detailLevel,
  scope,
}: {
  node: TopologyNodeData;
  detailLevel: "summary" | "full";
  scope: ScopeSelection;
}) {
  const details = node.details ?? {};
  if (node.entityType && PRIVATE_LINK_ENTITY_TYPES.has(node.entityType)) {
    return null;
  }
  const definition = node.entityType
    ? DRILL_DOWN_BY_ENTITY[node.entityType]
    : undefined;
  const detailKey =
    definition?.kind === "routes"
      ? "routes"
      : definition?.kind === "rule_collections"
        ? "rule_collections"
        : "rules";
  const embeddedItems = asRecords(details[detailKey]);

  if (
    definition &&
    detailLevel === "summary" &&
    !Array.isArray(details[detailKey])
  ) {
    return <DrillDownSection node={node} definition={definition} scope={scope} />;
  }
  if (definition) {
    return (
      <>
        <RuleTable
          title={definition.title}
          items={embeddedItems}
          empty={definition.empty}
        />
        {node.entityType === "FirewallPolicy" && (
          <FactSection
            title="Policy facts"
            details={details}
            include={["base_policy_id", "threat_intel_mode", "rule_count"]}
          />
        )}
      </>
    );
  }
  if (node.entityType === "FirewallRule" || node.entityType === "NetworkSecurityRule" || node.entityType === "Route") {
    return <FactSection title={`${titleize(node.entityType)} details`} details={details} />;
  }
  if (node.entityType === "Subnet") {
    return <FactSection title="Subnet configuration" details={details} include={["address_prefixes", "nsg_id", "route_table_id", "nat_gateway_id", "service_endpoints"]} />;
  }
  if (node.entityType === "LoadBalancer" || node.entityType === "ApplicationGateway") {
    return <FactSection title={`${titleize(node.entityType)} configuration`} details={details} include={["sku", "frontend_ips", "public_ips", "backend_resource_ids", "waf_enabled"]} />;
  }
  return <FactSection title="Resource details" details={details} collapsed />;
}

function DrillDownSection({
  node,
  definition,
  scope,
}: {
  node: TopologyNodeData;
  definition: DrillDownDefinition;
  scope: ScopeSelection;
}) {
  const [page, setPage] = useState(0);
  const offset = page * DETAIL_PAGE_SIZE;
  const cacheKey = detailCacheKey(node.id, scope, offset);
  const [result, setResult] = useState<
    Envelope<NetworkTopologyResourceDetails> | undefined
  >(() => detailCache.get(cacheKey));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const currentRequestKeyRef = useRef(cacheKey);
  currentRequestKeyRef.current = cacheKey;

  const loadPage = useCallback(async (nextPage: number) => {
    const nextOffset = nextPage * DETAIL_PAGE_SIZE;
    const nextKey = detailCacheKey(node.id, scope, nextOffset);
    currentRequestKeyRef.current = nextKey;
    setPage(nextPage);
    const cached = detailCache.get(nextKey);
    if (cached) {
      setResult(cached);
      setError(null);
      setLoading(false);
      return;
    }
    setResult(undefined);
    setLoading(true);
    setError(null);
    try {
      const response = await requestDetailPage(node.id, scope, nextOffset);
      if (currentRequestKeyRef.current === nextKey) {
        setResult(response);
      }
    } catch (reason) {
      if (currentRequestKeyRef.current === nextKey) {
        setError(
          reason instanceof Error ? reason : new Error("Unknown detail error"),
        );
      }
    } finally {
      if (currentRequestKeyRef.current === nextKey) {
        setLoading(false);
      }
    }
  }, [node.id, scope]);

  const load = useCallback(() => loadPage(page), [loadPage, page]);
  const changePage = useCallback(
    (nextPage: number) => void loadPage(nextPage),
    [loadPage],
  );

  const resourceName = node.label || "the selected resource";
  return (
    <section
      className="topology-detail-section"
      aria-busy={loading ? "true" : undefined}
    >
      <h3>{definition.title}</h3>
      {!result && !error && (
        <>
          <span className="muted">{definition.disclosure}</span>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void load()}
            disabled={loading}
            aria-busy={loading ? "true" : undefined}
          >
            {definition.button}
          </button>
          {loading && <span className="muted">{definition.loading}</span>}
        </>
      )}
      {error && (
        <div className="callout callout-critical">
          <span>
            {titleize(definition.label)} could not be loaded — {error.message}.
            Retry, or open the resource in Azure.
          </span>
          <button
            type="button"
            className="button button-secondary"
            aria-label={`Retry loading ${definition.label} for ${resourceName}`}
            onClick={() => void load()}
            disabled={loading}
            aria-busy={loading ? "true" : undefined}
          >
            Retry
          </button>
        </div>
      )}
      {result && (
        <>
          <RuleRows items={result.data.items} empty={definition.empty} />
          <TablePagination
            pagination={result.pagination}
            pageRows={result.data.items.length}
            page={page}
            onPageChange={changePage}
            label={definition.label}
          />
        </>
      )}
    </section>
  );
}

function PrivateLinkFacts({
  node,
  visibleNodeIds,
}: {
  node: TopologyNodeData;
  visibleNodeIds?: ReadonlySet<string>;
}) {
  const details = node.details ?? {};
  if (!node.entityType || !PRIVATE_LINK_ENTITY_TYPES.has(node.entityType)) {
    return null;
  }

  const targetOutOfScope =
    details.target_out_of_scope === true ||
    details.target_resource_out_of_scope === true ||
    details.target_in_scope === false ||
    (typeof details.target_resource_id === "string" &&
      visibleNodeIds !== undefined &&
      !visibleNodeIds.has(details.target_resource_id.toLowerCase()));
  const publicAccess = formatValue(details.public_network_access);
  const publicAccessUnknown = publicAccess === "—";

  return (
    <>
      <section className="topology-detail-section">
        <h3>Private link</h3>
        <div className="topology-signal-row">
          <StatusBadge label="Private link candidate" tone="info" compact />
        </div>
      </section>
      <section className="topology-detail-section">
        <h3>
          {node.entityType === "PrivateEndpoint"
            ? "Private endpoint configuration"
            : node.entityType === "PrivateLinkService"
              ? "Private link service configuration"
              : "Private link configuration"}
        </h3>
        <dl className="topology-detail-list">
          {node.entityType === "PrivateEndpoint" && (
            <>
              <Fact
                label="Target resource"
                value={
                  targetOutOfScope
                    ? "Target resource is outside the collected scope."
                    : formatValue(details.target_resource_id)
                }
                mono={!targetOutOfScope}
              />
              <Fact
                label="Connection state"
                value={formatValue(details.connection_state)}
              />
              <Fact
                label="Subnet"
                value={formatValue(details.subnet_id)}
                mono
              />
            </>
          )}
          {node.entityType === "PrivateLinkService" && (
            <>
              <Fact label="Alias" value={formatValue(details.alias)} />
              <Fact
                label="Load balancer"
                value={formatValue(
                  details.load_balancer_id ?? details.load_balancer_ids,
                )}
                mono
              />
            </>
          )}
          <div className="topology-detail-fact">
            <dt>Public network access</dt>
            <dd>
              <StatusBadge
                label={publicAccessUnknown ? "Unknown" : publicAccess}
                tone={
                  publicAccessUnknown
                    ? "unknown"
                    : publicAccess.toLowerCase() === "enabled"
                      ? "critical"
                      : "success"
                }
                compact
              />
            </dd>
          </div>
        </dl>
      </section>
    </>
  );
}

function HubDependents({
  vnetId,
  scope,
}: {
  vnetId: string;
  scope: ScopeSelection;
}) {
  const scopeKey = scopeCacheKey(scope);
  const dependents = useApi(
    () => networkApi.hubDependents(vnetId, scope),
    [vnetId, scopeKey],
  );

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
      <RuleRows items={items} empty={empty} />
    </section>
  );
}

function RuleRows({
  items,
  empty,
}: {
  items: Record<string, unknown>[];
  empty: string;
}) {
  if (items.length === 0) {
    return <span className="muted">{empty}</span>;
  }
  return (
    <div className="topology-rule-list">
      {items.map((item, index) => (
        <article key={String(item.id ?? item.name ?? index)}>
          <strong>{formatValue(item.name)}</strong>
          <span>
            {[
              item.priority ? `Priority ${formatValue(item.priority)}` : "",
              item.direction ? formatValue(item.direction) : "",
              item.access ?? item.action
                ? formatValue(item.access ?? item.action)
                : "",
              item.protocol ?? item.protocols
                ? formatValue(item.protocol ?? item.protocols)
                : "",
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
          <small>
            {[
              item.source_address ?? item.source_addresses
                ? `Source: ${formatValue(item.source_address ?? item.source_addresses)}`
                : "",
              item.destination_address ??
              item.destination_addresses ??
              item.destination_fqdns
                ? `Destination: ${formatValue(item.destination_address ?? item.destination_addresses ?? item.destination_fqdns)}`
                : "",
              item.destination_port ?? item.destination_ports
                ? `Ports: ${formatValue(item.destination_port ?? item.destination_ports)}`
                : "",
              item.next_hop_type
                ? `Next hop: ${formatValue(item.next_hop_type)} ${formatValue(item.next_hop_ip)}`
                : "",
            ]
              .filter(Boolean)
              .join(" · ")}
          </small>
        </article>
      ))}
    </div>
  );
}
