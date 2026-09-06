"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { SourceSectionState } from "@/components/exposure/SourceSectionState";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useApi } from "@/hooks/useApi";
import { useExposureSection } from "@/hooks/useExposureSection";
import {
  DEFAULT_EXPOSURE_SORT,
  exposureQueryKey,
  exposureRetentionKey,
  updateExposureQueryState,
  type ExposureQueryState,
} from "@/lib/exposure-query-state";
import type { ScopeSelection } from "@/lib/scope";
import { patchingApi, vulnerabilityApi } from "@/lib/services";
import type {
  ExposureEnvelope,
  ExposureFinding,
  ExposurePage,
  PatchRun,
} from "@/lib/types";

interface PatchInventoryProps {
  scope: ScopeSelection;
  /** Free-text filter shared with the rest of the Exposure workspace. */
  query?: string;
}

interface PatchInventoryFinding extends ExposureFinding {
  weakness_kind?: string;
  source_family?: string;
  source_state?: string;
  current_state?: string;
  severity?: string;
  priority_score?: number | null;
  recommendation?: string;
  sla_state?: string;
  sla_age_seconds?: number | null;
  sla_due_at?: string | null;
  package_name?: string;
  package_version?: string;
  detail_path?: string;
  execution_eligible?: boolean;
  governed_action_id?: string;
  evidence_refs?: Array<{ source_id?: string; source_family?: string }>;
  review_handoff?: {
    outcome?: "review_handoff" | "no_safe_action";
    href?: string;
    reason?: string;
  };
}

const TARGET_KIND_OPTIONS = [
  { value: "server", label: "Servers" },
  { value: "container_image", label: "Container images" },
];

function dateCopy(value: string | null | undefined): string {
  if (!value) return "Due date unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Due date unknown";
  return `Due ${new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(date)}`;
}

function ageCopy(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "SLA age unknown";
  }
  const days = Math.floor(value / 86_400);
  if (days >= 1) return `SLA age ${days} ${days === 1 ? "day" : "days"}`;
  return `SLA age ${Math.floor(value / 3_600)} hours`;
}

function detailHref(row: PatchInventoryFinding): string {
  if (row.detail_path?.startsWith("/exposure/")) return row.detail_path;
  return `/exposure/${
    row.weakness_kind === "kb" ? "kbs" : "cves"
  }/${encodeURIComponent(row.weakness_id)}`;
}

function governedHref(row: PatchInventoryFinding): string {
  if (
    row.target_kind === "container_image" &&
    row.review_handoff?.outcome === "review_handoff" &&
    row.review_handoff.href?.startsWith("/remediation?")
  ) {
    return row.review_handoff.href;
  }
  const params = new URLSearchParams();
  params.set("resource_key", row.target_id);
  params.set("generation", row.read_model_generation_id);
  params.set("return_focus", row.exposure_id);
  if (row.subscription_id) params.append("subscription", row.subscription_id);
  if (row.weakness_kind === "kb") {
    params.append("kb", row.weakness_id);
  } else {
    params.append("cve", row.weakness_id);
  }
  return `/remediation?${params.toString()}`;
}

function runTone(state: string): "critical" | "warning" | "success" | "neutral" {
  if (state === "failed" || state === "rejected") return "critical";
  if (state === "succeeded") return "success";
  if (state === "submitted" || state === "running") return "warning";
  return "neutral";
}

