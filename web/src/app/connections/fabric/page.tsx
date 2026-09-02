"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { FabricMedallionPanel } from "@/components/fabric/medallion";
import { useApi } from "@/hooks/useApi";
import type { ScopeSelection } from "@/lib/scope";
import { useScope } from "@/lib/scope-context";
import { connectionsApi } from "@/lib/services";

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

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Connections"
        title="Fabric medallion by subscription"
        description="Bronze, Silver, and Gold dataset health, publication lifecycle, governance gaps, and ingestion history for a single Azure subscription."
        actions={
          <div className="page-header-actions-group">
            <Link className="button" href="/connections">
              Back to connections
            </Link>
            <button type="button" className="button button-primary" onClick={() => setRefreshKey((value) => value + 1)}>
              Refresh Fabric health
            </button>
          </div>
        }
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
    </div>
  );
}
