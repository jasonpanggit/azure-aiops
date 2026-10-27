"use client";

import { StatePanel } from "@/components/ui/StatePanel";
import type { FabricPublicationEvidence as PublicationEvidence, FabricPublicationFact, FabricPublicationStage } from "@/lib/types";

const STAGES: Array<[FabricPublicationStage, string]> = [
  ["acquired", "Acquisition completeness"],
  ["validated", "Publisher validation"],
  ["persisted", "Publisher persistence"],
  ["registered", "Cloud registration"],
  ["active", "Active readable product"],
  ["consumer_query_verified", "Consumer query qualification"],
];

function validFact(fact: FabricPublicationFact | null): boolean {
  return fact === null || !!fact && (
    [fact.attempt_id, fact.source_generation, fact.publication_run_id].every(
      (value) => typeof value === "string" && value.trim().length > 0 && value.length <= 256,
    ) &&
    typeof fact.observed_at === "string" && Number.isFinite(Date.parse(fact.observed_at)) &&
    !!fact.scope && Object.keys(fact.scope).length === 1 &&
    Array.isArray(fact.scope.subscription) && fact.scope.subscription.length > 0 &&
    fact.scope.subscription.every((value) => typeof value === "string")
  );
}

/** Keeps publisher receipts distinct from source freshness and current readiness. */
export function FabricPublicationEvidence({ tableName, evidence }: {
  tableName: string;
  evidence?: PublicationEvidence;
}) {
  const supported = evidence?.contract === "fabric-product-publication/1" &&
    evidence.table_name === tableName && !!evidence.stages &&
    ["not_recorded", "recorded_publisher_outcome"].includes(evidence.evidence_mode) &&
    (evidence.publication_attempt === null || (
      !!evidence.publication_attempt &&
      ["running", "completed", "failed"].includes(evidence.publication_attempt.status) &&
      typeof evidence.publication_attempt.observed_at === "string"
    )) &&
    STAGES.every(([key]) => {
      const stage = evidence.stages[key];
      const supportedStage = key === "validated" || key === "persisted";
      return stage && typeof stage.reason_code === "string" &&
        validFact(stage.last_attempt) && validFact(stage.last_good) &&
        (supportedStage || (stage.last_attempt === null && stage.last_good === null)) &&
        (stage.status === "unknown" ? stage.last_attempt === null : (
          stage.status === "recorded" && supportedStage &&
          evidence.publication_attempt?.status === "completed" &&
          stage.evidence_mode === "recorded_publisher_outcome" &&
          !!stage.last_attempt && !!stage.last_good
        ));
    });

  return (
    <details>
      <summary>Inspect publication stages for {tableName}</summary>
      <section aria-label={`Publication stages: ${tableName}`}>
        <p>Recorded publisher completion is not current table inventory, source freshness, active Gold, or consumer readiness. Last-good facts may belong to an older generation.</p>
        {!evidence ? (
          <StatePanel title="Publication stages unavailable" message="This response does not supply product publication receipts." />
        ) : !supported ? (
          <StatePanel title="Unsupported publication evidence" message="Publication stages cannot be interpreted safely." tone="error" />
        ) : (
          <>
            <p>Publication attempt: {evidence.publication_attempt?.status || "Not recorded"}.
              {" "}Recorded at: {evidence.publication_attempt?.observed_at || "Unreported"}.</p>
            <dl>
              {STAGES.map(([key, label]) => {
                const stage = evidence.stages[key];
                return (
                  <div key={key}>
                    <dt>{label}</dt>
                    <dd>
                      {stage.status === "recorded" ? "Completion recorded" : "Unknown"}
                      {" · "}{stage.reason_code}
                      <p>Last attempted completion: {stage.last_attempt?.source_generation || "Not recorded"}.
                        {" "}Last-good source generation: {stage.last_good?.source_generation || "Not recorded"}.
                        {" "}Last good recorded at: {stage.last_good?.observed_at || "Unreported"}.</p>
                    </dd>
                  </div>
                );
              })}
            </dl>
          </>
        )}
      </section>
    </details>
  );
}
