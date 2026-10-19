"use client";

import { StatePanel } from "@/components/ui/StatePanel";
import { TablePagination } from "@/components/ui/TablePagination";
import { useTablePagination } from "@/lib/use-table-pagination";
import type { FabricRecordedEvidence as RecordedEvidence } from "@/lib/types";

/** Displays recorded source attempts and retention without inferring serving activation. */
export function FabricRecordedEvidence({ tableName, evidence }: {
  tableName: string;
  evidence?: RecordedEvidence;
}) {
  const supported = evidence?.evidence_mode === "recorded_metadata" && evidence.generation_kind === "source_partition";
  const sources = useTablePagination(supported ? evidence.sources : []);

  return (
    <details>
      <summary>Inspect recorded source evidence for {tableName}</summary>
      <section aria-label={`Recorded source evidence: ${tableName}`}>
        <h4>Source-partition generations</h4>
        <p>Last good means recorded source retention, not an active serving product. Attempts, freshness, and downstream readiness are independent.</p>
        {!evidence ? (
          <StatePanel title="Recorded source evidence unavailable" message="This response does not supply source-partition attempt or retention evidence." />
        ) : !supported ? (
          <StatePanel title="Unsupported source evidence contract" message="This response cannot be interpreted as recorded source-partition evidence." tone="error" />
        ) : sources.total === 0 ? (
          <StatePanel title="No source-partition evidence recorded" message="An empty receipt list does not prove successful ingestion or serving activation." />
        ) : (
          <>
            <ul aria-label={`${tableName} source partitions`}>
              {sources.pageRows.map((source, index) => (
                <li key={index}>
                  <strong>{Object.entries(source.scope).map(([key, values]) => `${key}: ${values.join(", ")}`).join(" · ") || "Scope unreported"}</strong>
                  <dl>
                    <div><dt>Source partition</dt><dd>{source.partition_key || "Unreported"}</dd></div>
                    <div><dt>Metadata observation</dt><dd>{source.observed_at || "Unreported"}</dd></div>
                    <div><dt>Metadata freshness</dt><dd>{source.freshness}</dd></div>
                    <div><dt>Recorded status</dt><dd>{source.recorded_status || "unknown"}</dd></div>
                    <div><dt>Provider status</dt><dd>{source.provider_status || "unknown"}</dd></div>
                    <div><dt>Last attempt status</dt><dd>{source.last_attempt.status || "unknown"}</dd></div>
                    <div><dt>Attempted source generation</dt><dd>{source.last_attempt.generation_id || "Unreported"}</dd></div>
                    <div><dt>Attempted at</dt><dd>{source.last_attempt.attempted_at || "Unreported"}</dd></div>
                    <div><dt>Attempt reason code</dt><dd>{source.last_attempt.reason_code || "Unreported"}</dd></div>
                    <div><dt>Last-good retention evidence</dt><dd>{source.last_good.status}</dd></div>
                    <div><dt>Retained source generation</dt><dd>{source.last_good.generation_id || "Unreported"}</dd></div>
                    <div><dt>Last good observed at</dt><dd>{source.last_good.observed_at || "Unreported"}</dd></div>
                    <div><dt>Retention reason code</dt><dd>{source.last_good.reason_code || "Unreported"}</dd></div>
                    <div><dt>Recorded lineage reference</dt><dd>{source.lineage_ref || "Unreported"}</dd></div>
                  </dl>
                </li>
              ))}
            </ul>
            <TablePagination total={sources.total} pageRows={sources.pageRows.length} page={sources.page} onPageChange={sources.setPage} pageSize={sources.pageSize} onPageSizeChange={sources.setPageSize} label={`${tableName} source partitions`} />
          </>
        )}
      </section>
    </details>
  );
}
