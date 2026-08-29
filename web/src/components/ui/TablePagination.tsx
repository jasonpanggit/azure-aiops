"use client";

import type { Pagination } from "@/lib/types";
import { PAGE_SIZE_OPTIONS } from "@/lib/use-table-pagination";

interface TablePaginationProps {
  /** Server envelope pagination. Omit for tables paginated in the browser. */
  pagination?: Pagination | null;
  /** Rows rendered on the current page, used to compute the upper bound. */
  pageRows: number;
  page: number;
  onPageChange: (page: number) => void;
  /** Total row count for client-paginated tables. */
  total?: number;
  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
  /** Noun shown in the range summary, e.g. "resources". */
  label?: string;
}

/** Page numbers around the current page, with gaps collapsed to an ellipsis. */
function pageWindow(page: number, pageCount: number): (number | "gap")[] {
  if (pageCount <= 7) return Array.from({ length: pageCount }, (_, index) => index);

  const items = new Set<number>([0, pageCount - 1, page]);
  if (page - 1 > 0) items.add(page - 1);
  if (page + 1 < pageCount - 1) items.add(page + 1);

  const ordered = Array.from(items).sort((a, b) => a - b);
  const result: (number | "gap")[] = [];
  ordered.forEach((value, index) => {
    if (index > 0 && value - ordered[index - 1] > 1) result.push("gap");
    result.push(value);
  });
  return result;
}

/**
 * Range summary, row-count selector, and page controls for a table.
 *
 * Without this the UI silently renders only the first slice of a result set, so
 * an operator has no way to tell a small estate apart from a truncated one.
 * Supports both server-paginated envelopes and rows paginated in the browser so
 * pagination reads and behaves identically across every page.
 */
export function TablePagination({
  pagination,
  pageRows,
  page,
  onPageChange,
  total: totalProp,
  pageSize,
  onPageSizeChange,
  label = "rows",
}: TablePaginationProps) {
  const serverMode = Boolean(pagination);

  if (!serverMode && totalProp === undefined) return null;

  const total = serverMode ? pagination!.total : totalProp ?? 0;
  const size = pageSize ?? pagination?.limit ?? 0;
  const offset = serverMode ? pagination!.offset : page * (size || 1);
  const hasNext = serverMode
    ? pagination!.next_offset !== null && pagination!.next_offset !== undefined
    : offset + pageRows < total;

  // Server envelopes only report the next offset, so a page count is known
  // solely in client mode; the numbered jump list is limited to that case.
  const pageCount = serverMode || !size ? 0 : Math.max(1, Math.ceil(total / size));

  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + pageRows, total);
  const singlePage = page === 0 && !hasNext;

  return (
    <div className="table-footer">
      <span className="table-footer-range">
        Showing {first}–{last} of {total} {label}
      </span>

      <span className="table-footer-actions">
        {onPageSizeChange && (
          <select
            className="table-footer-size"
            value={size}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
            aria-label={`Rows per page for ${label}`}
          >
            {PAGE_SIZE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option} / page
              </option>
            ))}
          </select>
        )}

        {!singlePage && (
          <>
            <button
              type="button"
              className="button"
              disabled={page === 0}
              onClick={() => onPageChange(Math.max(0, page - 1))}
              aria-label="Previous page"
            >
              Previous
            </button>

            {pageCount > 1 && (
              <span className="table-footer-pages">
                {pageWindow(page, pageCount).map((item, index) =>
                  item === "gap" ? (
                    <span key={`gap-${index}`} className="table-footer-gap">
                      …
                    </span>
                  ) : (
                    <button
                      key={item}
                      type="button"
                      className={`button table-footer-page${item === page ? " is-active" : ""}`}
                      aria-current={item === page ? "page" : undefined}
                      aria-label={`Page ${item + 1}`}
                      onClick={() => onPageChange(item)}
                    >
                      {item + 1}
                    </button>
                  ),
                )}
              </span>
            )}

            <button
              type="button"
              className="button"
              disabled={!hasNext}
              onClick={() => onPageChange(page + 1)}
              aria-label="Next page"
            >
              Next
            </button>
          </>
        )}
      </span>
    </div>
  );
}
