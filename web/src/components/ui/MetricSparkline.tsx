"use client";

/** Lightweight inline trend line for a single metric's recent series. No
 * chart library dependency: renders a normalized SVG polyline, matching the
 * hand-rolled convention used by UtilizationBarChart and CvssRadarChart. */

export interface SparklinePoint {
  timestamp: string;
  value: number;
}

const CRITICAL = 90;
const WARNING = 70;

function strokeColor(latest: number | null): string {
  if (latest == null) return "#94a3b8";
  if (latest >= CRITICAL) return "#dc2626";
  if (latest >= WARNING) return "#d97706";
  return "#16a34a";
}

/** Compact trend sparkline, one polyline over the queried lookback window.
 * `max` clamps the y-axis (defaults to 100 for percentage metrics); pass the
 * observed peak for byte-rate metrics so the line still has visible shape. */
export function MetricSparkline({
  data,
  max,
  height = 40,
  width = 160,
}: {
  data: SparklinePoint[];
  max?: number;
  height?: number;
  width?: number;
}) {
  if (data.length === 0) {
    return (
      <svg width={width} height={height} role="img" aria-label="No trend data available">
        <text x={4} y={height / 2 + 4} fontSize={11} fill="var(--muted-foreground, #94a3b8)">
          No trend data
        </text>
      </svg>
    );
  }

  const values = data.map((d) => d.value);
  const latest = values[values.length - 1] ?? null;
  const ceiling = max ?? Math.max(100, ...values);
  const pad = 4;
  const points = data
    .map((d, i) => {
      const x = pad + (i / Math.max(1, data.length - 1)) * (width - pad * 2);
      const pct = ceiling > 0 ? Math.max(0, Math.min(1, d.value / ceiling)) : 0;
      const y = height - pad - pct * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={`Trend over the last ${data.length} readings, latest ${latest?.toFixed(1) ?? "—"}`}
    >
      <polyline points={points} fill="none" stroke={strokeColor(latest)} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
