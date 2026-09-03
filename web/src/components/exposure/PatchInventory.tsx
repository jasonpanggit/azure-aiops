"use client";

import { Fragment, useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useApi } from "@/hooks/useApi";
import type { ScopeSelection } from "@/lib/scope";
import { patchingApi } from "@/lib/services";
import { useColumnFilters } from "@/lib/table-column-filters";
import type { PatchTarget } from "@/lib/types";
import { useTablePagination } from "@/lib/use-table-pagination";

interface PatchInventoryProps {
  scope: ScopeSelection;
  /** Free-text filter shared with the rest of the exposure workspace. */
  query?: string;
}

function stateTone(state: string): "critical" | "warning" | "success" | "neutral" {
  if (state === "failed" || state === "rejected") return "critical";
  if (state === "succeeded") return "success";
  if (state === "submitted" || state === "running") return "warning";
  return "neutral";
}

function remediationHref(target: PatchTarget, selected: string[]): string {
  const params = new URLSearchParams();
  params.set("resource_key", target.target_id);
  if (target.subscription_id) params.set("subscription", target.subscription_id);
  const patchIds = selected.length > 0
    ? selected
    : target.available_patches.map((patch) => patch.patch_id);
  for (const patchId of patchIds) params.append("kb", patchId);
  if (target.business_service) params.set("business_service", target.business_service);
  return `/remediation?${params.toString()}`;
}

/**
 * Read-only patch readiness inventory.
 *
 * Patch selection is context for a governed remediation handoff only. This
 * component deliberately has no mutation client: approval, immutable snapshot
 * capture, and execution all happen in the remediation workspace.
 */
