"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { SourceSectionState } from "@/components/exposure/SourceSectionState";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { DonutChart } from "@/components/ui/DonutChart";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader, type PageHeaderCompleteness } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone, toneColor } from "@/components/ui/StatusBadge";
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
import { buildDefenderPostureCopilotContext } from "@/lib/copilot/page-adapters";
import type { ExposureFacets, ExposureFinding, ExposurePage } from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

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

function targetName(value: string): string {
  if (value.startsWith("sha256:") && value.length > 31) {
    return `${value.slice(0, 20)}…${value.slice(-8)}`;
  }
  const segments = value.split("/").filter(Boolean);
  return segments.at(-1) || value;
}

function displayFacet(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function facetCount(facets: ExposureFacets | null, name: string, value: string): number | null {
  if (!facets) return null;
  const folded = value.toLocaleLowerCase("en-US");
  const match = (facets.facets[name] ?? []).find(
    (item) => item.value.toLocaleLowerCase("en-US") === folded,
  );
  return match?.count ?? 0;
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
  const [copilotOpen, setCopilotOpen] = useState(false);
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

  const facets = useExposureSection<ExposureFacets>({
    queryKey: `${exposureQueryKey(queryState)}|defender-exposure=facets`,
    retentionKey: `${exposureRetentionKey(queryState)}|defender-exposure=facets`,
    load: ({ signal }) =>
      vulnerabilityApi.exposureFacets(queryState, ["severity"], { signal }),
    isEmpty: (data) => data.total_count === 0,
  });
  const facetData = facets.data;

  const page = section.data;
  const rows = useMemo(() => page?.items ?? [], [page?.items]);
  const criticalCount = facetCount(facetData, "severity", "critical")
    ?? rows.filter((item) => item.severity?.toLocaleLowerCase("en-US") === "critical").length;
  const severityBreakdown = useMemo(() => {
    const order = ["critical", "high", "medium", "low", "unknown"];
    if (facetData) {
      const items = facetData.facets.severity ?? [];
      const byValue = new Map(items.map((item) => [item.value.toLocaleLowerCase("en-US"), item]));
      const extra = items.filter((item) => !order.includes(item.value.toLocaleLowerCase("en-US")));
      const canonical = order.map((key) => byValue.get(key) ?? { value: key, count: 0 });
      return [...canonical, ...extra].map((item) => ({
        label: displayFacet(item.value),
        value: item.count,
        color: toneColor(statusTone(item.value)),
        filterValue: item.value.toLocaleLowerCase("en-US"),
      }));
    }
    const counts = new Map<string, number>();
    for (const item of rows) {
      const key = (item.severity || "unknown").toLowerCase();
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    const keys = [...order, ...Array.from(counts.keys()).filter((key) => !order.includes(key))];
    return keys.map((key) => ({
      label: key.charAt(0).toUpperCase() + key.slice(1),
      value: counts.get(key) ?? 0,
      color: toneColor(statusTone(key)),
      filterValue: key,
    }));
  }, [facetData, rows]);
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

  const first = rows.length ? (queryState.page - 1) * queryState.pageSize + 1 : 0;
  const last = rows.length ? first + rows.length - 1 : 0;
  const sourceStatus = section.status === "current" || section.status === "healthy-empty"
    ? "fresh"
    : section.status === "stale"
      ? "stale"
      : section.status === "partial"
        ? "partial"
        : "unavailable";
  const defenderCopilot = buildDefenderPostureCopilotContext({
    scope: queryState.scope,
    filters: {
      source_family: ["defender_image"],
      target_kind: ["container_image"],
      page: [String(queryState.page)],
    },
    records: rows.map((item, index) => ({
      identity: item.exposure_id || `${item.weakness_id}-${index}`,
      namespace: "vulnerability",
      kind: "defender_image_finding",
      source: "exposure/defender-image-findings",
      resourceId: item.target_id,
      observedAt: section.metadata.observedAt,
      priority: index,
      data: {
        target_id: item.target_id,
        target_kind: item.target_kind,
        subscription_id: item.subscription_id,
        read_model_generation_id: item.read_model_generation_id,
        weakness_id: item.weakness_id,
        weakness_kind: item.weakness_kind,
        severity: item.severity,
        current_state: item.current_state,
        priority_score: item.priority_score,
        recommendation: item.recommendation,
      },
    })),
    evidence: section.envelope?.evidence ?? [],
    coverage: [{
      key: "defender_image_findings",
      visibleCount: rows.length,
      totalCount: page?.total_count ?? rows.length,
      truncated: rows.length < (page?.total_count ?? rows.length),
      available: sourceStatus !== "unavailable",
    }],
    sourceStatuses: [{
      source: "defender_image",
      observedAt: section.metadata.observedAt,
      status: sourceStatus,
    }],
  });

  return (
    <div className="page-container exposure-defender-page">
      <PageHeader
        eyebrow="Exposure management"
        title="Defender image exposure"
        description="Review generation-pinned container image findings sourced from Defender without loading the full ontology or unrelated posture datasets."
        completeness={completeness(page)}
        actions={
          <CopilotDrawerButton
            onClick={() => setCopilotOpen(true)}
            label="Ask Copilot about Defender image exposure"
          />
        }
        metadata={
          <>
            <span>{page?.total_count.toLocaleString("en-US") ?? "Unknown"} Defender image findings</span>
            <span>{rows.length.toLocaleString("en-US")} loaded on this page</span>
            <span>Review only. Nothing executes from Exposure.</span>
          </>
        }
      />

      <CopilotInsights
        snapshot={defenderCopilot.snapshot}
        requestedScope={defenderCopilot.requestedScope}
        contextLabel="Defender posture"
        onOpenCopilot={() => setCopilotOpen(true)}
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
                label="Critical findings"
                value={criticalCount}
                detail={
                  facetData
                    ? `Across ${(page?.total_count ?? 0).toLocaleString("en-US")} total findings`
                    : `Across ${rows.length.toLocaleString("en-US")} rows loaded on this page`
                }
                tone={criticalCount > 0 ? "critical" : "success"}
                completeness={facets.status === "current" ? "complete" : "partial"}
              />
            </div>

            {rows.length > 0 && (
              <div className="dashboard-charts-row">
                <div className="chart-card">
                  <h3 className="chart-card-title">
                    {facetData ? "Severity mix (all findings)" : "Severity mix (loaded rows only)"}
                  </h3>
                  <DonutChart
                    segments={severityBreakdown}
                    centerValue={facetData ? (page?.total_count ?? rows.length) : rows.length}
                    centerLabel={facetData ? "total findings" : "on this page"}
                    onSegmentClick={toggleSeverityFilter}
                    activeFilterValue={queryState.filters.severity ?? null}
                  />
                </div>
              </div>
            )}

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
                    <div className="exposure-finding-target">
                      <strong className="exposure-long-value">{targetName(item.target_id)}</strong>
                      <StatusBadge label="Container image" tone="neutral" compact />
                      <span className="table-secondary exposure-long-value">{item.target_id}</span>
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
      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Defender image exposure"
        requestedScope={defenderCopilot.requestedScope}
        snapshot={defenderCopilot.snapshot}
        starterQuestions={defenderCopilot.starterQuestions}
      />
    </div>
  );
}
