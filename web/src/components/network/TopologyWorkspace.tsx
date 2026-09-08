"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  clearTopologyDetailCache,
  TopologyDetailDrawer,
} from "@/components/network/TopologyDetailDrawer";
import type {
  TopologyExportContext,
  TopologyGraphHandle,
  TopologySelection,
} from "@/components/network/TopologyGraph";
import { formatDateTime, relativeTime } from "@/lib/format";
import { buildTopologyGraph } from "@/lib/network-graph";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import type {
  CollectionCoverage,
  EvidenceItem,
  NetworkGap,
  NetworkSummary,
  NetworkTopology,
  Pagination,
  RuleFinding,
} from "@/lib/types";

const SEVERITY_RANK: Record<string, number> = { critical: 3, high: 2, medium: 1, low: 0 };

export type TopologyDetailLevel = "summary" | "full";

// Plan 12-02 measured the largest interactive fCoSE canvas at 1,500 nodes
// (224.298 ms against a 250 ms ceiling). Never raise this above the contract cap.
export const FULL_DETAIL_GUARD_NODES = 1_500;
export const FULL_DETAIL_GUARD_BUILD_MS = 3_000;
export const BADGE_FETCH_PAGE_SIZE = 500;
export const BADGE_FETCH_MAX_PAGES = 4;

interface FindingBadge {
  severity: string;
  count: number;
  title: string;
}

interface BadgePage<T> {
  data: T;
  pagination?: Pagination | null;
}

type LoadGapPage = (
  offset: number,
  limit: number,
) => Promise<BadgePage<{ gaps: NetworkGap[] }>>;
type LoadRuleFindingPage = (
  offset: number,
  limit: number,
) => Promise<BadgePage<{ findings: RuleFinding[] }>>;

interface BadgeCoverage {
  mapped: number;
  total: number;
  truncated: boolean;
}

const EMPTY_GAPS: NetworkGap[] = [];
const EMPTY_RULE_FINDINGS: RuleFinding[] = [];

function pluralFindings(count: number): string {
  return `${count} open finding${count === 1 ? "" : "s"}`;
}

/** Highest-severity finding per resource id, used to badge topology nodes with
 * open gaps/rule findings without a separate lookup step on the canvas. */
function buildFindingSeverityMap(
  gaps: NetworkGap[],
  ruleFindings: RuleFinding[]
): Map<string, FindingBadge> {
  const aggregates = new Map<
    string,
    {
      severity: string;
      findingIds: Set<string>;
      controlIds: Set<string>;
      affectedIds: Set<string>;
    }
  >();
  const bump = (
    resourceId: string,
    severity: string,
    findingId: string,
    role: "direct" | "control" | "affected",
  ) => {
    if (!resourceId) return;
    const foldedId = resourceId.toLowerCase();
    const existing = aggregates.get(foldedId);
    if (!existing) {
      aggregates.set(foldedId, {
        severity,
        findingIds: new Set([findingId]),
        controlIds: role === "control" ? new Set([findingId]) : new Set(),
        affectedIds: role === "affected" ? new Set([findingId]) : new Set(),
      });
    } else {
      existing.findingIds.add(findingId);
      if (role === "control") existing.controlIds.add(findingId);
      if (role === "affected") existing.affectedIds.add(findingId);
      if (
        (SEVERITY_RANK[severity] ?? 0) >
        (SEVERITY_RANK[existing.severity] ?? 0)
      ) {
        existing.severity = severity;
      }
    }
  };
  for (const gap of gaps) {
    bump(gap.resource_id, gap.severity, `gap:${gap.gap_id}`, "direct");
  }
  for (const finding of ruleFindings) {
    const findingId = `rule:${finding.finding_id}`;
    bump(finding.control_id, finding.severity, findingId, "control");
    const affectedIds = new Set(
      (finding.affected_resource_ids ?? [])
        .filter(Boolean)
        .map((resourceId) => resourceId.toLowerCase()),
    );
    for (const affectedId of Array.from(affectedIds)) {
      bump(affectedId, finding.severity, findingId, "affected");
    }
  }

  const map = new Map<string, FindingBadge>();
  aggregates.forEach((value, resourceId) => {
    const count = value.findingIds.size;
    let title = `${pluralFindings(count)} (${value.severity})`;
    if (value.controlIds.size > 0 && value.affectedIds.size > 0) {
      title = `${pluralFindings(value.controlIds.size)} on this control and ${
        value.affectedIds.size
      } affecting this resource (${value.severity})`;
    } else if (value.affectedIds.size > 0) {
      title = `${pluralFindings(count)} affecting this resource (${value.severity})`;
    }
    map.set(resourceId, { severity: value.severity, count, title });
  });
  return map;
}

