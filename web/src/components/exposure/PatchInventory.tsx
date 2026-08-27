"use client";

import { Fragment, useCallback, useMemo, useState } from "react";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import type { ScopeSelection } from "@/lib/scope";
import { patchingApi } from "@/lib/services";
import type { PatchRun, PatchTarget } from "@/lib/types";

type RebootSetting = "IfRequired" | "Never" | "Always";

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

/**
 * Patchable inventory with explicit per-patch selection and a single guarded
 * trigger. The API re-validates every selected id against the target's own
 * availability list, so nothing chosen here can widen what a run may install.
 */
export function PatchInventory({ scope, query = "" }: PatchInventoryProps) {
  const [runsToken, setRunsToken] = useState(0);
  const targets = useApi(() => patchingApi.targets(scope), [scope, runsToken]);
  const runs = useApi(() => patchingApi.runs(scope), [scope, runsToken]);

  const [expanded, setExpanded] = useState<string | null>(null);
  const [selection, setSelection] = useState<Record<string, string[]>>({});
  const [reason, setReason] = useState("");
  const [rebootSetting, setRebootSetting] = useState<RebootSetting>("IfRequired");
  const [dryRun, setDryRun] = useState(true);
  // Keyed by target: an AKS cluster can host several pools, so the pool named
  // for one target must not leak onto another.
  const [nodePools, setNodePools] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<PatchRun | null>(null);

  const filteredTargets = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const rows = targets.data?.data ?? [];
    if (!normalized) return rows;
    return rows.filter((target) =>
      [target.name, target.target_id, target.inventory_kind, target.business_service, target.environment].some(
        (value) => String(value ?? "").toLowerCase().includes(normalized)
      )
    );
  }, [targets.data, query]);

  const selectedFor = useCallback((targetId: string) => selection[targetId] ?? [], [selection]);

  const togglePatch = useCallback((target: PatchTarget, patchId: string) => {
    setSubmitError(null);
    setSelection((prev) => {
      const current = prev[target.target_id] ?? [];
      const isSelected = current.includes(patchId);
      // AKS node image upgrades accept exactly one target version.
      if (target.operation === "node_image_upgrade") {
        return { ...prev, [target.target_id]: isSelected ? [] : [patchId] };
      }
      return {
        ...prev,
        [target.target_id]: isSelected ? current.filter((id) => id !== patchId) : [...current, patchId],
      };
    });
  }, []);

  const trigger = useCallback(
    async (target: PatchTarget) => {
      const patchIds = selection[target.target_id] ?? [];
      if (patchIds.length === 0) return;
      const nodePool = (nodePools[target.target_id] ?? "").trim();
      if (target.requires_node_pool && nodePool.length === 0) return;
      setSubmitting(true);
      setSubmitError(null);
      try {
        const response = await patchingApi.trigger({
          target_id: target.target_id,
          patch_ids: patchIds,
          reason: reason.trim(),
          reboot_setting: rebootSetting,
          ...(nodePool ? { node_pool: nodePool } : {}),
          dry_run: dryRun,
        });
        setLastRun(response.data);
        setSelection((prev) => ({ ...prev, [target.target_id]: [] }));
        setRunsToken((token) => token + 1);
      } catch (error) {
        setSubmitError(error instanceof Error ? error.message : String(error));
      } finally {
        setSubmitting(false);
      }
    },
    [dryRun, nodePools, reason, rebootSetting, selection]
  );

  if (targets.loading) {
    return (
      <StatePanel
        title="Loading patchable inventory"
        message="Reading server inventory and patch availability."
        tone="loading"
      />
    );
  }

  if (targets.error) {
    return (
      <StatePanel
        title="Patchable inventory unavailable"
        message={targets.error.message || "The request failed."}
        tone="error"
      />
    );
  }

  const warnings = targets.data?.warnings ?? [];
  const recentRuns = runs.data?.data ?? [];

  return (
    <section className="card queue-card" data-testid="patch-inventory">
      <div className="card-header">
        <div>
          <h2>Patch and node image remediation</h2>
          <p>
            Select the updates to install on an Azure VM or Arc-enabled server, or the node image version to roll
            out to an AKS node pool, then trigger the run. Every selection is re-validated by the API against what
            that target actually has available.
          </p>
        </div>
      </div>

      {warnings.length > 0 && (
        <div className="card-body">
          {warnings.map((warning) => (
            <p className="muted" key={warning} role="status">
              {warning}
            </p>
          ))}
        </div>
      )}

      <div className="card-body patch-run-controls">
        <label className="form-field">
          <span className="field-label">Reason (recorded on the run)</span>
          <input
            className="form-control"
            type="text"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="e.g. Emergency patch for CVE-2026-0001"
          />
        </label>
        <label className="form-field">
          <span className="field-label">Reboot</span>
          <select className="form-control" value={rebootSetting} onChange={(event) => setRebootSetting(event.target.value as RebootSetting)}>
            <option value="IfRequired">If required</option>
            <option value="Never">Never</option>
            <option value="Always">Always</option>
          </select>
        </label>
        <label className="toggle-field">
          <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
          <span>Dry run (validate without contacting Azure)</span>
        </label>
      </div>

      {submitError && (
        <div className="card-body">
          <p className="muted" role="alert">
            {submitError}
          </p>
        </div>
      )}

      {lastRun && (
        <div className="card-body">
          <p role="status">
            Run <code>{lastRun.run_id}</code> is <strong>{lastRun.state}</strong>
            {lastRun.message ? ` — ${lastRun.message}` : ""}
          </p>
        </div>
      )}

      {filteredTargets.length === 0 ? (
        <div className="card-body">
          <p className="muted">No patchable servers match the current filters.</p>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="operations-table exposure-table">
            <thead>
              <tr>
                <th>Server</th>
                <th>Inventory</th>
                <th>Scope</th>
                <th>Open findings</th>
                <th>Available updates</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredTargets.map((target) => {
                const selected = selectedFor(target.target_id);
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
                          {[target.environment, target.region, target.owner].filter(Boolean).join(" · ") ||
                            "No scope metadata"}
                        </div>
                      </td>
                      <td>
                        <strong>{target.cve_count} CVEs</strong>
                        <div className="table-secondary">
                          {target.critical_count} critical · {target.overdue_count} overdue
                        </div>
                      </td>
                      <td>
                        <strong>{target.available_patches.length} available</strong>
                        <div className="table-secondary">
                          {selected.length > 0 ? `${selected.length} selected` : "None selected"}
                        </div>
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
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="detail-row">
                        <td colSpan={6}>
                          {!target.patchable ? (
                            <p className="muted">
                              {target.blocked_reason || "This target cannot be patched from HOG."}
                            </p>
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
                                      <span>
                                        <strong>{patch.patch_id}</strong>
                                        {patch.title ? ` — ${patch.title}` : ""}
                                      </span>
                                    </label>
                                    <div className="table-secondary">
                                      {[
                                        patch.classification,
                                        patch.severity,
                                        patch.reboot_required ? "reboot required" : "",
                                        patch.cve_ids.slice(0, 3).join(", "),
                                        `source: ${patch.source}`,
                                      ]
                                        .filter(Boolean)
                                        .join(" · ")}
                                    </div>
                                  </li>
                                ))}
                              </ul>
                              {target.requires_node_pool && (
                                <label className="form-field">
                                  <span className="field-label">Agent pool</span>
                                  <input
                                    className="form-control"
                                    value={nodePools[target.target_id] ?? ""}
                                    placeholder="e.g. systempool"
                                    onChange={(event) =>
                                      setNodePools((prev) => ({
                                        ...prev,
                                        [target.target_id]: event.target.value,
                                      }))
                                    }
                                  />
                                </label>
                              )}
                              <button
                                type="button"
                                className="button button-primary"
                                disabled={
                                  submitting ||
                                  selected.length === 0 ||
                                  reason.trim().length === 0 ||
                                  (target.requires_node_pool &&
                                    (nodePools[target.target_id] ?? "").trim().length === 0)
                                }
                                onClick={() => void trigger(target)}
                              >
                                {submitting
                                  ? "Submitting…"
                                  : target.operation === "node_image_upgrade"
                                    ? "Trigger node image upgrade"
                                    : `Install ${selected.length} update${selected.length === 1 ? "" : "s"}`}
                              </button>
                              {reason.trim().length === 0 && (
                                <p className="muted">A reason is required before a run can be triggered.</p>
                              )}
                              {target.requires_node_pool &&
                                (nodePools[target.target_id] ?? "").trim().length === 0 && (
                                  <p className="muted">
                                    Name the agent pool to upgrade. HOG will not roll every pool in the
                                    cluster.
                                  </p>
                                )}
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
      )}

      {recentRuns.length > 0 && (
        <div className="card-body">
          <h3>Recent runs</h3>
          <div className="table-scroll">
            <table className="operations-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Target</th>
                  <th>Updates</th>
                  <th>State</th>
                  <th>Requested by</th>
                </tr>
              </thead>
              <tbody>
                {recentRuns.map((run) => (
                  <tr key={run.run_id}>
                    <td>
                      <code>{run.run_id}</code>
                      <div className="table-secondary">{run.created_at}</div>
                    </td>
                    <td>
                      <strong>{run.target_id}</strong>
                      <div className="table-secondary">{run.operation}</div>
                    </td>
                    <td>{run.patch_ids.join(", ") || "—"}</td>
                    <td>
                      <StatusBadge label={run.state} tone={stateTone(run.state)} />
                      <div className="table-secondary">{run.message || run.provider || ""}</div>
                    </td>
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
