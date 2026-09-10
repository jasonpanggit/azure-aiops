"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { SourceSectionState } from "@/components/exposure/SourceSectionState";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader, type PageHeaderCompleteness } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { TablePagination } from "@/components/ui/TablePagination";
import { useExposureSection } from "@/hooks/useExposureSection";
import {
  exposureDetailHref,
  encodeExposureQueryState,
  exposureQueryKey,
  exposureRetentionKey,
  parseExposureQueryState,
  restartExposureQuery,
  updateExposureQueryState,
  type ExposureQueryState,
} from "@/lib/exposure-query-state";
import { useScope } from "@/lib/scope-context";
import { vulnerabilityApi } from "@/lib/services";
import type { ExposureFinding, ExposurePage } from "@/lib/types";

interface DefenderExposureFinding extends ExposureFinding {
  weakness_kind?: string;
  severity?: string;
  source_family?: string;
  current_state?: string;
  sla_state?: string;
  priority_score?: number | null;
  recommendation?: string;
}

function completeness(page: ExposurePage<DefenderExposureFinding> | null): PageHeaderCompleteness | undefined {
  if (!page) return undefined;
  const value = page.contract.completeness;
  const state = value.state === "complete" || value.state === "partial" || value.state === "stale"
    ? value.state
    : "unavailable";
  return {
    state,
    freshness: page.freshness.state === "stale" ? "stale" : "unknown",
    representedConnections: value.represented_connections,
    expectedConnections: value.expected_connections,
    representedCount: value.represented ?? value.represented_count,
    totalCount: value.total ?? value.total_count,
    excludedCount: value.excluded ?? value.excluded_count,
    excludedReasons: value.excluded_reasons ?? [],
  };
}

function detailHref(item: DefenderExposureFinding, state: ExposureQueryState): string {
  const segment = item.weakness_kind === "kb" ? "kbs" : "cves";
  return exposureDetailHref(segment, item.weakness_id, {
    ...state,
    generation: state.generation || item.read_model_generation_id,
  }, {
    origin: "/exposure/defender-posture",
    row: item.exposure_id,
    scroll: 0,
  });
}

