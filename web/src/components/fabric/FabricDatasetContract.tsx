"use client";

import { useEffect, useRef } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { StatePanel } from "@/components/ui/StatePanel";
import { TablePagination } from "@/components/ui/TablePagination";
import { useApi } from "@/hooks/useApi";
import type { ScopeSelection } from "@/lib/scope";
import { fabricMedallionApi } from "@/lib/services";
import { useTablePagination } from "@/lib/use-table-pagination";

const ISSUE_COPY: Record<string, string> = {
  source_unavailable: "Source recorded unavailable",
  source_failed: "Source attempt recorded failed",
  freshness_stale: "Metadata clock past target",
  freshness_unknown: "Metadata freshness unknown",
  quality_degraded: "Recorded quality degraded",
  quality_unknown: "Quality unreported",
  lineage_unreported: "Lineage reference unreported",
};

/** Opens a scoped registry declaration without schema probes, DAG inference, or publication. */
export function FabricDatasetContract({
  tableName, scope, refreshKey, id, onClose,
}: { tableName: string; scope: ScopeSelection; refreshKey: number; id: string; onClose: () => void }) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => panel.current?.focus(), []);
  const result = useApi(async () => {
    const envelope = await fabricMedallionApi.datasetContract(tableName, scope);
    const data = envelope.data;
    if (
      !data || data.table_name !== tableName ||
      data.declared_schema?.source !== "fabric.schema_registry" ||
      typeof data.declared_schema.version !== "string" || !data.declared_schema.version ||
      !["available", "not_registered"].includes(data.declared_schema.status) ||
      !Array.isArray(data.declared_schema.fields) ||
      data.declared_schema.fields.some(field => !field || typeof field.name !== "string" || !field.name ||
        typeof field.type !== "string" || !field.type || typeof field.nullable !== "boolean") ||
      (data.declared_schema.status === "not_registered" && data.declared_schema.fields.length > 0) ||
      data.deployed_schema_validation !== "not_collected" || data.producer_ownership !== "not_collected" ||
      data.dataset_dependency_graph !== "not_collected" || !Array.isArray(data.source_diagnostics) ||
      data.source_diagnostics.some(source => !source || typeof source.scope !== "object" || source.scope === null ||
        !Object.values(source.scope).every(values => Array.isArray(values) && values.every(value => typeof value === "string")) ||
        !["fresh", "stale", "unknown"].includes(source.freshness) ||
        !(["partition_key", "status_at", "recorded_status", "recorded_quality", "lineage_ref"] as const).every(key =>
          typeof source[key] === "string") ||
        !Array.isArray(source.issues) || source.issues.some(issue => typeof issue !== "string")) ||
      typeof data.evaluated_at !== "string" || !Number.isFinite(Date.parse(data.evaluated_at))
    ) throw new Error("Dataset contract response is inconsistent with the requested dataset or supported evidence contract.");
    return envelope;
  }, [tableName, JSON.stringify(scope), refreshKey]);
  const data = result.data?.data;
  const fields = useTablePagination(data?.declared_schema.fields ?? []);
  const sources = useTablePagination(data?.source_diagnostics ?? []);

  return (
    <section className="card fabric-contract" id={id} ref={panel} tabIndex={-1} aria-label={`Dataset contract: ${tableName}`}>
      <div className="card-header">
        <div><h3>{tableName}: contract &amp; source diagnostics</h3><p>Declared schema and recorded metadata, not a live validation result.</p></div>
        <button type="button" className="button" onClick={onClose}>Close contract</button>
      </div>
      <div className="card-body">
        {result.loading ? <StatePanel title="Loading declared dataset contract" message="Reading registry fields and scoped source diagnostics." tone="loading" />
          : result.error ? (
            <>
              <StatePanel title="Dataset contract unavailable" message={result.error.message} tone="error" />
              <button type="button" className="button" onClick={result.refetch}>Retry contract read</button>
            </>
          ) : data && (
            <>
              <EvidenceBar evidence={result.data!.evidence} knowledgeVersion={result.data!.knowledge_version} warnings={result.data!.warnings} />
              <p>Registry {data.declared_schema.version} · {data.declared_schema.source}. Diagnostic evaluation: {data.evaluated_at}.</p>
              <p>Deployed-schema validation and producer ownership are not collected. Field types and nullability describe the declared contract, not observed data conformity.</p>
              <h4>Declared fields</h4>
              {data.declared_schema.status === "not_registered" ? (
                <StatePanel title="No declared schema registered" message="The dataset has scoped source-status evidence, but no schema declaration in this registry version. This does not prove the deployed table has no schema." />
              ) : (
                <>
                  <table className="data-table fabric-contract-table">
                    <caption>{tableName}: {fields.total} declared fields</caption>
                    <thead><tr><th scope="col">Field</th><th scope="col">Declared type</th><th scope="col">Nullable</th></tr></thead>
                    <tbody>{fields.pageRows.map(field => <tr key={field.name}><th scope="row">{field.name}</th><td>{field.type}</td><td>{field.nullable ? "Yes" : "No"}</td></tr>)}</tbody>
                  </table>
                  <TablePagination total={fields.total} pageRows={fields.pageRows.length} page={fields.page} onPageChange={fields.setPage} pageSize={fields.pageSize} onPageSizeChange={fields.setPageSize} label="declared fields" />
                </>
              )}
              <h4>Dependency diagnostics</h4>
              <p>Dataset dependency edges are not collected. These scoped source references do not establish upstream/downstream tables, pipeline ordering, complete lineage, or root cause. Missing evidence is not &ldquo;no dependencies.&rdquo;</p>
              {sources.total === 0 ? <StatePanel title="No source diagnostics recorded" message="There is no retained source-status evidence to diagnose for this response." /> : (
                <>
                  <ul className="fabric-source-diagnostics" aria-label="Recorded dataset source diagnostics">
                    {sources.pageRows.map((source, index) => (
                      <li key={index}>
                        <strong>{Object.entries(source.scope).map(([name, values]) => `${name}: ${values.join(", ")}`).join(" · ") || "Scope identity unreported"}</strong>
                        {source.partition_key && <p>Source partition: {source.partition_key}</p>}
                        <p>Recorded status: {source.recorded_status}. Recorded quality: {source.recorded_quality}. Metadata freshness: {source.freshness}.</p>
                        <p>Status clock: {source.status_at || "Unreported"}. Recorded lineage reference: {source.lineage_ref || "Unreported"}.</p>
                        <p>{source.issues.length ? source.issues.map(issue => ISSUE_COPY[issue] ?? `Unrecognized diagnostic: ${issue}`).join(" · ") : "No listed metadata issues; dependency health is still unverified."}</p>
                      </li>
                    ))}
                  </ul>
                  <TablePagination total={sources.total} pageRows={sources.pageRows.length} page={sources.page} onPageChange={sources.setPage} pageSize={sources.pageSize} onPageSizeChange={sources.setPageSize} label="source diagnostics" />
                </>
              )}
            </>
          )}
      </div>
    </section>
  );
}
