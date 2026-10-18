"use client";

import Link from "next/link";
import type { SituationSummary } from "@/lib/situations";
import { formatDateTime, relativeTime } from "@/lib/format";
import { StatusBadge, statusTone } from "./ui/StatusBadge";
import { TableColumnFilters } from "./ui/TableColumnFilters";
import { TablePagination } from "./ui/TablePagination";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import { overviewHref } from "@/lib/overview";
import type { ScopeSelection } from "@/lib/scope";

export interface SituationTableProps {
  situations: SituationSummary[];
  compact?: boolean;
  selectedIds?: ReadonlySet<string>;
  onSelect?: (id: string) => void;
  showFilters?: boolean;
  paginate?: boolean;
  scope?: ScopeSelection;
  showDeadlines?: boolean;
}

/** Ranked Situation queue optimized for fast operational scanning. */
export function SituationTable({ situations, compact = false, selectedIds, onSelect, showFilters = true, paginate = true, scope, showDeadlines = false }: SituationTableProps) {
  const { filteredRows, filters, resetFilters } = useColumnFilters(situations, [
    { id: "priority", label: "Priority", getValues: (situation) => situation.priority },
    { id: "status", label: "Status", getValues: (situation) => situation.status },
    {
      id: "service",
      label: "Service",
      getValues: (situation) => situation.businessServices.length ? situation.businessServices : "Service not mapped",
    },
    { id: "owner", label: "Owner", getValues: (situation) => situation.owner },
  ]);
  const situationPaging = useTablePagination(filteredRows);

  return (
    <>
      {showFilters && <TableColumnFilters
        filters={filters}
        onReset={resetFilters}
        resultCount={filteredRows.length}
        totalCount={situations.length}
      />}
      <div className="table-scroll">
      <table className="operations-table">
        <thead>
          <tr>
            {onSelect && <th>Select for handoff</th>}
            <th>Priority</th>
            <th>Situation</th>
            <th>Business impact</th>
            <th>Likely cause</th>
            <th>Owner</th>
            {showDeadlines && <th className="situation-deadline-cell">Declared response review</th>}
            {!compact && <th>Latest change</th>}
            <th aria-label="Open" />
          </tr>
        </thead>
        <tbody>
          {(paginate ? situationPaging.pageRows : filteredRows).map((situation) => (
            <tr key={situation.id}>
              {onSelect && <td><input type="checkbox"
                aria-label={`Select ${situation.title} for handoff`}
                checked={selectedIds?.has(situation.id) ?? false}
                onChange={() => onSelect(situation.id)}
              /></td>}
              <td>
                <StatusBadge
                  label={situation.priority}
                  tone={situation.priority === "P1" ? "critical" : situation.priority === "P2" ? "high" : "warning"}
                  compact
                />
              </td>
              <td>
                <Link className="table-primary-link" href={overviewHref(`/situations/${encodeURIComponent(situation.id)}`, scope ?? {})}>
                  {situation.title}
                </Link>
                <div className="table-secondary">
                  <StatusBadge label={situation.status} tone={statusTone(situation.status)} compact />
                  <span title={formatDateTime(situation.startedAt)}>Started {relativeTime(situation.startedAt)}</span>
                </div>
              </td>
              <td>
                <strong>{situation.businessServices[0] ?? "Service not mapped"}</strong>
                <div className="table-secondary">
                  {situation.applications.length} application{situation.applications.length === 1 ? "" : "s"}
                </div>
              </td>
              <td>
                <span className="table-wrap">{situation.cause}</span>
                <div className="table-secondary">{Math.round(situation.confidence * 100)}% confidence</div>
              </td>
              <td>
                <strong>{situation.owner}</strong>
                <div className="table-secondary">{situation.supportTeam}</div>
              </td>
              {showDeadlines && <td className="situation-deadline-cell"><StatusBadge label={situation.responseDeadline?.state ?? "unknown"} tone={situation.responseDeadline?.state === "overdue" ? "warning" : "neutral"} />
                <div className="table-secondary">{situation.responseDeadline?.declaration ? formatDateTime(situation.responseDeadline.declaration.due_at) : "No confirmed deadline"}</div>
                <div className="table-secondary">{situation.responseDeadline?.reason || "No sourced timing commitment"}</div>
                {situation.responseDeadline && <div className="table-secondary">Evaluated {formatDateTime(situation.responseDeadline.evaluated_at)}</div>}</td>}
              {!compact && (
                <td>
                  {situation.latestChange ? (
                    <>
                      <span className="table-wrap">{situation.latestChange.summary}</span>
                      <div className="table-secondary">{relativeTime(situation.latestChange.timestamp)}</div>
                    </>
                  ) : (
                    <span className="muted">No correlated change</span>
                  )}
                </td>
              )}
              <td>
                <Link
                  className="table-open-link"
                  href={overviewHref(`/situations/${encodeURIComponent(situation.id)}`, scope ?? {})}
                  aria-label={`Investigate ${situation.title}`}
                >
                  →
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {paginate && <TablePagination
        total={situationPaging.total}
        pageRows={situationPaging.pageRows.length}
        page={situationPaging.page}
        onPageChange={situationPaging.setPage}
        pageSize={situationPaging.pageSize}
        onPageSizeChange={situationPaging.setPageSize}
        label="situations"
      />}
    </>
  );
}
