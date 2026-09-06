"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { useMsal } from "@azure/msal-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import {
  RiskExceptionDialog,
  type RiskExceptionRecordRequest,
  type RiskExceptionRecordResult,
  type RiskExceptionRevokeRequest,
  type RiskExceptionRevokeResult,
} from "@/components/exposure/RiskExceptionDialog";
import { AttackPathGraphView } from "@/components/ui/AttackPathGraphView";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { CvssRadarChart } from "@/components/ui/CvssRadarChart";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import {
  PageHeader,
  type PageHeaderCompleteness,
} from "@/components/ui/PageHeader";
import { SourceSectionState } from "@/components/exposure/SourceSectionState";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import {
  advanceExposureCursor,
  encodeExposureQueryState,
  exposureDetailHref,
  exposureDetailParentLabel,
  exposureDetailReturnHref,
  exposureQueryKey,
  exposureRetentionKey,
  parseExposureDetailContext,
  parseExposureQueryState,
  restartExposureQuery,
  retreatExposureCursor,
  updateExposureQueryState,
  type ExposureQueryState,
} from "@/lib/exposure-query-state";
import {
  useExposureSection,
  type ExposureSectionPresentation,
  type ExposureSectionResult,
} from "@/hooks/useExposureSection";
import { useScope } from "@/lib/scope-context";
import {
  buildCopilotSnapshot,
  copilotEvidenceRows,
  vulnerabilityApi,
} from "@/lib/services";
import type {
  AttackPathGraph,
  CveDetail,
  Envelope,
  ExposureEnrichmentSourceState,
  ExposureCursorPagination,
  ExposureFinding,
  ExposureOverview,
  ExposurePage,
} from "@/lib/types";

interface CveFindingRow extends ExposureFinding {
  server_id?: string;
  missing_kb?: string;
  application?: string;
  business_service?: string;
  environment?: string;
  network_exposure?: string;
  reachable?: boolean;
  firewall_path?: string[];
  nsg_path?: string[];
  owner?: string;
  due_at?: string | null;
  days_open?: number | null;
  overdue?: boolean | null;
  risk_accepted?: boolean;
  risk_acceptance_reason?: string;
  risk_acceptance_expires_at?: string;
  severity?: string;
}

const TARGET_KIND_OPTIONS = [
  { value: "server", label: "Servers" },
  { value: "container_image", label: "Container images" },
];

function canonicalPath(pathname: string, state: ExposureQueryState): string {
  const encoded = encodeExposureQueryState(state).toString();
  return encoded ? `${pathname}?${encoded}` : pathname;
}

function statusRank(status: ExposureSectionPresentation["status"]): number {
  return {
    current: 0,
    "healthy-empty": 0,
    stale: 1,
    partial: 2,
    loading: 3,
    unavailable: 4,
  }[status];
}

function aggregateCompleteness(
  sections: ExposureSectionPresentation[],
): PageHeaderCompleteness {
  const worst = sections.reduce(
    (current, candidate) =>
      statusRank(candidate.status) > statusRank(current.status)
        ? candidate
        : current,
    sections[0],
  );
  const state =
    worst.status === "current" || worst.status === "healthy-empty"
      ? "complete"
      : worst.status === "loading" || worst.status === "unavailable"
        ? "unavailable"
        : worst.status;
  const metadata = worst.metadata;
  return {
    state,
    freshness:
      state === "complete"
        ? "current"
        : state === "stale"
          ? "stale"
          : "unknown",
    representedConnections: metadata.represented,
    expectedConnections: metadata.expected,
    representedCount: metadata.loaded,
    totalCount: metadata.total,
    excludedCount: metadata.excluded,
    excludedReasons: metadata.excludedReasons,
  };
}

function metricCompleteness(
  status: ExposureSectionPresentation["status"],
): "complete" | "partial" | "stale" | "unavailable" {
  if (status === "current" || status === "healthy-empty") return "complete";
  if (status === "loading") return "unavailable";
  return status;
}

