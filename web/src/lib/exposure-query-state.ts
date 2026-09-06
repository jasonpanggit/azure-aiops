import type {
  ExposureSort,
  ExposureSortField,
} from "./types";
import { ApiError } from "./types";
import {
  SCOPE_DIMENSIONS,
  scopeToSearchParams,
  type ScopeDimension,
  type ScopeSelection,
} from "./scope";

export const EXPOSURE_SEARCH_DEBOUNCE_MS = 300;
export const EXPOSURE_PAGE_SIZES = [25, 50, 100] as const;
export const DEFAULT_EXPOSURE_SORT: ExposureSort = {
  field: "priority_score",
  direction: "desc",
};

const SORT_FIELDS = new Set<ExposureSortField>([
  "priority_score",
  "severity",
  "target_id",
  "weakness_id",
]);
const ENUM_FILTERS = {
  severity: new Set(["critical", "high", "medium", "low", "unknown"]),
  target_kind: new Set(["server", "container_image"]),
  completeness: new Set([
    "complete",
    "partial",
    "stale",
    "unavailable",
    "unknown",
    "healthy-empty",
  ]),
} as const;
const FREEFORM_FILTERS: readonly Exclude<
  ExposureStringFilter,
  "search" | "severity" | "target_kind" | "completeness"
>[] = [
  "current_state",
  "deployment_state",
  "sla_state",
  "source_family",
  "source_state",
  "weakness_id",
];
const API_FILTER_KEYS = [
  "severity",
  "target_kind",
  "source_family",
  "current_state",
  "sla_state",
  "completeness",
  "active",
  "sla_overdue",
] as const;
const MAX_CURSOR_LENGTH = 16_384;
const MAX_QUERY_VALUE_LENGTH = 256;
const MAX_TARGET_LENGTH = 2_048;

type ExposureStringFilter =
  | "search"
  | "severity"
  | "target_kind"
  | "source_family"
  | "current_state"
  | "sla_state"
  | "completeness"
  | "deployment_state"
  | "source_state"
  | "weakness_id";

export type ExposureFilterState = Partial<
  Record<ExposureStringFilter, string>
> & {
  active?: boolean;
  sla_overdue?: boolean;
};

export interface ExposureQueryState {
  scope: ScopeSelection;
  filters: ExposureFilterState;
  sort: ExposureSort;
  pageSize: (typeof EXPOSURE_PAGE_SIZES)[number];
  cursor: string | null;
  cursorHistory: string[];
  page: number;
  target: string;
  drawer: string;
  generation: string;
}

export type ExposureQueryPatch = Partial<
  Omit<ExposureQueryState, "scope" | "filters" | "sort">
> & {
  scope?: ReadonlyScope;
  filters?: ExposureFilterState;
  sort?: ExposureSort;
};

export interface ExposureRestartState {
  required: boolean;
  reason: string;
  generation: string;
}

export const EXPOSURE_DETAIL_ORIGINS = [
  "/exposure/defender-posture",
  "/exposure/patch-priorities",
] as const;

export type ExposureDetailOrigin = (typeof EXPOSURE_DETAIL_ORIGINS)[number];

export interface ExposureDetailContext {
  origin: ExposureDetailOrigin;
  row: string;
  scroll: number | null;
}

type ReadonlyScope = Partial<
  Record<ScopeDimension, readonly string[]>
>;

function normalizedValues(values: readonly string[] | undefined): string[] {
  return Array.from(
    new Set((values ?? []).map((value) => value.trim()).filter(Boolean)),
  )
    .sort((left, right) => (left < right ? -1 : left > right ? 1 : 0));
}

function normalizedScope(scope: ReadonlyScope): ScopeSelection {
  const normalized: ScopeSelection = {};
  for (const dimension of SCOPE_DIMENSIONS) {
    const values = normalizedValues(scope[dimension]);
    if (values.length) normalized[dimension] = values;
  }
  return normalized;
}

function authorizedUrlScope(
  params: URLSearchParams,
  authorizedScope: ReadonlyScope,
): ScopeSelection {
  const fallback = normalizedScope(authorizedScope);
  const resolved: ScopeSelection = {};

  for (const dimension of SCOPE_DIMENSIONS) {
    const authorized = fallback[dimension] ?? [];
    const requested = normalizedValues(params.getAll(dimension));
    if (!requested.length) {
      if (authorized.length) resolved[dimension] = [...authorized];
      continue;
    }

    const authorizedByFoldedValue = new Map(
      authorized.map((value) => [value.toLocaleLowerCase("en-US"), value]),
    );
    const accepted = requested
      .map((value) => authorizedByFoldedValue.get(value.toLocaleLowerCase("en-US")))
      .filter((value): value is string => Boolean(value));
    if (accepted.length) {
      resolved[dimension] = normalizedValues(accepted);
    } else if (authorized.length) {
      // A URL value is context only, never authority. Falling back to the
      // already-authorized browser scope avoids both widening and a misleading
      // empty selection when a forged value is supplied.
      resolved[dimension] = [...authorized];
    }
  }
  return resolved;
}

