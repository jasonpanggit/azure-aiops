"use client";

import { useMemo, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { inventoryApi } from "@/lib/services";
import type {
  Envelope,
  InventorySourceStatus,
  InventoryNarrative,
  LifecycleReview,
  OsInventoryGroup,
  OsInventoryMachine,
  SoftwareInventoryGroup,
  SoftwareInventoryMachine,
  SoftwareMapping,
} from "@/lib/types";

type InventoryTab = "os" | "software";

function lifecycleLabel(group: OsInventoryGroup): string {
  return group.review_required ? "EOL date needs review" : group.lifecycle_status;
}

function sourceLabel(source: string): string {
  if (source === "azure_vm") return "Azure VM";
  if (source === "logs") return "Log Analytics";
  if (source === "unlinked") return "Unlinked";
  return "Arc";
}

function sourceTone(state: string): "success" | "warning" | "critical" | "unknown" {
  if (state === "ready") return "success";
  if (state === "partial" || state === "stale") return "warning";
  if (state === "unknown") return "unknown";
  return "critical";
}

function riskBucket(group: OsInventoryGroup): "expired" | "expiring" | "supported" | "review" {
  if (group.review_required || group.lifecycle_status.toLowerCase() === "unknown") return "review";
  if (["eol", "expired"].includes(group.lifecycle_status.toLowerCase())) return "expired";
  if (group.days_remaining !== null && group.days_remaining >= 0 && group.days_remaining <= 90) return "expiring";
  return "supported";
}

function lifecycleTone(group: OsInventoryGroup) {
  if (group.review_required) return "unknown" as const;
  if (riskBucket(group) === "expired") return "critical" as const;
  if (riskBucket(group) === "expiring") return "warning" as const;
  return "success" as const;
}

function NarrativePanel({ narrative }: { narrative: ReturnType<typeof useApi<Envelope<InventoryNarrative>>> }) {
  return (
    <section aria-label="Inventory risk narrative" className="detail-panel">
      <div className="card-header">
        <h2>Inventory risk narrative</h2>
        {narrative.data && (
          <StatusBadge
            label={`${narrative.data.data.confidence} confidence`}
            tone={narrative.data.data.confidence === "high" ? "success" : "warning"}
            compact
          />
        )}
      </div>
      {narrative.loading && (
        <StatePanel title="Loading risk narrative" message="Summarizing scoped inventory aggregates." tone="loading" />
      )}
      {narrative.error && (
        <StatePanel title="Risk narrative unavailable" message={narrative.error.message} tone="error" />
      )}
      {narrative.data && (
        <>
          <p><strong>Facts from inventory</strong></p>
          <p>{narrative.data.data.fact_summary}</p>
          {narrative.data.data.narrated_summary ? (
            <>
              <p><strong>Model narration{narrative.data.data.narrated_by ? ` · ${narrative.data.data.narrated_by}` : ""}</strong></p>
              <p>{narrative.data.data.narrated_summary}</p>
            </>
          ) : (
            <p className="muted">Model narration is unavailable; deterministic facts remain authoritative.</p>
          )}
          {narrative.data.data.citations.length > 0 && (
            <p className="muted">
              Evidence: {narrative.data.data.citations.map((citation) => `${citation.source_engine} / ${citation.source_table}`).join(" · ")}
            </p>
          )}
          {narrative.data.warnings?.map((warning) => (
            <p className="muted" key={warning}>{warning}</p>
          ))}
        </>
      )}
    </section>
  );
}

export default function SoftwareInventoryPage() {
  const { scope } = useScope();
  const [tab, setTab] = useState<InventoryTab>("os");
  const [subscriptionFilter, setSubscriptionFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<"all" | "azure_vm" | "arc">("all");
  const [lifecycleFilter, setLifecycleFilter] = useState<"all" | "expired" | "expiring" | "supported" | "review">("all");
  const [softwareSearch, setSoftwareSearch] = useState("");
  const [softwareSourceFilter, setSoftwareSourceFilter] = useState<"all" | "azure_vm" | "arc" | "unlinked">("all");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<OsInventoryMachine[]>([]);
  const [detailGroup, setDetailGroup] = useState<OsInventoryGroup | null>(null);
  const [softwareDetail, setSoftwareDetail] = useState<SoftwareInventoryMachine[]>([]);
  const [softwareDetailGroup, setSoftwareDetailGroup] = useState<SoftwareInventoryGroup | null>(null);
  const [softwareDetailEnvelope, setSoftwareDetailEnvelope] = useState<Envelope<import("@/lib/types").SoftwareInventoryDetail> | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [review, setReview] = useState<LifecycleReview | null>(null);
  const [reviewGroup, setReviewGroup] = useState<OsInventoryGroup | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [manualDate, setManualDate] = useState("");
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [mappingError, setMappingError] = useState<string | null>(null);
  const [mappingSubmitting, setMappingSubmitting] = useState<string | null>(null);
  const effectiveScope = useMemo(
    () => subscriptionFilter === "all"
      ? scope
      : { ...scope, subscription: [subscriptionFilter] },
    [scope, subscriptionFilter],
  );
  const scopeKey = useMemo(() => JSON.stringify(effectiveScope), [effectiveScope]);
  const inventory = useApi(() => inventoryApi.os(effectiveScope), [scopeKey, refreshKey]);
  const softwareInventory = useApi(() => inventoryApi.software(effectiveScope), [scopeKey, refreshKey]);
  const narrative = useApi(() => inventoryApi.narrative(effectiveScope), [scopeKey, refreshKey]);
  const mappings = useApi(
    () => inventoryApi.mappings(effectiveScope),
    [scopeKey, refreshKey],
  );

  const groups = inventory.data?.data.groups ?? [];
  const filteredGroups = useMemo(
    () => groups.filter((group) => {
      const haystack = `${group.os_name} ${group.os_version}`.toLowerCase();
      return (
        haystack.includes(search.toLowerCase()) &&
        (sourceFilter === "all" || group.source_types.includes(sourceFilter)) &&
        (lifecycleFilter === "all" || riskBucket(group) === lifecycleFilter)
      );
    }),
    [groups, lifecycleFilter, search, sourceFilter],
  );
  const totalMachines = filteredGroups.reduce((total, group) => total + group.machine_count, 0);
  const reviewCount = filteredGroups.filter((group) => group.review_required).length;
  const sourceStates: Record<string, InventorySourceStatus> = inventory.data?.data.source_status ?? {};
  const partialSource = Object.values(sourceStates).find((source) => source.state !== "ready");
  const softwareGroups = softwareInventory.data?.data.groups ?? [];
  const filteredSoftwareGroups = useMemo(
    () => softwareGroups.filter((group) => {
      const haystack = `${group.software_name} ${group.software_version}`.toLowerCase();
      return (
        haystack.includes(softwareSearch.toLowerCase()) &&
        (softwareSourceFilter === "all" || group.source_types.includes(softwareSourceFilter))
      );
    }),
    [softwareGroups, softwareSearch, softwareSourceFilter],
  );
  const softwareTotal = filteredSoftwareGroups.reduce((total, group) => total + group.install_count, 0);
  const unlinkedSoftware = filteredSoftwareGroups.reduce((total, group) => total + group.unlinked_count, 0);
  const softwareSourceStates: Record<string, InventorySourceStatus> =
    softwareInventory.data?.data.source_status ?? {};
  const softwarePartialSource = Object.values(softwareSourceStates).find((source) => source.state !== "ready");
  const mappingItems: SoftwareMapping[] = mappings.data?.data.mappings ?? [];

  async function openGroup(group: OsInventoryGroup) {
    setSelectedKey(group.key);
    setDetailError(null);
    try {
      const response = await inventoryApi.osGroup(group.key, effectiveScope);
      setDetail(response.data.machines);
      setDetailGroup(response.data.group);
    } catch (error) {
      setDetail([]);
      setDetailGroup(null);
      setDetailError(error instanceof Error ? error.message : "Machine detail is unavailable.");
    }
  }

  async function openSoftwareGroup(group: SoftwareInventoryGroup) {
    setSelectedKey(group.key);
    setDetailError(null);
    try {
      const response = await inventoryApi.softwareGroup(group.key, effectiveScope);
      setSoftwareDetail(response.data.machines);
      setSoftwareDetailGroup(response.data.group);
      setSoftwareDetailEnvelope(response);
    } catch (error) {
      setSoftwareDetail([]);
      setSoftwareDetailGroup(null);
      setDetailError(error instanceof Error ? error.message : "Software detail is unavailable.");
    }
  }

  async function openLifecycleReview(group: OsInventoryGroup) {
    setReviewGroup(group);
    setReview(null);
    setReviewError(null);
    setManualDate("");
    try {
      const response = await inventoryApi.lifecycleReview(group.key, effectiveScope);
      setReview(response.data);
    } catch (error) {
      setReviewError(error instanceof Error ? error.message : "Lifecycle review is unavailable.");
    }
  }

  async function confirmLifecycle(candidateId?: string) {
    if (!review) return;
    setReviewSubmitting(true);
    setReviewError(null);
    try {
      const response = await inventoryApi.confirmLifecycle(
        reviewGroup?.key ?? review.normalized_os_key,
        {
          normalized_os_key: review.normalized_os_key,
          expected_revision: review.catalog_revision,
          ...(candidateId ? { candidate_id: candidateId } : { manual_date: manualDate }),
        },
        effectiveScope,
      );
      setReview(response.data);
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setReviewError(error instanceof Error ? error.message : "Lifecycle confirmation failed.");
    } finally {
      setReviewSubmitting(false);
    }

  }

  async function decideMapping(mapping: SoftwareMapping, decision: "approve" | "reject") {
    setMappingSubmitting(mapping.mapping_id);
    setMappingError(null);
    try {
      const response = decision === "approve"
        ? await inventoryApi.approveMapping(mapping.mapping_id, mapping.revision, effectiveScope)
        : await inventoryApi.rejectMapping(mapping.mapping_id, mapping.revision, effectiveScope);
      void response;
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setMappingError(error instanceof Error ? error.message : "Mapping decision failed.");
    } finally {
      setMappingSubmitting(null);
    }
  }

  return (
    <main className="page-shell">
      <PageHeader
        eyebrow="Inventory"
        title="Software Inventory"
        description="Find authorized operating-system and installed-software coverage across native Azure VMs and Arc-enabled servers."
        metadata={
          inventory.data && (
            <EvidenceBar
              evidence={inventory.data.evidence}
              sourceStatus={Object.fromEntries(
                Object.entries(inventory.data.data.source_status).map(([source, status]) => [source, status.state]),
              )}
              warnings={inventory.data.warnings}
            />
          )
        }
      />

      <div role="tablist" aria-label="Inventory views" className="tab-list">
        <button
          id="os-inventory-tab"
          type="button"
          role="tab"
          aria-selected={tab === "os"}
          aria-controls="os-inventory-panel"
          tabIndex={tab === "os" ? 0 : -1}
          onClick={() => setTab("os")}
        >
          OS Inventory
        </button>
        <button
          id="installed-software-tab"
          type="button"
          role="tab"
          aria-selected={tab === "software"}
          aria-controls="installed-software-panel"
          tabIndex={tab === "software" ? 0 : -1}
          onClick={() => setTab("software")}
        >
          Installed Software
        </button>
      </div>

      <NarrativePanel narrative={narrative} />

      {tab === "software" ? (
        <section id="installed-software-panel" role="tabpanel" aria-labelledby="installed-software-tab" tabIndex={0}>
          <section aria-label="Installed software summary" className="metric-grid">
            <MetricCard label="Software groups" value={filteredSoftwareGroups.length} detail="Canonical name and version" />
            <MetricCard label="Installations" value={softwareTotal} detail="Authorized current rows" />
            <MetricCard label="Unlinked rows" value={unlinkedSoftware} detail="Exact resource join required" />
          </section>
          <section aria-label="Installed software dashboard" className="inventory-dashboard">
            <div className="card-header"><h2>Top software by install count</h2><span className="muted">{filteredSoftwareGroups.length} shown</span></div>
            {filteredSoftwareGroups.slice(0, 5).map((group) => (
              <div className="inventory-bar-row" key={group.key}>
                <span>{group.software_name} {group.software_version}</span>
                <div className="inventory-bar" style={{ width: `${softwareTotal ? Math.max(4, (group.install_count / softwareTotal) * 100) : 0}%` }} aria-hidden="true" />
                <strong>{group.install_count}</strong>
              </div>
            ))}
          </section>
          <div className="inventory-filters" aria-label="Installed software filters">
            <label>
              Search software
              <input value={softwareSearch} onChange={(event) => setSoftwareSearch(event.target.value)} placeholder="Name or version" />
            </label>
            <label>
              Source
              <select value={softwareSourceFilter} onChange={(event) => setSoftwareSourceFilter(event.target.value as typeof softwareSourceFilter)}>
                <option value="all">All sources</option>
                <option value="azure_vm">Azure VM</option>
                <option value="arc">Arc</option>
                <option value="unlinked">Unlinked</option>
              </select>
            </label>
            <label>
              Subscription
              <select value={subscriptionFilter} onChange={(event) => setSubscriptionFilter(event.target.value)}>
                <option value="all">All authorized subscriptions</option>
                {(scope.subscription ?? []).map((subscription) => (
                  <option key={subscription} value={subscription}>{subscription}</option>
                ))}
              </select>
            </label>
            <div className="inventory-source-badges" aria-label="Installed software source status">
              {Object.values(softwareSourceStates).map((source) => (
                <StatusBadge key={source.source_type} label={`${sourceLabel(source.source_type)} · ${source.state}`} tone={sourceTone(source.state)} compact />
              ))}
            </div>
          </div>
          {softwareInventory.loading && (
            <StatePanel title="Loading installed software" message="Reading ConfigurationData observations." tone="loading" />
          )}
          {softwareInventory.error && (
            <StatePanel title="Installed software unavailable" message={softwareInventory.error.message} tone="error" />
          )}
          {!softwareInventory.loading && !softwareInventory.error && softwareGroups.length === 0 && (
            <StatePanel title="No installed software observations" message="The authorized scope has no successful ConfigurationData rows." />
          )}
          {!softwareInventory.loading && !softwareInventory.error && softwareGroups.length > 0 && filteredSoftwareGroups.length === 0 && (
            <StatePanel title="No matching installed software" message="Adjust the search, source, or subscription filters." />
          )}
          {softwarePartialSource && (
            <StatePanel
              title="Installed software source is unavailable"
              message={`Log Analytics source is ${softwarePartialSource.state}; rows are not presented as a successful empty result.`}
              tone="error"
            />
          )}
          {filteredSoftwareGroups.length > 0 && (
            <section aria-label="Installed software groups" className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Software</th>
                    <th>Installations</th>
                    <th>Sources</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSoftwareGroups.map((group) => (
                    <tr key={group.key}>
                      <td>
                        <strong>{group.software_name}</strong>
                        <span className="table-subtitle">{group.software_version}</span>
                      </td>
                      <td>{group.install_count}</td>
                      <td>{group.source_types.map((source) => source === "azure_vm" ? "Azure VM" : source === "arc" ? "Arc" : "Unlinked").join(", ")}</td>
                      <td>
                        <button type="button" onClick={() => openSoftwareGroup(group)} aria-label={`View machines for ${group.software_name} ${group.software_version}`}>
                          View machines
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
          {mappingError && <StatePanel title="Mapping decision unavailable" message={mappingError} tone="error" />}
          {mappingItems.length > 0 && (
            <section aria-label="Software normalization review" className="detail-panel">
              <h2>Normalization review</h2>
              <p>Only approved mappings change software group counts.</p>
              <ul>
                {mappingItems.map((mapping) => (
                  <li key={mapping.mapping_id}>
                    <strong>{mapping.raw_name} {mapping.raw_version}</strong>
                    {mapping.publisher && <span className="table-subtitle">Publisher: {mapping.publisher}</span>}
                    <span className="table-subtitle">
                      Suggests: {mapping.canonical_name} {mapping.canonical_version} · {mapping.status} · confidence {mapping.confidence}
                    </span>
                    <span className="table-subtitle">
                      Source: {mapping.method} · observed {mapping.source_timestamp}
                    </span>
                    {mapping.status === "suggested" && (
                      <>
                        <button
                          type="button"
                          disabled={mappingSubmitting === mapping.mapping_id}
                          onClick={() => void decideMapping(mapping, "approve")}
                        >
                          Approve mapping
                        </button>
                        <button
                          type="button"
                          disabled={mappingSubmitting === mapping.mapping_id}
                          onClick={() => void decideMapping(mapping, "reject")}
                        >
                          Reject mapping
                        </button>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {softwareDetailGroup && (
            <section aria-label="Installed software machine details" className="detail-panel">
              <h2>{softwareDetailGroup.software_name} {softwareDetailGroup.software_version}</h2>
              <p className="detail-context">
                Exact server lookup · {softwareDetail.length} authorized machine{softwareDetail.length === 1 ? "" : "s"} ·
                scope {Object.entries(softwareDetailEnvelope?.scope ?? {}).map(([key, values]) => `${key}: ${values.join(", ")}`).join(" · ") || "all authorized scope"}
              </p>
              {detailError ? (
                <StatePanel title="Software detail unavailable" message={detailError} tone="error" />
              ) : (
                <div className="table-scroll">
                <table className="data-table detail-table">
                  <thead>
                    <tr>
                      <th>Machine</th>
                      <th>Source / environment</th>
                      <th>Subscription / resource group</th>
                      <th>Canonical identity</th>
                      <th>Raw identity</th>
                      <th>Observed</th>
                    </tr>
                  </thead>
                  <tbody>
                  {softwareDetail.map((machine, index) => (
                    <tr key={`${machine.resource_id || machine.source_computer_id || machine.machine_name}-${index}`}>
                      <td><strong>{machine.machine_name}</strong><span className="table-subtitle">{machine.resource_id || machine.source_computer_id}</span></td>
                      <td>{machine.source_type ? sourceLabel(machine.source_type) : "Unlinked"}<span className="table-subtitle">{machine.environment}</span></td>
                      <td>{machine.subscription_id || "Unknown"}<span className="table-subtitle">{machine.resource_group || "Unknown"}</span></td>
                      <td>{machine.canonical_identity}<span className="table-subtitle">{machine.canonical_name} {machine.canonical_version}</span></td>
                      <td>{machine.raw_identity.name || "Unknown"}<span className="table-subtitle">{machine.raw_identity.version || "Unknown"} · {machine.join_status === "linked" ? "exact resource join" : "resource join unavailable"}</span></td>
                      <td>{machine.observed_at}<span className="table-subtitle">{machine.time_generated}</span></td>
                    </tr>
                  ))}
                  </tbody>
                </table>
                </div>
              )}
            </section>
          )}
        </section>
      ) : (
        <section id="os-inventory-panel" role="tabpanel" aria-labelledby="os-inventory-tab" tabIndex={0}>
          <section aria-label="OS inventory summary" className="metric-grid">
            <MetricCard label="OS groups" value={groups.length} detail="Authorized OS identities" />
            <MetricCard label="Machines" value={totalMachines} detail="After scope filtering" />
            <MetricCard label="Needs review" value={reviewCount} detail="Unknown lifecycle mapping" />
          </section>
          <section aria-label="OS inventory dashboard" className="inventory-dashboard">
            <div className="card-header"><h2>EOL risk distribution</h2><span className="muted">{totalMachines} machines</span></div>
            {(["expired", "expiring", "supported", "review"] as const).map((bucket) => {
              const count = filteredGroups.filter((group) => riskBucket(group) === bucket).reduce((total, group) => total + group.machine_count, 0);
              return (
                <div className="inventory-bar-row" key={bucket}>
                  <span>{bucket === "expiring" ? "Expiring within 90 days" : bucket === "review" ? "Needs review" : bucket[0].toUpperCase() + bucket.slice(1)}</span>
                  <div className={`inventory-bar inventory-bar-${bucket}`} style={{ width: `${totalMachines ? Math.max(count ? 4 : 0, (count / totalMachines) * 100) : 0}%` }} aria-hidden="true" />
                  <strong>{count}</strong>
                </div>
              );
            })}
            <div className="card-header inventory-chart-secondary"><h2>Top OS versions</h2></div>
            {filteredGroups.slice(0, 5).map((group) => (
              <div className="inventory-bar-row" key={group.key}>
                <span>{group.os_name} {group.os_version}</span>
                <div className="inventory-bar" style={{ width: `${totalMachines ? Math.max(4, (group.machine_count / totalMachines) * 100) : 0}%` }} aria-hidden="true" />
                <strong>{group.machine_count}</strong>
              </div>
            ))}
          </section>
          <div className="inventory-filters" aria-label="OS inventory filters">
            <label>
              Search OS
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Name or version" />
            </label>
            <label>
              Source
              <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value as typeof sourceFilter)}>
                <option value="all">All sources</option>
                <option value="azure_vm">Azure VM</option>
                <option value="arc">Arc</option>
              </select>
            </label>
            <label>
              EOL status
              <select value={lifecycleFilter} onChange={(event) => setLifecycleFilter(event.target.value as typeof lifecycleFilter)}>
                <option value="all">All lifecycle states</option>
                <option value="expired">Expired</option>
                <option value="expiring">Expiring within 90 days</option>
                <option value="supported">Supported</option>
                <option value="review">Needs review</option>
              </select>
            </label>
            <label>
              Subscription
              <select value={subscriptionFilter} onChange={(event) => setSubscriptionFilter(event.target.value)}>
                <option value="all">All authorized subscriptions</option>
                {(scope.subscription ?? []).map((subscription) => (
                  <option key={subscription} value={subscription}>{subscription}</option>
                ))}
              </select>
            </label>
            <div className="inventory-source-badges" aria-label="OS source status">
              {Object.values(sourceStates).map((source) => (
                <StatusBadge key={source.source_type} label={`${sourceLabel(source.source_type)} · ${source.state}`} tone={sourceTone(source.state)} compact />
              ))}
            </div>
          </div>

          {inventory.loading && <StatePanel title="Loading OS inventory" message="Reading the active immutable generation." tone="loading" />}
          {inventory.error && (
            <StatePanel title="OS inventory unavailable" message={inventory.error.message} tone="error" />
          )}
          {!inventory.loading && !inventory.error && groups.length === 0 && (
            <StatePanel title="No OS observations" message="The authorized scope has no published OS inventory rows." />
          )}
          {!inventory.loading && !inventory.error && groups.length > 0 && filteredGroups.length === 0 && (
            <StatePanel title="No matching OS observations" message="Adjust the search, source, lifecycle, or subscription filters." />
          )}
          {partialSource && (
            <StatePanel
              title="Inventory source is partial"
              message={`${sourceLabel(partialSource.source_type)} source is ${partialSource.state}; successful rows are shown without treating the source as empty.`}
              tone="error"
            />
          )}

          {filteredGroups.length > 0 && (
            <section aria-label="OS inventory groups" className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>OS</th>
                    <th>Machines</th>
                    <th>Sources</th>
                    <th>Lifecycle</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredGroups.map((group) => (
                    <tr key={group.key}>
                      <td>
                        <strong>{group.os_name}</strong>
                        <span className="table-subtitle">{group.os_version}</span>
                      </td>
                      <td>{group.machine_count}</td>
                      <td>{group.source_types.map(sourceLabel).join(", ")}</td>
                      <td>
                        <StatusBadge label={lifecycleLabel(group)} tone={lifecycleTone(group)} />
                        {group.support_end && <span className="table-subtitle">ends {group.support_end}</span>}
                      </td>
                      <td>
                        <button type="button" onClick={() => openGroup(group)} aria-label={`View machines for ${group.os_name} ${group.os_version}`}>
                          View machines
                        </button>
                        {group.review_required && (
                          <button type="button" onClick={() => openLifecycleReview(group)}>
                            Review EOL date
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {reviewGroup && (
            <section aria-label="EOL lifecycle review" className="detail-panel">
              <h2>Review lifecycle: {reviewGroup.os_name} {reviewGroup.os_version}</h2>
              {reviewError && <StatePanel title="Lifecycle review unavailable" message={reviewError} tone="error" />}
              {review && (
                <>
                  <p>
                    {review.status === "catalog_hit" || review.status === "confirmed"
                      ? `Confirmed ${review.classification.support_end ?? "without a support end date"}.`
                      : "No catalog winner was selected. Review every cited candidate before confirming."}
                  </p>
                  {review.candidates.length > 0 && (
                    <ul>
                      {review.candidates.map((candidate) => (
                        <li key={candidate.candidate_id}>
                          <strong>{candidate.date}</strong> · {candidate.source_kind} · confidence {candidate.confidence}
                          <span className="table-subtitle">Claim: {candidate.extracted_claim}</span>
                          <span className="table-subtitle">Retrieved: {candidate.retrieved_at}</span>
                          <a href={candidate.citation} target="_blank" rel="noreferrer">
                            Citation
                          </a>
                          {review.status === "review_required" && (
                            <button
                              type="button"
                              disabled={reviewSubmitting}
                              onClick={() => confirmLifecycle(candidate.candidate_id)}
                            >
                              Confirm this date
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {review.status === "review_required" && (
                    <form
                      onSubmit={(event) => {
                        event.preventDefault();
                        void confirmLifecycle();
                      }}
                    >
                      <label>
                        Or enter a date
                        <input
                          type="date"
                          value={manualDate}
                          onChange={(event) => setManualDate(event.target.value)}
                          required
                        />
                      </label>
                      <button type="submit" disabled={reviewSubmitting || !manualDate}>
                        Confirm manual date
                      </button>
                    </form>
                  )}
                </>
              )}
            </section>
          )}

          {selectedKey && (
            <section aria-label="OS machine details" className="detail-panel">
              <h2>{detailGroup ? `${detailGroup.os_name} ${detailGroup.os_version}` : "Machine details"}</h2>
              {detailError ? (
                <StatePanel title="Machine detail unavailable" message={detailError} tone="error" />
              ) : (
                <div className="table-scroll">
                <table className="data-table detail-table">
                  <thead>
                    <tr>
                      <th>Machine</th>
                      <th>Source / environment</th>
                      <th>Subscription / resource group</th>
                      <th>Lifecycle</th>
                      <th>Observed / evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                  {detail.map((machine) => (
                    <tr key={machine.resource_id}>
                      <td><strong>{machine.machine_name}</strong><span className="table-subtitle">{machine.resource_id}</span></td>
                      <td>{sourceLabel(machine.source_type)}<span className="table-subtitle">{machine.environment}</span></td>
                      <td>{machine.subscription_id}<span className="table-subtitle">{machine.resource_group}</span></td>
                      <td><StatusBadge label={machine.review_required ? "EOL date needs review" : machine.lifecycle_status} tone={machine.review_required ? "unknown" : lifecycleTone({ ...machine, key: machine.resource_id, machine_count: 1, source_types: [machine.source_type] })} /></td>
                      <td>{machine.observed_at}<span className="table-subtitle">{machine.evidence.map((item) => `${item.source_engine} / ${item.source_table}`).join(" · ") || "Evidence retained by API envelope"}</span></td>
                    </tr>
                  ))}
                  </tbody>
                </table>
                </div>
              )}
            </section>
          )}
        </section>
      )}
    </main>
  );
}
