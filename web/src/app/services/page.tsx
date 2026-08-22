"use client";

import Link from "next/link";
import { useMemo } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useApi } from "@/hooks/useApi";
import { useScope } from "@/lib/scope-context";
import { connectionsApi, operationsApi } from "@/lib/services";
import { rankSituations } from "@/lib/situations";

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
  const connections = useApi(() => connectionsApi.list(scope), [scope]);
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

  const error = connections.error ?? incidents.error;

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Service operations"
        title="Business services"
        description="A service-centered operating model that connects ownership, environments, subscriptions, active risk, and technical dependencies."
      />
      <EvidenceBar
        evidence={[...(connections.data?.evidence ?? []), ...(incidents.data?.evidence ?? [])]}
        knowledgeVersion={incidents.data?.knowledge_version}
        warnings={[...(connections.data?.warnings ?? []), ...(incidents.data?.warnings ?? [])]}
      />
      {error ? (
        <StatePanel title="Service catalog is incomplete" message={error.message} tone="error" />
      ) : connections.loading || incidents.loading ? (
        <StatePanel title="Building service catalog" message="Joining business metadata with active operational risk." tone="loading" />
      ) : services.length === 0 ? (
        <StatePanel title="No business services mapped" message="Map subscription connections to business services to activate this operating view." />
      ) : (
        <div className="card service-catalog">
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
                {services.map((service) => (
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
        </div>
      )}
    </div>
  );
}
