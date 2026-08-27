"use client";

/** Colour stops mirror the existing status-tone palette used across the app
 * (critical/warning/success) so the gauge reads consistently with badges
 * and metric cards elsewhere. */
function toneForScore(score: number, invert: boolean): { color: string; label: string } {
  const effective = invert ? 100 - score : score;
  if (effective >= 75) return { color: "#b42318", label: invert ? "Excellent" : "Critical" };
  if (effective >= 50) return { color: "#c26400", label: invert ? "Good" : "High" };
  if (effective >= 25) return { color: "#8a6100", label: invert ? "Fair" : "Medium" };
  return { color: "#107c10", label: invert ? "Needs attention" : "Low" };
}

export interface RiskGaugeProps {
  /** 0-100 score, matching the scale the risk engines already emit. */
  score: number;
  label?: string;
  detail?: string;
  /** When true, a higher score is better (e.g. a compliance posture score)
   * instead of worse (e.g. a risk score) — flips both the colour bands and
   * the tone label so the gauge still reads correctly at a glance. */
  invert?: boolean;
}

/** A semicircular arc gauge for a 0-100 score. Pure SVG, no charting
 * library required — reads the same score already returned by the predeploy,
 * patch, lifecycle, and compliance posture engines, just rendered visually
 * instead of as a bare number in a table cell. */
export function RiskGauge({ score, label = "Risk score", detail, invert = false }: RiskGaugeProps) {
  const clamped = Math.max(0, Math.min(100, score));
  const tone = toneForScore(clamped, invert);

  // Semicircle from 180deg (left) to 0deg (right) over a 120-radius arc.
  const radius = 70;
  const cx = 90;
  const cy = 90;
  const angle = Math.PI * (1 - clamped / 100);
  const needleX = cx + radius * Math.cos(angle);
  const needleY = cy - radius * Math.sin(angle);
  const arcLength = Math.PI * radius;
  const dash = (clamped / 100) * arcLength;

  return (
    <div className="risk-gauge">
      <svg viewBox="0 0 180 100" className="risk-gauge-svg" role="img" aria-label={`${label}: ${clamped} out of 100, ${tone.label}`}>
        <path
          d={`M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={14}
          strokeLinecap="round"
        />
        <path
          d={`M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`}
          fill="none"
          stroke={tone.color}
          strokeWidth={14}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${arcLength - dash}`}
          className="risk-gauge-arc"
        />
        <line x1={cx} y1={cy} x2={needleX} y2={needleY} stroke="var(--color-text)" strokeWidth={3} strokeLinecap="round" />
        <circle cx={cx} cy={cy} r={5} fill="var(--color-text)" />
      </svg>
      <div className="risk-gauge-readout">
        <span className="risk-gauge-value" style={{ color: tone.color }}>
          {clamped}
        </span>
        <span className="risk-gauge-label">
          {label} · {tone.label}
        </span>
        {detail && <span className="risk-gauge-detail">{detail}</span>}
      </div>
    </div>
  );
}
