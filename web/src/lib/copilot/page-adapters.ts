import type { ScopeSelection } from "@/lib/scope";
import * as services from "@/lib/services";
import type {
  CanonicalCopilotRequest,
  CopilotEntityRef,
  CopilotEvidenceSnapshotV2 as StrictCopilotEvidenceSnapshotV2,
  CopilotFreshnessStatusV2,
  CopilotSnapshotEvidenceV2,
  CopilotSnapshotStatusV2,
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
  "/inventory": "integrated",
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

function validateSelectedInventorySelector(record: InventoryCopilotRecord): void {
  if (record.kind === "os_group") {
    const osName = record.data.os_name;
    const osVersion = record.data.os_version;
    if (osName && osVersion && osName !== "all" && osVersion !== "all") {
      boundedSelectorText("os_name", osName);
      boundedSelectorText("os_version", osVersion);
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
      boundedSelectorText("software_name", softwareName);
      boundedSelectorText("software_version", softwareVersion);
    }
    return;
  }
  boundedSelectorText("resource_type", record.data.resource_type, 160);
  boundedSelectorText("sku", record.data.sku || "Unknown");
  boundedSelectorText("tier", record.data.tier || "Unknown");
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
