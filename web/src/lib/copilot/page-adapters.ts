import type { ScopeSelection } from "@/lib/scope";
import * as services from "@/lib/services";
import type {
  CanonicalCopilotRequest,
  CollectionCoverage,
  ComplianceDeviation,
  CopilotEntityRef,
  CopilotEvidenceIdentity,
  CopilotEvidenceSnapshotV2 as StrictCopilotEvidenceSnapshotV2,
  CopilotFreshnessStatusV2,
  CopilotPageKind,
  CopilotPageKindV2,
  CopilotPageSnapshot,
  CopilotSnapshotStatus,
  CopilotSnapshotEvidenceV2,
  CopilotSnapshotStatusV2,
  DurableSituation,
  Envelope,
  EvidenceItem,
  NetworkGap,
  NetworkSummary,
  NetworkTopology,
  RuleFinding,
  SubscriptionConnection,
  VulnerabilitySummary,
} from "@/lib/types";

export type {
  CanonicalCopilotCitation,
  CanonicalCopilotRequest,
  CanonicalCopilotResult,
} from "@/lib/types";

export type CopilotPageDisposition = "integrated" | "deferred" | "excluded";

interface LegacyCopilotSnapshotEvidenceV2 {
  evidence_id: string;
  source: string;
  status: CopilotSnapshotStatusV2;
  observed_at: string;
  resource_id: string;
  data: Record<string, unknown>;
}

interface LegacyCopilotEvidenceSnapshotV2 {
  version: "2";
  page_kind: "inventory";
  page_id: string;
  coverage: StrictCopilotEvidenceSnapshotV2["coverage"];
  freshness: StrictCopilotEvidenceSnapshotV2["freshness"];
  evidence: LegacyCopilotSnapshotEvidenceV2[];
}

/** Adapter-facing snapshot type with compatibility for pre-v2 drawer fixtures. */
export type CopilotEvidenceSnapshotV2 =
  | StrictCopilotEvidenceSnapshotV2
  | LegacyCopilotEvidenceSnapshotV2;

export const COPILOT_SNAPSHOT_LIMITS = {
  snapshotBytes: 128 * 1024,
  selectedEntities: 50,
  evidenceRows: 200,
  evidenceRowBytes: 8 * 1024,
  freshnessRecords: 32,
  evidenceCitations: 32,
  materialClaims: 200,
} as const;

export interface InventoryCopilotRecord {
  identity: string;
  kind: "os_group" | "software_group" | "azure_group";
  source: string;
  observedAt?: string;
  resourceId?: string;
  status?: CopilotSnapshotStatusV2;
  data: Record<string, unknown>;
}

export interface InventorySourceObservation {
  source: string;
  observedAt?: string;
  status: string;
}

export interface InventoryCopilotAdapterInput {
  scope: ScopeSelection;
  tab: "os" | "software" | "azure";
  filters: Record<string, string>;
  sort?: Record<string, "asc" | "desc">;
  records: InventoryCopilotRecord[];
  selectedIdentity?: string | null;
  totalCount: number;
  offset?: number;
  limit?: number;
  observedAt?: string;
  sourceStatuses: InventorySourceObservation[];
}

export interface InventoryCopilotContext {
  disposition: "integrated";
  requestedScope: ScopeSelection;
  snapshot: StrictCopilotEvidenceSnapshotV2;
  uncertainty: string[];
  starterQuestions: Array<{
    label: string;
    specialistId: string;
    tool: string;
    toolArguments: Record<string, unknown>;
  }>;
}

interface StableEvidenceIdentity {
  source: string;
  sourceKey: string;
  entity: CopilotEvidenceIdentity;
  claimType: string;
}

type InventorySnapshotEvidence = CopilotSnapshotEvidenceV2 & {
  source_key: string;
  entity: CopilotEvidenceIdentity;
  claim_type: string;
  citations: string[];
  selected: boolean;
  direct: boolean;
  actionable: boolean;
  severity: CopilotSnapshotEvidenceV2["severity"];
  quality: CopilotSnapshotEvidenceV2["quality"];
};

/** The exact manifest-backed v2 page kind on which an integrated route anchors. */
export type CopilotRouteAnchorPageKind = CopilotPageKindV2;

/** Exactly one reviewed Copilot disposition per Next.js route (D-03, locked page policy). */
export type CopilotRouteDisposition =
  | { kind: "integrated"; pageKind: CopilotRouteAnchorPageKind }
  | { kind: "dedicated"; surface: string }
  | { kind: "redirect"; target: string }
  | { kind: "excluded"; reason: string };

/**
 * Exhaustive disposition for all 28 reviewed routes.
 *
 * The Plan 11-16 filesystem gate compares these keys to
 * `web/src/app/**\/page.tsx` so no route can ship without exactly one reviewed
 * disposition, and the manifest-parity gate reads each integrated `pageKind`
 * as the route's authoritative specialist anchor (D-03, D-05, D-06). Every
 * integrated `pageKind` mirrors the page kind its adapter emits, and each is a
 * key in the versioned specialist manifest's page mapping.
 */
export const COPILOT_ROUTE_DISPOSITIONS: Record<string, CopilotRouteDisposition> = {
  // 23 integrated routes -- each renders the shared CopilotDrawerButton and a
  // typed page adapter over already-loaded, authorized evidence.
  "/": { kind: "integrated", pageKind: "overview" },
  "/network": { kind: "integrated", pageKind: "network" },
  "/compliance": { kind: "integrated", pageKind: "compliance" },
  "/exposure": { kind: "integrated", pageKind: "exposure" },
  "/exposure/cves/[id]": { kind: "integrated", pageKind: "cve_detail" },
  "/exposure/defender-posture": { kind: "integrated", pageKind: "defender_posture" },
  "/exposure/kbs/[id]": { kind: "integrated", pageKind: "kb_detail" },
  "/exposure/patch-priorities": { kind: "integrated", pageKind: "patch_priorities" },
  "/situations": { kind: "integrated", pageKind: "situations" },
  "/situations/[id]": { kind: "integrated", pageKind: "situation_detail" },
  "/changes": { kind: "integrated", pageKind: "changes" },
  "/changes/predeploy": { kind: "integrated", pageKind: "changes_predeploy" },
  "/inventory": { kind: "integrated", pageKind: "inventory" },
  "/connections": { kind: "integrated", pageKind: "connections" },
  "/connections/fabric": { kind: "integrated", pageKind: "connections_fabric" },
  "/governance": { kind: "integrated", pageKind: "governance" },
  "/identity": { kind: "integrated", pageKind: "identity" },
  "/finops": { kind: "integrated", pageKind: "finops" },
  "/remediation": { kind: "integrated", pageKind: "remediation" },
  "/resource-health": { kind: "integrated", pageKind: "resource_health" },
  "/services": { kind: "integrated", pageKind: "services" },
  "/services/[name]": { kind: "integrated", pageKind: "service_detail" },
  "/twin": { kind: "integrated", pageKind: "twin" },
  // 3 dedicated Copilot/investigation surfaces -- they are the reasoning
  // destination itself and never embed a second contextual launcher.
  "/copilot": { kind: "dedicated", surface: "operations-copilot" },
  "/investigate": { kind: "dedicated", surface: "guided-investigation" },
  "/agents": { kind: "dedicated", surface: "multi-agent-investigation" },
  // 1 redirect -- the legacy collection alias is consolidated into Patch priorities.
  "/vulnerabilities": { kind: "redirect", target: "/exposure/patch-priorities" },
  // 1 excluded -- pure navigation/query aggregation with no stable retained
  // evidence snapshot contract in Phase 11.
  "/search": {
    kind: "excluded",
    reason:
      "Navigation and query aggregation only; Phase 11 defines no stable retained evidence snapshot contract for search results, so results deep-link to eligible detail pages instead of being carried as Copilot evidence.",
  },
};

const SHA256_CONSTANTS = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
  0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
  0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
  0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
  0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
  0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
] as const;

const STATUS_WARNING_PRIORITY: Record<CopilotSnapshotStatusV2, number> = {
  ok: 0,
  empty: 1,
  partial: 2,
  unavailable: 3,
  denied: 4,
};

const FRESHNESS_WARNING_PRIORITY: Record<CopilotFreshnessStatusV2, number> = {
  fresh: 0,
  partial: 1,
  stale: 2,
  unavailable: 3,
};

const INVENTORY_EVIDENCE_SOURCES = {
  os: "inventory/os_observations",
  software: "inventory/software_observations",
  azure: "inventory/resource_observations",
} as const;

const PYTHON_312_UNCASED_CODE_POINTS = new Set([
  0x1c89,
  0xa7cb,
  0xa7cc,
  0xa7ce,
  0xa7d2,
  0xa7d4,
  0xa7da,
  0xa7dc,
]);

/** Returns the reviewed Copilot integration disposition for a route. */
export function copilotPageDisposition(pathname: string): CopilotPageDisposition {
  const disposition = COPILOT_ROUTE_DISPOSITIONS[pathname];
  if (!disposition) return "deferred";
  if (disposition.kind === "integrated") return "integrated";
  if (disposition.kind === "excluded") return "excluded";
  // Dedicated surfaces and redirects have no embedded contextual adapter.
  return "deferred";
}

/** Compatibility entry point for the canonical API client now owned by services. */
export function investigateCanonical(
  request: Omit<CanonicalCopilotRequest, "snapshot"> & {
    snapshot: CopilotEvidenceSnapshotV2;
  },
  scope: ScopeSelection,
) {
  if (!isStrictSnapshot(request.snapshot)) {
    throw new Error("canonical requests require the complete snapshot v2 contract");
  }
  return services.investigateCanonical({ ...request, snapshot: request.snapshot }, scope);
}

function isStrictSnapshot(
  snapshot: CopilotEvidenceSnapshotV2,
): snapshot is StrictCopilotEvidenceSnapshotV2 {
  return (
    "selected_entities" in snapshot
    && Array.isArray(snapshot.selected_entities)
    && "material_claims" in snapshot
    && Array.isArray(snapshot.material_claims)
    && snapshot.evidence.every((item) =>
      "source_key" in item
      && "entity" in item
      && "claim_type" in item
      && "citations" in item
      && "selected" in item
      && "direct" in item
      && "actionable" in item
      && "severity" in item
      && "quality" in item)
  );
}

function rotateRight(value: number, count: number): number {
  return (value >>> count) | (value << (32 - count));
}

function compareCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left, (character) => character.codePointAt(0) ?? 0);
  const rightPoints = Array.from(right, (character) => character.codePointAt(0) ?? 0);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index] < rightPoints[index] ? -1 : 1;
    }
  }
  return leftPoints.length - rightPoints.length;
}

function sha256(value: string): string {
  const bytes = new TextEncoder().encode(value);
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  const bitLength = bytes.length * 8;
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000));
  view.setUint32(paddedLength - 4, bitLength >>> 0);

  const hash = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const words = new Uint32Array(64);

  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(offset + index * 4);
    }
    for (let index = 16; index < 64; index += 1) {
      const left = words[index - 15];
      const right = words[index - 2];
      const sigma0 = rotateRight(left, 7) ^ rotateRight(left, 18) ^ (left >>> 3);
      const sigma1 = rotateRight(right, 17) ^ rotateRight(right, 19) ^ (right >>> 10);
      words[index] = (words[index - 16] + sigma0 + words[index - 7] + sigma1) >>> 0;
    }

    let a = hash[0];
    let b = hash[1];
    let c = hash[2];
    let d = hash[3];
    let e = hash[4];
    let f = hash[5];
    let g = hash[6];
    let h = hash[7];
    for (let index = 0; index < 64; index += 1) {
      const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choice = (e & f) ^ (~e & g);
      const temp1 = (h + sum1 + choice + SHA256_CONSTANTS[index] + words[index]) >>> 0;
      const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (sum0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temp1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temp1 + temp2) >>> 0;
    }

    hash[0] = (hash[0] + a) >>> 0;
    hash[1] = (hash[1] + b) >>> 0;
    hash[2] = (hash[2] + c) >>> 0;
    hash[3] = (hash[3] + d) >>> 0;
    hash[4] = (hash[4] + e) >>> 0;
    hash[5] = (hash[5] + f) >>> 0;
    hash[6] = (hash[6] + g) >>> 0;
    hash[7] = (hash[7] + h) >>> 0;
  }

  return Array.from(hash, (part) => part.toString(16).padStart(8, "0")).join("");
}

function unicodeCaseFold(value: string): string {
  return Array.from(value, (character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    if (
      PYTHON_312_UNCASED_CODE_POINTS.has(codePoint)
      || (codePoint >= 0x10d50 && codePoint <= 0x10d65)
      || (codePoint >= 0x16ea0 && codePoint <= 0x16eb8)
    ) {
      return character;
    }
    if (codePoint === 0x0131) return character;
    if (codePoint === 0x1e9e) return "ss";
    if (
      (codePoint >= 0x13a0 && codePoint <= 0x13ef)
      || (codePoint >= 0x13f0 && codePoint <= 0x13f5)
    ) {
      return character;
    }
    if (codePoint >= 0xab70 && codePoint <= 0xabbf) {
      return String.fromCodePoint(codePoint - 0x97d0);
    }
    if (codePoint >= 0x13f8 && codePoint <= 0x13fd) {
      return String.fromCodePoint(codePoint - 8);
    }
    return character.toUpperCase().toLowerCase();
  }).join("");
}

function normalizedIdentityPart(value: string): string {
  const compact = value.trim().split(/\s+/).filter(Boolean).join(" ");
  return unicodeCaseFold(compact);
}

function canonicalResourceId(resourceId: string): string {
  const trimmed = resourceId.trim();
  const parts = trimmed.split("/").filter(Boolean);
  if (
    !trimmed.startsWith("/")
    || parts[0]?.toLowerCase() !== "subscriptions"
    || !parts[1]
  ) {
    throw new Error("Azure entities require canonical ARM resource IDs");
  }
  if (Array.from(trimmed).length > 512) {
    throw new Error("Azure resource ID exceeds limit of 512");
  }
  const canonical = `/${parts.map(unicodeCaseFold).join("/")}`;
  if (Array.from(canonical).length > 512) {
    throw new Error("canonical Azure resource ID exceeds limit of 512");
  }
  return canonical;
}

function entityKey(entity: CopilotEvidenceIdentity): string {
  if (entity.type === "azure") {
    return `azure:${canonicalResourceId(entity.resource_id)}`;
  }
  if (entity.type === "observation") {
    return [
      "observation",
      normalizedIdentityPart(entity.source),
      normalizedIdentityPart(entity.source_key),
    ].join(":");
  }
  return [
    "domain",
    normalizedIdentityPart(entity.namespace),
    normalizedIdentityPart(entity.kind),
    normalizedIdentityPart(entity.source_key),
  ].join(":");
}

