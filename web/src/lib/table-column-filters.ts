"use client";

import { useEffect, useMemo, useState } from "react";
import type { TableColumnFilter } from "@/components/ui/TableColumnFilters";

type FilterValue = string | number | boolean | null | undefined;

export interface TableColumnFilterDefinition<T> {
  id: string;
  label: string;
  allLabel?: string;
  getValues: (row: T) => FilterValue | FilterValue[];
  formatOption?: (value: string) => string;
}

export interface TableColumnFilterState<T> {
  filteredRows: T[];
  filters: TableColumnFilter[];
  resetFilters: () => void;
}

function normalizeFilterValues(values: FilterValue | FilterValue[]): string[] {
  return (Array.isArray(values) ? values : [values])
    .map((value) => String(value ?? "").trim())
    .filter(Boolean);
}

/** Builds dropdown column filters and applies them before client-side pagination. */
export function useColumnFilters<T>(
  rows: readonly T[],
  definitions: readonly TableColumnFilterDefinition<T>[],
): TableColumnFilterState<T> {
  const [selected, setSelected] = useState<Record<string, string>>({});
  const definitionIds = useMemo(() => definitions.map((definition) => definition.id).join("\u0000"), [definitions]);

  useEffect(() => {
    setSelected((current) => {
      const activeIds = new Set(definitions.map((definition) => definition.id));
      const next = Object.fromEntries(Object.entries(current).filter(([id]) => activeIds.has(id)));
      return Object.keys(next).length === Object.keys(current).length ? current : next;
    });
  }, [definitionIds, definitions]);

  const filters = useMemo<TableColumnFilter[]>(
    () =>
      definitions.map((definition) => {
        const values = rows.flatMap((row) => normalizeFilterValues(definition.getValues(row)));
        const uniqueValues = Array.from(new Set(values)).sort((left, right) => left.localeCompare(right));
        return {
          id: definition.id,
          label: definition.label,
          allLabel: definition.allLabel,
          value: selected[definition.id] ?? "all",
          options: uniqueValues.map((value) => ({
            value,
            label: definition.formatOption?.(value) ?? value,
          })),
          onChange: (value: string) =>
            setSelected((current) => ({
              ...current,
              [definition.id]: value,
            })),
        };
      }),
    [definitions, rows, selected],
  );

  const filteredRows = useMemo(
    () =>
      rows.filter((row) =>
        definitions.every((definition) => {
          const value = selected[definition.id] ?? "all";
          if (value === "all") return true;
          return normalizeFilterValues(definition.getValues(row)).includes(value);
        }),
      ) as T[],
    [definitions, rows, selected],
  );

  const resetFilters = () => setSelected({});

  return { filteredRows, filters, resetFilters };
}
