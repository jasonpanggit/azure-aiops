"use client";

import { useCallback, useEffect, useMemo, useRef } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import fcose from "cytoscape-fcose";
import {
  buildTopologyGraph,
  type TopologyEdgeData,
  type TopologyNodeData,
} from "@/lib/network-graph";
import type { NetworkTopology } from "@/lib/types";

cytoscape.use(fcose);

const KIND_COLOR: Record<string, string> = {
  hub: "#0f6cbd",
  spoke: "#56616f",
  isolated: "#8a6100",
  unresolved: "#778290",
  service: "#107c10",
  resource: "#605e5c",
};

const EDGE_COLOR: Record<string, string> = {
  healthy: "#8a97a6",
  unhealthy: "#b42318",
  unresolved: "#c9cfd7",
  service: "#107c10",
  relationship: "#6b7280",
};

/** Severity -> corner-badge colour for nodes carrying an open gap or rule finding. */
const SEVERITY_BADGE_COLOR: Record<string, string> = {
  critical: "#b42318",
  high: "#c26400",
  medium: "#8a6100",
  low: "#605e5c",
};

/** A small filled circle rendered as a second background-image layer, so an
 * open finding shows as a corner badge without any new icon asset. */
function severityBadgeUri(severity: string): string {
  const color = SEVERITY_BADGE_COLOR[severity] ?? SEVERITY_BADGE_COLOR.low;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><circle cx="12" cy="12" r="10" fill="${color}" stroke="#ffffff" stroke-width="2"/></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

/** Synchronizes one node's imperative Cytoscape badge data with its finding. */
export function syncFindingBadge(
  node: cytoscape.NodeSingular,
  finding: { severity: string; count: number; title?: string } | undefined
): void {
  if (finding) {
    const badge = severityBadgeUri(finding.severity);
    node.data("badge", badge);
    node.data(
      "badgeTitle",
      finding.title ??
        `${finding.count} open finding${finding.count === 1 ? "" : "s"} (${finding.severity})`,
    );
    node.style("background-image", [node.data("icon") || "none", badge]);
  } else {
    node.removeData("badge");
    node.removeData("badgeTitle");
    node.style("background-image", node.data("icon") || "none");
  }
}

/**
 * Cytoscape stylesheet. Official Azure icons sit on a white tile and are only
 * framed by a role-coloured border — Microsoft's icon terms forbid altering the
 * artwork itself, so no filter or recolouring is applied.
 */
export const STYLESHEET = [
  {
    selector: "node[kind]",
    style: {
      "background-color": "#ffffff",
      "background-image": "data(icon)",
      "background-fit": "contain",
      "background-clip": "none",
      "background-width": "62%",
      "background-height": "62%",
      "border-width": 2,
      "border-color": (node: cytoscape.NodeSingular) => KIND_COLOR[node.data("kind") as string] ?? "#56616f",
      shape: "round-rectangle",
      width: 52,
      height: 52,
      label: "data(label)",
      "font-size": 10,
      color: "#17202a",
      "text-valign": "bottom",
      "text-margin-y": 6,
      "text-wrap": "ellipsis",
      "text-max-width": "96px",
      "text-background-color": "#ffffff",
      "text-background-opacity": 0.85,
      "text-background-padding": "2px",
    },
  },
  {
    selector: 'node[kind = "hub"]',
    style: { width: 68, height: 68, "font-size": 11, "font-weight": "bold" },
  },
  {
    selector: 'node[kind = "unresolved"]',
    style: { "border-style": "dashed", opacity: 0.75 },
  },
  {
    selector: 'node[kind = "service"]',
    style: { shape: "round-diamond", width: 48, height: 48 },
  },
  {
    selector: 'node[kind = "resource"]',
    style: { shape: "round-rectangle", width: 46, height: 46, "font-size": 9 },
  },
  {
    // Workloads outside the network keep the dashed outline that marks them as
    // context rather than network topology, but still show their service icon.
    selector: 'node[kind = "workload"]',
    style: {
      shape: "round-rectangle",
      width: 46,
      height: 46,
      "font-size": 9,
      "border-width": 1.5,
      "border-style": "dashed",
      "border-color": "#8a97a6",
    },
  },
  {
    // Only a workload with no official glyph falls back to a plain tile.
    selector: 'node[kind = "workload"][icon = ""]',
    style: { "background-color": "#eef2f7", "background-image": "none" },
  },
  {
    // Corner badge for a node with an open gap/rule finding: rendered as a
    // second background-image layer so no extra DOM node or icon asset is
    // needed. Position/size keep it clear of the primary service icon.
    selector: "node[badge]",
    style: {
      // Cytoscape parses multi-layer background values as space-separated
      // lists, not comma-separated; a comma here makes the whole stylesheet
      // invalid and the graph fails to mount.
      "background-image": (node: cytoscape.NodeSingular) => [node.data("icon") || "none", node.data("badge")],
      "background-fit": "contain none",
      "background-clip": "none none",
      "background-width": "62% 34%",
      "background-height": "62% 34%",
      "background-position-x": "50% 100%",
      "background-position-y": "50% 0%",
    },
  },
  {
    selector: 'node[entityType = "NetworkSecurityRule"], node[entityType = "FirewallRule"], node[entityType = "Route"]',
    style: { width: 34, height: 34, "font-size": 8, opacity: 0.9 },
  },
  {
    selector: "node:parent",
    style: {
      "background-color": "#f5f7fa",
      "border-color": "#c9cfd7",
      "border-width": 1,
      "border-style": "dashed",
      shape: "round-rectangle",
      // Extra top padding reserves a header strip for the subscription label.
      padding: 30,
      label: "data(label)",
      "font-size": 10,
      "font-weight": "bold",
      color: "#778290",
      "text-valign": "top",
      "text-halign": "center",
      "text-margin-y": -8,
    },
  },
  {
    selector: "edge",
    style: {
      width: 1.6,
      "line-color": (edge: cytoscape.EdgeSingular) => EDGE_COLOR[edge.data("kind") as string] ?? "#8a97a6",
      "curve-style": "bezier",
      // Every edge is directed unless it is a peering, which is drawn with a
      // head at each end when both sides are configured.
      "target-arrow-shape": "triangle",
      "target-arrow-color": (edge: cytoscape.EdgeSingular) => EDGE_COLOR[edge.data("kind") as string] ?? "#8a97a6",
      "arrow-scale": 1.1,
      label: "data(label)",
      "font-size": 9,
      color: "#778290",
      "text-background-color": "#ffffff",
      "text-background-opacity": 0.9,
      "text-background-padding": "2px",
      // Keep relationship lines above the compound subscription backdrop.
      "z-compound-depth": "top",
      "z-index": 20,
    },
  },
  { selector: 'edge[kind = "unhealthy"]', style: { width: 3, "line-style": "dashed" } },
  { selector: 'edge[kind = "unresolved"]', style: { "line-style": "dotted" } },
  { selector: 'edge[kind = "service"]', style: { "line-style": "dashed", width: 2, opacity: 0.85 } },
  { selector: 'edge[kind = "relationship"]', style: { "line-style": "solid", width: 2.2, opacity: 0.95 } },
  // A bidirectional peering is symmetric, so it carries a head at both ends.
  { selector: "edge[?bidirectional]", style: { "source-arrow-shape": "triangle", "source-arrow-color": "#8a97a6" } },
  { selector: ".cy-selected", style: { "border-width": 4, "border-color": "#0f6cbd", "overlay-color": "#0f6cbd", "overlay-opacity": 0.12, "overlay-padding": 8 } },
  { selector: "edge.cy-selected", style: { width: 3.5, "line-color": "#0f6cbd" } },
  { selector: ".cy-dimmed", style: { opacity: 0.15, "text-opacity": 0.1 } },
  // Hover-highlight: the hovered node and its immediate neighbourhood pop
  // forward while everything else recedes, so dense graphs stay legible.
  { selector: ".cy-hover-focus", style: { "z-index": 30 } },
  { selector: "node.cy-hover-focus", style: { "border-width": 4 } },
  { selector: "edge.cy-hover-focus", style: { width: 3, opacity: 1 } },
  // Faded enough to recede behind the focused neighbourhood, but still legible
  // so the surrounding topology stays readable rather than washing out.
  { selector: ".cy-hover-fade", style: { opacity: 0.3, "text-opacity": 0.2 } },
  // Group containers are backdrops, not participants in a hover focus, so
  // fading them just makes the canvas look washed out.
  { selector: "node:parent.cy-hover-fade", style: { opacity: 1, "text-opacity": 1 } },
] as unknown as cytoscape.StylesheetJson;

/**
 * Focus a hovered element's neighbourhood and fade the rest.
 *
 * Descendants of the focused set are kept in focus so hovering a node that
 * contains children never blanks them out, and compound group containers are
 * excluded from the fade by the stylesheet so the canvas keeps its structure.
 */
export function applyHoverFocus(cy: cytoscape.Core, focus: cytoscape.Collection): void {
  const withDescendants = focus.union(focus.nodes().descendants());
  cy.elements().difference(withDescendants).addClass("cy-hover-fade");
  withDescendants.addClass("cy-hover-focus");
}

/** Remove every hover-highlight class, restoring the graph's resting state. */
export function clearHoverFocus(cy: cytoscape.Core): void {
  cy.elements().removeClass("cy-hover-fade cy-hover-focus");
}

/**
 * fCoSE options, scaled to the graph size.
 *
 * `quality: "proof"` runs the full multi-level force simulation to convergence.
 * On a small estate that is a better-looking layout for a few hundred
 * milliseconds of work; past roughly a hundred nodes it is quadratic enough to
 * lock the main thread for seconds, and the canvas appears frozen. `randomize`
 * compounds this: it discards the previous positions, so every re-layout pays
 * full cost *and* the user loses spatial memory of where things were.
 *
 * So both degrade with size: large graphs get the incremental "default"
 * quality and keep their existing positions, which is faster and less
 * disorienting precisely when there is most to keep track of.
 */
const LAYOUT_NODE_BUDGET = 100;

export function layoutFor(nodeCount: number): cytoscape.LayoutOptions {
  const large = nodeCount > LAYOUT_NODE_BUDGET;
  return {
    name: "fcose",
    quality: large ? "default" : "proof",
    animate: false,
    randomize: !large,
    nodeSeparation: 110,
    idealEdgeLength: 130,
    nodeRepulsion: 9000,
    gravityRangeCompound: 1.4,
    packComponents: true,
    padding: 40,
  } as unknown as cytoscape.LayoutOptions;
}

/** Preserve spatial memory whenever a new topology payload replaces one that
 * already has positioned nodes. The explicit Re-layout action remains the only
 * path that forces randomization. */
export function layoutForTransition(
  nodeCount: number,
  hasPreviousPositions: boolean,
): cytoscape.LayoutOptions {
  const options = layoutFor(nodeCount);
  return hasPreviousPositions
    ? ({ ...options, randomize: false } as cytoscape.LayoutOptions)
    : options;
}

/** Triggers a browser download for a data: URI without a server round trip. */
function downloadDataUri(uri: string, filename: string): void {
  const link = document.createElement("a");
  link.href = uri;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

export interface TopologySelection {
  node: TopologyNodeData | null;
  edge: TopologyEdgeData | null;
}

/** Imperative handle exposed to the host so toolbar buttons can drive the canvas. */
export interface TopologyGraphHandle {
  exportPng: () => void;
  exportJson: () => void;
}

interface TopologyGraphProps {
  topology: NetworkTopology;
  /** Applied to node labels. In "dim" mode non-matches fade but stay on
   * screen; in "filter" mode they are removed from the rendered graph so the
   * user can focus on a subset without losing spatial memory of what exists. */
  search: string;
  filterMode?: boolean;
  showServices: boolean;
  selectedId: string;
  onSelect: (selection: TopologySelection) => void;
  /** Receives an imperative handle for export actions once the canvas mounts. */
  onReady?: (handle: TopologyGraphHandle | null) => void;
  /** Highest-severity open gap/rule finding per resource id. When set, matching
   * nodes render a small corner badge sourced from `/gaps` and `/rule-findings`. */
  findingSeverityByResource?: Map<
    string,
    { severity: string; count: number; title?: string }
  >;
}

/**
 * Interactive Cytoscape canvas for the observed network topology.
 *
 * Elements are constructed once per topology payload; search, service toggling
 * and selection mutate the live graph in place so pan and zoom are preserved.
 */
export default function TopologyGraph({
  topology,
  search,
  filterMode = false,
  showServices,
  selectedId,
  onSelect,
  onReady,
  findingSeverityByResource,
}: TopologyGraphProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const positionsRef = useRef<Map<string, cytoscape.Position>>(new Map());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const graph = useMemo(() => buildTopologyGraph(topology), [topology]);

  const elements = useMemo<ElementDefinition[]>(() => {
    const groups: ElementDefinition[] = graph.groups.map((group) => ({
      data: { id: group.id, label: group.label },
    }));
    const nodes: ElementDefinition[] = graph.nodes.map((node) => ({
      data: { ...node, detail: node },
    }));
    const edges: ElementDefinition[] = graph.edges.map((edge) => ({
      data: { ...edge, detail: edge },
    }));
    return [...groups, ...nodes, ...edges];
  }, [graph]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const previousPositions = positionsRef.current;
    const positionedElements = elements.map((element) => {
      const id = "data" in element ? String(element.data.id ?? "") : "";
      const position = previousPositions.get(id);
      return position ? { ...element, position } : element;
    });
    const cy = cytoscape({
      container,
      elements: positionedElements,
      style: STYLESHEET,
      minZoom: 0.15,
      maxZoom: 3,
      wheelSensitivity: 0.2,
      boxSelectionEnabled: false,
    });
    cyRef.current = cy;

    const hasPreviousPositions = cy
      .nodes()
      .toArray()
      .some((node) => previousPositions.has(node.id()));
    cy.layout(layoutForTransition(cy.nodes().length, hasPreviousPositions)).run();
    cy.fit(undefined, 40);

    cy.on("tap", "node", (event) => {
      const detail = event.target.data("detail") as TopologyNodeData | undefined;
      // Compound subscription groups carry no detail payload.
      if (detail) onSelectRef.current({ node: detail, edge: null });
    });
    cy.on("tap", "edge", (event) => {
      onSelectRef.current({ node: null, edge: event.target.data("detail") as TopologyEdgeData });
    });
    cy.on("tap", (event) => {
      if (event.target === cy) onSelectRef.current({ node: null, edge: null });
    });

    // Hover-highlight: pull the hovered node's direct neighbourhood forward
    // and fade the rest, so relationships are legible even in dense graphs.
    // Compound subscription groups are skipped: they cover large areas of
    // otherwise-empty canvas, so treating a hover over that background as a
    // node hover would fade the whole graph.
    cy.on("mouseover", "node", (event) => {
      const node = event.target as cytoscape.NodeSingular;
      if (node.isParent()) return;
      applyHoverFocus(cy, node.closedNeighborhood());
    });
    cy.on("mouseover", "edge", (event) => {
      const edge = event.target as cytoscape.EdgeSingular;
      applyHoverFocus(cy, edge.connectedNodes().union(edge));
    });
    cy.on("mouseout", "node, edge", () => {
      clearHoverFocus(cy);
    });

    // Keep the viewport correct when the canvas is expanded to full screen.
    const observer = new ResizeObserver(() => {
      cy.resize();
    });
    observer.observe(container);

    onReady?.({
      exportPng: () => {
        const uri = cy.png({ full: true, scale: 2, bg: "#eef2f6" });
        downloadDataUri(uri, "network-topology.png");
      },
      exportJson: () => {
        const payload = JSON.stringify(topology, null, 2);
        const uri = `data:application/json;charset=utf-8,${encodeURIComponent(payload)}`;
        downloadDataUri(uri, "network-topology.json");
      },
    });

    return () => {
      const positions = new Map<string, cytoscape.Position>();
      cy.nodes().forEach((node) => {
        if (!node.isParent()) positions.set(node.id(), { ...node.position() });
      });
      positionsRef.current = positions;
      observer.disconnect();
      onReady?.(null);
      cy.destroy();
      cyRef.current = null;
    };
  }, [elements, onReady, topology]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const term = search.trim().toLowerCase();
    cy.batch(() => {
      cy.elements().removeClass("cy-dimmed cy-selected");
      cy.elements().style("display", "element");
      const services = cy.nodes('[kind = "service"]').union(cy.edges('[kind = "service"]'));
      services.style("display", showServices ? "element" : "none");
      if (term) {
        const matched = cy
          .nodes("[label]")
          .filter((node) => String(node.data("label") ?? "").toLowerCase().includes(term));
        const keep = matched.union(matched.connectedEdges()).union(matched.ancestors());
        const drop = cy.elements().difference(keep);
        if (filterMode) {
          // True filter: remove non-matches from the rendered graph entirely,
          // rather than merely dimming them, so the view is unambiguous.
          drop.style("display", "none");
        } else {
          drop.addClass("cy-dimmed");
        }
      }
      if (selectedId) {
        const selected = cy.getElementById(selectedId);
        if (selected.nonempty()) selected.removeClass("cy-dimmed").addClass("cy-selected");
      }
    });
  }, [search, filterMode, showServices, selectedId]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const finding = findingSeverityByResource?.get(node.id().toLowerCase());
        syncFindingBadge(node, finding);
      });
    });
  }, [findingSeverityByResource, elements]);

  const fit = useCallback(() => {
    cyRef.current?.animate({ fit: { eles: cyRef.current.elements(), padding: 40 } }, { duration: 200 });
  }, []);

  const zoomBy = useCallback((factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }, []);

  const relayout = useCallback(() => {
    const cy = cyRef.current;
    if (!cy) return;
    // An explicit re-layout is the one case where discarding positions is what
    // the user asked for, so force the randomized pass regardless of size.
    cy.layout({ ...layoutFor(cy.nodes().length), randomize: true } as cytoscape.LayoutOptions).run();
    cy.fit(undefined, 40);
  }, []);

  return (
    <div className="topology-canvas-wrap">
      <div
        className="topology-canvas"
        ref={containerRef}
        role="application"
        aria-label="Interactive network topology graph"
      />
      <div className="topology-canvas-controls">
        <button type="button" onClick={() => zoomBy(1.25)} aria-label="Zoom in">
          +
        </button>
        <button type="button" onClick={() => zoomBy(0.8)} aria-label="Zoom out">
          −
        </button>
        <button type="button" onClick={fit}>
          Fit
        </button>
        <button type="button" onClick={relayout}>
          Re-layout
        </button>
      </div>
    </div>
  );
}
