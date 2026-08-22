import { formatScalar, titleize } from "@/lib/format";
import { StatusBadge, statusTone } from "./StatusBadge";

export interface StructuredDataProps {
  value: unknown;
  depth?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function Scalar({ value }: { value: unknown }) {
  if (typeof value === "string") {
    const tone = statusTone(value);
    if (tone !== "neutral") return <StatusBadge label={titleize(value)} tone={tone} compact />;
  }
  return <span>{formatScalar(value)}</span>;
}

/** Renders arbitrary API data as readable sections, lists, and key-value rows instead of raw JSON. */
export function StructuredData({ value, depth = 0 }: StructuredDataProps) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="muted">None reported</span>;
    return (
      <div className="structured-list">
        {value.map((item, index) => (
          <div className="structured-list-item" key={isRecord(item) ? String(item.id ?? item.name ?? index) : index}>
            <StructuredData value={item} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }

  if (isRecord(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) return <span className="muted">No details available</span>;
    return (
      <dl className={depth === 0 ? "structured-data" : "structured-data structured-data-nested"}>
        {entries.map(([key, item]) => (
          <div className="structured-row" key={key}>
            <dt>{titleize(key)}</dt>
            <dd>
              {Array.isArray(item) || isRecord(item) ? (
                <StructuredData value={item} depth={depth + 1} />
              ) : (
                <Scalar value={item} />
              )}
            </dd>
          </div>
        ))}
      </dl>
    );
  }

  return <Scalar value={value} />;
}