export function PatchInventory({ scope, query = "" }: PatchInventoryProps) {
  const targets = useApi(() => patchingApi.targets(scope), [scope]);
  const runs = useApi(() => patchingApi.runs(scope), [scope]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [selection, setSelection] = useState<Record<string, string[]>>({});

  const filteredTargets = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const rows = targets.data?.data ?? [];
    if (!normalized) return rows;
    return rows.filter((target) =>
      [target.name, target.target_id, target.inventory_kind, target.business_service, target.environment].some(
        (value) => String(value ?? "").toLowerCase().includes(normalized)
      )
    );
  }, [query, targets.data]);

  const { filteredRows: visibleTargets, filters, resetFilters } = useColumnFilters(filteredTargets, [
    { id: "inventory", label: "Inventory", getValues: (target) => target.inventory_kind },
    { id: "service", label: "Service", getValues: (target) => target.business_service || "Unassigned service" },
    { id: "environment", label: "Environment", getValues: (target) => target.environment || "Unknown" },
    { id: "operation", label: "Operation", getValues: (target) => target.operation === "node_image_upgrade" ? "Node image upgrade" : "Install patches" },
  ]);
  const paging = useTablePagination(visibleTargets);

  const togglePatch = useCallback((target: PatchTarget, patchId: string) => {
    setSelection((current) => {
      const selected = current[target.target_id] ?? [];
      if (target.operation === "node_image_upgrade") {
        return { ...current, [target.target_id]: selected.includes(patchId) ? [] : [patchId] };
      }
      return {
        ...current,
        [target.target_id]: selected.includes(patchId)
          ? selected.filter((item) => item !== patchId)
          : [...selected, patchId],
      };
    });
  }, []);

  if (targets.loading) {
    return <StatePanel title="Loading patchable inventory" message="Reading patch readiness and governed handoff context." tone="loading" />;
  }
  if (targets.error) {
    return <StatePanel title="Patchable inventory unavailable" message={targets.error.message || "The request failed."} tone="error" />;
  }

  const recentRuns = runs.data?.data ?? [];
  return (
    <section className="card queue-card" data-testid="patch-inventory">
      <div className="card-header">
        <div>
          <h2>Patch and node image readiness</h2>
          <p>
            Inspect available updates here, then open governed remediation to review business impact,
            capture approval, and execute the server-owned patch snapshot.
          </p>
        </div>
      </div>

      {(targets.data?.warnings ?? []).map((warning) => (
        <div className="card-body" key={warning}>
          <p className="muted" role="status">{warning}</p>
        </div>
      ))}

      <div className="card-body">
        <p className="callout callout-warning">
          Direct patch submission is disabled. Inventory selections are handed to the governed remediation workspace as review context only.
        </p>
      </div>

      {filteredTargets.length === 0 ? (
        <div className="card-body"><p className="muted">No patchable servers match the current filters.</p></div>
      ) : (
        <>
          <TableColumnFilters
            filters={filters}
            onReset={resetFilters}
            resultCount={visibleTargets.length}
            totalCount={filteredTargets.length}
          />
          <div className="table-scroll">
            <table className="operations-table exposure-table">
              <thead>
                <tr>
                  <th>Server</th>
                  <th>Inventory</th>
                  <th>Scope</th>
                  <th>Open findings</th>
                  <th>Available updates</th>
                  <th>Governed action</th>
                </tr>
              </thead>
              <tbody>
                {paging.pageRows.map((target) => {
                  const selected = selection[target.target_id] ?? [];
                  const isOpen = expanded === target.target_id;
                  return (
                    <Fragment key={target.target_id}>
                      <tr>
                        <td>
                          <strong>{target.name || target.target_id}</strong>
                          <div className="table-secondary">{target.target_id}</div>
                        </td>
                        <td>
                          <StatusBadge label={target.inventory_kind} tone="neutral" />
                          <div className="table-secondary">
                            {target.operation === "node_image_upgrade" ? "Node image upgrade" : "Install patches"}
                          </div>
                        </td>
                        <td>
                          <strong>{target.business_service || "Unassigned service"}</strong>
                          <div className="table-secondary">
                            {[target.environment, target.region, target.owner].filter(Boolean).join(" · ") || "No scope metadata"}
                          </div>
                        </td>
                        <td>
                          <strong>{target.cve_count} CVEs</strong>
                          <div className="table-secondary">{target.critical_count} critical · {target.overdue_count} overdue</div>
                        </td>
                        <td>
                          <strong>{target.available_patches.length} available</strong>
                          <div className="table-secondary">{selected.length > 0 ? `${selected.length} selected` : "All shown for review"}</div>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="button button-quiet"
                            onClick={() => setExpanded(isOpen ? null : target.target_id)}
                            aria-expanded={isOpen}
                          >
                            {isOpen ? "Hide updates" : "Choose updates"}
                          </button>
                          <Link className="button button-primary" href={remediationHref(target, selected)}>
                            Open governed remediation
                          </Link>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="detail-row">
                          <td colSpan={6}>
                            {!target.patchable ? (
                              <p className="muted">{target.blocked_reason || "This target is not currently patchable."}</p>
                            ) : target.available_patches.length === 0 ? (
                              <p className="muted">No updates are currently known for this target.</p>
                            ) : (
                              <div className="patch-selection">
                                <ul className="patch-option-list">
                                  {target.available_patches.map((patch) => (
                                    <li key={patch.patch_id}>
                                      <label className="patch-option">
                                        <input
                                          type={target.operation === "node_image_upgrade" ? "radio" : "checkbox"}
                                          name={`patch-${target.target_id}`}
                                          checked={selected.includes(patch.patch_id)}
                                          onChange={() => togglePatch(target, patch.patch_id)}
                                        />
                                        <span><strong>{patch.patch_id}</strong>{patch.title ? ` — ${patch.title}` : ""}</span>
                                      </label>
                                      <div className="table-secondary">
                                        {[patch.classification, patch.severity, patch.reboot_required ? "reboot required" : "", patch.cve_ids.slice(0, 3).join(", "), `source: ${patch.source}`].filter(Boolean).join(" · ")}
                                      </div>
                                    </li>
                                  ))}
                                </ul>
                                <p className="muted">Selection narrows review context only; the server creates the authoritative executable snapshot.</p>
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <TablePagination
            total={paging.total}
            pageRows={paging.pageRows.length}
            page={paging.page}
            onPageChange={paging.setPage}
            pageSize={paging.pageSize}
            onPageSizeChange={paging.setPageSize}
            label="targets"
          />
        </>
      )}

      {recentRuns.length > 0 && (
        <div className="card-body">
          <h3>Historical patch runs</h3>
          <div className="table-scroll">
            <table className="operations-table">
              <thead><tr><th>Run</th><th>Target</th><th>Updates</th><th>State</th><th>Requested by</th></tr></thead>
              <tbody>
                {recentRuns.map((run) => (
                  <tr key={run.run_id}>
                    <td><code>{run.run_id}</code><div className="table-secondary">{run.created_at}</div></td>
                    <td><strong>{run.target_id}</strong><div className="table-secondary">{run.operation}</div></td>
                    <td>{run.patch_ids.join(", ") || "—"}</td>
                    <td><StatusBadge label={run.state} tone={stateTone(run.state)} /><div className="table-secondary">{run.message || run.provider || ""}</div></td>
                    <td>{run.requested_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
