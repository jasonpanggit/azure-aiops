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
import { ServiceBrief } from "@/components/ServiceBrief";
import { serviceDependencies, serviceSourceState } from "@/lib/service-brief";
import { overviewHref } from "@/lib/overview";
import type { Envelope } from "@/lib/types";

/** Collects bounded dependency/blast-radius names from typed semantic sections. */
function collectDependencies(...contexts: (SemanticContext | undefined)[]): ServiceDependencyObservation[] {
  return serviceDependencies(...contexts).slice(0, 50).map(row => ({
    id: `${row.relation}:${row.entityType}:${row.id}`, name: row.name, relation: row.relation, resource_id: row.resourceId || undefined,
  }));
}

/** Business service operating view with semantic context, risk, and blast radius. */
export default function ServiceDetailPage({ params }: { params: { name: string } }) {
  const name = params.name;
  const { scope } = useScope();
  return <ServiceWorkspace key={`${JSON.stringify(scope)}:${name}`} name={name} />;
}

function ServiceWorkspace({ name }: { name: string }) {
  const { scope } = useScope();
  const context = useApi(() => contextApi.businessService(name, scope), [name, scope]);
  const risk = useApi(() => contextApi.risk(name, scope), [name, scope]);
  const impact = useApi(() => contextApi.impact(name, scope), [name, scope]);
  const [copilotOpen, setCopilotOpen] = useState(false);

  const sectionKeys = (context?: SemanticContext): string[] => Object.keys(context?.sections ?? {});
  const sectionState = (
    api: {
      data?: Envelope<SemanticContext> | null;
      error?: Error | null;
    },
  ) => {
    const sourceStatus = api.data?.data?.source_status ?? {};
    const source = serviceSourceState(api.data, api.error);
    const available = source.available;
    return {
      subject: available && api.data?.data?.subject
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
          : source.state
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
    dependencies: collectDependencies(
      serviceSourceState(context.data, context.error).available ? context.data?.data : undefined,
      serviceSourceState(impact.data, impact.error).available ? impact.data?.data : undefined,
    ),
    evidence: [...(context.data?.evidence ?? []), ...(risk.data?.evidence ?? []), ...(impact.data?.evidence ?? [])],
  });

  return (
    <div className="page-container operational-page">
      <div className="breadcrumb"><Link href={overviewHref("/services", scope)}>Services</Link><span>/</span><span>{name}</span></div>
      <PageHeader
        eyebrow="Business service"
        title={name}
        description="What is affected in this business capability, which evidence supports it, and where ownership or dependency context is still missing."
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label={`Ask Copilot about ${name}`} />}
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
        <><ServiceBrief context={context} risk={risk} impact={impact} scope={scope} />
        <nav className="section-nav" aria-label="Service detail sections">
          <a href="#service-context">Source context</a><a href="#service-risk">Risk evidence</a><a href="#service-impact">Dependency impact</a>
        </nav>
        <div className="service-detail-grid">
          <section id="service-context" className="card" aria-label="Service context"><div className="card-header"><h2>Service context</h2><p>Review the returned service context and its source qualifications.</p></div><div className="card-body">{context.error ? <StatePanel title="Service context unavailable" message={context.error.message} tone="partial" /> : <details><summary>Inspect source context</summary><StructuredData value={context.data?.data ?? {}} /></details>}</div></section>
          <section id="service-risk" className="card" aria-label="Aggregated risk"><div className="card-header"><h2>Aggregated risk</h2><p>Review reported risk evidence without inferring source completeness.</p></div><div className="card-body">{risk.error ? <StatePanel title="Risk evidence unavailable" message={risk.error.message} tone="partial" /> : <details><summary>Inspect source risk</summary><StructuredData value={risk.data?.data ?? {}} /></details>}</div></section>
          <section id="service-impact" className="card service-impact-card" aria-label="Dependency impact"><div className="card-header"><h2>Dependency impact</h2><p>Dependency context does not establish verified deployment impact.</p></div><div className="card-body">{impact.error ? <StatePanel title="Dependency evidence unavailable" message={impact.error.message} tone="partial" /> : <details><summary>Inspect source impact</summary><StructuredData value={impact.data?.data ?? {}} /></details>}</div></section>
        </div></>
      )}

      <CopilotInsights
        snapshot={serviceCopilot.snapshot}
        ready={!context.loading && !risk.loading && !impact.loading}
        requestedScope={serviceCopilot.requestedScope}
        contextLabel={name}
        onOpenCopilot={() => setCopilotOpen(true)}
      />

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
