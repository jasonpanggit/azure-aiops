import type { ScopeSelection } from "@/lib/scope";
import * as services from "@/lib/services";
import type {
  CanonicalCopilotRequest,
  CollectionCoverage,
  ComplianceDeviation,
  CopilotEntityRef,
  CopilotEvidenceSnapshotV2 as StrictCopilotEvidenceSnapshotV2,
  CopilotFreshnessStatusV2,
  CopilotPageKind,
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
  entity: CopilotEntityRef;
  claimType: string;
}

type InventorySnapshotEvidence = CopilotSnapshotEvidenceV2 & {
  source_key: string;
  entity: CopilotEntityRef;
  claim_type: string;
  citations: string[];
  selected: boolean;
  direct: boolean;
  actionable: boolean;
  severity: CopilotSnapshotEvidenceV2["severity"];
  quality: CopilotSnapshotEvidenceV2["quality"];
};

const PAGE_DISPOSITIONS = {
  "/": "integrated",
  "/compliance": "integrated",
  "/exposure": "integrated",
  "/inventory": "integrated",
  "/network": "integrated",
  "/situations": "integrated",
} as const satisfies Record<string, CopilotPageDisposition>;

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
  return PAGE_DISPOSITIONS[pathname as keyof typeof PAGE_DISPOSITIONS] ?? "deferred";
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

function entityKey(entity: CopilotEntityRef): string {
  if (entity.type === "azure") {
    return `azure:${canonicalResourceId(entity.resource_id)}`;
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

function freshnessStatus(status: string): CopilotFreshnessStatusV2 {
  if (status === "ready" || status === "fresh") return "fresh";
  if (status === "stale") return "stale";
  if (status === "partial") return "partial";
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
    starterQuestions: [
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
    ],
  };
}

function buildEmptyInventoryContextEvidence(
  input: InventoryCopilotAdapterInput,
  inventoryContext: Record<string, unknown>,
): InventorySnapshotEvidence {
  const source = INVENTORY_EVIDENCE_SOURCES[input.tab];
  const sourceKey = `page-context:${input.tab}`;
  const entity: CopilotEntityRef = {
    type: "domain",
    namespace: "inventory",
    kind: `${input.tab}_page_context`,
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
  epss_score?: number;
  is_known_exploited?: boolean;
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
} as const;

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
    toolArguments: {},
  },
];

const COMPLIANCE_STARTERS: CoreCopilotStarterQuestion[] = [
  {
    label: "Which PROD workloads bypass the firewall?",
    specialistId: "network",
    tool: "firewall_nsg_gaps",
    toolArguments: {},
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
    tool: "risk_context",
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

function coreRecordEntity(record: CoreCopilotRecord): CopilotEntityRef {
  if (isCanonicalAzureResourceId(record.resourceId)) {
    return {
      type: "azure",
      resource_id: canonicalResourceId(record.resourceId),
    };
  }
  return {
    type: "domain",
    namespace: boundedString("entity namespace", record.namespace, 1, 64),
    kind: boundedString("entity kind", record.kind, 1, 64),
    source_key: coreRecordSourceKey(record),
  };
}

function entityOrderingKey(entity: CopilotEntityRef): string {
  return entity.type === "domain"
    ? `0:${entity.namespace}:${entity.kind}:${entity.source_key}`
    : `1:${entity.resource_id}`;
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
  const entity: CopilotEntityRef = canonicalResource
    ? { type: "azure", resource_id: canonicalResource }
    : {
        type: "domain",
        namespace: "source",
        kind: "observation",
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
    const entity: CopilotEntityRef = {
      type: "domain",
      namespace: "page",
      kind: "coverage",
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
  const coverage = normalizeCoverage(input.coverage);
  const selectedRecords = input.records.filter((record) => record.selected);
  const selectedEntities = selectedRecords
    .map(coreRecordEntity)
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

  const coverageRows = coverageEvidenceRows(coverage);
  const candidates = [
    ...input.records.map(coreEvidenceRow),
    ...input.evidence.map(sourceEvidenceRow),
  ].sort((left, right) =>
    left.priority - right.priority
    || compareCodePoints(left.row.evidence_id, right.row.evidence_id));
  const candidateEvidence = new Map<string, ReturnType<typeof coreEvidenceRow>["row"]>();
  const retainedCandidateIds: string[] = [];
  const candidateLimit = Math.max(
    0,
    COPILOT_SNAPSHOT_LIMITS.evidenceRows - coverageRows.length,
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

  const buildSnapshot = () => {
    const evidence = [
      ...retainedCandidateIds.flatMap((id) => {
        const row = candidateEvidence.get(id);
        return row ? [row] : [];
      }),
      ...coverageRows,
    ].sort((left, right) => compareCodePoints(left.evidence_id, right.evidence_id));
    return services.buildCopilotSnapshot({
      pageKind: config.pageKind,
      pageId: config.pageId,
      scope: input.scope,
      filters: normalizeFilters(input.filters, input.sort),
      selectedResources,
      evidence,
      freshness,
    });
  };
  let snapshot = buildSnapshot();
  while (
    new TextEncoder().encode(stableJson(snapshot)).length + numericValueCount(snapshot)
      > COPILOT_SNAPSHOT_LIMITS.snapshotBytes
    && retainedCandidateIds.length > 0
  ) {
    retainedCandidateIds.pop();
    snapshot = buildSnapshot();
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
  const cve = input.cve ?? null;
  const findingRows = input.findings.rows ?? [];
  const attackGraph = input.attack?.graph ?? null;
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
        epss_score: cve.epss_score,
        is_known_exploited: cve.is_known_exploited,
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
      observedAt: input.findings.observedAt,
      status: cve ? "fresh" : "unavailable",
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
        visibleCount: input.findings.loadedCount,
        totalCount: Math.max(input.findings.loadedCount, input.findings.totalCount),
        truncated: input.findings.loadedCount < input.findings.totalCount,
        available: input.findings.available,
      },
      {
        key: "associated_kbs",
        visibleCount: cve?.associated_kbs.length ?? 0,
        totalCount: cve?.associated_kbs.length ?? 0,
        available: Boolean(cve),
      },
      {
        key: "attack_path",
        visibleCount: attackGraph?.nodes.length ?? 0,
        totalCount: attackGraph?.nodes.length ?? 0,
        available: input.attack?.available ?? false,
      },
    ],
    sourceStatuses,
  };
}

function cveDetailStarters(input: CveDetailCopilotPageInput): CoreCopilotStarterQuestion[] {
  const cveId = input.cve?.cve_id ?? input.cveId;
  return [
    {
      label: `Explain ${cveId}`,
      specialistId: "vulnerability",
      tool: "cve_detail",
      toolArguments: { cve_id: cveId },
    },
    {
      label: `Show the blast radius of ${cveId}`,
      specialistId: "vulnerability",
      tool: "cve_attack_path",
      toolArguments: { cve_id: cveId },
    },
  ];
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
  return buildCoreCopilotContext(
    { pageKind: "vulnerability", pageId: `cve:${input.cveId}` },
    cveDetailCoreInput(input),
    cveDetailStarters(input),
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

/** Registry of contextual routes migrated by Plan 11-07. */
export const CORE_COPILOT_PAGE_ADAPTERS = {
  "/": buildOverviewCopilotContext,
  "/compliance": buildComplianceCopilotContext,
  "/exposure": buildExposureCopilotContext,
  "/network": buildNetworkCopilotContext,
  "/situations": buildSituationsCopilotContext,
} as const;
