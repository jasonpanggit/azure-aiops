"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { PatchInventory } from "@/components/exposure/PatchInventory";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { OperationsSignalChart } from "@/components/ui/OperationsSignalChart";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { buildCopilotSnapshot, copilotEvidenceRows, vulnerabilityApi } from "@/lib/services";

/** Service- and reachability-aware vulnerability prioritization workspace. */
export default function ExposurePage() {
  const { scope } = useScope();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [reachableOnly, setReachableOnly] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [exceptionsToken, setExceptionsToken] = useState(0);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [selectedExceptions, setSelectedExceptions] = useState<Set<string>>(new Set());
  const [bulkRevoking, setBulkRevoking] = useState(false);

  // Server-side search filtering operates over the full dataset rather than
  // just the fetched page, so debounce the free-text query before it drives
  // API calls to avoid firing a request on every keystroke.
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => clearTimeout(handle);
  }, [query]);

  const listFilters = useMemo(
    () => ({ q: debouncedQuery || undefined, reachableOnly }),
    [debouncedQuery, reachableOnly]
  );

  const summary = useApi(() => vulnerabilityApi.summary(scope), [scope]);
  const exposures = useApi(() => vulnerabilityApi.exposures(scope, listFilters), [scope, listFilters]);
  const patches = useApi(() => vulnerabilityApi.patchPriorities(scope, listFilters), [scope, listFilters]);
  const servers = useApi(() => vulnerabilityApi.serverExposures(scope, listFilters), [scope, listFilters]);
  const sla = useApi(() => vulnerabilityApi.slaCompliance(scope), [scope]);
  const riskExceptions = useApi(() => vulnerabilityApi.riskExceptions(), [scope, exceptionsToken]);

  const revokeException = useCallback(async (exceptionId: string) => {
    setRevokingId(exceptionId);
    setRevokeError(null);
    try {
      await vulnerabilityApi.revokeRiskException(exceptionId);
      setExceptionsToken((token) => token + 1);
      setSelectedExceptions((prev) => {
        const next = new Set(prev);
        next.delete(exceptionId);
        return next;
      });
    } catch (err) {
      setRevokeError(err instanceof Error ? err.message : "Failed to revoke risk exception.");
    } finally {
      setRevokingId(null);
    }
  }, []);

  const revokeExceptions = useCallback(async (exceptionIds: string[]) => {
    setBulkRevoking(true);
    setRevokeError(null);
    const failures: string[] = [];
    for (const id of exceptionIds) {
      try {
        await vulnerabilityApi.revokeRiskException(id);
      } catch {
        failures.push(id);
      }
    }
    setExceptionsToken((token) => token + 1);
    setSelectedExceptions(new Set());
    setBulkRevoking(false);
    if (failures.length > 0) {
      setRevokeError(`Failed to revoke ${failures.length} of ${exceptionIds.length} selected exceptions.`);
    }
  }, []);

  const expiringExceptionIds = useMemo(() => {
    const cutoff = Date.now() + 7 * 24 * 60 * 60 * 1000;
    const ids = new Set<string>();
    for (const exception of riskExceptions.data?.data ?? []) {
      if (!exception.expires_at) continue;
      const expiresAt = Date.parse(exception.expires_at);
      if (!Number.isNaN(expiresAt) && expiresAt <= cutoff) {
        ids.add(exception.exception_id);
      }
    }
    return ids;
  }, [riskExceptions.data]);

  const filteredPatches = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (patches.data?.data ?? []).filter((patch) => {
      if (!normalized) return true;
      return [patch.kb_id, patch.recommended_action, ...patch.cve_ids].some((value) =>
        String(value ?? "").toLowerCase().includes(normalized)
      );
    });
  }, [patches.data, query]);

  const filteredCves = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (exposures.data?.data ?? []).filter((exposure) => {
      if (!exposure.cve_id.toUpperCase().startsWith("CVE-")) return false;
      if (!normalized) return true;
      return [exposure.cve_id, exposure.missing_kb, exposure.recommended_patch, exposure.severity].some((value) =>
        String(value ?? "").toLowerCase().includes(normalized)
      );
    });
  }, [exposures.data, query]);

  const filteredServers = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (servers.data?.data ?? []).filter((server) => {
      if (!normalized) return true;
      return [
        server.name,
        server.server_id,
        server.inventory_kind,
        server.resource_type,
        server.business_service,
        server.application,
        server.environment,
        server.owner,
        server.region,
        server.network_exposure,
        ...server.cve_ids,
        ...server.missing_kbs,
      ].some((value) => String(value ?? "").toLowerCase().includes(normalized));
    });
  }, [servers.data, query]);

  const { filteredRows: columnFilteredServers, filters: serverFilters, resetFilters: resetServerFilters } = useColumnFilters(filteredServers, [
    { id: "inventory", label: "Inventory", getValues: (server) => server.inventory_kind },
    { id: "reachability", label: "Reachability", getValues: (server) => server.internet_exposed ? "Internet exposed" : server.reachable ? "Reachable" : "No path observed" },
    { id: "service", label: "Service", getValues: (server) => server.business_service || "Unassigned service" },
    { id: "environment", label: "Environment", getValues: (server) => server.environment || "Unknown" },
  ]);
  const { filteredRows: columnFilteredPatches, filters: patchFilters, resetFilters: resetPatchFilters } = useColumnFilters(filteredPatches, [
    { id: "reachability", label: "Reachability", getValues: (patch) => patch.reachable_server_count ? "Reachable" : "No path observed" },
    { id: "action", label: "Action", getValues: (patch) => patch.recommended_action || "Recommended patch" },
  ]);
  const { filteredRows: columnFilteredCves, filters: cveFilters, resetFilters: resetCveFilters } = useColumnFilters(filteredCves, [
    { id: "severity", label: "Severity", getValues: (exposure) => exposure.severity },
    { id: "reachability", label: "Reachability", getValues: (exposure) => exposure.internet_exposed ? "Internet exposed" : exposure.reachable_server_count ? "Reachable" : "No path observed" },
    { id: "kb", label: "Patch KB", getValues: (exposure) => exposure.missing_kb || "No KB" },
  ]);

  const serverPaging = useTablePagination(columnFilteredServers);
  const patchPaging = useTablePagination(columnFilteredPatches);
  const cvePaging = useTablePagination(columnFilteredCves);

  const bestPatch = patches.data?.data[0];
  const serverInventoryCounts = useMemo(() => {
    return (servers.data?.data ?? []).reduce<Record<string, number>>((counts, server) => {
      counts[server.inventory_kind] = (counts[server.inventory_kind] ?? 0) + 1;
      return counts;
    }, {});
  }, [servers.data]);
  const serverInventorySummary = Object.entries(serverInventoryCounts)
    .map(([kind, count]) => `${kind}: ${count}`)
    .join(" · ");
  // Named per-source so a single failing call (e.g. patches) doesn't block
  // rendering of sections whose own data loaded successfully.
  const sourceErrors = [
    { label: "Summary", error: summary.error },
    { label: "CVE exposures", error: exposures.error },
    { label: "Patch priorities", error: patches.error },
    { label: "Server exposures", error: servers.error },
  ].filter((entry): entry is { label: string; error: Error } => entry.error != null);
  const fatalError = summary.error ?? servers.error;
  const loading = summary.loading || exposures.loading || patches.loading || servers.loading;

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Exposure management"
        title="Which exposure should be reduced first?"
        description="Prioritize observed vulnerability exposure by reachability, affected services, exploit signals, and the patch evidence available in this scope."
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about exposure" />}
        metadata={
          <>
            <span>{summary.data?.data.affected_business_service_count ?? 0} affected business services</span>
            <span>{summary.data?.data.affected_server_count ?? 0} affected servers</span>
            <span>{serverInventorySummary || "Server inventory grouped by host"}</span>
            <span>Patch recommendations are advisory</span>
          </>
        }
      />

      <EvidenceBar
        evidence={[
          ...(summary.data?.evidence ?? []),
          ...(exposures.data?.evidence ?? []),
          ...(patches.data?.evidence ?? []),
          ...(servers.data?.evidence ?? []),
        ]}
        knowledgeVersion={summary.data?.knowledge_version}
        warnings={[
          ...(summary.data?.warnings ?? []),
          ...(exposures.data?.warnings ?? []),
          ...(patches.data?.warnings ?? []),
          ...(servers.data?.warnings ?? []),
        ]}
        fallbackTimestamp={summary.data?.data.freshness}
      />

      <div className="metric-grid exposure-metrics">
        <MetricCard
          label="Critical CVEs"
          value={summary.data?.data.critical_count ?? "—"}
          detail={`${summary.data?.data.cve_count ?? 0} CVEs observed in the current scope`}
          tone={(summary.data?.data.critical_count ?? 0) > 0 ? "critical" : "success"}
        />
        <MetricCard
          label="Internet exposed"
          value={summary.data?.data.internet_exposed_count ?? "—"}
          detail="Findings with an observed Internet-reachable path"
          tone={(summary.data?.data.internet_exposed_count ?? 0) > 0 ? "critical" : "success"}
        />
        <MetricCard
          label="Exposed inventory"
          value={servers.data?.pagination?.total ?? servers.data?.data.length ?? "—"}
          detail={serverInventorySummary || "Azure VM, Arc-enabled server, and AKS node exposure"}
          tone={(summary.data?.data.reachable_server_count ?? 0) > 0 ? "warning" : "success"}
        />
        <MetricCard
          label="Highest-value patch"
          value={bestPatch?.kb_id ?? "—"}
          detail={
            bestPatch
              ? `${Math.round(bestPatch.expected_risk_reduction)} expected risk reduction across ${bestPatch.affected_business_service_count} services`
              : "No patch priority available"
          }
          tone={bestPatch ? "success" : "default"}
        />
      </div>

      <section className="card dashboard-visual-card exposure-signal-card">
        <div className="card-header">
          <div>
            <h2>Exposure profile</h2>
            <p>Prioritization signals across the authorized environment.</p>
          </div>
          <span className="visual-card-kicker">Decision view</span>
        </div>
        <div className="card-body">
          <OperationsSignalChart
            signals={[
              { label: "Critical CVEs", value: summary.data?.data.critical_count ?? 0, tone: "critical" },
              { label: "Internet exposed", value: summary.data?.data.internet_exposed_count ?? 0, tone: "critical" },
              { label: "Reachable servers", value: summary.data?.data.reachable_server_count ?? 0, tone: "warning" },
              { label: "Affected services", value: summary.data?.data.affected_business_service_count ?? 0, tone: "info" },
            ]}
          />
        </div>
      </section>

      {bestPatch && (
        <section className="best-action-card">
          <div className="best-action-rank">01</div>
          <div>
            <span>Highest risk reduction per patch</span>
            <h2>{bestPatch.kb_id}</h2>
            <p>{bestPatch.recommended_action}</p>
          </div>
          <div className="best-action-facts">
            <div>
              <strong>{bestPatch.cve_ids.length}</strong>
              <span>CVEs removed</span>
            </div>
            <div>
              <strong>{bestPatch.reachable_server_count}</strong>
              <span>Reachable servers</span>
            </div>
            <div>
              <strong>{bestPatch.affected_business_service_count}</strong>
              <span>Business services</span>
            </div>
          </div>
          <Link className="button button-primary" href={`/exposure/kbs/${encodeURIComponent(bestPatch.kb_id)}`}>
            Open KB details
          </Link>
        </section>
      )}

      {sla.data?.data && (
        <section className="card">
          <div className="card-header">
            <div>
              <h2>SLA compliance &amp; aging</h2>
              <p>
                Snapshot-in-time view of currently open findings: how much is within its remediation SLA vs.
                overdue, and how long open findings have been outstanding.
              </p>
            </div>
          </div>
          <div className="card-body">
            <div className="metric-grid exposure-metrics">
              <MetricCard
                label="Overall compliance"
                value={
                  sla.data.data.overall_compliance_rate === null
                    ? "—"
                    : `${Math.round(sla.data.data.overall_compliance_rate * 100)}%`
                }
                detail={`${sla.data.data.compliant_count} of ${sla.data.data.tracked_count} tracked findings within SLA`}
                tone={(sla.data.data.overdue_count ?? 0) > 0 ? "warning" : "success"}
              />
              <MetricCard
                label="Overdue findings"
                value={sla.data.data.overdue_count}
                detail={`${sla.data.data.open_count} total open findings`}
                tone={(sla.data.data.overdue_count ?? 0) > 0 ? "critical" : "success"}
              />
            </div>
            <div className="table-scroll">
              <table className="operations-table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Open</th>
                    <th>Compliance</th>
                    <th>Overdue</th>
                    <th>Avg days open</th>
                    <th>Max days open</th>
                  </tr>
                </thead>
                <tbody>
                  {sla.data.data.by_severity.map((row) => (
                    <tr key={row.severity}>
                      <td><StatusBadge label={row.severity} tone={statusTone(row.severity)} compact /></td>
                      <td>{row.open_count}</td>
                      <td>
                        {row.compliance_rate === null ? "—" : `${Math.round(row.compliance_rate * 100)}%`}
                      </td>
                      <td>{row.overdue_count}</td>
                      <td>{row.avg_days_open}</td>
                      <td>{row.max_days_open}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ marginTop: "0.75rem" }}>
              <p className="table-secondary" style={{ marginBottom: "0.5rem" }}>Aging (days open)</p>
              <OperationsSignalChart
                signals={Object.entries(sla.data.data.aging_buckets).map(([bucket, count], index, all) => ({
                  label: bucket,
                  value: count,
                  // Later buckets represent longer-open findings; escalate tone toward the tail.
                  tone: index >= all.length - 1 ? "critical" : index >= all.length - 2 ? "warning" : "info",
                }))}
              />
            </div>
          </div>
        </section>
      )}

      {(riskExceptions.data?.data.length ?? 0) > 0 && (
        <section className="card">
          <div className="card-header">
            <div>
              <h2>Active risk exceptions</h2>
              <p>
                CVEs where risk has been formally accepted. These findings stay visible elsewhere on this page but
                are excluded from SLA compliance tracking while the exception is active.
                {expiringExceptionIds.size > 0 && (
                  <> <strong>{expiringExceptionIds.size}</strong> {expiringExceptionIds.size === 1 ? "exception expires" : "exceptions expire"} within 7 days.</>
                )}
              </p>
            </div>
            {selectedExceptions.size > 0 && (
              <button
                type="button"
                className="button button-quiet"
                disabled={bulkRevoking}
                onClick={() => void revokeExceptions(Array.from(selectedExceptions))}
              >
                {bulkRevoking ? "Revoking…" : `Revoke selected (${selectedExceptions.size})`}
              </button>
            )}
          </div>
          {revokeError && (
            <div className="card-body">
              <p className="muted" role="alert">{revokeError}</p>
            </div>
          )}
          <div className="table-scroll">
            <table className="operations-table">
              <thead>
                <tr>
                  <th aria-label="Select">
                    <input
                      type="checkbox"
                      aria-label="Select all risk exceptions"
                      checked={
                        (riskExceptions.data?.data.length ?? 0) > 0 &&
                        selectedExceptions.size === (riskExceptions.data?.data.length ?? 0)
                      }
                      onChange={(event) => {
                        if (event.target.checked) {
                          setSelectedExceptions(new Set((riskExceptions.data?.data ?? []).map((exception) => exception.exception_id)));
                        } else {
                          setSelectedExceptions(new Set());
                        }
                      }}
                    />
                  </th>
                  <th>CVE</th>
                  <th>Scope</th>
                  <th>Reason</th>
                  <th>Approved by</th>
                  <th>Expires</th>
                  <th aria-label="Revoke" />
                </tr>
              </thead>
              <tbody>
                {(riskExceptions.data?.data ?? []).map((exception) => {
                  const isExpiring = expiringExceptionIds.has(exception.exception_id);
                  return (
                    <tr key={exception.exception_id}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Select ${exception.cve_id}`}
                          checked={selectedExceptions.has(exception.exception_id)}
                          onChange={(event) => {
                            setSelectedExceptions((prev) => {
                              const next = new Set(prev);
                              if (event.target.checked) {
                                next.add(exception.exception_id);
                              } else {
                                next.delete(exception.exception_id);
                              }
                              return next;
                            });
                          }}
                        />
                      </td>
                      <td>
                        <Link className="table-primary-link" href={`/exposure/cves/${encodeURIComponent(exception.cve_id)}`}>
                          {exception.cve_id}
                        </Link>
                      </td>
                      <td>{exception.server_id || "All affected servers"}</td>
                      <td>{exception.reason}</td>
                      <td>{exception.approved_by || "Unrecorded"}</td>
                      <td>
                        {exception.expires_at || "No expiry"}
                        {isExpiring && <StatusBadge tone="warning" label="Expiring soon" />}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="button button-quiet"
                          disabled={revokingId === exception.exception_id}
                          onClick={() => void revokeException(exception.exception_id)}
                        >
                          {revokingId === exception.exception_id ? "Revoking…" : "Revoke"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="queue-toolbar">
        <label className="search-field">
          <span>Find exposure</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="CVE, KB, service scope, or severity"
          />
        </label>
        <label className="toggle-field">
          <input
            type="checkbox"
            checked={reachableOnly}
            onChange={(event) => setReachableOnly(event.target.checked)}
          />
          <span>Reachable only</span>
        </label>
      </div>

      {fatalError ? (
        <StatePanel
          title="Exposure intelligence is unavailable"
          message={`${fatalError.message}. The workbench will not treat missing vulnerability data as an all-clear state.`}
          tone="error"
        />
      ) : loading ? (
        <StatePanel
          title="Ranking vulnerability exposure"
          message="Combining KB patch state, CVE intelligence, network reachability, and business service criticality."
          tone="loading"
        />
      ) : (
        <>
        {sourceErrors.length > 0 && (
          <StatePanel
            title="Some exposure sources are degraded"
            message={`${sourceErrors.map((entry) => `${entry.label}: ${entry.error.message}`).join(" · ")}. Sections below reflect only the sources that loaded.`}
            tone="error"
          />
        )}
        {filteredServers.length === 0 && filteredPatches.length === 0 && filteredCves.length === 0 ? (
        <StatePanel
          title="No exposure matches these filters"
          message="Adjust the search or reachability filter. Results reflect the current operating context."
        />
      ) : (
        <div className="exposure-landing-sections">
          <section className="card queue-card">
            <div className="card-header">
              <div>
                <h2>Server-centric exposure inventory</h2>
                <p>Read-only inventory grouped by compute host across Azure VMs, Arc-enabled servers, and AKS nodes with observed exposure and patch evidence.</p>
              </div>
            </div>
            {filteredServers.length === 0 ? (
              <div className="card-body">
                <p className="muted">No server exposures match the current filters.</p>
              </div>
            ) : (
              <>
              <TableColumnFilters
                filters={serverFilters}
                onReset={resetServerFilters}
                resultCount={columnFilteredServers.length}
                totalCount={filteredServers.length}
              />
              <div className="table-scroll">
                <table className="operations-table exposure-table">
                  <thead>
                    <tr>
                      <th>Server</th>
                      <th>Inventory</th>
                      <th>Exposure</th>
                      <th>Scope</th>
                      <th>Open findings</th>
                      <th>Patch evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {serverPaging.pageRows.map((server) => (
                      <tr key={server.server_id}>
                        <td>
                          <strong>{server.name || server.server_id}</strong>
                          <div className="table-secondary">{server.server_id}</div>
                        </td>
                        <td>
                          <StatusBadge label={server.inventory_kind} tone="neutral" />
                          <div className="table-secondary">{server.resource_type || "Inventory type unavailable"}</div>
                        </td>
                        <td>
                          <StatusBadge
                            label={server.internet_exposed ? "Internet exposed" : server.reachable ? "Reachable" : "No path observed"}
                            tone={server.internet_exposed ? "critical" : server.reachable ? "warning" : "neutral"}
                          />
                          <div className="table-secondary">{server.network_exposure || "unknown"} exposure</div>
                        </td>
                        <td>
                          <strong>{server.business_service || "Unassigned service"}</strong>
                          <div className="table-secondary">
                            {[server.application, server.environment, server.region, server.owner].filter(Boolean).join(" · ") || "No scope metadata"}
                          </div>
                        </td>
                        <td>
                          <strong>{server.cve_count} CVEs</strong>
                          <div className="table-secondary">
                            {server.critical_count} critical · {server.overdue_count} overdue · max {server.max_days_open}d open
                          </div>
                        </td>
                        <td>
                          <strong>{server.missing_kbs.slice(0, 2).join(", ") || "No KB"}</strong>
                          <div className="table-secondary">{server.cve_ids.slice(0, 3).join(", ") || "No CVE id"}</div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </>
            )}
            <TablePagination
              total={serverPaging.total}
              pageRows={serverPaging.pageRows.length}
              page={serverPaging.page}
              onPageChange={serverPaging.setPage}
              pageSize={serverPaging.pageSize}
              onPageSizeChange={serverPaging.setPageSize}
              label="servers"
            />
          </section>

          <PatchInventory scope={scope} query={query} />

          <section className="card queue-card">
            <div className="card-header">
              <div>
                <h2>Patch priorities by KB</h2>
                <p>Operational patch queue. Open a KB to see the CVEs it resolves and the assets still missing it.</p>
              </div>
            </div>
            {filteredPatches.length === 0 ? (
              <div className="card-body">
                <p className="muted">No KB patch priorities match the current filters.</p>
              </div>
            ) : (
              <>
              <TableColumnFilters
                filters={patchFilters}
                onReset={resetPatchFilters}
                resultCount={columnFilteredPatches.length}
                totalCount={filteredPatches.length}
              />
              <div className="table-scroll">
                <table className="operations-table exposure-table">
                  <thead>
                    <tr>
                      <th>Priority</th>
                      <th>KB</th>
                      <th>CVEs resolved</th>
                      <th>Reachability</th>
                      <th>Business impact</th>
                      <th>Risk reduction</th>
                      <th aria-label="Open" />
                    </tr>
                  </thead>
                  <tbody>
                    {patchPaging.pageRows.map((patch, index) => (
                      <tr key={patch.kb_id}>
                        <td>
                          <span className="rank-number">{String(patchPaging.page * patchPaging.pageSize + index + 1).padStart(2, "0")}</span>
                        </td>
                        <td>
                          <Link className="table-primary-link" href={`/exposure/kbs/${encodeURIComponent(patch.kb_id)}`}>
                            {patch.kb_id}
                          </Link>
                          <div className="table-secondary">{patch.recommended_action}</div>
                        </td>
                        <td>
                          <strong>{patch.cve_ids.length}</strong>
                          <div className="table-secondary">{patch.cve_ids.slice(0, 3).join(", ") || "Advisory-only KB"}</div>
                        </td>
                        <td>
                          <StatusBadge
                            label={patch.reachable_server_count ? "Reachable" : "No path observed"}
                            tone={patch.reachable_server_count ? "warning" : "neutral"}
                          />
                          <div className="table-secondary">{patch.reachable_server_count} reachable servers</div>
                        </td>
                        <td>
                          <strong>{patch.affected_business_service_count} business services</strong>
                          <div className="table-secondary">
                            {patch.affected_application_count} apps · {patch.affected_server_count} servers
                          </div>
                        </td>
                        <td>
                          <strong>{Math.round(patch.expected_risk_reduction)}</strong>
                          <div className="risk-bar">
                            <span style={{ width: `${Math.min(100, Math.max(0, patch.expected_risk_reduction))}%` }} />
                          </div>
                        </td>
                        <td>
                          <Link
                            className="table-secondary"
                            href={`/remediation?kb=${encodeURIComponent(patch.kb_id)}`}
                            style={{ marginRight: "0.75rem" }}
                          >
                            Remediate
                          </Link>
                          <Link className="table-open-link" href={`/exposure/kbs/${encodeURIComponent(patch.kb_id)}`} aria-label={`Open ${patch.kb_id}`}>
                            →
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </>
            )}
            <TablePagination
              total={patchPaging.total}
              pageRows={patchPaging.pageRows.length}
              page={patchPaging.page}
              onPageChange={patchPaging.setPage}
              pageSize={patchPaging.pageSize}
              onPageSizeChange={patchPaging.setPageSize}
              label="KBs"
            />
          </section>

          <section className="card queue-card">
            <div className="card-header">
              <div>
                <h2>High-priority CVEs</h2>
                <p>Security analysis queue. This table only includes real CVE identifiers; advisory-only KBs stay in the patch table above.</p>
              </div>
            </div>
            {filteredCves.length === 0 ? (
              <div className="card-body">
                <p className="muted">No CVEs match the current filters.</p>
              </div>
            ) : (
              <>
              <TableColumnFilters
                filters={cveFilters}
                onReset={resetCveFilters}
                resultCount={columnFilteredCves.length}
                totalCount={filteredCves.length}
              />
              <div className="table-scroll">
                <table className="operations-table exposure-table">
                  <thead>
                    <tr>
                      <th>Priority</th>
                      <th>CVE</th>
                      <th>Reachability</th>
                      <th>Business impact</th>
                      <th>Risk reduction</th>
                      <th>Patch KB</th>
                      <th aria-label="Open" />
                    </tr>
                  </thead>
                  <tbody>
                    {cvePaging.pageRows.map((exposure, index) => (
                      <tr key={exposure.cve_id}>
                        <td>
                          <span className="rank-number">{String(cvePaging.page * cvePaging.pageSize + index + 1).padStart(2, "0")}</span>
                        </td>
                        <td>
                          <Link className="table-primary-link" href={`/exposure/cves/${encodeURIComponent(exposure.cve_id)}`}>
                            {exposure.cve_id}
                          </Link>
                          <div className="table-secondary">
                            <StatusBadge label={exposure.severity} tone={statusTone(exposure.severity)} compact />
                            <span>{exposure.exploit_signal || "No exploit signal"}</span>
                          </div>
                        </td>
                        <td>
                          <StatusBadge
                            label={exposure.internet_exposed ? "Internet exposed" : exposure.reachable_server_count ? "Reachable" : "No path observed"}
                            tone={exposure.internet_exposed ? "critical" : exposure.reachable_server_count ? "warning" : "neutral"}
                          />
                          <div className="table-secondary">{exposure.reachable_server_count} reachable servers</div>
                        </td>
                        <td>
                          <strong>{exposure.affected_business_service_count} business services</strong>
                          <div className="table-secondary">
                            {exposure.affected_application_count} apps · {exposure.affected_server_count} servers
                          </div>
                        </td>
                        <td>
                          <strong>{Math.round(exposure.expected_risk_reduction)}</strong>
                          <div className="risk-bar">
                            <span style={{ width: `${Math.min(100, Math.max(0, exposure.expected_risk_reduction))}%` }} />
                          </div>
                        </td>
                        <td>
                          <Link className="table-primary-link" href={`/exposure/kbs/${encodeURIComponent(exposure.missing_kb)}`}>
                            {exposure.missing_kb}
                          </Link>
                          <div className="table-secondary">{exposure.recommended_patch || "Recommended patch"}</div>
                        </td>
                        <td>
                          <Link
                            className="table-secondary"
                            href={`/remediation?cve=${encodeURIComponent(exposure.cve_id)}`}
                            style={{ marginRight: "0.75rem" }}
                          >
                            Remediate
                          </Link>
                          <Link className="table-open-link" href={`/exposure/cves/${encodeURIComponent(exposure.cve_id)}`} aria-label={`Open ${exposure.cve_id}`}>
                            →
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              </>
            )}
            <TablePagination
              total={cvePaging.total}
              pageRows={cvePaging.pageRows.length}
              page={cvePaging.page}
              onPageChange={cvePaging.setPage}
              pageSize={cvePaging.pageSize}
              onPageSizeChange={cvePaging.setPageSize}
              label="CVEs"
            />
          </section>
        </div>
        )}
        </>
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Vulnerability exposure"
        snapshot={buildCopilotSnapshot({
          pageKind: "vulnerability",
          pageId: "exposure",
          scope,
          filters: { query: query ? [query] : [], reachable: reachableOnly ? ["true"] : [] },
          evidence: copilotEvidenceRows("vulnerability", [
            ...(summary.data?.evidence ?? []),
            ...(exposures.data?.evidence ?? []),
            ...(patches.data?.evidence ?? []),
            ...(servers.data?.evidence ?? []),
          ], [...filteredCves, ...filteredPatches, ...filteredServers]),
        })}
        starterQuestions={[
          { label: "Which CVEs affect our highest-risk service?", tool: "cve_exposure", toolArguments: {} },
          { label: "What should be patched first?", tool: "cve_exposure", toolArguments: {} },
          { label: "Which servers have failed patches?", tool: "cve_exposure", toolArguments: {} },
        ]}
      />
    </div>
  );
}