function asciiJson(value: unknown): string {
  return JSON.stringify(value).replace(
    /[\u007f-\uffff]/g,
    (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`,
  );
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item ?? null)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value)
      .filter(([, item]) => item !== undefined)
      .sort(([left], [right]) => compareCodePoints(left, right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/** Builds the stable evidence identity used by the backend canonicalizer. */
export function canonicalEvidenceStableId(identity: StableEvidenceIdentity): string {
  const encoded = asciiJson([
    normalizedIdentityPart(identity.source),
    normalizedIdentityPart(identity.sourceKey),
    entityKey(identity.entity),
    normalizedIdentityPart(identity.claimType),
  ]);
  return `evidence:${sha256(encoded).slice(0, 32)}`;
}

/** Serializes a snapshot with stable object-key and adapter-controlled list ordering. */
export function serializeCopilotSnapshot(snapshot: StrictCopilotEvidenceSnapshotV2): string {
  return stableJson(snapshot);
}

const SNAPSHOT_V2_PAGE_KINDS = new Set<CopilotPageKindV2>([
  "overview",
  "network",
  "vulnerability",
  "patch",
  "incident",
  "compliance",
  "exposure",
  "cve_detail",
  "defender_posture",
  "kb_detail",
  "patch_priorities",
  "situations",
  "situation_detail",
  "changes",
  "changes_predeploy",
  "inventory",
  "connections",
  "connections_fabric",
  "governance",
  "identity",
  "finops",
  "remediation",
  "resource_health",
  "resource",
  "services",
  "service_detail",
  "twin",
  "copilot",
  "investigate",
  "agents",
]);
const SNAPSHOT_EVIDENCE_ID = /^[A-Za-z0-9._:-]+$/;
const SNAPSHOT_DOMAIN_PART = /^[A-Za-z0-9._-]+$/;

function exactKeys(
  name: string,
  value: object,
  expected: readonly string[],
  optional: readonly string[] = [],
): void {
  const allowed = new Set(expected);
  const actual = Object.keys(value);
  const unknown = actual.filter((key) => !allowed.has(key));
  const optionalKeys = new Set(optional);
  const missing = expected.filter(
    (key) => !optionalKeys.has(key) && !actual.includes(key),
  );
  if (unknown.length || missing.length) {
    throw new Error(
      `${name} has invalid fields: ${[...unknown, ...missing].sort().join(", ")}`,
    );
  }
}

function boundedSnapshotString(
  name: string,
  value: unknown,
  minimum: number,
  maximum: number,
  pattern?: RegExp,
): string {
  if (typeof value !== "string") throw new Error(`${name} must be a string`);
  const normalized = value.trim();
  const length = Array.from(normalized).length;
  if (length < minimum || length > maximum || (pattern && !pattern.test(normalized))) {
    throw new Error(`${name} must contain between ${minimum} and ${maximum} valid characters`);
  }
  return normalized;
}

function finiteJsonValue(value: unknown, seen = new Set<object>()): void {
  if (typeof value === "number" && !Number.isFinite(value)) {
    throw new Error("snapshot data contains a non-finite number");
  }
  if (typeof value === "bigint" || typeof value === "function" || typeof value === "symbol") {
    throw new Error("snapshot data is not JSON-compatible");
  }
  if (!value || typeof value !== "object") return;
  if (seen.has(value)) throw new Error("snapshot data contains a cycle");
  seen.add(value);
  for (const item of Array.isArray(value) ? value : Object.values(value)) {
    finiteJsonValue(item, seen);
  }
  seen.delete(value);
}

function normalizedData(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("snapshot evidence data must be an object");
  }
  finiteJsonValue(value);
  const serialized = JSON.stringify(value);
  if (serialized === undefined) {
    throw new Error("snapshot evidence data is not JSON-compatible");
  }
  return JSON.parse(serialized) as Record<string, unknown>;
}

function normalizedSnapshotEntity(value: unknown): CopilotEvidenceIdentity {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("snapshot entity must be an object");
  }
  const record = value as Record<string, unknown>;
  if (record.type === "azure") {
    exactKeys("Azure snapshot entity", record, ["type", "resource_id"]);
    return {
      type: "azure",
      resource_id: canonicalResourceId(
        boundedSnapshotString("Azure resource ID", record.resource_id, 1, 512),
      ),
    };
  }
  if (record.type === "domain") {
    exactKeys("domain snapshot entity", record, [
      "type",
      "namespace",
      "kind",
      "source_key",
    ]);
    const sourceKey = boundedSnapshotString(
      "domain source key",
      record.source_key,
      1,
      256,
    );
    if (/[\0\r\n]/.test(sourceKey)) {
      throw new Error("domain source key contains an invalid control character");
    }
    return {
      type: "domain",
      namespace: boundedSnapshotString(
        "domain namespace",
        record.namespace,
        1,
        64,
        SNAPSHOT_DOMAIN_PART,
      ),
      kind: boundedSnapshotString(
        "domain kind",
        record.kind,
        1,
        80,
        SNAPSHOT_DOMAIN_PART,
      ),
      source_key: sourceKey,
    };
  }
  if (record.type === "observation") {
    exactKeys("observation snapshot identity", record, [
      "type",
      "source",
      "source_key",
    ]);
    const sourceKey = boundedSnapshotString(
      "observation source key",
      record.source_key,
      1,
      256,
    );
    if (/[\0\r\n]/.test(sourceKey)) {
      throw new Error("observation source key contains an invalid control character");
    }
    return {
      type: "observation",
      source: boundedSnapshotString(
        "observation source",
        record.source,
        1,
        128,
      ),
      source_key: sourceKey,
    };
  }
  throw new Error("snapshot entity type is invalid");
}

function normalizeStrictSnapshotV2(
  snapshot: StrictCopilotEvidenceSnapshotV2,
): StrictCopilotEvidenceSnapshotV2 {
  exactKeys("snapshot", snapshot, [
    "version",
    "page_kind",
    "page_id",
    "filters",
    "query",
    "generation_id",
    "coverage",
    "freshness",
    "selected_entities",
    "evidence",
    "material_claims",
  ], ["filters", "query", "generation_id"]);
  if (snapshot.version !== "2" || !SNAPSHOT_V2_PAGE_KINDS.has(snapshot.page_kind)) {
    throw new Error("snapshot version or page kind is invalid");
  }
  const pageId = boundedSnapshotString("snapshot page ID", snapshot.page_id, 1, 128);
  exactKeys("snapshot coverage", snapshot.coverage, [
    "visible_count",
    "total_count",
    "complete",
  ]);
  const { visible_count: visibleCount, total_count: totalCount, complete } = snapshot.coverage;
  if (
    !Number.isSafeInteger(visibleCount)
    || !Number.isSafeInteger(totalCount)
    || visibleCount < 0
    || totalCount < 0
    || visibleCount > 1_000_000
    || totalCount > 1_000_000
    || visibleCount > totalCount
    || (complete && visibleCount !== totalCount)
  ) {
    throw new Error("snapshot coverage is invalid");
  }
  assertBound(
    "freshness records",
    snapshot.freshness.length,
    COPILOT_SNAPSHOT_LIMITS.freshnessRecords,
  );
  const freshness = snapshot.freshness.map((item) => {
    exactKeys("snapshot freshness", item, ["source", "observed_at", "status"]);
    if (!["fresh", "stale", "partial", "unavailable"].includes(item.status)) {
      throw new Error("snapshot freshness status is invalid");
    }
    return {
      source: boundedSnapshotString("freshness source", item.source, 1, 128),
      observed_at: boundedSnapshotString(
        "freshness observation time",
        item.observed_at,
        1,
        128,
      ),
      status: item.status,
    };
  }).sort((left, right) =>
    compareCodePoints(
      stableJson([left.source, left.observed_at, left.status]),
      stableJson([right.source, right.observed_at, right.status]),
    ));
  assertBound(
    "selected entities",
    snapshot.selected_entities.length,
    COPILOT_SNAPSHOT_LIMITS.selectedEntities,
  );
  const selectedEntities = snapshot.selected_entities
    .map((value) => {
      const entity = normalizedSnapshotEntity(value);
      if (entity.type === "observation") {
        throw new Error("selected snapshot identities must be domain or Azure entities");
      }
      return entity;
    })
    .sort((left, right) =>
      compareCodePoints(entityOrderingKey(left), entityOrderingKey(right)));
  if (
    new Set(selectedEntities.map(entityOrderingKey)).size
    !== selectedEntities.length
  ) {
    throw new Error("snapshot selected entities must be unique");
  }
  assertBound(
    "evidence rows",
    snapshot.evidence.length,
    COPILOT_SNAPSHOT_LIMITS.evidenceRows,
  );
  const evidence = snapshot.evidence.map((item) => {
    exactKeys("snapshot evidence", item, [
      "evidence_id",
      "source",
      "status",
      "observed_at",
      "resource_id",
      "source_key",
      "entity",
      "claim_type",
      "citations",
      "selected",
      "direct",
      "actionable",
      "severity",
      "quality",
      "data",
    ]);
    const evidenceId = boundedSnapshotString(
      "evidence ID",
      item.evidence_id,
      1,
      160,
      SNAPSHOT_EVIDENCE_ID,
    );
    if (/^(snapshot|tool):/i.test(evidenceId)) {
      throw new Error("snapshot evidence ID uses a reserved citation namespace");
    }
    const sourceKey = boundedSnapshotString(
      "evidence source key",
      item.source_key,
      0,
      256,
    );
    if (/[\0\r\n]/.test(sourceKey)) {
      throw new Error("evidence source key contains an invalid control character");
    }
    assertBound(
      "evidence citations",
      item.citations.length,
      COPILOT_SNAPSHOT_LIMITS.evidenceCitations,
    );
    const citations = item.citations.map((citation) => {
      const normalized = boundedSnapshotString(
        "evidence citation",
        citation,
        1,
        200,
      );
      if (/[\0\r\n]/.test(normalized)) {
        throw new Error("snapshot evidence citation is invalid");
      }
      return normalized;
    });
    if (new Set(citations).size !== citations.length) {
      throw new Error("snapshot evidence citations must be unique");
    }
    if (!["ok", "empty", "partial", "unavailable", "denied"].includes(item.status)) {
      throw new Error("snapshot evidence status is invalid");
    }
    if (!["unknown", "low", "medium", "high", "critical"].includes(item.severity)) {
      throw new Error("snapshot evidence severity is invalid");
    }
    if (!["unknown", "low", "medium", "high"].includes(item.quality)) {
      throw new Error("snapshot evidence quality is invalid");
    }
    const data = normalizedData(item.data);
    assertEvidenceRowBound(data);
    return {
      evidence_id: evidenceId,
      source: boundedSnapshotString("evidence source", item.source, 1, 128),
      status: item.status,
      observed_at: boundedSnapshotString(
        "evidence observation time",
        item.observed_at,
        0,
        128,
      ),
      resource_id: boundedSnapshotString(
        "evidence resource ID",
        item.resource_id,
        0,
        512,
      ),
      source_key: sourceKey,
      entity: normalizedSnapshotEntity(item.entity),
      claim_type: boundedSnapshotString(
        "evidence claim type",
        item.claim_type,
        1,
        128,
      ),
      citations,
      selected: Boolean(item.selected),
      direct: Boolean(item.direct),
      actionable: Boolean(item.actionable),
      severity: item.severity,
      quality: item.quality,
      data,
    };
  }).sort((left, right) => compareCodePoints(left.evidence_id, right.evidence_id));
  const evidenceIds = new Set(evidence.map((item) => item.evidence_id));
  if (evidenceIds.size !== evidence.length) {
    throw new Error("snapshot evidence IDs must be unique");
  }
  assertBound(
    "material claims",
    snapshot.material_claims.length,
    COPILOT_SNAPSHOT_LIMITS.materialClaims,
  );
  const materialClaims = snapshot.material_claims.map((claim) => {
    exactKeys("snapshot material claim", claim, [
      "claim_id",
      "evidence_refs",
      "requires_complete_coverage",
    ]);
    if (claim.evidence_refs.length < 1 || claim.evidence_refs.length > 32) {
      throw new Error("material claim evidence references are outside bounds");
    }
    const evidenceRefs = claim.evidence_refs.map((reference) =>
      boundedSnapshotString(
        "material claim evidence reference",
        reference,
        1,
        160,
        SNAPSHOT_EVIDENCE_ID,
      ));
    if (evidenceRefs.some((reference) => !evidenceIds.has(reference))) {
      throw new Error("material claim has a missing evidence reference");
    }
    return {
      claim_id: boundedSnapshotString(
        "material claim ID",
        claim.claim_id,
        1,
        160,
        SNAPSHOT_EVIDENCE_ID,
      ),
      evidence_refs: Array.from(new Set(evidenceRefs)).sort(compareCodePoints),
      requires_complete_coverage: Boolean(claim.requires_complete_coverage),
    };
  }).sort((left, right) => compareCodePoints(left.claim_id, right.claim_id));
  const filters = normalizeFilters(snapshot.filters ?? {}, undefined);
  const query = boundedSnapshotString(
    "snapshot query",
    snapshot.query ?? filters.query?.join(" ") ?? "",
    0,
    1024,
  ).toLocaleLowerCase("en-US");
  const generationPayload = {
    coverage: {
      visible_count: visibleCount,
      total_count: totalCount,
      complete,
    },
    freshness,
    evidence,
    material_claims: materialClaims,
  };
  const normalized: StrictCopilotEvidenceSnapshotV2 = {
    version: "2",
    page_kind: snapshot.page_kind,
    page_id: pageId,
    filters,
    query,
    generation_id: `generation:${sha256(stableJson(generationPayload))}`,
    coverage: generationPayload.coverage,
    freshness,
    selected_entities: selectedEntities,
    evidence,
    material_claims: materialClaims,
  };
  assertBound(
    "snapshot",
    new TextEncoder().encode(serializeCopilotSnapshot(normalized)).length
      + numericValueCount(normalized),
    COPILOT_SNAPSHOT_LIMITS.snapshotBytes,
  );
  return normalized;
}

function legacySnapshotEntity(
  pageKind: CopilotPageKind,
  row: CopilotPageSnapshot["evidence"][number],
  sourceKey: string,
): CopilotEvidenceIdentity {
  if (row.data.entity !== undefined) {
    return normalizedSnapshotEntity(row.data.entity);
  }
  if (row.resource_id) {
    return {
      type: "azure",
      resource_id: canonicalResourceId(row.resource_id),
    };
  }
  return {
    type: "domain",
    namespace: "page",
    kind: pageKind,
    source_key: sourceKey,
  };
}

const LEGACY_PAGE_ID_KINDS: Readonly<Record<string, CopilotPageKindV2>> = {
  "operations-overview": "overview",
  "network-topology": "network",
  "compliance-posture": "compliance",
  exposure: "exposure",
  "defender-posture": "defender_posture",
  "patch-priorities": "patch_priorities",
  situations: "situations",
  changes: "changes",
  predeploy: "changes_predeploy",
  connections: "connections",
  "fabric-medallion": "connections_fabric",
  governance: "governance",
  identity: "identity",
  finops: "finops",
  remediation: "remediation",
  "resource-health": "resource_health",
  services: "services",
  twin: "twin",
};

function legacyPageKind(snapshot: CopilotPageSnapshot): CopilotPageKindV2 {
  if (snapshot.page_id.startsWith("cve:")) return "cve_detail";
  if (snapshot.page_id.startsWith("kb:")) return "kb_detail";
  if (snapshot.page_id.startsWith("situation:")) return "situation_detail";
  if (snapshot.page_id.startsWith("service:")) return "service_detail";
  if (snapshot.page_id === "inventory" || snapshot.page_id.startsWith("inventory:")) {
    return "inventory";
  }
  return LEGACY_PAGE_ID_KINDS[snapshot.page_id] ?? snapshot.page_kind;
}

function legacyObservedCoverage(
  snapshot: CopilotPageSnapshot,
): StrictCopilotEvidenceSnapshotV2["coverage"] {
  const observations = snapshot.evidence.flatMap((row) => {
    if (
      row.section !== "coverage"
      || row.data.claim_type !== "coverage"
      || !row.data.coverage
      || typeof row.data.coverage !== "object"
      || Array.isArray(row.data.coverage)
    ) {
      return [];
    }
    const coverage = row.data.coverage as Record<string, unknown>;
    const visibleCount = coverage.visible_count;
    const totalCount = coverage.total_count;
    const complete = coverage.complete;
    if (
      !Number.isSafeInteger(visibleCount)
      || !Number.isSafeInteger(totalCount)
      || typeof complete !== "boolean"
      || (visibleCount as number) < 0
      || (totalCount as number) < 0
      || (visibleCount as number) > (totalCount as number)
      || (complete && visibleCount !== totalCount)
    ) {
      throw new Error("legacy snapshot coverage observation is invalid");
    }
    return [{
      visible_count: visibleCount as number,
      total_count: totalCount as number,
      complete,
    }];
  });
  if (!observations.length) {
    return { visible_count: 0, total_count: 0, complete: false };
  }
  const visibleCount = observations.reduce(
    (total, item) => total + item.visible_count,
    0,
  );
  const totalCount = observations.reduce(
    (total, item) => total + item.total_count,
    0,
  );
  return {
    visible_count: visibleCount,
    total_count: totalCount,
    complete: observations.every((item) => item.complete)
      && visibleCount === totalCount,
  };
}

/**
 * Converts any integrated page snapshot to the one strict, bounded v2 wire
 * contract. Character limits use Unicode code points; row limits use the
 * backend-compatible escaped JSON byte count; structural limits reject N+1
 * rather than silently widening or dropping observations.
 */
export function normalizeCopilotSnapshotV2(
  snapshot: CopilotPageSnapshot | CopilotEvidenceSnapshotV2,
): StrictCopilotEvidenceSnapshotV2 {
  if (snapshot.version === "2") {
    if (!isStrictSnapshot(snapshot)) {
      throw new Error("canonical requests require the complete snapshot v2 contract");
    }
    return normalizeStrictSnapshotV2(snapshot);
  }

  const selectedEntities: CopilotEntityRef[] = snapshot.selected_resources.map((resource) => ({
    type: "azure" as const,
    resource_id: canonicalResourceId(resource.resource_id),
  }));
  const evidence = snapshot.evidence.map((row) => {
    const sourceKeyValue = typeof row.data.source_key === "string"
      ? row.data.source_key
      : row.evidence_id;
    const sourceKey = boundedSourceKey(sourceKeyValue);
    const entity = legacySnapshotEntity(snapshot.page_kind, row, sourceKey);
    if (row.data.selected === true && entity.type !== "observation") {
      selectedEntities.push(entity);
    }
    return {
      evidence_id: row.evidence_id,
      source: row.section,
      status: row.status,
      observed_at: row.observed_at ?? "",
      resource_id: entity.type === "azure" ? entity.resource_id : "",
      source_key: sourceKey,
      entity,
      claim_type: typeof row.data.claim_type === "string"
        ? row.data.claim_type
        : "observation",
      citations: [],
      selected: row.data.selected === true,
      direct: true,
      actionable: false,
      severity: "unknown" as const,
      quality: "unknown" as const,
      data: row.data,
    };
  });
  const deduplicatedSelected = selectedEntities.filter((entity, index, entities) =>
    entities.findIndex((candidate) =>
      entityOrderingKey(candidate) === entityOrderingKey(entity)) === index);
  const materialClaims = evidence
    .filter((item) => item.direct && ["ok", "partial"].includes(item.status))
    .map((item) => ({
      claim_id: `claim:${sha256(item.evidence_id).slice(0, 32)}`,
      evidence_refs: [item.evidence_id],
      requires_complete_coverage: false,
    }));
  return normalizeStrictSnapshotV2({
    version: "2",
    page_kind: legacyPageKind(snapshot),
    page_id: snapshot.page_id,
    filters: snapshot.filters,
    query: snapshot.filters.query?.join(" ") ?? "",
    coverage: legacyObservedCoverage(snapshot),
    freshness: snapshot.freshness,
    selected_entities: deduplicatedSelected,
    evidence,
    material_claims: materialClaims,
  });
}

function freshnessStatus(status: string): CopilotFreshnessStatusV2 {
  if (
    status === "ready"
    || status === "fresh"
    || status === "current"
    || status === "request_time"
    || status === "ok"
    || status === "available"
  ) return "fresh";
  if (status === "stale") return "stale";
  if (status === "partial" || status === "degraded") return "partial";
  return "unavailable";
}

function recordEntity(record: InventoryCopilotRecord): CopilotEntityRef {
  if (record.resourceId) {
    return {
      type: "azure",
      resource_id: canonicalResourceId(record.resourceId),
    };
  }
  return {
    type: "domain",
    namespace: "inventory",
    kind: record.kind,
    source_key: record.identity,
  };
}

function assertBound(name: string, actual: number, maximum: number): void {
  if (actual > maximum) {
    throw new Error(`${name} exceeds limit of ${maximum}`);
  }
}

function boundedString(
  name: string,
  value: string,
  minimum: number,
  maximum: number,
): string {
  const trimmed = value.trim();
  const length = Array.from(trimmed).length;
  if (length < minimum || length > maximum) {
    throw new Error(`${name} must contain between ${minimum} and ${maximum} characters`);
  }
  return trimmed;
}

function boundedSourceKey(value: string): string {
  const sourceKey = boundedString("source key", value, 1, 256);
  if (/[\0\r\n]/.test(sourceKey)) {
    throw new Error("source key contains an invalid control character");
  }
  return sourceKey;
}

function boundedCoreSourceKey(value: string): string {
  const sourceKey = value.trim();
  if (Array.from(sourceKey).length <= 160) return boundedSourceKey(sourceKey);
  if (/[\0\r\n]/.test(sourceKey)) {
    throw new Error("source key contains an invalid control character");
  }
  return `sha256:${sha256(asciiJson(sourceKey))}`;
}

function boundedFilterValue(name: string, value: string): string {
  const normalized = value.trim();
  if (!normalized) {
    throw new Error(`${name} must contain between 1 and 160 characters`);
  }
  if (/[\0\r\n]/.test(normalized)) {
    throw new Error(`${name} contains an invalid control character`);
  }
  return Array.from(normalized).length <= 160
    ? normalized
    : `sha256:${sha256(asciiJson(normalized))}`;
}

function boundedSelectorText(
  field: string,
  value: unknown,
  maximum = 120,
): string {
  const text = boundedString(`inventory selector ${field}`, String(value ?? ""), 1, maximum);
  if (/[\0\r\n]/.test(text)) {
    throw new Error(`inventory selector ${field} contains an invalid control character`);
  }
  return text;
}

function validateAssembledSelector(value: string): void {
  if (Array.from(value).length > 240) {
    throw new Error("inventory resource selector exceeds limit of 240");
  }
}

function validateSelectedInventorySelector(record: InventoryCopilotRecord): void {
  if (record.kind === "os_group") {
    const osName = record.data.os_name;
    const osVersion = record.data.os_version;
    if (osName && osVersion && osName !== "all" && osVersion !== "all") {
      validateAssembledSelector(`group:${[
        boundedSelectorText("os_name", osName),
        boundedSelectorText("os_version", osVersion),
      ].join("|")}`);
    }
    return;
  }
  if (record.kind === "software_group") {
    const softwareName = record.data.software_name;
    const softwareVersion = record.data.software_version;
    if (
      softwareName
      && softwareVersion
      && softwareName !== "all"
      && softwareVersion !== "all"
    ) {
      validateAssembledSelector(`group:${[
        boundedSelectorText("software_name", softwareName),
        boundedSelectorText("software_version", softwareVersion),
      ].join("|")}`);
    }
    return;
  }
  validateAssembledSelector(`group:${[
    boundedSelectorText("resource_type", record.data.resource_type, 160)
      .replaceAll("/", ":"),
    boundedSelectorText("sku", record.data.sku || "Unknown"),
    boundedSelectorText("tier", record.data.tier || "Unknown"),
  ].join("|")}`);
}

function validateActiveInventoryFilters(
  tab: InventoryCopilotAdapterInput["tab"],
  filters: Record<string, string>,
): void {
  if (tab === "os") {
    const osName = filters.os_name;
    const osVersion = filters.os_version;
    if (osName && osVersion && osName !== "all" && osVersion !== "all") {
      validateAssembledSelector(`group:${[
        boundedSelectorText("os_name", osName),
        boundedSelectorText("os_version", osVersion),
      ].join("|")}`);
    }
    return;
  }
  if (tab === "azure") {
    const resourceType = filters.resource_type;
    if (resourceType && resourceType !== "all") {
      validateAssembledSelector(
        `type:${boundedSelectorText("resource_type", resourceType, 160)}`,
      );
    }
  }
}

function assertEvidenceRowBound(data: Record<string, unknown>): void {
  const bytes = new TextEncoder().encode(asciiJson(data)).length + numericValueCount(data);
  assertBound("evidence row", bytes, COPILOT_SNAPSHOT_LIMITS.evidenceRowBytes);
}

function numericValueCount(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return 1;
  if (Array.isArray(value)) {
    return value.reduce((total, item) => total + numericValueCount(item), 0);
  }
  if (value && typeof value === "object") {
    return Object.values(value).reduce(
      (total, item) => total + numericValueCount(item),
      0,
    );
  }
  return 0;
}

function mergeDuplicateEvidence(
  current: InventorySnapshotEvidence,
  incoming: InventorySnapshotEvidence,
): InventorySnapshotEvidence {
  const currentIdentity = stableJson([current.source, current.source_key, current.entity]);
  const incomingIdentity = stableJson([incoming.source, incoming.source_key, incoming.entity]);
  const base = compareCodePoints(currentIdentity, incomingIdentity) <= 0 ? current : incoming;
  return {
    ...base,
    status: STATUS_WARNING_PRIORITY[current.status] >= STATUS_WARNING_PRIORITY[incoming.status]
      ? current.status
      : incoming.status,
    observed_at: current.observed_at >= incoming.observed_at
      ? current.observed_at
      : incoming.observed_at,
    selected: current.selected || incoming.selected,
    direct: current.direct || incoming.direct,
    actionable: current.actionable || incoming.actionable,
  };
}

/**
 * Builds the immutable Inventory v2 observation sent to the governed
 * orchestration route. It carries observations and hints, never authority.
 */
export function buildInventoryCopilotContext(input: InventoryCopilotAdapterInput): InventoryCopilotContext {
  assertBound("evidence rows", input.records.length, COPILOT_SNAPSHOT_LIMITS.evidenceRows);
  assertBound(
    "freshness records",
    input.sourceStatuses.length,
    COPILOT_SNAPSHOT_LIMITS.freshnessRecords,
  );
  if (!Number.isInteger(input.totalCount) || input.totalCount < 0 || input.totalCount > 1_000_000) {
    throw new Error("total count is outside the server bounds");
  }

  const populatedFilters = Object.entries(input.filters)
    .map(([key, value]) => [key, value.trim()] as const)
    .filter(([, value]) => Boolean(value));
  assertBound("inventory filters", populatedFilters.length, 16);
  const filterContext = Object.fromEntries(
    populatedFilters
      .map(([key, value]) => [
        boundedSelectorText("filter name", key, 64),
        boundedSelectorText(`filter ${key}`, value, 160),
      ])
      .sort(([left], [right]) => compareCodePoints(left, right)),
  );
  validateActiveInventoryFilters(input.tab, filterContext);
  const sortContext = Object.fromEntries(
    Object.entries(input.sort ?? {}).sort(([left], [right]) => compareCodePoints(left, right)),
  );
  const inventoryContext = {
    tab: input.tab,
    filters: filterContext,
    sort: sortContext,
    offset: input.offset ?? 0,
    limit: input.limit ?? input.records.length,
  };
  const evidenceById = new Map<string, InventorySnapshotEvidence>();

  for (const record of input.records) {
    const source = boundedString("evidence source", record.source, 1, 128);
    const sourceKey = boundedSourceKey(record.identity);
    const observedAt = record.observedAt ?? input.observedAt ?? "";
    if (observedAt) boundedString("evidence observation time", observedAt, 1, 128);
    const entity = recordEntity({ ...record, identity: sourceKey });
    const claimType = record.kind;
    const selected = Boolean(
      input.selectedIdentity
      && normalizedIdentityPart(record.identity)
        === normalizedIdentityPart(input.selectedIdentity),
    );
    if (selected) validateSelectedInventorySelector(record);
    const stableId = canonicalEvidenceStableId({
      source,
      sourceKey,
      entity,
      claimType,
    });
    const data = {
      ...record.data,
      inventory_context: inventoryContext,
      selected: false,
    };
    assertEvidenceRowBound(data);
    const evidenceId = `browser:${sha256(asciiJson([stableId, stableJson(data)])).slice(0, 32)}`;
    const evidenceRow: InventorySnapshotEvidence = {
      evidence_id: evidenceId,
      source,
      status: record.status ?? "ok",
      observed_at: observedAt,
      resource_id: entity.type === "azure" ? entity.resource_id : "",
      source_key: sourceKey,
      entity,
      claim_type: claimType,
      citations: [],
      selected,
      direct: true,
      actionable: false,
      severity: "unknown",
      quality: "high",
      data,
    };
    const existing = evidenceById.get(evidenceId);
    evidenceById.set(
      evidenceId,
      existing ? mergeDuplicateEvidence(existing, evidenceRow) : evidenceRow,
    );
  }

  const recordEvidence = Array.from(evidenceById.values()).sort((left, right) =>
    compareCodePoints(left.evidence_id, right.evidence_id));
  if (recordEvidence.length > input.totalCount) {
    throw new Error("visible count cannot exceed total count");
  }
  const selectorMarkedEntities = new Set<string>();
  const markedRecordEvidence = recordEvidence.map((item) => {
    const key = entityKey(item.entity);
    const selectorSelected = item.selected && !selectorMarkedEntities.has(key);
    if (selectorSelected) selectorMarkedEntities.add(key);
    return {
      ...item,
      data: {
        ...item.data,
        selected: selectorSelected,
      },
    };
  });
  const contextEvidence: InventorySnapshotEvidence[] = input.records.length === 0
    ? [buildEmptyInventoryContextEvidence(input, inventoryContext)]
    : [];
  const evidence = [...markedRecordEvidence, ...contextEvidence].sort((left, right) =>
    compareCodePoints(left.evidence_id, right.evidence_id));
  assertBound("evidence rows", evidence.length, COPILOT_SNAPSHOT_LIMITS.evidenceRows);

  const selectedEntities = recordEvidence
    .filter((item) => item.selected)
    .map((item) => item.entity)
    .filter((entity): entity is CopilotEntityRef => entity.type !== "observation")
    .filter((entity, index, entities) => {
      const key = entityKey(entity);
      return entities.findIndex((candidate) => entityKey(candidate) === key) === index;
    })
    .sort((left, right) => compareCodePoints(entityKey(left), entityKey(right)));
  assertBound(
    "selected entities",
    selectedEntities.length,
    COPILOT_SNAPSHOT_LIMITS.selectedEntities,
  );

  const sourceObservations = input.sourceStatuses.map((source) => {
    const observedAt = source.observedAt || input.observedAt || "unknown";
    return {
      source: boundedString("freshness source", source.source, 1, 128),
      observed_at: boundedString("freshness observation time", observedAt, 1, 128),
      status: freshnessStatus(source.status),
    };
  });
  const aggregateStatus = sourceObservations.reduce<CopilotFreshnessStatusV2>(
    (current, item) =>
      FRESHNESS_WARNING_PRIORITY[current] >= FRESHNESS_WARNING_PRIORITY[item.status]
        ? current
        : item.status,
    sourceObservations.length ? "fresh" : "unavailable",
  );
  const aggregateObservedAt = sourceObservations.reduce(
    (latest, item) => latest >= item.observed_at ? latest : item.observed_at,
    input.observedAt || "unknown",
  );
  const freshnessSources = Array.from(
    new Set(
      input.records.length
        ? input.records.map((record) => boundedString("evidence source", record.source, 1, 128))
        : [INVENTORY_EVIDENCE_SOURCES[input.tab]],
    ),
  ).sort(compareCodePoints);
  const freshness = freshnessSources.map((source) => ({
    source,
    observed_at: boundedString(
      "freshness observation time",
      aggregateObservedAt,
      1,
      128,
    ),
    status: aggregateStatus,
  }));
  assertBound(
    "freshness records",
    freshness.length,
    COPILOT_SNAPSHOT_LIMITS.freshnessRecords,
  );

  const snapshot: StrictCopilotEvidenceSnapshotV2 = {
    version: "2",
    page_kind: "inventory",
    page_id: `inventory:${input.tab}`,
    coverage: {
      visible_count: recordEvidence.length,
      total_count: input.totalCount,
      complete: recordEvidence.length === input.totalCount,
    },
    freshness,
    selected_entities: selectedEntities,
    evidence,
    material_claims: [],
  };
  assertBound(
    "snapshot",
    new TextEncoder().encode(serializeCopilotSnapshot(snapshot)).length
      + numericValueCount(snapshot),
    COPILOT_SNAPSHOT_LIMITS.snapshotBytes,
  );

  const uncertainty = [
    ...(snapshot.coverage.complete ? [] : ["visible subset is incomplete"]),
    ...sourceObservations
      .filter((item) => item.status !== "fresh")
      .map((item) => `${item.source} freshness is ${item.status}`),
    ...(!sourceObservations.length
      ? [`${INVENTORY_EVIDENCE_SOURCES[input.tab]} freshness is unavailable`]
      : []),
  ];

  return {
    disposition: "integrated",
    requestedScope: input.scope,
    snapshot,
    uncertainty,
    starterQuestions: INVENTORY_STARTERS,
  };
}

function buildEmptyInventoryContextEvidence(
  input: InventoryCopilotAdapterInput,
  inventoryContext: Record<string, unknown>,
): InventorySnapshotEvidence {
  const source = INVENTORY_EVIDENCE_SOURCES[input.tab];
  const sourceKey = `page-context:${input.tab}`;
  const entity: CopilotEvidenceIdentity = {
    type: "observation",
    source,
    source_key: sourceKey,
  };
  const data = { inventory_context: inventoryContext, selected: false };
  assertEvidenceRowBound(data);
  const stableId = canonicalEvidenceStableId({
    source,
    sourceKey,
    entity,
    claimType: "page_context",
  });
  return {
    evidence_id: `browser:${sha256(asciiJson([stableId, stableJson(data)])).slice(0, 32)}`,
    source,
    status: "empty",
    observed_at: input.observedAt ?? "",
    resource_id: "",
    source_key: sourceKey,
    entity,
    claim_type: "page_context",
    citations: [],
    selected: false,
    direct: false,
    actionable: false,
    severity: "unknown",
    quality: "unknown",
    data,
  };
}

/** One stable, already-authorized observation supplied by a contextual page. */
export interface CoreCopilotRecord {
  identity: string;
  namespace: string;
  kind: string;
  source: string;
  data: Record<string, unknown>;
  /** Treat rendered evidence as non-authoritative when it has no Azure identity. */
  evidenceIdentity?: "domain" | "observation";
  resourceId?: string;
  resourceType?: string;
  name?: string;
  observedAt?: string;
  status?: CopilotSnapshotStatus;
  selected?: boolean;
  priority?: number;
}

/** Visible-versus-total coverage for one collection rendered by a page. */
export interface CoreCopilotCoverageInput {
  key: string;
  visibleCount: number;
  totalCount: number;
  truncated?: boolean;
  available?: boolean;
}

/** Source observation used to retain freshness independently from row order. */
export interface CoreCopilotSourceStatus {
  source: string;
  observedAt?: string;
  status: CopilotFreshnessStatusV2;
}

/** Low-level input shared by the Overview, Network, and Compliance adapters. */
export interface CoreCopilotAdapterInput {
  scope: ScopeSelection;
  filters: Record<string, string[]>;
  sort?: Record<string, string>;
  records: CoreCopilotRecord[];
  evidence: EvidenceItem[];
  coverage: CoreCopilotCoverageInput[];
  sourceStatuses: CoreCopilotSourceStatus[];
}

/** Read-only starter hint submitted through the drawer's policy boundary. */
export interface CoreCopilotStarterQuestion {
  label: string;
  specialistId: string;
  tool?: string;
  toolArguments: Record<string, unknown>;
}

/** Normalized coverage retained by a contextual page adapter. */
export interface CoreCopilotCoverage {
  visible_count: number;
  total_count: number;
  complete: boolean;
  truncated: boolean;
}

/** Pure contextual page output consumed by the shared Copilot drawer. */
export interface CoreCopilotContext {
  disposition: "integrated";
  requestedScope: ScopeSelection;
  snapshot: CopilotPageSnapshot;
  selectedEntities: CopilotEntityRef[];
  coverage: Record<string, CoreCopilotCoverage>;
  uncertainty: string[];
  starterQuestions: CoreCopilotStarterQuestion[];
}

/** Already-loaded Overview envelopes; no adapter performs data access. */
export interface OverviewCopilotPageInput {
  scope: ScopeSelection;
  situations?: Envelope<DurableSituation[]> | null;
  visibleSituationIds?: string[];
  network?: Envelope<NetworkSummary> | null;
  vulnerabilities?: Envelope<VulnerabilitySummary> | null;
  connections?: Envelope<SubscriptionConnection[]> | null;
}

type NetworkTopologyEnvelope = Envelope<{
  topology: NetworkTopology;
  summary: NetworkSummary;
}>;

type NetworkGapsEnvelope = Envelope<{
  gaps: NetworkGap[];
  intended_design_declared: boolean;
  summary: NetworkSummary;
  coverage?: CollectionCoverage;
}>;

type NetworkFindingsEnvelope = Envelope<{
  findings: RuleFinding[];
  summary: NetworkSummary;
  coverage?: CollectionCoverage;
}>;

type NetworkBypassEnvelope = Envelope<{
  gaps: NetworkGap[];
  count: number;
}>;

/** Already-loaded Network envelopes and active page state. */
export interface NetworkCopilotPageInput {
  scope: ScopeSelection;
  tab: "flow" | "topology" | "gaps" | "rules" | "policy";
  gapOffset: number;
  gapLimit: number;
  findingOffset: number;
  findingLimit: number;
  topology?: NetworkTopologyEnvelope | null;
  gaps?: NetworkGapsEnvelope | null;
  findings?: NetworkFindingsEnvelope | null;
  bypass?: NetworkBypassEnvelope | null;
}

/** Compliance row projected by the page before the adapter assigns identity. */
export interface ComplianceCopilotViolation {
  id: string;
  type: string;
  severity: string;
  title: string;
  detail: string;
  resource: string;
  application: string;
  businessService: string;
  owner: string;
  affectedTraffic: string;
  vulnerabilityExposure: string;
  remediation: string;
}

/** Already-loaded Compliance observations and evaluated page state. */
export interface ComplianceCopilotPageInput {
  scope: ScopeSelection;
  policyName: string;
  selectedId: string | null;
  violations: ComplianceCopilotViolation[];
  governedDeviations: ComplianceDeviation[];
  evidence: EvidenceItem[];
  sourceEnvelopes?: Record<string, Envelope<unknown> | null | undefined>;
}

/** One already-loaded Exposure landing section projected by the route. */
export interface ExposureCopilotSection<T> {
  value: T | null | undefined;
  loadedCount: number;
  totalCount: number;
  freshness: CopilotFreshnessStatusV2;
  available: boolean;
  observedAt?: string;
  evidence?: EvidenceItem[];
}

/** Vulnerability summary fields the Exposure adapter cites. */
export interface ExposureSummaryFields {
  cve_count: number;
  affected_asset_count: number;
  affected_business_service_count: number;
  critical_count: number;
  reachable_server_count: number;
  internet_exposed_count: number;
}

/** Patch priority fields the Exposure adapter cites. */
export interface ExposurePatchFields {
  priority_id: string;
  kb_id: string;
  cve_ids: string[];
  priority_score: number;
  affected_server_count: number;
  recommended_action: string;
}

/** Asset exposure fields the Exposure adapter cites. */
export interface ExposureAssetFields {
  asset_id: string;
  name?: string;
  resource_type?: string;
  business_service?: string;
  application?: string;
  cve_count?: number;
  critical_count?: number;
  network_exposure?: string;
  reachable?: boolean;
}

/** Defender overview fields the Exposure adapter cites. */
export interface ExposureDefenderFields {
  active_alert_count: number;
  critical_alert_count: number;
  attack_path_count: number;
  unhealthy_recommendation_count: number;
}

/** SLA compliance fields the Exposure adapter cites. */
export interface ExposureSlaFields {
  open_count: number;
  overdue_count: number;
  overall_compliance_rate: number | null;
}

/** Risk exception fields the Exposure adapter cites. */
export interface ExposureRiskExceptionFields {
  exception_id: string;
  cve_id: string;
  server_id: string;
  expires_at: string;
  approved_by: string;
}

/** Already-loaded Exposure landing sections; no adapter performs data access. */
export interface ExposureCopilotPageInput {
  scope: ScopeSelection;
  summary?: ExposureCopilotSection<ExposureSummaryFields | null> | null;
  patchPriorities?: ExposureCopilotSection<ExposurePatchFields[]> | null;
  assets?: ExposureCopilotSection<ExposureAssetFields[]> | null;
  defender?: ExposureCopilotSection<ExposureDefenderFields | null> | null;
  sla?: ExposureCopilotSection<ExposureSlaFields | null> | null;
  riskExceptions?: ExposureCopilotSection<ExposureRiskExceptionFields[]> | null;
}

/** A CVE finding row projected by the detail page before adapter typing. */
export interface CveFindingObservation {
  exposure_id?: string;
  target_id?: string;
  weakness_id?: string;
  server_id?: string;
  application?: string;
  business_service?: string;
  environment?: string;
  network_exposure?: string;
  reachable?: boolean;
  missing_kb?: string;
  severity?: string;
  target_kind?: string;
  current_state?: string;
  represented_workload_count?: number | null;
  total_workload_count?: number | null;
  due_at?: string | null;
  overdue?: boolean | null;
}

/** CVE record fields the CVE detail adapter cites. */
export interface CveSummaryFields {
  cve_id: string;
  title?: string;
  description?: string;
  severity?: string;
  cvss?: unknown;
  epss_score?: number | null;
  epss_percentile?: number | null;
  is_known_exploited?: boolean;
  kev_date_added?: string;
  kev_due_date?: string;
  kev_ransomware_use?: string;
  associated_kbs: string[];
}

/** Attack-path node fields the CVE detail adapter cites. */
export interface CveAttackNode {
  id: string;
  kind?: string;
  label?: string;
  business_service?: string;
  reachable?: boolean;
}

/** Attack-path graph the CVE detail adapter cites. */
export interface CveAttackGraph {
  nodes: CveAttackNode[];
}

/** Per-source enrichment trust reported by the CVE detail page. */
export interface CveDetailCopilotSource {
  key: string;
  freshness: CopilotFreshnessStatusV2;
  available: boolean;
  observedAt?: string;
}

/** Already-loaded CVE detail sections and evaluated page state. */
export interface CveDetailCopilotPageInput {
  scope: ScopeSelection;
  cveId: string;
  cve?: CveSummaryFields | null;
  findings: {
    rows: CveFindingObservation[];
    loadedCount: number;
    totalCount: number;
    available: boolean;
    freshness: CopilotFreshnessStatusV2;
    observedAt?: string;
  };
  attack?: {
    graph: CveAttackGraph | null;
    available: boolean;
    freshness: CopilotFreshnessStatusV2;
    observedAt?: string;
  } | null;
  sources: CveDetailCopilotSource[];
  filters?: Record<string, string[]>;
  evidence: EvidenceItem[];
}

/** Situation fields the Situation queue adapter cites. */
export interface SituationCopilotFields {
  situation_id: string;
  title?: string;
  priority?: string;
  severity?: string;
  lifecycle_state?: string;
  situation_type?: string;
  owner?: string;
  support_team?: string;
  affected_resource_ids?: string[];
  evidence_state?: string;
  last_observed_at?: string;
}

/** Situation source-trust fields the queue adapter cites. */
export interface SituationSourceStatusFields {
  source_family: string;
  observed_at?: string;
  availability?: string;
  freshness: string;
}

/** Already-loaded Situation queue page and evaluated triage state. */
export interface SituationsCopilotPageInput {
  scope: ScopeSelection;
  situations: SituationCopilotFields[];
  query: string;
  priority: string;
  page: number;
  pageSize: number;
  totalCount: number;
  nextOffset: number | null;
  selectedSituationId?: string | null;
  available: boolean;
  observedAt?: string;
  evidence: EvidenceItem[];
  sourceStatuses?: SituationSourceStatusFields[];
}

/** Selected governed remediation plan/action identity fields (read-only). */
export interface RemediationCopilotPlanFields {
  plan_id: string;
  action_id?: string;
  action_version?: string;
  title: string;
  status: string;
  family: string;
  resource_id?: string;
  resource_type?: string;
  resource_name?: string;
  snapshot_hash?: string;
}

/**
 * Current server-projected eligibility. These are descriptive mirrors of the
 * authoritative workflow projection -- they never grant Copilot any authority
 * and are re-read from the live workflow on every render.
 */
export interface RemediationCopilotEligibility {
  plan_executable: boolean;
  plan_ineligibility_reason?: string;
  can_operate: boolean;
  operate_ineligible_reason?: string;
  can_approve: boolean;
  approve_ineligible_reason?: string;
  approval_current: boolean;
  approval_status: string;
  has_executable_preview: boolean;
  recommended_step: string;
}

/** One current approval requirement row projected into the read context. */
export interface RemediationCopilotRequirementFields {
  policy_id: string;
  role: string;
  stage: string;
  satisfied: boolean;
  unmet_reason?: string;
}

/** Current execution lifecycle facts (recovery controls stay server-bound). */
export interface RemediationCopilotExecutionFields {
  execution_id: string;
  status: string;
  retryable: boolean;
  cancellable: boolean;
  supersedable: boolean;
  remaining_attempts?: number;
}

/** Current server-projected workflow blocker identity (read-only). */
export interface RemediationCopilotBlockerFields {
  code: string;
  step: string;
}

/** Source availability/freshness carried independently of row order. */
export interface RemediationCopilotSourceFreshness {
  source: string;
  availability?: "available" | "degraded" | "unavailable" | "partial";
  freshness?: string;
  observedAt?: string;
}

/**
 * Evidence carried from a prior investigation thread. It is always labeled
 * non-current and inert -- it can inform explanation but can never replace the
 * current server eligibility facts (D-08, D-09).
 */
export interface RemediationCopilotHistoricalEvidence {
  key: string;
  summary?: string;
  observedAt?: string;
  data?: Record<string, unknown>;
}

/** Visible-versus-total coverage for the loaded governed plan list. */
export interface RemediationCopilotCoverageInput {
  visiblePlanCount: number;
  totalPlanCount: number;
}

/** Already-loaded remediation workflow projection consumed by the adapter. */
export interface RemediationCopilotPageInput {
  scope: ScopeSelection;
  selectedPlan: RemediationCopilotPlanFields | null;
  eligibility: RemediationCopilotEligibility | null;
  requirements: RemediationCopilotRequirementFields[];
  execution: RemediationCopilotExecutionFields | null;
  blockers: RemediationCopilotBlockerFields[];
  evidence: EvidenceItem[];
  historicalEvidence?: RemediationCopilotHistoricalEvidence[];
  coverage: RemediationCopilotCoverageInput;
  sourceStatuses: RemediationCopilotSourceFreshness[];
}

/** Defender posture aggregate counts the adapter cites (read-only). */
export interface DefenderOverviewCopilotFields {
  active_alert_count: number;
  critical_alert_count: number;
  attack_path_count: number;
  unhealthy_recommendation_count: number;
  vulnerable_container_image_count: number;
  container_image_cve_count: number;
}

/** Defender secure-score aggregate the adapter cites. */
export interface DefenderSecureScoreCopilotFields {
  current: number;
  max: number;
  percentage: number | null;
}

/** Defender posture finding row projected before adapter typing. */
export interface DefenderPostureFindingFields {
  assessment_id: string;
  asset_id: string;
  asset_name?: string;
  resource_type?: string;
  defender_plan?: string;
  status?: string;
  severity?: string;
  recommendation?: string;
  business_service?: string;
  application?: string;
  last_assessed_at?: string;
}

/** Defender alert row the adapter cites. */
export interface DefenderAlertCopilotFields {
  id: string;
  title?: string;
  severity?: string;
  status?: string;
  timeGenerated?: string;
}

/** Defender attack-path row the adapter cites. */
export interface DefenderAttackPathCopilotFields {
  id: string;
  title?: string;
  potentialImpact?: string;
  nodeCount?: number;
}

/** Defender container-image exposure row the adapter cites. */
export interface DefenderContainerCopilotFields {
  id: string;
  target_resource_id?: string;
  repository?: string;
  severity?: string;
  critical_count?: number;
  cve_count?: number;
}

/** Already-loaded Defender posture sections; no adapter performs data access. */
export interface DefenderPostureCopilotPageInput {
  scope: ScopeSelection;
  selectedAssetId?: string | null;
  overview?: ExposureCopilotSection<DefenderOverviewCopilotFields | null> | null;
  secureScore?: ExposureCopilotSection<DefenderSecureScoreCopilotFields | null> | null;
  findings?: ExposureCopilotSection<DefenderPostureFindingFields[]> | null;
  alerts?: ExposureCopilotSection<DefenderAlertCopilotFields[]> | null;
  attackPaths?: ExposureCopilotSection<DefenderAttackPathCopilotFields[]> | null;
  containers?: ExposureCopilotSection<DefenderContainerCopilotFields[]> | null;
  evidence: EvidenceItem[];
}

/** KB record fields the KB detail adapter cites. */
export interface KbSummaryFields {
  kb_id: string;
  title?: string;
  product?: string;
  severity?: string;
  published_at?: string;
  target_date?: string;
  cve_ids: string[];
  affected_servers: string[];
  affected_server_count?: number;
  affected_servers_truncated?: boolean;
  affected_business_services: string[];
}

/** A KB finding row projected by the detail page before adapter typing. */
export interface KbFindingObservation {
  target_id?: string;
  server_id?: string;
  cve_id?: string;
  product_name?: string;
  target_date?: string;
  application?: string;
  business_service?: string;
  environment?: string;
  severity?: string;
  reachable?: boolean;
  network_exposure?: string;
  missing_kb?: string;
}

/** Already-loaded KB detail sections and evaluated page state. */
export interface KbDetailCopilotPageInput {
  scope: ScopeSelection;
  kbId: string;
  kb?: KbSummaryFields | null;
  findings: {
    rows: KbFindingObservation[];
    loadedCount: number;
    totalCount: number;
    available: boolean;
    freshness: CopilotFreshnessStatusV2;
    observedAt?: string;
  };
  sources: CveDetailCopilotSource[];
  filters?: Record<string, string[]>;
  evidence: EvidenceItem[];
}

/** A patch-priority finding row projected before adapter typing. */
export interface PatchPriorityObservation {
  exposure_id?: string;
  target_id?: string;
  weakness_id?: string;
  missing_kb?: string;
  kb_id?: string;
  server_id?: string;
  application?: string;
  business_service?: string;
  severity?: string;
  priority_score?: number | null;
  recommendation?: string;
  sla_state?: string;
  sla_overdue?: boolean | null;
}

/** Source availability/freshness carried independently of row order. */
export interface PatchPrioritySourceStatus {
  source: string;
  freshness?: string;
  observedAt?: string;
  availability?: string;
}

/** Already-loaded patch-priority queue and evaluated page state. */
export interface PatchPrioritiesCopilotPageInput {
  scope: ScopeSelection;
  rows: PatchPriorityObservation[];
  loadedCount: number;
  totalCount: number;
  available: boolean;
  freshness: CopilotFreshnessStatusV2;
  observedAt?: string;
  selectedId?: string | null;
  filters?: Record<string, string[]>;
  sort?: Record<string, string>;
  evidence: EvidenceItem[];
  sourceStatuses?: PatchPrioritySourceStatus[];
}

/** A correlated change event projected from the incident timeline. */
export interface ChangeCorrelationObservation {
  event_id: string;
  incident_id?: string;
  incident_title?: string;
  event_type?: string;
  summary?: string;
  source?: string;
  timestamp?: string;
  business_services?: string[];
}

/** Source availability/freshness carried independently of row order. */
export interface ChangesSourceStatus {
  source: string;
  freshness?: string;
  observedAt?: string;
  availability?: string;
}

/** Already-loaded change-correlation stream and evaluated page state. */
export interface ChangesCopilotPageInput {
  scope: ScopeSelection;
  changes: ChangeCorrelationObservation[];
  loadedCount: number;
  totalCount: number;
  available: boolean;
  freshness: CopilotFreshnessStatusV2;
  observedAt?: string;
  selectedId?: string | null;
  filters?: Record<string, string[]>;
  evidence: EvidenceItem[];
  sourceStatuses?: ChangesSourceStatus[];
}

/** Proposed-change identity fields the predeploy adapter cites. */
export interface PredeployChangeFields {
  change_id?: string;
  title?: string;
  author?: string;
  source?: string;
  target_environment?: string;
  resource_change_count?: number;
}

/** Predicted simulation fields (never an observed outcome). */
export interface PredeploySimulationFields {
  highest_severity?: string;
  simulated_domains: string[];
  by_severity: Record<string, number>;
  effect_count: number;
  confirmed_outcome: boolean;
}

/** Predicted risk fields (never a confirmed cause). */
export interface PredeployRiskFields {
  score: number;
  level: string;
  confidence: string;
  confirmed_cause: boolean;
}

/** CAB recommendation fields the predeploy adapter cites. */
export interface PredeployCabFields {
  verdict: string;
  risk_level: string;
  required_approvals: string[];
  confirmed_cause: boolean;
}

/** An impacted-resource row projected before adapter typing. */
export interface PredeployImpactObservation {
  resource_id?: string;
  resource_name?: string;
  business_service?: string;
  environment?: string;
  relationship?: string;
}

/** Already-loaded predeploy assessment sections consumed by the adapter. */
export interface PredeployCopilotPageInput {
  scope: ScopeSelection;
  change?: PredeployChangeFields | null;
  simulation?: PredeploySimulationFields | null;
  risk?: PredeployRiskFields | null;
  cab?: PredeployCabFields | null;
  impactedResources: PredeployImpactObservation[];
  impactedTotalCount: number;
  impactedTruncated?: boolean;
  available: boolean;
  freshness: CopilotFreshnessStatusV2;
  observedAt?: string;
  unknowns?: string[];
  evidence: EvidenceItem[];
}

/** A subscription connection row projected before adapter typing. */
export interface ConnectionCopilotObservation {
  connection_id: string;
  name: string;
  subscription_id: string;
  business_service?: string;
  environment?: string;
  criticality?: string;
  health_status: string;
  sync_status: string;
  sync_record_count?: number;
  last_successful_sync_at?: string | null;
  is_active: boolean;
}

/** Already-loaded subscription-connection registry and evaluated page state. */
export interface ConnectionsCopilotPageInput {
  scope: ScopeSelection;
  connections: ConnectionCopilotObservation[];
  loadedCount: number;
  totalCount: number;
  available: boolean;
  freshness: CopilotFreshnessStatusV2;
  observedAt?: string;
  selectedConnectionId?: string | null;
  filters?: Record<string, string[]>;
  evidence: EvidenceItem[];
}

/** A Fabric medallion layer health count the adapter cites. */
export interface FabricLayerCopilotFields {
  layer: "bronze" | "silver" | "gold";
  healthy: number;
  total: number;
}

/** A Fabric manifest projection row projected before adapter typing. */
export interface FabricManifestCopilotObservation {
  projection_name: string;
  disposition: string;
  compatibility_version?: string | null;
  subscription_id?: string;
}

/** Fabric governance completeness aggregate the adapter cites. */
export interface FabricGovernanceCopilotFields {
  ownership_gap_count: number;
  tag_gap_count: number;
  referential_integrity_blockers: number;
}

/** Fabric capacity/readiness aggregate the adapter cites. */
export interface FabricCapacityCopilotFields {
  status: string;
  state?: string;
  capacity_name?: string;
}

/** Independent Fabric source availability/freshness carried per section. */
export interface FabricMedallionSourceStatus {
  source: string;
  freshness?: string;
  observedAt?: string;
  availability?: string;
}

/** Already-loaded Fabric medallion sections and evaluated page state. */
export interface FabricMedallionCopilotPageInput {
  scope: ScopeSelection;
  subscriptionId?: string | null;
  layers: FabricLayerCopilotFields[];
  manifest: FabricManifestCopilotObservation[];
  manifestTotalCount?: number;
  governance?: FabricGovernanceCopilotFields | null;
  capacity?: FabricCapacityCopilotFields | null;
  semanticReadiness?: { status: string; reason?: string } | null;
  dataAgentReadiness?: { status: string; configured: boolean } | null;
  lineageRef?: string | null;
  available: boolean;
  deploymentBlocked?: boolean;
  freshness: CopilotFreshnessStatusV2;
  observedAt?: string;
  evidence: EvidenceItem[];
  sourceStatuses?: FabricMedallionSourceStatus[];
}

/** An enterprise governance role projected before adapter typing. */
export interface GovernanceRoleObservation {
  role_id: string;
  name?: string;
  permissions: string[];
}

/** A governance policy section summary projected before adapter typing. */
export interface GovernancePolicyObservation {
  section: string;
  setting_count: number;
}

/** Already-loaded governance sections and evaluated page state. */
export interface GovernanceCopilotPageInput {
  scope: ScopeSelection;
  roles: GovernanceRoleObservation[];
  rolesTotalCount?: number;
  policies: GovernancePolicyObservation[];
  accessReviewAudiences: string[];
  auditExportKinds: string[];
  settingsAvailable: boolean;
  audiencesAvailable: boolean;
  kindsAvailable: boolean;
  freshness: CopilotFreshnessStatusV2;
  observedAt?: string;
  filters?: Record<string, string[]>;
  evidence: EvidenceItem[];
}

/** A principal risk row projected before adapter typing. */
export interface IdentityPrincipalObservation {
  principal_id: string;
  principal_type?: string;
  privileged?: boolean;
  stale?: boolean;
  widest_scope_breadth?: string;
  assignment_count?: number;
  roles?: string[];
}

/** A subscription-owner row projected before adapter typing. */
export interface IdentityOwnerObservation {
  principal_id: string;
  principal_type?: string;
  subscription_id?: string;
  scope_breadth?: string;
  stale?: boolean;
}

/** A stale access-review assignment projected before adapter typing. */
export interface IdentityAccessReviewObservation {
  assignment_id: string;
  principal_id: string;
  role?: string;
  privileged?: boolean;
}

/** A service-principal credential row projected before adapter typing. */
export interface IdentitySpnObservation {
  credential_id: string;
  connection_name?: string;
  rotation_status: string;
  days_to_expiry?: number | null;
  issues_count: number;
}

/** Identity summary aggregate the adapter cites. */
export interface IdentitySummaryCopilotFields {
  principal_count: number;
  privileged_principal_count: number;
  stale_assignment_count: number;
  non_human_principal_count: number;
  assignment_count: number;
}

/** Already-loaded identity governance sections and evaluated page state. */
export interface IdentityCopilotPageInput {
  scope: ScopeSelection;
  summary?: IdentitySummaryCopilotFields | null;
  principals: IdentityPrincipalObservation[];
  principalsTotalCount: number;
  owners: IdentityOwnerObservation[];
  ownersTotalCount: number;
  staleAccess: IdentityAccessReviewObservation[];
  staleTotalCount: number;
  spnCredentials: IdentitySpnObservation[];
  spnTotalCount: number;
  available: boolean;
  freshness: CopilotFreshnessStatusV2;
  observedAt?: string;
  selectedPrincipalId?: string | null;
  filters?: Record<string, string[]>;
  evidence: EvidenceItem[];
}

/** A cost savings opportunity projected before adapter typing. */
export interface FinOpsOpportunityObservation {
  recommendation_id?: string;
  resource_id?: string;
  problem?: string;
  impact?: string;
  annual_savings: number | null;
  currency: string;
  owner?: string;
  business_service?: string;
  subscription?: string;
}

/** A waste item projected before adapter typing. */
export interface FinOpsWasteObservation {
  resource_id?: string;
  resource_type?: string;
  reason?: string;
  annual_savings: number | null;
  currency: string;
  owner?: string;
  business_service?: string;
}

/** A cost attribution group projected before adapter typing. */
export interface FinOpsAttributionObservation {
  dimension: string;
  group: string;
  identified_annual_savings: number;
  savings_opportunity_count: number;
  waste_item_count: number;
}

/** FinOps summary aggregate the adapter cites (currency + observation window). */
export interface FinOpsSummaryCopilotFields {
  identified_annual_savings: number;
  currency: string;
  savings_opportunity_count: number;
  quantified_opportunity_count: number;
  waste_item_count: number;
  actual_spend?: number;
  actual_spend_currency?: string;
  actual_spend_period_start?: string;
  actual_spend_period_end?: string;
  unavailable_metrics: { metric: string; reason: string }[];
}

/** Already-loaded FinOps sections and evaluated page state. */
export interface FinOpsCopilotPageInput {
  scope: ScopeSelection;
  summary?: FinOpsSummaryCopilotFields | null;
  dimension: string;
  attribution: FinOpsAttributionObservation[];
  attributionTotalCount: number;
  opportunities: FinOpsOpportunityObservation[];
  opportunitiesTotalCount: number;
  waste: FinOpsWasteObservation[];
  wasteTotalCount: number;
  available: boolean;
  freshness: CopilotFreshnessStatusV2;
  observedAt?: string;
  filters?: Record<string, string[]>;
  evidence: EvidenceItem[];
}

/** A resource utilization row projected before adapter typing. */
export interface ResourceHealthObservation {
  resource_id: string;
  resource_name?: string;
  resource_type?: string;
  status: string;
  cpu_percent: number | null;
  memory_percent: number | null;
  disk_free_percent: number | null;
  observed_at?: string;
  unavailable_metrics: string[];
  series_point_count: number;
}

/** Resource-health summary aggregate the adapter cites. */
export interface ResourceHealthSummaryCopilotFields {
  total: number;
  critical: number;
  warning: number;
  healthy: number;
  unknown: number;
}

/** Already-loaded resource-health snapshot and evaluated page state. */
export interface ResourceHealthCopilotPageInput {
  scope: ScopeSelection;
  resources: ResourceHealthObservation[];
  loadedCount: number;
  totalCount: number;
  summary?: ResourceHealthSummaryCopilotFields | null;
  available: boolean;
  cached?: boolean;
  observedAt?: string;
  freshness: CopilotFreshnessStatusV2;
  unavailableMetrics?: string[];
  warnings?: string[];
  filters?: Record<string, string[]>;
  selectedResourceId?: string | null;
  evidence: EvidenceItem[];
}

/** Durable evidence fields the Situation detail adapter cites. */
export interface SituationDetailEvidenceObservation {
  evidence_id: string;
  source_family: string;
  source_object_id: string;
  assertion?: string;
  quality: string;
  availability: string;
  freshness: string;
  observed_at?: string;
  resource_ids?: string[];
}

/** Durable source-trust fields the Situation detail adapter cites. */
export interface SituationDetailSourceStatus {
  source_family: string;
  availability: string;
  freshness: string;
  observed_at?: string;
}

/** Bounded linked-entity fields the Situation detail adapter cites. */
export interface SituationDetailLinkObservation {
  link_id: string;
  entity_type: string;
  entity_id: string;
  relation: string;
  quality: string;
}

/** Recorded service audit fields the Situation detail adapter cites. */
export interface SituationDetailAuditObservation {
  event_id: string;
  actor: string;
  action: string;
  timestamp: string;
}

/** Selected Situation identity fields the detail adapter cites. */
export interface SituationDetailFields {
  situation_id: string;
  title?: string;
  severity?: string;
  priority?: string;
  lifecycle_state?: string;
  situation_type?: string;
  owner?: string;
  support_team?: string;
  evidence_state?: string;
  affected_resource_ids?: string[];
  unknowns?: string[];
  started_at?: string;
  last_observed_at?: string;
}

/** Already-loaded Situation detail sections and evaluated page state. */
export interface SituationDetailCopilotPageInput {
  scope: ScopeSelection;
  situationId: string;
  situation?: SituationDetailFields | null;
  evidence: SituationDetailEvidenceObservation[];
  links: SituationDetailLinkObservation[];
  sourceStatuses: SituationDetailSourceStatus[];
  auditEvents?: SituationDetailAuditObservation[];
  auditAvailable?: boolean;
  available: boolean;
  observedAt?: string;
  citations: EvidenceItem[];
}

/** Synthesized business-service catalog row the Services adapter cites. */
export interface ServicesCatalogObservation {
  name: string;
  environments: string[];
  subscriptionCount: number;
  situationCount: number;
  criticalCount: number;
  healthRisk: number;
  operationalState: string;
}

/** Already-loaded Services catalog page and evaluated page state. */
export interface ServicesCopilotPageInput {
  scope: ScopeSelection;
  services: ServicesCatalogObservation[];
  visibleCount: number;
  totalCount: number;
  filters?: Record<string, string[]>;
  selectedServiceName?: string | null;
  connectionsAvailable: boolean;
  incidentsAvailable: boolean;
  connectionsObservedAt?: string;
  incidentsObservedAt?: string;
  connectionsFreshness?: CopilotFreshnessStatusV2;
  incidentsFreshness?: CopilotFreshnessStatusV2;
  evidence: EvidenceItem[];
}

/** Semantic subject fields the Service detail adapter cites (non-ARM by default). */
export interface ServiceDetailSubjectFields {
  entity_type?: string;
  name?: string;
  lifecycle_status?: string;
  owner?: string | null;
  support_team?: string | null;
  business_service?: string | null;
  application?: string | null;
  environment?: string | null;
  criticality?: string | null;
  resource_id?: string | null;
}

/** One independently-available service context section (context, risk, or impact). */
export interface ServiceDetailSection {
  subject?: ServiceDetailSubjectFields | null;
  available: boolean;
  freshness: CopilotFreshnessStatusV2;
  observedAt?: string;
  sections?: string[];
  /** Per-provider state retained from the loaded section response. */
  sourceStatus?: Record<string, string>;
  /** Explicit server degradation warnings that remain citation-eligible. */
  warnings?: string[];
}

/** Bounded dependency/blast-radius entity the Service detail adapter cites. */
export interface ServiceDependencyObservation {
  id: string;
  name?: string;
  relation?: string;
  resource_id?: string;
}

/** Already-loaded Service detail sections and evaluated page state. */
export interface ServiceDetailCopilotPageInput {
  scope: ScopeSelection;
  name: string;
  context: ServiceDetailSection;
  risk: ServiceDetailSection;
  impact: ServiceDetailSection;
  dependencies?: ServiceDependencyObservation[];
  filters?: Record<string, string[]>;
  evidence: EvidenceItem[];
}

/** Twin entity fields the operational-twin adapter cites. */
export interface TwinEntityObservation {
  id: string;
  kind: string;
  name?: string;
  version?: string;
  state?: string;
  confidence?: string;
  business_service?: string;
  resource_id?: string;
}

/** Twin relationship fields the operational-twin adapter cites. */
export interface TwinRelationshipObservation {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence?: string;
  supported?: boolean;
}

/** Twin temporal event fields the operational-twin adapter cites. */
export interface TwinTimelineObservation {
  timestamp: string;
  type: string;
  entity: string;
  summary?: string;
}

/** Twin traversal fields the operational-twin adapter cites. */
export interface TwinTraversalObservation {
  resource_id: string;
  path: Array<{ id: string; kind: string; name?: string }>;
  business_consequence: string[];
}

/** Twin scenario fields the operational-twin adapter cites (scenario, not observed). */
export interface TwinScenarioObservation {
  scenario: string;
  target: string;
  likely_impact?: string;
  risk_delta?: number;
  impacted_count?: number;
  assumptions?: string[];
}

/** Already-loaded operational-twin sections and evaluated page state. */
export interface TwinCopilotPageInput {
  scope: ScopeSelection;
  twinId: string;
  version?: string;
  previousVersion?: string;
  observedAt?: string;
  liveObservedAt?: string;
  confidence?: string;
  /** Scenario-weighted risk score already rendered by the Twin page. */
  riskScore?: number | null;
  entities: TwinEntityObservation[];
  entitiesTotal: number;
  relationships: TwinRelationshipObservation[];
  relationshipsTotal: number;
  timeline: TwinTimelineObservation[];
  timelineTotal: number;
  traversal?: TwinTraversalObservation | null;
  scenario?: TwinScenarioObservation | null;
  selectedResourceId?: string | null;
  available: boolean;
  freshness?: CopilotFreshnessStatusV2;
  sourceStatus?: Record<string, string>;
  unsupportedRelationships?: string[];
  staleTemporalEvidence?: string[];
  filters?: Record<string, string[]>;
  evidence: EvidenceItem[];
}

const CORE_PAGE_CONFIG = {
  overview: {
    pageKind: "resource",
    pageId: "operations-overview",
  },
  network: {
    pageKind: "network",
    pageId: "network-topology",
  },
  compliance: {
    pageKind: "governance",
    pageId: "compliance-posture",
  },
  exposure: {
    pageKind: "vulnerability",
    pageId: "exposure",
  },
  situations: {
    pageKind: "incident",
    pageId: "situations",
  },
  remediation: {
    pageKind: "remediation",
    pageId: "remediation",
  },
} as const;

const INVENTORY_STARTERS: Array<{
  label: string;
  specialistId: string;
  tool: string;
  toolArguments: Record<string, unknown>;
}> = [
  {
    label: "Review visible inventory health",
    specialistId: "inventory_data_health",
    tool: "inventory_resources",
    toolArguments: {},
  },
  {
    label: "Where is inventory coverage incomplete?",
    specialistId: "inventory_data_health",
    tool: "inventory_resources",
    toolArguments: {},
  },
];

const OVERVIEW_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "What needs attention right now?",
    specialistId: "incident",
    tool: "incidents",
    toolArguments: {},
  },
  {
    label: "Which services have the highest risk?",
    specialistId: "vulnerability",
    tool: "cve_exposure",
    toolArguments: {},
  },
  {
    label: "What should be fixed first?",
    specialistId: "remediation",
    tool: "remediation_opportunities",
    toolArguments: {},
  },
  {
    label: "Give me an executive summary of cross-domain risk.",
    specialistId: "executive_summary",
    toolArguments: {},
  },
];

const NETWORK_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Can UAT reach PROD?",
    specialistId: "network",
    tool: "traffic_flow",
    toolArguments: { source: "UAT", destination: "PROD" },
  },
  {
    label: "Show inspection bypass paths.",
    specialistId: "network",
    tool: "firewall_nsg_gaps",
    toolArguments: { category: "firewall_bypass" },
  },
];

const COMPLIANCE_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Which PROD workloads bypass the firewall?",
    specialistId: "network",
    tool: "firewall_nsg_gaps",
    toolArguments: { category: "firewall_bypass" },
  },
  {
    label: "Which CVEs affect our critical services?",
    specialistId: "vulnerability",
    tool: "cve_exposure",
    toolArguments: {},
  },
  {
    label: "Which governance risks or exceptions need review?",
    specialistId: "governance",
    toolArguments: {},
  },
];

const EXPOSURE_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Which CVEs affect our highest-risk service?",
    specialistId: "vulnerability",
    tool: "cve_exposure",
    toolArguments: {},
  },
  {
    label: "What should be patched first?",
    specialistId: "vulnerability",
    tool: "cve_exposure",
    toolArguments: {},
  },
  {
    label: "Which Defender plans have the most open recommendations?",
    specialistId: "vulnerability",
    tool: "cve_exposure",
    toolArguments: {},
  },
];

const SITUATIONS_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Which situations are highest priority?",
    specialistId: "incident",
    tool: "incidents",
    toolArguments: {},
  },
  {
    label: "What should be fixed first?",
    specialistId: "remediation",
    tool: "remediation_opportunities",
    toolArguments: {},
  },
  {
    label: "What changed before the outage?",
    specialistId: "incident",
    tool: "incidents",
    toolArguments: {},
  },
];

// Advisory explanation/handoff hints only. None of these tools mutate state;
// approval and execution remain existing server-side workflows (D-10).
const REMEDIATION_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Explain this remediation plan and its current blockers.",
    specialistId: "remediation",
    tool: "remediation_opportunities",
    toolArguments: {},
  },
  {
    label: "What must be approved before this plan can run?",
    specialistId: "remediation",
    tool: "remediation_opportunities",
    toolArguments: {},
  },
  {
    label: "What is the safest next governed step?",
    specialistId: "remediation",
    tool: "remediation_opportunities",
    toolArguments: {},
  },
];

// Advisory Defender/patch explanation hints only. None of these tools mutate
// state; approval and execution remain existing server-side workflows (D-10).
const DEFENDER_POSTURE_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Which Defender findings expose our critical services?",
    specialistId: "vulnerability",
    tool: "cve_exposure",
    toolArguments: {},
  },
  {
    label: "Which attack paths reach reachable assets?",
    specialistId: "vulnerability",
    toolArguments: {},
  },
  {
    label: "What should we remediate first?",
    specialistId: "remediation",
    tool: "remediation_opportunities",
    toolArguments: {},
  },
];

const PATCH_PRIORITIES_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "What is the top KB and why is it ranked first?",
    specialistId: "patch",
    tool: "patch_priorities",
    toolArguments: {},
  },
  {
    label: "Which product and publication date apply to the top KB?",
    specialistId: "patch",
    tool: "patch_priorities",
    toolArguments: {},
  },
  {
    label: "What action is recommended for the top KB?",
    specialistId: "patch",
    tool: "patch_priorities",
    toolArguments: {},
  },
];

// Cross-domain change hints. Correlation is advisory and never causal; none of
// these tools deploy, approve, or execute anything (D-03, D-06, D-08, D-10).
const CHANGES_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "What changed near active situations?",
    specialistId: "incident",
    tool: "incidents",
    toolArguments: {},
  },
  {
    label: "Which incidents correlate with recent changes?",
    specialistId: "incident",
    tool: "incidents",
    toolArguments: {},
  },
  {
    label: "What is the safest way to remediate this change's impact?",
    specialistId: "remediation",
    tool: "remediation_opportunities",
    toolArguments: {},
  },
];

const PREDEPLOY_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Explain the predicted risk of this change.",
    specialistId: "incident",
    tool: "incidents",
    toolArguments: {},
  },
  {
    label: "Which impacted services carry vulnerability exposure?",
    specialistId: "vulnerability",
    tool: "cve_exposure",
    toolArguments: {},
  },
  {
    label: "What governed remediation would this change require?",
    specialistId: "remediation",
    tool: "remediation_opportunities",
    toolArguments: {},
  },
];

const CONNECTIONS_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Review visible connection health",
    specialistId: "inventory_data_health",
    tool: "inventory_resources",
    toolArguments: {},
  },
  {
    label: "Where is subscription coverage incomplete or blocked?",
    specialistId: "inventory_data_health",
    tool: "inventory_resources",
    toolArguments: {},
  },
];

// Fabric medallion hints reach the Inventory & Data Health specialist only;
// optional Gold/Data Agent grounding is never a prerequisite (D-03, D-09).
const FABRIC_MEDALLION_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "How healthy are the Bronze, Silver, and Gold layers?",
    specialistId: "inventory_data_health",
    tool: "inventory_resources",
    toolArguments: {},
  },
  {
    label: "Which datasets have governance or lineage gaps?",
    specialistId: "inventory_data_health",
    tool: "inventory_resources",
    toolArguments: {},
  },
];

// Governance hints stay within the governance specialist's read-only toolset.
const GOVERNANCE_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Who owns governance decisions in this scope?",
    specialistId: "governance",
    toolArguments: {},
  },
  {
    label: "Where are policy or ownership gaps?",
    specialistId: "governance",
    toolArguments: {},
  },
  {
    label: "Which services need governance attention?",
    specialistId: "governance",
    toolArguments: {},
  },
];

// Identity hints stay within the identity_access specialist's read-only toolset.
const IDENTITY_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Which principals hold the widest access?",
    specialistId: "identity_access",
    toolArguments: {},
  },
  {
    label: "Who owns access in this business service?",
    specialistId: "identity_access",
    toolArguments: {},
  },
  {
    label: "Search for stale or unused access.",
    specialistId: "identity_access",
    toolArguments: {},
  },
];

// FinOps hints stay within the finops specialist's read-only toolset.
const FINOPS_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Which business services own the most savings?",
    specialistId: "finops",
    toolArguments: {},
  },
  {
    label: "Where is spend attribution missing or uncertain?",
    specialistId: "finops",
    toolArguments: {},
  },
  {
    label: "Search cost opportunities by owner.",
    specialistId: "finops",
    toolArguments: {},
  },
];

// Resource-health hints stay within the resource_health_observability specialist.
const RESOURCE_HEALTH_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "What incidents relate to these resources?",
    specialistId: "resource_health_observability",
    tool: "incidents",
    toolArguments: {},
  },
  {
    label: "Which services are impacted by resource pressure?",
    specialistId: "resource_health_observability",
    toolArguments: {},
  },
  {
    label: "Search resource utilization anomalies.",
    specialistId: "resource_health_observability",
    toolArguments: {},
  },
];

// Situation detail hints stay on the incident specialist that owns the
// situation_detail page mapping; every tool exists in the manifest catalog and
// none mutate state (D-03, D-05).
const SITUATION_DETAIL_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Summarize this situation and its evidence.",
    specialistId: "incident",
    tool: "incidents",
    toolArguments: {},
  },
  {
    label: "Which business services are affected?",
    specialistId: "incident",
    toolArguments: {},
  },
  {
    label: "What is the blast radius?",
    specialistId: "incident",
    toolArguments: {},
  },
];

// Services list/detail hints stay on the resource_health_observability
// specialist that owns the services/service_detail page mappings.
const SERVICES_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Which services need attention?",
    specialistId: "resource_health_observability",
    tool: "incidents",
    toolArguments: {},
  },
  {
    label: "What is the operational impact across services?",
    specialistId: "resource_health_observability",
    toolArguments: {},
  },
  {
    label: "Find a specific service.",
    specialistId: "resource_health_observability",
    toolArguments: {},
  },
];

// Service detail hints stay on the resource_health_observability specialist and
// carry the selected service name for a same-tab, in-place investigation.
function serviceDetailStarters(name: string): CoreCopilotStarterQuestion[] {
  return [
    {
      label: `Summarize the operational health of ${name}.`,
      specialistId: "resource_health_observability",
      tool: "incidents",
      toolArguments: {},
    },
    {
      label: `What depends on ${name}?`,
      specialistId: "resource_health_observability",
      tool: "impact_context",
      toolArguments: { subject: name },
    },
    {
      label: `Search related evidence for ${name}.`,
      specialistId: "resource_health_observability",
      tool: "search",
      toolArguments: { query: name },
    },
  ];
}

// Operational twin hints stay on the network specialist that owns the twin
// page mapping; every tool exists in the manifest catalog (D-03, D-05).
const TWIN_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Which business services are affected if this changes?",
    specialistId: "network",
    toolArguments: {},
  },
  {
    label: "Show the topology and dependencies for this resource.",
    specialistId: "network",
    tool: "network_topology",
    toolArguments: {},
  },
  {
    label: "What depends on this hub or resource?",
    specialistId: "network",
    toolArguments: {},
  },
];

function isCoreCopilotInput(
  input: CoreCopilotAdapterInput | object,
): input is CoreCopilotAdapterInput {
  return "records" in input;
}

function isCanonicalAzureResourceId(value: string | undefined): value is string {
  const parts = String(value ?? "").split("/").filter(Boolean);
  const providerIndex = parts.findIndex((part) => part.toLowerCase() === "providers");
  return (
    String(value ?? "").startsWith("/")
    && parts[0]?.toLowerCase() === "subscriptions"
    && Boolean(parts[1])
    && parts[2]?.toLowerCase() === "resourcegroups"
    && Boolean(parts[3])
    && providerIndex === 4
    && parts.length > providerIndex + 2
  );
}

function coreRecordSourceKey(record: CoreCopilotRecord): string {
  const identity = String(record.identity ?? "").trim();
  if (identity) return boundedCoreSourceKey(identity);
  return `anonymous:${sha256(stableJson([
    record.namespace,
    record.kind,
    record.source,
    record.resourceId ?? "",
    record.data,
  ]))}`;
}

function coreRecordEntity(record: CoreCopilotRecord): CopilotEvidenceIdentity {
  if (isCanonicalAzureResourceId(record.resourceId)) {
    return {
      type: "azure",
      resource_id: canonicalResourceId(record.resourceId),
    };
  }
  if (record.evidenceIdentity === "observation") {
    return {
      type: "observation",
      source: boundedString("observation source", record.source, 1, 128),
      source_key: coreRecordSourceKey(record),
    };
  }
  return {
    type: "domain",
    namespace: boundedString("entity namespace", record.namespace, 1, 64),
    kind: boundedString("entity kind", record.kind, 1, 64),
    source_key: coreRecordSourceKey(record),
  };
}

function entityOrderingKey(entity: CopilotEvidenceIdentity): string {
  if (entity.type === "domain") {
    return `0:${entity.namespace}:${entity.kind}:${entity.source_key}`;
  }
  if (entity.type === "observation") {
    return `1:${entity.source}:${entity.source_key}`;
  }
  return `2:${entity.resource_id}`;
}

function normalizeFilters(
  filters: Record<string, string[]>,
  sort: Record<string, string> | undefined,
): Record<string, string[]> {
  const entries = Object.entries(filters)
    .map(([key, values]) => [
      boundedString("filter name", key, 1, 64),
      Array.from(new Set(
        values
          .map((value) => boundedFilterValue(`filter ${key}`, value))
          .filter(Boolean),
      )).sort(compareCodePoints),
    ] as const)
    .filter(([, values]) => values.length > 0);
  assertBound("page filters", entries.length, 16);
  const normalized = Object.fromEntries(
    entries.sort(([left], [right]) => compareCodePoints(left, right)),
  );
  const sortValues = Object.entries(sort ?? {})
    .map(([key, direction]) =>
      `${boundedString("sort field", key, 1, 64)}:${boundedString("sort direction", direction, 1, 16)}`)
    .sort(compareCodePoints);
  if (sortValues.length) normalized.sort = sortValues;
  return normalized;
}

function normalizeCoverage(
  inputs: CoreCopilotCoverageInput[],
): Record<string, CoreCopilotCoverage> {
  return Object.fromEntries(
    inputs
      .map((item) => {
        if (
          !Number.isInteger(item.visibleCount)
          || !Number.isInteger(item.totalCount)
          || item.visibleCount < 0
          || item.totalCount < 0
          || item.visibleCount > item.totalCount
        ) {
          throw new Error(`invalid ${item.key} coverage`);
        }
        const key = boundedString("coverage key", item.key, 1, 64);
        return [key, {
          visible_count: item.visibleCount,
          total_count: item.totalCount,
          complete: item.available !== false && item.visibleCount === item.totalCount,
          truncated: item.truncated ?? item.visibleCount < item.totalCount,
        }] as const;
      })
      .sort(([left], [right]) => compareCodePoints(left, right)),
  );
}

function coreEvidenceRow(record: CoreCopilotRecord) {
  const source = boundedString("evidence source", record.source, 1, 128);
  const entity = coreRecordEntity(record);
  const sourceKey = coreRecordSourceKey(record);
  const claimType = boundedString("claim type", record.kind, 1, 64);
  const data = {
    ...record.data,
    entity,
    source_key: sourceKey,
    claim_type: claimType,
    selected: record.selected ?? false,
    actionable: false,
    mutation_authorized: false,
  };
  assertEvidenceRowBound(data);
  return {
    priority: record.priority ?? 50,
    row: {
      evidence_id: canonicalEvidenceStableId({
        source,
        sourceKey,
        entity,
        claimType,
      }),
      ...(entity.type === "azure" ? { resource_id: entity.resource_id } : {}),
      section: source,
      status: record.status ?? "ok",
      observed_at: record.observedAt,
      data,
    },
  };
}

function sourceEvidenceRow(item: EvidenceItem) {
  const source = boundedString(
    "evidence source",
    `${item.source_engine}/${item.source_table}`,
    1,
    128,
  );
  const canonicalResource = isCanonicalAzureResourceId(item.resource_id ?? undefined)
    ? canonicalResourceId(item.resource_id!)
    : undefined;
  const sourceKey = boundedCoreSourceKey(
    canonicalResource ?? `${item.source_engine}:${item.source_table}`,
  );
  const entity: CopilotEvidenceIdentity = canonicalResource
    ? { type: "azure", resource_id: canonicalResource }
    : {
        type: "observation",
        source,
        source_key: sourceKey,
      };
  const data = {
    entity,
    source_key: sourceKey,
    claim_type: "source_observation",
    source_engine: item.source_engine,
    source_table: item.source_table,
    confidence: item.confidence,
    freshness: item.freshness,
    selected: false,
    actionable: false,
    mutation_authorized: false,
  };
  assertEvidenceRowBound(data);
  return {
    priority: 40,
    row: {
      evidence_id: canonicalEvidenceStableId({
        source,
        sourceKey,
        entity,
        claimType: "source_observation",
      }),
      ...(canonicalResource ? { resource_id: canonicalResource } : {}),
      section: source,
      status: (item.freshness === "unknown" ? "unavailable" : "ok") as CopilotSnapshotStatus,
      observed_at: item.timestamp,
      data,
    },
  };
}

function coverageEvidenceRows(coverage: Record<string, CoreCopilotCoverage>) {
  return Object.entries(coverage).map(([key, value]) => {
    const entity: CopilotEvidenceIdentity = {
      type: "observation",
      source: "page/coverage",
      source_key: key,
    };
    return {
      evidence_id: canonicalEvidenceStableId({
        source: "page/coverage",
        sourceKey: key,
        entity,
        claimType: "coverage",
      }),
      section: "coverage",
      status: (
        !value.complete && value.visible_count === 0 && value.total_count === 0
          ? "unavailable"
          : "ok"
      ) as CopilotSnapshotStatus,
      observed_at: undefined,
      data: {
        entity,
        source_key: key,
        claim_type: "coverage",
        coverage: value,
        selected: false,
        actionable: false,
        mutation_authorized: false,
      },
    };
  });
}

function normalizedFreshness(sourceStatuses: CoreCopilotSourceStatus[]) {
  const bySource = new Map<string, CoreCopilotSourceStatus>();
  for (const item of sourceStatuses) {
    const source = boundedString("freshness source", item.source, 1, 128);
    const candidate = { ...item, source };
    const current = bySource.get(source);
    if (
      !current
      || FRESHNESS_WARNING_PRIORITY[candidate.status]
        > FRESHNESS_WARNING_PRIORITY[current.status]
      || (
        candidate.status === current.status
        && (candidate.observedAt ?? "") > (current.observedAt ?? "")
      )
    ) {
      bySource.set(source, candidate);
    }
  }
  return Array.from(bySource.values())
    .sort((left, right) => compareCodePoints(left.source, right.source))
    .map((item) => ({
      source: item.source,
      observed_at: item.observedAt || "unknown",
      status: item.status,
    }));
}

function buildCoreCopilotContext(
  config: { pageKind: CopilotPageKind; pageId: string },
  input: CoreCopilotAdapterInput,
  starters: CoreCopilotStarterQuestion[],
): CoreCopilotContext {
  const declaredCoverage = normalizeCoverage(input.coverage);
  const selectedRecords = input.records.filter((record) => record.selected);
  const selectedEntities = selectedRecords
    .map(coreRecordEntity)
    .filter((entity): entity is CopilotEntityRef => entity.type !== "observation")
    .filter((entity, index, entities) =>
      entities.findIndex((candidate) =>
        entityOrderingKey(candidate) === entityOrderingKey(entity)) === index)
    .sort((left, right) =>
      compareCodePoints(entityOrderingKey(left), entityOrderingKey(right)))
    .slice(0, COPILOT_SNAPSHOT_LIMITS.selectedEntities);
  const selectedResources = selectedRecords
    .filter((record) => isCanonicalAzureResourceId(record.resourceId))
    .map((record) => ({
      resource_id: canonicalResourceId(record.resourceId!),
      resource_type: record.resourceType || "Microsoft.Resources/resources",
      ...(record.name ? { name: record.name } : {}),
    }))
    .filter((resource, index, resources) =>
      resources.findIndex((candidate) =>
        candidate.resource_id === resource.resource_id) === index)
    .slice(0, COPILOT_SNAPSHOT_LIMITS.selectedEntities);

  const candidates = [
    ...input.records.map(coreEvidenceRow),
    ...input.evidence.map(sourceEvidenceRow),
  ].sort((left, right) =>
    left.priority - right.priority
    || compareCodePoints(left.row.evidence_id, right.row.evidence_id));
  type CandidateEvidenceRow =
    | ReturnType<typeof coreEvidenceRow>["row"]
    | ReturnType<typeof sourceEvidenceRow>["row"];
  const candidateEvidence = new Map<string, CandidateEvidenceRow>();
  const retainedCandidateIds: string[] = [];
  const candidateLimit = Math.max(
    0,
    COPILOT_SNAPSHOT_LIMITS.evidenceRows - Object.keys(declaredCoverage).length,
  );
  for (const candidate of candidates) {
    const existing = candidateEvidence.get(candidate.row.evidence_id);
    if (!existing || (candidate.row.observed_at ?? "") > (existing.observed_at ?? "")) {
      candidateEvidence.set(candidate.row.evidence_id, candidate.row);
    }
    if (!existing && retainedCandidateIds.length < candidateLimit) {
      retainedCandidateIds.push(candidate.row.evidence_id);
    }
  }
  const freshness = normalizedFreshness(input.sourceStatuses);
  assertBound("freshness records", freshness.length, COPILOT_SNAPSHOT_LIMITS.freshnessRecords);

  const rowLimitApplied = candidateEvidence.size > candidateLimit;
  let byteLimitApplied = false;
  const buildSnapshot = () => {
    const omittedCount = candidateEvidence.size - retainedCandidateIds.length;
    const coverage = Object.fromEntries(
      Object.entries(declaredCoverage).map(([key, value]) => [
        key,
        omittedCount
          ? { ...value, complete: false, truncated: true }
          : value,
      ]),
    );
    const retention = {
      input_count: candidateEvidence.size,
      retained_count: retainedCandidateIds.length,
      omitted_count: omittedCount,
      row_limit: COPILOT_SNAPSHOT_LIMITS.evidenceRows,
      byte_limit: COPILOT_SNAPSHOT_LIMITS.snapshotBytes,
      reasons: [
        ...(rowLimitApplied ? ["row_limit"] : []),
        ...(byteLimitApplied ? ["byte_limit"] : []),
      ],
    };
    const coverageRows = coverageEvidenceRows(coverage).map((row, index) =>
      index === 0
        ? {
          ...row,
          data: {
            ...row.data,
            retention,
          },
        }
        : row);
    const evidence = [
      ...retainedCandidateIds.flatMap((id) => {
        const row = candidateEvidence.get(id);
        return row ? [row] : [];
      }),
      ...coverageRows,
    ].sort((left, right) => compareCodePoints(left.evidence_id, right.evidence_id));
    const snapshot = services.buildCopilotSnapshot({
      pageKind: config.pageKind,
      pageId: config.pageId,
      scope: input.scope,
      filters: normalizeFilters(input.filters, input.sort),
      selectedResources,
      evidence,
      freshness,
    });
    return { coverage, snapshot };
  };
  let built = buildSnapshot();
  const strictSnapshotFits = (snapshot: CopilotPageSnapshot): boolean => {
    try {
      normalizeCopilotSnapshotV2(snapshot);
      return true;
    } catch (error) {
      if (
        error instanceof Error
        && error.message
          === `snapshot exceeds limit of ${COPILOT_SNAPSHOT_LIMITS.snapshotBytes}`
      ) {
        return false;
      }
      throw error;
    }
  };
  while (
    (
      new TextEncoder().encode(stableJson(built.snapshot)).length
        + numericValueCount(built.snapshot)
        > COPILOT_SNAPSHOT_LIMITS.snapshotBytes
      || !strictSnapshotFits(built.snapshot)
    )
    && retainedCandidateIds.length > 0
  ) {
    retainedCandidateIds.pop();
    byteLimitApplied = true;
    built = buildSnapshot();
  }
  const { coverage, snapshot } = built;
  const omittedCount = candidateEvidence.size - retainedCandidateIds.length;
  if (!strictSnapshotFits(snapshot)) {
    throw new Error(
      `snapshot exceeds limit of ${COPILOT_SNAPSHOT_LIMITS.snapshotBytes}`,
    );
  }
  assertBound(
    "snapshot",
    new TextEncoder().encode(stableJson(snapshot)).length + numericValueCount(snapshot),
    COPILOT_SNAPSHOT_LIMITS.snapshotBytes,
  );

  return {
    disposition: "integrated",
    requestedScope: input.scope,
    snapshot,
    selectedEntities,
    coverage,
    uncertainty: [
      ...Object.entries(coverage)
        .filter(([, item]) => item.truncated)
        .map(([key]) => `${key} coverage is truncated`),
      ...(omittedCount
        ? [`evidence retention omitted ${omittedCount} rows`]
        : []),
      ...freshness
        .filter((item) => item.status !== "fresh")
        .map((item) => `${item.source} freshness is ${item.status}`),
    ],
    starterQuestions: starters,
  };
}

function envelopeTotal(envelope: Envelope<unknown[]> | null | undefined): number {
  return envelope?.pagination?.total ?? envelope?.data.length ?? 0;
}

function evidenceFreshness(value: EvidenceItem["freshness"]): CopilotFreshnessStatusV2 {
  if (value === "fresh") return "fresh";
  if (value === "aging") return "partial";
  if (value === "stale") return "stale";
  return "unavailable";
}

function envelopeSourceStatus(
  source: string,
  envelope: Envelope<unknown> | null | undefined,
): CoreCopilotSourceStatus {
  if (!envelope) return { source, observedAt: "unknown", status: "unavailable" };
  const evidence = envelope.evidence ?? [];
  const reportedStatuses = Object.values(envelope.source_status ?? {}).map(freshnessStatus);
  const statuses = evidence.length
    ? evidence.map((item) => evidenceFreshness(item.freshness))
    : reportedStatuses;
  const status = statuses.length
    ? statuses.reduce((current, candidate) =>
      FRESHNESS_WARNING_PRIORITY[candidate] > FRESHNESS_WARNING_PRIORITY[current]
        ? candidate
        : current)
    : "unavailable";
  const observedAt = evidence.reduce(
    (latest, item) => item.timestamp > latest ? item.timestamp : latest,
    envelope.live_observed_at ?? "",
  );
  return { source, observedAt: observedAt || "unknown", status };
}

function overviewCoreInput(input: OverviewCopilotPageInput): CoreCopilotAdapterInput {
  const loadedSituations = input.situations?.data ?? [];
  const situationsById = new Map(
    loadedSituations.map((situation) => [situation.situation_id, situation]),
  );
  const situations = input.visibleSituationIds
    ? input.visibleSituationIds.flatMap((id) => {
      const situation = situationsById.get(id);
      return situation ? [situation] : [];
    })
    : loadedSituations;
  const connections = input.connections?.data ?? [];
  const records: CoreCopilotRecord[] = [
    ...situations.slice(0, 50).map((situation, index) => ({
      identity: situation.situation_id,
      namespace: "operations",
      kind: "situation",
      source: "situations/visible",
      observedAt: situation.last_observed_at,
      priority: index,
      data: {
        title: situation.title,
        priority: situation.priority,
        severity: situation.severity,
        lifecycle_state: situation.lifecycle_state,
        owner: situation.owner,
        support_team: situation.support_team,
        affected_resource_ids: situation.affected_resource_ids,
        evidence_state: situation.evidence_state,
      },
    })),
    ...(input.network ? [{
      identity: "network-summary",
      namespace: "operations",
      kind: "network_summary",
      source: "network/summary",
      priority: 60,
      data: { ...input.network.data },
    }] : []),
    ...(input.vulnerabilities ? [{
      identity: "vulnerability-summary",
      namespace: "operations",
      kind: "vulnerability_summary",
      source: "vulnerability/summary",
      priority: 60,
      data: {
        cve_count: input.vulnerabilities.data.cve_count,
        affected_server_count: input.vulnerabilities.data.affected_server_count,
        reachable_server_count: input.vulnerabilities.data.reachable_server_count,
        internet_exposed_count: input.vulnerabilities.data.internet_exposed_count,
        critical_count: input.vulnerabilities.data.critical_count,
      },
    }] : []),
    ...connections.slice(0, 25).map((connection) => ({
      identity: connection.connection_id,
      namespace: "connections",
      kind: "subscription_connection",
      source: "connections/visible",
      observedAt: connection.last_successful_sync_at ?? connection.last_synced_at ?? undefined,
      priority: 70,
      data: {
        name: connection.name,
        subscription_id: connection.subscription_id,
        business_service: connection.business_service,
        application: connection.application,
        environment: connection.environment,
        owner: connection.owner,
        support_team: connection.support_team,
        criticality: connection.criticality,
        health_status: connection.health_status,
        sync_status: connection.sync_status,
      },
    })),
  ];
  return {
    scope: input.scope,
    filters: { view: ["overview"] },
    sort: { situation_priority: "asc" },
    records,
    evidence: [
      ...(input.situations?.evidence ?? []),
      ...(input.network?.evidence ?? []),
      ...(input.vulnerabilities?.evidence ?? []),
      ...(input.connections?.evidence ?? []),
    ],
    coverage: [
      {
        key: "situations",
        visibleCount: Math.min(situations.length, 50),
        totalCount: envelopeTotal(input.situations),
        truncated: situations.length > 50 || envelopeTotal(input.situations) > 50,
        available: Boolean(input.situations),
      },
      {
        key: "connections",
        visibleCount: Math.min(connections.length, 25),
        totalCount: envelopeTotal(input.connections),
        truncated: connections.length > 25 || envelopeTotal(input.connections) > 25,
        available: Boolean(input.connections),
      },
    ],
    sourceStatuses: [
      envelopeSourceStatus("connections", input.connections),
      envelopeSourceStatus("network", input.network),
      envelopeSourceStatus("situations", input.situations),
      envelopeSourceStatus("vulnerabilities", input.vulnerabilities),
    ],
  };
}

function collectionCoverage(
  key: string,
  visibleCount: number,
  totalCount: number,
  coverage?: CollectionCoverage,
  available = true,
): CoreCopilotCoverageInput {
  const total = coverage?.total ?? totalCount;
  return {
    key,
    visibleCount,
    totalCount: Math.max(visibleCount, total),
    truncated: coverage?.truncated ?? visibleCount < total,
    available,
  };
}

function networkCoreInput(input: NetworkCopilotPageInput): CoreCopilotAdapterInput {
  const topology = input.topology?.data.topology;
  const gaps = input.gaps?.data.gaps ?? [];
  const findings = input.findings?.data.findings ?? [];
  const bypassGaps = input.bypass?.data.gaps ?? [];
  const records: CoreCopilotRecord[] = [
    ...(input.topology ? [{
      identity: "network-summary",
      namespace: "network",
      kind: "topology_summary",
      source: "network/topology",
      priority: 0,
      data: {
        summary: input.topology.data.summary,
        connection_ids: topology?.connection_ids ?? [],
        unresolved_peer_vnet_ids: topology?.unresolved_peer_vnet_ids ?? [],
      },
    }] : []),
    ...(topology?.hubs ?? []).slice(0, 50).map((hub) => ({
      identity: hub.vnet_id,
      namespace: "network",
      kind: "virtual_network",
      source: "network/topology",
      resourceId: hub.vnet_id,
      resourceType: "Microsoft.Network/virtualNetworks",
      name: hub.name,
      selected: true,
      priority: 1,
      data: {
        name: hub.name,
        role: hub.role,
        connection_id: hub.connection_id,
        subscription_id: hub.subscription_id,
        peer_count: hub.peer_count,
        signals: hub.signals,
      },
    })),
    ...bypassGaps.map((gap) => networkGapRecord(gap, "network/firewall-bypass", 5)),
    ...gaps.map((gap) => networkGapRecord(gap, "network/gaps", 10)),
    ...findings.map((finding) => ({
      identity: finding.finding_id,
      namespace: "network",
      kind: "rule_finding",
      source: "network/rule-findings",
      resourceId: finding.affected_resource_ids?.find(isCanonicalAzureResourceId),
      priority: 20,
      data: {
        check: finding.category,
        finding: finding.title,
        issue: finding.detail,
        compliant: false,
        severity: finding.severity,
        rule_id: finding.rule_id,
        rule_name: finding.rule_name,
        control: finding.control,
        control_id: finding.control_id,
        recommendation: finding.recommendation,
        connection_id: finding.connection_id,
        subscription_id: finding.subscription_id,
        environment: finding.environment,
        evidence: finding.evidence,
      },
    })),
  ];
  const gapTotal = input.gaps?.pagination?.total
    ?? input.gaps?.data.coverage?.total
    ?? input.gaps?.data.summary.gap_count
    ?? gaps.length;
  const findingTotal = input.findings?.pagination?.total
    ?? input.findings?.data.coverage?.total
    ?? input.findings?.data.summary.rule_finding_count
    ?? findings.length;
  return {
    scope: input.scope,
    filters: {
      tab: [input.tab],
      gap_page: [String(input.gapOffset), String(input.gapLimit)],
      finding_page: [String(input.findingOffset), String(input.findingLimit)],
    },
    records,
    evidence: [
      ...(input.topology?.evidence ?? []),
      ...(input.gaps?.evidence ?? []),
      ...(input.findings?.evidence ?? []),
      ...(input.bypass?.evidence ?? []),
    ],
    coverage: [
      collectionCoverage(
        "gaps",
        gaps.length,
        gapTotal,
        input.gaps?.data.coverage,
        Boolean(input.gaps),
      ),
      collectionCoverage(
        "rule_findings",
        findings.length,
        findingTotal,
        input.findings?.data.coverage,
        Boolean(input.findings),
      ),
    ],
    sourceStatuses: [
      envelopeSourceStatus("network_bypass", input.bypass),
      envelopeSourceStatus("network_gaps", input.gaps),
      envelopeSourceStatus("network_rule_findings", input.findings),
      envelopeSourceStatus("network_topology", input.topology),
    ],
  };
}

function networkGapRecord(
  gap: NetworkGap,
  source: string,
  priority: number,
): CoreCopilotRecord {
  return {
    identity: gap.gap_id,
    namespace: "network",
    kind: source.endsWith("firewall-bypass") ? "firewall_bypass" : "network_gap",
    source,
    resourceId: isCanonicalAzureResourceId(gap.resource_id) ? gap.resource_id : undefined,
    resourceType: gap.resource_type,
    name: gap.resource_name,
    priority,
    data: {
      check: source.endsWith("firewall-bypass") ? "firewall" : gap.category,
      finding: gap.title,
      issue: gap.detail,
      compliant: false,
      severity: gap.severity,
      resource_id: gap.resource_id,
      resource_name: gap.resource_name,
      resource_type: gap.resource_type,
      recommendation: gap.recommendation,
      basis: gap.basis,
      connection_id: gap.connection_id,
      subscription_id: gap.subscription_id,
      environment: gap.environment,
      vnet_id: gap.vnet_id,
      evidence: gap.evidence,
    },
  };
}

function complianceCoreInput(
  input: ComplianceCopilotPageInput,
): CoreCopilotAdapterInput {
  const violationSources = [
    "topology",
    "network_gaps",
    "network_rule_findings",
    "vulnerability_exposure",
  ];
  const deviationSources = ["policy_deviations", "security_deviations"];
  const sourcesAvailable = (sources: string[]) =>
    !input.sourceEnvelopes
    || sources.every((source) => Boolean(input.sourceEnvelopes?.[source]));
  const records: CoreCopilotRecord[] = [
    ...input.violations.map((violation) => ({
      identity: violation.id,
      namespace: "compliance",
      kind: "policy_violation",
      source: "compliance/violations",
      resourceId: isCanonicalAzureResourceId(violation.resource)
        ? violation.resource
        : undefined,
      selected: violation.id === input.selectedId,
      priority: violation.id === input.selectedId ? 0 : 10,
      data: {
        type: violation.type,
        severity: violation.severity,
        title: violation.title,
        detail: violation.detail,
        resource: violation.resource,
        application: violation.application,
        business_service: violation.businessService,
        owner: violation.owner,
        affected_traffic: violation.affectedTraffic,
        vulnerability_exposure: violation.vulnerabilityExposure,
        remediation: violation.remediation,
      },
    })),
    ...input.governedDeviations.map((deviation) => ({
      identity: deviation.deviation_id,
      namespace: "compliance",
      kind: "governed_deviation",
      source: "compliance/deviations",
      observedAt: deviation.observed_at,
      resourceId: isCanonicalAzureResourceId(deviation.resource)
        ? deviation.resource
        : undefined,
      selected: deviation.deviation_id === input.selectedId,
      priority: deviation.deviation_id === input.selectedId ? 0 : 20,
      data: {
        kind: deviation.kind,
        severity: deviation.severity,
        control: deviation.control,
        status: deviation.status,
        resource: deviation.resource,
        application: deviation.application,
        business_service: deviation.business_service,
        environment: deviation.environment,
        business_criticality: deviation.business_criticality,
        subscription: deviation.subscription,
      },
    })),
  ];
  return {
    scope: input.scope,
    filters: {
      policy: [input.policyName],
      ...(input.selectedId
        ? { selected: [boundedCoreSourceKey(input.selectedId)] }
        : {}),
    },
    sort: { severity: "desc" },
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "violations",
        visibleCount: input.violations.length,
        totalCount: input.violations.length,
        available: sourcesAvailable(violationSources),
      },
      {
        key: "governed_deviations",
        visibleCount: input.governedDeviations.length,
        totalCount: input.governedDeviations.length,
        available: sourcesAvailable(deviationSources),
      },
    ],
    sourceStatuses: Object.entries(input.sourceEnvelopes ?? {})
      .map(([source, envelope]) => envelopeSourceStatus(source, envelope)),
  };
}

function exposureCoverage(
  key: string,
  section?: ExposureCopilotSection<unknown> | null,
): CoreCopilotCoverageInput {
  const visible = section?.loadedCount ?? 0;
  const total = Math.max(visible, section?.totalCount ?? 0);
  return {
    key,
    visibleCount: visible,
    totalCount: total,
    truncated: visible < total,
    available: section?.available ?? false,
  };
}

function exposureSectionStatus(
  source: string,
  section?: ExposureCopilotSection<unknown> | null,
): CoreCopilotSourceStatus | null {
  if (!section) return null;
  return {
    source,
    observedAt: section.observedAt,
    status: section.available ? section.freshness : "unavailable",
  };
}

function exposureCoreInput(input: ExposureCopilotPageInput): CoreCopilotAdapterInput {
  const summaryValue = input.summary?.value ?? null;
  const patchRows = input.patchPriorities?.value ?? [];
  const assetRows = input.assets?.value ?? [];
  const defenderValue = input.defender?.value ?? null;
  const slaValue = input.sla?.value ?? null;
  const exceptionRows = input.riskExceptions?.value ?? [];
  const records: CoreCopilotRecord[] = [
    ...(summaryValue ? [{
      identity: "vulnerability-summary",
      namespace: "vulnerability",
      kind: "vulnerability_summary",
      source: "exposure/summary",
      observedAt: input.summary?.observedAt,
      priority: 0,
      data: {
        cve_count: summaryValue.cve_count,
        affected_asset_count: summaryValue.affected_asset_count,
        affected_business_service_count: summaryValue.affected_business_service_count,
        critical_count: summaryValue.critical_count,
        reachable_server_count: summaryValue.reachable_server_count,
        internet_exposed_count: summaryValue.internet_exposed_count,
      },
    }] : []),
    ...patchRows.slice(0, 50).map((patch, index) => ({
      identity: patch.priority_id,
      namespace: "vulnerability",
      kind: "patch_priority",
      source: "exposure/patch-priorities",
      observedAt: input.patchPriorities?.observedAt,
      priority: 10 + index,
      data: {
        kb_id: patch.kb_id,
        cve_ids: patch.cve_ids,
        priority_score: patch.priority_score,
        affected_server_count: patch.affected_server_count,
        recommended_action: patch.recommended_action,
      },
    })),
    ...assetRows.slice(0, 50).map((asset, index) => ({
      identity: asset.asset_id,
      namespace: "vulnerability",
      kind: "asset_exposure",
      source: "exposure/assets",
      resourceId: asset.asset_id,
      resourceType: asset.resource_type,
      name: asset.name,
      observedAt: input.assets?.observedAt,
      priority: 30 + index,
      data: {
        business_service: asset.business_service,
        application: asset.application,
        cve_count: asset.cve_count,
        critical_count: asset.critical_count,
        network_exposure: asset.network_exposure,
        reachable: asset.reachable,
      },
    })),
    ...(defenderValue ? [{
      identity: "defender-overview",
      namespace: "vulnerability",
      kind: "defender_overview",
      source: "exposure/defender",
      observedAt: input.defender?.observedAt,
      priority: 60,
      data: {
        active_alert_count: defenderValue.active_alert_count,
        critical_alert_count: defenderValue.critical_alert_count,
        attack_path_count: defenderValue.attack_path_count,
        unhealthy_recommendation_count: defenderValue.unhealthy_recommendation_count,
      },
    }] : []),
    ...(slaValue ? [{
      identity: "sla-compliance",
      namespace: "vulnerability",
      kind: "sla_compliance",
      source: "exposure/sla",
      priority: 65,
      data: {
        open_count: slaValue.open_count,
        overdue_count: slaValue.overdue_count,
        overall_compliance_rate: slaValue.overall_compliance_rate,
      },
    }] : []),
    ...exceptionRows.slice(0, 50).map((exception, index) => ({
      identity: exception.exception_id,
      namespace: "vulnerability",
      kind: "risk_exception",
      source: "exposure/risk-exceptions",
      observedAt: input.riskExceptions?.observedAt,
      priority: 70 + index,
      data: {
        cve_id: exception.cve_id,
        server_id: exception.server_id,
        expires_at: exception.expires_at,
        approved_by: exception.approved_by,
      },
    })),
  ];
  const sourceStatuses = [
    exposureSectionStatus("summary", input.summary),
    exposureSectionStatus("patch_priorities", input.patchPriorities),
    exposureSectionStatus("assets", input.assets),
    exposureSectionStatus("defender", input.defender),
    exposureSectionStatus("sla", input.sla),
    exposureSectionStatus("risk_exceptions", input.riskExceptions),
  ].filter((status): status is CoreCopilotSourceStatus => status !== null);
  return {
    scope: input.scope,
    filters: { view: ["exposure"] },
    records,
    evidence: [
      ...(input.summary?.evidence ?? []),
      ...(input.patchPriorities?.evidence ?? []),
      ...(input.assets?.evidence ?? []),
      ...(input.defender?.evidence ?? []),
      ...(input.sla?.evidence ?? []),
      ...(input.riskExceptions?.evidence ?? []),
    ],
    coverage: [
      exposureCoverage("patch_priorities", input.patchPriorities),
      exposureCoverage("assets", input.assets),
      exposureCoverage("risk_exceptions", input.riskExceptions),
    ],
    sourceStatuses,
  };
}

function cveDetailCoreInput(input: CveDetailCopilotPageInput): CoreCopilotAdapterInput {
  const requestedCveId = input.cveId.trim().toUpperCase();
  const cve = input.cve?.cve_id.trim().toUpperCase() === requestedCveId
    ? input.cve
    : null;
  const findingRows = (input.findings.rows ?? []).filter(
    (finding) => finding.weakness_id?.trim().toUpperCase() === requestedCveId,
  );
  const attackGraph = input.attack?.graph ?? null;
  const cveSource = input.sources.find((source) => source.key === "nvd");
  const records: CoreCopilotRecord[] = [
    ...(cve ? [{
      identity: cve.cve_id,
      namespace: "vulnerability",
      kind: "cve",
      source: "exposure/cve",
      selected: true,
      priority: 0,
      data: {
        title: cve.title,
        description: cve.description,
        severity: cve.severity,
        cvss: cve.cvss,
        epss_score: cve.epss_score ?? undefined,
        epss_percentile: cve.epss_percentile ?? undefined,
        is_known_exploited: cve.is_known_exploited,
        kev_date_added: cve.kev_date_added,
        kev_due_date: cve.kev_due_date,
        kev_ransomware_use: cve.kev_ransomware_use,
        associated_kbs: cve.associated_kbs,
      },
    }] : []),
    ...(cve?.associated_kbs ?? []).slice(0, 50).map((kb, index) => ({
      identity: kb,
      namespace: "vulnerability",
      kind: "kb",
      source: "exposure/cve-kbs",
      priority: 5 + index,
      data: { kb_id: kb, cve_id: cve?.cve_id },
    })),
    ...findingRows.slice(0, 50).map((finding, index) => ({
      identity: finding.target_id ?? finding.exposure_id ?? `finding-${index}`,
      namespace: "vulnerability",
      kind: "cve_finding",
      source: "exposure/cve-findings",
      resourceId: finding.target_id,
      observedAt: input.findings.observedAt,
      priority: 20 + index,
      data: {
        exposure_id: finding.exposure_id,
        business_service: finding.business_service,
        application: finding.application,
        environment: finding.environment,
        severity: finding.severity,
        target_kind: finding.target_kind,
        current_state: finding.current_state,
        represented_workload_count: finding.represented_workload_count,
        total_workload_count: finding.total_workload_count,
        missing_kb: finding.missing_kb,
        reachable: finding.reachable,
        network_exposure: finding.network_exposure,
        overdue: finding.overdue,
      },
    })),
    ...(attackGraph?.nodes ?? []).slice(0, 50).map((node, index) => ({
      identity: node.id,
      namespace: "vulnerability",
      kind: "attack_path_node",
      source: "exposure/attack-path",
      observedAt: input.attack?.observedAt,
      priority: 50 + index,
      data: {
        node_kind: node.kind,
        label: node.label,
        business_service: node.business_service,
        reachable: node.reachable,
      },
    })),
  ];
  const sourceStatuses: CoreCopilotSourceStatus[] = [
    {
      source: "cve",
      observedAt: cveSource?.observedAt,
      status: (
        cve && cveSource?.available
          ? cveSource.freshness
          : "unavailable"
      ) as CopilotFreshnessStatusV2,
    },
    {
      source: "findings",
      observedAt: input.findings.observedAt,
      status: input.findings.available ? input.findings.freshness : "unavailable",
    },
    ...(input.attack ? [{
      source: "attack_path",
      observedAt: input.attack.observedAt,
      status: (input.attack.available ? input.attack.freshness : "unavailable") as CopilotFreshnessStatusV2,
    }] : []),
    ...input.sources.map((source) => ({
      source: source.key,
      observedAt: source.observedAt,
      status: (source.available ? source.freshness : "unavailable") as CopilotFreshnessStatusV2,
    })),
  ];
  return {
    scope: input.scope,
    filters: input.filters ?? {},
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "findings",
        visibleCount: Math.min(input.findings.loadedCount, 50),
        totalCount: Math.max(input.findings.loadedCount, input.findings.totalCount),
        truncated: Math.min(input.findings.loadedCount, 50) < input.findings.totalCount,
        available: input.findings.available,
      },
      {
        key: "associated_kbs",
        visibleCount: Math.min(cve?.associated_kbs.length ?? 0, 50),
        totalCount: cve?.associated_kbs.length ?? 0,
        truncated: (cve?.associated_kbs.length ?? 0) > 50,
        available: Boolean(cve),
      },
      ...(input.attack ? [{
        key: "attack_path",
        visibleCount: Math.min(attackGraph?.nodes.length ?? 0, 50),
        totalCount: attackGraph?.nodes.length ?? 0,
        truncated: (attackGraph?.nodes.length ?? 0) > 50,
        available: input.attack.available,
      }] : []),
    ],
    sourceStatuses,
  };
}

function cveDetailStarters(input: CveDetailCopilotPageInput): CoreCopilotStarterQuestion[] {
  const cveId = input.cveId.trim().toUpperCase();
  return [
    {
      label: `Explain ${cveId}`,
      specialistId: "vulnerability",
      tool: "cve_detail",
      toolArguments: { cve_id: cveId },
    },
    ...(input.attack ? [{
      label: `Show the blast radius of ${cveId}`,
      specialistId: "vulnerability",
      tool: "cve_attack_path",
      toolArguments: { cve_id: cveId },
    }] : []),
  ];
}

function defenderPostureCoreInput(
  input: DefenderPostureCopilotPageInput,
): CoreCopilotAdapterInput {
  const overviewValue = input.overview?.value ?? null;
  const scoreValue = input.secureScore?.value ?? null;
  const findingRows = input.findings?.value ?? [];
  const alertRows = input.alerts?.value ?? [];
  const attackRows = input.attackPaths?.value ?? [];
  const containerRows = input.containers?.value ?? [];
  const selectedAssetId = input.selectedAssetId ?? null;
  const records: CoreCopilotRecord[] = [
    ...(overviewValue ? [{
      identity: "defender-overview",
      namespace: "vulnerability",
      kind: "defender_overview",
      source: "defender/overview",
      observedAt: input.overview?.observedAt,
      priority: 0,
      data: {
        active_alert_count: overviewValue.active_alert_count,
        critical_alert_count: overviewValue.critical_alert_count,
        attack_path_count: overviewValue.attack_path_count,
        unhealthy_recommendation_count: overviewValue.unhealthy_recommendation_count,
        vulnerable_container_image_count: overviewValue.vulnerable_container_image_count,
        container_image_cve_count: overviewValue.container_image_cve_count,
      },
    }] : []),
    ...(scoreValue ? [{
      identity: "defender-secure-score",
      namespace: "vulnerability",
      kind: "defender_secure_score",
      source: "defender/secure-score",
      observedAt: input.secureScore?.observedAt,
      priority: 2,
      data: {
        current: scoreValue.current,
        max: scoreValue.max,
        percentage: scoreValue.percentage,
      },
    }] : []),
    ...findingRows.slice(0, 50).map((finding, index) => ({
      identity: finding.assessment_id,
      namespace: "vulnerability",
      kind: "defender_finding",
      source: "defender/recommendations",
      resourceId: finding.asset_id,
      resourceType: finding.resource_type,
      name: finding.asset_name,
      observedAt: finding.last_assessed_at ?? input.findings?.observedAt,
      selected: selectedAssetId != null && finding.asset_id === selectedAssetId,
      priority: 10 + index,
      data: {
        asset_name: finding.asset_name,
        defender_plan: finding.defender_plan,
        status: finding.status,
        severity: finding.severity,
        recommendation: finding.recommendation,
        business_service: finding.business_service,
        application: finding.application,
      },
    })),
    ...alertRows.slice(0, 50).map((alert, index) => ({
      identity: alert.id,
      namespace: "vulnerability",
      kind: "defender_alert",
      source: "defender/alerts",
      observedAt: alert.timeGenerated ?? input.alerts?.observedAt,
      priority: 30 + index,
      data: {
        title: alert.title,
        severity: alert.severity,
        status: alert.status,
      },
    })),
    ...attackRows.slice(0, 50).map((path, index) => ({
      identity: path.id,
      namespace: "vulnerability",
      kind: "defender_attack_path",
      source: "defender/attack-paths",
      observedAt: input.attackPaths?.observedAt,
      priority: 40 + index,
      data: {
        title: path.title,
        potential_impact: path.potentialImpact,
        node_count: path.nodeCount,
      },
    })),
    ...containerRows.slice(0, 50).map((image, index) => ({
      identity: image.id,
      namespace: "vulnerability",
      kind: "container_image_exposure",
      source: "defender/container-images",
      resourceId: image.target_resource_id,
      observedAt: input.containers?.observedAt,
      priority: 50 + index,
      data: {
        repository: image.repository,
        severity: image.severity,
        critical_count: image.critical_count,
        cve_count: image.cve_count,
      },
    })),
  ];
  const sourceStatuses = [
    exposureSectionStatus("overview", input.overview),
    exposureSectionStatus("secure_score", input.secureScore),
    exposureSectionStatus("findings", input.findings),
    exposureSectionStatus("alerts", input.alerts),
    exposureSectionStatus("attack_paths", input.attackPaths),
    exposureSectionStatus("containers", input.containers),
  ].filter((status): status is CoreCopilotSourceStatus => status !== null);
  return {
    scope: input.scope,
    filters: {
      view: ["defender-posture"],
      ...(selectedAssetId && isCanonicalAzureResourceId(selectedAssetId)
        ? { selected: [boundedCoreSourceKey(selectedAssetId)] }
        : {}),
    },
    records,
    evidence: [
      ...input.evidence,
      ...(input.overview?.evidence ?? []),
      ...(input.findings?.evidence ?? []),
      ...(input.alerts?.evidence ?? []),
      ...(input.attackPaths?.evidence ?? []),
      ...(input.containers?.evidence ?? []),
    ],
    coverage: [
      exposureCoverage("findings", input.findings),
      exposureCoverage("alerts", input.alerts),
      exposureCoverage("attack_paths", input.attackPaths),
      exposureCoverage("containers", input.containers),
    ],
    sourceStatuses,
  };
}

function kbDetailCoreInput(input: KbDetailCopilotPageInput): CoreCopilotAdapterInput {
  const kb = input.kb ?? null;
  const findingRows = input.findings.rows ?? [];
  const kbSource = input.sources.find(
    (source) => source.key === "silver_patch_snapshot",
  );
  const records: CoreCopilotRecord[] = [
    ...(kb ? [{
      identity: kb.kb_id,
      namespace: "vulnerability",
      kind: "kb",
      source: "exposure/kb",
      observedAt: input.findings.observedAt,
      selected: true,
      priority: 0,
      data: {
        title: kb.title,
        product: kb.product,
        severity: kb.severity,
        published_at: kb.published_at,
        target_date: kb.target_date,
        affected_server_count: kb.affected_server_count ?? kb.affected_servers.length,
        affected_servers_truncated: kb.affected_servers_truncated ?? false,
        affected_business_services: kb.affected_business_services,
      },
    }] : []),
    ...(kb?.cve_ids ?? []).slice(0, 50).map((cveId, index) => ({
      identity: cveId,
      namespace: "vulnerability",
      kind: "cve",
      source: "exposure/kb-cves",
      priority: 5 + index,
      data: { cve_id: cveId, kb_id: kb?.kb_id },
    })),
    ...findingRows.slice(0, 50).map((finding, index) => ({
      identity: finding.target_id ?? finding.server_id ?? `finding-${index}`,
      namespace: "vulnerability",
      kind: "kb_finding",
      source: "exposure/kb-findings",
      resourceId: finding.target_id,
      observedAt: input.findings.observedAt,
      priority: 20 + index,
      data: {
        server_id: finding.server_id,
        cve_id: finding.cve_id,
        product_name: finding.product_name,
        target_date: finding.target_date,
        application: finding.application,
        business_service: finding.business_service,
        environment: finding.environment,
        severity: finding.severity,
        reachable: finding.reachable,
        network_exposure: finding.network_exposure,
        missing_kb: finding.missing_kb,
      },
    })),
  ];
  const sourceStatuses: CoreCopilotSourceStatus[] = [
    {
      source: "kb",
      observedAt: kbSource?.observedAt,
      status: (
        kb && kbSource?.available
          ? kbSource.freshness
          : "unavailable"
      ) as CopilotFreshnessStatusV2,
    },
    {
      source: "findings",
      observedAt: input.findings.observedAt,
      status: input.findings.available ? input.findings.freshness : "unavailable",
    },
    ...input.sources.map((source) => ({
      source: source.key,
      observedAt: source.observedAt,
      status: (source.available ? source.freshness : "unavailable") as CopilotFreshnessStatusV2,
    })),
  ];
  return {
    scope: input.scope,
    filters: input.filters ?? {},
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "findings",
        visibleCount: Math.min(input.findings.loadedCount, 50),
        totalCount: Math.max(input.findings.loadedCount, input.findings.totalCount),
        truncated: Math.min(input.findings.loadedCount, 50) < input.findings.totalCount,
        available: input.findings.available,
      },
      {
        key: "associated_cves",
        visibleCount: Math.min(kb?.cve_ids.length ?? 0, 50),
        totalCount: kb?.cve_ids.length ?? 0,
        truncated: (kb?.cve_ids.length ?? 0) > 50,
        available: Boolean(kb),
      },
    ],
    sourceStatuses,
  };
}

function kbDetailStarters(input: KbDetailCopilotPageInput): CoreCopilotStarterQuestion[] {
  const kbId = input.kb?.kb_id ?? input.kbId;
  return [
    {
      label: `Explain ${kbId} and the CVEs it remediates`,
      specialistId: "patch",
      tool: "kb_detail",
      toolArguments: { kb_id: kbId },
    },
    {
      label: `Which product and publication date apply to ${kbId}?`,
      specialistId: "patch",
      tool: "kb_detail",
      toolArguments: { kb_id: kbId },
    },
    {
      label: `What should we patch first for ${kbId}?`,
      specialistId: "patch",
      tool: "patch_priorities",
      toolArguments: {},
    },
  ];
}

function patchPrioritiesCoreInput(
  input: PatchPrioritiesCopilotPageInput,
): CoreCopilotAdapterInput {
  const selectedId = input.selectedId ?? null;
  const records: CoreCopilotRecord[] = input.rows.slice(0, 50).map((row, index) => ({
    identity: row.exposure_id ?? row.target_id ?? `patch-${index}`,
    namespace: "vulnerability",
    kind: "patch_priority",
    source: "exposure/patch-priorities",
    resourceId: row.target_id,
    observedAt: input.observedAt,
    selected: selectedId != null && row.exposure_id === selectedId,
    priority: index,
    data: {
      exposure_id: row.exposure_id,
      weakness_id: row.weakness_id,
      missing_kb: row.missing_kb ?? row.kb_id,
      server_id: row.server_id,
      application: row.application,
      business_service: row.business_service,
      severity: row.severity,
      priority_score: row.priority_score,
      recommendation: row.recommendation,
      sla_state: row.sla_state,
      sla_overdue: row.sla_overdue,
    },
  }));
  const sourceStatuses: CoreCopilotSourceStatus[] = input.sourceStatuses?.length
    ? input.sourceStatuses.map((status) => ({
      source: status.source,
      observedAt: status.observedAt,
      status: status.availability === "unavailable"
        ? "unavailable"
        : freshnessStatus(status.freshness ?? "unknown"),
    }))
    : [{
      source: "patch_priorities",
      observedAt: input.observedAt,
      status: (input.available ? input.freshness : "unavailable") as CopilotFreshnessStatusV2,
    }];
  return {
    scope: input.scope,
    filters: input.filters ?? { view: ["patch-priorities"] },
    sort: input.sort,
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "patch_priorities",
        visibleCount: input.loadedCount,
        totalCount: Math.max(input.loadedCount, input.totalCount),
        truncated: input.loadedCount < input.totalCount,
        available: input.available,
      },
    ],
    sourceStatuses,
  };
}

function changesCoreInput(input: ChangesCopilotPageInput): CoreCopilotAdapterInput {
  const selectedId = input.selectedId ?? null;
  const records: CoreCopilotRecord[] = input.changes.slice(0, 50).map((change, index) => ({
    identity: change.event_id,
    namespace: "change",
    kind: "change_correlation",
    source: "changes/incident-timeline",
    observedAt: change.timestamp,
    selected: selectedId != null && change.event_id === selectedId,
    priority: index,
    data: {
      event_id: change.event_id,
      incident_id: change.incident_id,
      incident_title: change.incident_title,
      event_type: change.event_type,
      summary: change.summary,
      change_source: change.source,
      business_services: change.business_services,
      // Temporal proximity is a correlation signal, never a causal conclusion.
      correlation_basis: "temporal_proximity",
      confirmed: false,
    },
  }));
  const sourceStatuses: CoreCopilotSourceStatus[] = input.sourceStatuses?.length
    ? input.sourceStatuses.map((status) => ({
      source: status.source,
      observedAt: status.observedAt,
      status: status.availability === "unavailable"
        ? "unavailable"
        : freshnessStatus(status.freshness ?? "unknown"),
    }))
    : [{
      source: "changes",
      observedAt: input.observedAt,
      status: (input.available ? input.freshness : "unavailable") as CopilotFreshnessStatusV2,
    }];
  return {
    scope: input.scope,
    filters: input.filters ?? { view: ["changes"] },
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "changes",
        visibleCount: input.loadedCount,
        totalCount: Math.max(input.loadedCount, input.totalCount),
        truncated: input.loadedCount < input.totalCount,
        available: input.available,
      },
    ],
    sourceStatuses,
  };
}

function predeployCoreInput(input: PredeployCopilotPageInput): CoreCopilotAdapterInput {
  const change = input.change ?? null;
  const simulation = input.simulation ?? null;
  const risk = input.risk ?? null;
  const cab = input.cab ?? null;
  const records: CoreCopilotRecord[] = [
    ...(change ? [{
      identity: change.change_id ?? "proposed-change",
      namespace: "change",
      kind: "proposed_change",
      source: "predeploy/change",
      observedAt: input.observedAt,
      selected: true,
      priority: 0,
      data: {
        title: change.title,
        author: change.author,
        change_source: change.source,
        target_environment: change.target_environment,
        resource_change_count: change.resource_change_count,
      },
    }] : []),
    ...(simulation ? [{
      identity: "change-simulation",
      namespace: "change",
      kind: "change_simulation",
      source: "predeploy/simulation",
      observedAt: input.observedAt,
      priority: 5,
      data: {
        highest_severity: simulation.highest_severity,
        simulated_domains: simulation.simulated_domains,
        by_severity: simulation.by_severity,
        effect_count: simulation.effect_count,
        // Simulated effects are predicted, never observed outcomes.
        confirmed_outcome: simulation.confirmed_outcome,
        predicted: true,
        observed: false,
      },
    }] : []),
    ...(risk ? [{
      identity: "change-risk",
      namespace: "change",
      kind: "change_risk",
      source: "predeploy/risk",
      observedAt: input.observedAt,
      priority: 6,
      data: {
        score: risk.score,
        level: risk.level,
        confidence: risk.confidence,
        // Risk is a prediction, never a confirmed cause.
        confirmed_cause: risk.confirmed_cause,
        predicted: true,
        observed: false,
      },
    }] : []),
    ...(cab ? [{
      identity: "cab-recommendation",
      namespace: "change",
      kind: "cab_recommendation",
      source: "predeploy/cab",
      observedAt: input.observedAt,
      priority: 7,
      data: {
        verdict: cab.verdict,
        risk_level: cab.risk_level,
        required_approvals: cab.required_approvals,
        confirmed_cause: cab.confirmed_cause,
        predicted: true,
        observed: false,
      },
    }] : []),
    ...input.impactedResources.slice(0, 50).map((resource, index) => ({
      identity: resource.resource_id ?? `impacted-${index}`,
      namespace: "change",
      kind: "impacted_resource",
      source: "predeploy/impacted-resources",
      resourceId: resource.resource_id,
      name: resource.resource_name,
      observedAt: input.observedAt,
      priority: 20 + index,
      data: {
        resource_name: resource.resource_name,
        business_service: resource.business_service,
        environment: resource.environment,
        relationship: resource.relationship,
        // Predicted blast radius, not a confirmed impact.
        predicted: true,
        observed: false,
      },
    })),
  ];
  const sourceStatuses: CoreCopilotSourceStatus[] = [
    {
      source: "assessment",
      observedAt: input.observedAt,
      status: (input.available ? input.freshness : "unavailable") as CopilotFreshnessStatusV2,
    },
  ];
  return {
    scope: input.scope,
    filters: {
      view: ["predeploy"],
      ...(change?.target_environment
        ? { target_environment: [change.target_environment] }
        : {}),
    },
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "impacted_resources",
        visibleCount: input.impactedResources.length,
        totalCount: Math.max(input.impactedResources.length, input.impactedTotalCount),
        truncated: input.impactedTruncated
          ?? input.impactedResources.length < input.impactedTotalCount,
        available: input.available,
      },
    ],
    sourceStatuses,
  };
}

function connectionsCoreInput(input: ConnectionsCopilotPageInput): CoreCopilotAdapterInput {
  const selectedId = input.selectedConnectionId ?? null;
  const records: CoreCopilotRecord[] = input.connections.slice(0, 50).map((connection, index) => {
    const sync = String(connection.sync_status ?? "").toLowerCase();
    const health = String(connection.health_status ?? "").toLowerCase();
    // A failed or blocked sync is a distinct deployment-blocked state, never an
    // outage of the connection registry itself.
    const deploymentBlocked = ["failed", "blocked", "error"].includes(sync)
      || health === "blocked";
    return {
      identity: connection.connection_id,
      namespace: "connection",
      kind: "subscription_connection",
      source: "connections/registry",
      observedAt: connection.last_successful_sync_at ?? input.observedAt,
      selected: selectedId != null && connection.connection_id === selectedId,
      priority: index,
      data: {
        connection_id: connection.connection_id,
        name: connection.name,
        subscription_id: connection.subscription_id,
        business_service: connection.business_service,
        environment: connection.environment,
        criticality: connection.criticality,
        health_status: connection.health_status,
        sync_status: connection.sync_status,
        record_count: connection.sync_record_count ?? 0,
        last_successful_sync_at: connection.last_successful_sync_at,
        is_active: connection.is_active,
        deployment_blocked: deploymentBlocked,
      },
    };
  });
  return {
    scope: input.scope,
    filters: input.filters ?? { view: ["subscriptions"] },
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "connections",
        visibleCount: input.loadedCount,
        totalCount: Math.max(input.loadedCount, input.totalCount),
        truncated: input.loadedCount < input.totalCount,
        available: input.available,
      },
    ],
    sourceStatuses: [
      {
        source: "connections",
        observedAt: input.observedAt,
        status: (input.available ? input.freshness : "unavailable") as CopilotFreshnessStatusV2,
      },
    ],
  };
}

function fabricMedallionCoreInput(input: FabricMedallionCopilotPageInput): CoreCopilotAdapterInput {
  const records: CoreCopilotRecord[] = [
    ...input.layers.map((layer, index) => ({
      identity: layer.layer,
      namespace: "fabric",
      kind: "medallion_layer",
      source: "fabric/medallion-layers",
      observedAt: input.observedAt,
      priority: index,
      data: {
        layer: layer.layer,
        healthy: layer.healthy,
        total: layer.total,
      },
    })),
    ...input.manifest.slice(0, 50).map((entry, index) => ({
      identity: entry.projection_name,
      namespace: "fabric",
      kind: "fabric_manifest",
      source: "fabric/manifest",
      observedAt: input.observedAt,
      priority: 10 + index,
      data: {
        projection_name: entry.projection_name,
        disposition: entry.disposition,
        compatibility_version: entry.compatibility_version,
        subscription_id: entry.subscription_id,
      },
    })),
    ...(input.governance ? [{
      identity: "fabric-governance",
      namespace: "fabric",
      kind: "fabric_governance",
      source: "fabric/governance",
      observedAt: input.observedAt,
      priority: 8,
      data: {
        ownership_gap_count: input.governance.ownership_gap_count,
        tag_gap_count: input.governance.tag_gap_count,
        referential_integrity_blockers: input.governance.referential_integrity_blockers,
      },
    }] : []),
    ...(input.capacity || input.semanticReadiness || input.dataAgentReadiness || input.lineageRef ? [{
      identity: "fabric-capacity",
      namespace: "fabric",
      kind: "fabric_capacity",
      source: "fabric/capabilities",
      observedAt: input.observedAt,
      priority: 9,
      data: {
        status: input.capacity?.status ?? "unknown",
        state: input.capacity?.state,
        capacity_name: input.capacity?.capacity_name,
        semantic_status: input.semanticReadiness?.status,
        data_agent_status: input.dataAgentReadiness?.status,
        // Optional Gold/Data Agent grounding is an enrichment, never required.
        data_agent_configured: input.dataAgentReadiness?.configured ?? false,
        lineage_ref: input.lineageRef ?? undefined,
        deployment_blocked: input.deploymentBlocked ?? false,
      },
    }] : []),
  ];
  const sourceStatuses: CoreCopilotSourceStatus[] = input.sourceStatuses?.length
    ? input.sourceStatuses.map((status) => ({
      source: status.source,
      observedAt: status.observedAt ?? input.observedAt,
      status: status.availability === "unavailable"
        ? "unavailable"
        : freshnessStatus(status.freshness ?? "unknown"),
    }))
    : [{
      source: "fabric_medallion",
      observedAt: input.observedAt,
      status: (input.available ? input.freshness : "unavailable") as CopilotFreshnessStatusV2,
    }];
  return {
    scope: input.scope,
    filters: {
      view: ["fabric-medallion"],
      ...(input.subscriptionId ? { subscription: [input.subscriptionId] } : {}),
    },
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "manifest",
        visibleCount: input.manifest.length,
        totalCount: Math.max(input.manifest.length, input.manifestTotalCount ?? input.manifest.length),
        truncated: input.manifest.length < (input.manifestTotalCount ?? input.manifest.length),
        available: input.available,
      },
    ],
    sourceStatuses,
  };
}

function governanceCoreInput(input: GovernanceCopilotPageInput): CoreCopilotAdapterInput {
  const records: CoreCopilotRecord[] = [
    ...input.roles.slice(0, 50).map((role, index) => ({
      identity: role.role_id,
      namespace: "governance",
      kind: "governance_role",
      source: "governance/settings",
      observedAt: input.observedAt,
      priority: index,
      data: {
        role_id: role.role_id,
        name: role.name,
        permissions: role.permissions,
        // Ownership evidence: owner-equivalent roles are flagged, never mutated.
        privileged: role.permissions.some((permission) =>
          ["admin", "owner"].includes(String(permission).toLowerCase())),
      },
    })),
    ...input.policies.map((policy, index) => ({
      identity: policy.section,
      namespace: "governance",
      kind: "governance_policy",
      source: "governance/settings",
      observedAt: input.observedAt,
      priority: 20 + index,
      data: {
        section: policy.section,
        setting_count: policy.setting_count,
      },
    })),
    ...input.accessReviewAudiences.map((audience, index) => ({
      identity: audience,
      namespace: "governance",
      kind: "access_review_audience",
      source: "governance/access-reviews",
      observedAt: input.observedAt,
      priority: 30 + index,
      data: {
        audience,
      },
    })),
    ...input.auditExportKinds.map((kind, index) => ({
      identity: kind,
      namespace: "governance",
      kind: "audit_export_kind",
      source: "governance/exports",
      observedAt: input.observedAt,
      priority: 40 + index,
      data: {
        export_kind: kind,
      },
    })),
  ].map((record) => ({ ...record, evidenceIdentity: "observation" }));
  // Settings, access reviews, and audit exports degrade independently; an
  // unavailable review/export source never blanks the settings evidence.
  const sourceStatuses: CoreCopilotSourceStatus[] = [
    {
      source: "settings",
      observedAt: input.observedAt,
      status: (input.settingsAvailable ? input.freshness : "unavailable") as CopilotFreshnessStatusV2,
    },
    {
      source: "access_reviews",
      observedAt: input.observedAt,
      status: (input.audiencesAvailable ? input.freshness : "unavailable") as CopilotFreshnessStatusV2,
    },
    {
      source: "audit_exports",
      observedAt: input.observedAt,
      status: (input.kindsAvailable ? input.freshness : "unavailable") as CopilotFreshnessStatusV2,
    },
  ];
  return {
    scope: input.scope,
    filters: input.filters ?? { view: ["governance"] },
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "roles",
        visibleCount: input.roles.length,
        totalCount: Math.max(input.roles.length, input.rolesTotalCount ?? input.roles.length),
        truncated: input.roles.length < (input.rolesTotalCount ?? input.roles.length),
        available: input.settingsAvailable,
      },
      {
        key: "access_review_audiences",
        visibleCount: input.accessReviewAudiences.length,
        totalCount: input.accessReviewAudiences.length,
        available: input.audiencesAvailable,
      },
      {
        key: "audit_export_kinds",
        visibleCount: input.auditExportKinds.length,
        totalCount: input.auditExportKinds.length,
        available: input.kindsAvailable,
      },
    ],
    sourceStatuses,
  };
}

function identityCoreInput(input: IdentityCopilotPageInput): CoreCopilotAdapterInput {
  const selectedId = input.selectedPrincipalId ?? null;
  const records: CoreCopilotRecord[] = [
    // Principals are non-ARM domain identities; the principal id is redacted
    // from every scope-validated Azure resource field (T-11-29).
    ...input.principals.slice(0, 50).map((principal, index) => ({
      identity: principal.principal_id,
      namespace: "identity",
      kind: "identity_principal",
      source: "identity/principals",
      observedAt: input.observedAt,
      selected: selectedId != null && principal.principal_id === selectedId,
      priority: index,
      data: {
        principal_type: principal.principal_type,
        privileged: principal.privileged ?? false,
        stale: principal.stale ?? false,
        widest_scope_breadth: principal.widest_scope_breadth,
        assignment_count: principal.assignment_count ?? 0,
        role_count: principal.roles?.length ?? 0,
        roles: (principal.roles ?? []).slice(0, 20),
      },
    })),
    ...input.owners.slice(0, 50).map((owner, index) => ({
      identity: owner.principal_id,
      namespace: "identity",
      kind: "subscription_owner",
      source: "identity/subscription-owners",
      observedAt: input.observedAt,
      priority: 100 + index,
      data: {
        principal_type: owner.principal_type,
        subscription_id: owner.subscription_id,
        scope_breadth: owner.scope_breadth,
        stale: owner.stale ?? false,
      },
    })),
    ...input.staleAccess.slice(0, 50).map((assignment, index) => ({
      identity: assignment.assignment_id,
      namespace: "identity",
      kind: "stale_access",
      source: "identity/stale-access",
      observedAt: input.observedAt,
      priority: 200 + index,
      data: {
        principal_id_ref: assignment.principal_id,
        role: assignment.role,
        privileged: assignment.privileged ?? false,
      },
    })),
    ...input.spnCredentials.slice(0, 50).map((credential, index) => ({
      identity: credential.credential_id,
      namespace: "identity",
      kind: "spn_credential",
      source: "identity/spn-credentials",
      observedAt: input.observedAt,
      priority: 300 + index,
      data: {
        connection_name: credential.connection_name,
        rotation_status: credential.rotation_status,
        days_to_expiry: credential.days_to_expiry ?? null,
        issues_count: credential.issues_count,
      },
    })),
  ].map((record) => ({ ...record, evidenceIdentity: "observation" }));
  return {
    scope: input.scope,
    filters: input.filters ?? { view: ["identity"] },
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "principals",
        visibleCount: input.principals.length,
        totalCount: Math.max(input.principals.length, input.principalsTotalCount),
        truncated: input.principals.length < input.principalsTotalCount,
        available: input.available,
      },
      {
        key: "subscription_owners",
        visibleCount: input.owners.length,
        totalCount: Math.max(input.owners.length, input.ownersTotalCount),
        truncated: input.owners.length < input.ownersTotalCount,
        available: input.available,
      },
      {
        key: "stale_access",
        visibleCount: input.staleAccess.length,
        totalCount: Math.max(input.staleAccess.length, input.staleTotalCount),
        truncated: input.staleAccess.length < input.staleTotalCount,
        available: input.available,
      },
      {
        key: "spn_credentials",
        visibleCount: input.spnCredentials.length,
        totalCount: Math.max(input.spnCredentials.length, input.spnTotalCount),
        truncated: input.spnCredentials.length < input.spnTotalCount,
        available: input.available,
      },
    ],
    sourceStatuses: [
      {
        source: "identity",
        observedAt: input.observedAt,
        status: (input.available ? input.freshness : "unavailable") as CopilotFreshnessStatusV2,
      },
    ],
  };
}

function finopsCoreInput(input: FinOpsCopilotPageInput): CoreCopilotAdapterInput {
  const summary = input.summary ?? null;
  const records: CoreCopilotRecord[] = [
    ...(summary ? [{
      identity: "finops-summary",
      namespace: "finops",
      kind: "finops_summary",
      source: "finops/summary",
      observedAt: input.observedAt,
      priority: 0,
      data: {
        identified_annual_savings: summary.identified_annual_savings,
        currency: summary.currency,
        savings_opportunity_count: summary.savings_opportunity_count,
        quantified_opportunity_count: summary.quantified_opportunity_count,
        waste_item_count: summary.waste_item_count,
        actual_spend: summary.actual_spend ?? null,
        actual_spend_currency: summary.actual_spend_currency,
        actual_spend_period_start: summary.actual_spend_period_start,
        actual_spend_period_end: summary.actual_spend_period_end,
      },
    }] : []),
    ...input.attribution.slice(0, 50).map((group, index) => ({
      identity: `${group.dimension}:${group.group}`,
      namespace: "finops",
      kind: "cost_attribution",
      source: "finops/attribution",
      observedAt: input.observedAt,
      priority: 10 + index,
      data: {
        dimension: group.dimension,
        group: group.group,
        identified_annual_savings: group.identified_annual_savings,
        savings_opportunity_count: group.savings_opportunity_count,
        waste_item_count: group.waste_item_count,
      },
    })),
    ...input.opportunities.slice(0, 50).map((opportunity, index) => ({
      identity: opportunity.recommendation_id ?? opportunity.resource_id ?? `opportunity-${index}`,
      namespace: "finops",
      kind: "savings_opportunity",
      source: "finops/opportunities",
      resourceId: opportunity.resource_id,
      observedAt: input.observedAt,
      priority: 100 + index,
      data: {
        recommendation_id: opportunity.recommendation_id,
        problem: opportunity.problem,
        impact: opportunity.impact,
        // Null is preserved as "not quantified", never coerced to zero.
        annual_savings: opportunity.annual_savings,
        currency: opportunity.currency,
        owner: opportunity.owner,
        business_service: opportunity.business_service,
        subscription: opportunity.subscription,
      },
    })),
    ...input.waste.slice(0, 50).map((waste, index) => ({
      identity: waste.resource_id ?? `waste-${index}`,
      namespace: "finops",
      kind: "waste_item",
      source: "finops/waste",
      resourceId: waste.resource_id,
      observedAt: input.observedAt,
      priority: 200 + index,
      data: {
        resource_type: waste.resource_type,
        reason: waste.reason,
        annual_savings: waste.annual_savings,
        currency: waste.currency,
        owner: waste.owner,
        business_service: waste.business_service,
      },
    })),
  ].map((record) => ({ ...record, evidenceIdentity: "observation" }));
  return {
    scope: input.scope,
    filters: input.filters ?? { view: ["finops"], dimension: [input.dimension] },
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "opportunities",
        visibleCount: input.opportunities.length,
        totalCount: Math.max(input.opportunities.length, input.opportunitiesTotalCount),
        truncated: input.opportunities.length < input.opportunitiesTotalCount,
        available: input.available,
      },
      {
        key: "waste",
        visibleCount: input.waste.length,
        totalCount: Math.max(input.waste.length, input.wasteTotalCount),
        truncated: input.waste.length < input.wasteTotalCount,
        available: input.available,
      },
      {
        key: "attribution",
        visibleCount: input.attribution.length,
        totalCount: Math.max(input.attribution.length, input.attributionTotalCount),
        truncated: input.attribution.length < input.attributionTotalCount,
        available: input.available,
      },
    ],
    sourceStatuses: [
      {
        source: "finops",
        observedAt: input.observedAt,
        status: (input.available ? input.freshness : "unavailable") as CopilotFreshnessStatusV2,
      },
    ],
  };
}

function resourceHealthCoreInput(input: ResourceHealthCopilotPageInput): CoreCopilotAdapterInput {
  const selectedId = input.selectedResourceId ?? null;
  const records: CoreCopilotRecord[] = input.resources.slice(0, 50).map((resource, index) => ({
    identity: resource.resource_id,
    namespace: "observability",
    kind: "resource_utilization",
    source: "resource-health/metrics",
    resourceId: resource.resource_id,
    name: resource.resource_name,
    observedAt: resource.observed_at ?? input.observedAt,
    selected: selectedId != null && resource.resource_id === selectedId,
    priority: index,
    data: {
      resource_name: resource.resource_name,
      resource_type: resource.resource_type,
      status: resource.status,
      cpu_percent: resource.cpu_percent,
      memory_percent: resource.memory_percent,
      disk_free_percent: resource.disk_free_percent,
      // Missing series are stated, never fabricated as zero.
      unavailable_metrics: resource.unavailable_metrics,
      series_point_count: resource.series_point_count,
      observed_at: resource.observed_at,
    },
  }));
  return {
    scope: input.scope,
    filters: input.filters ?? { view: ["resource-health"] },
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "resources",
        visibleCount: input.loadedCount,
        totalCount: Math.max(input.loadedCount, input.totalCount),
        truncated: input.loadedCount < input.totalCount,
        available: input.available,
      },
    ],
    sourceStatuses: [
      {
        source: "resource_health",
        observedAt: input.observedAt,
        // A cached snapshot is still fresh evidence, not a degraded source.
        status: (input.available ? input.freshness : "unavailable") as CopilotFreshnessStatusV2,
      },
    ],
  };
}

function situationDetailCoreInput(
  input: SituationDetailCopilotPageInput,
): CoreCopilotAdapterInput {
  const situation = input.situation ?? null;
  const affected = situation?.affected_resource_ids ?? [];
  const evidenceRows = input.evidence ?? [];
  const links = input.links ?? [];
  const auditEvents = input.auditEvents ?? [];
  const records: CoreCopilotRecord[] = [
    ...(situation ? [{
      identity: situation.situation_id,
      namespace: "operations",
      kind: "situation",
      source: "situations/detail",
      selected: true,
      priority: 0,
      data: {
        title: situation.title,
        severity: situation.severity,
        priority: situation.priority,
        lifecycle_state: situation.lifecycle_state,
        situation_type: situation.situation_type,
        owner: situation.owner,
        support_team: situation.support_team,
        evidence_state: situation.evidence_state,
        started_at: situation.started_at,
        last_observed_at: situation.last_observed_at,
        unknown_count: situation.unknowns?.length ?? 0,
      },
    }] : []),
    ...affected.slice(0, 50).map((resourceId, index) => ({
      identity: resourceId,
      namespace: "operations",
      kind: "affected_resource",
      source: "situations/affected",
      resourceId,
      observedAt: situation?.last_observed_at,
      priority: 10 + index,
      data: {},
    })),
    ...evidenceRows.slice(0, 50).map((item, index) => ({
      identity: item.evidence_id,
      namespace: "operations",
      kind: "situation_evidence",
      source: `situations/${item.source_family}`,
      resourceId: (item.resource_ids ?? []).find((value) =>
        isCanonicalAzureResourceId(value)),
      observedAt: item.observed_at,
      priority: 30 + index,
      data: {
        source_family: item.source_family,
        source_object_id: item.source_object_id,
        assertion: item.assertion,
        quality: item.quality,
        availability: item.availability,
        freshness: item.freshness,
      },
    })),
    ...links.slice(0, 50).map((link, index) => ({
      identity: link.link_id,
      namespace: "operations",
      kind: "linked_entity",
      source: "situations/links",
      priority: 60 + index,
      data: {
        entity_type: link.entity_type,
        entity_id: link.entity_id,
        relation: link.relation,
        quality: link.quality,
      },
    })),
    ...auditEvents.slice(0, 50).map((event, index) => ({
      identity: event.event_id,
      namespace: "operations",
      kind: "audit_event",
      source: "situations/audit",
      observedAt: event.timestamp,
      priority: 80 + index,
      data: {
        actor: event.actor,
        action: event.action,
      },
    })),
  ];
  const sourceStatuses: CoreCopilotSourceStatus[] = input.sourceStatuses?.length
    ? input.sourceStatuses.map((status) => ({
      source: status.source_family,
      observedAt: status.observed_at,
      status: status.availability === "unavailable"
        ? "unavailable"
        : freshnessStatus(status.freshness),
    }))
    : [{
      source: "situations",
      observedAt: input.observedAt,
      status: (input.available ? "fresh" : "unavailable") as CopilotFreshnessStatusV2,
    }];
  return {
    scope: input.scope,
    filters: {},
    records,
    evidence: input.citations,
    coverage: [
      {
        key: "evidence",
        visibleCount: evidenceRows.length,
        totalCount: evidenceRows.length,
        available: input.available,
      },
      {
        key: "affected_resources",
        visibleCount: affected.length,
        totalCount: affected.length,
        available: input.available,
      },
      {
        key: "links",
        visibleCount: links.length,
        totalCount: links.length,
        available: input.available,
      },
      {
        key: "audit",
        visibleCount: auditEvents.length,
        totalCount: auditEvents.length,
        available: input.auditAvailable !== false,
      },
    ],
    sourceStatuses,
  };
}

function servicesCoreInput(input: ServicesCopilotPageInput): CoreCopilotAdapterInput {
  const records: CoreCopilotRecord[] = input.services.slice(0, 50).map((service, index) => ({
    identity: service.name,
    namespace: "operations",
    kind: "business_service",
    source: "services/catalog",
    evidenceIdentity: "observation",
    selected: input.selectedServiceName != null
      && service.name === input.selectedServiceName,
    priority: index,
    data: {
      service: service.name,
      operational_state: service.operationalState,
      environments: service.environments,
      subscription_count: service.subscriptionCount,
      situation_count: service.situationCount,
      critical_count: service.criticalCount,
      health_risk: service.healthRisk,
    },
  }));
  return {
    scope: input.scope,
    filters: input.filters ?? {},
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "services",
        visibleCount: input.visibleCount,
        totalCount: Math.max(input.visibleCount, input.totalCount),
        truncated: input.visibleCount < input.totalCount,
        available: input.connectionsAvailable || input.incidentsAvailable,
      },
    ],
    sourceStatuses: [
      {
        source: "connections",
        observedAt: input.connectionsObservedAt,
        status: (input.connectionsAvailable
          ? (input.connectionsFreshness ?? "fresh")
          : "unavailable") as CopilotFreshnessStatusV2,
      },
      {
        source: "incidents",
        observedAt: input.incidentsObservedAt,
        status: (input.incidentsAvailable
          ? (input.incidentsFreshness ?? "fresh")
          : "unavailable") as CopilotFreshnessStatusV2,
      },
    ],
  };
}

function serviceDetailCoreInput(
  input: ServiceDetailCopilotPageInput,
): CoreCopilotAdapterInput {
  const subject = input.context.subject ?? null;
  const dependencies = input.dependencies ?? [];
  const sectionCount = (section: ServiceDetailSection): number =>
    section.sections?.length ?? 0;
  const sectionStatusRecords: CoreCopilotRecord[] = (
    [
      ["context", input.context],
      ["risk", input.risk],
      ["impact", input.impact],
    ] as const
  ).flatMap(([key, section], index) => {
    const detail = section.warnings?.find((warning) => warning.trim());
    if (!detail && section.available) return [];
    return [{
      identity: `${input.name}:${key}:status`,
      namespace: "operations",
      kind: "service_section_status",
      source: "service_section_status",
      evidenceIdentity: "observation" as const,
      selected: true,
      priority: 1 + index,
      // The observation itself is current and valid; its data explicitly
      // records that the underlying provider section is unavailable.
      status: "ok" as const,
      observedAt: section.observedAt,
      data: {
        section: key,
        availability: section.available ? "partial" : "unavailable",
        detail: detail ?? `${key} evidence is unavailable.`,
        source_status: Object.entries(section.sourceStatus ?? {})
          .sort(([left], [right]) => compareCodePoints(left, right))
          .map(([source, status]) => `${source}:${status}`),
      },
    }];
  });
  const records: CoreCopilotRecord[] = [
    {
      identity: input.name,
      namespace: "operations",
      kind: "business_service",
      source: "services/context",
      evidenceIdentity: "observation",
      selected: true,
      priority: 0,
      data: {
        owner: subject?.owner ?? undefined,
        support_team: subject?.support_team ?? undefined,
        environment: subject?.environment ?? undefined,
        criticality: subject?.criticality ?? undefined,
        lifecycle_status: subject?.lifecycle_status ?? undefined,
        application: subject?.application ?? undefined,
      },
    },
    ...sectionStatusRecords,
    ...dependencies.slice(0, 50).map((dependency, index) => ({
      identity: dependency.id,
      namespace: "operations",
      kind: "service_dependency",
      source: "services/impact",
      ...(!isCanonicalAzureResourceId(dependency.resource_id)
        ? { evidenceIdentity: "observation" as const }
        : {}),
      resourceId: isCanonicalAzureResourceId(dependency.resource_id)
        ? dependency.resource_id
        : undefined,
      priority: 10 + index,
      data: {
        name: dependency.name,
        relation: dependency.relation,
      },
    })),
  ];
  return {
    scope: input.scope,
    filters: input.filters ?? {},
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "context_sections",
        visibleCount: sectionCount(input.context),
        totalCount: sectionCount(input.context),
        available: input.context.available,
      },
      {
        key: "risk_sections",
        visibleCount: sectionCount(input.risk),
        totalCount: sectionCount(input.risk),
        available: input.risk.available,
      },
      {
        key: "dependencies",
        visibleCount: dependencies.length,
        totalCount: dependencies.length,
        available: input.impact.available,
      },
    ],
    sourceStatuses: [
      {
        source: "context",
        observedAt: input.context.observedAt,
        status: (input.context.available
          ? input.context.freshness
          : "unavailable") as CopilotFreshnessStatusV2,
      },
      {
        source: "risk",
        observedAt: input.risk.observedAt,
        status: (input.risk.available
          ? input.risk.freshness
          : "unavailable") as CopilotFreshnessStatusV2,
      },
      {
        source: "impact",
        observedAt: input.impact.observedAt,
        status: (input.impact.available
          ? input.impact.freshness
          : "unavailable") as CopilotFreshnessStatusV2,
      },
    ],
  };
}

function twinCoreInput(input: TwinCopilotPageInput): CoreCopilotAdapterInput {
  const selectedId = input.selectedResourceId
    ?? (input.traversal ? input.traversal.resource_id : null);
  const businessServiceCount = input.entities.filter(
    (entity) => entity.kind === "business_service",
  ).length;
  const resourceCount = input.entities.filter(
    (entity) => entity.kind === "resource",
  ).length;
  const vulnerabilityCount = input.entities.filter(
    (entity) => entity.kind === "vulnerability",
  ).length;
  const relationshipCount = input.relationships.length;
  const dependencyDetail = relationshipCount > 0
    ? (
        `The current twin contains ${relationshipCount} relationship `
        + `record${relationshipCount === 1 ? "" : "s"} and `
        + `${businessServiceCount} business service `
        + `entit${businessServiceCount === 1 ? "y" : "ies"}.`
      )
    : (
        "The current twin contains no relationship evidence, so affected "
        + "business services and dependencies cannot be asserted."
      );
  const riskDetail = typeof input.riskScore === "number"
    ? (
        `The current twin reports a scenario-weighted risk score of `
        + `${input.riskScore} with ${vulnerabilityCount} visible vulnerability `
        + `entit${vulnerabilityCount === 1 ? "y" : "ies"}.`
      )
    : (
        "The current twin has no scenario-weighted risk score, so a current "
        + "risk level cannot be asserted."
      );
  const records: CoreCopilotRecord[] = [
    {
      identity: `${input.twinId}:status`,
      namespace: "operations",
      kind: "twin_status",
      source: "twin/status",
      evidenceIdentity: "observation",
      selected: true,
      priority: 0,
      observedAt: input.liveObservedAt ?? input.observedAt,
      data: {
        entity_count: input.entities.length,
        business_service_count: businessServiceCount,
        resource_count: resourceCount,
        vulnerability_count: vulnerabilityCount,
        relationship_count: relationshipCount,
        dependency_detail: dependencyDetail,
        risk_detail: riskDetail,
      },
    },
    ...input.entities.slice(0, 50).map((entity, index) => ({
      identity: entity.id,
      namespace: "operations",
      kind: boundedString("twin entity kind", entity.kind || "entity", 1, 64),
      source: "twin/entities",
      ...(!isCanonicalAzureResourceId(entity.resource_id)
        ? { evidenceIdentity: "observation" as const }
        : {}),
      resourceId: isCanonicalAzureResourceId(entity.resource_id)
        ? entity.resource_id
        : undefined,
      selected: selectedId != null
        && (entity.id === selectedId || entity.id === `resource:${selectedId}`),
      priority: index,
      data: {
        name: entity.name,
        version: entity.version,
        state: entity.state,
        confidence: entity.confidence,
        business_service: entity.business_service,
        observed: true,
      },
    })),
    ...input.relationships.slice(0, 50).map((relationship, index) => ({
      identity: relationship.id,
      namespace: "operations",
      kind: "twin_relationship",
      source: "twin/relationships",
      evidenceIdentity: "observation" as const,
      priority: 60 + index,
      data: {
        source: relationship.source,
        target: relationship.target,
        type: relationship.type,
        confidence: relationship.confidence,
        // Unsupported edges stay uncertain rather than asserted.
        supported: relationship.supported ?? true,
      },
    })),
    ...input.timeline.slice(0, 50).map((event, index) => ({
      identity: `${event.type}:${event.timestamp}:${event.entity}`,
      namespace: "operations",
      kind: "twin_event",
      source: "twin/timeline",
      evidenceIdentity: "observation" as const,
      observedAt: event.timestamp,
      priority: 120 + index,
      data: {
        type: event.type,
        entity: event.entity,
        summary: event.summary,
      },
    })),
    ...(input.traversal ? [{
      identity: `traversal:${input.traversal.resource_id}`,
      namespace: "operations",
      kind: "twin_traversal",
      source: "twin/traversal",
      ...(!isCanonicalAzureResourceId(input.traversal.resource_id)
        ? { evidenceIdentity: "observation" as const }
        : {}),
      resourceId: isCanonicalAzureResourceId(input.traversal.resource_id)
        ? input.traversal.resource_id
        : undefined,
      priority: 180,
      data: {
        resource_id: input.traversal.resource_id,
        path: input.traversal.path.map((entity) => entity.id),
        business_consequence: input.traversal.business_consequence,
      },
    }] : []),
    ...(input.scenario ? [{
      identity: `scenario:${input.scenario.scenario}:${input.scenario.target}`,
      namespace: "operations",
      kind: "twin_scenario",
      source: "twin/scenario",
      evidenceIdentity: "observation" as const,
      priority: 190,
      data: {
        scenario: input.scenario.scenario,
        target: input.scenario.target,
        likely_impact: input.scenario.likely_impact,
        risk_delta: input.scenario.risk_delta,
        impacted_count: input.scenario.impacted_count,
        assumptions: input.scenario.assumptions,
        // Scenario projections are hypothetical, never observed reality.
        observed: false,
      },
    }] : []),
  ];
  const sourceStatuses: CoreCopilotSourceStatus[] = input.sourceStatus
    && Object.keys(input.sourceStatus).length
    ? Object.entries(input.sourceStatus).map(([source, status]) => ({
      source,
      observedAt: input.liveObservedAt ?? input.observedAt,
      status: freshnessStatus(status),
    }))
    : [{
      source: "twin",
      observedAt: input.liveObservedAt ?? input.observedAt,
      status: (input.available
        ? (input.freshness ?? "fresh")
        : "unavailable") as CopilotFreshnessStatusV2,
    }];
  return {
    scope: input.scope,
    filters: input.filters ?? {},
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "entities",
        visibleCount: input.entities.length,
        totalCount: Math.max(input.entities.length, input.entitiesTotal),
        truncated: input.entities.length < input.entitiesTotal,
        available: input.available,
      },
      {
        key: "relationships",
        visibleCount: input.relationships.length,
        totalCount: Math.max(input.relationships.length, input.relationshipsTotal),
        truncated: input.relationships.length < input.relationshipsTotal,
        available: input.available,
      },
      {
        key: "timeline",
        visibleCount: input.timeline.length,
        totalCount: Math.max(input.timeline.length, input.timelineTotal),
        truncated: input.timeline.length < input.timelineTotal,
        available: input.available,
      },
    ],
    sourceStatuses,
  };
}

function situationsCoreInput(input: SituationsCopilotPageInput): CoreCopilotAdapterInput {
  const records: CoreCopilotRecord[] = input.situations.slice(0, 50).map((situation, index) => ({
    identity: situation.situation_id,
    namespace: "operations",
    kind: "situation",
    source: "situations/visible",
    observedAt: situation.last_observed_at,
    selected: input.selectedSituationId != null
      && situation.situation_id === input.selectedSituationId,
    priority: index,
    data: {
      title: situation.title,
      priority: situation.priority,
      severity: situation.severity,
      lifecycle_state: situation.lifecycle_state,
      situation_type: situation.situation_type,
      owner: situation.owner,
      support_team: situation.support_team,
      affected_resource_ids: situation.affected_resource_ids,
      evidence_state: situation.evidence_state,
    },
  }));
  const evidenceStatuses = input.evidence.map((item) =>
    evidenceFreshness(item.freshness));
  const inferredStatus = !input.available
    ? "unavailable"
    : evidenceStatuses.length
      ? evidenceStatuses.reduce((current, candidate) =>
        FRESHNESS_WARNING_PRIORITY[candidate]
          > FRESHNESS_WARNING_PRIORITY[current]
          ? candidate
          : current)
      : "unavailable";
  const sourceStatuses: CoreCopilotSourceStatus[] = input.sourceStatuses?.length
    ? input.sourceStatuses.map((status) => ({
      source: status.source_family,
      observedAt: status.observed_at,
      status: status.availability === "unavailable"
        ? "unavailable"
        : freshnessStatus(status.freshness),
    }))
    : [{
      source: "situations",
      observedAt: input.observedAt,
      status: inferredStatus,
    }];
  return {
    scope: input.scope,
    filters: {
      query: input.query ? [input.query] : [],
      priority: input.priority === "all" ? [] : [input.priority],
      page: [String(input.page)],
    },
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "situations",
        visibleCount: input.situations.length,
        totalCount: Math.max(input.situations.length, input.totalCount),
        truncated: input.situations.length < input.totalCount,
        available: input.available,
      },
    ],
    sourceStatuses,
  };
}

function remediationCoreInput(input: RemediationCopilotPageInput): CoreCopilotAdapterInput {
  const plan = input.selectedPlan;
  const eligibility = input.eligibility;
  assertBound("remediation workflow blockers", input.blockers.length, 16);
  const workflowBlockers = input.blockers.map(
    (blocker) => `${blocker.step}:${blocker.code}`,
  );
  const records: CoreCopilotRecord[] = [];
  if (plan) {
    records.push({
      identity: plan.plan_id,
      namespace: "remediation",
      kind: "remediation_plan",
      source: "remediation/plan",
      resourceId: plan.resource_id,
      resourceType: plan.resource_type,
      name: plan.resource_name,
      selected: true,
      priority: 0,
      data: {
        title: plan.title,
        status: plan.status,
        family: plan.family,
        action_id: plan.action_id,
        action_version: plan.action_version,
        snapshot_hash: plan.snapshot_hash,
        current: true,
        // Descriptive, read-only mirrors of the current server projection.
        plan_executable: eligibility?.plan_executable ?? false,
        plan_ineligibility_reason: eligibility?.plan_ineligibility_reason,
        can_operate: eligibility?.can_operate ?? false,
        operate_ineligible_reason: eligibility?.operate_ineligible_reason,
        can_approve: eligibility?.can_approve ?? false,
        approve_ineligible_reason: eligibility?.approve_ineligible_reason,
        approval_current: eligibility?.approval_current ?? false,
        approval_status: eligibility?.approval_status ?? "none",
        has_executable_preview: eligibility?.has_executable_preview ?? false,
        recommended_step: eligibility?.recommended_step ?? "",
        workflow_blockers: workflowBlockers,
      },
    });
  }
  if (input.execution) {
    records.push({
      identity: input.execution.execution_id,
      namespace: "remediation",
      kind: "remediation_execution",
      source: "remediation/execution",
      priority: 5,
      data: {
        current: true,
        status: input.execution.status,
        retryable: input.execution.retryable,
        cancellable: input.execution.cancellable,
        supersedable: input.execution.supersedable,
        remaining_attempts: input.execution.remaining_attempts,
      },
    });
  }
  records.push(
    ...input.requirements.slice(0, 50).map((requirement, index) => ({
      identity: `${requirement.policy_id}:${requirement.role}:${requirement.stage}`,
      namespace: "remediation",
      kind: "approval_requirement",
      source: "remediation/approval",
      priority: 10 + index,
      data: {
        current: true,
        policy_id: requirement.policy_id,
        role: requirement.role,
        stage: requirement.stage,
        satisfied: requirement.satisfied,
        unmet_reason: requirement.unmet_reason,
      },
    })),
  );
  // Carried thread evidence is inert and explicitly non-current: it can never
  // stand in for the current server eligibility facts above (D-08, D-09).
  records.push(
    ...(input.historicalEvidence ?? []).slice(0, 50).map((item, index) => ({
      identity: item.key,
      namespace: "history",
      kind: "historical_finding",
      source: "remediation/thread-history",
      observedAt: item.observedAt,
      status: "unavailable" as CopilotSnapshotStatus,
      priority: 90 + index,
      data: {
        ...(item.data ?? {}),
        summary: item.summary,
        current: false,
        superseded_by_current_state: true,
      },
    })),
  );
  const sourceStatuses: CoreCopilotSourceStatus[] = input.sourceStatuses.map((status) => ({
    source: status.source,
    observedAt: status.observedAt,
    status: status.availability === "unavailable"
      ? "unavailable"
      : freshnessStatus(status.freshness ?? "unknown"),
  }));
  return {
    scope: input.scope,
    filters: {
      view: ["remediation"],
      plan: plan ? [plan.plan_id] : [],
    },
    records,
    evidence: input.evidence,
    coverage: [
      {
        key: "plans",
        visibleCount: input.coverage.visiblePlanCount,
        totalCount: Math.max(input.coverage.visiblePlanCount, input.coverage.totalPlanCount),
        truncated: input.coverage.visiblePlanCount < input.coverage.totalPlanCount,
        available: true,
      },
    ],
    sourceStatuses,
  };
}

/** Builds the typed Overview context from loaded records or loaded envelopes. */
export function buildOverviewCopilotContext(
  input: CoreCopilotAdapterInput | OverviewCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    CORE_PAGE_CONFIG.overview,
    isCoreCopilotInput(input) ? input : overviewCoreInput(input),
    OVERVIEW_STARTERS,
  );
}

/** Builds the typed Network context from loaded records or Network envelopes. */
export function buildNetworkCopilotContext(
  input: CoreCopilotAdapterInput | NetworkCopilotPageInput,
): CoreCopilotContext {
  const context = buildCoreCopilotContext(
    CORE_PAGE_CONFIG.network,
    isCoreCopilotInput(input) ? input : networkCoreInput(input),
    NETWORK_STARTERS,
  );
  if (isCoreCopilotInput(input)) return context;
  const firstHub = input.topology?.data.topology.hubs[0];
  if (!firstHub) return context;
  return {
    ...context,
    starterQuestions: [
      context.starterQuestions[0],
      {
        label: `What depends on ${firstHub.name}?`,
        specialistId: "network",
        tool: "hub_dependents",
        toolArguments: { vnet_id: firstHub.vnet_id },
      },
      ...context.starterQuestions.slice(1),
    ],
  };
}

/** Builds the typed Compliance context from loaded records or evaluated rows. */
export function buildComplianceCopilotContext(
  input: CoreCopilotAdapterInput | ComplianceCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    CORE_PAGE_CONFIG.compliance,
    isCoreCopilotInput(input) ? input : complianceCoreInput(input),
    COMPLIANCE_STARTERS,
  );
}

/** Builds the typed Exposure landing context from loaded decision sections. */
export function buildExposureCopilotContext(
  input: CoreCopilotAdapterInput | ExposureCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    CORE_PAGE_CONFIG.exposure,
    isCoreCopilotInput(input) ? input : exposureCoreInput(input),
    EXPOSURE_STARTERS,
  );
}

/** Builds the typed CVE detail context from loaded vulnerability sections. */
export function buildCveDetailCopilotContext(
  input: CveDetailCopilotPageInput,
): CoreCopilotContext {
  const cveId = input.cveId.trim().toUpperCase();
  return buildCoreCopilotContext(
    { pageKind: "vulnerability", pageId: `cve:${cveId}` },
    cveDetailCoreInput({ ...input, cveId }),
    cveDetailStarters({ ...input, cveId }),
  );
}

/** Builds the typed Defender posture context from loaded posture sections. */
export function buildDefenderPostureCopilotContext(
  input: CoreCopilotAdapterInput | DefenderPostureCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    { pageKind: "vulnerability", pageId: "defender-posture" },
    isCoreCopilotInput(input) ? input : defenderPostureCoreInput(input),
    DEFENDER_POSTURE_STARTERS,
  );
}

/** Builds the typed KB detail context from loaded patch/CVE evidence. */
export function buildKbDetailCopilotContext(
  input: KbDetailCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    { pageKind: "vulnerability", pageId: `kb:${input.kbId}` },
    kbDetailCoreInput(input),
    kbDetailStarters(input),
  );
}

/** Builds the typed patch-priority context from the loaded priority queue. */
export function buildPatchPrioritiesCopilotContext(
  input: CoreCopilotAdapterInput | PatchPrioritiesCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    { pageKind: "vulnerability", pageId: "patch-priorities" },
    isCoreCopilotInput(input) ? input : patchPrioritiesCoreInput(input),
    PATCH_PRIORITIES_STARTERS,
  );
}

/** Builds the typed change-correlation context from the loaded change stream. */
export function buildChangesCopilotContext(
  input: CoreCopilotAdapterInput | ChangesCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    { pageKind: "incident", pageId: "changes" },
    isCoreCopilotInput(input) ? input : changesCoreInput(input),
    CHANGES_STARTERS,
  );
}

/** Builds the typed predeploy assessment context from the loaded evaluation. */
export function buildPredeployCopilotContext(
  input: CoreCopilotAdapterInput | PredeployCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    { pageKind: "governance", pageId: "predeploy" },
    isCoreCopilotInput(input) ? input : predeployCoreInput(input),
    PREDEPLOY_STARTERS,
  );
}

/** Builds the typed Situation queue context from the loaded triage page. */
export function buildSituationsCopilotContext(
  input: CoreCopilotAdapterInput | SituationsCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    CORE_PAGE_CONFIG.situations,
    isCoreCopilotInput(input) ? input : situationsCoreInput(input),
    SITUATIONS_STARTERS,
  );
}

/**
 * Builds the typed, read-only Remediation context from the loaded governed
 * workflow projection. Approval and execution remain existing server-side
 * workflows; this adapter only explains and prepares a governed handoff and
 * never carries mutation authority into Copilot (D-10).
 */
export function buildRemediationCopilotContext(
  input: CoreCopilotAdapterInput | RemediationCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    CORE_PAGE_CONFIG.remediation,
    isCoreCopilotInput(input) ? input : remediationCoreInput(input),
    REMEDIATION_STARTERS,
  );
}

/**
 * Builds the typed connection data-health context from the loaded subscription
 * registry. Sync/health remain the only mutation paths on the page; this
 * adapter only explains already-loaded source health (D-03, D-09).
 */
export function buildConnectionsCopilotContext(
  input: CoreCopilotAdapterInput | ConnectionsCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    { pageKind: "resource", pageId: "connections" },
    isCoreCopilotInput(input) ? input : connectionsCoreInput(input),
    CONNECTIONS_STARTERS,
  );
}

/** Builds the typed Fabric medallion context from loaded layer/manifest health. */
export function buildFabricMedallionCopilotContext(
  input: CoreCopilotAdapterInput | FabricMedallionCopilotPageInput,
): CoreCopilotContext {
  const context = buildCoreCopilotContext(
    { pageKind: "resource", pageId: "fabric-medallion" },
    isCoreCopilotInput(input) ? input : fabricMedallionCoreInput(input),
    FABRIC_MEDALLION_STARTERS,
  );
  // A paused/unprovisioned capacity is a distinct deployment-blocked state,
  // surfaced explicitly so it is never conflated with an outage or a healthy
  // empty layer (D-09).
  if (!isCoreCopilotInput(input) && input.deploymentBlocked) {
    return {
      ...context,
      uncertainty: [...context.uncertainty, "fabric_medallion is deployment-blocked"],
    };
  }
  return context;
}

/** Builds the typed governance context from loaded settings/review/export state. */
export function buildGovernanceCopilotContext(
  input: CoreCopilotAdapterInput | GovernanceCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    { pageKind: "governance", pageId: "governance" },
    isCoreCopilotInput(input) ? input : governanceCoreInput(input),
    GOVERNANCE_STARTERS,
  );
}

/**
 * Builds the typed identity access context from loaded governance sections.
 * Principals stay non-ARM domain identities and the server reauthorizes every
 * scope; this adapter carries only bounded, already-authorized fields and no
 * mutation path (D-03, D-05, D-06, D-08, D-09).
 */
export function buildIdentityCopilotContext(
  input: CoreCopilotAdapterInput | IdentityCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    { pageKind: "governance", pageId: "identity" },
    isCoreCopilotInput(input) ? input : identityCoreInput(input),
    IDENTITY_STARTERS,
  );
}

/** Builds the typed FinOps context from loaded attribution/opportunity/waste. */
export function buildFinOpsCopilotContext(
  input: CoreCopilotAdapterInput | FinOpsCopilotPageInput,
): CoreCopilotContext {
  const context = buildCoreCopilotContext(
    { pageKind: "governance", pageId: "finops" },
    isCoreCopilotInput(input) ? input : finopsCoreInput(input),
    FINOPS_STARTERS,
  );
  // Genuinely unobservable figures are stated as uncertainty rather than
  // implied as zero spend (D-09).
  if (!isCoreCopilotInput(input) && input.summary?.unavailable_metrics.length) {
    return {
      ...context,
      uncertainty: [
        ...context.uncertainty,
        ...input.summary.unavailable_metrics.map(
          (item) => `${item.metric} is unavailable: ${item.reason}`,
        ),
      ],
    };
  }
  return context;
}

/** Builds the typed resource-health context from the loaded utilization snapshot. */
export function buildResourceHealthCopilotContext(
  input: CoreCopilotAdapterInput | ResourceHealthCopilotPageInput,
): CoreCopilotContext {
  const context = buildCoreCopilotContext(
    { pageKind: "resource", pageId: "resource-health" },
    isCoreCopilotInput(input) ? input : resourceHealthCoreInput(input),
    RESOURCE_HEALTH_STARTERS,
  );
  // Missing metric series are named explicitly so absent data never reads as a
  // healthy zero (D-09).
  if (!isCoreCopilotInput(input) && input.unavailableMetrics?.length) {
    return {
      ...context,
      uncertainty: [
        ...context.uncertainty,
        ...input.unavailableMetrics.map((metric) => `${metric} series is unavailable`),
      ],
    };
  }
  return context;
}

/** Builds the typed Situation detail context from the loaded durable brief. */
export function buildSituationDetailCopilotContext(
  input: SituationDetailCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    { pageKind: "incident", pageId: `situation:${input.situationId}` },
    situationDetailCoreInput(input),
    SITUATION_DETAIL_STARTERS,
  );
}

/** Builds the typed Services catalog context from the loaded service list. */
export function buildServicesCopilotContext(
  input: CoreCopilotAdapterInput | ServicesCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    { pageKind: "resource", pageId: "services" },
    isCoreCopilotInput(input) ? input : servicesCoreInput(input),
    SERVICES_STARTERS,
  );
}

/** Builds the typed Service detail context from the loaded semantic sections. */
export function buildServiceDetailCopilotContext(
  input: ServiceDetailCopilotPageInput,
): CoreCopilotContext {
  return buildCoreCopilotContext(
    { pageKind: "resource", pageId: `service:${input.name}` },
    serviceDetailCoreInput(input),
    serviceDetailStarters(input.name),
  );
}

/**
 * Builds the typed operational-twin context from the loaded snapshot,
 * traversal, and scenario. Unsupported relationships and stale temporal
 * evidence stay uncertain rather than asserted (D-03, D-04, D-08, D-09).
 */
export function buildTwinCopilotContext(
  input: TwinCopilotPageInput,
): CoreCopilotContext {
  const context = buildCoreCopilotContext(
    { pageKind: "network", pageId: "twin" },
    twinCoreInput(input),
    TWIN_STARTERS,
  );
  const extraUncertainty = [
    ...(input.unsupportedRelationships ?? []).map(
      (type) => `${type} is not a supported twin relationship; treat as uncertain`,
    ),
    ...(input.staleTemporalEvidence ?? []).map(
      (note) => `${note} is historical evidence and is not asserted as current`,
    ),
  ];
  if (extraUncertainty.length) {
    return { ...context, uncertainty: [...context.uncertainty, ...extraUncertainty] };
  }
  return context;
}

/** Registry of contextual routes migrated by Plan 11-07. */
export const CORE_COPILOT_PAGE_ADAPTERS = {
  "/": buildOverviewCopilotContext,
  "/compliance": buildComplianceCopilotContext,
  "/exposure": buildExposureCopilotContext,
  "/network": buildNetworkCopilotContext,
  "/remediation": buildRemediationCopilotContext,
  "/situations": buildSituationsCopilotContext,
} as const;

/**
 * Reviewed starter specialist/tool hints per integrated route.
 *
 * Each value is the exact hint set the route's adapter emits -- the shared
 * static hint constants, or a representative instance for the id-parameterized
 * detail routes (the specialist and tool are invariant to the id). The Plan
 * 11-16 manifest-parity gate proves every hint here maps to an authorized
 * manifest specialist and a granted tool, and that the union of these hints
 * plus each route's page-kind anchor owners equals the versioned specialist
 * portfolio exactly (D-03, D-05, D-06). Hints carry advisory routing only;
 * backend policy still authorizes every specialist and tool execution.
 */
export const COPILOT_ROUTE_STARTER_HINTS: Record<string, readonly CoreCopilotStarterQuestion[]> = {
  "/": OVERVIEW_STARTERS,
  "/network": NETWORK_STARTERS,
  "/compliance": COMPLIANCE_STARTERS,
  "/exposure": EXPOSURE_STARTERS,
  "/exposure/cves/[id]": cveDetailStarters({ cveId: "CVE-0000-00000" } as unknown as CveDetailCopilotPageInput),
  "/exposure/defender-posture": DEFENDER_POSTURE_STARTERS,
  "/exposure/kbs/[id]": kbDetailStarters({ kbId: "KB0000000" } as unknown as KbDetailCopilotPageInput),
  "/exposure/patch-priorities": PATCH_PRIORITIES_STARTERS,
  "/situations": SITUATIONS_STARTERS,
  "/situations/[id]": SITUATION_DETAIL_STARTERS,
  "/changes": CHANGES_STARTERS,
  "/changes/predeploy": PREDEPLOY_STARTERS,
  "/inventory": INVENTORY_STARTERS,
  "/connections": CONNECTIONS_STARTERS,
  "/connections/fabric": FABRIC_MEDALLION_STARTERS,
  "/governance": GOVERNANCE_STARTERS,
  "/identity": IDENTITY_STARTERS,
  "/finops": FINOPS_STARTERS,
  "/remediation": REMEDIATION_STARTERS,
  "/resource-health": RESOURCE_HEALTH_STARTERS,
  "/services": SERVICES_STARTERS,
  "/services/[name]": serviceDetailStarters("service"),
  "/twin": TWIN_STARTERS,
};
