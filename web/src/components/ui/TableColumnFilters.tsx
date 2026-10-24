"use client";

export interface TableColumnFilterOption {
  value: string;
  label: string;
}

export interface TableColumnFilter {
  id: string;
  label: string;
  value: string;
  options: TableColumnFilterOption[];
  defaultValue?: string;
  allLabel?: string;
  onChange: (value: string) => void;
}

interface TableColumnFiltersProps {
  filters: TableColumnFilter[];
  onReset?: () => void;
  resultCount?: number;
  totalCount?: number;
}

/** Consistent labeled table filters with an optional explicit all-values label. */
export function TableColumnFilters({
  filters,
  onReset,
  resultCount,
  totalCount,
}: TableColumnFiltersProps) {
  const hasActiveFilters = filters.some(
    (filter) => filter.value !== (filter.defaultValue ?? "all"),
  );

  return (
    <div className="table-column-filters" aria-label="Table column filters">
      <div className="table-column-filter-controls">
        {filters.map((filter) => (
          <label key={filter.id}>
            {filter.label}
            <select
              value={filter.value}
              onChange={(event) => filter.onChange(event.target.value)}
              aria-label={`Filter by ${filter.label}`}
            >
              {filter.defaultValue === undefined && (
                <option value="all">{filter.allLabel ?? `Any ${filter.label.toLowerCase()}`}</option>
              )}
              {filter.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <div className="table-column-filter-summary">
        {resultCount !== undefined && totalCount !== undefined && (
          <span>
            {resultCount} of {totalCount} shown
          </span>
        )}
        {onReset && hasActiveFilters && (
          <button type="button" className="button button-quiet" onClick={onReset}>
            Clear filters
          </button>
        )}
      </div>
    </div>
  );
}
