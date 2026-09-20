"use client";

export interface DonutSegment {
  label: string;
  value: number;
  color: string;
}

export interface DonutChartProps {
  segments: DonutSegment[];
  /** Rendered in the center of the ring, e.g. the total count. */
  centerValue?: string | number;
  centerLabel?: string;
}

/** Compact ring chart for count breakdowns (e.g. severity, source, or state
 * distributions). Pure SVG, no charting library — matches the hand-rolled
 * convention used by CvssRadarChart, RiskGauge, and UtilizationBarChart. */
export function DonutChart({ segments, centerValue, centerLabel }: DonutChartProps) {
  const total = segments.reduce((sum, segment) => sum + Math.max(0, segment.value), 0);
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  const cx = 48;
  const cy = 48;
  let offset = 0;

  const ariaSummary = segments.map((segment) => `${segment.label} ${segment.value}`).join(", ");

  return (
    <div className="donut-chart">
      <div className="donut-chart-visual">
        <svg
          viewBox="0 0 96 96"
          className="donut-chart-svg"
          role="img"
          aria-label={`Distribution: ${ariaSummary || "no data"}`}
        >
          {total === 0 ? (
            <circle cx={cx} cy={cy} r={radius} fill="none" stroke="var(--color-border)" strokeWidth={14} />
          ) : (
            segments
              .filter((segment) => segment.value > 0)
              .map((segment) => {
                const fraction = segment.value / total;
                const dash = fraction * circumference;
                const dashArray = `${dash} ${circumference - dash}`;
                const rotation = (offset / total) * 360 - 90;
                offset += segment.value;
                return (
                  <circle
                    key={segment.label}
                    cx={cx}
                    cy={cy}
                    r={radius}
                    fill="none"
                    stroke={segment.color}
                    strokeWidth={14}
                    strokeDasharray={dashArray}
                    transform={`rotate(${rotation} ${cx} ${cy})`}
                  />
                );
              })
          )}
        </svg>
        {(centerValue !== undefined || centerLabel) && (
          <div className="donut-chart-center">
            {centerValue !== undefined && (
              <span
                className={
                  String(centerValue).length > 6
                    ? "donut-chart-center-value donut-chart-center-value--compact"
                    : "donut-chart-center-value"
                }
              >
                {centerValue}
              </span>
            )}
            {centerLabel && <span className="donut-chart-center-label">{centerLabel}</span>}
          </div>
        )}
      </div>
      <ul className="donut-chart-legend">
        {segments.map((segment) => (
          <li key={segment.label}>
            <span className="donut-chart-swatch" style={{ background: segment.color }} aria-hidden="true" />
            <span className="donut-chart-legend-label">{segment.label}</span>
            <span className="donut-chart-legend-value">{segment.value.toLocaleString("en-US")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