function safeString(
  value: string | null,
  {
    maxLength = MAX_QUERY_VALUE_LENGTH,
    pattern,
    lower = false,
  }: { maxLength?: number; pattern?: RegExp; lower?: boolean } = {},
): string {
  const trimmed = value?.trim() ?? "";
  if (!trimmed || trimmed.length > maxLength || (pattern && !pattern.test(trimmed))) {
    return "";
  }
  return lower ? trimmed.toLocaleLowerCase("en-US") : trimmed;
}

function enumValue(
  value: string | null,
  allowed: ReadonlySet<string>,
): string {
  const normalized = safeString(value, { lower: true });
  return allowed.has(normalized) ? normalized : "";
}

function booleanValue(value: string | null): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

function filterState(params: URLSearchParams): ExposureFilterState {
  const filters: ExposureFilterState = {};
  const search = safeString(params.get("q"));
  if (search) filters.search = search;

  const severity = enumValue(params.get("severity"), ENUM_FILTERS.severity);
  if (severity) filters.severity = severity;
  const targetKind = enumValue(
    params.get("target_kind"),
    ENUM_FILTERS.target_kind,
  );
  if (targetKind) filters.target_kind = targetKind;
  const completeness = enumValue(
    params.get("completeness"),
    ENUM_FILTERS.completeness,
  );
  if (completeness) {
    filters.completeness = completeness;
  }
  for (const field of FREEFORM_FILTERS) {
    const value = safeString(params.get(field), {
      pattern: /^[a-zA-Z0-9._:-]+$/,
      lower: true,
    });
    if (value) filters[field] = value;
  }
  const active = booleanValue(params.get("active"));
  if (active !== undefined) filters.active = active;
  const slaOverdue = booleanValue(params.get("sla_overdue"));
  if (slaOverdue !== undefined) filters.sla_overdue = slaOverdue;
  return filters;
}

function pageSizeValue(value: string | null): ExposureQueryState["pageSize"] {
  const parsed = Number(value);
  return EXPOSURE_PAGE_SIZES.includes(
    parsed as ExposureQueryState["pageSize"],
  )
    ? (parsed as ExposureQueryState["pageSize"])
    : 50;
}

function cursorValue(value: string | null): string | null {
  const cursor = safeString(value, { maxLength: MAX_CURSOR_LENGTH });
  return cursor || null;
}

function detailOrigin(value: string | null): ExposureDetailOrigin {
  return EXPOSURE_DETAIL_ORIGINS.includes(value as ExposureDetailOrigin)
    ? (value as ExposureDetailOrigin)
    : "/exposure/patch-priorities";
}

