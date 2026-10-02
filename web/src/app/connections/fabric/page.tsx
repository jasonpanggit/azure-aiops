"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/ui/PageHeader";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { StatePanel } from "@/components/ui/StatePanel";
import { FabricMedallionPanel, FABRIC_LAYER_KEYS } from "@/components/fabric/medallion";
import { useApi } from "@/hooks/useApi";
import { buildFabricMedallionCopilotContext } from "@/lib/copilot/page-adapters";
import type { ScopeSelection } from "@/lib/scope";
import { useScope } from "@/lib/scope-context";
import { connectionsApi, fabricMedallionApi } from "@/lib/services";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

/** Per-subscription Fabric medallion workbench. */
export default function FabricMedallionPage() {
  return (
    <Suspense fallback={<StatePanel title="Loading Fabric medallion" message="Preparing subscription selection." tone="loading" />}>
      <FabricMedallionPageContent />
    </Suspense>
  );
}

function FabricMedallionPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { scope } = useScope();
  const [refreshKey, setRefreshKey] = useState(0);
  const connections = useApi(() => connectionsApi.list(scope), [scope]);
  const rows = useMemo(() => connections.data?.data ?? [], [connections.data]);

  const requestedSubscription = searchParams.get("subscription") ?? "";
  const [selectedSubscription, setSelectedSubscription] = useState(requestedSubscription);

  useEffect(() => {
    setSelectedSubscription(requestedSubscription);
  }, [requestedSubscription]);

  const selectSubscription = useCallback(
    (subscriptionId: string) => {
      setSelectedSubscription(subscriptionId);
      const params = new URLSearchParams(searchParams.toString());
      if (subscriptionId) params.set("subscription", subscriptionId);
      else params.delete("subscription");
      const query = params.toString();
      router.replace(query ? `/connections/fabric?${query}` : "/connections/fabric", { scroll: false });
    },
    [router, searchParams],
  );

  // The page-level subscription picker narrows the global scope so every
  // Fabric medallion call resolves to a single subscription's datasets.
  const fabricScope: ScopeSelection = useMemo(
    () => (selectedSubscription ? { ...scope, subscription: [selectedSubscription] } : scope),
    [scope, selectedSubscription],
  );

  const activeConnection = rows.find((connection) => connection.subscription_id === selectedSubscription);

  const [copilotOpen, setCopilotOpen] = useState(false);
  // Page-level medallion reads feed the read-only Copilot context. The embedded
  // FabricMedallionPanel owns its own independent reads; this adapter only
  // explains the already-loaded layer/manifest/governance/readiness evidence
  // and never gains a mutation path (D-03, D-09).
  const layerSummary = useApi(() => fabricMedallionApi.layers(fabricScope), [refreshKey, JSON.stringify(fabricScope)]);
  const manifest = useApi(() => fabricMedallionApi.manifest(fabricScope), [refreshKey, JSON.stringify(fabricScope)]);
  const governance = useApi(() => fabricMedallionApi.governance(fabricScope), [refreshKey, JSON.stringify(fabricScope)]);
  const capabilities = useApi(() => fabricMedallionApi.capabilities(fabricScope), [refreshKey, JSON.stringify(fabricScope)]);
  const fabricSections = [
    { source: "fabric/medallion-layers", envelope: layerSummary.data },
    { source: "fabric/manifest", envelope: manifest.data },
    { source: "fabric/governance", envelope: governance.data },
    { source: "fabric/capabilities", envelope: capabilities.data },
  ] as const;
  const fabricEvidence = fabricSections.flatMap(({ envelope }) => envelope?.evidence ?? []);
  const fabricSourceStatuses = fabricSections.flatMap(({ source, envelope }) => {
    if (!envelope) {
      return [{ source, availability: "unavailable", freshness: "unknown" }];
    }
    if (!envelope.evidence?.length) {
      return [{ source, availability: "available", freshness: "unknown" }];
    }
    return envelope.evidence.map((item) => ({
      source,
      availability: "available",
      freshness: item.freshness,
      observedAt: item.timestamp,
    }));
  });

  const capacity = capabilities.data?.data.capacity;
  const capacityStatus = String(capacity?.status ?? "").toLowerCase();
  const deploymentBlocked = capacityStatus
    ? ["paused", "suspended", "inactive", "deleted", "not_provisioned", "unprovisioned"].includes(capacityStatus)
    : false;
  const layerCounts = layerSummary.data?.data.layers;
  const fabricAvailable = fabricSections.every(({ envelope }) => Boolean(envelope));

  const fabricCopilot = buildFabricMedallionCopilotContext({
    scope: fabricScope,
    subscriptionId: selectedSubscription || null,
    layers: layerCounts ? FABRIC_LAYER_KEYS.map((layer) => ({
      layer,
      healthy: layerCounts[layer]?.healthy ?? 0,
      total: layerCounts[layer]?.total ?? 0,
    })) : [],
    manifest: (manifest.data?.data.entries ?? []).map((entry) => ({
      projection_name: entry.projection_name,
      disposition: entry.disposition,
      compatibility_version: entry.compatibility_version,
      subscription_id: entry.subscription_id,
    })),
    manifestTotalCount: manifest.data?.data.entries?.length ?? 0,
    governance: governance.data
      ? {
          ownership_gap_count: governance.data.data.ownership_gap_count,
          tag_gap_count: governance.data.data.tag_gap_count,
          referential_integrity_blockers: governance.data.data.referential_integrity_blockers,
        }
      : null,
    capacity: capacity
      ? { status: capacity.status, state: capacity.state, capacity_name: capacity.capacity_name ?? capacity.name }
      : null,
    semanticReadiness: capabilities.data?.data.semantic_readiness ?? null,
    dataAgentReadiness: capabilities.data?.data.data_agent_readiness ?? null,
    lineageRef: capabilities.data?.data.lineage?.native_lineage_url ?? null,
    available: fabricAvailable,
    deploymentBlocked,
    freshness: fabricAvailable ? "fresh" : "unavailable",
    evidence: fabricEvidence,
    sourceStatuses: fabricSourceStatuses.map((status) => (
      deploymentBlocked && status.source === "fabric/capabilities"
        ? { ...status, availability: "blocked" }
        : status
    )),
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Connections"
        title="Fabric medallion by subscription"
        description="Bronze, Silver, and Gold dataset health, publication lifecycle, governance gaps, and ingestion history for a single Azure subscription."
        actions={
          <div className="page-header-actions-group">
            <CopilotDrawerButton
              onClick={() => setCopilotOpen(true)}
              label="Ask Copilot about Fabric health"
            />
            <Link className="button" href="/connections">
              Back to connections
            </Link>
            <button type="button" className="button button-primary" onClick={() => setRefreshKey((value) => value + 1)}>
              Refresh Fabric health
            </button>
          </div>
        }
      />

      <CopilotInsights
        snapshot={fabricCopilot.snapshot}
        ready={!connections.loading}
        requestedScope={fabricCopilot.requestedScope}
        contextLabel="Fabric medallion"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      <section className="card fabric-subscription-picker" aria-label="Subscription selection">
        <div className="card-header">
          <div>
            <h2>Subscription</h2>
            <p>Select which onboarded subscription&apos;s Fabric medallion status to inspect.</p>
          </div>
        </div>
        <div className="card-body">
          {connections.error ? (
            <StatePanel title="Subscription list is unavailable" message={connections.error.message} tone="error" />
          ) : connections.loading ? (
            <StatePanel title="Loading subscriptions" message="Reading onboarded subscription connections." tone="loading" />
          ) : rows.length === 0 ? (
            <StatePanel
              title="No subscriptions onboarded"
              message="Onboard a subscription from the connections page before inspecting Fabric medallion health."
            />
          ) : (
            <>
              <label className="form-field">
                <span>Subscription connection</span>
                <select
                  className="form-control"
                  value={selectedSubscription}
                  onChange={(event) => selectSubscription(event.target.value)}
                >
                  <option value="">All onboarded subscriptions</option>
                  {rows.map((connection) => (
                    <option key={connection.connection_id} value={connection.subscription_id}>
                      {connection.name} ({connection.subscription_id})
                    </option>
                  ))}
                </select>
              </label>
              {activeConnection && (
                <div className="immutable-grid" aria-label="Selected subscription context">
                  <div>
                    <span>Connection</span>
                    <strong>{activeConnection.name}</strong>
                  </div>
                  <div>
                    <span>Subscription ID</span>
                    <strong>{activeConnection.subscription_id}</strong>
                  </div>
                  <div>
                    <span>Business service</span>
                    <strong>{activeConnection.business_service || "Service not mapped"}</strong>
                  </div>
                  <div>
                    <span>Environment</span>
                    <strong>{activeConnection.environment || "Environment not mapped"}</strong>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </section>

      <FabricMedallionPanel asTabPanel={false} refreshKey={refreshKey} scope={fabricScope} />

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Fabric medallion"
        requestedScope={fabricCopilot.requestedScope}
        snapshot={fabricCopilot.snapshot}
        starterQuestions={fabricCopilot.starterQuestions}
      />
    </div>
  );
}
