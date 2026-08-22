/** Converts a machine-readable key into an operator-friendly label. */
export function titleize(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

/** Formats an ISO timestamp for compact operational surfaces. */
export function formatDateTime(value?: string | null): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

/** Describes how recently an ISO timestamp occurred. */
export function relativeTime(value?: string | null): string {
  if (!value) return "Freshness unknown";
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return value;
  const minutes = Math.round((timestamp - Date.now()) / 60_000);
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return formatter.format(hours, "hour");
  return formatter.format(Math.round(hours / 24), "day");
}

/** Shortens Azure resource IDs without losing the recognizable resource name. */
export function compactResourceId(value: string): string {
  if (!value.startsWith("/subscriptions/")) return value;
  const segments = value.split("/").filter(Boolean);
  return segments.length > 4 ? `…/${segments.slice(-4).join("/")}` : value;
}

/** Returns a presentable string for unknown API scalar values. */
export function formatScalar(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not available";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return new Intl.NumberFormat("en").format(value);
  return compactResourceId(String(value));
}
