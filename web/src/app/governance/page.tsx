"use client";

import { useMemo, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TablePagination } from "@/components/ui/TablePagination";
import { useTablePagination } from "@/lib/use-table-pagination";
import { useApi } from "@/hooks/useApi";
import { titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { governanceApi } from "@/lib/services";
import type { AccessReviewPack, AuditExportPack } from "@/lib/types";

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

const EDITABLE_POLICY_SECTIONS = [
  "onboarding_policy",
  "architecture_policy",
  "vulnerability_policy",
  "agent_policy",
  "retention_policy",
] as const;

type PolicySection = (typeof EDITABLE_POLICY_SECTIONS)[number];

export default function GovernancePage() {
  const { scope } = useScope();
  const [tab, setTab] = useState<Tab>("reviews");
  const [pack, setPack] = useState<AccessReviewPack | AuditExportPack | null>(null);
  const [packLabel, setPackLabel] = useState("");
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const [draft, setDraft] = useState<Record<string, Record<string, unknown>> | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [saveError, setSaveError] = useState("");

  const [settingsRefresh, setSettingsRefresh] = useState(0);
  const audiences = useApi(() => governanceApi.accessReviewKinds(), []);
  const kinds = useApi(() => governanceApi.exportKinds(), []);
  const settings = useApi(
    () => governanceApi.settings(scope),
    [scope, settingsRefresh],
  );

  async function generate(label: string, loader: () => Promise<{ data: unknown }>) {
    setBusy(label);
    setActionError("");
    try {
      const response = await loader();
      setPack(response.data as AccessReviewPack | AuditExportPack);
      setPackLabel(label);
    } catch (error) {
      setPack(null);
      setActionError(
        error instanceof Error ? error.message : "The pack could not be generated.",
      );
    } finally {
      setBusy("");
    }
  }

  const currentSettings = settings.data?.data;
  const roles = useMemo(() => currentSettings?.roles ?? [], [currentSettings]);
  const rolesPaging = useTablePagination(roles);

  // Seed the editable draft once per fresh settings read; edits then live only
  // in local state until explicitly saved, so a background refetch never
  // clobbers unsaved operator input.
  const settingsVersion = currentSettings ? JSON.stringify(currentSettings) : "";
  useMemo(() => {
    if (!currentSettings) return;
    setDraft(
      Object.fromEntries(
        EDITABLE_POLICY_SECTIONS.map((section) => [
          section,
          { ...(currentSettings[section] as Record<string, unknown> | undefined) },
        ]),
      ),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsVersion]);

  function setField(section: PolicySection, key: string, value: unknown) {
    setSaveMessage("");
    setSaveError("");
    setDraft((prev) => ({
      ...(prev ?? {}),
      [section]: { ...(prev?.[section] ?? {}), [key]: value },
    }));
  }

  async function saveSettings() {
    if (!draft) return;
    setSaving(true);
    setSaveMessage("");
    setSaveError("");
    try {
      await governanceApi.updateSettings(draft);
      setSaveMessage("Policy settings saved.");
      setSettingsRefresh((n) => n + 1);
    } catch (error) {
      setSaveError(
        error instanceof Error ? error.message : "Unable to save settings.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Enterprise governance"
        title="Can governance decisions be reviewed?"
        description="Review access packs, audit evidence availability, and the settings that shape onboarding, architecture, agents, and retention."
        metadata={
          <>
            <span>Every pack records its own provenance</span>
            <span>Scope-limited to your subscriptions</span>
          </>
        }
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

                <div className="policy-editor">
                  {EDITABLE_POLICY_SECTIONS.map((section) => {
                    const values = draft?.[section] ?? {};
                    const entries = Object.entries(values);
                    if (entries.length === 0) return null;
                    return (
                      <div key={section} className="policy-editor-group">
                        <h3>{titleize(section.replace("_policy", ""))}</h3>
                        {entries.map(([key, value]) => (
                          <label key={key} className="policy-editor-field">
                            <span>{titleize(key)}</span>
                            {typeof value === "boolean" ? (
                              <input
                                type="checkbox"
                                checked={value}
                                onChange={(e) =>
                                  setField(section, key, e.target.checked)
                                }
                              />
                            ) : typeof value === "number" ? (
                              <input
                                type="number"
                                value={value}
                                onChange={(e) =>
                                  setField(section, key, Number(e.target.value))
                                }
                              />
                            ) : (
                              <span className="table-wrap muted">
                                {Array.isArray(value) ? value.join(", ") : String(value)}
                              </span>
                            )}
                          </label>
                        ))}
                      </div>
                    );
                  })}
                </div>
                <div className="policy-editor-actions">
                  <button
                    type="button"
                    className="button"
                    onClick={saveSettings}
                    disabled={saving || !draft}
                  >
                    {saving ? "Saving..." : "Save policy settings"}
                  </button>
                  {saveMessage && <p role="status">{saveMessage}</p>}
                  {saveError && (
                    <p role="alert" className="text-critical">
                      {saveError}
                    </p>
                  )}
                </div>
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
    </div>
  );
}
