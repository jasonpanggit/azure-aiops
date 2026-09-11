"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { CvssRadarChart } from "@/components/ui/CvssRadarChart";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { buildKbDetailCopilotContext } from "@/lib/copilot/page-adapters";
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
import { kbApi, vulnerabilityApi } from "@/lib/services";
import type {
  Envelope,
  ExposureCursorPagination,
  ExposureEnrichmentSourceState,
  ExposureFinding,
  ExposureOverview,
  ExposurePage,
  KbDetail,
} from "@/lib/types";

interface KbFindingRow extends ExposureFinding {
  cve_id?: string;
  server_id?: string;
  application?: string;
  business_service?: string;
  environment?: string;
  reachable?: boolean;
  network_exposure?: string;
  owner?: string;
  severity?: string;
}

const TARGET_KIND_OPTIONS = [
  { value: "server", label: "Servers" },
  { value: "container_image", label: "Container images" },
];

function cursorEnvelope<T>(
  promise: Promise<Envelope<T>>,
): Promise<Envelope<T, ExposureCursorPagination>> {
  return promise as unknown as Promise<Envelope<T, ExposureCursorPagination>>;
}

function sourceRecord(
  detail: KbDetail | null,
  source: string,
): ExposureEnrichmentSourceState | null {
  return (
    Object.values(detail?.enrichment?.sources ?? {}).find(
      (entry) => entry.source.toLocaleLowerCase("en-US") === source,
    ) ?? null
  );
}

function presentSection<T>(
  section: ExposureSectionResult<T>,
  common: ExposureSectionResult<ExposureOverview>,
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
      common.data?.contract.completeness.represented_connections ??
      common.metadata.represented,
    expected:
      common.data?.contract.completeness.expected_connections ??
      common.metadata.expected,
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
  const presented = {
    ...section,
    retrying: section.retrying || Boolean(section.loading && section.data),
  };
  if (section.loading && !section.data) return { ...presented, metadata, status: "loading" };
  if (source) {
    const succeeded = ["success", "succeeded", "complete"].includes(
      source.status.toLocaleLowerCase("en-US"),
    );
    if (source.stale || (!succeeded && source.has_last_known_good)) {
      return { ...presented, metadata, status: "stale" };
    }
    if (!succeeded && !source.has_last_known_good) {
      return {
        ...presented,
        metadata,
        error: new Error(
          source.safe_error_code || `${source.source} enrichment is unavailable`,
        ),
        status: "unavailable",
      };
    }
  }
  if (section.error) {
    return {
      ...presented,
      metadata,
      status: section.data ? "stale" : "unavailable",
    };
  }
  if (empty) return { ...presented, metadata, status: "healthy-empty" };
  return {
    ...presented,
    metadata,
    status: common.data
      ? common.status === "healthy-empty"
        ? "current"
        : common.status
      : "partial",
  };
}

function qualifySnapshot(
  state: ExposureSectionPresentation,
  snapshot: KbDetail["snapshot"],
): ExposureSectionPresentation {
  if (!snapshot) {
    return {
      ...state,
      status: ["loading", "unavailable", "stale"].includes(state.status)
        ? state.status
        : "partial",
      metadata: {
        ...state.metadata,
        freshnessSourceFamily: "aum",
        safeErrorMessage:
          state.metadata.safeErrorMessage || "Silver patch snapshot freshness is unavailable",
      },
    };
  }
  const completeness = snapshot.completeness.toLocaleLowerCase("en-US");
  const freshness = snapshot.freshness.toLocaleLowerCase("en-US");
  const status =
    completeness === "unavailable"
      ? "unavailable"
      : freshness === "stale" || completeness === "stale"
        ? "stale"
        : freshness !== "fresh"
          ? "partial"
        : completeness === "complete" || completeness === "healthy-empty"
            ? state.status
            : "partial";
  return {
    ...state,
    status,
    metadata: {
      ...state.metadata,
      observedAt: snapshot.as_of || state.metadata.observedAt,
      freshnessSourceFamily: "aum",
    },
  };
}

function aggregateCompleteness(
  states: ExposureSectionPresentation[],
): PageHeaderCompleteness {
  const rank = {
    current: 0,
    "healthy-empty": 0,
    stale: 1,
    partial: 2,
    loading: 3,
    unavailable: 4,
  };
  const worst = states.reduce((left, right) =>
    rank[right.status] > rank[left.status] ? right : left,
  );
  const state =
    worst.status === "current" || worst.status === "healthy-empty"
      ? "complete"
      : worst.status === "loading" || worst.status === "unavailable"
        ? "unavailable"
        : worst.status;
  return {
    state,
    freshness: state === "complete" ? "current" : state === "stale" ? "stale" : "unknown",
    representedConnections: worst.metadata.represented,
    expectedConnections: worst.metadata.expected,
    representedCount: worst.metadata.loaded,
    totalCount: worst.metadata.total,
    excludedCount: worst.metadata.excluded,
    excludedReasons: worst.metadata.excludedReasons,
  };
}

