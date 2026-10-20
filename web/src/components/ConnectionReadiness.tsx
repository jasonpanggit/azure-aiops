"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useApi } from "@/hooks/useApi";
import { formatDateTime } from "@/lib/format";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { fabricMedallionApi, inventoryApi, ontologyAutomationApi } from "@/lib/services";
import type { SubscriptionConnection } from "@/lib/types";
import { StatusBadge } from "./ui/StatusBadge";

/** Independently sourced readiness stages; discovery success is not publication proof. */
export function ConnectionReadiness({ connection, scope, refreshKey }: {
  connection: SubscriptionConnection;
  scope: ScopeSelection;
  refreshKey: number;
}) {
  const selectedScope = useMemo(() => ({
    ...scope, subscription: [connection.subscription_id], subscription_connection: [connection.connection_id],
  }), [scope, connection.subscription_id, connection.connection_id]);
  const key = JSON.stringify(selectedScope);
  const fabricHref = `/connections/fabric?${scopeToSearchParams(selectedScope)}`;
  const inventory = useApi(() => inventoryApi.resources(selectedScope, 0, 1), [key, refreshKey]);
  const layers = useApi(() => fabricMedallionApi.layers(selectedScope), [key, refreshKey]);
  const ontology = useApi(() => ontologyAutomationApi.status(connection.connection_id, selectedScope), [key, refreshKey]);
  const capabilities = useApi(() => fabricMedallionApi.capabilities(selectedScope), [key, refreshKey]);
  const generation = ontology.data?.data.generation;
  const inventoryFamilies = Object.values(inventory.data?.data.family_availability ?? {});
  const inventoryScopeQualified = inventory.data?.data.scope_qualification?.status === "supported";
  const inventoryGeneration = inventory.data?.data.generation_id;
  const inventoryDetail = inventory.data
    ? `${inventoryScopeQualified
      ? `${inventory.data.pagination?.total ?? "Unknown"} authorized inventory resources`
      : "Connection-scoped inventory count is unavailable: published connection attribution is not qualified"}; query contract ${inventory.data.data.query_version || "not reported"}. ${inventoryGeneration
      ? `Publication generation ${inventoryGeneration}.`
      : "Publication generation is not reported by this endpoint."} Discovery record counts are not resource counts. ${inventoryFamilies.map(family => `${family.family}: ${family.state}`).join("; ")}`
    : "Reading the inventory consumer contract.";
  const stages = [
    {
      name: "Discovery", status: connection.sync_status || "unknown",
      detail: `${connection.sync_record_count ?? "Unknown"} discovery records; last successful sync ${formatDateTime(connection.last_successful_sync_at)}.`,
      href: "/connections",
    },
    {
      name: "Persisted inventory", status: inventory.loading ? "loading" : inventory.error ? "unavailable" : !inventoryScopeQualified ? "unknown" : inventoryFamilies.some(family => family.state !== "ready") ? "partial" : inventory.data ? "observed" : "unknown",
      detail: inventory.error?.message ?? inventoryDetail,
      href: null,
    },
    ...(["bronze", "silver", "gold"] as const).map(layer => {
      const count = layers.data?.data.layers[layer];
      return {
        name: `${layer[0].toUpperCase()}${layer.slice(1)} publication`,
        status: layers.loading ? "loading" : layers.error ? "unavailable" : !count?.total ? "unknown" : count.healthy === count.total ? "healthy" : "degraded",
        detail: layers.error?.message ?? (count
          ? `${count.healthy}/${count.total} registered datasets healthy. Observed ${formatDateTime(layers.data?.evidence?.[0]?.timestamp)}.`
          : "No layer evidence returned."),
        href: fabricHref,
      };
    }),
    {
      name: "Active ontology", status: ontology.loading ? "loading" : ontology.error ? "unavailable" : generation?.status ?? "unknown",
      detail: ontology.error?.message ?? (generation
        ? `Active pointer: ${generation.active_generation || "none"}. Validation ${generation.validation.passed ? "passed" : "not passed"}; consumer compatibility ${generation.compatibility.all_consumers_compatible ? "reported compatible" : "not confirmed"}.`
        : "Reading generation and pointer evidence."),
      href: "/connections",
    },
    {
      name: "Consumer capabilities", status: capabilities.loading ? "loading" : capabilities.error ? "unavailable" : "reported",
      detail: capabilities.error?.message ?? (capabilities.data
        ? `Capacity ${capabilities.data.data.capacity.status}; semantic model ${capabilities.data.data.semantic_readiness.status}; Data Agent ${capabilities.data.data.data_agent_readiness.status}. These capability checks do not prove every portal consumer is healthy.`
        : "Reading capacity and consumer capability evidence."),
      href: fabricHref,
    },
  ];
  return (
    <section className="card" aria-label={`Readiness for ${connection.name}`}>
      <div className="card-header"><div><h2>Connection readiness journey</h2><p>{connection.name}: a successful sync does not prove Fabric publication or downstream readiness. Each stage reports its own evidence.</p></div></div>
      <ol className="timeline-list card-body">
        {stages.map(stage => <li key={stage.name}>
          <strong>{stage.name}</strong>
          <StatusBadge label={stage.status} tone={stage.status === "unavailable" ? "critical" : stage.status === "healthy" ? "success" : "neutral"} compact />
          <span>{stage.detail}</span>
          {stage.href
            ? <Link href={stage.href}>Inspect {stage.name.toLowerCase()}</Link>
            : <span>Inventory drill-through is unavailable: the destination does not support this selected connection scope.</span>}
        </li>)}
      </ol>
    </section>
  );
}
