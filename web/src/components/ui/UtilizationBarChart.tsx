"use client";

/** Lightweight horizontal bar chart for per-resource CPU utilization. No
 * chart library dependency: renders normalized SVG bars, matching the
 * hand-rolled convention used by CvssRadarChart. */

export interface UtilizationBarDatum {
  id: string;
  label: string;
  value: number | null;
}

const CRITICAL = 90;
const WARNING = 70;

function barColor(value: number | null): string {
  if (value == null) return "#94a3b8";
  if (value >= CRITICAL) return "#dc2626";
  if (value >= WARNING) return "#d97706";
  return "#16a34a";
}

/** Horizontal bar chart, one bar per resource, sorted by caller. */
export function UtilizationBarChart({ data }: { data: UtilizationBarDatum[] }) {
  if (data.length === 0) return null;

  const rowHeight = 28;
  const height = data.length * rowHeight + 8;
  const labelWidth = 160;
  const chartWidth = 480;
  const width = labelWidth + chartWidth + 48;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      role="img"
      aria-label="CPU utilization by resource"
      style={{ maxWidth: 640, display: "block" }}
    >
      {data.map((d, i) => {
        const y = i * rowHeight + 4;
        const pct = Math.max(0, Math.min(100, d.value ?? 0));
        const barW = d.value == null ? 0 : (pct / 100) * chartWidth;
        return (
          <g key={d.id}>
            <text x={0} y={y + rowHeight / 2 + 4} fontSize={12} fill="var(--muted-foreground, #64748b)">
              {d.label.length > 20 ? `${d.label.slice(0, 19)}…` : d.label}
            </text>
            <rect
              x={labelWidth}
              y={y}
              width={chartWidth}
              height={rowHeight - 8}
              rx={4}
              fill="rgba(148, 163, 184, 0.15)"
            />
            <rect x={labelWidth} y={y} width={barW} height={rowHeight - 8} rx={4} fill={barColor(d.value)} />
            <text
              x={labelWidth + chartWidth + 8}
              y={y + rowHeight / 2 + 4}
              fontSize={12}
              fill="var(--foreground, #1f2937)"
            >
              {d.value == null ? "—" : `${d.value.toFixed(0)}%`}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
