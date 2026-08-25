"use client";

import { useMemo, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { inventoryApi } from "@/lib/services";
import type {
  InventorySourceStatus,
  LifecycleReview,
  OsInventoryGroup,
  OsInventoryMachine,
  SoftwareInventoryGroup,
  SoftwareInventoryMachine,
} from "@/lib/types";

function lifecycleLabel(group: OsInventoryGroup): string {
  return group.review_required ? "EOL date needs review" : group.lifecycle_status;
}

function sourceLabel(source: string): string {
  return source === "azure_vm" ? "Azure VM" : "Arc";
}

export default function SoftwareInventoryPage() {
  const { scope } = useScope();
  const [tab, setTab] = useState<"os" | "software">("os");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<OsInventoryMachine[]>([]);
  const [detailGroup, setDetailGroup] = useState<OsInventoryGroup | null>(null);
  const [softwareDetail, setSoftwareDetail] = useState<SoftwareInventoryMachine[]>([]);
  const [softwareDetailGroup, setSoftwareDetailGroup] = useState<SoftwareInventoryGroup | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [review, setReview] = useState<LifecycleReview | null>(null);
  const [reviewGroup, setReviewGroup] = useState<OsInventoryGroup | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [manualDate, setManualDate] = useState("");
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const scopeKey = useMemo(() => JSON.stringify(scope), [scope]);
  const inventory = useApi(() => inventoryApi.os(scope), [scopeKey, refreshKey]);
  const softwareInventory = useApi(() => inventoryApi.software(scope), [scopeKey]);

  const groups = inventory.data?.data.groups ?? [];
  const totalMachines = groups.reduce((total, group) => total + group.machine_count, 0);
  const reviewCount = groups.filter((group) => group.review_required).length;
  const sourceStates: Record<string, InventorySourceStatus> = inventory.data?.data.source_status ?? {};
  const partialSource = Object.values(sourceStates).find((source) => source.state !== "ready");
  const softwareGroups = softwareInventory.data?.data.groups ?? [];
  const softwareTotal = softwareGroups.reduce((total, group) => total + group.install_count, 0);
  const unlinkedSoftware = softwareGroups.reduce((total, group) => total + group.unlinked_count, 0);
  const softwareSourceStates: Record<string, InventorySourceStatus> =
    softwareInventory.data?.data.source_status ?? {};
  const softwarePartialSource = Object.values(softwareSourceStates).find((source) => source.state !== "ready");

  async function openGroup(group: OsInventoryGroup) {
    setSelectedKey(group.key);
    setDetailError(null);
    try {
      const response = await inventoryApi.osGroup(group.key, scope);
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
      const response = await inventoryApi.softwareGroup(group.key, scope);
      setSoftwareDetail(response.data.machines);
      setSoftwareDetailGroup(response.data.group);
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
      const response = await inventoryApi.lifecycleReview(group.key, scope);
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
        scope,
      );
      setReview(response.data);
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setReviewError(error instanceof Error ? error.message : "Lifecycle confirmation failed.");
    } finally {
      setReviewSubmitting(false);
    }
  }

  return (
    <main className="page-shell">
      <PageHeader
        eyebrow="Inventory"
        title="Software Inventory"
        description="Inspect authorized operating-system observations across native Azure VMs and Arc-enabled servers."
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

      <nav aria-label="Inventory views" className="tab-list">
        <button type="button" aria-pressed={tab === "os"} onClick={() => setTab("os")}>
          OS Inventory
        </button>
        <button type="button" aria-pressed={tab === "software"} onClick={() => setTab("software")}>
          Installed Software
        </button>
      </nav>

      {tab === "software" ? (
        <>
          <section aria-label="Installed software summary" className="metric-grid">
            <MetricCard label="Software groups" value={softwareGroups.length} detail="Canonical name and version" />
            <MetricCard label="Installations" value={softwareTotal} detail="Authorized current rows" />
            <MetricCard label="Unlinked rows" value={unlinkedSoftware} detail="Exact resource join required" />
          </section>
          {softwareInventory.loading && (
            <StatePanel title="Loading installed software" message="Reading ConfigurationData observations." tone="loading" />
          )}
          {softwareInventory.error && (
            <StatePanel title="Installed software unavailable" message={softwareInventory.error.message} tone="error" />
          )}
          {!softwareInventory.loading && !softwareInventory.error && softwareGroups.length === 0 && (
            <StatePanel title="No installed software observations" message="The authorized scope has no successful ConfigurationData rows." />
          )}
          {softwarePartialSource && (
            <StatePanel
              title="Installed software source is unavailable"
              message={`Log Analytics source is ${softwarePartialSource.state}; rows are not presented as a successful empty result.`}
              tone="error"
            />
          )}
          {softwareGroups.length > 0 && (
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
                  {softwareGroups.map((group) => (
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
          {softwareDetailGroup && (
            <section aria-label="Installed software machine details" className="detail-panel">
              <h2>{softwareDetailGroup.software_name} {softwareDetailGroup.software_version}</h2>
              {detailError ? (
                <StatePanel title="Software detail unavailable" message={detailError} tone="error" />
              ) : (
                <ul>
                  {softwareDetail.map((machine, index) => (
                    <li key={`${machine.resource_id || machine.source_computer_id || machine.machine_name}-${index}`}>
                      <strong>{machine.machine_name}</strong> · {machine.source_type ? sourceLabel(machine.source_type) : "Unlinked"} · {machine.environment} · {machine.subscription_id}
                      <span className="table-subtitle">
                        {machine.resource_group} · {machine.join_status === "linked" ? "exact resource join" : "resource join unavailable"} · observed {machine.observed_at}
                      </span>
                      <span className="table-subtitle">Raw: {machine.raw_software_name} {machine.raw_software_version}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </>
      ) : (
        <>
          <section aria-label="OS inventory summary" className="metric-grid">
            <MetricCard label="OS groups" value={groups.length} detail="Authorized OS identities" />
            <MetricCard label="Machines" value={totalMachines} detail="After scope filtering" />
            <MetricCard label="Needs review" value={reviewCount} detail="Unknown lifecycle mapping" />
          </section>

          {inventory.loading && <StatePanel title="Loading OS inventory" message="Reading the active immutable generation." tone="loading" />}
          {inventory.error && (
            <StatePanel title="OS inventory unavailable" message={inventory.error.message} tone="error" />
          )}
          {!inventory.loading && !inventory.error && groups.length === 0 && (
            <StatePanel title="No OS observations" message="The authorized scope has no published OS inventory rows." />
          )}
          {partialSource && (
            <StatePanel
              title="Inventory source is partial"
              message={`${sourceLabel(partialSource.source_type)} source is ${partialSource.state}; successful rows are shown without treating the source as empty.`}
              tone="error"
            />
          )}

          {groups.length > 0 && (
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
                  {groups.map((group) => (
                    <tr key={group.key}>
                      <td>
                        <strong>{group.os_name}</strong>
                        <span className="table-subtitle">{group.os_version}</span>
                      </td>
                      <td>{group.machine_count}</td>
                      <td>{group.source_types.map(sourceLabel).join(", ")}</td>
                      <td>
                        <StatusBadge label={lifecycleLabel(group)} tone={statusTone(group.review_required ? "unknown" : group.lifecycle_status)} />
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
                <ul>
                  {detail.map((machine) => (
                    <li key={machine.resource_id}>
                      <strong>{machine.machine_name}</strong> · {sourceLabel(machine.source_type)} · {machine.environment} · {machine.subscription_id}
                      <span className="table-subtitle">{machine.resource_group} · observed {machine.observed_at}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </>
      )}
    </main>
  );
}
