"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StatePanel } from "@/components/ui/StatePanel";
import { TopologyDetailDrawer } from "@/components/network/TopologyDetailDrawer";
import type { TopologyGraphHandle, TopologySelection } from "@/components/network/TopologyGraph";
import type { NetworkGap, NetworkTopology, RuleFinding } from "@/lib/types";

const SEVERITY_RANK: Record<string, number> = { critical: 3, high: 2, medium: 1, low: 0 };

/** Highest-severity finding per resource id, used to badge topology nodes with
 * open gaps/rule findings without a separate lookup step on the canvas. */
function buildFindingSeverityMap(
  gaps: NetworkGap[],
  ruleFindings: RuleFinding[]
): Map<string, { severity: string; count: number }> {
  const map = new Map<string, { severity: string; count: number }>();
  const bump = (resourceId: string, severity: string) => {
    if (!resourceId) return;
    const existing = map.get(resourceId);
    if (!existing) {
      map.set(resourceId, { severity, count: 1 });
      return;
    }
    existing.count += 1;
    if ((SEVERITY_RANK[severity] ?? 0) > (SEVERITY_RANK[existing.severity] ?? 0)) {
      existing.severity = severity;
    }
  };
  for (const gap of gaps) bump(gap.resource_id, gap.severity);
  for (const finding of ruleFindings) bump(finding.control_id, finding.severity);
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
    let value = map.get(resourceId);
    if (!value) {
      value = { gaps: [], ruleFindings: [] };
      map.set(resourceId, value);
    }
    return value;
  };
  for (const gap of gaps) {
    if (!gap.resource_id) continue;
    entry(gap.resource_id).gaps.push(gap);
  }
  for (const finding of ruleFindings) {
    if (!finding.control_id) continue;
    entry(finding.control_id).ruleFindings.push(finding);
  }
  return map;
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
  loading: boolean;
  error: Error | null;
  gaps?: NetworkGap[];
  ruleFindings?: RuleFinding[];
}

/** Interactive topology workspace: Cytoscape canvas, filters, and a detail drawer. */
export function TopologyWorkspace({
  topology,
  loading,
  error,
  gaps = [],
  ruleFindings = [],
}: TopologyWorkspaceProps) {
  const [search, setSearch] = useState("");
  const [filterMode, setFilterMode] = useState(false);
  const [showServices, setShowServices] = useState(true);
  const [showFindings, setShowFindings] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [selection, setSelection] = useState<TopologySelection>(EMPTY_SELECTION);
  const graphHandleRef = useRef<TopologyGraphHandle | null>(null);

  const findingSeverityByResource = useMemo(
    () => buildFindingSeverityMap(gaps, ruleFindings),
    [gaps, ruleFindings]
  );
  const findingsByResource = useMemo(
    () => buildFindingsByResource(gaps, ruleFindings),
    [gaps, ruleFindings]
  );

  const handleGraphReady = useCallback((handle: TopologyGraphHandle | null) => {
    graphHandleRef.current = handle;
  }, []);

  const clearSelection = useCallback(() => setSelection(EMPTY_SELECTION), []);

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
    if (!topology) return null;
    return {
      hubs: topology.hubs.length,
      spokes: topology.spokes.length,
      isolated: topology.isolated.length,
      unresolved: topology.unresolved_peer_vnet_ids.length,
      services: topology.shared_services.length,
      links: topology.links.length,
      resources: topology.resources?.length ?? topology.hubs.length + topology.spokes.length + topology.isolated.length + topology.shared_services.length,
      relationships: topology.relationships?.length ?? topology.links.length + topology.shared_services.reduce((count, service) => count + service.consumer_vnet_ids.length, 0),
    };
  }, [topology]);

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
            checked={showFindings}
            onChange={(event) => setShowFindings(event.target.checked)}
          />
          <span>Gap / rule badges</span>
        </label>
        <div className="topology-legend" aria-label="Topology legend">
          <span className="topology-legend-hub">Hub</span>
          <span className="topology-legend-spoke">Spoke</span>
          <span className="topology-legend-resource">Resource</span>
          <span className="topology-legend-isolated">Isolated</span>
          <span className="topology-legend-unresolved">Not onboarded</span>
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

      <div className="topology-stage">
        <TopologyGraph
          topology={topology}
          search={search}
          filterMode={filterMode}
          showServices={showServices}
          selectedId={selectedId}
          onSelect={setSelection}
          onReady={handleGraphReady}
          findingSeverityByResource={showFindings ? findingSeverityByResource : undefined}
        />
        <TopologyDetailDrawer
          node={selection.node}
          edge={selection.edge}
          onClose={clearSelection}
          findings={selection.node ? findingsByResource.get(selection.node.id) : undefined}
        />
      </div>

      {counts && (
        <div className="topology-footnote">
          <span>{counts.hubs} hubs</span>
          <span>{counts.spokes} spokes</span>
          <span>{counts.isolated} isolated</span>
          <span>{counts.links} peerings</span>
          <span>{counts.services} shared services</span>
          <span>{counts.resources} resources</span>
          <span>{counts.relationships} relationships</span>
          <span>{counts.unresolved} peers not onboarded</span>
        </div>
      )}
    </section>
  );
}