function detailRow(value: string | null): string {
  return safeString(value, {
    maxLength: MAX_TARGET_LENGTH,
    pattern: /^[^\u0000-\u001f\u007f?#&=<>]+$/,
  });
}

function detailScroll(value: string | null): number | null {
  if (!value || !/^\d{1,8}$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 && parsed <= 10_000_000
    ? parsed
    : null;
}

/** Presentation-only detail context. It never changes the authorized scope. */
export function parseExposureDetailContext(
  params: URLSearchParams,
): ExposureDetailContext {
  return {
    origin: detailOrigin(params.get("origin")),
    row: detailRow(params.get("row")),
    scroll: detailScroll(params.get("scroll")),
  };
}

function detailContextParams(
  state: ExposureQueryState,
  context: ExposureDetailContext,
): URLSearchParams {
  const detailState: ExposureQueryState = {
    ...state,
    cursor: null,
    cursorHistory: [],
    page: 1,
  };
  const params = encodeExposureQueryState(detailState);
  params.set("origin", context.origin);
  if (context.row) params.set("row", context.row);
  if (context.scroll !== null) params.set("scroll", String(context.scroll));
  return params;
}

export function exposureDetailHref(
  kind: "cves" | "kbs",
  id: string,
  state: ExposureQueryState,
  context: ExposureDetailContext,
): string {
  const params = detailContextParams(state, context);
  return `/exposure/${kind}/${encodeURIComponent(id)}?${params.toString()}`;
}

export function exposureDetailReturnHref(
  state: ExposureQueryState,
  context: ExposureDetailContext,
): string {
  const params = detailContextParams(state, context);
  params.delete("origin");
  const suffix = params.toString();
  return suffix ? `${context.origin}?${suffix}` : context.origin;
}

export function exposureDetailParentLabel(
  origin: ExposureDetailOrigin,
): "Defender posture" | "Patch priorities" {
  return origin === "/exposure/defender-posture"
    ? "Defender posture"
    : "Patch priorities";
}

export function parseExposureQueryState(
  params: URLSearchParams,
  { authorizedScope }: { authorizedScope: ReadonlyScope },
): ExposureQueryState {
  const requestedSort = safeString(params.get("sort_by"), { lower: true });
  const requestedDirection = safeString(params.get("sort_direction"), {
    lower: true,
  });
  const cursor = cursorValue(params.get("cursor"));
  const cursorHistory = cursor
    ? params
        .getAll("cursor_back")
        .map(cursorValue)
        .filter((value): value is string => value !== null)
        .slice(0, 100)
    : [];
  const requestedPage = Number(params.get("page"));
  const page =
    cursor && Number.isSafeInteger(requestedPage) && requestedPage > 1
      ? Math.min(requestedPage, 10_000)
      : cursor
        ? cursorHistory.length + 2
        : 1;

  return {
    scope: authorizedUrlScope(params, authorizedScope),
    filters: filterState(params),
    sort: {
      field: SORT_FIELDS.has(requestedSort as ExposureSortField)
        ? (requestedSort as ExposureSortField)
        : DEFAULT_EXPOSURE_SORT.field,
      direction:
        requestedDirection === "asc" || requestedDirection === "desc"
          ? requestedDirection
          : DEFAULT_EXPOSURE_SORT.direction,
    },
    pageSize: pageSizeValue(params.get("page_size")),
    cursor,
    cursorHistory,
    page,
    target: safeString(params.get("target"), { maxLength: MAX_TARGET_LENGTH }),
    drawer: safeString(params.get("drawer"), {
      maxLength: 64,
      pattern: /^[a-zA-Z0-9_-]+$/,
      lower: true,
    }),
    generation: safeString(params.get("generation"), {
      pattern: /^[a-zA-Z0-9._:-]+$/,
    }),
  };
}

function appendScope(params: URLSearchParams, scope: ScopeSelection): void {
  for (const dimension of SCOPE_DIMENSIONS) {
    for (const value of normalizedValues(scope[dimension])) {
      params.append(dimension, value);
    }
  }
}

export function encodeExposureQueryState(
  state: ExposureQueryState,
): URLSearchParams {
  const params = new URLSearchParams();
  appendScope(params, state.scope);
  const stringEntries: Array<[string, string | undefined]> = [
    ["q", state.filters.search],
    ["severity", state.filters.severity],
    ["target_kind", state.filters.target_kind],
    ["source_family", state.filters.source_family],
    ["current_state", state.filters.current_state],
    ["sla_state", state.filters.sla_state],
    ["completeness", state.filters.completeness],
    ["deployment_state", state.filters.deployment_state],
    ["source_state", state.filters.source_state],
    ["weakness_id", state.filters.weakness_id],
  ];
  for (const [key, value] of stringEntries) {
    if (value) params.set(key, value);
  }
  if (state.filters.active !== undefined) {
    params.set("active", String(state.filters.active));
  }
  if (state.filters.sla_overdue !== undefined) {
    params.set("sla_overdue", String(state.filters.sla_overdue));
  }
  if (
    state.sort.field !== DEFAULT_EXPOSURE_SORT.field ||
    state.sort.direction !== DEFAULT_EXPOSURE_SORT.direction
  ) {
    params.set("sort_by", state.sort.field);
    params.set("sort_direction", state.sort.direction);
  }
  if (state.pageSize !== 50) params.set("page_size", String(state.pageSize));
  if (state.cursor) {
    params.set("cursor", state.cursor);
    for (const priorCursor of state.cursorHistory) {
      params.append("cursor_back", priorCursor);
    }
    params.set("page", String(state.page));
  }
  if (state.target) params.set("target", state.target);
  if (state.drawer) params.set("drawer", state.drawer);
  if (state.generation) params.set("generation", state.generation);
  return params;
}

function stableEntries(value: Record<string, unknown>): string {
  return JSON.stringify(
    Object.entries(value)
      .filter(([, item]) => item !== undefined && item !== "")
      .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0)),
  );
}

