"use client";

export interface CountBarDatum {
  id: string;
  label: string;
  value: number;
}

/** Horizontal bar list for count breakdowns or explicitly labeled like-unit values. Bars
 * are normalized against the largest value in the set. Pure CSS/DOM — no
 * charting library, matching the hand-rolled convention used elsewhere in
 * this UI (DonutChart, RiskGauge, UtilizationBarChart). */
export function CountBarChart({ data, unit, ariaLabel, formatValue }: {
  data: CountBarDatum[];
  unit?: string;
  /** Override the count-specific name when displaying another quantitative unit. */
  ariaLabel?: string;
  /** Format exact values, for example monetary amounts in one currency. */
  formatValue?: (value: number) => string;
}) {
  if (data.length === 0) return null;
  const max = Math.max(1, ...data.map((d) => d.value));

  return (
    <ul className="count-bar-chart" aria-label={ariaLabel ?? `Counts by ${unit ?? "category"}`}>
      {data.map((d) => (
        <li key={d.id} className="count-bar-row">
          <span className="count-bar-label">{d.label}</span>
          <span className="count-bar-track">
            <span
              className="count-bar-fill"
              style={{ width: `${Math.max(0, Math.min(100, (d.value / max) * 100))}%` }}
            />
          </span>
          <span className="count-bar-value">{formatValue ? formatValue(d.value) : d.value.toLocaleString("en-US")}</span>
        </li>
      ))}
    </ul>
  );
}
