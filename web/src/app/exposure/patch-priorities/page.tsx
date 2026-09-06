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

import {
  RiskExceptionDialog,
  type RiskExceptionRevokeOutcome,
  type RiskExceptionRevokeRequest,
  type RiskExceptionRevokeResult,
} from "@/components/exposure/RiskExceptionDialog";
import { SourceSectionState } from "@/components/exposure/SourceSectionState";
import { PageHeader, type PageHeaderCompleteness } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useApi } from "@/hooks/useApi";
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
import {
  remediationApi,
  vulnerabilityApi,
  type ExposureRemediationCase,
} from "@/lib/services";
import type {
  ExposureEnvelope,
  ExposureFinding,
  ExposurePage,
  ExposureSort,
  RiskException,
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

function containerReviewHref(
  item: PatchExposureFinding,
  handoff: ExposureRemediationCase,
  pathname: string,
  state: ExposureQueryState,
): string {
  const boundState = {
    ...state,
    target: item.target_id,
    generation: item.read_model_generation_id || state.generation,
  };
  const params = new URLSearchParams();
  params.set("handoff", handoff.handoff_id || handoff.exposure_id);
  params.set("generation", boundState.generation);
  params.set("return_to", canonicalPath(pathname, boundState));
  params.set("return_focus", item.exposure_id);
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
  const detailContext = useMemo(
    () => parseExposureDetailContext(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
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
  const handoffs = useApi(
    () => remediationApi.exposureHandoffs(queryState.scope),
    [exposureRetentionKey(queryState)],
  );
  const riskExceptions = useApi(
    () => vulnerabilityApi.riskExceptions(queryState.scope),
    [exposureRetentionKey(queryState)],
  );
  const [selectedExceptions, setSelectedExceptions] = useState<Set<string>>(
    new Set(),
  );
  const [riskDialogOpen, setRiskDialogOpen] = useState(false);
  const revokeInvokerRef = useRef<HTMLButtonElement>(null);
  const restoredTargetRef = useRef("");
  const page = section.data;
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
  const exceptionRows = riskExceptions.data?.data ?? [];
  const selectedExceptionRows = exceptionRows.filter((exception) =>
    selectedExceptions.has(exception.exception_id),
  );
  const handoffByExposureId = useMemo(
    () =>
      new Map(
        (handoffs.data?.data.cases ?? []).map((handoff) => [
          handoff.exposure_id,
          handoff,
        ]),
      ),
    [handoffs.data],
  );
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

  const revokeSelected = async (
    request: RiskExceptionRevokeRequest,
  ): Promise<RiskExceptionRevokeResult> => {
    const outcomes: RiskExceptionRevokeOutcome[] = [];
    for (let index = 0; index < request.exceptionIds.length; index += 1) {
      const exceptionId = request.exceptionIds[index];
      try {
        await vulnerabilityApi.revokeRiskException(exceptionId);
        outcomes.push({ exceptionId, status: "succeeded" });
      } catch (error) {
        outcomes.push({
          exceptionId,
          status: "failed",
          message: error instanceof Error ? error.message : String(error),
        });
        for (const remainingId of request.exceptionIds.slice(index + 1)) {
          outcomes.push({
            exceptionId: remainingId,
            status: "not_attempted",
            message: "Not attempted after an earlier revocation failed.",
          });
        }
        return {
          status: "partial",
          auditId: outcomes.find((outcome) => outcome.status === "succeeded")
            ?.exceptionId,
          outcomes,
        };
      }
    }
    return {
      status: "success",
      auditId: outcomes[0]?.exceptionId,
      outcomes,
    };
  };

  return (
    <div className="page-container exposure-patch-priorities">
      <PageHeader
        eyebrow="Exposure management"
        title="Patch priorities"
        description="Review server-backed patch and vulnerability evidence, SLA state, and governed next actions."
        completeness={headerCompleteness(page)}
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

      <SourceSectionState
        sourceName="Patch priority evidence"
        itemLabel="findings"
        state={sectionPresentation}
      >
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
                    const containerHandoff = handoffByExposureId.get(
                      item.exposure_id,
                    );
                    const canReviewContainer =
                      isServer === false &&
                      containerHandoff?.outcome === "review_handoff" &&
                      containerHandoff.direct_execution_supported === false;
                    return (
                      <tr key={item.exposure_id} id={item.exposure_id} tabIndex={-1}>
                        <td data-label="Rank">Rank {rank.toLocaleString("en-US")}</td>
                        <td data-label="Finding">
                          <Link
                            className="table-primary-link"
                            href={itemDetailHref(item, queryState, 0)}
                            onClick={(event) => {
                              event.currentTarget.href = itemDetailHref(
                                item,
                                queryState,
                                Math.max(0, Math.round(window.scrollY)),
                              );
                            }}
                          >
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
                          ) : canReviewContainer && containerHandoff ? (
                            <>
                              <Link
                                className="button button-primary"
                                href={containerReviewHref(
                                  item,
                                  containerHandoff,
                                  pathname,
                                  queryState,
                                )}
                              >
                                Open governed container review for {item.weakness_id}
                              </Link>
                              <span className="table-secondary">
                                Nothing executes from Exposure.
                              </span>
                            </>
                          ) : (
                            <span className="table-secondary">
                              {isServer === false
                                ? containerHandoff?.outcome_reason ||
                                  (handoffs.loading
                                    ? "Checking governed review eligibility"
                                    : "No safe container action")
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

      <section className="card queue-card" aria-labelledby="risk-exceptions-heading">
        <div className="card-header">
          <div>
            <h2 id="risk-exceptions-heading">Risk exceptions</h2>
            <p>
              Active audited exceptions for the current authorized scope.
              Selection is limited to this loaded page.
            </p>
          </div>
        </div>
        {riskExceptions.loading ? (
          <StatePanel
            title="Loading risk exceptions"
            message="Reading active risk exceptions for this scope."
            tone="loading"
            busy
          />
        ) : riskExceptions.error ? (
          <StatePanel
            title="Risk exceptions are unavailable"
            message={riskExceptions.error.message}
            tone="error"
            action={
              <button
                type="button"
                className="button"
                onClick={riskExceptions.refetch}
              >
                Retry risk exceptions
              </button>
            }
          />
        ) : exceptionRows.length === 0 ? (
          <StatePanel
            title="No active risk exceptions"
            message="No active risk exceptions were returned for this authorized scope."
            tone="empty"
          />
        ) : (
          <>
            <div className="card-body">
              <button
                ref={revokeInvokerRef}
                type="button"
                className="button button-danger"
                disabled={selectedExceptions.size === 0}
                onClick={() => setRiskDialogOpen(true)}
              >
                Revoke {selectedExceptions.size} selected risk exceptions
              </button>
            </div>
            <div
              className="table-scroll exposure-responsive-table"
              role="region"
              aria-label="Risk exceptions table"
              tabIndex={0}
            >
              <table className="operations-table exposure-table">
                <caption>Active risk exceptions in the represented scope</caption>
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        aria-label={`Select all ${exceptionRows.length} risk exceptions on this page`}
                        checked={
                          exceptionRows.length > 0 &&
                          selectedExceptions.size === exceptionRows.length
                        }
                        onChange={(event) =>
                          setSelectedExceptions(
                            event.target.checked
                              ? new Set(
                                  exceptionRows.map(
                                    (exception) => exception.exception_id,
                                  ),
                                )
                              : new Set(),
                          )
                        }
                      />
                    </th>
                    <th>Audit record</th>
                    <th>CVE</th>
                    <th>Target scope</th>
                    <th>Reason</th>
                    <th>Expiry</th>
                  </tr>
                </thead>
                <tbody>
                  {exceptionRows.map((exception) => (
                    <tr key={exception.exception_id}>
                      <td data-label="Select">
                        <input
                          type="checkbox"
                          aria-label={`Select risk exception ${exception.exception_id} for ${exception.cve_id}`}
                          checked={selectedExceptions.has(exception.exception_id)}
                          onChange={(event) =>
                            setSelectedExceptions((current) => {
                              const next = new Set(current);
                              if (event.target.checked) {
                                next.add(exception.exception_id);
                              } else {
                                next.delete(exception.exception_id);
                              }
                              return next;
                            })
                          }
                        />
                      </td>
                      <td data-label="Audit record"><code>{exception.exception_id}</code></td>
                      <td data-label="CVE">
                        <Link
                          className="table-primary-link"
                          href={`/exposure/cves/${encodeURIComponent(exception.cve_id)}`}
                        >
                          {exception.cve_id}
                        </Link>
                      </td>
                      <td data-label="Target scope">
                        {exception.server_id || "Authorized CVE scope"}
                      </td>
                      <td data-label="Reason">{exception.reason}</td>
                      <td data-label="Expiry">{exception.expires_at || "No expiry"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <RiskExceptionDialog
        mode="revoke"
        open={riskDialogOpen}
        onOpenChange={setRiskDialogOpen}
        returnFocusRef={revokeInvokerRef}
        exceptions={selectedExceptionRows.map((exception: RiskException) => ({
          id: exception.exception_id,
          label: `${exception.exception_id} · ${exception.cve_id}`,
          targetScope: exception.server_id || "Authorized CVE scope",
        }))}
        representedScope={`${selectedExceptionRows.length} selected on this page`}
        onRevoke={revokeSelected}
        onSelectionChange={(remainingIds) =>
          setSelectedExceptions(new Set(remainingIds))
        }
        onRefresh={async () => {
          riskExceptions.refetch();
          section.retry();
        }}
      />
    </div>
  );
}
