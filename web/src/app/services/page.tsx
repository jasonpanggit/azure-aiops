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
import { overviewHref } from "@/lib/overview";
import type { SubscriptionConnection } from "@/lib/types";

interface ServiceRow {
  name: string;
  environments: Set<string>;
  subscriptions: Set<string>;
  situationCount: number;
  criticalCount: number;
  healthRisk: number;
  connections: SubscriptionConnection[];
  unmapped: boolean;
}

/** Business service catalog synthesized from registry metadata and a separately sourced incident report. */
export default function ServicesPage() {
  const { scope } = useScope();
  return <ServicesWorkspace key={JSON.stringify(scope)} />;
}

function ServicesWorkspace() {
  const { scope } = useScope();
  const connections = useApi(() => connectionsApi.listAll(scope), [scope]);
  const incidents = useApi(() => operationsApi.incidents(scope), [scope]);

  const services = useMemo(() => {
    const rows = new Map<string, ServiceRow>();
    for (const connection of connections.data?.data ?? []) {
      const mappedName = connection.business_service?.trim();
      const name = mappedName || "Unmapped service";
      const key = mappedName ? `service:${name}` : "unmapped";
      const row = rows.get(key) ?? {
        name,
        environments: new Set<string>(),
        subscriptions: new Set<string>(),
        situationCount: 0,
        criticalCount: 0,
        healthRisk: 0,
        connections: [],
        unmapped: !mappedName,
      };
      if (connection.environment) row.environments.add(connection.environment);
      row.subscriptions.add(connection.subscription_id);
      if (!["healthy", "active"].includes(connection.health_status)) row.healthRisk += 1;
      row.connections.push(connection);
      rows.set(key, row);
    }
    for (const situation of rankSituations(incidents.data?.data.incidents ?? [])) {
      for (const name of situation.businessServices.length ? situation.businessServices : ["Unmapped service"]) {
        const unmapped = !situation.businessServices.length;
        const key = unmapped ? "unmapped" : `service:${name}`;
        const row = rows.get(key) ?? {
          name,
          environments: new Set<string>(),
          subscriptions: new Set<string>(),
          situationCount: 0,
          criticalCount: 0,
          healthRisk: 0,
          connections: [],
          unmapped,
        };
        row.situationCount += 1;
        if (situation.priority === "P1") row.criticalCount += 1;
        rows.set(key, row);
      }
    }
    return Array.from(rows.values()).sort(
      (left, right) => right.criticalCount - left.criticalCount || right.situationCount - left.situationCount
    );
  }, [connections.data, incidents.data]);

  const incidentsAvailable = !incidents.loading && !incidents.error && Boolean(incidents.data);
  const stateFor = (service: ServiceRow) => !incidentsAvailable ? "Incident evidence unavailable" : service.criticalCount ? "Critical attention" : service.situationCount ? "Incident associations present" : "No incident associations in loaded report";
  const mappingFields = ["business_service", "owner", "support_team", "environment"] as const;
  const missingFields = (connection: SubscriptionConnection) => mappingFields.filter(field => !connection[field]?.trim());
  const mappingGaps = (connections.data?.data ?? []).filter(connection => missingFields(connection).length > 0);
  const { filteredRows: filteredServices, filters: serviceFilters, resetFilters: resetServiceFilters } = useColumnFilters(services, [
    {
      id: "state",
      label: "State",
      getValues: stateFor,
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
  // Read-only contextual Copilot over the already-loaded, authorized catalog.
  // Visible services, ownership/scope, active-situation counts, health risk,
  // and honest visible/total coverage stay bound; no row is actionable (D-03, D-08).
  const servicesCopilot = buildServicesCopilotContext({
    scope,
    services: filteredServices.map((service) => ({
      id: service.unmapped ? "unmapped" : `service:${service.name}`,
      name: service.name,
      environments: Array.from(service.environments),
      subscriptionCount: service.subscriptions.size,
      situationCount: service.situationCount,
      criticalCount: service.criticalCount,
      healthRisk: service.healthRisk,
      operationalState: stateFor(service),
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
    connectionsFreshness: connections.data?.evidence?.length && connections.data.evidence.every(row => row.freshness === "fresh") ? "fresh" : "partial",
    incidentsFreshness: incidents.data?.evidence?.some(row => row.freshness === "stale") ? "stale" : incidents.data?.evidence?.length && incidents.data.evidence.every(row => row.freshness === "fresh") ? "fresh" : "partial",
    evidence: [...(connections.data?.evidence ?? []), ...(incidents.data?.evidence ?? [])],
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Service operations"
        title="Which services need attention?"
        description="Compare registry mappings, loaded incident associations, and evidence gaps before opening a service brief."
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
      {incidents.error && !connections.error && !connections.loading && (
        <StatePanel
          title="Incident data deferred"
          message={`Service catalog rows are available, but incident evidence is unavailable: ${incidents.error.message}`}
          tone="partial"
        />
      )}
      {error ? (
        <StatePanel title="Service catalog is incomplete" message={error.message} tone="error" />
      ) : connections.loading || (!connections.data && incidents.loading) ? (
        <StatePanel title="Building service catalog" message="Joining business metadata with active operational risk." tone="loading" />
      ) : services.length === 0 ? (
        <StatePanel title="No service labels in loaded sources" message="Review accessible connection mappings. Unavailable incident evidence does not establish an empty service estate." />
      ) : (
        <>
          <section className="card service-brief" aria-label="Service mapping completeness">
            <div className="card-header"><div><h2>Mapping completeness</h2><p>Review missing accountable context in authorized connection registry rows, not inferred resource ownership.</p></div></div>
            <div className="card-body">
              <p>{mappingGaps.length}/{connections.data?.data.length ?? 0} loaded connection rows have missing service, owner, support team, or environment.
                {" "}Disabled connections are included. Distinct services are synthesized labels, not an authoritative service registry or estate denominator.</p>
              <p>Incident associations are a separate source. A missing or empty incident report never establishes availability, latency, SLO attainment, or error-budget health.</p>
              {mappingGaps.length > 0 ? <ul>{mappingGaps.slice(0, 20).map(connection => <li key={connection.connection_id}>
                <Link href={overviewHref("/connections", scope, connection.is_active ? connection.connection_id : undefined)}>{connection.name}</Link>
                {" "}· Missing: {missingFields(connection).map(field => field.replaceAll("_", " ")).join(", ")}
              </li>)}</ul> : <p>No missing values in these four fields among the loaded registry rows; this is not a resource mapping completeness claim.</p>}
              {mappingGaps.length > 20 && <p>Showing 20/{mappingGaps.length} rows. <Link href={overviewHref("/connections", scope)}>Review remaining mapping gaps in Connections</Link>.</p>}
            </div>
          </section>
          <section className="card dashboard-visual-card service-overview-card">
            <div className="card-header">
              <div>
                <h2>Incident association map</h2>
                <p>Loaded incident associations grouped by business service, not service reliability.</p>
              </div>
              <span className="visual-card-kicker">{services.length} services</span>
            </div>
            <div className="card-body">
              {incidentsAvailable ? <OperationsSignalChart
                signals={services.slice(0, 6).map((service) => ({
                  label: service.name,
                  value: service.situationCount,
                  tone: service.criticalCount ? "critical" : service.situationCount ? "warning" : "success",
                }))}
              /> : <p>Incident evidence unavailable; no clean service state is inferred.</p>}
            </div>
          </section>
          <div className="card service-catalog">
            <TableColumnFilters
              filters={serviceFilters}
              onReset={resetServiceFilters}
              resultCount={filteredServices.length}
              totalCount={services.length}
            />
            <p className="service-scroll-hint">More columns may be off-screen. Scroll horizontally, or focus the table and use arrow keys.</p>
            <div className="table-scroll" tabIndex={0} role="region" aria-label="Service catalog, horizontally scrollable">
            <table className="operations-table">
              <caption>Loaded authorized service labels; incident counts may associate the same incident with multiple services.</caption>
              <thead>
                <tr>
                  <th>Business service</th>
                  <th>Operational state</th>
                  <th>Incident associations</th>
                  <th>Connection mapping</th>
                  <th>Environments</th>
                  <th>Mapped subscriptions</th>
                  <th aria-label="Open" />
                </tr>
              </thead>
              <tbody>
                {servicesPaging.pageRows.map((service) => (
                  <tr key={`${service.unmapped}:${service.name}`}>
                    <td>
                      {service.unmapped ? <Link className="table-primary-link" href={overviewHref("/connections", scope)}>Unmapped service · review connections</Link> : <Link className="table-primary-link" href={overviewHref(`/services/${encodeURIComponent(service.name)}`, scope)}>{service.name}</Link>}
                    </td>
                    <td>
                      <StatusBadge
                        label={stateFor(service)}
                        tone={!incidentsAvailable ? "warning" : service.criticalCount ? "critical" : service.situationCount ? "warning" : "neutral"}
                      />
                    </td>
                    <td><strong>{incidentsAvailable ? service.situationCount : "—"}</strong><div className="table-secondary">{incidentsAvailable ? `${service.criticalCount} critical; report scope only` : "Not assessed"}</div></td>
                    <td>{service.connections.length ? <><span>{service.connections.filter(connection => missingFields(connection).length === 0).length}/{service.connections.length} mapped registry rows</span>
                      <div className="table-secondary">Fields: service, owner, support, environment; not resource coverage</div></> : "No connection mapping rows reported"}</td>
                    <td>{Array.from(service.environments).join(", ") || "Not mapped"}</td>
                    <td>{service.connections.length ? service.subscriptions.size : "Unreported"}</td>
                    <td><Link className="table-open-link" aria-label={`Review ${service.name}`} href={overviewHref(service.unmapped ? "/connections" : `/services/${encodeURIComponent(service.name)}`, scope)}>→</Link></td>
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
