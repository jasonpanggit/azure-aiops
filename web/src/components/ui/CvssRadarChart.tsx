"use client";

/** Lightweight CVSS vector radar chart. No chart library dependency: parses the
 * CVSS v3.x vector string client-side and renders normalized axes as an SVG
 * polygon, matching the visual convention of the NVD CVSS calculator. */

const METRIC_LABELS: Record<string, string> = {
  AV: "Attack vector",
  AC: "Attack complexity",
  PR: "Privileges required",
  UI: "User interaction",
  S: "Scope",
  C: "Confidentiality",
  I: "Integrity",
  A: "Availability",
};

// Higher value = more severe/exploitable, normalized 0-1 per CVSS v3.1 metric definitions.
const METRIC_SCALES: Record<string, Record<string, number>> = {
  AV: { N: 1, A: 0.75, L: 0.5, P: 0.25 },
  AC: { L: 1, H: 0.5 },
  PR: { N: 1, L: 0.6, H: 0.3 },
  UI: { N: 1, R: 0.5 },
  S: { C: 1, U: 0.5 },
  C: { H: 1, L: 0.5, N: 0 },
  I: { H: 1, L: 0.5, N: 0 },
  A: { H: 1, L: 0.5, N: 0 },
};

const AXIS_ORDER = ["AV", "AC", "PR", "UI", "C", "I", "A"];

function parseCvssVector(vector: string): Record<string, string> {
  const parts: Record<string, string> = {};
  for (const segment of vector.split("/")) {
    const [key, value] = segment.split(":");
    if (key && value && key in METRIC_SCALES) parts[key] = value;
  }
  return parts;
}

export function CvssRadarChart({
  vector,
  radius = 78,
  compact = false,
}: {
  vector: string;
  radius?: number;
  compact?: boolean;
}) {
  const metrics = parseCvssVector(vector);
  const axes = AXIS_ORDER.filter((key) => metrics[key] !== undefined);
  if (axes.length < 3) return null;

  // Reserve fixed margin for the outer axis labels so they never clip the
  // viewBox edge, independent of the plotted radius. Compact mode drops the
  // labels entirely -- in a table cell repeated across every CVE row there is
  // no space for them, and the shape alone is what makes rows comparable at a
  // glance. The full vector stays available as a tooltip and to screen
  // readers, so nothing is lost.
  const labelMargin = compact ? 4 : 78;
  const size = (radius + labelMargin) * 2;
  const center = size / 2;
  const angleStep = (2 * Math.PI) / axes.length;

  const point = (index: number, value: number) => {
    const angle = index * angleStep - Math.PI / 2;
    const r = radius * value;
    return [center + r * Math.cos(angle), center + r * Math.sin(angle)] as const;
  };

  const polygonPoints = axes
    .map((key, index) => point(index, METRIC_SCALES[key][metrics[key]] ?? 0).join(","))
    .join(" ");

  const rings = compact ? [0.5, 1] : [0.25, 0.5, 0.75, 1];
  const summary = axes.map((key) => `${METRIC_LABELS[key]}: ${metrics[key]}`).join(", ");

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className={compact ? "cvss-radar-chart cvss-radar-chart-compact" : "cvss-radar-chart"}
      role="img"
      aria-label={`CVSS vector radar chart. ${summary}`}
    >
      {compact && <title>{vector}</title>}
      {rings.map((ring) => (
        <polygon
          key={ring}
          points={axes.map((_, index) => point(index, ring).join(",")).join(" ")}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={1}
        />
      ))}
      {axes.map((_, index) => {
        const [x, y] = point(index, 1);
        return <line key={index} x1={center} y1={center} x2={x} y2={y} stroke="var(--color-border)" strokeWidth={1} />;
      })}
      <polygon
        points={polygonPoints}
        fill="var(--color-critical)"
        fillOpacity={0.25}
        stroke="var(--color-critical)"
        strokeWidth={compact ? 1.5 : 2}
      />
      {!compact &&
        axes.map((key, index) => {
          // Distance-based label offset (not a radius multiplier) keeps labels a
          // consistent distance from the plot regardless of chart size, and the
          // anchor is picked from horizontal position so left/right labels don't
          // run past the viewBox edge.
          const angle = index * angleStep - Math.PI / 2;
          const lx = center + (radius + 22) * Math.cos(angle);
          const ly = center + (radius + 22) * Math.sin(angle);
          const anchor = Math.cos(angle) > 0.3 ? "start" : Math.cos(angle) < -0.3 ? "end" : "middle";
          return (
            <text
              key={key}
              x={lx}
              y={ly}
              textAnchor={anchor}
              dominantBaseline="middle"
              className="cvss-radar-label"
            >
              {METRIC_LABELS[key]} ({metrics[key]})
            </text>
          );
        })}
    </svg>
  );
}
