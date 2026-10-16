"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import BlastRadiusGraph from "@/components/predeploy/BlastRadiusGraph";
import { NetworkReviewContext } from "@/components/predeploy/NetworkReviewContext";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { RiskGauge } from "@/components/ui/RiskGauge";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import type { StatusTone } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useApi } from "@/hooks/useApi";
import { buildPredeployCopilotContext } from "@/lib/copilot/page-adapters";
import { formatDateTime, titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { predeployApi } from "@/lib/services";
import { networkReviewBookmark } from "@/lib/network-review";
import type { NetworkReviewBookmark } from "@/lib/network-review";
import { scopeToSearchParams } from "@/lib/scope";
import { ARTIFACT_MAX_BYTES, inspectArtifact } from "@/lib/predeploy-intake";
import type { ArtifactInspection } from "@/lib/predeploy-intake";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import type { ChangeAssessment, Envelope, NetworkFindingReview } from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

const SOURCE_LABELS: Record<string, string> = {
  terraform_plan: "Terraform plan (JSON)",
  bicep_what_if: "Bicep what-if result",
  arm_diff: "ARM deployment diff",
  github_pull_request: "GitHub pull request",
  azure_devops: "Azure DevOps pull request",
};

const PLACEHOLDER = `{
  "resource_changes": [
    {
      "address": "azurerm_network_security_group.web",
      "type": "azurerm_network_security_group",
      "change": {
        "actions": ["update"],
        "before": { "id": "/subscriptions/.../networkSecurityGroups/web" },
        "after": { "id": "/subscriptions/.../networkSecurityGroups/web" }
      }
    }
  ]
}`;

/** A CAB verdict is a recommendation, so tone must not read as an authorization. */
function verdictTone(verdict: string): StatusTone {
  if (verdict === "approve") return "success";
  if (verdict === "approve_with_conditions") return "warning";
  return "critical";
}

/** Review a proposed change before deployment: reach, risk, and approval path. */
export default function PreDeploymentPage() {
  const { scope } = useScope();
  const params = useSearchParams();
  const query = params.toString();
  const bookmark = useMemo(() => networkReviewBookmark(new URLSearchParams(query)), [query]);
  return <PreDeploymentWorkspace key={`${scopeToSearchParams(scope)}|${query}`} bookmark={bookmark} />;
}

function PreDeploymentWorkspace({ bookmark }: { bookmark: NetworkReviewBookmark }) {
  const { scope } = useScope();
  const sources = useApi(() => predeployApi.sources(scope), [scope]);
  const history = useApi(() => predeployApi.assessments(scope), [scope]);

  const [source, setSource] = useState("terraform_plan");
  const [artifact, setArtifact] = useState("");
  const [inspection, setInspection] = useState<ArtifactInspection | null>(null);
  const [artifactReviewed, setArtifactReviewed] = useState(false);
  const [readingFile, setReadingFile] = useState(false);
  const [intakeError, setIntakeError] = useState<string | null>(null);
  const fileRead = useRef(0);
  const [result, setResult] = useState<Envelope<ChangeAssessment> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [networkReview, setNetworkReview] = useState<NetworkFindingReview | null>(null);
  const [attachNetwork, setAttachNetwork] = useState(false);
  const [reviewAttempt, setReviewAttempt] = useState(0);
  const submittingRequest = useRef<AbortController | null>(null);
  useEffect(() => () => { submittingRequest.current?.abort(); fileRead.current++; }, []);
  const linkedBlocked = bookmark.present && (!networkReview || !attachNetwork);

  const evidence = useMemo(() => result?.data.risk?.evidence ?? [], [result]);
  const { filteredRows: filteredEvidence, filters: evidenceFilters, resetFilters: resetEvidenceFilters } = useColumnFilters(evidence, [
    { id: "factor", label: "Factor", getValues: (item) => item.factor, formatOption: titleize },
    { id: "source", label: "Source", getValues: (item) => item.source },
  ]);
  const evidencePaging = useTablePagination(filteredEvidence);
  const effects = useMemo(() => result?.data.simulation?.effects ?? [], [result]);
  const { filteredRows: filteredEffects, filters: effectFilters, resetFilters: resetEffectFilters } = useColumnFilters(effects, [
    { id: "domain", label: "Domain", getValues: (effect) => effect.domain, formatOption: titleize },
    { id: "effect", label: "Effect", getValues: (effect) => effect.effect, formatOption: titleize },
    { id: "severity", label: "Severity", getValues: (effect) => effect.severity, formatOption: titleize },
    { id: "validation", label: "Validation", getValues: (effect) => effect.requires_validation ? "Required" : "Not required" },
  ]);
  const effectsPaging = useTablePagination(filteredEffects);
  const impactedResources = useMemo(
    () => result?.data.blast_radius?.impacted_resources ?? [],
    [result],
  );
  const { filteredRows: filteredImpactedResources, filters: impactedFilters, resetFilters: resetImpactedFilters } = useColumnFilters(impactedResources, [
    { id: "service", label: "Service", getValues: (resource) => resource.business_service || "Not mapped" },
    { id: "environment", label: "Environment", getValues: (resource) => resource.environment || "Unknown" },
    { id: "owner", label: "Owner", getValues: (resource) => resource.owner || "Unassigned" },
    { id: "relationship", label: "Relationship", getValues: (resource) => resource.depth === 0 ? "Directly changed" : "Dependent" },
  ]);
  const impactedPaging = useTablePagination(filteredImpactedResources);
  const historyRows = useMemo(() => history.data?.data ?? [], [history.data]);
  const { filteredRows: filteredHistoryRows, filters: historyFilters, resetFilters: resetHistoryFilters } = useColumnFilters(historyRows, [
    { id: "source", label: "Source", getValues: (row) => SOURCE_LABELS[row.source] ?? titleize(row.source) },
    { id: "risk", label: "Risk", getValues: (row) => row.risk_level, formatOption: titleize },
    { id: "verdict", label: "Verdict", getValues: (row) => row.verdict, formatOption: titleize },
  ]);
  const historyPaging = useTablePagination(filteredHistoryRows);

  function changeArtifact(text: string) {
    fileRead.current++;
    setReadingFile(false); setArtifact(text); setInspection(null);
    setArtifactReviewed(false); setIntakeError(null);
  }

  function inspect() {
    setArtifactReviewed(false); setIntakeError(null); setInspection(null);
    try { setInspection(inspectArtifact(source, artifact)); }
    catch (failure) { setIntakeError(failure instanceof Error ? failure.message : String(failure)); }
  }

  async function readFile(file: File | undefined) {
    if (!file) return;
    changeArtifact("");
    if (file.size > ARTIFACT_MAX_BYTES) { setIntakeError("Artifact exceeds the 2 MiB UTF-8 limit."); return; }
    const read = ++fileRead.current;
    setReadingFile(true);
    try {
      const bytes = await file.arrayBuffer();
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      if (fileRead.current === read) changeArtifact(text);
    } catch {
      if (fileRead.current === read) { setIntakeError("Could not read UTF-8 JSON. Choose a valid JSON file again."); setReadingFile(false); }
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submittingRequest.current) return;
    setError(null);
    if (linkedBlocked) { setError("Review and explicitly attach exact Network evidence, or remove the handoff before submitting a separate change."); return; }

    if (!inspection || !artifactReviewed || inspection.detectedSensitiveValues || readingFile) {
      setError("Inspect the artifact, redact detected sensitive values locally, then review it before assessment.");
      return;
    }

    const controller = new AbortController();
    submittingRequest.current = controller;
    setSubmitting(true); setResult(null);
    try {
      const response = await predeployApi.assess(source, inspection.payload, "", {
        scope, signal: controller.signal,
        ...(bookmark.reference && attachNetwork ? { networkReview: bookmark.reference } : {}),
      });
      if (!controller.signal.aborted) setResult(response);
    } catch (submitError: unknown) {
      if (!controller.signal.aborted) {
        setError(submitError instanceof Error ? submitError.message : String(submitError));
        setResult(null);
        if (bookmark.present) { setNetworkReview(null); setAttachNetwork(false); }
      }
    } finally {
      if (!controller.signal.aborted) { submittingRequest.current = null; setSubmitting(false); }
    }
  }

  const assessment = result?.data;
  const risk = assessment?.risk;
  const cab = assessment?.cab_recommendation;
  const blast = assessment?.blast_radius;
  const rows = history.data?.data ?? [];

  // Read-only contextual Copilot over the loaded assessment. Simulation, risk,
  // and CAB verdicts are predicted, never observed; nothing here deploys or
  // approves — governed remediation stays a separate workflow (D-03, D-06, D-10).
  const predeployCopilot = buildPredeployCopilotContext({
    scope,
    change: assessment
      ? {
          change_id: assessment.change.change_id,
          title: assessment.change.title,
          author: assessment.change.author,
          source: assessment.change.source,
          target_environment: assessment.change.target_environment,
          resource_change_count: assessment.change.effective_change_count,
        }
      : null,
    simulation: assessment?.simulation
      ? {
          highest_severity: assessment.simulation.highest_severity,
          simulated_domains: assessment.simulation.simulated_domains,
          by_severity: assessment.simulation.by_severity,
          effect_count: assessment.simulation.effects.length,
          confirmed_outcome: assessment.simulation.confirmed_outcome,
        }
      : null,
    risk: risk
      ? {
          score: risk.score,
          level: risk.level,
          confidence: risk.confidence,
          confirmed_cause: risk.confirmed_cause,
        }
      : null,
    cab: cab
      ? {
          verdict: cab.verdict,
          risk_level: cab.risk_level,
          required_approvals: cab.required_approvals,
          confirmed_cause: cab.confirmed_cause,
        }
      : null,
    impactedResources: impactedResources.map((resource) => ({
      resource_id: resource.resource_id,
      resource_name: resource.name,
      business_service: resource.business_service,
      environment: resource.environment,
      relationship: resource.depth === 0 ? "directly_changed" : resource.relationship,
    })),
    impactedTotalCount: blast?.total_impacted_count ?? impactedResources.length,
    impactedTruncated: blast?.truncated,
    available: Boolean(assessment),
    freshness: assessment ? "fresh" : "unavailable",
    observedAt: assessment?.assessed_at,
    unknowns: risk?.unknowns,
    evidence: result?.evidence ?? [],
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Change intelligence"
        title="What will this change affect?"
        description="Assess a proposed change before deployment: what it touches, which business services depend on it, and which evidence remains declared rather than observed."
        metadata={
          <>
            <span>{rows.length} recent assessments</span>
            <span>Assessed from declared configuration, not observed behaviour</span>
          </>
        }
        actions={
          <CopilotDrawerButton
            onClick={() => setCopilotOpen(true)}
            label="Ask Copilot about this assessment"
          />
        }
      />

      <CopilotInsights
        snapshot={predeployCopilot.snapshot}
        ready={!history.loading}
        requestedScope={predeployCopilot.requestedScope}
        contextLabel="Pre-deployment assessment"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      {bookmark.present && <div className="network-review-handoff">
        {bookmark.reference ? <NetworkReviewContext key={reviewAttempt} scope={scope} reference={bookmark.reference} onReady={setNetworkReview} />
          : <p role="alert">{bookmark.error}</p>}
        {bookmark.reference && error && !networkReview && <button type="button" className="button button-secondary"
          onClick={() => { setError(null); setReviewAttempt(current => current + 1); }}>Reload exact Network evidence before retrying</button>}
        <label><input type="checkbox" checked={attachNetwork} disabled={!networkReview || submitting}
          onChange={event => setAttachNetwork(event.target.checked)} /> Attach this exact Network finding context to my separately supplied artifact for advisory review.</label>
        <p>The artifact must be prepared and reviewed separately. This attachment does not establish that it addresses the finding.</p>
        <Link href={`/changes/predeploy?${scopeToSearchParams(scope)}`}>Remove Network context and review a separate change</Link>
      </div>}

      <form className="card predeploy-artifact" onSubmit={submit}>
        <div className="card-header">
          <h2>Submit a proposed change</h2>
          <p>Inspect a plan, what-if result, or pull request payload locally before sending it. Nothing is deployed.</p>
        </div>
        <div className="card-body form-grid">
          <label className="form-field">
            <span>Change source</span>
            <select className="form-control" value={source} disabled={submitting} onChange={(event) => {
              fileRead.current++; setReadingFile(false); setSource(event.target.value);
              setInspection(null); setArtifactReviewed(false); setIntakeError(null);
            }}>
              {(sources.data?.data.sources ?? Object.keys(SOURCE_LABELS)).map((option) => (
                <option key={option} value={option}>
                  {SOURCE_LABELS[option] ?? titleize(option)}
                </option>
              ))}
            </select>
          </label>
          <label className="form-field form-span">
            <span>Choose a JSON artifact (maximum 2 MiB)</span>
            <input className="form-control" type="file" accept=".json,application/json" disabled={submitting}
              onChange={event => { const file = event.target.files?.[0]; event.target.value = ""; void readFile(file); }} />
          </label>
          <label className="form-field form-span">
            <span>Change artifact (JSON)</span>
            <textarea
              className="form-control"
              value={artifact}
              onChange={(event) => changeArtifact(event.target.value)}
              disabled={submitting}
              placeholder={PLACEHOLDER}
              rows={10}
              spellCheck={false}
            />
          </label>
          <div className="predeploy-intake form-span">
            <p>Maximum 500 changes/files, 24 nesting levels and 50,000 values. Inspection recognizes common credential keys and Terraform sensitivity masks; it cannot detect every secret in prose, source code or arbitrary values. Review the full artifact yourself. File contents stay in this page until assessment; no raw artifact is retained in assessment history.</p>
            <button type="button" className="button button-secondary" onClick={inspect} disabled={submitting || readingFile || !artifact.trim()}>Inspect artifact locally</button>
            {readingFile && <p role="status">Reading local JSON file…</p>}
            {intakeError && <p role="alert">{intakeError}</p>}
            {inspection && <>
              <p role="status">{inspection.bytes.toLocaleString()} UTF-8 bytes inspected. {inspection.detectedSensitiveValues} detected sensitive values; {inspection.withheldValues} withheld values.</p>
              {inspection.detectedSensitiveValues > 0
                ? <><p>Assessment is blocked. Replace detected values with explicit redaction markers locally, inspect the changed artifact, and review it again. Redacted configuration remains unknown.</p>
                  <button type="button" className="button button-secondary" disabled={submitting} onClick={() => changeArtifact(inspection.redactedText)}>Redact detected values locally</button></>
                : <label><input type="checkbox" checked={artifactReviewed} disabled={submitting}
                    onChange={event => setArtifactReviewed(event.target.checked)} /> I reviewed this artifact and removed sensitive content. Redaction and declared configuration are not verified runtime evidence or deployment approval.</label>}
            </>}
          </div>
          <div className="form-actions">
            <button type="submit" className="button button-primary" disabled={submitting || readingFile || linkedBlocked || !inspection || !artifactReviewed || inspection.detectedSensitiveValues > 0}>
              {submitting ? "Assessing…" : "Assess impact"}
            </button>
          </div>
        </div>
      </form>

      {error && <StatePanel title="Assessment failed" message={error} tone="error" />}

      {assessment && risk && cab && blast && (
        <>
          {assessment.artifact && <div className="predeploy-intake">
            <h2>Submitted artifact provenance</h2>
            <p>SHA-256 <code>{assessment.artifact.sha256}</code></p>
            <p>{assessment.artifact.utf8_bytes.toLocaleString()} canonical UTF-8 bytes; {assessment.artifact.withheld_value_count} withheld values. {assessment.artifact.interpretation}</p>
          </div>}
          {assessment.network_review && <p className="network-review-result" role="status">
            Network finding {assessment.network_review.finding_id} retained with assessment {assessment.assessment_id}.
            {" "}Exact review digest: {assessment.network_review.reviewed_digest}. Advisory context only; the artifact-to-finding relationship is not verified.
          </p>}
          <EvidenceBar
            evidence={result?.evidence}
            knowledgeVersion={result?.knowledge_version}
            warnings={result?.warnings}
          />

          <div className="predeploy-summary">
            <section className="card">
              <div className="card-header">
                <h2>Risk score</h2>
              </div>
              <div className="card-body risk-gauge-body">
                <RiskGauge
                  score={risk.score}
                  detail={`${titleize(risk.confidence)} confidence · ${risk.evidence.length} evidence factor${risk.evidence.length === 1 ? "" : "s"}`}
                />
              </div>
            </section>

            <section className="metric-grid">
              <MetricCard
                label="CAB recommendation"
                value={titleize(cab.verdict)}
                detail={cab.summary}
                tone={cab.verdict === "approve" ? "success" : "warning"}
              />
              <MetricCard
                label="Impacted resources"
                value={blast.total_impacted_count}
                detail={`${blast.directly_changed_count} directly changed${blast.truncated ? " · traversal truncated" : ""}`}
              />
              <MetricCard
                label="Business services"
                value={blast.business_services.length}
                detail={blast.business_services.join(", ") || "No business service mapped in scope"}
              />
            </section>
          </div>

          <section className="card">
            <div className="card-header">
              <h2>Recommendation</h2>
              <StatusBadge label={titleize(cab.verdict)} tone={verdictTone(cab.verdict)} />
            </div>
            <div className="card-body">
              <p>{cab.summary}</p>
              {cab.conditions.length > 0 && (
                <>
                  <h3>Conditions</h3>
                  <ul>
                    {cab.conditions.map((condition) => (
                      <li key={condition}>{condition}</li>
                    ))}
                  </ul>
                </>
              )}
              {cab.required_approvals.length > 0 && (
                <>
                  <h3>Required approvals</h3>
                  <ul>
                    {cab.required_approvals.map((approval) => (
                      <li key={approval}>{titleize(approval)}</li>
                    ))}
                  </ul>
                </>
              )}
              {cab.triggers.length > 0 && (
                <>
                  <h3>Why this verdict</h3>
                  <ul>
                    {cab.triggers.map((trigger) => (
                      <li key={trigger.trigger}>
                        <strong>{titleize(trigger.trigger)}</strong> — {trigger.reason}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <p className="muted">{cab.interpretation}</p>
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h2>Risk evidence</h2>
              <p>{risk.justification}</p>
            </div>
            <div className="card-body">
              {risk.evidence.length === 0 ? (
                <p className="muted">No risk factors were identified from the submitted change.</p>
              ) : (
                <>
                <TableColumnFilters
                  filters={evidenceFilters}
                  onReset={resetEvidenceFilters}
                  resultCount={filteredEvidence.length}
                  totalCount={evidence.length}
                />
                <div className="table-scroll">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th scope="col">Factor</th>
                        <th scope="col">Observation</th>
                        <th scope="col">Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {evidencePaging.pageRows.map((item) => (
                        <tr key={`${item.factor}-${item.source}`}>
                          <td className="cell-nowrap">{titleize(item.factor)}</td>
                          <td>{item.observation}</td>
                          <td className="cell-nowrap">{item.source}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <TablePagination
                  total={evidencePaging.total}
                  pageRows={evidencePaging.pageRows.length}
                  page={evidencePaging.page}
                  onPageChange={evidencePaging.setPage}
                  pageSize={evidencePaging.pageSize}
                  onPageSizeChange={evidencePaging.setPageSize}
                  label="risk factors"
                />
                </>
              )}
              <p className="muted">{risk.interpretation}</p>
            </div>
          </section>

          {/* Unknowns are shown as prominently as findings: a low score derived
              from missing data must not read as evidence of safety. */}
          <section className="card">
            <div className="card-header">
              <h2>Confidence and unknowns</h2>
              <StatusBadge label={titleize(risk.confidence)} tone={statusTone(risk.confidence)} />
            </div>
            <div className="card-body">
              <p>{risk.confidence_rationale}</p>
              {risk.unknowns.length === 0 ? (
                <p className="muted">No gaps were declared for this assessment.</p>
              ) : (
                <ul>
                  {risk.unknowns.map((unknown) => (
                    <li key={unknown}>{unknown}</li>
                  ))}
                </ul>
              )}
              {assessment.scope_excluded_resource_count > 0 && (
                <p className="muted">
                  {assessment.scope_excluded_resource_count} discovered resource(s) were outside
                  your scope and were excluded from this assessment.
                </p>
              )}
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h2>Simulated effects</h2>
              <p>{assessment.simulation.interpretation}</p>
            </div>
            <div className="card-body">
              {assessment.simulation.effects.length === 0 ? (
                <p className="muted">
                  No effects were simulated for the domains present in this change.
                </p>
              ) : (
                <>
                <TableColumnFilters
                  filters={effectFilters}
                  onReset={resetEffectFilters}
                  resultCount={filteredEffects.length}
                  totalCount={effects.length}
                />
                <div className="table-scroll">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th scope="col">Domain</th>
                        <th scope="col">Effect</th>
                        <th scope="col">Severity</th>
                        <th scope="col">Detail</th>
                        <th scope="col">Validation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {effectsPaging.pageRows.map((effect) => (
                        <tr key={`${effect.address}-${effect.effect}`}>
                          <td className="cell-nowrap">{titleize(effect.domain)}</td>
                          <td className="cell-nowrap">{titleize(effect.effect)}</td>
                          <td>
                            <StatusBadge
                              label={titleize(effect.severity)}
                              tone={statusTone(effect.severity)}
                              compact
                            />
                          </td>
                          <td>{effect.detail}</td>
                          <td className="cell-nowrap">{effect.requires_validation ? "Required" : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <TablePagination
                  total={effectsPaging.total}
                  pageRows={effectsPaging.pageRows.length}
                  page={effectsPaging.page}
                  onPageChange={effectsPaging.setPage}
                  pageSize={effectsPaging.pageSize}
                  onPageSizeChange={effectsPaging.setPageSize}
                  label="effects"
                />
                </>
              )}
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <h2>Blast radius</h2>
              <p>{blast.interpretation}</p>
            </div>
            <div className="card-body">
              {blast.impacted_resources.length === 0 ? (
                <p className="muted">
                  No discovered resources in your scope depend on the changed resources.
                </p>
              ) : (
                <>
                  <BlastRadiusGraph resources={blast.impacted_resources} />
                  <h3 className="blast-radius-table-heading">Impacted resource detail</h3>
                  <TableColumnFilters
                    filters={impactedFilters}
                    onReset={resetImpactedFilters}
                    resultCount={filteredImpactedResources.length}
                    totalCount={impactedResources.length}
                  />
                  <div className="table-scroll">
                    <table className="operations-table">
                      <thead>
                        <tr>
                          <th scope="col">Resource</th>
                          <th scope="col">Business service</th>
                          <th scope="col">Environment</th>
                          <th scope="col">Owner</th>
                          <th scope="col">Relationship</th>
                        </tr>
                      </thead>
                      <tbody>
                        {impactedPaging.pageRows.map((resource) => (
                          <tr key={resource.resource_id}>
                            <td>
                              {resource.name || resource.resource_id}
                              {resource.depth === 0 && (
                                <StatusBadge label="Changed" tone="info" compact />
                              )}
                              {resource.name && (
                                <div className="table-secondary">
                                  <span className="resource-id-cell" title={resource.resource_id}>
                                    {resource.resource_id}
                                  </span>
                                </div>
                              )}
                            </td>
                            <td>{resource.business_service || "Not mapped"}</td>
                            <td>{resource.environment || "Unknown"}</td>
                            <td>{resource.owner || "Unassigned"}</td>
                            <td>
                              {resource.depth === 0
                                ? "Directly changed"
                                : `Depends on changed resource (depth ${resource.depth})`}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <TablePagination
                    total={impactedPaging.total}
                    pageRows={impactedPaging.pageRows.length}
                    page={impactedPaging.page}
                    onPageChange={impactedPaging.setPage}
                    pageSize={impactedPaging.pageSize}
                    onPageSizeChange={impactedPaging.setPageSize}
                    label="impacted resources"
                  />
                </>
              )}
            </div>
          </section>
        </>
      )}

      <section className="card">
        <div className="card-header">
          <h2>Recent assessments</h2>
          <p>Assessments visible within your current scope.</p>
        </div>
        <div className="card-body">
          {history.error ? (
            <StatePanel
              title="Assessment history is unavailable"
              message={history.error.message}
              tone="error"
            />
          ) : history.loading ? (
            <StatePanel
              title="Loading assessments"
              message="Retrieving recent assessments."
              tone="loading"
            />
          ) : rows.length === 0 ? (
            <StatePanel
              title="No assessments yet"
              message="Submit a change artifact above to assess its impact before deployment."
            />
          ) : (
            <>
            <TableColumnFilters
              filters={historyFilters}
              onReset={resetHistoryFilters}
              resultCount={filteredHistoryRows.length}
              totalCount={historyRows.length}
            />
            <div className="table-scroll">
              <table className="operations-table">
                <thead>
                  <tr>
                    <th scope="col">Change</th>
                    <th scope="col">Source</th>
                    <th scope="col">Risk</th>
                    <th scope="col">Verdict</th>
                    <th scope="col">Impacted</th>
                    <th scope="col">Assessed</th>
                  </tr>
                </thead>
                <tbody>
                  {historyPaging.pageRows.map((row) => (
                    <tr key={row.assessment_id}>
                      <td>{row.title || row.change_id}</td>
                      <td>{SOURCE_LABELS[row.source] ?? titleize(row.source)}</td>
                      <td>
                        <StatusBadge
                          label={`${row.risk_score} ${titleize(row.risk_level)}`}
                          tone={statusTone(row.risk_level)}
                          compact
                        />
                      </td>
                      <td>
                        <StatusBadge
                          label={titleize(row.verdict)}
                          tone={verdictTone(row.verdict)}
                          compact
                        />
                      </td>
                      <td>{row.total_impacted_count}</td>
                      <td>{formatDateTime(row.assessed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <TablePagination
              total={historyPaging.total}
              pageRows={historyPaging.pageRows.length}
              page={historyPaging.page}
              onPageChange={historyPaging.setPage}
              pageSize={historyPaging.pageSize}
              onPageSizeChange={historyPaging.setPageSize}
              label="assessments"
            />
            </>
          )}
        </div>
      </section>

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Pre-deployment assessment"
        requestedScope={predeployCopilot.requestedScope}
        snapshot={predeployCopilot.snapshot}
        starterQuestions={predeployCopilot.starterQuestions}
      />
    </div>
  );
}
