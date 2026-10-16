/** Supported server-composed evidence kinds; capture never accepts client JSON. */
export const AUDIT_CAPTURE_KINDS = [
  "subscription_onboarding", "network_design", "firewall_nsg",
  "vulnerability_exposure", "identity", "remediation", "executive",
] as const;
export type AuditCaptureKind = (typeof AUDIT_CAPTURE_KINDS)[number];

export interface AuditCaptureManifest {
  export_id: string;
  kind: AuditCaptureKind;
  captured_at: string;
  generated_at: string;
  observed_at: string;
  sha256: string;
  size_bytes: number;
  warning_count: number;
}

export interface AuditCaptureCollection {
  schema_version: 1;
  actor: string;
  scope: Record<string, string[]>;
  revision: number;
  captures: AuditCaptureManifest[];
  redaction: "standard_secret_keys";
}

export interface AuditCaptureDetail {
  manifest: AuditCaptureManifest;
  content: string;
  redaction: "standard_secret_keys";
}

/** Verify the exact UTF-8 download, not a reserialized preview or storage wrapper. */
export async function verifyAuditCapture(detail: AuditCaptureDetail): Promise<void> {
  const bytes = new TextEncoder().encode(detail.content);
  if (bytes.byteLength !== detail.manifest.size_bytes || bytes.byteLength > 512 * 1024) {
    throw new Error("Retained content byte count does not match its manifest. Download is disabled.");
  }
  if (!globalThis.crypto?.subtle) {
    throw new Error("This browser cannot verify SHA-256 here. Download is disabled.");
  }
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  const actual = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  if (actual !== detail.manifest.sha256) {
    throw new Error("Retained content checksum does not match its manifest. Download is disabled.");
  }
}
