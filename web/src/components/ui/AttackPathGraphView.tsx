"use client";

import type { AttackPathGraph, AttackPathNode } from "@/lib/types";

/** Lightweight multi-hop attack-path visualization. No chart/graph library
 * dependency: lays nodes out in fixed columns by kind (origin → firewall →
 * NSG → server) and draws straight SVG connectors for each edge, mirroring
 * the left-to-right flow of an actual network path. */

const COLUMN_ORDER: AttackPathNode["kind"][] = ["origin", "firewall", "nsg", "server"];
const COLUMN_LABELS: Record<AttackPathNode["kind"], string> = {
  origin: "Origin",
  firewall: "Firewall",
  nsg: "NSG",
  server: "Affected servers",
};
const COLUMN_WIDTH = 220;
const ROW_HEIGHT = 64;
const NODE_WIDTH = 160;
const NODE_HEIGHT = 40;

function nodeColor(node: AttackPathNode): string {
  if (node.kind === "origin") return "#8a94a6";
  if (node.kind === "firewall" || node.kind === "nsg") return "#c99a2e";
  if (node.reachable === false) return "#8a94a6";
  return node.network_exposure === "internet" ? "#c94f4f" : "#3f7f5f";
}

export function AttackPathGraphView({ graph }: { graph: AttackPathGraph }) {
  const columns = COLUMN_ORDER.map((kind) => graph.nodes.filter((node) => node.kind === kind));
  const positions = new Map<string, { x: number; y: number }>();
  columns.forEach((nodes, columnIndex) => {
    nodes.forEach((node, rowIndex) => {
      positions.set(node.id, {
        x: columnIndex * COLUMN_WIDTH + 20,
        y: rowIndex * ROW_HEIGHT + 20,
      });
    });
  });

  const maxRows = Math.max(1, ...columns.map((nodes) => nodes.length));
  const width = COLUMN_ORDER.length * COLUMN_WIDTH + NODE_WIDTH;
  const height = maxRows * ROW_HEIGHT + NODE_HEIGHT + 20;

  return (
    <div className="attack-path-graph">
      <svg width={width} height={height} role="img" aria-label={`Attack path graph for ${graph.cve_id}`}>
        {graph.edges.map((edge) => {
          const from = positions.get(edge.source);
          const to = positions.get(edge.target);
          if (!from || !to) return null;
          const x1 = from.x + NODE_WIDTH;
          const y1 = from.y + NODE_HEIGHT / 2;
          const x2 = to.x;
          const y2 = to.y + NODE_HEIGHT / 2;
          return (
            <g key={`${edge.source}->${edge.target}`}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#5a6472" strokeWidth={1.5} markerEnd="url(#attack-path-arrow)" />
              {edge.label && (
                <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 6} fontSize={10} fill="#8a94a6" textAnchor="middle">
                  {edge.label}
                </text>
              )}
            </g>
          );
        })}
        <defs>
          <marker id="attack-path-arrow" markerWidth={8} markerHeight={8} refX={7} refY={4} orient="auto">
            <path d="M0,0 L8,4 L0,8 Z" fill="#5a6472" />
          </marker>
        </defs>
        {graph.nodes.map((node) => {
          const position = positions.get(node.id);
          if (!position) return null;
          return (
            <g key={node.id} transform={`translate(${position.x}, ${position.y})`}>
              <rect width={NODE_WIDTH} height={NODE_HEIGHT} rx={6} fill={nodeColor(node)} opacity={0.85} />
              <text x={NODE_WIDTH / 2} y={NODE_HEIGHT / 2 + 4} fontSize={11} fill="#fff" textAnchor="middle">
                {node.label.length > 22 ? `${node.label.slice(0, 20)}…` : node.label}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="attack-path-legend">
        {COLUMN_ORDER.map((kind) => (
          <span key={kind}>{COLUMN_LABELS[kind]}</span>
        ))}
      </div>
    </div>
  );
}
