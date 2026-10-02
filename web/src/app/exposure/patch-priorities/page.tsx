"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { SourceSectionState } from "@/components/exposure/SourceSectionState";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { CountBarChart } from "@/components/ui/CountBarChart";
import { DonutChart } from "@/components/ui/DonutChart";
import { PageHeader, type PageHeaderCompleteness } from "@/components/ui/PageHeader";
import { RiskGauge } from "@/components/ui/RiskGauge";
import { StatusBadge, statusTone, toneColor } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useExposureSection } from "@/hooks/useExposureSection";
import {
  advanceExposureCursor,
  createExposureSearchCommitter,
  encodeExposureQueryState,
  exposureDetailHref,
  exposureQueryKey,
  exposureRetentionKey,
  parseExposureDetailContext,
  parseExposureQueryState,
  restartExposureQuery,
  retreatExposureCursor,
  updateExposureQueryState,
  type ExposureQueryState,
} from "@/lib/exposure-query-state";
import { useScope } from "@/lib/scope-context";
import { buildPatchPrioritiesCopilotContext } from "@/lib/copilot/page-adapters";
import { vulnerabilityApi } from "@/lib/services";
import type {
  ExposureEnvelope,
  ExposureFinding,
  ExposurePage,
  ExposureSort,
} from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

export interface PatchExposureFinding extends ExposureFinding {
  weakness_kind?: string;
  source_family?: string;
  source_state?: string;
  current_state?: string;
  severity?: string;
  priority_score?: number | null;
  recommendation?: string;
  finding_title?: string;
  sla_state?: string;
  sla_age_seconds?: number | null;
  sla_target_seconds?: number | null;
  sla_due_at?: string | null;
  sla_overdue?: boolean | null;
  detail_path?: string;
  governed_action_id?: string;
  execution_eligible?: boolean;
  package_name?: string;
  package_version?: string;
  evidence_refs?: Array<{ source_id?: string; source_family?: string }>;
}

const TARGET_KIND_OPTIONS = [
  { value: "server", label: "Servers" },
  { value: "container_image", label: "Container images" },
];
const PATCH_REFRESH_POLL_MS = 3_000;

type PatchPriorityView = "patch" | "vm" | "container";

const PATCH_PRIORITY_VIEWS: Array<{
  id: PatchPriorityView;
  label: string;
}> = [
  { id: "patch", label: "By patch" },
  { id: "vm", label: "By VM" },
  { id: "container", label: "By container image" },
];

const PATCH_PRIORITY_VIEW_COPY: Record<
  PatchPriorityView,
  {
    heading: string;
    description: string;
    searchLabel: string;
    caption: string;
    regionLabel: string;
  }
> = {
  patch: {
    heading: "Patch and vulnerability priorities",
    description:
      "Priority-ranked findings across represented servers and container images.",
    searchLabel: "Search patches and vulnerabilities",
    caption: "Scoped patch and vulnerability priorities",
    regionLabel: "Patch priorities table",
  },
  vm: {
    heading: "Patch priorities by VM",
    description:
      "Server findings sorted by VM so operators can review each machine's patch workload.",
    searchLabel: "Search VMs or patches",
    caption: "VM-organized patch priorities",
    regionLabel: "VM patch priorities table",
  },
  container: {
    heading: "Vulnerability priorities by container image",
    description:
      "Container findings sorted by immutable image target for governed review.",
    searchLabel: "Search container images or vulnerabilities",
    caption: "Container image vulnerability priorities",
    regionLabel: "Container image priorities table",
  },
};

function requestedPatchPriorityView(
  params: URLSearchParams,
  state: ExposureQueryState,
): PatchPriorityView {
  const requested = params.get("view");
  if (requested === "patch" || requested === "vm" || requested === "container") {
    return requested;
  }
  if (state.sort.field === "target_id") {
    if (state.filters.target_kind === "server") return "vm";
    if (state.filters.target_kind === "container_image") return "container";
  }
  return "patch";
}

function queryStateForView(
  state: ExposureQueryState,
  view: PatchPriorityView,
): ExposureQueryState {
  if (view === "patch") {
    return updateExposureQueryState(state, {
      sort: { field: "priority_score", direction: "desc" },
    });
  }
  const targetKind = view === "vm" ? "server" : "container_image";
  return updateExposureQueryState(state, {
    filters: {
      ...state.filters,
      target_kind: targetKind,
      source_family: targetKind === "container_image" ? "defender_image" : "aum",
    },
    sort: { field: "target_id", direction: "asc" },
  });
}

function displayDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return `Due ${new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed)}`;
}

function durationCopy(value: number | null | undefined): string | null {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return null;
  }
  const days = Math.floor(value / 86_400);
  if (days >= 1) return `SLA age ${days.toLocaleString("en-US")} ${days === 1 ? "day" : "days"}`;
  const hours = Math.floor(value / 3_600);
  if (hours >= 1) return `SLA age ${hours.toLocaleString("en-US")} ${hours === 1 ? "hour" : "hours"}`;
  return `SLA age ${Math.max(0, Math.floor(value / 60)).toLocaleString("en-US")} minutes`;
}

function priorityCopy(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "Not yet scored";
  }
  return `Priority score ${value.toLocaleString("en-US")}/100`;
}

function targetKindCopy(value: PatchExposureFinding["target_kind"]): string {
  return value === "container_image" ? "Container image" : "Server";
}

function targetName(value: string): string {
  if (value.startsWith("sha256:") && value.length > 31) {
    return `${value.slice(0, 20)}…${value.slice(-8)}`;
  }
  const segments = value.split("/").filter(Boolean);
  return segments.at(-1) || value;
}

function itemDetailHref(
  item: PatchExposureFinding,
  state: ExposureQueryState,
  scroll: number,
): string {
  const segment = item.weakness_kind === "kb" ? "kbs" : "cves";
  return exposureDetailHref(segment, item.weakness_id, state, {
    origin: "/exposure/patch-priorities",
    row: item.exposure_id,
    scroll,
  });
}

function headerCompleteness(
  page: ExposurePage<PatchExposureFinding> | null,
): PageHeaderCompleteness | undefined {
  const completeness = page?.contract.completeness ?? page?.completeness;
  if (!completeness) return undefined;
  const state =
    completeness.state === "complete" ||
    completeness.state === "partial" ||
    completeness.state === "stale" ||
    completeness.state === "unavailable"
      ? completeness.state
      : "unavailable";
  const freshnessValue = String(
    page?.contract.freshness.state ?? page?.freshness.state ?? "unknown",
  ).toLowerCase();
  return {
    state,
    freshness:
      freshnessValue === "current" || freshnessValue === "fresh"
        ? "current"
        : freshnessValue === "stale" || freshnessValue === "aging"
          ? "stale"
          : "unknown",
    representedConnections: completeness.represented_connections,
    expectedConnections: completeness.expected_connections,
    excludedCount:
      completeness.excluded ?? completeness.excluded_count,
  };
}

function canonicalPath(
  pathname: string,
  state: ExposureQueryState,
  view: PatchPriorityView = "patch",
): string {
  const params = encodeExposureQueryState(state);
  if (view !== "patch") params.set("view", view);
  const encoded = params.toString();
  return encoded ? `${pathname}?${encoded}` : pathname;
}

function remediationHref(
  item: PatchExposureFinding,
  pathname: string,
  state: ExposureQueryState,
  view: PatchPriorityView,
): string {
  const boundState = {
    ...state,
    target: item.target_id,
    generation: item.read_model_generation_id || state.generation,
  };
  const params = new URLSearchParams();
  params.set("resource_key", item.target_id);
  params.set("generation", boundState.generation);
  params.set("return_to", canonicalPath(pathname, boundState, view));
  params.set("return_focus", item.exposure_id);
  if (item.subscription_id) params.append("subscription", item.subscription_id);
  if (item.weakness_kind === "kb") {
    params.append("kb", item.weakness_id);
  } else {
    params.append("cve", item.weakness_id);
  }
  return `/remediation?${params.toString()}`;
}

function nextSort(current: ExposureSort): ExposureSort {
  if (current.field !== "priority_score") {
    return { field: "priority_score", direction: "desc" };
  }
  return {
    field: "priority_score",
    direction: current.direction === "desc" ? "asc" : "desc",
  };
}

