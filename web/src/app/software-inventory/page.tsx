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
import type { InventorySourceStatus, OsInventoryGroup, OsInventoryMachine } from "@/lib/types";

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
  const [detailError, setDetailError] = useState<string | null>(null);
  const scopeKey = useMemo(() => JSON.stringify(scope), [scope]);
  const inventory = useApi(() => inventoryApi.os(scope), [scopeKey]);

  const groups = inventory.data?.data.groups ?? [];
  const totalMachines = groups.reduce((total, group) => total + group.machine_count, 0);
  const reviewCount = groups.filter((group) => group.review_required).length;
  const sourceStates: Record<string, InventorySourceStatus> = inventory.data?.data.source_status ?? {};
  const partialSource = Object.values(sourceStates).find((source) => source.state !== "ready");

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
        <StatePanel
          title="Installed Software is coming in the next inventory slice"
          message="The OS tracer is live. Installed-software observations will appear here once the ConfigurationData source is connected."
        />
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
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