function RunHistory({ runs }: { runs: PatchRun[] }) {
  if (runs.length === 0) {
    return (
      <StatePanel
        title="No historical patch runs"
        message="No governed patch runs are recorded for this authorized scope."
        tone="empty"
      />
    );
  }
  return (
    <div
      className="table-scroll exposure-responsive-table"
      role="region"
      aria-label="Historical patch runs table"
      tabIndex={0}
    >
      <table className="operations-table">
        <caption>Historical governed patch runs</caption>
        <thead>
          <tr>
            <th>Run</th>
            <th>Target</th>
            <th>Updates</th>
            <th>State</th>
            <th>Requested by</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id}>
              <td data-label="Run">
                <code>{run.run_id}</code>
                <div className="table-secondary">{run.created_at}</div>
              </td>
              <td data-label="Target">
                <strong>{run.target_id}</strong>
                <div className="table-secondary">{run.operation}</div>
              </td>
              <td data-label="Updates">{run.patch_ids.join(", ") || "—"}</td>
              <td data-label="State">
                <StatusBadge label={run.state} tone={runTone(run.state)} />
                <div className="table-secondary">{run.message || run.provider || ""}</div>
              </td>
              <td data-label="Requested by">{run.requested_by}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Read-only inventory over the canonical Exposure collection.
 *
 * Server findings may link to the existing governed server workflow. Container
 * findings remain review-only/no-safe-action and this component owns no
 * execution or infrastructure mutation client.
 */
export function PatchInventory({ scope, query = "" }: PatchInventoryProps) {
  const [targetKind, setTargetKind] = useState("all");
  const [page, setPage] = useState(1);
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<string[]>([]);
  const [pageSize, setPageSize] = useState<25 | 50 | 100>(50);
  const queryState = useMemo<ExposureQueryState>(
    () => ({
      scope,
      filters: {
        search: query.trim() || undefined,
        target_kind: targetKind === "all" ? undefined : targetKind,
      },
      sort: DEFAULT_EXPOSURE_SORT,
      pageSize,
      cursor,
      cursorHistory,
      page,
      target: "",
      drawer: "",
      generation: "",
    }),
    [cursor, cursorHistory, page, pageSize, query, scope, targetKind],
  );
  const findings = useExposureSection<ExposurePage<PatchInventoryFinding>>({
    queryKey: exposureQueryKey(queryState),
    retentionKey: exposureRetentionKey(queryState),
    load: ({ signal }) =>
      vulnerabilityApi.exposureItems(queryState, { signal }) as Promise<
        ExposureEnvelope<ExposurePage<PatchInventoryFinding>>
      >,
    isEmpty: (response) => response.items.length === 0,
  });
  const runs = useApi(() => patchingApi.runs(scope), [scope]);
  const rows = findings.data?.items ?? [];
  const total = findings.data?.total_count ?? 0;
  const first = rows.length ? (page - 1) * pageSize + 1 : 0;
  const last = rows.length ? first + rows.length - 1 : 0;
  const represented =
    findings.data?.contract.counts.represented ??
    findings.metadata.represented;

  const resetPaging = () => {
    setCursor(null);
    setCursorHistory([]);
    setPage(1);
  };

  return (
    <section className="card queue-card" data-testid="patch-inventory">
      <div className="card-header">
        <div>
          <h2>Patch and node image readiness</h2>
          <p>
            Common Exposure evidence supplies target kind, weakness, package,
            SLA, freshness, completeness, and governed next-action context.
          </p>
        </div>
      </div>

      <SourceSectionState
        sourceName="Patch inventory"
        itemLabel="findings"
        state={findings}
      >
        <TableColumnFilters
          filters={[
            {
              id: "target_kind",
              label: "Target kind",
              value: targetKind,
              options: TARGET_KIND_OPTIONS,
              onChange: (value) => {
                setTargetKind(value);
                resetPaging();
              },
            },
          ]}
          resultCount={rows.length}
          totalCount={total}
          onReset={() => {
            setTargetKind("all");
            resetPaging();
          }}
        />

        {rows.length > 0 && (
          <div
            className="table-scroll exposure-responsive-table"
            role="region"
            aria-label="Patch inventory table"
            tabIndex={0}
          >
            <p className="table-scroll-hint">Scroll horizontally to see all columns</p>
            <table className="operations-table exposure-table">
              <caption>Scoped patch, package, and container vulnerability inventory</caption>
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Finding</th>
                  <th>Target kind</th>
                  <th>Package evidence</th>
                  <th>SLA</th>
                  <th>Source state</th>
                  <th>Governed action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => {
                  const isContainer = row.target_kind === "container_image";
                  const canReviewContainer =
                    isContainer &&
                    row.review_handoff?.outcome === "review_handoff" &&
                    Boolean(row.review_handoff.href);
                  const canExecuteServer =
                    !isContainer &&
                    row.execution_eligible === true &&
                    Boolean(row.governed_action_id);
                  return (
                    <tr key={row.exposure_id} id={row.exposure_id} tabIndex={-1}>
                      <td data-label="Rank">Rank {first + index}</td>
                      <td data-label="Finding">
                        <Link className="table-primary-link" href={detailHref(row)}>
                          {row.weakness_id}
                        </Link>
                        <div className="table-secondary">
                          {row.recommendation || "Recommendation unavailable"}
                        </div>
                      </td>
                      <td data-label="Target kind">
                        <StatusBadge
                          label={isContainer ? "Container image" : "Server"}
                          tone="neutral"
                        />
                        <div className="table-secondary exposure-long-value">
                          {row.target_id}
                        </div>
                      </td>
                      <td data-label="Package evidence">
                        {row.package_name
                          ? `${row.package_name}${row.package_version ? ` ${row.package_version}` : ""}`
                          : "Package evidence unavailable"}
                      </td>
                      <td data-label="SLA">
                        <div>{ageCopy(row.sla_age_seconds)}</div>
                        <div className="table-secondary">{dateCopy(row.sla_due_at)}</div>
                      </td>
                      <td data-label="Source state">
                        <StatusBadge
                          label={row.completeness || "unknown"}
                          tone={row.completeness === "complete" ? "success" : "warning"}
                        />
                        <div className="table-secondary">
                          {(row.source_families ?? [row.source_family].filter(Boolean)).join(", ") ||
                            "Unknown source"}
                        </div>
                      </td>
                      <td data-label="Governed action">
                        {canExecuteServer ? (
                          <Link className="button button-primary" href={governedHref(row)}>
                            Open governed remediation
                          </Link>
                        ) : canReviewContainer ? (
                          <Link className="button button-primary" href={governedHref(row)}>
                            Open governed container review
                          </Link>
                        ) : (
                          <span className="table-secondary">
                            {row.review_handoff?.reason ||
                              (isContainer
                                ? "No safe container action"
                                : "No safe governed action")}
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

        {findings.data && (
          <TablePagination
            mode="cursor"
            cursor={{
              total,
              returnedCount: rows.length,
              first,
              last,
              hasMore: Boolean(findings.data.next_cursor),
              hasPrevious: page > 1,
              historyDepth: cursorHistory.length,
              representedCount: represented,
            }}
            busy={findings.refreshing}
            pageSize={pageSize}
            onPageSizeChange={(size) => {
              setPageSize(size);
              resetPaging();
            }}
            onPreviousCursor={() => {
              const history = [...cursorHistory];
              setCursor(history.pop() ?? null);
              setCursorHistory(history);
              setPage((value) => Math.max(1, value - 1));
            }}
            onNextCursor={() => {
              const next = findings.data?.next_cursor;
              if (!next) return;
              if (cursor) setCursorHistory((history) => [...history, cursor]);
              setCursor(next);
              setPage((value) => value + 1);
            }}
            label="findings"
          />
        )}
      </SourceSectionState>

      <section aria-labelledby="historical-patch-runs-heading">
        <div className="card-header">
          <h3 id="historical-patch-runs-heading">Historical patch runs</h3>
        </div>
        {runs.loading ? (
          <StatePanel
            title="Loading Historical patch runs"
            message="Loading Historical patch runs. Current Exposure findings remain available."
            tone="loading"
            busy
          />
        ) : runs.error ? (
          <StatePanel
            title="Historical patch runs is unavailable"
            message={`${runs.error.message || "No safe provider detail was returned."} Current Exposure findings remain available.`}
            tone="error"
            action={
              <button
                type="button"
                className="button"
                onClick={runs.refetch}
                aria-label="Retry Historical patch runs"
              >
                Retry Historical patch runs
              </button>
            }
          />
        ) : (
          <RunHistory runs={runs.data?.data ?? []} />
        )}
      </section>
    </section>
  );
}
