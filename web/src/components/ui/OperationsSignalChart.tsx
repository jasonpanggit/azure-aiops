"use client";

export interface OperationsSignal {
  label: string;
  value: number;
  tone: "critical" | "warning" | "success" | "info";
}

const COLORS = {
  critical: "var(--color-critical)",
  warning: "var(--color-warning)",
  success: "var(--color-success)",
  info: "var(--color-info)",
};

/** Compact, accessible bar visualization for high-signal counts already returned by the API. */
export function OperationsSignalChart({ signals }: { signals: OperationsSignal[] }) {
  const maxValue = Math.max(1, ...signals.map((signal) => signal.value));
  if (signals.every((signal) => signal.value === 0)) {
    return <p className="chart-empty">No elevated signals in this scope.</p>;
  }

  return (
    <div className="operations-chart" role="img" aria-label="Operational signal counts">
      <div className="operations-chart-bars">
        {signals.map((signal) => (
          <div className="operations-chart-row" key={signal.label}>
            <div className="operations-chart-label"><span>{signal.label}</span><strong>{signal.value}</strong></div>
            <div className="operations-chart-track" aria-hidden="true">
              <span style={{ width: `${(signal.value / maxValue) * 100}%`, background: COLORS[signal.tone] }} />
            </div>
          </div>
        ))}
      </div>
      <div className="chart-caption">Current signals · selected operating scope</div>
    </div>
  );
}

/** Compact coverage ring that turns connection health into a glanceable composition. */
export function CoverageDonut({ healthy, needsAttention }: { healthy: number; needsAttention: number }) {
  const total = healthy + needsAttention;
  if (total === 0) return <p className="chart-empty">No connection coverage in this scope.</p>;

  const healthyRatio = healthy / total;
  const circumference = 2 * Math.PI * 42;
  const healthyDash = healthyRatio * circumference;

  const attentionLabel = `${needsAttention} connection${needsAttention === 1 ? "" : "s"} needing attention`;
  return (
    <div className="coverage-chart" role="img" aria-label={`${healthy} healthy connection${healthy === 1 ? "" : "s"} and ${attentionLabel}`}>
      <div className="coverage-chart-graphic">
        <svg viewBox="0 0 110 110" className="coverage-chart-svg" aria-hidden="true">
          <circle cx="55" cy="55" r="42" fill="none" stroke="var(--color-warning-subtle)" strokeWidth="13" />
          <circle
            cx="55"
            cy="55"
            r="42"
            fill="none"
            stroke="var(--color-success)"
            strokeWidth="13"
            strokeDasharray={`${healthyDash} ${circumference - healthyDash}`}
            strokeLinecap="round"
            transform="rotate(-90 55 55)"
          />
        </svg>
        <div className="coverage-chart-total"><strong>{total}</strong><span>connections</span></div>
      </div>
      <div className="chart-legend">
        <div><span className="chart-legend-dot chart-legend-success" /><span>Healthy</span><strong>{healthy}</strong></div>
        <div><span className="chart-legend-dot chart-legend-warning" /><span>{attentionLabel}</span><strong>{needsAttention}</strong></div>
      </div>
    </div>
  );
}
