"use client";

import Link from "next/link";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StructuredData } from "@/components/ui/StructuredData";
import { useApi } from "@/hooks/useApi";
import { contextApi } from "@/lib/services";
import { useScope } from "@/lib/scope-context";

/** Business service operating view with semantic context, risk, and blast radius. */
export default function ServiceDetailPage({ params }: { params: { name: string } }) {
  const name = decodeURIComponent(params.name);
  const { scope } = useScope();
  const context = useApi(() => contextApi.businessService(name, scope), [name, scope]);
  const risk = useApi(() => contextApi.risk(name, scope), [name, scope]);
  const impact = useApi(() => contextApi.impact(name, scope), [name, scope]);
  const error = context.error ?? risk.error ?? impact.error;

  if (error) {
    return <div className="page-container"><StatePanel title="Service view is unavailable" message={error.message} tone="error" /></div>;
  }

  return (
    <div className="page-container">
      <div className="breadcrumb"><Link href="/services">Services</Link><span>/</span><span>{name}</span></div>
      <PageHeader
        eyebrow="Business service"
        title={name}
        description="What is affected in this business capability, which evidence supports it, and where ownership or dependency context is still missing."
        actions={<Link className="button button-primary" href={`/copilot?service=${encodeURIComponent(name)}`}>Ask Copilot</Link>}
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
          <section className="card"><div className="card-header"><h2>Service context</h2></div><div className="card-body"><StructuredData value={context.data?.data ?? {}} /></div></section>
          <section className="card"><div className="card-header"><h2>Aggregated risk</h2></div><div className="card-body"><StructuredData value={risk.data?.data ?? {}} /></div></section>
          <section className="card service-impact-card"><div className="card-header"><h2>Dependency impact</h2></div><div className="card-body"><StructuredData value={impact.data?.data ?? {}} /></div></section>
        </div>
      )}
    </div>
  );
}