function patchSectionTrust(
  status: ReturnType<typeof useExposureSection>["status"],
): { available: boolean; freshness: "fresh" | "partial" | "stale" | "unavailable" } {
  const available = status !== "unavailable" && status !== "loading";
  const freshness =
    status === "current" || status === "healthy-empty"
      ? ("fresh" as const)
      : status === "partial"
        ? ("partial" as const)
        : status === "stale"
          ? ("stale" as const)
          : ("unavailable" as const);
  return { available, freshness };
}

/** Server-backed patch priorities over the canonical scoped Exposure read model. */
export default function PatchPrioritiesPage() {
  const { scope } = useScope();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const detailContext = useMemo(
    () => parseExposureDetailContext(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const parsedQueryState = useMemo(
    () => {
      const parsed = parseExposureQueryState(
        new URLSearchParams(searchParams.toString()),
        {
        authorizedScope: scope,
        },
      );
      const targetKind = parsed.filters.target_kind ?? "server";
      const sourceFamily =
        targetKind === "container_image" ? "defender_image" : "aum";
      return {
        ...parsed,
        filters: {
          ...parsed.filters,
          target_kind: targetKind,
          source_family: sourceFamily,
        },
      };
    },
    [scope, searchParams],
  );
  const view = useMemo(
    () =>
      requestedPatchPriorityView(
        new URLSearchParams(searchParams.toString()),
        parsedQueryState,
      ),
    [parsedQueryState, searchParams],
  );
  const includeResolved = searchParams.get("include_resolved") === "1";
  const queryState = useMemo(() => {
    const base =
      view === "patch"
        ? parsedQueryState
        : queryStateForView(parsedQueryState, view);
    // Patch priorities are about what still needs action. Without this
    // default, already-installed/resolved findings (e.g. compliant KBs)
    // appear alongside genuinely missing patches, which is misleading.
    // Applied as a plain merge (not updateExposureQueryState) so this
    // implicit default never resets an in-flight cursor/generation.
    if (includeResolved || base.filters.active !== undefined) return base;
    return { ...base, filters: { ...base.filters, active: true } };
  }, [parsedQueryState, view, includeResolved]);
  const viewCopy = PATCH_PRIORITY_VIEW_COPY[view];
  const [searchDraft, setSearchDraft] = useState(
    queryState.filters.search ?? "",
  );
  const searchStateRef = useRef(queryState);
  searchStateRef.current = queryState;

  const commitQuery = useCallback(
    (next: ExposureQueryState, nextView: PatchPriorityView = view) => {
      router.replace(canonicalPath(pathname, next, nextView), { scroll: false });
    },
    [pathname, router, view],
  );
  const commitQueryRef = useRef(commitQuery);
  commitQueryRef.current = commitQuery;
  const searchCommitterRef = useRef<ReturnType<
    typeof createExposureSearchCommitter
  > | null>(null);
  if (searchCommitterRef.current === null) {
    searchCommitterRef.current = createExposureSearchCommitter((value) => {
      const current = searchStateRef.current;
      if (value === (current.filters.search ?? "")) return;
      commitQueryRef.current(
        updateExposureQueryState(current, {
          filters: { ...current.filters, search: value || undefined },
        }),
      );
    });
  }
  const searchCommitter = searchCommitterRef.current;

  useEffect(() => () => searchCommitter.dispose(), [searchCommitter]);
  useEffect(() => {
    setSearchDraft(queryState.filters.search ?? "");
  }, [queryState.filters.search]);

  const section = useExposureSection<ExposurePage<PatchExposureFinding>>({
    queryKey: exposureQueryKey(queryState),
    retentionKey: exposureRetentionKey(queryState),
    load: ({ signal }) =>
      vulnerabilityApi.exposureItems(queryState, { signal }) as Promise<
        ExposureEnvelope<ExposurePage<PatchExposureFinding>>
      >,
    isEmpty: (page) => page.items.length === 0,
  });
  const [copilotOpen, setCopilotOpen] = useState(false);
  const restoredTargetRef = useRef("");
  const page = section.data;
  const refreshState = page?.freshness.refresh;
  const rows = useMemo(() => page?.items ?? [], [page?.items]);
  const sectionPresentation = {
    ...section,
    metadata: {
      ...section.metadata,
      represented:
        page?.contract.completeness.represented_connections ??
        section.metadata.represented,
      expected:
        page?.contract.completeness.expected_connections ??
        section.metadata.expected,
    },
  };
  const represented =
    page?.contract.counts.represented ??
    page?.contract.completeness.represented ??
    page?.total_count ??
    0;
  const total =
    page?.contract.counts.total ??
    page?.contract.completeness.total ??
    page?.total_count ??
    0;
  const excluded =
    page?.contract.counts.excluded ??
    page?.contract.completeness.excluded ??
    0;
  const first = rows.length === 0 ? 0 : (queryState.page - 1) * queryState.pageSize + 1;
  const last = rows.length === 0 ? 0 : first + rows.length - 1;
  const targetKind = queryState.filters.target_kind ?? "server";

  const severityBreakdown = useMemo(() => {
    const order = ["critical", "high", "medium", "low", "unknown"];
    const counts = new Map<string, number>();
    for (const item of rows) {
      const key = (item.severity || "unknown").toLowerCase();
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    const labeled = order.map((key) => ({ key, label: key.charAt(0).toUpperCase() + key.slice(1) }));
    for (const key of Array.from(counts.keys())) {
      if (!order.includes(key)) labeled.push({ key, label: key.charAt(0).toUpperCase() + key.slice(1) });
    }
    return labeled.map(({ key, label }) => ({
      label,
      value: counts.get(key) ?? 0,
      color: toneColor(statusTone(key)),
      filterValue: key,
    }));
  }, [rows]);

  const targetBreakdown = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of rows) {
      const key = targetName(item.target_id) || "Unattributed";
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([label, value]) => ({ id: label, label, value }));
  }, [rows]);

  const coveragePercent = total > 0 ? Math.round((represented / total) * 100) : null;

  // Read-only contextual Copilot over the already-loaded patch-priority queue.
  // Governed remediation stays behind existing server endpoints (D-03, D-04, D-10).
  const patchCopilot = buildPatchPrioritiesCopilotContext({
    scope,
    rows: rows.map((row) => ({
      exposure_id: row.exposure_id,
      target_id: row.target_id,
      weakness_id: row.weakness_id,
      missing_kb: row.weakness_kind === "kb" ? row.weakness_id : undefined,
      server_id: row.target_id,
      severity: row.severity,
      priority_score: row.priority_score,
      recommendation: row.recommendation,
      sla_state: row.sla_state,
      sla_overdue: row.sla_overdue,
    })),
    loadedCount: rows.length,
    totalCount: page?.total_count ?? rows.length,
    available: patchSectionTrust(section.status).available,
    freshness: patchSectionTrust(section.status).freshness,
    observedAt: section.metadata.observedAt,
    filters: {
      target_kind: [targetKind],
      view: [view],
      page: [String(queryState.page)],
    },
    sort: queryState.sort
      ? { [queryState.sort.field]: queryState.sort.direction }
      : undefined,
    evidence: section.envelope?.evidence ?? [],
    sourceStatuses: [
      {
        source: "patch_priorities",
        ...patchSectionTrust(section.status),
        observedAt: section.metadata.observedAt,
      },
    ],
  });

  const updateFilter = useCallback(
    (field: "target_kind", value: string) => {
      const targetKind = value;
      commitQuery(
        updateExposureQueryState(queryState, {
          filters: {
            ...queryState.filters,
            [field]: targetKind,
            source_family:
              targetKind === "container_image" ? "defender_image" : "aum",
          },
        }),
      );
    },
    [commitQuery, queryState],
  );

  const toggleSeverityFilter = useCallback(
    (value: string) => {
      const next = queryState.filters.severity === value ? undefined : value;
      commitQuery(
        updateExposureQueryState(queryState, {
          filters: { ...queryState.filters, severity: next },
        }),
      );
    },
    [commitQuery, queryState],
  );

  const setIncludeResolved = useCallback(
    (next: boolean) => {
      const params = encodeExposureQueryState(queryState);
      if (view !== "patch") params.set("view", view);
      if (next) {
        // Showing resolved/installed findings requires dropping the
        // active-only default so both states are represented.
        params.delete("active");
        params.set("include_resolved", "1");
      } else {
        params.delete("include_resolved");
        params.delete("active");
      }
      const encoded = params.toString();
      router.replace(encoded ? `${pathname}?${encoded}` : pathname, {
        scroll: false,
      });
    },
    [pathname, queryState, router, view],
  );

  const selectView = useCallback(
    (nextView: PatchPriorityView) => {
      commitQuery(queryStateForView(queryState, nextView), nextView);
    },
    [commitQuery, queryState],
  );

  useEffect(() => {
    const restoreIdentity = detailContext.row || queryState.target;
    if (
      !rows.length ||
      !restoreIdentity ||
      restoredTargetRef.current === restoreIdentity
    ) {
      return;
    }
    const match = rows.find(
      (item) =>
        item.exposure_id === restoreIdentity ||
        item.target_id === restoreIdentity ||
        item.target_id.endsWith(`/${restoreIdentity}`),
    );
    if (!match) return;
    const row = document.getElementById(match.exposure_id);
    row?.focus({ preventScroll: true });
    if (detailContext.scroll !== null && document.scrollingElement) {
      document.scrollingElement.scrollTop = detailContext.scroll;
    } else {
      row?.scrollIntoView?.({ block: "center" });
    }
    restoredTargetRef.current = restoreIdentity;
  }, [detailContext.row, detailContext.scroll, queryState.target, rows]);

  useEffect(() => {
    if (!refreshState?.refreshing) return;
    const timer = window.setTimeout(section.retry, PATCH_REFRESH_POLL_MS);
    return () => window.clearTimeout(timer);
  }, [refreshState?.refreshing, section.retry]);

  return (
    <div className="page-container exposure-patch-priorities">
      <PageHeader
        eyebrow="Exposure management"
        title="Patch priorities"
        description="Review patch and vulnerability evidence by priority, VM, or container image with governed next actions."
        completeness={headerCompleteness(page)}
        actions={
          <CopilotDrawerButton
            onClick={() => setCopilotOpen(true)}
            label="Ask Copilot about patch priorities"
          />
        }
      />

      <CopilotInsights
        snapshot={patchCopilot.snapshot}
        requestedScope={patchCopilot.requestedScope}
        contextLabel="Patch priorities"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      {section.restart.required && (
        <div className="callout callout-warning" role="alert">
          <p>
            The retained Exposure generation expired. Restart from the first
            page to continue safely.
          </p>
          <button
            type="button"
            className="button"
            onClick={() => commitQuery(restartExposureQuery(queryState))}
          >
            Restart results
          </button>
        </div>
      )}

      {refreshState?.refreshing && (
        <div className="callout callout-info" role="status">
          Refreshing patch priorities in the background. Showing the last
          known good snapshot
          {refreshState.last_success_at
            ? ` from ${refreshState.last_success_at}`
            : ""}
          .
        </div>
      )}

      {!refreshState?.refreshing && refreshState?.failure_code && (
        <div className="callout callout-warning" role="alert">
          The background patch refresh failed. Showing the last known good
          snapshot
          {refreshState.last_success_at
            ? ` from ${refreshState.last_success_at}`
            : ""}
          .
        </div>
      )}

      {!refreshState?.refreshing &&
        !refreshState?.failure_code &&
        refreshState?.last_success_at && (
          <div className="callout callout-info" role="status">
            Patch priorities refreshed {refreshState.last_success_at}.
          </div>
        )}

      <SourceSectionState
        sourceName="Patch priority evidence"
        itemLabel="findings"
        state={sectionPresentation}
      >
        <section className="card queue-card" aria-labelledby="patch-priority-heading">
          <div className="card-header">
            <div>
              <h2 id="patch-priority-heading">{viewCopy.heading}</h2>
              <p>
                {represented.toLocaleString("en-US")} represented findings ·{" "}
                {total.toLocaleString("en-US")} total findings ·{" "}
                {excluded.toLocaleString("en-US")} excluded findings
              </p>
              <p>{viewCopy.description}</p>
            </div>
          </div>

          {rows.length > 0 && (
            <div className="card-body dashboard-charts-row">
              <div className="chart-card">
                <h3 className="chart-card-title">Severity mix (this page)</h3>
                <DonutChart
                  segments={severityBreakdown}
                  centerValue={rows.length}
                  centerLabel="findings"
                  onSegmentClick={toggleSeverityFilter}
                  activeFilterValue={queryState.filters.severity ?? null}
                />
              </div>
              <div className="chart-card">
                <h3 className="chart-card-title">Top targets (this page)</h3>
                <CountBarChart data={targetBreakdown} unit="target" />
              </div>
              {coveragePercent !== null && (
                <div className="chart-card">
                  <h3 className="chart-card-title">Queue coverage</h3>
                  <RiskGauge
                    score={coveragePercent}
                    invert
                    label="Represented of total"
                    detail={`${represented.toLocaleString("en-US")} of ${total.toLocaleString("en-US")} findings represented`}
                  />
                </div>
              )}
            </div>
          )}

          <div className="card-body patch-priority-view-controls">
            <div className="form-field">
              <span id="patch-priority-view-label">Organize findings</span>
              <div
                className="segmented-control"
                role="group"
                aria-labelledby="patch-priority-view-label"
              >
                {PATCH_PRIORITY_VIEWS.map((candidate) => (
                  <button
                    key={candidate.id}
                    type="button"
                    className={view === candidate.id ? "segmented-active" : ""}
                    aria-pressed={view === candidate.id}
                    onClick={() => selectView(candidate.id)}
                  >
                    {candidate.label}
                  </button>
                ))}
              </div>
            </div>
            <label className="form-field" htmlFor="patch-exposure-search">
              <span>{viewCopy.searchLabel}</span>
              <input
                id="patch-exposure-search"
                type="search"
                value={searchDraft}
                onChange={(event) => {
                  setSearchDraft(event.target.value);
                  searchCommitter.schedule(event.target.value);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    searchCommitter.submit(event.currentTarget.value);
                  }
                }}
              />
            </label>
          </div>

          <div className="form-field patch-priority-status-toggle">
            <label>
              <input
                type="checkbox"
                checked={includeResolved}
                onChange={(event) => setIncludeResolved(event.target.checked)}
              />
              Include already-installed / resolved findings
            </label>
          </div>

          {view === "patch" && (
            <TableColumnFilters
              filters={[
                {
                  id: "target_kind",
                  label: "Target kind",
                  value: targetKind,
                  defaultValue: "server",
                  options: TARGET_KIND_OPTIONS,
                  onChange: (value) => updateFilter("target_kind", value),
                },
              ]}
              resultCount={rows.length}
              totalCount={page?.total_count ?? 0}
              onReset={() => updateFilter("target_kind", "server")}
            />
          )}

          {rows.length > 0 && (
            <div
              className="table-scroll exposure-responsive-table"
              role="region"
              aria-label={viewCopy.regionLabel}
              tabIndex={0}
            >
              <p className="table-scroll-hint">Scroll horizontally to see all columns</p>
              <table className="operations-table exposure-table">
                <caption>{viewCopy.caption}</caption>
                <thead>
                  <tr>
                    <th>Rank</th>
                    {view === "patch" ? (
                      <>
                        <th>Finding</th>
                        <th>Target</th>
                      </>
                    ) : (
                      <>
                        <th>{view === "vm" ? "VM" : "Container image"}</th>
                        <th>{view === "vm" ? "Missing patch" : "Vulnerability"}</th>
                      </>
                    )}
                    <th>Evidence</th>
                    <th>SLA</th>
                    <th
                      aria-sort={
                        queryState.sort.field === "priority_score"
                          ? queryState.sort.direction === "desc"
                            ? "descending"
                            : "ascending"
                          : "none"
                      }
                    >
                      <button
                        type="button"
                        className="table-sort-button"
                        aria-label="Sort by operational priority"
                        onClick={() =>
                          commitQuery(
                            updateExposureQueryState(queryState, {
                              sort: nextSort(queryState.sort),
                            }),
                          )
                        }
                      >
                        Operational priority
                      </button>
                    </th>
                    <th>Governed action</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((item, index) => {
                    const rank = first + index;
                    const isServer = item.target_kind === "server";
                    const findingCell = (
                      <td
                        data-label={
                          view === "vm"
                            ? "Missing patch"
                            : view === "container"
                              ? "Vulnerability"
                              : "Finding"
                        }
                      >
                        <div className="exposure-finding-heading">
                          <Link
                            className="table-primary-link"
                            href={itemDetailHref(item, queryState, 0)}
                            onClick={(event) => {
                              if (
                                event.button === 0 &&
                                !event.metaKey &&
                                !event.ctrlKey &&
                                !event.shiftKey &&
                                !event.altKey
                              ) {
                                event.preventDefault();
                                router.push(
                                  itemDetailHref(
                                    item,
                                    queryState,
                                    Math.max(0, Math.round(window.scrollY)),
                                  ),
                                );
                              }
                            }}
                          >
                            {item.weakness_id}
                          </Link>
                          <StatusBadge
                            label={item.severity ?? "Unknown severity"}
                            tone={statusTone(item.severity ?? "unknown")}
                            compact
                          />
                        </div>
                        {item.finding_title ? (
                          <div className="table-secondary exposure-long-value">
                            {item.finding_title}
                          </div>
                        ) : null}
                        <div className="table-secondary">
                          {item.recommendation || "Recommendation unavailable"}
                        </div>
                      </td>
                    );
                    const targetCell = (
                      <td
                        data-label={
                          view === "vm"
                            ? "VM"
                            : view === "container"
                              ? "Container image"
                              : "Target"
                        }
                      >
                        <strong className="exposure-long-value">
                          {targetName(item.target_id)}
                        </strong>
                        <div>
                          <StatusBadge
                            label={targetKindCopy(item.target_kind)}
                            tone="neutral"
                          />
                        </div>
                        <div
                          className="table-secondary resource-id-cell"
                          title={item.target_id}
                        >
                          {item.target_id}
                        </div>
                      </td>
                    );
                    return (
                      <tr key={item.exposure_id} id={item.exposure_id} tabIndex={-1}>
                        <td data-label="Rank">
                          <span className="rank-badge">{rank.toLocaleString("en-US")}</span>
                        </td>
                        {view === "patch" ? (
                          <>
                            {findingCell}
                            {targetCell}
                          </>
                        ) : (
                          <>
                            {targetCell}
                            {findingCell}
                          </>
                        )}
                        <td data-label="Evidence">
                          <strong>
                            {(item.source_families ?? [item.source_family].filter(Boolean)).join(", ") ||
                              "Unknown source"}
                          </strong>
                          <div className="table-secondary">
                            {item.package_name
                              ? `${item.package_name}${item.package_version ? ` ${item.package_version}` : ""}`
                              : `${item.weakness_kind?.toUpperCase() || "Weakness"} evidence`}
                          </div>
                        </td>
                        <td data-label="SLA">
                          <StatusBadge
                            label={item.sla_state || "Not yet scored"}
                            tone={item.sla_overdue ? "critical" : "neutral"}
                          />
                          {durationCopy(item.sla_age_seconds) ? (
                            <div className="table-secondary">
                              {durationCopy(item.sla_age_seconds)}
                            </div>
                          ) : null}
                          {displayDate(item.sla_due_at) ? (
                            <div className="table-secondary">
                              {displayDate(item.sla_due_at)}
                            </div>
                          ) : null}
                        </td>
                        <td data-label="Operational priority">
                          <strong>{priorityCopy(item.priority_score)}</strong>
                        </td>
                        <td data-label="Governed action">
                          {isServer && item.execution_eligible ? (
                            <Link
                              className="button button-primary"
                              href={remediationHref(item, pathname, queryState, view)}
                            >
                              Open governed remediation for {item.weakness_id}
                            </Link>
                          ) : (
                            <span className="table-secondary">
                              {isServer === false
                                ? "No safe container action"
                                : "No safe action available"}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {page && (
            <TablePagination
              mode="cursor"
              cursor={{
                total: page.total_count,
                returnedCount: rows.length,
                first,
                last,
                hasMore: Boolean(page.next_cursor),
                hasPrevious: queryState.page > 1,
                historyDepth: queryState.cursorHistory.length,
                representedCount: represented,
              }}
              busy={section.refreshing}
              pageSize={queryState.pageSize}
              onPageSizeChange={(pageSize) =>
                commitQuery(updateExposureQueryState(queryState, { pageSize }))
              }
              onPreviousCursor={() =>
                commitQuery(retreatExposureCursor(queryState))
              }
              onNextCursor={() => {
                if (page.next_cursor) {
                  commitQuery(
                    advanceExposureCursor(
                      {
                        ...queryState,
                        generation: page.generation,
                      },
                      page.next_cursor,
                    ),
                  );
                }
              }}
              label="findings"
            />
          )}
        </section>
      </SourceSectionState>

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Patch priorities"
        requestedScope={patchCopilot.requestedScope}
        snapshot={patchCopilot.snapshot}
        starterQuestions={patchCopilot.starterQuestions}
      />
    </div>
  );
}