function metricCompleteness(
  status: ExposureSectionPresentation["status"],
): "complete" | "partial" | "stale" | "unavailable" {
  if (status === "current" || status === "healthy-empty") return "complete";
  if (status === "loading") return "unavailable";
  return status;
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
      <div className="card-header"><h2>{label}</h2></div>
      <SourceSectionState sourceName={sourceName} itemLabel={itemLabel} state={state}>
        {children}
      </SourceSectionState>
    </section>
  );
}

/** Scoped KB detail with independent metadata, MSRC, and finding state. */
function kbSectionTrust(
  status: ExposureSectionPresentation["status"],
): { available: boolean; freshness: "fresh" | "partial" | "stale" | "unavailable" } {
  const available = status !== "unavailable" && status !== "loading";
  const freshness =
    status === "current" || status === "healthy-empty"
      ? ("fresh" as const)
      : status === "partial"
        ? ("partial" as const)
        : status === "stale"
          ? ("stale" as const)
          : ("unavailable" as const);
  return { available, freshness };
}

function kbCopilotEnrichmentSources(
  detail: ExposureSectionResult<KbDetail>,
  common: ExposureSectionResult<ExposureOverview>,
) {
  const priority = { fresh: 0, partial: 1, stale: 2, unavailable: 3 } as const;
  const grouped = new Map<string, {
    key: string;
    available: boolean;
    freshness: "fresh" | "partial" | "stale" | "unavailable";
    observedAt?: string;
  }>();
  for (const source of Object.values(detail.data?.enrichment?.sources ?? {})) {
    const state = presentSection(detail, common, { source });
    const trust = kbSectionTrust(state.status);
    const key = source.source.toLocaleLowerCase("en-US");
    const current = grouped.get(key);
    if (!current || priority[trust.freshness] > priority[current.freshness]) {
      grouped.set(key, {
        key,
        ...trust,
        observedAt: state.metadata.observedAt,
      });
    }
  }
  return Array.from(grouped.values()).sort((left, right) =>
    left.key.localeCompare(right.key, "en-US"));
}

function qualifyAssociationState(
  state: ExposureSectionPresentation,
  enrichmentStates: ExposureSectionPresentation[],
): ExposureSectionPresentation {
  if (state.status === "loading" || state.status === "unavailable") return state;
  if (enrichmentStates.some((item) =>
    item.status === "unavailable" || item.status === "partial")) {
    return { ...state, status: "partial" };
  }
  if (enrichmentStates.some((item) => item.status === "stale")) {
    return { ...state, status: "stale" };
  }
  return state;
}