function cursorEnvelope<T>(
  promise: Promise<Envelope<T>>,
): Promise<Envelope<T, ExposureCursorPagination>> {
  return promise as unknown as Promise<Envelope<T, ExposureCursorPagination>>;
}

function sourceRecord(
  detail: CveDetail | null,
  source: "nvd" | "epss" | "kev" | "msrc",
): ExposureEnrichmentSourceState | null {
  const entries = Object.values(detail?.enrichment?.sources ?? {});
  return (
    entries.find((entry) => entry.source.toLocaleLowerCase("en-US") === source) ??
    null
  );
}

function presentSection<T>(
  section: ExposureSectionResult<T>,
  common: ExposureSectionResult<unknown>,
  {
    loaded,
    empty = false,
    source,
  }: {
    loaded?: number;
    empty?: boolean;
    source?: ExposureEnrichmentSourceState | null;
  } = {},
): ExposureSectionPresentation {
  const metadata = {
    ...common.metadata,
    represented:
      (common.data as ExposureOverview | null)?.contract.completeness
        .represented_connections ?? common.metadata.represented,
    expected:
      (common.data as ExposureOverview | null)?.contract.completeness
        .expected_connections ?? common.metadata.expected,
    loaded,
    observedAt:
      source?.source_at ??
      source?.succeeded_at ??
      source?.attempted_at ??
      common.metadata.observedAt,
    freshnessSourceFamily: source?.source ?? common.metadata.freshnessSourceFamily,
    safeErrorMessage:
      source?.safe_error_code || section.error?.message || common.metadata.safeErrorMessage,
  };
  const presentedSection = {
    ...section,
    retrying: section.retrying || Boolean(section.loading && section.data),
  };
  if (section.loading && !section.data) {
    return { ...presentedSection, metadata, status: "loading" };
  }
  if (section.error) {
    return {
      ...presentedSection,
      metadata,
      status: section.data ? "stale" : "unavailable",
    };
  }
  if (source) {
    const succeeded = ["success", "succeeded", "complete"].includes(
      source.status.toLocaleLowerCase("en-US"),
    );
    if (source.stale || (!succeeded && source.has_last_known_good)) {
      return { ...presentedSection, metadata, status: "stale" };
    }
    if (!succeeded && !source.has_last_known_good) {
      return {
        ...presentedSection,
        metadata,
        error: new Error(
          source.safe_error_code || `${source.source} enrichment is unavailable`,
        ),
        status: "unavailable",
      };
    }
  }
  if (empty) return { ...presentedSection, metadata, status: "healthy-empty" };
  const commonStatus = common.data
    ? common.status
    : common.loading
      ? "partial"
      : "partial";
  return {
    ...presentedSection,
    metadata,
    status:
      commonStatus === "healthy-empty" ? "current" : commonStatus,
  };
}

function Section({
  label,
  sourceName,
  itemLabel,
  state,
  children,
}: {
  label: string;
  sourceName: string;
  itemLabel: string;
  state: ExposureSectionPresentation;
  children?: React.ReactNode;
}) {
  return (
    <section role="region" aria-label={`${label} section`}>
      <div className="card-header">
        <h2>{label}</h2>
      </div>
      <SourceSectionState
        sourceName={sourceName}
        itemLabel={itemLabel}
        state={state}
      >
        {children}
      </SourceSectionState>
    </section>
  );
}

