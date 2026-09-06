"use client";

import type { Pagination } from "@/lib/types";
import { PAGE_SIZE_OPTIONS } from "@/lib/use-table-pagination";

export const EXPOSURE_PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
export const DEFAULT_EXPOSURE_PAGE_SIZE = 50;

export type ExposurePageSize = (typeof EXPOSURE_PAGE_SIZE_OPTIONS)[number];

export interface CursorPageMetadata {
  /** Exact server total for the current governed query. */
  total: number;
  /** Exact number returned in this response, independent of rendered rows. */
  returnedCount: number;
  /** Exact one-based range bounds supplied by the server (0/0 when empty). */
  first: number;
  last: number;
  hasMore: boolean;
  /** Whether the parent-owned opaque cursor stack can move backward. */
  hasPrevious: boolean;
  /** Number of opaque history entries held by the parent query hook. */
  historyDepth: number;
  /** Authorized records represented by the current evidence, when available. */
  representedCount?: number;
}

interface LegacyTablePaginationProps {
  mode?: "offset";
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
  cursor?: never;
  busy?: never;
  onPreviousCursor?: never;
  onNextCursor?: never;
}

interface CursorTablePaginationProps {
  mode: "cursor";
  cursor: CursorPageMetadata;
  busy?: boolean;
  pageSize?: ExposurePageSize;
  onPageSizeChange: (size: ExposurePageSize) => void;
  onPreviousCursor: () => void;
  onNextCursor: () => void;
  /** Noun shown in the range summary, e.g. "exceptions". */
  label?: string;
  pagination?: never;
  pageRows?: never;
  page?: never;
  onPageChange?: never;
  total?: never;
}

export type TablePaginationProps = LegacyTablePaginationProps | CursorTablePaginationProps;

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

function cursorRangeCopy(cursor: CursorPageMetadata, label: string): string {
  const range = `Showing ${cursor.first.toLocaleString()}–${cursor.last.toLocaleString()} of ${cursor.total.toLocaleString()} ${label}`;
  const differsFromRepresented =
    cursor.representedCount !== undefined && cursor.returnedCount !== cursor.representedCount;
  const showLoaded = cursor.returnedCount !== cursor.total || differsFromRepresented;
  return showLoaded ? `${range} · ${cursor.returnedCount.toLocaleString()} loaded` : range;
}

function CursorTablePagination({
  cursor,
  busy = false,
  pageSize = DEFAULT_EXPOSURE_PAGE_SIZE,
  onPageSizeChange,
  onPreviousCursor,
  onNextCursor,
  label = "rows",
}: CursorTablePaginationProps) {
  const rangeCopy = cursorRangeCopy(cursor, label);
  const statusCopy = busy ? `Loading ${label}. Current result: ${rangeCopy}` : rangeCopy;

  return (
    <nav
      className="table-footer"
      aria-label={`Pagination for ${label}`}
      aria-busy={busy}
      data-cursor-history-depth={cursor.historyDepth}
    >
      <span className="table-footer-range" role="status" aria-live="polite" aria-atomic="true">
        {statusCopy}
      </span>

      <span className="table-footer-actions">
        <select
          className="table-footer-size"
          value={pageSize}
          disabled={busy}
          onChange={(event) => onPageSizeChange(Number(event.target.value) as ExposurePageSize)}
          aria-label={`Rows per page for ${label}`}
        >
          {EXPOSURE_PAGE_SIZE_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option} / page
            </option>
          ))}
        </select>

        <button
          type="button"
          className="button"
          disabled={busy || !cursor.hasPrevious}
          onClick={onPreviousCursor}
          aria-label="Previous page"
        >
          Previous
        </button>
        <button
          type="button"
          className="button"
          disabled={busy || !cursor.hasMore}
          onClick={onNextCursor}
          aria-label="Next page"
        >
          Next
        </button>
      </span>
    </nav>
  );
}

/**
 * Range summary, row-count selector, and page controls for a table.
 *
 * Without this the UI silently renders only the first slice of a result set, so
 * an operator has no way to tell a small estate apart from a truncated one.
 * Supports both server-paginated envelopes and rows paginated in the browser so
 * pagination reads and behaves identically across every page.
 */
export function TablePagination(props: TablePaginationProps) {
  if (props.mode === "cursor") {
    return <CursorTablePagination {...props} />;
  }

  const {
    pagination,
    pageRows,
    page,
    onPageChange,
    total: totalProp,
    pageSize,
    onPageSizeChange,
    label = "rows",
  } = props;
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
