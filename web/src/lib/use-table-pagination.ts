"use client";

import { useEffect, useMemo, useState } from "react";

/** Row counts offered by every paginated table so the choice is predictable. */
export const PAGE_SIZE_OPTIONS = [20, 50, 100] as const;

export const DEFAULT_PAGE_SIZE: number = PAGE_SIZE_OPTIONS[0];

export interface TablePaginationState<T> {
  /** Rows belonging to the current page. */
  pageRows: T[];
  page: number;
  setPage: (page: number) => void;
  pageSize: number;
  setPageSize: (size: number) => void;
  total: number;
  pageCount: number;
}

/**
 * Client-side pagination for tables whose rows are already in memory.
 *
 * Filtering shrinks `rows` underneath the current page, so the page index is
 * clamped rather than trusted; without that a filtered table can render an
 * empty page and read as "no results" when results exist.
 */
export function useTablePagination<T>(
  rows: readonly T[],
  initialPageSize: number = DEFAULT_PAGE_SIZE,
): TablePaginationState<T> {
  const [page, setPage] = useState(0);
  const [pageSize, setPageSizeState] = useState(initialPageSize);

  const total = rows.length;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(page, pageCount - 1);

  useEffect(() => {
    if (page > pageCount - 1) setPage(pageCount - 1);
  }, [page, pageCount]);

  const pageRows = useMemo(
    () => rows.slice(safePage * pageSize, safePage * pageSize + pageSize) as T[],
    [rows, safePage, pageSize],
  );

  // Changing the row count keeps the first visible row on screen instead of
  // jumping to an unrelated offset.
  const setPageSize = (size: number) => {
    const firstRow = safePage * pageSize;
    setPageSizeState(size);
    setPage(Math.floor(firstRow / size));
  };

  return {
    pageRows,
    page: safePage,
    setPage,
    pageSize,
    setPageSize,
    total,
    pageCount,
  };
}