/** Defender-origin findings projected from the bounded Exposure SQL read model. */
export default function DefenderPosturePage() {
  const { scope } = useScope();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const cursorHistory = useRef<Array<string | null>>([]);
  const queryState = useMemo(() => {
    const parsed = parseExposureQueryState(new URLSearchParams(searchParams.toString()), {
      authorizedScope: scope,
    });
    return {
      ...parsed,
      filters: {
        ...parsed.filters,
        source_family: "defender_image",
        target_kind: "container_image",
      },
    };
  }, [scope, searchParams]);
  const commitQuery = useCallback(
    (next: ExposureQueryState) => {
      const params = encodeExposureQueryState(next).toString();
      router.replace(params ? `${pathname}?${params}` : pathname, { scroll: false });
    },
    [pathname, router],
  );
  const bindingKey = useMemo(
    () => JSON.stringify({
      scope: queryState.scope,
      filters: queryState.filters,
      sort: queryState.sort,
      pageSize: queryState.pageSize,
    }),
    [queryState.filters, queryState.pageSize, queryState.scope, queryState.sort],
  );
  const previousBinding = useRef("");
  useEffect(() => {
    const changed = previousBinding.current && previousBinding.current !== bindingKey;
    previousBinding.current = bindingKey;
    if (changed && queryState.cursor) {
      cursorHistory.current = [];
      commitQuery(restartExposureQuery(queryState));
    }
  }, [bindingKey, commitQuery, queryState]);

  const section = useExposureSection<ExposurePage<DefenderExposureFinding>>({
    queryKey: `${exposureQueryKey(queryState)}|defender-exposure`,
    retentionKey: `${exposureRetentionKey(queryState)}|defender-exposure`,
    load: ({ signal }) =>
      vulnerabilityApi.exposureItems(queryState, { signal }) as unknown as Promise<
        import("@/lib/types").ExposureEnvelope<ExposurePage<DefenderExposureFinding>>
      >,
    isEmpty: (page) => page.items.length === 0,
  });

  const page = section.data;
  const rows = page?.items ?? [];
  const criticalCount = rows.filter(
    (item) => item.severity?.toLocaleLowerCase("en-US") === "critical",
  ).length;
  const first = rows.length ? (queryState.page - 1) * queryState.pageSize + 1 : 0;
  const last = rows.length ? first + rows.length - 1 : 0;

  return (
    <div className="page-container exposure-defender-page">
      <PageHeader
        eyebrow="Exposure management"
        title="Defender image exposure"
        description="Review generation-pinned container image findings sourced from Defender without loading the full ontology or unrelated posture datasets."
        completeness={completeness(page)}
        metadata={
          <>
            <span>{page?.total_count.toLocaleString("en-US") ?? "Unknown"} Defender image findings</span>
            <span>{rows.length.toLocaleString("en-US")} loaded on this page</span>
            <span>Review only. Nothing executes from Exposure.</span>
          </>
        }
      />

      <EvidenceBar
        evidence={section.envelope?.evidence ?? []}
        knowledgeVersion={page?.generation}
        warnings={section.envelope?.warnings ?? []}
        fallbackTimestamp={section.metadata.observedAt}
        aggregateState={completeness(page)}
        sourceStatus={{ "Defender image findings": `${section.status} · ${rows.length} loaded` }}
      />

      {!section.loading && !page && (
        <StatePanel
          title="Defender image exposure is unavailable"
          message="No usable Defender image partition is available for the authorized scope."
          tone="error"
          action={
            section.restart.required ? (
              <button
                type="button"
                className="button"
                onClick={() => {
                  cursorHistory.current = [];
                  commitQuery(restartExposureQuery(queryState));
                }}
              >
                Restart results
              </button>
            ) : undefined
          }
        />
      )}

      <section className="card queue-card">
        <div className="card-header">
          <div>
            <h2>Defender image findings</h2>
            <p>Highest-priority current findings in the authorized SQL partition.</p>
          </div>
          <Link className="button" href="/exposure/patch-priorities">Open all priorities</Link>
        </div>
        <div className="card-body">
          <SourceSectionState sourceName="Defender image findings" itemLabel="findings" state={section}>
            <div className="metric-grid exposure-metrics">
              <MetricCard
                label="Total Defender image findings"
                value={page?.total_count}
                detail="Generation-pinned Defender image exposure facts"
                completeness={section.status === "current" ? "complete" : "partial"}
              />
              <MetricCard
                label="Critical findings loaded"
                value={criticalCount}
                detail={`Across ${rows.length.toLocaleString("en-US")} rows loaded on this page`}
                tone={criticalCount > 0 ? "critical" : "success"}
                completeness={section.status === "current" ? "complete" : "partial"}
              />
            </div>

            <div className="exposure-finding-list" aria-label="Defender image finding list">
              {rows.map((item) => (
                <article className="exposure-finding-row" key={item.exposure_id}>
                  <div>
                    <div className="exposure-finding-heading">
                      <Link href={detailHref(item, { ...queryState, generation: page?.generation ?? "" })}>
                        {item.weakness_id}
                      </Link>
                      <StatusBadge
                        label={item.severity ?? "Unknown severity"}
                        tone={statusTone(item.severity ?? "unknown")}
                        compact
                      />
                    </div>
                    <p>{item.recommendation || "Review the affected image and current evidence."}</p>
                  </div>
                  <div className="exposure-finding-score">
                    <strong>{item.priority_score ?? "Unknown"}</strong>
                    <span>priority</span>
                  </div>
                </article>
              ))}
            </div>
            <TablePagination
              mode="cursor"
              cursor={{
                total: page?.total_count ?? 0,
                returnedCount: rows.length,
                first,
                last,
                hasMore: Boolean(page?.next_cursor),
                hasPrevious: cursorHistory.current.length > 0,
                historyDepth: cursorHistory.current.length,
                representedCount: page?.contract.completeness.represented ?? page?.contract.completeness.represented_count,
              }}
              busy={section.loading || section.refreshing}
              pageSize={queryState.pageSize}
              onPageSizeChange={(pageSize) =>
                {
                  cursorHistory.current = [];
                  commitQuery(updateExposureQueryState(queryState, { pageSize }));
                }
              }
              onPreviousCursor={() => {
                const cursor = cursorHistory.current.pop() ?? null;
                commitQuery({
                  ...queryState,
                  cursor,
                  cursorHistory: [],
                  page: Math.max(1, queryState.page - 1),
                });
              }}
              onNextCursor={() => {
                if (page?.next_cursor) {
                  cursorHistory.current.push(queryState.cursor);
                  commitQuery({
                    ...queryState,
                    cursor: page.next_cursor,
                    cursorHistory: [],
                    page: queryState.page + 1,
                  });
                }
              }}
              label="Defender image findings"
            />
          </SourceSectionState>
        </div>
      </section>
    </div>
  );
}
