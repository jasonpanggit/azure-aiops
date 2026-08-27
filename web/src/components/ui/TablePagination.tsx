"use client";

import type { Pagination } from "@/lib/types";

interface TablePaginationProps {
  pagination: Pagination | null | undefined;
  /** Rows rendered on the current page, used to compute the upper bound. */
  pageRows: number;
  page: number;
  onPageChange: (page: number) => void;
  /** Noun shown in the range summary, e.g. "resources". */
  label?: string;
}

/**
 * Range summary plus previous/next controls for a server-paginated table.
 *
 * Without this the UI silently renders only the first page of an envelope, so
 * an operator has no way to tell a small estate apart from a truncated one.
 * Mirrors the footer used by the situations queue so pagination behaves
 * consistently across the app.
 */
export function TablePagination({
  pagination,
  pageRows,
  page,
  onPageChange,
  label = "rows",
}: TablePaginationProps) {
  if (!pagination) return null;

  const { offset, total, next_offset: nextOffset } = pagination;
  const hasNext = nextOffset !== null && nextOffset !== undefined;

  // A single page that holds everything needs no controls, but suppressing the
  // footer entirely would hide the total. Keep the count, drop the buttons.
  const singlePage = page === 0 && !hasNext;

  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + pageRows, total);

  return (
    <div className="table-footer">
      Showing {first}–{last} of {total} {label}
      {!singlePage && (
        <span className="table-footer-actions">
          <button
            type="button"
            className="button"
            disabled={page === 0}
            onClick={() => onPageChange(Math.max(0, page - 1))}
          >
            Previous
          </button>
          <button
            type="button"
            className="button"
            disabled={!hasNext}
            onClick={() => onPageChange(page + 1)}
          >
            Next
          </button>
        </span>
      )}
    </div>
  );
}
