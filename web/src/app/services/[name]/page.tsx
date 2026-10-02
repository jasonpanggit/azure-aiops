"use client";

import Link from "next/link";
import { useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StructuredData } from "@/components/ui/StructuredData";
import { useApi } from "@/hooks/useApi";
import { contextApi } from "@/lib/services";
import { buildServiceDetailCopilotContext, type ServiceDependencyObservation } from "@/lib/copilot/page-adapters";
import { useScope } from "@/lib/scope-context";
import type { CopilotFreshnessStatusV2, SemanticContext } from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

const DEPENDENCY_SECTION_KEYS = [
  "impacted_resources",
  "impacted_applications",
  "impacted_services",
  "impacted_business_services",
  "upstream_dependencies",
  "downstream_dependents",
] as const;

/** Collects bounded dependency/blast-radius names from typed semantic sections. */
function collectDependencies(...contexts: (SemanticContext | undefined)[]): ServiceDependencyObservation[] {
  const seen = new Set<string>();
  const dependencies: ServiceDependencyObservation[] = [];
  for (const context of contexts) {
    const sections = (context?.sections ?? {}) as Record<string, unknown>;
    for (const key of DEPENDENCY_SECTION_KEYS) {
      const value = sections[key];
      if (!Array.isArray(value)) continue;
      for (const item of value) {
        if (typeof item !== "string" || !item || seen.has(item)) continue;
        seen.add(item);
        dependencies.push({
          id: item,
          name: item,
          relation: key,
          resource_id: item.startsWith("/subscriptions/") ? item : undefined,
        });
      }
    }
  }
  return dependencies.slice(0, 50);
}

/** Business service operating view with semantic context, risk, and blast radius. */
export default function ServiceDetailPage({ params }: { params: { name: string } }) {
  const name = decodeURIComponent(params.name);
  const { scope } = useScope();
  const context = useApi(() => contextApi.businessService(name, scope), [name, scope]);
  const risk = useApi(() => contextApi.risk(name, scope), [name, scope]);
  const impact = useApi(() => contextApi.impact(name, scope), [name, scope]);
  const [copilotOpen, setCopilotOpen] = useState(false);

  const sectionKeys = (context?: SemanticContext): string[] => Object.keys(context?.sections ?? {});
  const sectionState = (
    api: {
      data?: {
        data?: SemanticContext;
        warnings?: string[];
      } | null;
      error?: Error | null;
    },
  ) => {
    const sourceStatus = api.data?.data?.source_status ?? {};
    const statuses = Object.values(sourceStatus).map((status) =>
      String(status).trim().toLowerCase());
    const allUnavailable = statuses.length > 0
      && statuses.every((status) =>
        ["deferred", "empty", "unavailable"].includes(status));
    const partiallyUnavailable = statuses.some((status) =>
      ["deferred", "empty", "unavailable"].includes(status));
    const available = !api.error && Boolean(api.data) && !allUnavailable;
    return {
      subject: api.data?.data?.subject
        ? {
            entity_type: api.data.data.subject.entity_type,
            name: api.data.data.subject.name,
            lifecycle_status: api.data.data.subject.lifecycle_status,
            owner: api.data.data.subject.owner,
            support_team: api.data.data.subject.support_team,
            business_service: api.data.data.subject.business_service,
            application: api.data.data.subject.application,
            environment: api.data.data.subject.environment,
            criticality: api.data.data.subject.criticality,
            resource_id: api.data.data.subject.resource_id,
          }
        : null,
      available,
      freshness: (
        !available
          ? "unavailable"
          : partiallyUnavailable
            ? "partial"
            : "fresh"
      ) as CopilotFreshnessStatusV2,
      observedAt: api.data?.data?.live_observed_at,
      sections: sectionKeys(api.data?.data ?? undefined),
      sourceStatus,
      warnings: [
        ...(api.data?.warnings ?? []),
        ...(api.error ? [api.error.message] : []),
      ],
    };
  };

  // Read-only contextual Copilot over the already-loaded semantic sections.
  // Selected service identity, ownership, dependencies, and independent
  // per-section availability stay bound; no row is actionable (D-03, D-04, D-08).
  const serviceCopilot = buildServiceDetailCopilotContext({
    scope,
    name,
    context: sectionState(context),
    risk: sectionState(risk),
    impact: sectionState(impact),
    dependencies: collectDependencies(context.data?.data ?? undefined, impact.data?.data ?? undefined),
    evidence: [...(context.data?.evidence ?? []), ...(risk.data?.evidence ?? []), ...(impact.data?.evidence ?? [])],
  });

  return (
    <div className="page-container">
      <div className="breadcrumb"><Link href="/services">Services</Link><span>/</span><span>{name}</span></div>
      <PageHeader
        eyebrow="Business service"
        title={name}
        description="What is affected in this business capability, which evidence supports it, and where ownership or dependency context is still missing."
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label={`Ask Copilot about ${name}`} />}
      />

      <CopilotInsights
        snapshot={serviceCopilot.snapshot}
        ready={!context.loading && !risk.loading && !impact.loading}
        requestedScope={serviceCopilot.requestedScope}
        contextLabel={name}
        onOpenCopilot={() => setCopilotOpen(true)}
      />
      <EvidenceBar
        evidence={[...(context.data?.evidence ?? []), ...(risk.data?.evidence ?? []), ...(impact.data?.evidence ?? [])]}
        knowledgeVersion={context.data?.knowledge_version}
        graphFreshness={context.data?.data?.graph_freshness}
        liveObservedAt={context.data?.data?.live_observed_at}
        sourceStatus={context.data?.data?.source_status}
        warnings={[...(context.data?.warnings ?? []), ...(risk.data?.warnings ?? []), ...(impact.data?.warnings ?? [])]}
      />
      {context.loading || risk.loading || impact.loading ? (
        <StatePanel title="Building service operating view" message="Resolving context, risk, and blast radius." tone="loading" />
      ) : (
        <div className="service-detail-grid">
          <section className="card"><div className="card-header"><h2>Service context</h2></div><div className="card-body">{context.error ? <StatePanel title="Service context unavailable" message={context.error.message} tone="partial" /> : <StructuredData value={context.data?.data ?? {}} />}</div></section>
          <section className="card"><div className="card-header"><h2>Aggregated risk</h2></div><div className="card-body">{risk.error ? <StatePanel title="Risk evidence unavailable" message={risk.error.message} tone="partial" /> : <StructuredData value={risk.data?.data ?? {}} />}</div></section>
          <section className="card service-impact-card"><div className="card-header"><h2>Dependency impact</h2></div><div className="card-body">{impact.error ? <StatePanel title="Dependency evidence unavailable" message={impact.error.message} tone="partial" /> : <StructuredData value={impact.data?.data ?? {}} />}</div></section>
        </div>
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel={name}
        requestedScope={serviceCopilot.requestedScope}
        snapshot={serviceCopilot.snapshot}
        starterQuestions={serviceCopilot.starterQuestions}
      />
    </div>
  );
}