export default function KbDetailPage({ params }: { params: { id: string } }) {
  const decodedKbId = decodeURIComponent(params.id).trim().toLocaleUpperCase("en-US");
  const kbMatch = /^(?:KB)?(\d{4,})$/.exec(decodedKbId);
  const kbId = kbMatch ? `KB${kbMatch[1]}` : decodedKbId;
  const { scope } = useScope();
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
    filters: { ...queryState.filters, weakness_id: kbId },
    cursor: null,
    cursorHistory: [],
    page: 1,
  }));
  const [copilotOpen, setCopilotOpen] = useState(false);

  const common = useExposureSection<ExposureOverview>({
    queryKey: `${exposureQueryKey(findingState)}|common`,
    retentionKey: `${exposureRetentionKey(findingState)}|common`,
    load: ({ signal }) =>
      vulnerabilityApi.exposureOverview(findingState, { signal }),
  });
  const detail = useExposureSection<KbDetail>({
    queryKey: `kb-detail|${kbId}|${JSON.stringify(findingState.scope)}`,
    load: ({ signal }) =>
      cursorEnvelope(kbApi.detail(kbId, findingState.scope, { signal })),
    isEmpty: () => false,
  });
  const findings = useExposureSection<ExposurePage<KbFindingRow>>({
    queryKey: `${exposureQueryKey(findingState)}|findings|${kbId}`,
    retentionKey: `${exposureRetentionKey(findingState)}|findings|${kbId}`,
    load: ({ signal }) =>
      vulnerabilityApi.exposureItems(findingState, { signal }) as Promise<
        Envelope<ExposurePage<KbFindingRow>, ExposureCursorPagination>
      >,
    isEmpty: (page) => page.items.length === 0,
  });

  const data = detail.data;
  const rows = findings.data?.items ?? [];
  const metadataState = qualifySnapshot(
    presentSection(detail, common, { loaded: data ? 1 : 0 }),
    data?.snapshot,
  );
  const enrichmentStates = Object.values(detail.data?.enrichment?.sources ?? {}).map(
    (source) => presentSection(detail, common, { source }),
  );
  const msrcState = qualifyAssociationState(
    presentSection(detail, common, {
      loaded: detail.data?.cves.length ?? 0,
      empty: Boolean(detail.data && detail.data.cves.length === 0),
      source: sourceRecord(detail.data, "msrc"),
    }),
    enrichmentStates,
  );
  const findingsState = presentSection(findings, common, {
    loaded: rows.length,
    empty: Boolean(findings.data && rows.length === 0),
  });
  const headerState = aggregateCompleteness([
    metadataState,
    msrcState,
    ...enrichmentStates,
    findingsState,
  ]);
  const restartRequired = [common, detail, findings].some(
    (section) => section.restart.required,
  );
  const parentLabel = exposureDetailParentLabel(detailContext.origin);
  const backHref = exposureDetailReturnHref(queryState, detailContext);
  const currentDetailHref = exposureDetailHref(
    "kbs",
    kbId,
    queryState,
    detailContext,
  );
  const findingPage = findings.data;
  const first = rows.length ? (findingState.page - 1) * findingState.pageSize + 1 : 0;
  const last = rows.length ? first + rows.length - 1 : 0;
  const cveHref = (cveId: string) =>
    exposureDetailHref("cves", cveId, queryState, detailContext);

  // Read-only contextual Copilot over the already-loaded KB evidence. Governed
  // remediation stays behind the existing server workflow (D-03, D-04, D-10).
  const kbCopilot = buildKbDetailCopilotContext({
    scope,
    kbId,
    kb: data
      ? {
          kb_id: data.kb_id,
          title: data.title,
          severity: data.severity,
          published_at: data.published_at,
          cve_ids: data.cve_ids,
          affected_servers: data.affected_servers,
          affected_server_count: data.affected_server_count,
          affected_servers_truncated: data.affected_servers_truncated,
          affected_business_services: data.affected_business_services,
        }
      : null,
    findings: {
      rows: rows.map((row) => ({
        target_id: row.target_id,
        server_id: row.server_id,
        cve_id: row.cve_id,
        application: row.application,
        business_service: row.business_service,
        environment: row.environment,
        severity: row.severity,
        reachable: row.reachable,
        network_exposure: row.network_exposure,
        missing_kb: data?.kb_id,
      })),
      loadedCount: rows.length,
      totalCount: findingPage?.total_count ?? rows.length,
      available: kbSectionTrust(findingsState.status).available,
      freshness: kbSectionTrust(findingsState.status).freshness,
      observedAt: findingsState.metadata.observedAt,
    },
    sources: [
      {
        key: "silver_patch_snapshot",
        ...kbSectionTrust(metadataState.status),
        observedAt: metadataState.metadata.observedAt,
      },
      ...kbCopilotEnrichmentSources(detail, common),
    ],
    filters: {
      target_kind: [findingState.filters.target_kind ?? "all"],
      page: [String(findingState.page)],
    },
    evidence: [
      ...(common.envelope?.evidence ?? []),
      ...(detail.envelope?.evidence ?? []),
    ],
  });

  return (
    <div className="page-container exposure-detail-page">
      <div className="breadcrumb">
        <Link href="/exposure">Exposure</Link>
        <span>/</span>
        <Link href={backHref}>{parentLabel}</Link>
        <span>/</span>
        <span>{data?.kb_id ?? kbId}</span>
      </div>
      <PageHeader
        eyebrow="Patch investigation"
        title={data?.kb_id ?? kbId}
        description={data?.title || "Scoped security-update evidence and affected findings."}
        completeness={headerState}
        actions={
          <>
            <Link className="button button-quiet" href={backHref}>
              Back to {parentLabel}
            </Link>
            <CopilotDrawerButton
              onClick={() => setCopilotOpen(true)}
              label={`Ask Copilot about ${data?.kb_id ?? kbId}`}
            />
            {data && (
              <Link
                className="button button-primary"
                href={`/remediation?kb=${encodeURIComponent(data.kb_id)}&cve=${encodeURIComponent(
                  data.cve_ids[0] || "",
                )}&generation=${encodeURIComponent(findingState.generation)}&return_to=${encodeURIComponent(
                  currentDetailHref,
                )}`}
              >
                Open governed remediation
              </Link>
            )}
          </>
        }
        metadata={
          data ? (
            <>
              <StatusBadge label={data.severity} tone={statusTone(data.severity)} />
              <span>{rows.length.toLocaleString("en-US")} loaded findings</span>
            </>
          ) : undefined
        }
      />
      <EvidenceBar
        evidence={common.envelope?.evidence ?? detail.envelope?.evidence}
        knowledgeVersion={common.envelope?.knowledge_version ?? detail.envelope?.knowledge_version}
        warnings={common.envelope?.warnings ?? detail.envelope?.warnings}
        aggregateState={headerState}
      />

      {restartRequired && (
        <div className="callout callout-warning" role="alert">
          <p>The retained Exposure generation expired. Restart from the first page to continue safely.</p>
          <button
            type="button"
            className="button"
            onClick={() =>
              router.replace(
                exposureDetailHref(
                  "kbs",
                  kbId,
                  restartExposureQuery(queryState),
                  detailContext,
                ),
                { scroll: false },
              )
            }
          >
            Restart results
          </button>
        </div>
      )}

      {metadataState.status === "unavailable" && !data && rows.length === 0 ? (
        <SourceSectionState
          sourceName="KB metadata"
          itemLabel="KB metadata"
          state={metadataState}
        />
      ) : (
        <>
          <Section label="KB metadata" sourceName="KB metadata" itemLabel="KB metadata" state={metadataState}>
            <div className="metric-grid">
              <MetricCard
                label="Severity"
                value={data?.severity || null}
                detail={data?.title || "Security update title unavailable"}
                size="text"
                completeness={metricCompleteness(metadataState.status)}
              />
              <MetricCard
                label="Published"
                value={data?.published_at ? `Published ${data.published_at}` : null}
                detail="MSRC Security Update Guide"
                size="text"
                completeness={metricCompleteness(metadataState.status)}
              />
              <MetricCard
                label="Affected targets"
                value={findingPage?.contract.counts.represented ?? null}
                unit="targets"
                detail={`${findingPage?.contract.counts.excluded ?? "Unknown"} excluded from this represented scope`}
                completeness={metricCompleteness(findingsState.status)}
              />
            </div>
          </Section>

          <Section
            label="MSRC CVE associations"
            sourceName="MSRC CVE associations"
            itemLabel="CVE associations"
            state={msrcState}
          >
            <div className="table-scroll exposure-responsive-table" role="region" aria-label="MSRC CVE association table" tabIndex={0}>
              <p className="table-scroll-hint">Scroll horizontally to see all columns</p>
              <table className="operations-table exposure-table">
                <caption>CVEs associated with {kbId} by MSRC</caption>
                <thead><tr><th>CVE</th><th>Severity</th><th>CVSS score</th><th>CVSS vector</th></tr></thead>
                <tbody>
                  {detail.data?.cves.map((cve) => (
                    <tr key={cve.cve_id}>
                      <td>
                        <Link className="table-primary-link" href={cveHref(cve.cve_id)}>
                          {cve.cve_id}
                        </Link>
                        <div className="table-secondary">{cve.title}</div>
                      </td>
                      <td><StatusBadge label={cve.cvss?.severity || cve.severity} tone={statusTone(cve.cvss?.severity || cve.severity)} compact /></td>
                      <td>{typeof cve.cvss?.base_score === "number" && Number.isFinite(cve.cvss.base_score) ? `${cve.cvss.base_score.toFixed(1)}/10` : "—"}</td>
                      <td>{cve.cvss?.vector ? <CvssRadarChart vector={cve.cvss.vector} radius={26} compact /> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section
            label="Affected findings"
            sourceName="Affected findings"
            itemLabel="findings"
            state={findingsState}
          >
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
              <div className="table-scroll exposure-responsive-table" role="region" aria-label="Affected KB findings table" tabIndex={0}>
                <p className="table-scroll-hint">Scroll horizontally to see all columns</p>
                <table className="operations-table exposure-table">
                  <caption>Authorized targets missing {kbId}</caption>
                  <thead><tr><th>Target</th><th>CVE</th><th>Kind</th><th>Service</th><th>Severity</th></tr></thead>
                  <tbody>
                    {rows.map((finding) => {
                      const cveId = finding.cve_id || (
                        finding.weakness_id.startsWith("CVE-")
                          ? finding.weakness_id
                          : ""
                      );
                      return (
                        <tr key={finding.exposure_id} id={finding.exposure_id} tabIndex={-1}>
                          <td><strong>{finding.server_id || finding.target_id}</strong></td>
                          <td>{cveId ? <Link className="table-primary-link" href={cveHref(cveId)}>{cveId}</Link> : "—"}</td>
                          <td>{finding.target_kind === "container_image" ? "Container image" : "Server"}</td>
                          <td>{finding.business_service || "Unmapped service"}</td>
                          <td>{finding.severity || data?.severity || "Unknown"}</td>
                        </tr>
                      );
                    })}
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
        </>
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel={data?.kb_id ?? kbId}
        requestedScope={kbCopilot.requestedScope}
        snapshot={kbCopilot.snapshot}
        starterQuestions={kbCopilot.starterQuestions}
      />
    </div>
  );
}
