"use client";

import { useMemo, useState } from "react";

import BlastRadiusGraph from "@/components/predeploy/BlastRadiusGraph";
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
import { formatDateTime, titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { predeployApi } from "@/lib/services";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import type { ChangeAssessment, Envelope } from "@/lib/types";

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
  const sources = useApi(() => predeployApi.sources(), []);
  const history = useApi(() => predeployApi.assessments(scope), [scope]);

  const [source, setSource] = useState("terraform_plan");
  const [artifact, setArtifact] = useState("");
  const [result, setResult] = useState<Envelope<ChangeAssessment> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
  const historyRows = useMemo(() => history.data?.data.assessments ?? [], [history.data]);
  const { filteredRows: filteredHistoryRows, filters: historyFilters, resetFilters: resetHistoryFilters } = useColumnFilters(historyRows, [
    { id: "source", label: "Source", getValues: (row) => SOURCE_LABELS[row.source] ?? titleize(row.source) },
    { id: "risk", label: "Risk", getValues: (row) => row.risk_level, formatOption: titleize },
    { id: "verdict", label: "Verdict", getValues: (row) => row.verdict, formatOption: titleize },
  ]);
  const historyPaging = useTablePagination(filteredHistoryRows);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(artifact) as Record<string, unknown>;
    } catch {
      // Parsed locally so a malformed paste is corrected here rather than
      // coming back as an opaque server-side rejection.
      setError("The artifact is not valid JSON. Paste the raw plan or what-if output.");
      return;
    }

    setSubmitting(true);
    try {
      setResult(await predeployApi.assess(source, payload));
    } catch (submitError: unknown) {
      setError(submitError instanceof Error ? submitError.message : String(submitError));
      setResult(null);
    } finally {
      setSubmitting(false);
    }
  }

  const assessment = result?.data;
  const risk = assessment?.risk;
  const cab = assessment?.cab_recommendation;
  const blast = assessment?.blast_radius;
  const rows = history.data?.data.assessments ?? [];

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
      />

      <form className="card" onSubmit={submit}>
        <div className="card-header">
          <h2>Submit a proposed change</h2>
          <p>Paste a plan, what-if result, or pull request payload. Nothing is deployed.</p>
        </div>
        <div className="card-body form-grid">
          <label>
            <span>Change source</span>
            <select value={source} onChange={(event) => setSource(event.target.value)}>
              {(sources.data?.data.sources ?? Object.keys(SOURCE_LABELS)).map((option) => (
                <option key={option} value={option}>
                  {SOURCE_LABELS[option] ?? titleize(option)}
                </option>
              ))}
            </select>
          </label>
          <label className="form-span">
            <span>Change artifact (JSON)</span>
            <textarea
              value={artifact}
              onChange={(event) => setArtifact(event.target.value)}
              placeholder={PLACEHOLDER}
              rows={10}
              spellCheck={false}
            />
          </label>
          <div className="form-actions">
            <button type="submit" disabled={submitting || artifact.trim() === ""}>
              {submitting ? "Assessing…" : "Assess impact"}
            </button>
          </div>
        </div>
      </form>

      {error && <StatePanel title="Assessment failed" message={error} tone="error" />}

      {assessment && risk && cab && blast && (
        <>
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
                          <td>{titleize(item.factor)}</td>
                          <td>{item.observation}</td>
                          <td>{item.source}</td>
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
                          <td>{titleize(effect.domain)}</td>
                          <td>{titleize(effect.effect)}</td>
                          <td>
                            <StatusBadge
                              label={titleize(effect.severity)}
                              tone={statusTone(effect.severity)}
                              compact
                            />
                          </td>
                          <td>{effect.detail}</td>
                          <td>{effect.requires_validation ? "Required" : "—"}</td>
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
    </div>
  );
}
