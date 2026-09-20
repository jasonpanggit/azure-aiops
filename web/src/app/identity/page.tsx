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
import { governanceApi } from "@/lib/services";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";

function rotationTone(status: string): "critical" | "warning" | "success" | "neutral" {
  if (status === "expired") return "critical";
  if (status === "expiring_soon") return "warning";
  if (status === "healthy") return "success";
  return "neutral";
}

/** Blast radius is a count per scope breadth; render it compactly. */
function blastRadius(radius: Record<string, number>): string {
  const entries = Object.entries(radius ?? {});
  if (entries.length === 0) return "None observed";
  return entries.map(([key, value]) => `${value} ${titleize(key).toLowerCase()}`).join(", ");
}

export default function IdentityPage() {
  const { scope } = useScope();
  const [copilotOpen, setCopilotOpen] = useState(false);

  const summary = useApi(() => governanceApi.identitySummary(scope), [scope]);
  const principals = useApi(() => governanceApi.identityPrincipals(scope), [scope]);
  const owners = useApi(() => governanceApi.subscriptionOwners(scope), [scope]);
  const stale = useApi(() => governanceApi.staleAccess(scope), [scope]);
  const nonHuman = useApi(() => governanceApi.nonHumanIdentities(scope), [scope]);
  const spn = useApi(() => governanceApi.spnCredentials(scope), [scope]);

  const principalRows = useMemo(() => principals.data?.data.principals ?? [], [principals.data]);
  const ownerRows = useMemo(() => owners.data?.data.owners ?? [], [owners.data]);
  const staleRows = useMemo(() => stale.data?.data.assignments ?? [], [stale.data]);
  const nonHumanRows = useMemo(() => nonHuman.data?.data.identities ?? [], [nonHuman.data]);
  const spnRows = useMemo(() => spn.data?.data.credentials ?? [], [spn.data]);

  const { filteredRows: filteredPrincipals, filters: principalFilters, resetFilters: resetPrincipalFilters } = useColumnFilters(principalRows, [
    { id: "type", label: "Type", getValues: (row) => row.principal_type || "unknown", formatOption: titleize },
    { id: "scope", label: "Widest scope", getValues: (row) => row.widest_scope_breadth || "unknown", formatOption: titleize },
    { id: "status", label: "Status", getValues: (row) => [row.privileged ? "privileged" : "", row.stale ? "stale" : "", !row.privileged && !row.stale ? "standard" : ""] },
  ]);
  const { filteredRows: filteredOwners, filters: ownerFilters, resetFilters: resetOwnerFilters } = useColumnFilters(ownerRows, [
    { id: "type", label: "Type", getValues: (row) => row.principal_type || "unknown", formatOption: titleize },
    { id: "status", label: "Status", getValues: (row) => row.stale ? "stale" : "current" },
  ]);
  const { filteredRows: filteredStale, filters: staleFilters, resetFilters: resetStaleFilters } = useColumnFilters(staleRows, [
    { id: "role", label: "Role", getValues: (row) => row.role || "Unresolved" },
    { id: "status", label: "Status", getValues: (row) => row.privileged ? "privileged" : "standard" },
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

  const loading = summary.loading || principals.loading || spn.loading;
  const error = summary.error ?? principals.error ?? spn.error;

  const totals = summary.data?.data;
  const spnSummary = spn.data?.data.summary;

  // The API warns when identity data has never synced. Surfacing that is
  // essential: an empty table must never read as "no privileged access".
  const warnings = [
    ...(summary.data?.warnings ?? []),
    ...(principals.data?.warnings ?? []),
  ];

  // Read-only contextual Copilot over already-loaded, server-authorized
  // identity evidence. Principals stay scope-safe domain identities; no
  // mutation path is exposed (D-03, D-05, D-06, D-08, D-09).
  const identityAvailable = !error && Boolean(summary.data);
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
    })),
    principalsTotalCount: principals.data?.data.count ?? principalRows.length,
    owners: ownerRows.map((owner) => ({
      principal_id: owner.principal_id,
      principal_type: owner.principal_type,
      subscription_id: owner.subscription_id,
      scope_breadth: owner.scope_breadth,
      stale: owner.stale,
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
    available: identityAvailable,
    freshness: identityAvailable ? "fresh" : "unavailable",
    evidence: [...(summary.data?.evidence ?? []), ...(principals.data?.evidence ?? [])],
  });

  return (
    <div className="page-container">
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

      <EvidenceBar
        evidence={[...(summary.data?.evidence ?? []), ...(spn.data?.evidence ?? [])]}
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
        />
      ) : loading ? (
        <StatePanel
          title="Reading access assignments"
          message="Resolving role assignments, definitions, and credential posture."
          tone="loading"
        />
      ) : (
        <>
          <div className="metric-grid">
            <MetricCard
              label="Principals with access"
              value={totals?.principal_count ?? 0}
              detail={`${totals?.assignment_count ?? 0} role assignments observed`}
            />
            <MetricCard
              label="Privileged principals"
              value={totals?.privileged_principal_count ?? 0}
              detail="Hold owner-equivalent or wildcard permissions"
              tone={(totals?.privileged_principal_count ?? 0) > 0 ? "critical" : "success"}
            />
            <MetricCard
              label="Stale assignments"
              value={totals?.stale_assignment_count ?? 0}
              detail={`Unchanged for over ${totals?.stale_threshold_days ?? 90} days`}
              tone={(totals?.stale_assignment_count ?? 0) > 0 ? "warning" : "success"}
            />
            <MetricCard
              label="Non-human identities"
              value={totals?.non_human_principal_count ?? 0}
              detail="Service principals and managed identities"
            />
          </div>

          <section className="card">
            <div className="card-header">
              <div>
                <h2>Principals and blast radius</h2>
                <p>
                  Each principal&apos;s widest scope determines how far a
                  compromise of that identity would reach.
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
                <div className="table-scroll">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Principal</th>
                        <th>Type</th>
                        <th>Roles</th>
                        <th>Widest scope</th>
                        <th>Blast radius</th>
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
                          <td>{titleize(row.principal_type || "unknown")}</td>
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
                              <StatusBadge label="privileged" tone="critical" compact />
                            )}
                            {row.stale && (
                              <StatusBadge label="stale" tone="warning" compact />
                            )}
                            {!row.privileged && !row.stale && (
                              <StatusBadge label="standard" tone="success" compact />
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

          <section className="card">
            <div className="card-header">
              <div>
                <h2>Subscription owners</h2>
                <p>Principals holding owner rights over a whole subscription.</p>
              </div>
            </div>
            <div className="card-body">
              {(owners.data?.data.owners.length ?? 0) === 0 ? (
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
                <div className="table-scroll">
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
                          <td>{titleize(row.principal_type || "unknown")}</td>
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
                              label={row.stale ? "stale" : "current"}
                              tone={row.stale ? "warning" : "success"}
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
              <TablePagination
                total={ownersPaging.total}
                pageRows={ownersPaging.pageRows.length}
                page={ownersPaging.page}
                onPageChange={ownersPaging.setPage}
                pageSize={ownersPaging.pageSize}
                onPageSizeChange={ownersPaging.setPageSize}
                label="owners"
              />
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <div>
                <h2>Stale access</h2>
                <p>
                  Assignments unchanged past the review threshold, privileged
                  ones first.
                </p>
              </div>
            </div>
            <div className="card-body">
              {(stale.data?.data.assignments.length ?? 0) === 0 ? (
                <StatePanel
                  title="No stale access"
                  message="Every observed assignment has changed within the review window."
                />
              ) : (
                <>
                <TableColumnFilters
                  filters={staleFilters}
                  onReset={resetStaleFilters}
                  resultCount={filteredStale.length}
                  totalCount={staleRows.length}
                />
                <div className="table-scroll">
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
                          <td>{row.role || "Unresolved"}</td>
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
                              label={row.privileged ? "privileged" : "standard"}
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
              <TablePagination
                total={stalePaging.total}
                pageRows={stalePaging.pageRows.length}
                page={stalePaging.page}
                onPageChange={stalePaging.setPage}
                pageSize={stalePaging.pageSize}
                onPageSizeChange={stalePaging.setPageSize}
                label="stale assignments"
              />
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <div>
                <h2>Non-human identities</h2>
                <p>Service principals and managed identities holding access.</p>
              </div>
            </div>
            <div className="card-body">
              {(nonHuman.data?.data.identities.length ?? 0) === 0 ? (
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
                <div className="table-scroll">
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
                          <td>{titleize(row.principal_type || "unknown")}</td>
                          <td>{row.assignment_count ?? "Unresolved"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
              )}
              <TablePagination
                total={nonHumanPaging.total}
                pageRows={nonHumanPaging.pageRows.length}
                page={nonHumanPaging.page}
                onPageChange={nonHumanPaging.setPage}
                pageSize={nonHumanPaging.pageSize}
                onPageSizeChange={nonHumanPaging.setPageSize}
                label="identities"
              />
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <div>
                <h2>Service principal governance</h2>
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
                <div className="table-scroll">
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
