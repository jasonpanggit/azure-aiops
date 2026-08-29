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
import { buildScopeOptions, type ScopeOptions } from "@/lib/scope-options";
import { useScope } from "@/lib/scope-context";
import { connectionsApi } from "@/lib/services";

const EMPTY_OPTIONS = buildScopeOptions([]);
const DIMENSION = "subscription" as const;

/**
 * Global data-backed operating-context selector. The caller may select one
 * or more subscriptions; every other scope dimension has been retired from
 * this control. Values come from the caller's accessible subscription
 * connections rather than accepting unvalidated free text.
 */
export function ScopeSelector() {
  const { scope, setScope, clearScope } = useScope();
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ScopeOptions>(EMPTY_OPTIONS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const selectedValues = scope[DIMENSION] ?? [];
  const activeCount = selectedValues.length;
  const primaryContext = selectedValues[0] ?? "All subscriptions";
  const availableOptions = options[DIMENSION].filter(
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
    const existing = scope[DIMENSION] ?? [];
    if (existing.includes(value)) return;
    setScope({ ...scope, [DIMENSION]: [...existing, value] });
  }

  function removeValue(value: string) {
    const remaining = selectedValues.filter((current) => current !== value);
    const next: typeof scope = { ...scope };
    if (remaining.length === 0) {
      delete next.subscription;
    } else {
      next.subscription = remaining;
    }
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
          <span>Select one or more subscriptions from your accessible connections.</span>
        </div>

        <label className="scope-select-field">
          <span>Subscription</span>
          <select
            value=""
            disabled={loading || availableOptions.length === 0}
            onChange={(event) => addValue(event.target.value)}
          >
            <option value="">
              {loading
                ? "Loading values…"
                : availableOptions.length
                  ? "Select subscription"
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

        {selectedValues.length > 0 && (
          <div className="scope-selections">
            <div>
              <div>Subscription</div>
              <TagGroup onDismiss={(_, data) => removeValue(data.value)}>
                {selectedValues.map((value) => (
                  <Tag key={value} value={value} dismissible>
                    {value}
                  </Tag>
                ))}
              </TagGroup>
            </div>
          </div>
        )}

        {activeCount > 0 && (
          <Button appearance="secondary" onClick={clearScope} style={{ marginTop: 12 }}>
            Clear all
          </Button>
        )}
      </PopoverSurface>
    </Popover>
  );
}
