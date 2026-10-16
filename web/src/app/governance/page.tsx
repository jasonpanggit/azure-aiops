"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useTablePagination } from "@/lib/use-table-pagination";
import { useApi } from "@/hooks/useApi";
import { buildGovernanceCopilotContext } from "@/lib/copilot/page-adapters";
import { titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { governanceApi } from "@/lib/services";
import { useColumnFilters } from "@/lib/table-column-filters";
import type { AccessReviewPack, AuditExportPack } from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";
import { EDITABLE_POLICY_SECTIONS, GovernanceSettingsEditor } from "@/components/GovernanceSettingsEditor";
import { GovernanceRetainedExports } from "@/components/GovernanceRetainedExports";

type Tab = "reviews" | "exports" | "settings";

const TABS: { id: Tab; label: string }[] = [
  { id: "reviews", label: "Access reviews" },
  { id: "exports", label: "Audit evidence" },
  { id: "settings", label: "Administration" },
];

/** Downloads a generated pack as JSON so it can be attached to an audit. */
function download(name: string, payload: unknown): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${name}-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

export default function GovernancePage() {
  const { scope } = useScope();
  const [tab, setTab] = useState<Tab>("reviews");
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [pack, setPack] = useState<AccessReviewPack | AuditExportPack | null>(null);
  const [packLabel, setPackLabel] = useState("");
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const requestId = useRef(0);

  useEffect(() => {
    setPack(null);
    setPackLabel("");
    setBusy("");
    setActionError("");
    return () => { requestId.current += 1; };
  }, [scope]);

  const audiences = useApi(() => governanceApi.accessReviewKinds(), []);
  const kinds = useApi(() => governanceApi.exportKinds(), []);
  const settings = useApi(
    signal => governanceApi.settings(scope, signal),
    [scope],
  );

  async function generate(label: string, loader: () => Promise<{ data: unknown }>) {
    if (busy) return;
    const id = ++requestId.current;
    setBusy(label);
    setActionError("");
    try {
      const response = await loader();
      if (id !== requestId.current) return;
      setPack(response.data as AccessReviewPack | AuditExportPack);
      setPackLabel(label);
    } catch (error) {
      if (id !== requestId.current) return;
      setPack(null);
      setActionError(
        error instanceof Error ? error.message : "The pack could not be generated.",
      );
    } finally {
      if (id === requestId.current) setBusy("");
    }
  }

  const currentSettings = settings.data?.data;
  const roles = useMemo(() => currentSettings?.roles ?? [], [currentSettings]);
  const { filteredRows: filteredRoles, filters: roleFilters, resetFilters: resetRoleFilters } = useColumnFilters(roles, [
    { id: "permission", label: "Permission", getValues: (role) => role.permissions },
  ]);
  const rolesPaging = useTablePagination(filteredRoles);

  // Read-only contextual Copilot over the already-loaded governance evidence.
  // Optional access-review/export enrichment is never a prerequisite; the
  // governance settings remain usable without it (D-03, D-04, D-06, D-09).
  const governanceCopilot = buildGovernanceCopilotContext({
    scope,
    roles: (currentSettings?.roles ?? []).map((role) => ({
      role_id: role.role_id,
      name: role.name,
      permissions: role.permissions,
    })),
    rolesTotalCount: roles.length,
    policies: EDITABLE_POLICY_SECTIONS.map((section) => ({
      section,
      setting_count: Object.keys(
        (currentSettings?.[section] as Record<string, unknown> | undefined) ?? {},
      ).length,
    })).filter((policy) => policy.setting_count > 0),
    accessReviewAudiences: audiences.data?.data.audiences ?? [],
    auditExportKinds: kinds.data?.data.kinds ?? [],
    settingsAvailable: !settings.error && Boolean(settings.data),
    audiencesAvailable: !audiences.error && Boolean(audiences.data),
    kindsAvailable: !kinds.error && Boolean(kinds.data),
    freshness: settings.error || !settings.data ? "unavailable" : "fresh",
    evidence: settings.data?.evidence ?? [],
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Enterprise governance"
        title="Can governance decisions be reviewed?"
        description="Review access packs, audit evidence availability, and the settings that shape onboarding, architecture, agents, and retention."
        actions={
          <CopilotDrawerButton
            onClick={() => setCopilotOpen(true)}
            label="Ask Copilot about governance"
          />
        }
        metadata={
          <>
            <span>Every pack records its own provenance</span>
            <span>Scope-limited to your subscriptions</span>
          </>
        }
      />

      <CopilotInsights
        snapshot={governanceCopilot.snapshot}
        ready={!audiences.loading && !kinds.loading && !settings.loading}
        requestedScope={governanceCopilot.requestedScope}
        contextLabel="Enterprise governance"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      <EvidenceBar
        evidence={settings.data?.evidence ?? []}
        knowledgeVersion={settings.data?.knowledge_version}
        warnings={settings.data?.warnings ?? []}
      />

      <div className="segmented-control" aria-label="Governance section">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={item.id === tab ? "segmented-active" : ""}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {actionError && (
        <StatePanel
          title="The pack could not be generated"
          message={actionError}
          tone="error"
        />
      )}

      {tab === "reviews" && (
        <section className="card">
          <div className="card-header">
            <div>
              <h2>Access review packs</h2>
              <p>
                A point-in-time record of who holds access, assembled for the
                audience that has to sign it off.
              </p>
            </div>
          </div>
          <div className="card-body">
            {audiences.error ? (
              <StatePanel
                title="Review audiences are unavailable"
                message={audiences.error.message ?? "No response was returned."}
                tone="error"
              />
            ) : audiences.loading ? (
              <StatePanel
                title="Loading audiences"
                message="Reading the available review packs."
                tone="loading"
              />
            ) : (
              <div className="metric-grid">
                {audiences.data?.data.audiences.map((audience) => (
                  <MetricCard
                    key={audience}
                    label={titleize(audience)}
                    value="Review pack"
                    detail="Generate a point-in-time access record for this audience"
                    action={
                      <button
                        type="button"
                        className="button"
                        disabled={busy === audience}
                        onClick={() =>
                          generate(audience, () =>
                            governanceApi.accessReview(audience, scope),
                          )
                        }
                      >
                        {busy === audience ? "Generating…" : "Generate"}
                      </button>
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {tab === "exports" && (
        <section className="card">
          <div className="card-header">
            <div>
              <h2>Audit evidence packs</h2>
              <p>
                Onboarding, network design, firewall and NSG, exposure,
                identity, remediation, and executive evidence.
              </p>
            </div>
          </div>
          <div className="card-body">
            {kinds.error ? (
              <StatePanel
                title="Export kinds are unavailable"
                message={kinds.error.message ?? "No response was returned."}
                tone="error"
              />
            ) : kinds.loading ? (
              <StatePanel
                title="Loading export kinds"
                message="Reading the available evidence packs."
                tone="loading"
              />
            ) : (
              <div className="metric-grid">
                {kinds.data?.data.kinds.map((kind) => (
                  <MetricCard
                    key={kind}
                    label={titleize(kind)}
                    value="Evidence pack"
                    detail="Assembled from observed data, with gaps stated"
                    action={
                      <button
                        type="button"
                        className="button"
                        disabled={busy === kind}
                        onClick={() =>
                          generate(kind, () => governanceApi.auditExport(kind, scope))
                        }
                      >
                        {busy === kind ? "Generating…" : "Generate"}
                      </button>
                    }
                  />
                ))}
              </div>
            )}
            <GovernanceRetainedExports scope={scope} />
          </div>
        </section>
      )}

      {tab === "settings" && (
        <section className="card">
          <div className="card-header">
            <div>
              <h2>Enterprise administration</h2>
              <p>
                Roles, taxonomies, and the onboarding, architecture, agent, and
                retention policies applied across the workbench.
              </p>
            </div>
          </div>
          <div className="card-body">
            {settings.error ? (
              <StatePanel
                title="Settings are unavailable"
                message={settings.error.message ?? "No response was returned."}
                tone="error"
                action={<button className="button" onClick={settings.refetch}>Reload settings overview</button>}
              />
            ) : settings.loading ? (
              <StatePanel
                title="Loading settings"
                message="Reading enterprise administration settings."
                tone="loading"
              />
            ) : !currentSettings ? (
              <StatePanel
                title="No settings returned"
                message="The settings document could not be read."
              />
            ) : (
              <>
                <TableColumnFilters
                  filters={roleFilters}
                  onReset={resetRoleFilters}
                  resultCount={filteredRoles.length}
                  totalCount={roles.length}
                />
                <div className="table-scroll">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Role</th>
                        <th>Description</th>
                        <th>Permissions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rolesPaging.pageRows.map((role) => (
                        <tr key={role.role_id}>
                          <td>
                            <span className="table-primary-link">{role.name}</span>
                            <div className="table-secondary">{role.role_id}</div>
                          </td>
                          <td>{role.description}</td>
                          <td>
                            <div className="table-secondary">
                              {role.permissions.map((permission) => (
                                <StatusBadge
                                  key={permission}
                                  label={permission}
                                  tone={permission === "admin" ? "critical" : "neutral"}
                                  compact
                                />
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <TablePagination
                  total={rolesPaging.total}
                  pageRows={rolesPaging.pageRows.length}
                  page={rolesPaging.page}
                  onPageChange={rolesPaging.setPage}
                  pageSize={rolesPaging.pageSize}
                  onPageSizeChange={rolesPaging.setPageSize}
                  label="roles"
                />

                <GovernanceSettingsEditor scope={scope} />
              </>
            )}
          </div>
        </section>
      )}

      {pack && (
        <section className="card">
          <div className="card-header">
            <div>
              <h2>{titleize(packLabel)} pack</h2>
              <p>
                Generated {String(pack.generated_at ?? "just now")}. Provenance is
                recorded inside the pack so a reviewer can trace every figure.
              </p>
            </div>
            <button
              type="button"
              className="button"
              onClick={() => download(packLabel, pack)}
            >
              Download JSON
            </button>
          </div>
          <div className="card-body">
            {Array.isArray(pack.warnings) && pack.warnings.length > 0 && (
              <StatePanel
                title="This pack is partial"
                message={pack.warnings.join(" ")}
                tone="error"
              />
            )}
            <pre className="report-preview">{JSON.stringify(pack, null, 2)}</pre>
          </div>
        </section>
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Enterprise governance"
        requestedScope={governanceCopilot.requestedScope}
        snapshot={governanceCopilot.snapshot}
        starterQuestions={governanceCopilot.starterQuestions}
      />
    </div>
  );
}
