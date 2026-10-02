"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { OperationsSignalChart } from "@/components/ui/OperationsSignalChart";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { connectionsApi, operationsApi } from "@/lib/services";
import { buildServicesCopilotContext } from "@/lib/copilot/page-adapters";
import { rankSituations } from "@/lib/situations";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

interface ServiceRow {
  name: string;
  environments: Set<string>;
  subscriptions: Set<string>;
  situationCount: number;
  criticalCount: number;
  healthRisk: number;
}

/** Business service catalog synthesized from onboarding context and active Situations. */
export default function ServicesPage() {
  const { scope } = useScope();
  const connections = useApi(() => connectionsApi.listAll(scope), [scope]);
  const incidents = useApi(() => operationsApi.incidents(scope), [scope]);

  const services = useMemo(() => {
    const rows = new Map<string, ServiceRow>();
    for (const connection of connections.data?.data ?? []) {
      const name = connection.business_service || "Unmapped service";
      const row = rows.get(name) ?? {
        name,
        environments: new Set<string>(),
        subscriptions: new Set<string>(),
        situationCount: 0,
        criticalCount: 0,
        healthRisk: 0,
      };
      if (connection.environment) row.environments.add(connection.environment);
      row.subscriptions.add(connection.subscription_id);
      if (!["healthy", "active"].includes(connection.health_status)) row.healthRisk += 1;
      rows.set(name, row);
    }
    for (const situation of rankSituations(incidents.data?.data.incidents ?? [])) {
      for (const name of situation.businessServices.length ? situation.businessServices : ["Unmapped service"]) {
        const row = rows.get(name) ?? {
          name,
          environments: new Set<string>(),
          subscriptions: new Set<string>(),
          situationCount: 0,
          criticalCount: 0,
          healthRisk: 0,
        };
        row.situationCount += 1;
        if (situation.priority === "P1") row.criticalCount += 1;
        rows.set(name, row);
      }
    }
    return Array.from(rows.values()).sort(
      (left, right) => right.criticalCount - left.criticalCount || right.situationCount - left.situationCount
    );
  }, [connections.data, incidents.data]);

  const { filteredRows: filteredServices, filters: serviceFilters, resetFilters: resetServiceFilters } = useColumnFilters(services, [
    {
      id: "state",
      label: "State",
      getValues: (service) => service.criticalCount ? "Critical attention" : service.situationCount ? "At risk" : "No active situation",
    },
    {
      id: "environment",
      label: "Environment",
      getValues: (service) => Array.from(service.environments),
    },
  ]);
  const servicesPaging = useTablePagination(filteredServices);

  const [copilotOpen, setCopilotOpen] = useState(false);

  const error = connections.error;

  const connectionsAvailable = !connections.error && Boolean(connections.data);
  const incidentsAvailable = !incidents.error && Boolean(incidents.data);
  // Read-only contextual Copilot over the already-loaded, authorized catalog.
  // Visible services, ownership/scope, active-situation counts, health risk,
  // and honest visible/total coverage stay bound; no row is actionable (D-03, D-08).
  const servicesCopilot = buildServicesCopilotContext({
    scope,
    services: filteredServices.map((service) => ({
      name: service.name,
      environments: Array.from(service.environments),
      subscriptionCount: service.subscriptions.size,
      situationCount: service.situationCount,
      criticalCount: service.criticalCount,
      healthRisk: service.healthRisk,
      operationalState: service.criticalCount
        ? "Critical attention"
        : service.situationCount
          ? "At risk"
          : "No active situation",
    })),
    visibleCount: filteredServices.length,
    totalCount: services.length,
    filters: Object.fromEntries(
      serviceFilters
        .filter((filter) => filter.value !== "all")
        .map((filter) => [filter.id, [filter.value]]),
    ),
    connectionsAvailable,
    incidentsAvailable,
    evidence: [...(connections.data?.evidence ?? []), ...(incidents.data?.evidence ?? [])],
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Service operations"
        title="Which services need attention?"
        description="Compare business services by ownership, scope, active situations, and evidence coverage before opening a service brief."
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about services" />}
      />

      <CopilotInsights
        snapshot={servicesCopilot.snapshot}
        ready={!connections.loading && !incidents.loading}
        requestedScope={servicesCopilot.requestedScope}
        contextLabel="Services"
        onOpenCopilot={() => setCopilotOpen(true)}
      />
      <EvidenceBar
        evidence={[...(connections.data?.evidence ?? []), ...(incidents.data?.evidence ?? [])]}
        knowledgeVersion={incidents.data?.knowledge_version}
        warnings={[
          ...(connections.data?.warnings ?? []),
          ...(incidents.data?.warnings ?? []),
          ...(incidents.error ? [incidents.error.message] : []),
        ]}
      />
      {error ? (
        <StatePanel title="Service catalog is incomplete" message={error.message} tone="error" />
      ) : connections.loading || (!connections.data && incidents.loading) ? (
        <StatePanel title="Building service catalog" message="Joining business metadata with active operational risk." tone="loading" />
      ) : services.length === 0 ? (
        <StatePanel title="No business services mapped" message="Map subscription connections to business services to activate this operating view." />
      ) : (
        <>
          {incidents.error && (
            <StatePanel
              title="Incident data deferred"
              message={`Service catalog rows are available, but active situation data is unavailable: ${incidents.error.message}`}
              tone="partial"
            />
          )}
          <section className="card dashboard-visual-card service-overview-card">
            <div className="card-header">
              <div>
                <h2>Service risk map</h2>
                <p>Active situations grouped by business service.</p>
              </div>
              <span className="visual-card-kicker">{services.length} services</span>
            </div>
            <div className="card-body">
              <OperationsSignalChart
                signals={services.slice(0, 6).map((service) => ({
                  label: service.name,
                  value: service.situationCount,
                  tone: service.criticalCount ? "critical" : service.situationCount ? "warning" : "success",
                }))}
              />
            </div>
          </section>
          <div className="card service-catalog">
            <TableColumnFilters
              filters={serviceFilters}
              onReset={resetServiceFilters}
              resultCount={filteredServices.length}
              totalCount={services.length}
            />
            <div className="table-scroll">
            <table className="operations-table">
              <thead>
                <tr>
                  <th>Business service</th>
                  <th>Operational state</th>
                  <th>Active situations</th>
                  <th>Environments</th>
                  <th>Subscriptions</th>
                  <th aria-label="Open" />
                </tr>
              </thead>
              <tbody>
                {servicesPaging.pageRows.map((service) => (
                  <tr key={service.name}>
                    <td>
                      <Link className="table-primary-link" href={`/services/${encodeURIComponent(service.name)}`}>
                        {service.name}
                      </Link>
                    </td>
                    <td>
                      <StatusBadge
                        label={service.criticalCount ? "Critical attention" : service.situationCount ? "At risk" : "No active situation"}
                        tone={service.criticalCount ? "critical" : service.situationCount ? "warning" : "success"}
                      />
                    </td>
                    <td><strong>{service.situationCount}</strong><div className="table-secondary">{service.criticalCount} critical</div></td>
                    <td>{Array.from(service.environments).join(", ") || "Not mapped"}</td>
                    <td>{service.subscriptions.size}</td>
                    <td><Link className="table-open-link" href={`/services/${encodeURIComponent(service.name)}`}>→</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <TablePagination
            total={servicesPaging.total}
            pageRows={servicesPaging.pageRows.length}
            page={servicesPaging.page}
            onPageChange={servicesPaging.setPage}
            pageSize={servicesPaging.pageSize}
            onPageSizeChange={servicesPaging.setPageSize}
            label="services"
          />
          </div>
        </>
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Services"
        requestedScope={servicesCopilot.requestedScope}
        snapshot={servicesCopilot.snapshot}
        starterQuestions={servicesCopilot.starterQuestions}
      />
    </div>
  );
}
