"use client";

import {
  Button,
  Popover,
  PopoverSurface,
  PopoverTrigger,
  Tag,
  TagGroup,
} from "@fluentui/react-components";
import { FilterRegular } from "@fluentui/react-icons";
import { useState } from "react";
import {
  SCOPE_DIMENSIONS,
  SCOPE_DIMENSION_LABELS,
  type ScopeDimension,
} from "@/lib/scope";
import { buildScopeOptions, type ScopeOptions } from "@/lib/scope-options";
import { useScope } from "@/lib/scope-context";
import { connectionsApi } from "@/lib/services";

const EMPTY_OPTIONS = buildScopeOptions([]);

/**
 * Global data-backed scope selector for every Operations API dimension.
 * Values come from the caller's accessible subscription connections rather
 * than accepting unvalidated free text.
 */
export function ScopeSelector() {
  const { scope, setScope, clearScope } = useScope();
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ScopeOptions>(EMPTY_OPTIONS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeDimension, setActiveDimension] = useState<ScopeDimension>("business_service");

  const activeCount = SCOPE_DIMENSIONS.reduce(
    (count, dimension) => count + (scope[dimension]?.length ?? 0),
    0
  );
  const primaryContext =
    scope.business_service?.[0] ??
    scope.application?.[0] ??
    scope.environment?.[0] ??
    scope.subscription_connection?.[0] ??
    scope.subscription?.[0] ??
    "All operations";
  const selectedValues = scope[activeDimension] ?? [];
  const availableOptions = options[activeDimension].filter(
    (option) => !selectedValues.includes(option.value)
  );

  async function loadOptions() {
    setLoading(true);
    setError("");
    try {
      const envelope = await connectionsApi.listAll();
      setOptions(buildScopeOptions(envelope.data));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Operating-context values could not be loaded."
      );
    } finally {
      setLoading(false);
    }
  }

  function addValue(value: string) {
    if (!value) return;
    const existing = scope[activeDimension] ?? [];
    if (existing.includes(value)) return;
    setScope({ ...scope, [activeDimension]: [...existing, value] });
  }

  function removeValue(dimension: ScopeDimension, value: string) {
    const remaining = (scope[dimension] ?? []).filter((current) => current !== value);
    const next = { ...scope, [dimension]: remaining };
    if (remaining.length === 0) delete next[dimension];
    setScope(next);
  }

  return (
    <Popover
      open={open}
      onOpenChange={(_, data) => {
        setOpen(data.open);
        if (data.open) void loadOptions();
      }}
    >
      <PopoverTrigger disableButtonEnhancement>
        <Button icon={<FilterRegular />} appearance="subtle">
          {primaryContext}
          {activeCount > 1 ? ` +${activeCount - 1}` : ""}
        </Button>
      </PopoverTrigger>
      <PopoverSurface style={{ width: 400 }} className="scope-popover">
        <div className="scope-popover-heading">
          <strong>Operating context</strong>
          <span>Select known values from your accessible subscription connections.</span>
        </div>

        <label className="scope-select-field">
          <span>Filter by</span>
          <select
            value={activeDimension}
            onChange={(event) => setActiveDimension(event.target.value as ScopeDimension)}
          >
            {SCOPE_DIMENSIONS.map((dimension) => (
              <option key={dimension} value={dimension}>
                {SCOPE_DIMENSION_LABELS[dimension]}
              </option>
            ))}
          </select>
        </label>

        <label className="scope-select-field">
          <span>{SCOPE_DIMENSION_LABELS[activeDimension]}</span>
          <select
            value=""
            disabled={loading || availableOptions.length === 0}
            onChange={(event) => addValue(event.target.value)}
          >
            <option value="">
              {loading
                ? "Loading values…"
                : availableOptions.length
                  ? `Select ${SCOPE_DIMENSION_LABELS[activeDimension].toLowerCase()}`
                  : "No additional values available"}
            </option>
            {availableOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {error && (
          <div className="scope-load-error" role="alert">
            <span>{error}</span>
            <Button size="small" appearance="secondary" onClick={() => void loadOptions()}>
              Retry
            </Button>
          </div>
        )}

        <div className="scope-selections">
          {SCOPE_DIMENSIONS.filter((dimension) => (scope[dimension]?.length ?? 0) > 0).map(
            (dimension) => (
              <div key={dimension}>
                <div>{SCOPE_DIMENSION_LABELS[dimension]}</div>
                <TagGroup onDismiss={(_, data) => removeValue(dimension, data.value)}>
                  {(scope[dimension] ?? []).map((value) => (
                    <Tag key={value} value={value} dismissible>
                      {value}
                    </Tag>
                  ))}
                </TagGroup>
              </div>
            )
          )}
        </div>

        {activeCount > 0 && (
          <Button appearance="secondary" onClick={clearScope} style={{ marginTop: 12 }}>
            Clear all
          </Button>
        )}
      </PopoverSurface>
    </Popover>
  );
}