/** Full gap/rule-finding records grouped by resource id, so the detail drawer
 * can show what actually caused a node's severity badge, not just its color. */
function buildFindingsByResource(
  gaps: NetworkGap[],
  ruleFindings: RuleFinding[]
): Map<string, { gaps: NetworkGap[]; ruleFindings: RuleFinding[] }> {
  const map = new Map<string, { gaps: NetworkGap[]; ruleFindings: RuleFinding[] }>();
  const entry = (resourceId: string) => {
    const foldedId = resourceId.toLowerCase();
    let value = map.get(foldedId);
    if (!value) {
      value = { gaps: [], ruleFindings: [] };
      map.set(foldedId, value);
    }
    return value;
  };
  for (const gap of gaps) {
    if (!gap.resource_id) continue;
    entry(gap.resource_id).gaps.push(gap);
  }
  for (const finding of ruleFindings) {
    if (!finding.control_id) continue;
    const resourceIds = new Set([
      finding.control_id.toLowerCase(),
      ...(finding.affected_resource_ids ?? []).map((id) => id.toLowerCase()),
    ]);
    for (const resourceId of Array.from(resourceIds)) {
      entry(resourceId).ruleFindings.push(finding);
    }
  }
  return map;
}

async function fetchBadgeCollection<T, TData>(
  loadPage: (offset: number, limit: number) => Promise<BadgePage<TData>>,
  selectItems: (data: TData) => T[],
): Promise<{ items: T[]; total: number; truncated: boolean }> {
  const items: T[] = [];
  let total = 0;
  let offset = 0;
  for (let pageNumber = 0; pageNumber < BADGE_FETCH_MAX_PAGES; pageNumber += 1) {
    const page = await loadPage(offset, BADGE_FETCH_PAGE_SIZE);
    const pageItems = selectItems(page.data);
    items.push(...pageItems);
    const coverage = (page.data as { coverage?: CollectionCoverage }).coverage;
    total =
      coverage?.total ??
      page.pagination?.total ??
      Math.max(total, items.length);
    if (items.length >= total || pageItems.length === 0) break;
    offset =
      page.pagination?.next_offset ??
      offset + pageItems.length;
  }
  return { items, total, truncated: items.length < total };
}

// Cytoscape needs a DOM, and pulls in a sizeable layout engine, so it is loaded
// client-side only and kept out of the initial route bundle.
const TopologyGraph = dynamic(() => import("@/components/network/TopologyGraph"), {
  ssr: false,
  loading: () => <StatePanel title="Loading topology canvas" message="Preparing the interactive graph." tone="loading" />,
});

const EMPTY_SELECTION: TopologySelection = { node: null, edge: null };

interface TopologyWorkspaceProps {
  topology: NetworkTopology | null;
  summary?: NetworkSummary | null;
  detailLevel?: TopologyDetailLevel;
  renderedDetailLevel?: TopologyDetailLevel;
  onDetailLevelChange?: (detail: TopologyDetailLevel) => void;
  onCancelDetailLoad?: () => void;
  loading: boolean;
  error: Error | null;
  gaps?: NetworkGap[];
  ruleFindings?: RuleFinding[];
  loadGapsPage?: LoadGapPage;
  loadRuleFindingsPage?: LoadRuleFindingPage;
  findingsLoading?: boolean;
  findingsError?: Error | null;
  onRetryFindings?: () => void;
  scope?: ScopeSelection | null;
  evidence?: EvidenceItem[] | null;
  warnings?: string[] | null;
  knowledgeVersion?: string | null;
  graphFreshness?: string;
}

