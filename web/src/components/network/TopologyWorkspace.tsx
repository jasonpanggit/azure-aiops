"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StatePanel } from "@/components/ui/StatePanel";
import { TopologyDetailDrawer } from "@/components/network/TopologyDetailDrawer";
import type { TopologyGraphHandle, TopologySelection } from "@/components/network/TopologyGraph";
import { formatDateTime, relativeTime } from "@/lib/format";
import { buildTopologyGraph } from "@/lib/network-graph";
import type {
  CollectionCoverage,
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
  onDetailLevelChange?: (detail: TopologyDetailLevel) => void;
  loading: boolean;
  error: Error | null;
  gaps?: NetworkGap[];
  ruleFindings?: RuleFinding[];
  loadGapsPage?: LoadGapPage;
  loadRuleFindingsPage?: LoadRuleFindingPage;
  findingsLoading?: boolean;
  findingsError?: Error | null;
  findingsTruncated?: boolean;
  onRetryFindings?: () => void;
  graphFreshness?: string;
}

/** Interactive topology workspace: Cytoscape canvas, filters, and a detail drawer. */
export function TopologyWorkspace({
  topology,
  summary = null,
  detailLevel = "summary",
  onDetailLevelChange,
  loading,
  error,
  gaps = EMPTY_GAPS,
  ruleFindings = EMPTY_RULE_FINDINGS,
  loadGapsPage,
  loadRuleFindingsPage,
  findingsLoading = false,
  findingsError = null,
  findingsTruncated = false,
  onRetryFindings = () => undefined,
  graphFreshness,
}: TopologyWorkspaceProps) {
  const [search, setSearch] = useState("");
  const [filterMode, setFilterMode] = useState(false);
  const [showServices, setShowServices] = useState(true);
  const [showFindings, setShowFindings] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [fullDetailPending, setFullDetailPending] = useState(false);
  const [selection, setSelection] = useState<TopologySelection>(EMPTY_SELECTION);
  const [selectionAnnouncement, setSelectionAnnouncement] = useState("");
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
    () => (topology ? buildTopologyGraph(topology) : null),
    [topology],
  );
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

  const clearSelection = useCallback(() => setSelection(EMPTY_SELECTION), []);
  const handleSelection = useCallback((next: TopologySelection) => {
    setSelectionAnnouncement("");
    setSelection(next);
  }, []);

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
      setSelection(EMPTY_SELECTION);
      setSelectionAnnouncement(
        "Selection cleared — the selected resource is hidden by the current filter.",
      );
    }
  }, [
    filterMode,
    matchingNodeIds,
    normalizedSearch,
    renderedGraph,
    selection.edge,
    selection.node,
  ]);

  const projectedFullNodeCount = useMemo(
    () =>
      Object.values(summary?.resource_counts ?? {}).reduce(
        (total, count) => total + count,
        0,
      ),
    [summary],
  );

  const chooseDetailLevel = useCallback(
    (nextDetail: TopologyDetailLevel) => {
      if (
        nextDetail === "full" &&
        projectedFullNodeCount > FULL_DETAIL_GUARD_NODES
      ) {
        setFullDetailPending(true);
        return;
      }
      setFullDetailPending(false);
      onDetailLevelChange?.(nextDetail);
    },
    [onDetailLevelChange, projectedFullNodeCount],
  );

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
      total: topology.coverage?.total ?? renderedGraph.nodes.length,
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

  if (loading) {
    return (
      <StatePanel
        title="Building cross-subscription topology"
        message="Stitching VNets, peerings, and shared services."
        tone="loading"
      />
    );
  }
  if (error) {
    return <StatePanel title="Topology is unavailable" message={error.message} tone="error" />;
  }
  if (!topology || topology.hubs.length + topology.spokes.length + topology.isolated.length === 0) {
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
          <span className="topology-legend-isolated">Isolated</span>
          <span className="topology-legend-unresolved">Peer VNet not shown</span>
          <span className="topology-legend-unhealthy">Peering not connected</span>
        </div>
        <button
          type="button"
          className="button button-secondary topology-export"
          onClick={() => graphHandleRef.current?.exportPng()}
        >
          Export PNG
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

      {fullDetailPending && (
        <div className="callout callout-warning" role="status">
          <strong>
            Full detail renders about {projectedFullNodeCount} nodes and may make
            the canvas slow to interact with.
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

      {badgeCoverage.truncated && (
        <div className="callout callout-warning" role="status">
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
          findingSeverityByResource={showFindings ? findingSeverityByResource : undefined}
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
                  truncated: findingsTruncated || badgeCoverage.truncated,
                  exhausted: !badgeLoading && !badgeCoverage.truncated,
                  loading: findingsLoading || badgeLoading,
                  error: findingsError,
                  onRetry: onRetryFindings,
                }
              : undefined
          }
          detailLevel={detailLevel}
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
            Rendering {counts.rendered} of {counts.total} nodes at {detailLevel} detail.
          </span>
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
