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
import { PageHeader, type PageHeaderCompleteness } from "@/components/ui/PageHeader";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useExposureSection } from "@/hooks/useExposureSection";
import {
  advanceExposureCursor,
  createExposureSearchCommitter,
  encodeExposureQueryState,
  exposureQueryKey,
  exposureRetentionKey,
  parseExposureQueryState,
  restartExposureQuery,
  retreatExposureCursor,
  updateExposureQueryState,
  type ExposureQueryState,
} from "@/lib/exposure-query-state";
import { useScope } from "@/lib/scope-context";
import { vulnerabilityApi } from "@/lib/services";
import type {
  ExposureEnvelope,
  ExposureFinding,
  ExposurePage,
  ExposureSort,
} from "@/lib/types";

export interface PatchExposureFinding extends ExposureFinding {
  weakness_kind?: string;
  source_family?: string;
  source_state?: string;
  current_state?: string;
  severity?: string;
  priority_score?: number | null;
  recommendation?: string;
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

function displayDate(value: string | null | undefined): string {
  if (!value) return "Due date unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Due date unknown";
  return `Due ${new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed)}`;
}

function durationCopy(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "SLA age unknown";
  }
  const days = Math.floor(value / 86_400);
  if (days >= 1) return `SLA age ${days.toLocaleString("en-US")} ${days === 1 ? "day" : "days"}`;
  const hours = Math.floor(value / 3_600);
  if (hours >= 1) return `SLA age ${hours.toLocaleString("en-US")} ${hours === 1 ? "hour" : "hours"}`;
  return `SLA age ${Math.max(0, Math.floor(value / 60)).toLocaleString("en-US")} minutes`;
}

function priorityCopy(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "Priority score unknown";
  }
  return `Priority score ${value.toLocaleString("en-US")}/100`;
}

function targetKindCopy(value: PatchExposureFinding["target_kind"]): string {
  return value === "container_image" ? "Container image" : "Server";
}

function itemDetailHref(item: PatchExposureFinding): string {
  if (item.detail_path?.startsWith("/exposure/")) return item.detail_path;
  const segment = item.weakness_kind === "kb" ? "kbs" : "cves";
  return `/exposure/${segment}/${encodeURIComponent(item.weakness_id)}`;
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

function canonicalPath(pathname: string, state: ExposureQueryState): string {
  const encoded = encodeExposureQueryState(state).toString();
  return encoded ? `${pathname}?${encoded}` : pathname;
}

function remediationHref(
  item: PatchExposureFinding,
  pathname: string,
  state: ExposureQueryState,
): string {
  const boundState = {
    ...state,
    target: item.target_id,
    generation: item.read_model_generation_id || state.generation,
  };
  const params = new URLSearchParams();
  params.set("resource_key", item.target_id);
  params.set("generation", boundState.generation);
  params.set("return_to", canonicalPath(pathname, boundState));
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

/** Server-backed patch priorities over the canonical scoped Exposure read model. */
export default function PatchPrioritiesPage() {
  const { scope } = useScope();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryState = useMemo(
    () =>
      parseExposureQueryState(new URLSearchParams(searchParams.toString()), {
        authorizedScope: scope,
      }),
    [scope, searchParams],
  );
  const [searchDraft, setSearchDraft] = useState(
    queryState.filters.search ?? "",
  );
  const searchStateRef = useRef(queryState);
  searchStateRef.current = queryState;

  const commitQuery = useCallback(
    (next: ExposureQueryState) => {
      router.replace(canonicalPath(pathname, next), { scroll: false });
    },
    [pathname, router],
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
  const page = section.data;
  const rows = page?.items ?? [];
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
  const targetKind = queryState.filters.target_kind ?? "all";

  const updateFilter = useCallback(
    (field: "target_kind", value: string) => {
      commitQuery(
        updateExposureQueryState(queryState, {
          filters: {
            ...queryState.filters,
            [field]: value === "all" ? undefined : value,
          },
        }),
      );
    },
    [commitQuery, queryState],
  );

  return (
    <div className="page-container exposure-patch-priorities">
      <PageHeader
        eyebrow="Exposure management"
        title="Patch priorities"
        description="Review server-backed patch and vulnerability evidence, SLA state, and governed next actions."
        completeness={headerCompleteness(page)}
      />

      <SourceSectionState
        sourceName="Patch priority evidence"
        itemLabel="findings"
        state={section}
      >
        {section.restart.required && (
          <div className="callout callout-warning" role="alert">
            <p>The retained Exposure generation expired. Restart from the first page to continue safely.</p>
            <button
              type="button"
              className="button"
              onClick={() => commitQuery(restartExposureQuery(queryState))}
            >
              Restart results
            </button>
          </div>
        )}

        <section className="card queue-card" aria-labelledby="patch-priority-heading">
          <div className="card-header">
            <div>
              <h2 id="patch-priority-heading">Patch and vulnerability priorities</h2>
              <p>
                {represented.toLocaleString("en-US")} represented findings ·{" "}
                {total.toLocaleString("en-US")} total findings ·{" "}
                {excluded.toLocaleString("en-US")} excluded findings
              </p>
            </div>
          </div>

          <div className="card-body">
            <label className="form-field" htmlFor="patch-exposure-search">
              <span>Search exposure</span>
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

          <TableColumnFilters
            filters={[
              {
                id: "target_kind",
                label: "Target kind",
                value: targetKind,
                options: TARGET_KIND_OPTIONS,
                onChange: (value) => updateFilter("target_kind", value),
              },
            ]}
            resultCount={rows.length}
            totalCount={page?.total_count ?? 0}
            onReset={() => updateFilter("target_kind", "all")}
          />

          {rows.length > 0 && (
            <div
              className="table-scroll exposure-responsive-table"
              role="region"
              aria-label="Patch priorities table"
              tabIndex={0}
            >
              <p className="table-scroll-hint">Scroll horizontally to see all columns</p>
              <table className="operations-table exposure-table">
                <caption>Scoped patch and vulnerability priorities</caption>
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>Finding</th>
                    <th>Target</th>
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
                    return (
                      <tr key={item.exposure_id} id={item.exposure_id} tabIndex={-1}>
                        <td data-label="Rank">Rank {rank.toLocaleString("en-US")}</td>
                        <td data-label="Finding">
                          <Link className="table-primary-link" href={itemDetailHref(item)}>
                            {item.weakness_id}
                          </Link>
                          <div className="table-secondary">
                            {item.recommendation || "Recommendation unavailable"}
                          </div>
                        </td>
                        <td data-label="Target">
                          <StatusBadge label={targetKindCopy(item.target_kind)} tone="neutral" />
                          <div className="table-secondary exposure-long-value">{item.target_id}</div>
                        </td>
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
                            label={item.sla_state || "indeterminate"}
                            tone={item.sla_overdue ? "critical" : "neutral"}
                          />
                          <div className="table-secondary">{durationCopy(item.sla_age_seconds)}</div>
                          <div className="table-secondary">{displayDate(item.sla_due_at)}</div>
                        </td>
                        <td data-label="Operational priority">
                          <strong>{priorityCopy(item.priority_score)}</strong>
                        </td>
                        <td data-label="Governed action">
                          {isServer && item.execution_eligible ? (
                            <Link
                              className="button button-primary"
                              href={remediationHref(item, pathname, queryState)}
                            >
                              Open governed remediation for {item.weakness_id}
                            </Link>
                          ) : (
                            <span className="table-secondary">
                              {item.target_kind === "container_image"
                                ? "Governed container review required"
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
    </div>
  );
}