/** Scoped CVE detail with independent core, graph, and enrichment state. */
export default function CveDetailPage({ params }: { params: { id: string } }) {
  const cveId = decodeURIComponent(params.id);
  const { scope } = useScope();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryState = useMemo(
    () =>
      parseExposureQueryState(new URLSearchParams(searchParams.toString()), {
        authorizedScope: scope,
      }),
    [scope, searchParams],
  );
  const detailContext = useMemo(
    () => parseExposureDetailContext(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );
  const [findingState, setFindingState] = useState<ExposureQueryState>(() => ({
    ...queryState,
    filters: { ...queryState.filters, weakness_id: cveId },
    cursor: null,
    cursorHistory: [],
    page: 1,
  }));
  const [refreshKey, setRefreshKey] = useState(0);
  const [riskDialogOpen, setRiskDialogOpen] = useState(false);
  const [revokeExceptionId, setRevokeExceptionId] = useState("");
  const [copilotOpen, setCopilotOpen] = useState(false);
  const riskInvokerRef = useRef<HTMLButtonElement>(null);
  const { accounts } = useMsal();
  const sessionApprover =
    accounts[0]?.username || accounts[0]?.name || "Authenticated session";

  const common = useExposureSection<ExposureOverview>({
    queryKey: `${exposureQueryKey(findingState)}|common`,
    retentionKey: `${exposureRetentionKey(findingState)}|common`,
    refreshKey,
    load: ({ signal }) =>
      vulnerabilityApi.exposureOverview(findingState, { signal }),
  });
  const core = useExposureSection<CveDetail>({
    queryKey: `${exposureRetentionKey(findingState)}|core|${cveId}`,
    refreshKey,
    load: ({ signal }) =>
      cursorEnvelope(vulnerabilityApi.cve(cveId, findingState.scope, { signal })),
    isEmpty: () => false,
  });
  const findings = useExposureSection<ExposurePage<CveFindingRow>>({
    queryKey: `${exposureQueryKey(findingState)}|findings|${cveId}`,
    retentionKey: `${exposureRetentionKey(findingState)}|findings|${cveId}`,
    refreshKey,
    load: ({ signal }) =>
      vulnerabilityApi.exposureItems(findingState, { signal }) as Promise<
        Envelope<ExposurePage<CveFindingRow>, ExposureCursorPagination>
      >,
    isEmpty: (page) => page.items.length === 0,
  });
  const attack = useExposureSection<AttackPathGraph>({
    queryKey: `${exposureRetentionKey(findingState)}|attack|${cveId}`,
    refreshKey,
    load: ({ signal }) =>
      cursorEnvelope(
        vulnerabilityApi.attackPath(cveId, findingState.scope, { signal }),
      ),
    isEmpty: (graph) => graph.edges.length === 0,
  });
  const nvd = useExposureSection<CveDetail>({
    queryKey: `${exposureRetentionKey(findingState)}|nvd|${cveId}`,
    refreshKey,
    load: ({ signal }) =>
      cursorEnvelope(vulnerabilityApi.cve(cveId, findingState.scope, { signal })),
    isEmpty: (detail) => !detail.cve.cvss?.vector && !detail.cve.description,
  });
  const epss = useExposureSection<CveDetail>({
    queryKey: `${exposureRetentionKey(findingState)}|epss|${cveId}`,
    refreshKey,
    load: ({ signal }) =>
      cursorEnvelope(vulnerabilityApi.cve(cveId, findingState.scope, { signal })),
    isEmpty: () => false,
  });
  const kev = useExposureSection<CveDetail>({
    queryKey: `${exposureRetentionKey(findingState)}|kev|${cveId}`,
    refreshKey,
    load: ({ signal }) =>
      cursorEnvelope(vulnerabilityApi.cve(cveId, findingState.scope, { signal })),
    isEmpty: (detail) => !detail.cve.is_known_exploited,
  });
  const kb = useExposureSection<CveDetail>({
    queryKey: `${exposureRetentionKey(findingState)}|kb|${cveId}`,
    refreshKey,
    load: ({ signal }) =>
      cursorEnvelope(vulnerabilityApi.cve(cveId, findingState.scope, { signal })),
    isEmpty: (detail) => detail.cve.associated_kbs.length === 0,
  });

  const data = core.data;
  const rows = findings.data?.items ?? [];
  const coreState = presentSection(findings, common, {
    loaded: rows.length,
    empty: Boolean(findings.data && rows.length === 0),
  });
  if (core.error && !data) {
    coreState.status = rows.length ? "partial" : "unavailable";
    coreState.error = core.error;
  }
  const attackState = presentSection(attack, common, {
    loaded: attack.data?.edges.length,
    empty: Boolean(attack.data && attack.data.edges.length === 0),
  });
  const nvdState = presentSection(nvd, common, {
    loaded: nvd.data ? 1 : 0,
    empty: Boolean(nvd.data && !nvd.data.cve.cvss?.vector && !nvd.data.cve.description),
    source: sourceRecord(nvd.data, "nvd"),
  });
  const epssState = presentSection(epss, common, {
    loaded: epss.data ? 1 : 0,
    source: sourceRecord(epss.data, "epss"),
  });
  const kevState = presentSection(kev, common, {
    loaded: kev.data?.cve.is_known_exploited ? 1 : 0,
    empty: Boolean(kev.data && !kev.data.cve.is_known_exploited),
    source: sourceRecord(kev.data, "kev"),
  });
  const kbState = presentSection(kb, common, {
    loaded: kb.data?.cve.associated_kbs.length ?? 0,
    empty: Boolean(kb.data && kb.data.cve.associated_kbs.length === 0),
    source: sourceRecord(kb.data, "msrc"),
  });
  const allStates = [coreState, attackState, nvdState, epssState, kevState, kbState];
  const headerState = aggregateCompleteness(allStates);
  const restartRequired = [common, core, findings, attack, nvd, epss, kev, kb].some(
    (section) => section.restart.required,
  );
  const parentLabel = exposureDetailParentLabel(detailContext.origin);
  const backHref = exposureDetailReturnHref(queryState, detailContext);
  const findingPage = findings.data;
  const first = rows.length ? (findingState.page - 1) * findingState.pageSize + 1 : 0;
  const last = rows.length ? first + rows.length - 1 : 0;

  const kbHref = (kbId: string) =>
    exposureDetailHref("kbs", kbId, queryState, detailContext);

  async function recordRiskException(
    request: RiskExceptionRecordRequest,
  ): Promise<RiskExceptionRecordResult> {
    try {
      const response = await vulnerabilityApi.acceptRisk({
        cve_id: request.cveId,
        reason: request.reason,
        expires_at: request.expiresAt || undefined,
      });
      return {
        status: "success",
        auditId: response.data.exception_id,
        effectiveScope: request.targetScope,
        expiresAt: response.data.expires_at || null,
        canRevoke: response.data.can_revoke === true,
        governance: request.governance,
      };
    } catch (error) {
      return {
        status: "failure",
        message:
          error instanceof Error
            ? error.message
            : "Risk exception was not recorded.",
      };
    }
  }

  async function refreshRiskEvidence(): Promise<void> {
    await Promise.all([
      vulnerabilityApi.exposureItems(findingState),
      vulnerabilityApi.exposureOverview(findingState),
      vulnerabilityApi.cve(cveId, findingState.scope),
    ]);
    setRefreshKey((value) => value + 1);
  }

  async function revokeRiskException(
    request: RiskExceptionRevokeRequest,
  ): Promise<RiskExceptionRevokeResult> {
    const exceptionId = request.exceptionIds[0];
    try {
      await vulnerabilityApi.revokeRiskException(exceptionId);
      return {
        status: "success",
        auditId: exceptionId,
        outcomes: [{ exceptionId, status: "succeeded" }],
      };
    } catch (error) {
      return {
        status: "failure",
        message:
          error instanceof Error
            ? error.message
            : "Risk exception was not revoked.",
        outcomes: [
          {
            exceptionId,
            status: "failed",
            message: error instanceof Error ? error.message : String(error),
          },
        ],
      };
    }
  }

  return (
    <div className="page-container exposure-detail-page">
      <div className="breadcrumb">
        <Link href="/exposure">Exposure</Link>
        <span>/</span>
        <Link href={backHref}>{parentLabel}</Link>
        <span>/</span>
        <span>{data?.cve.cve_id ?? cveId}</span>
      </div>
      <PageHeader
        eyebrow="Vulnerability investigation"
        title={data?.cve.cve_id ?? cveId}
        description={
          data?.cve.title ||
          data?.cve.description ||
          "Scoped vulnerability evidence and governed next actions."
        }
        completeness={headerState}
        actions={
          <>
            <Link className="button button-quiet" href={backHref}>
              Back to {parentLabel}
            </Link>
            <CopilotDrawerButton
              onClick={() => setCopilotOpen(true)}
              label={`Ask Copilot about ${cveId}`}
            />
            {data && rows.length > 0 && (
              <button
                ref={riskInvokerRef}
                type="button"
                className="button"
                onClick={() => setRiskDialogOpen(true)}
              >
                Record risk exception
              </button>
            )}
            {data && (
              <Link
                className="button button-primary"
                href={`/remediation?cve=${encodeURIComponent(data.cve.cve_id)}&generation=${encodeURIComponent(
                  findingState.generation,
                )}&return_to=${encodeURIComponent(canonicalPath(pathname, queryState))}`}
              >
                Open governed remediation
              </Link>
            )}
          </>
        }
        metadata={
          data ? (
            <>
              <StatusBadge label={data.cve.severity} tone={statusTone(data.cve.severity)} />
              <span>{rows.length.toLocaleString("en-US")} loaded findings</span>
            </>
          ) : undefined
        }
      />
      <EvidenceBar
        evidence={common.envelope?.evidence ?? core.envelope?.evidence}
        knowledgeVersion={common.envelope?.knowledge_version ?? core.envelope?.knowledge_version}
        warnings={common.envelope?.warnings ?? core.envelope?.warnings}
        aggregateState={headerState}
      />

      {restartRequired && (
        <div className="callout callout-warning" role="alert">
          <p>The retained Exposure generation expired. Restart from the first page to continue safely.</p>
          <button
            type="button"
            className="button"
            onClick={() =>
              router.replace(canonicalPath(pathname, restartExposureQuery(queryState)), {
                scroll: false,
              })
            }
          >
            Restart results
          </button>
        </div>
      )}

      {coreState.status === "unavailable" && !data && rows.length === 0 ? (
        <SourceSectionState
          sourceName="Scoped CVE findings"
          itemLabel="findings"
          state={coreState}
        />
      ) : (
        <>
          <Section
            label="Scoped findings"
            sourceName="Scoped CVE findings"
            itemLabel="findings"
            state={coreState}
          >
            <div className="metric-grid">
              <MetricCard
                label="Affected targets"
                value={findingPage ? findingPage.contract.counts.represented : null}
                unit="targets"
                detail={`${findingPage?.contract.counts.excluded ?? "Unknown"} excluded from this represented scope`}
                completeness={metricCompleteness(coreState.status)}
              />
              <MetricCard
                label="Business services"
                value={data?.affected_business_services.length ?? null}
                unit="services"
                detail={data?.affected_business_services.join(", ") || "Service mapping unavailable"}
                completeness={metricCompleteness(coreState.status)}
              />
            </div>
            <TableColumnFilters
              filters={[
                {
                  id: "target_kind",
                  label: "Target kind",
                  value: findingState.filters.target_kind ?? "all",
                  options: TARGET_KIND_OPTIONS,
                  onChange: (value) =>
                    setFindingState((current) =>
                      updateExposureQueryState(current, {
                        filters: {
                          ...current.filters,
                          target_kind: value === "all" ? undefined : value,
                        },
                      }),
                    ),
                },
              ]}
              resultCount={rows.length}
              totalCount={findingPage?.total_count ?? 0}
              onReset={() =>
                setFindingState((current) =>
                  updateExposureQueryState(current, {
                    filters: { ...current.filters, target_kind: undefined },
                  }),
                )
              }
            />
            {rows.length > 0 && (
              <div className="table-scroll exposure-responsive-table" role="region" aria-label="Scoped CVE findings table" tabIndex={0}>
                <p className="table-scroll-hint">Scroll horizontally to see all columns</p>
                <table className="operations-table exposure-table">
                  <caption>Authorized findings for {cveId}</caption>
                  <thead><tr><th>Target</th><th>Kind</th><th>Service</th><th>Severity</th><th>Patch</th><th>Risk status</th></tr></thead>
                  <tbody>
                    {rows.map((finding) => (
                      <tr key={finding.exposure_id} id={finding.exposure_id} tabIndex={-1}>
                        <td><strong>{finding.server_id || finding.target_id}</strong></td>
                        <td>{finding.target_kind === "container_image" ? "Container image" : "Server"}</td>
                        <td>{finding.business_service || "Unmapped service"}</td>
                        <td>{finding.severity || data?.cve.severity || "Unknown"}</td>
                        <td>
                          {finding.missing_kb ? (
                            <Link className="table-primary-link" href={kbHref(finding.missing_kb)}>
                              {finding.missing_kb}
                            </Link>
                          ) : "—"}
                        </td>
                        <td>{finding.risk_accepted ? "Risk accepted" : "Open"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <TablePagination
              mode="cursor"
              cursor={{
                total: findingPage?.total_count ?? 0,
                returnedCount: rows.length,
                first,
                last,
                hasMore: Boolean(findingPage?.next_cursor),
                hasPrevious: findingState.page > 1,
                historyDepth: findingState.cursorHistory.length,
                representedCount: findingPage?.contract.counts.represented,
              }}
              busy={findings.refreshing}
              pageSize={findingState.pageSize}
              onPageSizeChange={(pageSize) =>
                setFindingState((current) =>
                  updateExposureQueryState(current, { pageSize }),
                )
              }
              onPreviousCursor={() =>
                setFindingState((current) => retreatExposureCursor(current))
              }
              onNextCursor={() => {
                if (findingPage?.next_cursor) {
                  setFindingState((current) =>
                    advanceExposureCursor(current, findingPage.next_cursor!),
                  );
                }
              }}
              label="findings"
            />
          </Section>

          <Section label="Attack path" sourceName="Attack path" itemLabel="reachable paths" state={attackState}>
            {attack.data && <AttackPathGraphView graph={attack.data} />}
          </Section>

          <Section label="NVD and CVSS" sourceName="NVD and CVSS" itemLabel="NVD records" state={nvdState}>
            {nvd.data && (
              <div className="card cvss-radar-card">
                <div className="card-body">
                  <strong className="large-value">
                    {Number.isFinite(nvd.data.cve.cvss?.base_score)
                      ? `${nvd.data.cve.cvss.base_score.toFixed(1)}/10`
                      : "—"}
                  </strong>
                  <p className="cve-description">{nvd.data.cve.description || "—"}</p>
                </div>
                {nvd.data.cve.cvss?.vector && <CvssRadarChart vector={nvd.data.cve.cvss.vector} />}
              </div>
            )}
          </Section>

          <Section label="EPSS" sourceName="EPSS" itemLabel="EPSS scores" state={epssState}>
            <MetricCard
              label="Exploit probability"
              value={epss.data ? epss.data.cve.epss_score * 100 : null}
              unit="%"
              detail={
                epss.data
                  ? `${(epss.data.cve.epss_percentile * 100).toFixed(0)}th percentile`
                  : "EPSS evidence unavailable"
              }
              completeness={metricCompleteness(epssState.status)}
            />
          </Section>

          <Section label="CISA KEV" sourceName="CISA KEV" itemLabel="KEV entries" state={kevState}>
            {kev.data?.cve.is_known_exploited && (
              <div className="card-body">
                <StatusBadge label="Known exploited" tone="critical" />
                <p>Due {kev.data.cve.kev_due_date || "—"}</p>
                <p>{kev.data.cve.kev_ransomware_use || "Ransomware use unknown"}</p>
              </div>
            )}
          </Section>

          <Section label="KB mapping" sourceName="MSRC KB mapping" itemLabel="KB mappings" state={kbState}>
            <div className="card-body">
              {kb.data?.cve.associated_kbs.map((kbId) => (
                <p key={kbId}>
                  <Link className="table-primary-link" href={kbHref(kbId)}>{kbId}</Link>
                </p>
              ))}
            </div>
          </Section>
        </>
      )}

      {data && (
        <RiskExceptionDialog
          mode="record"
          open={riskDialogOpen}
          onOpenChange={setRiskDialogOpen}
          returnFocusRef={riskInvokerRef}
          record={{
            cveId: data.cve.cve_id,
            targetScope: `${rows.length.toLocaleString("en-US")} loaded ${
              rows.length === 1 ? "target" : "targets"
            } · ${(findingPage?.contract.counts.represented ?? "unknown").toLocaleString?.() ?? "unknown"} represented · ${
              findingPage?.contract.counts.total ?? "unknown"
            } total · ${findingPage?.contract.counts.excluded ?? "unknown"} excluded`,
            affectedMetrics: [
              `Open exposure count (${findingPage?.contract.counts.excluded ?? "unknown"} excluded from represented results)`,
              "Patch priority count",
            ],
            evidenceFreshness: `Generation ${
              findingPage?.generation || findingState.generation || "unknown"
            } · ${common.metadata.freshnessState} as of ${
              common.metadata.observedAt || "an unknown time"
            }`,
            sessionApprover,
          }}
          onRecord={recordRiskException}
          onRefresh={refreshRiskEvidence}
          onRequestRevoke={(exceptionId) => {
            setRiskDialogOpen(false);
            setRevokeExceptionId(exceptionId);
          }}
        />
      )}

      {data && revokeExceptionId && (
        <RiskExceptionDialog
          mode="revoke"
          open={Boolean(revokeExceptionId)}
          onOpenChange={(open) => {
            if (!open) setRevokeExceptionId("");
          }}
          returnFocusRef={riskInvokerRef}
          exceptions={[
            {
              id: revokeExceptionId,
              label: `${data.cve.cve_id} risk exception`,
              targetScope: `${rows.length.toLocaleString("en-US")} represented targets`,
            },
          ]}
          representedScope={`${rows.length.toLocaleString("en-US")} represented targets`}
          onRevoke={revokeRiskException}
          onRefresh={refreshRiskEvidence}
        />
      )}

      {data && (
        <CopilotDrawer
          open={copilotOpen}
          onClose={() => setCopilotOpen(false)}
          contextLabel={data.cve.cve_id}
          snapshot={buildCopilotSnapshot({
            pageKind: "vulnerability",
            pageId: `cve:${data.cve.cve_id}`,
            scope,
            selectedResources: [{ resource_id: data.cve.cve_id, resource_type: "CVE", name: data.cve.cve_id }],
            evidence: copilotEvidenceRows(
              "cve",
              [...(core.envelope?.evidence ?? []), ...(attack.envelope?.evidence ?? [])],
              [data.cve, ...rows, ...(attack.data?.nodes ?? [])],
            ),
          })}
          starterQuestions={[
            { label: `Explain ${data.cve.cve_id}`, tool: "cve_detail", toolArguments: { cve_id: data.cve.cve_id } },
            { label: `Show the blast radius of ${data.cve.cve_id}`, tool: "cve_attack_path", toolArguments: { cve_id: data.cve.cve_id } },
          ]}
        />
      )}
    </div>
  );
}