export function exposureQueryKey(state: ExposureQueryState): string {
  return JSON.stringify({
    scope: SCOPE_DIMENSIONS.map((dimension) => [
      dimension,
      normalizedValues(state.scope[dimension]),
    ]).filter(([, values]) => (values as string[]).length),
    filters: stableEntries(state.filters),
    sort: state.sort,
    pageSize: state.pageSize,
    cursor: state.cursor,
    generation: state.generation,
  });
}

function cursorBindingKey(state: ExposureQueryState): string {
  return JSON.stringify({
    scope: normalizedScope(state.scope),
    filters: stableEntries(state.filters),
    sort: state.sort,
    pageSize: state.pageSize,
  });
}

/** Identity used for retained rows while an opaque next/previous page loads. */
export function exposureRetentionKey(state: ExposureQueryState): string {
  return JSON.stringify({
    binding: cursorBindingKey(state),
    generation: state.generation,
  });
}

export function updateExposureQueryState(
  state: ExposureQueryState,
  patch: ExposureQueryPatch,
): ExposureQueryState {
  const updated: ExposureQueryState = {
    ...state,
    ...patch,
    scope: patch.scope ? normalizedScope(patch.scope) : state.scope,
    filters: patch.filters
      ? { ...state.filters, ...patch.filters }
      : state.filters,
    sort: patch.sort ?? state.sort,
  };
  if (cursorBindingKey(updated) !== cursorBindingKey(state)) {
    return {
      ...updated,
      cursor: null,
      cursorHistory: [],
      page: 1,
      generation: "",
    };
  }
  return updated;
}

export function advanceExposureCursor(
  state: ExposureQueryState,
  nextCursor: string,
): ExposureQueryState {
  const cursor = cursorValue(nextCursor);
  if (!cursor) throw new Error("A non-empty opaque Exposure cursor is required");
  return {
    ...state,
    cursor,
    cursorHistory: state.cursor
      ? [...state.cursorHistory, state.cursor]
      : state.cursorHistory,
    page: state.page + 1,
  };
}

export function retreatExposureCursor(
  state: ExposureQueryState,
): ExposureQueryState {
  if (state.page <= 1) return state;
  const history = [...state.cursorHistory];
  const cursor = history.pop() ?? null;
  return {
    ...state,
    cursor,
    cursorHistory: history,
    page: Math.max(1, state.page - 1),
  };
}

export function restartExposureQuery(
  state: ExposureQueryState,
): ExposureQueryState {
  return {
    ...state,
    cursor: null,
    cursorHistory: [],
    page: 1,
    generation: "",
  };
}

export function toExposureApiSearchParams(
  state: ExposureQueryState,
  {
    includePagination = true,
    includeSort = true,
  }: { includePagination?: boolean; includeSort?: boolean } = {},
): URLSearchParams {
  const params = scopeToSearchParams(state.scope);
  if (state.filters.search) params.set("q", state.filters.search);
  for (const key of API_FILTER_KEYS) {
    const value = state.filters[key];
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  if (includeSort) {
    params.set("sort_by", state.sort.field);
    params.set("sort_direction", state.sort.direction);
  }
  if (includePagination) {
    params.set("page_size", String(state.pageSize));
    if (state.cursor) params.set("cursor", state.cursor);
  }
  return params;
}

export function exposureRestartFromError(error: unknown): ExposureRestartState {
  if (!(error instanceof ApiError) || error.status !== 409) {
    return { required: false, reason: "", generation: "" };
  }
  const details = error.details ?? {};
  if (details.restart_required !== true) {
    return { required: false, reason: "", generation: "" };
  }
  const reason = safeString(
    typeof details.reason_code === "string" ? details.reason_code : "",
    { pattern: /^exposure_generation_(?:expired|evicted)$/ },
  );
  if (!reason) return { required: false, reason: "", generation: "" };
  return {
    required: true,
    reason,
    generation:
      typeof details.generation === "string"
        ? safeString(details.generation, {
            pattern: /^[a-zA-Z0-9._:-]+$/,
          })
        : "",
  };
}

export function createExposureSearchCommitter(
  commit: (value: string) => void,
  delay = EXPOSURE_SEARCH_DEBOUNCE_MS,
): {
  schedule: (value: string) => void;
  submit: (value: string) => void;
  dispose: () => void;
} {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const clear = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  return {
    schedule(value) {
      clear();
      timer = setTimeout(() => {
        timer = null;
        commit(value.trim());
      }, delay);
    },
    submit(value) {
      clear();
      commit(value.trim());
    },
    dispose: clear,
  };
}
