"use client";

import { useMemo, useState } from "react";
import Link from "next/link";

import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useApi } from "@/hooks/useApi";
import { buildIdentityCopilotContext } from "@/lib/copilot/page-adapters";
import { formatDateTime, titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { governanceApi } from "@/lib/services";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

const LEAST_PRIVILEGE_REASON_LABELS: Record<string, string> = {
  broad_management_group_scope: "Management-group scope",
  broad_subscription_scope: "Subscription-wide scope",
  elevated_role_or_action_heuristic: "Elevated role/action signal",
  wildcard_permission_patterns: "Wildcard permission pattern",
  assignment_unchanged_past_review_window: "Change age exceeds review window",
  assignment_change_age_unknown: "Change age unknown",
  assignment_scope_unknown: "Assignment scope unknown",
  role_definition_or_permissions_unresolved: "Role definition incomplete",
};

function rotationTone(status: string): "critical" | "warning" | "success" | "neutral" {
  if (status === "expired") return "critical";
  if (status === "expiring_soon") return "warning";
  if (status === "healthy") return "success";
  return "neutral";
}

/** Blast radius is a count per scope breadth; render it compactly. */
function blastRadius(radius: Record<string, number>): string {
  const entries = Object.entries(radius ?? {});
  if (entries.length === 0) return "Scope breadth unreported";
  return entries.map(([key, value]) => `${value} ${titleize(key).toLowerCase()}`).join(", ");
}

function permissionGroupLabel(label: string, count: number): string {
  return `${label} (${count})`;
}

export default function IdentityPage() {
  const { scope } = useScope();
  return <IdentityWorkspace key={scopeToSearchParams(scope).toString()} scope={scope} />;
}

function IdentityWorkspace({ scope }: { scope: ScopeSelection }) {
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [leastPrivilegePage, setLeastPrivilegePage] = useState(0);
  const [leastPrivilegePageSize, setLeastPrivilegePageSize] = useState(20);

  const summary = useApi(() => governanceApi.identitySummary(scope), [scope]);
  const principals = useApi(() => governanceApi.identityPrincipals(scope), [scope]);
  const owners = useApi(() => governanceApi.subscriptionOwners(scope), [scope]);
  const stale = useApi(() => governanceApi.staleAccess(scope), [scope]);
  const nonHuman = useApi(() => governanceApi.nonHumanIdentities(scope), [scope]);
  const spn = useApi(() => governanceApi.spnCredentials(scope), [scope]);
  const leastPrivilege = useApi(
    () => governanceApi.identityLeastPrivilege(
      scope,
      leastPrivilegePage * leastPrivilegePageSize,
      leastPrivilegePageSize,
    ),
    [scope, leastPrivilegePage, leastPrivilegePageSize],
  );

  const principalRows = useMemo(() => principals.data?.data.principals ?? [], [principals.data]);
  const ownerRows = useMemo(() => owners.data?.data.owners ?? [], [owners.data]);
  const staleRows = useMemo(() => stale.data?.data.assignments ?? [], [stale.data]);
  const nonHumanRows = useMemo(() => nonHuman.data?.data.identities ?? [], [nonHuman.data]);
  const spnRows = useMemo(() => spn.data?.data.credentials ?? [], [spn.data]);

  const { filteredRows: filteredPrincipals, filters: principalFilters, resetFilters: resetPrincipalFilters } = useColumnFilters(principalRows, [
    { id: "type", label: "Type", getValues: (row) => row.principal_type || "unknown", formatOption: titleize },
    { id: "scope", label: "Widest scope", getValues: (row) => row.widest_scope_breadth || "unknown", formatOption: titleize },
    { id: "status", label: "Status", getValues: (row) => [row.privileged ? "privileged signal" : row.risk_evidence?.classification === "no_classified_signal" ? "no classified signal" : "incomplete classification", row.stale ? "review overdue" : "", (row.risk_evidence?.unknown_age_assignments ?? 1) > 0 ? "unknown change age" : ""] },
  ]);
  const { filteredRows: filteredOwners, filters: ownerFilters, resetFilters: resetOwnerFilters } = useColumnFilters(ownerRows, [
    { id: "type", label: "Type", getValues: (row) => row.principal_type || "unknown", formatOption: titleize },
    { id: "status", label: "Status", getValues: (row) => row.stale ? "review overdue" : row.age_state === "within_review_window" ? "within review window" : "unknown change age" },
  ]);
  const { filteredRows: filteredStale, filters: staleFilters, resetFilters: resetStaleFilters } = useColumnFilters(staleRows, [
    { id: "role", label: "Role", getValues: (row) => row.role || "Unresolved" },
    { id: "status", label: "Status", getValues: (row) => row.privileged ? "privileged signal" : "no classified signal" },
  ]);
  const { filteredRows: filteredNonHuman, filters: nonHumanFilters, resetFilters: resetNonHumanFilters } = useColumnFilters(nonHumanRows, [
    { id: "type", label: "Type", getValues: (row) => row.principal_type || "unknown", formatOption: titleize },
  ]);
  const { filteredRows: filteredSpn, filters: spnFilters, resetFilters: resetSpnFilters } = useColumnFilters(spnRows, [
    { id: "rotation", label: "Rotation", getValues: (row) => row.rotation_status, formatOption: titleize },
    { id: "issues", label: "Issues", getValues: (row) => row.issues?.length ? "Has issues" : "No issues" },
  ]);

  const principalsPaging = useTablePagination(filteredPrincipals);
  const ownersPaging = useTablePagination(filteredOwners);
  const stalePaging = useTablePagination(filteredStale);
  const nonHumanPaging = useTablePagination(filteredNonHuman);
  const spnPaging = useTablePagination(filteredSpn);

  const sources = [summary, principals, owners, stale, nonHuman, spn];
  const loading = sources.some(source => source.loading);
  const error = sources.find(source => source.error)?.error;

  const totals = summary.data?.data;
  const spnSummary = spn.data?.data.summary;

  // The API warns when identity data has never synced. Surfacing that is
  // essential: an empty table must never read as "no privileged access".
  const warnings = Array.from(new Set([
    ...sources.flatMap(source => source.data?.warnings ?? []),
    ...(leastPrivilege.data?.warnings ?? []),
    ...(leastPrivilege.error
      ? [`Least-privilege review is unavailable: ${leastPrivilege.error.message ?? "No response was returned."}`]
      : []),
  ]));
  const identityEvidence = [
    ...sources.flatMap(source => source.data?.evidence ?? []),
    ...(leastPrivilege.data?.evidence ?? []),
  ];

  // Read-only contextual Copilot over already-loaded, server-authorized
  // identity evidence. Principals stay scope-safe domain identities; no
  // mutation path is exposed (D-03, D-05, D-06, D-08, D-09).
  const identityAvailable = !error && sources.every(source => Boolean(source.data));
  const completeEvidenceAvailable = identityAvailable && Boolean(leastPrivilege.data);
  const identityCopilot = buildIdentityCopilotContext({
    scope,
    summary: totals
      ? {
          principal_count: totals.principal_count,
          privileged_principal_count: totals.privileged_principal_count,
          stale_assignment_count: totals.stale_assignment_count,
          non_human_principal_count: totals.non_human_principal_count,
          assignment_count: totals.assignment_count,
        }
      : null,
    principals: principalRows.map((principal) => ({
      principal_id: principal.principal_id,
      principal_type: principal.principal_type,
      privileged: principal.privileged,
      stale: principal.stale,
      widest_scope_breadth: principal.widest_scope_breadth,
      assignment_count: principal.assignment_count,
      roles: principal.roles,
      risk_classification: principal.risk_evidence?.classification,
      unresolved_role_assignments: principal.risk_evidence?.unresolved_role_assignments,
      unknown_age_assignments: principal.risk_evidence?.unknown_age_assignments,
    })),
    principalsTotalCount: principals.data?.data.count ?? principalRows.length,
    owners: ownerRows.map((owner) => ({
      principal_id: owner.principal_id,
      principal_type: owner.principal_type,
      subscription_id: owner.subscription_id,
      scope_breadth: owner.scope_breadth,
      stale: owner.stale,
      age_state: owner.age_state,
    })),
    ownersTotalCount: owners.data?.data.count ?? ownerRows.length,
    staleAccess: staleRows.map((assignment) => ({
      assignment_id: assignment.assignment_id,
      principal_id: assignment.principal_id,
      role: assignment.role,
      privileged: assignment.privileged,
    })),
    staleTotalCount: stale.data?.data.count ?? staleRows.length,
    spnCredentials: spnRows.map((credential) => ({
      credential_id: credential.credential_id,
      connection_name: credential.connection_name,
      rotation_status: credential.rotation_status,
      days_to_expiry: credential.days_to_expiry,
      issues_count: credential.issues?.length ?? 0,
    })),
    spnTotalCount: spn.data?.data.count ?? spnRows.length,
    available: completeEvidenceAvailable,
    freshness: !identityAvailable ? "unavailable" : identityEvidence.some(item => item.freshness === "stale") ? "stale"
      : warnings.length === 0 && completeEvidenceAvailable && [...sources, leastPrivilege].every(source => Boolean(source.data?.evidence.length) && source.data?.evidence.every(item => item.freshness === "fresh")) ? "fresh" : "partial",
    evidence: identityEvidence,
  });

  return (
    <div className="page-container operational-page identity-workspace">
      <PageHeader
        eyebrow="Access governance"
        title="Who has access, and how wide is it?"
        description="Review observed RBAC assignments, subscription owners, non-human identities, and credential coverage within the authorized scope."
        actions={
          <CopilotDrawerButton
            onClick={() => setCopilotOpen(true)}
            label="Ask Copilot about identity access"
          />
        }
        metadata={
          <>
            <span>Derived from observed RBAC assignments</span>
            <span>Scope-limited to your subscriptions</span>
          </>
        }
      />

      {!error && !loading && (
        <nav className="section-nav" aria-label="Identity sections">
          <a href="#identity-overview">Overview</a>
          <a href="#identity-principals">Principals</a>
          <a href="#identity-least-privilege">Least-privilege review</a>
          <a href="#identity-owners">Subscription owners</a>
          <a href="#identity-stale">Stale access</a>
          <a href="#identity-non-human">Non-human identities</a>
          <a href="#identity-credentials">Credentials</a>
        </nav>
      )}

      <EvidenceBar
        evidence={identityEvidence}
        knowledgeVersion={summary.data?.knowledge_version}
        warnings={warnings}
      />

      {error ? (
        <StatePanel
          title="Identity intelligence is unavailable"
          message={
            error.message ??
            "No governance response was returned. Sync a subscription connection first."
          }
          tone="error"
          action={<button type="button" className="button" onClick={() => sources.filter(source => source.error).forEach(source => source.refetch())}>Retry failed identity reads</button>}
        />
      ) : loading ? (
        <StatePanel
          title="Reading access assignments"
          message="Resolving role assignments, definitions, and credential posture."
          tone="loading"
        />
      ) : (
        <>
          <div id="identity-overview" className="metric-grid" role="region" aria-label="Access overview">
            <MetricCard
              label="Principals with access"
              value={totals?.principal_count ?? 0}
              detail={`${totals?.assignment_count ?? 0} role assignments observed`}
            />
            <MetricCard
              label="Classified privileged signals"
              value={totals?.privileged_principal_count ?? 0}
              detail="Role-name/action heuristic, not effective access"
              tone={(totals?.privileged_principal_count ?? 0) > 0 ? "critical" : "default"}
            />
            <MetricCard
              label="Stale assignments"
              value={totals?.stale_assignment_count ?? 0}
              detail={`Unchanged for over ${totals?.stale_threshold_days ?? 90} days`}
              tone={(totals?.stale_assignment_count ?? 0) > 0 ? "warning" : "default"}
            />
            <MetricCard
              label="Non-human identities"
              value={totals?.non_human_principal_count ?? 0}
              detail="Service principals and managed identities"
            />
          </div>

          <section id="identity-principals" className="card" aria-labelledby="identity-principals-heading">
            <div className="card-header">
              <div>
                <h2 id="identity-principals-heading">Principals and observed grant breadth</h2>
                <p>
                  Counts describe recorded assignments by scope breadth, not distinct
                  reachable resources or a verified compromise blast radius. Group
                  membership, deny assignments, PIM eligibility, conditions and
                  data-plane permissions are not evaluated as effective access.
                </p>
              </div>
            </div>
            <div className="card-body">
              {(principals.data?.data.principals.length ?? 0) === 0 ? (
                <StatePanel
                  title="No principals observed"
                  message="No role assignment has been synced for the subscriptions in scope. This is not evidence that no access exists."
                />
              ) : (
                <>
                <TableColumnFilters
                  filters={principalFilters}
                  onReset={resetPrincipalFilters}
                  resultCount={filteredPrincipals.length}
                  totalCount={principalRows.length}
                />
                <p className="identity-table-hint" id="identity-table-hint">Scroll horizontally to review every assignment column.</p>
                <div className="table-scroll identity-principals-table" role="region" aria-label="Observed principal assignments" aria-describedby="identity-table-hint" tabIndex={0}>
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Principal</th>
                        <th>Type</th>
                        <th>Roles</th>
                        <th>Widest scope</th>
                        <th>Grant breadth</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {principalsPaging.pageRows.map((row) => (
                        <tr key={row.principal_id}>
                          <td>
                            <Link
                              className="table-primary-link"
                              href={`/search?q=${encodeURIComponent(row.principal_id)}`}
                            >
                              <span className="table-wrap resource-id-cell">{row.principal_id}</span>
                            </Link>
                            <div className="table-secondary">
                              {row.assignment_count} assignment
                              {row.assignment_count === 1 ? "" : "s"}
                            </div>
                          </td>
                          <td className="cell-nowrap">{titleize(row.principal_type || "unknown")}</td>
                          <td>
                            <div className="table-wrap">
                              {(row.roles?.length ?? 0) > 0 ? row.roles.join(", ") : "Unresolved"}
                            </div>
                          </td>
                          <td>
                            {titleize(row.widest_scope_breadth || "unknown")}
                            <div className="table-secondary">
                              <span className="resource-id-cell" title={row.widest_scope}>{row.widest_scope}</span>
                            </div>
                          </td>
                          <td>{blastRadius(row.blast_radius)}</td>
                          <td>
                            {row.privileged && (
                              <StatusBadge label="privileged signal" tone="critical" compact />
                            )}
                            {row.stale && (
                              <StatusBadge label="review overdue" tone="warning" compact />
                            )}
                            {!row.privileged && (
                              <StatusBadge label={row.risk_evidence?.classification === "no_classified_signal" ? "no classified signal" : "incomplete classification"} tone="neutral" compact />
                            )}
                            <div className="table-secondary">
                              {row.risk_evidence
                                ? `${row.risk_evidence.unresolved_role_assignments} unresolved role/action records; ${row.risk_evidence.unknown_age_assignments} unknown change ages`
                                : "Classification coverage and change ages unreported"}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
              )}
              <TablePagination
                total={principalsPaging.total}
                pageRows={principalsPaging.pageRows.length}
                page={principalsPaging.page}
                onPageChange={principalsPaging.setPage}
                pageSize={principalsPaging.pageSize}
                onPageSizeChange={principalsPaging.setPageSize}
                label="principals"
              />
            </div>
          </section>

          <section id="identity-least-privilege" className="card" aria-labelledby="identity-least-privilege-heading">
            <div className="card-header">
              <div>
                <h2 id="identity-least-privilege-heading">Least-privilege review candidates</h2>
                <p>
                  Advisory queue based on observed role definitions, scope breadth,
                  and assignment change age. It does not calculate effective access
                  or recommend an automatic role replacement.
                </p>
              </div>
            </div>
            <div className="card-body">
              {leastPrivilege.error ? (
                <StatePanel
                  title="Least-privilege review is unavailable"
                  message={leastPrivilege.error.message ?? "No response was returned."}
                  tone="error"
                  action={<button type="button" className="button" onClick={leastPrivilege.refetch}>Retry review candidates</button>}
                />
              ) : leastPrivilege.loading ? (
                <StatePanel
                  title="Preparing review candidates"
                  message="Comparing observed role-definition patterns and grant scopes."
                  tone="loading"
                />
              ) : leastPrivilege.data?.data.candidate_count === 0 ? (
                <StatePanel
                  title="No observed review candidates"
                  message="No assignments matched these advisory signals. This is not a finding that effective access is narrow or fully known."
                />
              ) : leastPrivilege.data ? (
                <>
                  <p className="identity-review-boundary">
                    Effective access remains not evaluated. Group membership, deny
                    assignments, PIM eligibility, and role-condition evaluation were
                    not collected; condition text is shown only as present or absent.
                  </p>
                  <p className="identity-table-hint" id="identity-review-table-hint">
                    Scroll horizontally to inspect each grant and its permission patterns.
                  </p>
                  <div
                    className="table-scroll identity-review-table"
                    role="region"
                    aria-label="Least-privilege review candidates"
                    aria-describedby="identity-review-table-hint"
                    tabIndex={0}
                  >
                    <table className="operations-table">
                      <thead>
                        <tr>
                          <th>Principal</th>
                          <th>Observed role</th>
                          <th>Observed scope</th>
                          <th>Permission patterns</th>
                          <th>Review signals</th>
                        </tr>
                      </thead>
                      <tbody>
                        {leastPrivilege.data.data.candidates.map((candidate) => (
                          <tr key={`${candidate.assignment_id}:${candidate.principal_id}`}>
                            <td>
                              <Link
                                className="table-primary-link"
                                href={`/search?q=${encodeURIComponent(candidate.principal_id)}`}
                              >
                                <span className="table-wrap resource-id-cell">{candidate.principal_id}</span>
                              </Link>
                              <div className="table-secondary">{titleize(candidate.principal_type)}</div>
                            </td>
                            <td>
                              <strong>{candidate.role}</strong>
                              <div className="table-secondary resource-id-cell">{candidate.role_definition_id}</div>
                              <div className="table-secondary">
                                Condition {candidate.condition_state === "present"
                                  ? "observed"
                                  : candidate.condition_state === "not_present"
                                    ? "not present"
                                    : "not collected"}
                              </div>
                            </td>
                            <td>
                              {titleize(candidate.scope_breadth)}
                              <div className="table-secondary resource-id-cell">{candidate.scope}</div>
                            </td>
                            <td>
                              <details className="identity-review-details">
                                <summary>
                                  Inspect {candidate.permission_profile.actions.count
                                    + candidate.permission_profile.data_actions.count} allow patterns
                                </summary>
                                <dl>
                                  {([
                                    ["Actions", candidate.permission_profile.actions],
                                    ["NotActions / exclusions", candidate.permission_profile.not_actions],
                                    ["DataActions", candidate.permission_profile.data_actions],
                                    ["NotDataActions / exclusions", candidate.permission_profile.not_data_actions],
                                  ] as const).map(([label, group]) => (
                                    <div key={label}>
                                      <dt>{permissionGroupLabel(label, group.count)}</dt>
                                      <dd>
                                        {group.count === 0 ? "No patterns recorded" : (
                                          <ul>
                                            {group.patterns.map((pattern) => <li key={pattern}><code>{pattern}</code></li>)}
                                            {group.truncated && <li>Additional patterns not shown</li>}
                                          </ul>
                                        )}
                                      </dd>
                                    </div>
                                  ))}
                                </dl>
                                <p>{candidate.recommendation}</p>
                              </details>
                              <div className="table-secondary">
                                {candidate.permission_profile.wildcard_pattern_count} wildcard patterns
                              </div>
                            </td>
                            <td>
                              <div className="identity-review-reasons">
                                {candidate.review_reasons.map((reason) => (
                                  <StatusBadge
                                    key={reason}
                                    label={LEAST_PRIVILEGE_REASON_LABELS[reason] ?? titleize(reason)}
                                    tone={reason.includes("elevated")
                                      ? "critical"
                                      : reason.includes("unknown") || reason.includes("unresolved")
                                        ? "warning"
                                        : "neutral"}
                                    compact
                                  />
                                ))}
                              </div>
                              <div className="table-secondary">
                                Change age: {titleize(candidate.age_state)}
                                {candidate.last_changed && ` · ${formatDateTime(candidate.last_changed)}`}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <TablePagination
                    total={leastPrivilege.data.data.candidate_count}
                    pageRows={leastPrivilege.data.data.candidates.length}
                    page={leastPrivilegePage}
                    onPageChange={setLeastPrivilegePage}
                    pageSize={leastPrivilegePageSize}
                    onPageSizeChange={(size) => {
                      setLeastPrivilegePageSize(size);
                      setLeastPrivilegePage(0);
                    }}
                    label="review candidates"
                  />
                </>
              ) : null}
            </div>
          </section>

          <section id="identity-owners" className="card" aria-labelledby="identity-owners-heading">
            <div className="card-header">
              <div>
                <h2 id="identity-owners-heading">Subscription owners</h2>
                <p>Principals holding owner rights over a whole subscription.</p>
              </div>
            </div>
            <div className="card-body">
              {owners.error ? (
                <StatePanel title="Subscription owners are unavailable" message={owners.error.message} tone="error"
                  action={<button className="button button-secondary" type="button" onClick={owners.refetch}>Retry subscription owners</button>} />
              ) : owners.loading ? (
                <StatePanel title="Reading subscription owners" message="Resolving observed owner-scoped assignments." tone="loading" />
              ) : (owners.data?.data.owners.length ?? 0) === 0 ? (
                <StatePanel
                  title="No subscription owners observed"
                  message="No owner-scoped assignment was found in the synced data for this scope."
                />
              ) : (
                <>
                <TableColumnFilters
                  filters={ownerFilters}
                  onReset={resetOwnerFilters}
                  resultCount={filteredOwners.length}
                  totalCount={ownerRows.length}
                />
                <div className="table-scroll" tabIndex={0} role="region" aria-label="Subscription owner records">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Principal</th>
                        <th>Type</th>
                        <th>Subscription</th>
                        <th>Assigned</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ownersPaging.pageRows.map((row, index) => (
                        <tr key={`${row.principal_id}-${row.scope}-${index}`}>
                          <td>
                            <Link
                              className="table-primary-link"
                              href={`/search?q=${encodeURIComponent(row.principal_id)}`}
                            >
                              <span className="table-wrap resource-id-cell">{row.principal_id}</span>
                            </Link>
                          </td>
                          <td className="cell-nowrap">{titleize(row.principal_type || "unknown")}</td>
                          <td>
                            <Link
                              className="table-primary-link"
                              href={`/search?q=${encodeURIComponent(row.subscription_id)}`}
                            >
                              <span className="table-wrap resource-id-cell">{row.subscription_id}</span>
                            </Link>
                          </td>
                          <td>{formatDateTime(row.assigned_on)}</td>
                          <td>
                            <StatusBadge
                              label={row.stale ? "review overdue" : row.age_state === "within_review_window" ? "within review window" : "unknown change age"}
                              tone={row.stale ? "warning" : "neutral"}
                              compact
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
              )}
              {!owners.error && !owners.loading && <TablePagination
                total={ownersPaging.total}
                pageRows={ownersPaging.pageRows.length}
                page={ownersPaging.page}
                onPageChange={ownersPaging.setPage}
                pageSize={ownersPaging.pageSize}
                onPageSizeChange={ownersPaging.setPageSize}
                label="owners"
              />}
            </div>
          </section>

          <section id="identity-stale" className="card" aria-labelledby="identity-stale-heading">
            <div className="card-header">
              <div>
                <h2 id="identity-stale-heading">Stale access</h2>
                <p>
                  Assignments unchanged past the review threshold, privileged
                  ones first.
                </p>
              </div>
            </div>
            <div className="card-body">
              {stale.error ? (
                <StatePanel title="Stale access is unavailable" message={stale.error.message} tone="error"
                  action={<button className="button button-secondary" type="button" onClick={stale.refetch}>Retry stale access</button>} />
              ) : stale.loading ? (
                <StatePanel title="Reading stale access" message="Checking observed assignments against the review threshold." tone="loading" />
              ) : (stale.data?.data.assignments.length ?? 0) === 0 ? (
                <StatePanel
                  title="No overdue change-age signal observed"
                  message="Missing, future, malformed or unzoned change timestamps cannot establish assignment age. Change recency does not prove use, continued need or an access review."
                />
              ) : (
                <>
                <TableColumnFilters
                  filters={staleFilters}
                  onReset={resetStaleFilters}
                  resultCount={filteredStale.length}
                  totalCount={staleRows.length}
                />
                <div className="table-scroll" tabIndex={0} role="region" aria-label="Stale access records">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Principal</th>
                        <th>Role</th>
                        <th>Scope</th>
                        <th>Last changed</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stalePaging.pageRows.map((row, index) => (
                        <tr key={`${row.assignment_id}-${index}`}>
                          <td>
                            <Link
                              className="table-primary-link"
                              href={`/search?q=${encodeURIComponent(row.principal_id)}`}
                            >
                              <span className="table-wrap resource-id-cell">{row.principal_id}</span>
                            </Link>
                          </td>
                          <td className="cell-nowrap">{row.role || "Unresolved"}</td>
                          <td>
                            <Link
                              className="table-primary-link"
                              href={`/search?q=${encodeURIComponent(row.scope)}`}
                            >
                              <span className="table-wrap resource-id-cell">{row.scope}</span>
                            </Link>
                          </td>
                          <td>{formatDateTime(row.last_changed)}</td>
                          <td>
                            <StatusBadge
                              label={row.privileged ? "privileged signal" : "no classified signal"}
                              tone={row.privileged ? "critical" : "neutral"}
                              compact
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
              )}
              {!stale.error && !stale.loading && <TablePagination
                total={stalePaging.total}
                pageRows={stalePaging.pageRows.length}
                page={stalePaging.page}
                onPageChange={stalePaging.setPage}
                pageSize={stalePaging.pageSize}
                onPageSizeChange={stalePaging.setPageSize}
                label="stale assignments"
              />}
            </div>
          </section>

          <section id="identity-non-human" className="card" aria-labelledby="identity-non-human-heading">
            <div className="card-header">
              <div>
                <h2 id="identity-non-human-heading">Non-human identities</h2>
                <p>Service principals and managed identities holding access.</p>
              </div>
            </div>
            <div className="card-body">
              {nonHuman.error ? (
                <StatePanel title="Non-human identities are unavailable" message={nonHuman.error.message} tone="error"
                  action={<button className="button button-secondary" type="button" onClick={nonHuman.refetch}>Retry non-human identities</button>} />
              ) : nonHuman.loading ? (
                <StatePanel title="Reading non-human identities" message="Resolving service principals and managed identities in scope." tone="loading" />
              ) : (nonHuman.data?.data.identities.length ?? 0) === 0 ? (
                <StatePanel
                  title="No non-human identities observed"
                  message="No service principal or managed identity was found in the synced data for this scope."
                />
              ) : (
                <>
                <TableColumnFilters
                  filters={nonHumanFilters}
                  onReset={resetNonHumanFilters}
                  resultCount={filteredNonHuman.length}
                  totalCount={nonHumanRows.length}
                />
                <div className="table-scroll" tabIndex={0} role="region" aria-label="Non-human identity records">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Identity</th>
                        <th>Type</th>
                        <th>Assignments</th>
                      </tr>
                    </thead>
                    <tbody>
                      {nonHumanPaging.pageRows.map((row, index) => (
                        <tr key={`${row.principal_id}-${index}`}>
                          <td>
                            <Link
                              className="table-primary-link"
                              href={`/search?q=${encodeURIComponent(row.resource_id || row.name || row.principal_id)}`}
                            >
                              {row.name || row.principal_id}
                            </Link>
                            {row.resource_id && (
                              <div className="table-secondary">
                                <span className="resource-id-cell">{row.resource_id}</span>
                              </div>
                            )}
                          </td>
                          <td className="cell-nowrap">{titleize(row.principal_type || "unknown")}</td>
                          <td>{row.assignment_count ?? "Unresolved"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
              )}
              {!nonHuman.error && !nonHuman.loading && <TablePagination
                total={nonHumanPaging.total}
                pageRows={nonHumanPaging.pageRows.length}
                page={nonHumanPaging.page}
                onPageChange={nonHumanPaging.setPage}
                pageSize={nonHumanPaging.pageSize}
                onPageSizeChange={nonHumanPaging.setPageSize}
                label="identities"
              />}
            </div>
          </section>

          <section id="identity-credentials" className="card" aria-labelledby="identity-credentials-heading">
            <div className="card-header">
              <div>
                <h2 id="identity-credentials-heading">Service principal governance</h2>
                <p>
                  Credential owner, scope, rotation status, and expiry for every
                  onboarding connection.
                </p>
              </div>
            </div>
            <div className="card-body">
              <div className="metric-grid">
                <MetricCard
                  label="Credentials"
                  value={spnSummary?.credential_count ?? 0}
                  detail="Across all onboarded connections in scope"
                />
                <MetricCard
                  label="Expired"
                  value={spnSummary?.expired_count ?? 0}
                  detail="Past their recorded expiry"
                  tone={(spnSummary?.expired_count ?? 0) > 0 ? "critical" : "success"}
                />
                <MetricCard
                  label="Expiring soon"
                  value={spnSummary?.expiring_soon_count ?? 0}
                  detail={`Within ${spnSummary?.expiry_warning_days ?? 30} days`}
                  tone={
                    (spnSummary?.expiring_soon_count ?? 0) > 0 ? "warning" : "success"
                  }
                />
                <MetricCard
                  label="Unknown expiry"
                  value={spnSummary?.unknown_expiry_count ?? 0}
                  detail="No expiry recorded, so rotation cannot be verified"
                  tone={
                    (spnSummary?.unknown_expiry_count ?? 0) > 0 ? "warning" : "success"
                  }
                />
              </div>

              {(spn.data?.data.credentials.length ?? 0) === 0 ? (
                <StatePanel
                  title="No credentials in scope"
                  message="No onboarding connection is visible under the current scope selection."
                />
              ) : (
                <>
                <TableColumnFilters
                  filters={spnFilters}
                  onReset={resetSpnFilters}
                  resultCount={filteredSpn.length}
                  totalCount={spnRows.length}
                />
                <div className="table-scroll" tabIndex={0} role="region" aria-label="Credential records">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Connection</th>
                        <th>Client ID</th>
                        <th>Rotation</th>
                        <th>Expires</th>
                        <th>Assignments</th>
                        <th>Issues</th>
                      </tr>
                    </thead>
                    <tbody>
                      {spnPaging.pageRows.map((row, index) => (
                        <tr key={row.credential_id || index}>
                          <td>
                            <Link className="table-primary-link" href="/connections">
                              {row.connection_name || row.connection_id}
                            </Link>
                            <div className="table-secondary">
                              <span className="resource-id-cell">{row.subscription_id}</span>
                            </div>
                          </td>
                          <td>
                            <span className="resource-id-cell" title={row.client_id}>{row.client_id || "—"}</span>
                          </td>
                          <td>
                            <StatusBadge
                              label={titleize(row.rotation_status)}
                              tone={rotationTone(row.rotation_status)}
                              compact
                            />
                          </td>
                          <td>
                            {row.expires_at ? formatDateTime(row.expires_at) : "Not recorded"}
                            {row.days_to_expiry !== null && (
                              <div className="table-secondary">
                                {row.days_to_expiry} days
                              </div>
                            )}
                          </td>
                          <td>
                            {row.observed_assignment_count === null ? (
                              <span title="Role assignments reference the service principal object id, which is not recorded for this credential.">
                                Not resolvable
                              </span>
                            ) : (
                              row.observed_assignment_count
                            )}
                          </td>
                          <td>
                            {(row.issues?.length ?? 0) === 0 ? (
                              <StatusBadge label="none" tone="success" compact />
                            ) : (
                              <div className="table-wrap">{row.issues.join("; ")}</div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
              )}
              <TablePagination
                total={spnPaging.total}
                pageRows={spnPaging.pageRows.length}
                page={spnPaging.page}
                onPageChange={spnPaging.setPage}
                pageSize={spnPaging.pageSize}
                onPageSizeChange={spnPaging.setPageSize}
                label="credentials"
              />
            </div>
          </section>
        </>
      )}


      <CopilotInsights
        snapshot={identityCopilot.snapshot}
        ready={!loading && !leastPrivilege.loading}
        requestedScope={identityCopilot.requestedScope}
        contextLabel="Access governance"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Access governance"
        requestedScope={identityCopilot.requestedScope}
        snapshot={identityCopilot.snapshot}
        starterQuestions={identityCopilot.starterQuestions}
      />
    </div>
  );
}
