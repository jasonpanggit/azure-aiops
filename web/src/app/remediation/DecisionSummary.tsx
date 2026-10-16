import { titleize } from "@/lib/format";
import type { RemediationWorkflow } from "@/lib/services";
import type { WorkflowStep } from "./blockers";

interface Props {
  workflow: RemediationWorkflow;
  canRun: boolean;
  businessReady: boolean;
  pending: boolean;
  onNavigate: (step: WorkflowStep) => void;
}

/** Read-time context and navigation, never a new approval or execution gate. */
export function DecisionSummary({ workflow, canRun, businessReady, pending, onNavigate }: Props) {
  const snapshot = workflow.preview?.execution_snapshot;
  const execution = workflow.execution;
  const blockers = workflow.blockers.filter(row => row.code !== "already_succeeded");
  const next: { label: string; step: WorkflowStep } = !workflow.action.executable
    ? { label: "Review with the resource owner", step: "review" }
    : execution
      ? { label: "Inspect recorded execution", step: "verify" }
      : !snapshot
        ? { label: "Resolve the executable preview", step: "review" }
        : !businessReady
          ? { label: "Resolve decision evidence", step: "review" }
          : !workflow.approval.current
            ? { label: workflow.approval.can_approve ? "Review approval requirements" : "Ask an authorized approver", step: "approve" }
            : !canRun
              ? { label: "Resolve execution eligibility", step: "review" }
              : { label: workflow.action.can_operate ? "Review the approved operation" : "Ask an authorized operator", step: "run" };
  const approval = workflow.approval.current
    ? "Reported current for this preview"
    : workflow.approval.status === "none"
      ? "No approval recorded"
      : `Not current: ${titleize(workflow.approval.status)}`;

  return <section className="remediation-decision-summary" aria-labelledby="remediation-decision-summary-title" aria-busy={pending}>
    <h2 id="remediation-decision-summary-title">Decision summary</h2>
    <dl className="remediation-decision-facts">
      <div><dt>Selected operation</dt><dd>{snapshot?.operation ? titleize(snapshot.operation) : "No executable operation in this preview"}</dd></div>
      <div><dt>Approval at last read</dt><dd>{approval}. {workflow.approval.requirements.filter(row => row.satisfied).length}/{workflow.approval.requirements.length} required roles satisfied.</dd></div>
      <div className="remediation-decision-target"><dt>Exact preview target</dt><dd><code>{snapshot?.target_id || "No executable target in this preview"}</code></dd></div>
    </dl>
    {pending ? <p role="status">Resolve the pending request or update selection before starting another approval or execution action.</p> : <p>
      Next permitted step: <button className="button" type="button" onClick={() => onNavigate(next.step)}>{next.label}</button>
    </p>}
    <div className="remediation-decision-disclosures">
      <details>
        <summary>Preview binding{snapshot ? `: ${snapshot.patch_ids.length} selected ${snapshot.patch_ids.length === 1 ? "update" : "updates"}` : " unavailable"}</summary>
        <dl>
          <div><dt>Plan</dt><dd><code>{workflow.plan.plan_id}</code></dd></div>
          <div><dt>Action version</dt><dd><code>{snapshot?.action_version || workflow.plan.action_version || "Not reported"}</code></dd></div>
          <div><dt>Snapshot hash</dt><dd><code>{snapshot?.snapshot_hash || "Not reported"}</code></dd></div>
        </dl>
        {snapshot?.patch_ids.length ? <ul>{snapshot.patch_ids.map(id => <li key={id}><code>{id}</code></li>)}</ul> : <p>No update identifiers in this preview. Configuration actions may have none.</p>}
      </details>
      <details>
        <summary>{blockers.length} reported blockers{workflow.plan.ineligibility_reason ? "; eligibility reason recorded" : ""}</summary>
        {blockers.length ? <ul>{blockers.map((row, index) => <li key={`${row.code}-${row.step}-${index}`}>
          {titleize(row.code)} · {titleize(row.step)}: {row.next_action || row.message}
        </li>)}</ul> : <p>No blockers reported in this response; this is not execution authorization.</p>}
        {workflow.plan.ineligibility_reason && <p>Plan eligibility: <code>{workflow.plan.ineligibility_reason}</code></p>}
        {workflow.approval.stale_reasons.length > 0 && <p>Approval mismatch: {workflow.approval.stale_reasons.map(titleize).join(", ")}.</p>}
        {!workflow.action.can_operate && <p>Operator capability: {workflow.action.operate_ineligible_reason || "Not granted for this plan"}.</p>}
        {!workflow.approval.can_approve && <p>Approver capability: {workflow.approval.approve_ineligible_reason || "Not granted for this plan"}.</p>}
      </details>
      {execution && <details>
        <summary>Recorded execution binding: {titleize(execution.status)}</summary>
        <p>This immutable execution is separate from the current preview; its recorded target or version may differ. Provider success is not proof of refreshed estate evidence.</p>
        <dl>
          <div><dt>Execution</dt><dd><code>{execution.execution_id}</code></dd></div>
          <div><dt>Recorded operation</dt><dd>{execution.execution_snapshot?.operation || "Not reported"}</dd></div>
          <div><dt>Recorded target</dt><dd><code>{execution.execution_snapshot?.target_id || "Not reported"}</code></dd></div>
          <div><dt>Recorded snapshot</dt><dd><code>{execution.execution_snapshot?.snapshot_hash || "Not reported"}</code></dd></div>
        </dl>
      </details>}
    </div>
    <p className="remediation-decision-boundary">Navigation only. The server rechecks current evidence, scope, approval and execution eligibility before any governed action.</p>
  </section>;
}