/** Interactive topology workspace: Cytoscape canvas, filters, and a detail drawer. */
export function TopologyWorkspace({
  topology,
  summary = null,
  detailLevel = "summary",
  renderedDetailLevel = detailLevel,
  onDetailLevelChange,
  onCancelDetailLoad,
  loading,
  error,
  gaps = EMPTY_GAPS,
  ruleFindings = EMPTY_RULE_FINDINGS,
  loadGapsPage,
  loadRuleFindingsPage,
  findingsLoading = false,
  findingsError = null,
  onRetryFindings = () => undefined,
  scope = null,
  evidence = null,
  warnings = null,
  knowledgeVersion = null,
  graphFreshness,
}: TopologyWorkspaceProps) {
  const [search, setSearch] = useState("");
  const [filterMode, setFilterMode] = useState(false);
  const [showServices, setShowServices] = useState(true);
  const [showUnattachedPrivateLinkCandidates, setShowUnattachedPrivateLinkCandidates] =
    useState(false);
  const [showFindings, setShowFindings] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [fullDetailPending, setFullDetailPending] = useState(false);
  const [detailLoadElapsedSeconds, setDetailLoadElapsedSeconds] = useState(0);
  const [selection, setSelection] = useState<TopologySelection>(EMPTY_SELECTION);
  const [selectionAnnouncement, setSelectionAnnouncement] = useState("");
  const selectionContextRef = useRef("");
  const topologyRef = useRef(topology);
  const graphHandleRef = useRef<TopologyGraphHandle | null>(null);
  const [badgeGaps, setBadgeGaps] = useState(gaps);
  const [badgeRuleFindings, setBadgeRuleFindings] = useState(ruleFindings);
  const [badgeLoading, setBadgeLoading] = useState(
    Boolean(loadGapsPage && loadRuleFindingsPage),
  );
  const [badgeCoverage, setBadgeCoverage] = useState<BadgeCoverage>({
    mapped: gaps.length + ruleFindings.length,
    total: gaps.length + ruleFindings.length,
    truncated: false,
  });

  useEffect(() => {
    if (!loadGapsPage || !loadRuleFindingsPage) {
      setBadgeLoading(false);
      setBadgeGaps(gaps);
      setBadgeRuleFindings(ruleFindings);
      setBadgeCoverage({
        mapped: gaps.length + ruleFindings.length,
        total: gaps.length + ruleFindings.length,
        truncated: false,
      });
      return undefined;
    }
    let cancelled = false;
    setBadgeLoading(true);
    Promise.all([
      fetchBadgeCollection(loadGapsPage, (data) => data.gaps),
      fetchBadgeCollection(loadRuleFindingsPage, (data) => data.findings),
    ])
      .then(([gapResult, findingResult]) => {
        if (cancelled) return;
        setBadgeLoading(false);
        setBadgeGaps(gapResult.items as NetworkGap[]);
        setBadgeRuleFindings(findingResult.items as RuleFinding[]);
        setBadgeCoverage({
          mapped: gapResult.items.length + findingResult.items.length,
          total: gapResult.total + findingResult.total,
          truncated: gapResult.truncated || findingResult.truncated,
        });
      })
      .catch(() => {
        if (cancelled) return;
        setBadgeLoading(false);
        // The page-level loaders own unavailable-state disclosure. Retain their
        // last successful rows here and compare them with summary totals rather
        // than presenting a failed badge fetch as complete.
        const mapped = gaps.length + ruleFindings.length;
        const total =
          (summary?.gap_count ?? gaps.length) +
          (summary?.rule_finding_count ?? ruleFindings.length);
        setBadgeGaps(gaps);
        setBadgeRuleFindings(ruleFindings);
        setBadgeCoverage({
          mapped,
          total,
          truncated: mapped < total,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [gaps, loadGapsPage, loadRuleFindingsPage, ruleFindings, summary]);

  const findingSeverityByResource = useMemo(
    () => buildFindingSeverityMap(badgeGaps, badgeRuleFindings),
    [badgeGaps, badgeRuleFindings]
  );
  const findingsByResource = useMemo(
    () => buildFindingsByResource(badgeGaps, badgeRuleFindings),
    [badgeGaps, badgeRuleFindings]
  );
  const renderedGraph = useMemo(
    () =>
      topology
        ? buildTopologyGraph(topology, {
            showUnattachedPrivateLinkCandidates,
          })
        : null,
    [showUnattachedPrivateLinkCandidates, topology],
  );
  const visibleNodeIds = useMemo(
    () =>
      new Set(
        (renderedGraph?.nodes ?? []).map((node) => node.id.toLowerCase()),
      ),
    [renderedGraph],
  );
  const visibleEdgeIds = useMemo(
    () => new Set((renderedGraph?.edges ?? []).map((edge) => edge.id)),
    [renderedGraph],
  );
  const scopeKey = useMemo(() => {
    const query = scopeToSearchParams(scope ?? {});
    query.sort();
    return query.toString();
  }, [scope]);
  useEffect(() => {
    setFullDetailPending(false);
  }, [scopeKey, summary]);
  const normalizedSearch = search.trim().toLowerCase();
  const matchingNodeIds = useMemo(
    () =>
      new Set(
        (renderedGraph?.nodes ?? [])
          .filter(
            (node) =>
              !normalizedSearch ||
              node.label.toLowerCase().includes(normalizedSearch),
          )
          .map((node) => node.id),
      ),
    [normalizedSearch, renderedGraph],
  );
  const filterHiddenCount =
    filterMode && normalizedSearch
      ? (renderedGraph?.nodes.length ?? 0) - matchingNodeIds.size
      : 0;

  const handleGraphReady = useCallback((handle: TopologyGraphHandle | null) => {
    graphHandleRef.current = handle;
  }, []);

  const clearSelection = useCallback(() => {
    setSelection(EMPTY_SELECTION);
    graphHandleRef.current?.focusCanvas();
  }, []);
  const handleSelection = useCallback((next: TopologySelection) => {
    setSelectionAnnouncement("");
    setSelection(next);
  }, []);

  useEffect(() => {
    const contextKey = `${scopeKey}::${renderedDetailLevel}`;
    if (
      selectionContextRef.current &&
      selectionContextRef.current !== contextKey
    ) {
      clearTopologyDetailCache();
      clearSelection();
      setSelectionAnnouncement("");
    }
    selectionContextRef.current = contextKey;
  }, [clearSelection, renderedDetailLevel, scopeKey]);

  useEffect(() => {
    if (topologyRef.current !== topology) {
      clearTopologyDetailCache();
      setSelection(EMPTY_SELECTION);
      setSelectionAnnouncement("");
    }
    topologyRef.current = topology;
  }, [topology]);

  useEffect(
    () => () => {
      clearTopologyDetailCache();
    },
    [],
  );

  useEffect(() => {
    if (
      (selection.node &&
        !visibleNodeIds.has(selection.node.id.toLowerCase())) ||
      (selection.edge && !visibleEdgeIds.has(selection.edge.id))
    ) {
      clearSelection();
      setSelectionAnnouncement("");
    }
  }, [
    clearSelection,
    selection.edge,
    selection.node,
    visibleEdgeIds,
    visibleNodeIds,
  ]);

  useEffect(() => {
    if (!filterMode || !normalizedSearch || (!selection.node && !selection.edge)) {
      return;
    }
    const selectedVisible = selection.node
      ? matchingNodeIds.has(selection.node.id)
      : Boolean(
          renderedGraph?.edges.some(
            (edge) =>
              edge.id === selection.edge?.id &&
              (matchingNodeIds.has(edge.source) ||
                matchingNodeIds.has(edge.target)),
          ),
        );
    if (!selectedVisible) {
      clearSelection();
      setSelectionAnnouncement(
        "Selection cleared — the selected resource is hidden by the current filter.",
      );
    }
  }, [
    clearSelection,
    filterMode,
    matchingNodeIds,
    normalizedSearch,
    renderedGraph,
    selection.edge,
    selection.node,
  ]);

  const projectedFullNodeCount = summary?.projected_full_node_count;
  const topologyBuildDurationMs = summary?.topology_build_duration_ms;
  const slowTopologyBuild =
    topologyBuildDurationMs !== undefined &&
    topologyBuildDurationMs > FULL_DETAIL_GUARD_BUILD_MS;

  const chooseDetailLevel = useCallback(
    (nextDetail: TopologyDetailLevel) => {
      if (
        nextDetail === "full" &&
        (projectedFullNodeCount === undefined ||
          projectedFullNodeCount > FULL_DETAIL_GUARD_NODES ||
          slowTopologyBuild)
      ) {
        setFullDetailPending(true);
        return;
      }
      setFullDetailPending(false);
      onDetailLevelChange?.(nextDetail);
    },
    [onDetailLevelChange, projectedFullNodeCount, slowTopologyBuild],
  );

  useEffect(() => {
    if (!loading || !topology || detailLevel !== "full") {
      setDetailLoadElapsedSeconds(0);
      return undefined;
    }
    const started = Date.now();
    const timer = window.setInterval(() => {
      setDetailLoadElapsedSeconds(
        Math.max(1, Math.floor((Date.now() - started) / 1_000)),
      );
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [detailLevel, loading, topology]);

  useEffect(() => {
    if (!expanded) return undefined;
    const onKey = (event: KeyboardEvent) => {
      // Escape closes the drawer first, then leaves full screen.
      if (event.key === "Escape") setExpanded(false);
    };
    document.body.classList.add("topology-fullscreen-open");
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.classList.remove("topology-fullscreen-open");
      window.removeEventListener("keydown", onKey);
    };
  }, [expanded]);

  const counts = useMemo(() => {
    if (!topology || !renderedGraph) return null;
    const droppedRelationships =
      (topology.counts.dropped_relationships as
        | Record<string, number>
        | undefined) ?? {};
    const droppedEntries = Object.entries(droppedRelationships).filter(
      ([, count]) => count > 0,
    );
    const peerCounts = renderedGraph.nodes.reduce(
      (result, node) => {
        if (node.kind === "unresolved") {
          const resolution = node.peerResolution ?? "unknown";
          result[resolution] += 1;
        }
        return result;
      },
      {
        not_ingested: 0,
        excluded_by_scope: 0,
        observed: 0,
        unknown: 0,
      },
    );
    return {
      hubs: topology.hubs.length,
      spokes: topology.spokes.length,
      isolated: topology.isolated.length,
      services: topology.shared_services.length,
      links: topology.links.length,
      resources: topology.resources?.length ?? topology.hubs.length + topology.spokes.length + topology.isolated.length + topology.shared_services.length,
      relationships: topology.relationships?.length ?? topology.links.length + topology.shared_services.reduce((count, service) => count + service.consumer_vnet_ids.length, 0),
      rendered: renderedGraph.nodes.length,
      total:
        topology.coverage?.nodes?.total ??
        topology.coverage?.total ??
        renderedGraph.nodes.length,
      droppedEntries,
      droppedTotal: droppedEntries.reduce((total, [, count]) => total + count, 0),
      peerCounts,
      findingsBearingNodes: renderedGraph.nodes.filter((node) =>
        findingSeverityByResource.has(node.id.toLowerCase()),
      ).length,
    };
  }, [findingSeverityByResource, renderedGraph, topology]);

  const freshnessSentence = useMemo(() => {
    if (!graphFreshness) {
      return "Snapshot age unknown — no observation timestamp was recorded.";
    }
    const milliseconds = new Date(graphFreshness).getTime();
    if (Number.isNaN(milliseconds) || milliseconds <= 0) {
      return "Snapshot age unknown — no observation timestamp was recorded.";
    }
    return `Snapshot observed ${relativeTime(graphFreshness)} (${formatDateTime(graphFreshness)}).`;
  }, [graphFreshness]);

  const exportContext = useMemo<TopologyExportContext>(() => {
    const relationshipTotal =
      topology?.coverage?.relationships?.total ??
      (typeof topology?.counts.relationships === "number"
        ? topology.counts.relationships
        : counts?.relationships ?? null);
    return {
      scope,
      detailLevel: renderedDetailLevel,
      coverage: {
        total: topology?.coverage?.total ?? counts?.total ?? null,
        returned:
          topology?.coverage?.nodes?.returned ??
          topology?.coverage?.returned ??
          counts?.rendered ??
          null,
        truncated: topology?.coverage?.truncated ?? false,
        badgePageBudget: BADGE_FETCH_MAX_PAGES,
        badgeFetchExhausted:
          !badgeLoading && !badgeCoverage.truncated,
        badgeReturned: badgeCoverage.mapped,
        badgeTotal: badgeCoverage.total,
        renderedNodes: counts?.rendered ?? 0,
        totalNodes: counts?.total ?? null,
        renderedRelationships:
          topology?.coverage?.relationships?.returned ??
          counts?.relationships ??
          0,
        totalRelationships: relationshipTotal,
        droppedRelationships: counts?.droppedTotal ?? 0,
      },
      filters: {
        search,
        filterMode,
        showServices,
        showFindings,
      },
      evidence,
      warnings,
      knowledgeVersion,
      graphFreshness: graphFreshness ?? null,
    };
  }, [
    badgeCoverage,
    badgeLoading,
    counts,
    evidence,
    filterMode,
    graphFreshness,
    knowledgeVersion,
    renderedDetailLevel,
    scope,
    search,
    showFindings,
    showServices,
    topology,
    warnings,
  ]);

  if (loading && !topology) {
    return (
      <StatePanel
        title="Building cross-subscription topology"
        message="Stitching VNets, peerings, and shared services."
        tone="loading"
      />
    );
  }
  if (error && !topology) {
    return <StatePanel title="Topology is unavailable" message={error.message} tone="error" />;
  }
  if (!topology || !renderedGraph || renderedGraph.nodes.length === 0) {
    return (
      <StatePanel
        title="No observed network topology"
        message="No VNets are visible in the current operating scope."
      />
    );
  }

  const selectedId = selection.node?.id ?? selection.edge?.id ?? "";

  return (
    <section
      className={`network-workspace topology-workspace${expanded ? " topology-workspace-expanded" : ""}`}
      aria-label="Network topology"
      aria-busy={loading}
    >
      <div className="topology-toolbar">
        <input
          className="form-control topology-search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Highlight resources by name"
          aria-label="Highlight topology nodes by name"
        />
        {onDetailLevelChange && (
          <div
            className="segmented-control"
            role="group"
            aria-label="Topology detail level"
          >
            <button
              type="button"
              aria-pressed={detailLevel === "summary"}
              className={detailLevel === "summary" ? "segmented-active" : ""}
              onClick={() => chooseDetailLevel("summary")}
            >
              Summary
            </button>
            <button
              type="button"
              aria-pressed={detailLevel === "full"}
              className={detailLevel === "full" ? "segmented-active" : ""}
              onClick={() => chooseDetailLevel("full")}
            >
              Full detail
            </button>
          </div>
        )}
        <label className="topology-toggle">
          <input
            type="checkbox"
            checked={filterMode}
            onChange={(event) => setFilterMode(event.target.checked)}
          />
          <span>Filter (hide non-matches)</span>
        </label>
        <label className="topology-toggle">
          <input
            type="checkbox"
            checked={showServices}
            onChange={(event) => setShowServices(event.target.checked)}
          />
          <span>Shared services</span>
        </label>
        <label className="topology-toggle">
          <input
            type="checkbox"
            checked={showUnattachedPrivateLinkCandidates}
            onChange={(event) =>
              setShowUnattachedPrivateLinkCandidates(event.target.checked)
            }
          />
          <span>Unattached private link candidates</span>
        </label>
        <label
          className="topology-toggle"
          title="Visual only — the details drawer always lists open findings."
        >
          <input
            type="checkbox"
            checked={showFindings}
            onChange={(event) => setShowFindings(event.target.checked)}
          />
          <span>Finding badges</span>
        </label>
        <div className="topology-legend" aria-label="Topology legend">
          <span className="topology-legend-hub">Hub</span>
          <span className="topology-legend-spoke">Spoke</span>
          <span className="topology-legend-resource">Resource</span>
          <span className="topology-legend-private-link">Private link candidate</span>
          <span className="topology-legend-isolated">Isolated</span>
          <span className="topology-legend-unresolved">Peer VNet not shown</span>
          <span className="topology-legend-unhealthy">Peering not connected</span>
        </div>
        {topology.coverage?.truncated && (
          <StatusBadge
            label={`Partial topology — ${
              topology.coverage.nodes?.returned ?? topology.coverage.returned
            } of ${
              topology.coverage.nodes?.total ?? topology.coverage.total
            } nodes; ${
              topology.coverage.relationships?.returned ?? counts?.relationships ?? 0
            } of ${
              topology.coverage.relationships?.total ?? counts?.relationships ?? 0
            } relationships`}
            tone="warning"
          />
        )}
        <button
          type="button"
          className="button button-secondary topology-export"
          onClick={() => graphHandleRef.current?.exportPng()}
          aria-label="Export PNG (image only)"
          title="The image carries no scope or freshness metadata. Export JSON for an auditable record."
        >
          Export PNG (image only)
        </button>
        <button
          type="button"
          className="button button-secondary topology-export"
          onClick={() => graphHandleRef.current?.exportJson()}
        >
          Export JSON
        </button>
        <button
          type="button"
          className="button button-secondary topology-expand"
          onClick={() => setExpanded((value) => !value)}
          aria-pressed={expanded}
        >
          {expanded ? "Exit full screen" : "Expand to full screen"}
        </button>
      </div>

      {error && (
        <div className="callout callout-critical topology-coverage" role="alert">
          <strong>Topology refresh failed.</strong>
          <span>{error.message} The retained topology remains available.</span>
        </div>
      )}

      {fullDetailPending && (
        <div className="callout callout-warning topology-coverage" role="status">
          <strong>
            {projectedFullNodeCount === undefined
              ? "Full-detail size is unavailable and may make the canvas slow to interact with."
              : projectedFullNodeCount > FULL_DETAIL_GUARD_NODES
                ? `Full detail renders about ${projectedFullNodeCount} nodes and may make the canvas slow to interact with.`
                : topologyBuildDurationMs !== undefined
                  ? `The last topology build took ${(topologyBuildDurationMs / 1_000).toFixed(1)} seconds; full detail may take a similar amount of time.`
                  : "Full-detail build cost is unavailable and may make the canvas slow to interact with."}
          </strong>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => {
              setFullDetailPending(false);
              onDetailLevelChange?.("full");
            }}
          >
            Load full detail
          </button>
        </div>
      )}

      {loading &&
        topology &&
        detailLevel === "full" &&
        detailLoadElapsedSeconds >= 3 && (
          <div
            className="callout callout-info topology-coverage"
            role="status"
          >
            <strong>
              Loading full detail — {detailLoadElapsedSeconds} seconds elapsed.
            </strong>
            <span>The populated topology remains available while this loads.</span>
            {onCancelDetailLoad && (
              <button
                type="button"
                className="button button-secondary"
                aria-label="Cancel full-detail load"
                onClick={onCancelDetailLoad}
              >
                Cancel
              </button>
            )}
          </div>
        )}

      {badgeCoverage.truncated && (
        <div className="callout callout-warning topology-coverage" role="status">
          <strong>Badge coverage is partial.</strong>
          <span>
            {badgeCoverage.mapped} of {badgeCoverage.total} findings were loaded,
            so some nodes may be missing a badge. Open a resource to see its
            confirmed findings.
          </span>
        </div>
      )}

      <div className="topology-stage">
        {filterMode && normalizedSearch && matchingNodeIds.size === 0 && (
          <div className="callout callout-info" role="status">
            No resources match &quot;{search.trim()}&quot;. Clear the filter to
            see the {renderedGraph?.nodes.length ?? 0} resources in scope.
          </div>
        )}
        <TopologyGraph
          topology={topology}
          search={search}
          filterMode={filterMode}
          showServices={showServices}
          selectedId={selectedId}
          onSelect={handleSelection}
          onReady={handleGraphReady}
          exportContext={exportContext}
          findingSeverityByResource={showFindings ? findingSeverityByResource : undefined}
          showUnattachedPrivateLinkCandidates={
            showUnattachedPrivateLinkCandidates
          }
        />
        <TopologyDetailDrawer
          node={selection.node}
          edge={selection.edge}
          onClose={clearSelection}
          findings={
            selection.node
              ? {
                  ...(findingsByResource.get(selection.node.id.toLowerCase()) ?? {
                    gaps: [],
                    ruleFindings: [],
                  }),
                  gapTotal: summary?.gap_count ?? gaps.length,
                  ruleFindingTotal:
                    summary?.rule_finding_count ?? ruleFindings.length,
                  mapped: badgeCoverage.mapped,
                  total: badgeCoverage.total,
                  truncated: badgeCoverage.truncated,
                  exhausted: !badgeLoading && !badgeCoverage.truncated,
                  loading: findingsLoading || badgeLoading,
                  error: findingsError,
                  onRetry: onRetryFindings,
                }
              : undefined
          }
          detailLevel={renderedDetailLevel}
          visibleNodeIds={visibleNodeIds}
          scope={scope ?? {}}
        />
      </div>

      {selectionAnnouncement && (
        <div role="status" aria-live="polite">
          {selectionAnnouncement}
        </div>
      )}

      {counts && (
        <div className="topology-footnote">
          <span>
            Rendering {counts.rendered} of {counts.total} nodes at {renderedDetailLevel} detail.
          </span>
          {renderedGraph.hiddenUnattachedPrivateLinkCount > 0 && (
            <span>
              {renderedGraph.hiddenUnattachedPrivateLinkCount} unattached private
              link candidate
              {renderedGraph.hiddenUnattachedPrivateLinkCount === 1 ? "" : "s"}{" "}
              hidden; enable the filter to show{" "}
              {renderedGraph.hiddenUnattachedPrivateLinkCount === 1 ? "it" : "them"}.
            </span>
          )}
          <span>{filterHiddenCount} hidden by filter</span>
          <span>{counts.hubs} hubs</span>
          <span>{counts.spokes} spokes</span>
          <span>{counts.isolated} isolated</span>
          <span>{counts.links} peerings</span>
          <span>{counts.services} shared services</span>
          <span>{counts.resources} resources</span>
          <span>{counts.relationships} relationships</span>
          {counts.droppedTotal > 0 && (
            <span>
              {counts.droppedTotal} relationships dropped (
              {counts.droppedEntries.map(([type]) => type).join(", ")}) —
              endpoints were not present in this scope.
            </span>
          )}
          {counts.peerCounts.not_ingested > 0 && (
            <span>{counts.peerCounts.not_ingested} peers not ingested</span>
          )}
          {counts.peerCounts.excluded_by_scope > 0 && (
            <span>
              {counts.peerCounts.excluded_by_scope} peers outside current scope
            </span>
          )}
          {counts.peerCounts.unknown > 0 && (
            <span>
              {counts.peerCounts.unknown} peers with unrecorded resolution
            </span>
          )}
          <span>{counts.findingsBearingNodes} nodes with open findings</span>
          <span>
            Badges: {badgeCoverage.mapped} of {badgeCoverage.total} findings
          </span>
          <span>{freshnessSentence}</span>
        </div>
      )}
    </section>
  );
}
