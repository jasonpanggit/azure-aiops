"use client";

import { useEffect, useMemo, useRef } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import fcose from "cytoscape-fcose";
import type { ImpactedResource } from "@/lib/types";

cytoscape.use(fcose);

const CRITICALITY_COLOR: Record<string, string> = {
  critical: "#b42318",
  high: "#c26400",
  medium: "#8a6100",
  low: "#107c10",
};

/** Renders a proposed change's blast radius as a live graph: the directly
 * changed resource(s) at the centre, radiating out to every dependent the
 * predeploy engine traced, coloured by criticality and labelled with depth.
 * Built from `depends_on` edges already present on each impacted resource —
 * no new backend data is required, this is a rendering layer only. */
export default function BlastRadiusGraph({ resources }: { resources: ImpactedResource[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);

  const elements = useMemo<ElementDefinition[]>(() => {
    const byId = new Map(resources.map((resource) => [resource.resource_id, resource]));
    const nodes: ElementDefinition[] = resources.map((resource) => ({
      data: {
        id: resource.resource_id,
        label: resource.name || resource.resource_id,
        changed: resource.depth === 0,
        criticality: resource.criticality || "low",
        detail: `${resource.business_service || "Unmapped service"} · ${resource.environment || "unknown env"} · ${resource.owner || "unassigned owner"}`,
      },
    }));
    const edges: ElementDefinition[] = [];
    resources.forEach((resource) => {
      resource.depends_on.forEach((sourceId) => {
        if (!byId.has(sourceId)) return;
        edges.push({
          data: {
            id: `${sourceId}->${resource.resource_id}`,
            source: sourceId,
            target: resource.resource_id,
          },
        });
      });
    });
    return [...nodes, ...edges];
  }, [resources]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || elements.length === 0) return undefined;
    const cy = cytoscape({
      container,
      elements,
      minZoom: 0.2,
      maxZoom: 3,
      wheelSensitivity: 0.2,
      boxSelectionEnabled: false,
      style: [
        {
          selector: "node",
          style: {
            "background-color": (node: cytoscape.NodeSingular) => CRITICALITY_COLOR[node.data("criticality") as string] ?? CRITICALITY_COLOR.low,
            label: "data(label)",
            shape: "ellipse",
            width: 44,
            height: 44,
            "font-size": 10,
            color: "#17202a",
            "text-valign": "bottom",
            "text-margin-y": 6,
            "text-wrap": "ellipsis",
            "text-max-width": "90px",
            "text-background-color": "#ffffff",
            "text-background-opacity": 0.85,
            "text-background-padding": "2px",
            "border-width": 2,
            "border-color": "#ffffff",
          },
        },
        {
          selector: "node[?changed]",
          style: {
            width: 60,
            height: 60,
            "font-weight": "bold",
            "border-width": 4,
            "border-color": "#0f6cbd",
            "border-style": "solid",
          },
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "#8a97a6",
            "target-arrow-color": "#8a97a6",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "arrow-scale": 1,
          },
        },
      ] as unknown as cytoscape.StylesheetJson,
      layout: {
        name: "fcose",
        // `quality: "proof"` converges the full force simulation, which locks
        // the main thread for seconds once the blast radius grows past a
        // hundred resources. Animating that is worse still, so both degrade
        // together: large graphs get the incremental layout and appear at once.
        quality: elements.length > 100 ? "default" : "proof",
        animate: elements.length <= 100,
        animationDuration: 500,
        randomize: true,
        nodeSeparation: 90,
        idealEdgeLength: 100,
        nodeRepulsion: 7000,
        padding: 30,
      } as unknown as cytoscape.LayoutOptions,
    });
    cyRef.current = cy;
    cy.ready(() => cy.fit(undefined, 30));

    const observer = new ResizeObserver(() => cy.resize());
    observer.observe(container);

    return () => {
      observer.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
  }, [elements]);

  if (resources.length === 0) return null;

  return (
    <div className="blast-radius-graph-wrap">
      <div className="blast-radius-graph" ref={containerRef} role="img" aria-label="Blast radius graph of impacted resources" />
      <div className="blast-radius-legend">
        <span>
          <span className="legend-swatch legend-swatch-changed" /> Directly changed
        </span>
        <span>
          <span className="legend-swatch" style={{ background: CRITICALITY_COLOR.critical }} /> Critical
        </span>
        <span>
          <span className="legend-swatch" style={{ background: CRITICALITY_COLOR.high }} /> High
        </span>
        <span>
          <span className="legend-swatch" style={{ background: CRITICALITY_COLOR.medium }} /> Medium
        </span>
        <span>
          <span className="legend-swatch" style={{ background: CRITICALITY_COLOR.low }} /> Low
        </span>
      </div>
    </div>
  );
}
