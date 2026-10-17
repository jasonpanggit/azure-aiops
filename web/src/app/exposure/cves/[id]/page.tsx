"use client";

import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { useMsal } from "@azure/msal-react";
import { useRouter, useSearchParams } from "next/navigation";

import {
  RiskExceptionDialog,
  type RiskExceptionRecordRequest,
  type RiskExceptionRecordResult,
  type RiskExceptionRevokeRequest,
  type RiskExceptionRevokeResult,
} from "@/components/exposure/RiskExceptionDialog";
import { SourceFreshnessRail } from "@/components/exposure/SourceFreshnessRail";
import { CveFixMatrix } from "@/components/exposure/CveFixMatrix";
import { CveEvidence } from "@/components/exposure/CveEvidence";
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
import { StatePanel } from "@/components/ui/StatePanel";
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
import type { ScopeSelection } from "@/lib/scope";
import {
  useExposureSection,
  type ExposureSectionPresentation,
  type ExposureSectionResult,
} from "@/hooks/useExposureSection";
import { useScope } from "@/lib/scope-context";
import {
  vulnerabilityApi,
} from "@/lib/services";
import { buildCveDetailCopilotContext } from "@/lib/copilot/page-adapters";
import type {
  AttackPathGraph,
  CveDetail,
  Envelope,
  ExposureExternalCatalog,
  ExposureExternalCatalogItem,
  ExposureExternalCatalogSource,
  ExposureEnrichmentSourceState,
  ExposureCursorPagination,
  ExposureFinding,
  ExposureOverview,
  ExposurePage,
} from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

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

const ATTACK_PATH_TIMEOUT_MS = 15_000;

function boundedAttackPathRequest(
  cveId: string,
  scope: ScopeSelection,
  signal: AbortSignal,
): Promise<Envelope<AttackPathGraph>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ATTACK_PATH_TIMEOUT_MS);
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });

  return vulnerabilityApi
    .attackPath(cveId, scope, { signal: controller.signal })
    .finally(() => {
      if (timer !== undefined) clearTimeout(timer);
      signal.removeEventListener("abort", abort);
    });
}

function catalogSource(
  item: ExposureExternalCatalogItem | null,
  source: "nvd" | "epss" | "kev" | "msrc",
): ExposureExternalCatalogSource | null {
  const entries = Object.values(item?.sources ?? {});
  return (
    entries.find((entry) => entry.source.toLocaleLowerCase("en-US") === source) ??
    null
  );
}

function catalogSources(
  item: ExposureExternalCatalogItem | null,
  source: "msrc",
): ExposureExternalCatalogSource[] {
  return Object.values(item?.sources ?? {}).filter(
    (entry) => entry.source.toLocaleLowerCase("en-US") === source,
  );
}

function aggregateCatalogSources(
  sources: ExposureExternalCatalogSource[],
): ExposureExternalCatalogSource | null {
  if (sources.length === 0) return null;
  const succeeded = (source: ExposureExternalCatalogSource) =>
    ["success", "succeeded", "complete"].includes(
      source.status.toLocaleLowerCase("en-US"),
    );
  const unavailable = sources.find(
    (source) => !succeeded(source) && !source.has_last_known_good,
  );
  const stale = sources.find(
    (source) => source.stale || (!succeeded(source) && source.has_last_known_good),
  );
  const selected = unavailable ?? stale ?? sources[0];
  const observed = sources
    .map((source) => source.source_at || source.succeeded_at || source.attempted_at)
    .filter(Boolean)
    .sort()[0] ?? "";
  return {
    ...selected,
    source: "msrc",
    identifier: sources.map((source) => source.identifier).sort().join(","),
    status: unavailable || stale ? "failed" : "succeeded",
    stale: Boolean(stale),
    has_last_known_good: unavailable ? false : true,
    safe_error_code:
      unavailable?.safe_error_code || stale?.safe_error_code || "",
    source_at: observed,
    payload: null,
  };
}

function recordPayload(
  source: ExposureExternalCatalogSource | null,
): Record<string, unknown> {
  return source?.payload ?? {};
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function catalogDetail(
  cveId: string,
  item: ExposureExternalCatalogItem | null,
): CveDetail | null {
  if (!item) return null;
  const nvd = recordPayload(catalogSource(item, "nvd"));
  const epss = recordPayload(catalogSource(item, "epss"));
  const kev = recordPayload(catalogSource(item, "kev"));
  const cvss = nvd.cvss && typeof nvd.cvss === "object"
    ? (nvd.cvss as Record<string, unknown>)
    : {};
  const cvssPresent = Boolean(
    stringValue(cvss.version) || stringValue(cvss.vector),
  );
  const associatedKbs = new Set(stringArray(nvd.associated_kbs));
  for (const source of catalogSources(item, "msrc")) {
    const payload = recordPayload(source);
    const kbId = stringValue(payload.kb_id) || source.identifier;
    if (kbId) associatedKbs.add(kbId.toUpperCase());
  }
  return {
    cve: {
      cve_id: stringValue(nvd.cve_id) || item.cve_id || cveId,
      title: stringValue(nvd.title),
      description: stringValue(nvd.description),
      severity: stringValue(nvd.severity) || stringValue(cvss.severity) || "Unknown",
      cvss: {
        version: stringValue(cvss.version),
        base_score: cvssPresent ? finiteNumber(cvss.base_score) : null,
        vector: stringValue(cvss.vector),
        severity: stringValue(cvss.severity) || stringValue(nvd.severity) || "Unknown",
      },
      associated_kbs: Array.from(associatedKbs).sort(),
      epss_score: finiteNumber(epss.epss_score),
      epss_percentile: finiteNumber(epss.epss_percentile),
      is_known_exploited: Boolean(Object.keys(kev).length),
      kev_date_added: stringValue(kev.kev_date_added),
      kev_due_date: stringValue(kev.kev_due_date),
      kev_ransomware_use: stringValue(kev.kev_ransomware_use),
      exploit_references: Array.isArray(nvd.exploit_references)
        ? nvd.exploit_references.filter(
            (value): value is { url: string; source: string } =>
              Boolean(value) &&
              typeof value === "object" &&
              typeof (value as { url?: unknown }).url === "string" &&
              typeof (value as { source?: unknown }).source === "string",
          )
        : [],
    },
    exploitability_signals: [],
    affected_servers: [],
    affected_applications: [],
    affected_business_services: [],
    findings: [],
    recommended_patch: "",
  };
}

function presentSection<T>(
  section: ExposureSectionResult<T>,
  common: ExposureSectionResult<unknown>,
  {
    loaded,
    empty = false,
    source,
    requiresSource = false,
    inheritCommon = true,
  }: {
    loaded?: number;
    empty?: boolean;
    source?: ExposureEnrichmentSourceState | ExposureExternalCatalogSource | null;
    requiresSource?: boolean;
    inheritCommon?: boolean;
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
    // `total`/`excluded` must come from this section's own contract, not the
    // shared CVE-wide target-completeness overview — otherwise every
    // section (Attack path, NVD, EPSS, KEV, KB mapping) wrongly borrows the
    // overview's total/excluded regardless of its own record count.
    total: section.metadata.total,
    excluded: section.metadata.excluded,
    excludedReasons: section.metadata.excludedReasons,
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
    const sourceStatus = source.status.toLocaleLowerCase("en-US");
    const succeeded = ["success", "succeeded", "complete"].includes(sourceStatus);
    if (["partial", "degraded"].includes(sourceStatus) && source.has_last_known_good) {
      return { ...presentedSection, metadata, status: "partial" };
    }
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
  } else if (requiresSource) {
    return {
      ...presentedSection,
      metadata: {
        ...metadata,
        safeErrorMessage: "No durable source status was returned.",
      },
      error: new Error("No durable source status was returned."),
      status: "unavailable",
    };
  }
  if (empty) return { ...presentedSection, metadata, status: "healthy-empty" };
  const commonStatus = !inheritCommon
    ? "current"
    : common.data
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

function copilotSectionTrust(
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

function Section({
  label,
  sourceName,
  itemLabel,
  state,
  emptyMessage,
  children,
}: {
  label: string;
  sourceName: string;
  itemLabel: string;
  state: ExposureSectionPresentation;
  emptyMessage?: string;
  children?: React.ReactNode;
}) {  return (
    <section role="region" aria-label={`${label} section`}>
      <div className="card-header">
        <h2>{label}</h2>
      </div>
      <SourceSectionState
        sourceName={sourceName}
        itemLabel={itemLabel}
        state={state}
        emptyMessage={emptyMessage}
      >
        {children}
      </SourceSectionState>
    </section>
  );
}

function CveDetailBody({ params }: { params: { id: string } }) {
  const cveId = decodeURIComponent(params.id).toUpperCase();
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
  const containerOnly = findingState.filters.target_kind === "container_image";

  const common = useExposureSection<ExposureOverview>({
    queryKey: `${exposureQueryKey(findingState)}|common`,
    retentionKey: `${exposureRetentionKey(findingState)}|common`,
    refreshKey,
    load: ({ signal }) =>
      vulnerabilityApi.exposureOverview(findingState, { signal }),
  });
  const catalog = useExposureSection<
    ExposureExternalCatalog<ExposureExternalCatalogItem>
  >({
    queryKey: `${exposureRetentionKey(findingState)}|catalog|${cveId}`,
    refreshKey,
    load: ({ signal }) =>
      vulnerabilityApi.exposureExternalCatalog<ExposureExternalCatalogItem>(
        cveId,
        findingState.scope,
        { signal, generation: findingState.generation },
      ),
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
      containerOnly
        ? Promise.resolve({
            data: {
              cve_id: cveId,
              nodes: [],
              edges: [],
              reachable_server_count: 0,
              internet_exposed: false,
            },
            evidence: [],
            warnings: [],
            scope: findingState.scope,
            knowledge_version: findingState.generation,
            pagination: {
              limit: 0,
              total: 0,
              next_cursor: null,
            },
          })
        : cursorEnvelope(
            boundedAttackPathRequest(cveId, findingState.scope, signal),
          ),
    isEmpty: (graph) => graph.edges.length === 0,
  });

  const catalogItem = catalog.data?.item ?? null;
  const data = catalogDetail(cveId, catalogItem);
  const rows = findings.data?.items ?? [];
  const loadedBusinessServices = Array.from(
    new Set(
      rows
        .map((finding) => finding.business_service?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  ).sort();
  const coreState = presentSection(findings, common, {
    loaded: rows.length,
    empty: Boolean(findings.data && rows.length === 0),
  });
  const attackNotFound =
    typeof attack.error === "object" &&
    attack.error !== null &&
    "status" in attack.error &&
    attack.error.status === 404;
  const attackState = (() => {
    const base = presentSection(attack, common, {
      loaded: attack.data?.edges.length,
      empty: Boolean(attack.data && attack.data.edges.length === 0),
      inheritCommon: !containerOnly,
    });

    if (
      !containerOnly &&
      !attack.data &&
      attackNotFound &&
      coreState.status !== "unavailable"
    ) {
      return {
        ...base,
        status: "healthy-empty" as const,
        error: null,
        metadata: {
          ...base.metadata,
          safeErrorMessage: "",
        },
      };
    }

    return base;
  })();
  const nvdSource = catalogSource(catalogItem, "nvd");
  const epssSource = catalogSource(catalogItem, "epss");
  const kevSource = catalogSource(catalogItem, "kev");
  const msrcSources = catalogSources(catalogItem, "msrc");
  const msrcSource = aggregateCatalogSources(msrcSources);
  const nvdState = presentSection(catalog, common, {
    loaded: nvdSource ? 1 : 0,
    empty: Boolean(nvdSource && !data?.cve.cvss?.vector && !data?.cve.description),
    source: nvdSource,
    requiresSource: true,
    inheritCommon: false,
  });
  const epssState = presentSection(catalog, common, {
    loaded: data?.cve.epss_score !== null ? 1 : 0,
    empty: Boolean(epssSource && data?.cve.epss_score === null),
    source: epssSource,
    requiresSource: true,
    inheritCommon: false,
  });
  const kevState = presentSection(catalog, common, {
    loaded: data?.cve.is_known_exploited ? 1 : 0,
    empty: Boolean(kevSource && !data?.cve.is_known_exploited),
    source: kevSource,
    requiresSource: true,
    inheritCommon: false,
  });
  const kbState = presentSection(catalog, common, {
    loaded: data?.cve.associated_kbs.length ?? 0,
    empty: Boolean(catalog.data && data?.cve.associated_kbs.length === 0),
    source: msrcSource,
    requiresSource: true,
    inheritCommon: false,
  });
  const allStates = [coreState, attackState, nvdState, epssState, kevState, kbState];
  const headerState = aggregateCompleteness(allStates);
  const restartRequired = [common, catalog, findings, attack].some(
    (section) => section.restart.required,
  );
  const parentLabel = exposureDetailParentLabel(detailContext.origin);
  const backHref = exposureDetailReturnHref(queryState, detailContext);
  const currentDetailHref = exposureDetailHref(
    "cves",
    cveId,
    queryState,
    detailContext,
  );
  const findingPage = findings.data;
  const retainedQuery = useMemo(() => ({ ...findingState, generation: findingPage?.generation ?? findingState.generation }), [findingState, findingPage?.generation]);
  const first = rows.length ? (findingState.page - 1) * findingState.pageSize + 1 : 0;
  const last = rows.length ? first + rows.length - 1 : 0;
  const representedTargets = findingPage?.contract.counts.represented;
  const remediationGuidance = containerOnly
    ? "Review the owning workload and image provenance, then open the governed remediation workflow to plan an image rebuild or replacement. Exposure does not mutate workloads."
    : data?.cve.is_known_exploited
      ? `Treat this as an active exploitation priority${
          data.cve.kev_due_date ? ` with a CISA due date of ${data.cve.kev_due_date}` : ""
        }. Validate the recommended update against the represented assets before approval.`
      : typeof data?.cve.epss_score === "number" && data.cve.epss_score >= 0.5
        ? "Prioritize patch validation because durable EPSS evidence indicates elevated exploit probability. Confirm asset criticality and reachability before approval."
        : "Validate applicability, reachability, and business impact before scheduling the recommended update through the governed remediation workflow.";

  const kbHref = (kbId: string) =>
    exposureDetailHref("kbs", kbId, { ...queryState, generation: findings.data?.generation ?? queryState.generation }, detailContext);

  async function recordRiskException(
    request: RiskExceptionRecordRequest,
  ): Promise<RiskExceptionRecordResult> {
    try {
      const response = await vulnerabilityApi.acceptRisk({
        cve_id: request.cveId,
        reason: request.reason,
        expires_at: request.expiresAt
          ? new Date(request.expiresAt).toISOString()
          : undefined,
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

  const cveCopilot = buildCveDetailCopilotContext({
    scope,
    cveId,
    cve: data
      ? {
          ...data.cve,
          epss_score: data.cve.epss_score ?? undefined,
        }
      : null,
    findings: {
      rows,
      loadedCount: rows.length,
      totalCount: findingPage?.total_count ?? rows.length,
      available: copilotSectionTrust(coreState.status).available,
      freshness: copilotSectionTrust(coreState.status).freshness,
      observedAt: coreState.metadata.observedAt,
    },
    attack: containerOnly
      ? undefined
      : {
          graph: attack.data ?? null,
          available: copilotSectionTrust(attackState.status).available,
          freshness: copilotSectionTrust(attackState.status).freshness,
          observedAt: attackState.metadata.observedAt,
        },
    sources: [
      { key: "nvd", ...copilotSectionTrust(nvdState.status), observedAt: nvdState.metadata.observedAt },
      { key: "epss", ...copilotSectionTrust(epssState.status), observedAt: epssState.metadata.observedAt },
      { key: "kev", ...copilotSectionTrust(kevState.status), observedAt: kevState.metadata.observedAt },
      { key: "msrc", ...copilotSectionTrust(kbState.status), observedAt: kbState.metadata.observedAt },
    ],
    filters: {
      weakness_id: [cveId],
      page: [String(findingState.page)],
    },
    evidence: [
      ...(common.envelope?.evidence ?? []),
      ...(catalog.envelope?.evidence ?? []),
      ...(attack.envelope?.evidence ?? []),
    ],
  });

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
                )}&return_to=${encodeURIComponent(currentDetailHref)}`}
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

      <CopilotInsights
        snapshot={cveCopilot.snapshot}
        ready={!common.loading && !findings.loading}
        requestedScope={cveCopilot.requestedScope}
        contextLabel={data?.cve.cve_id ?? "CVE detail"}
        onOpenCopilot={() => setCopilotOpen(true)}
      />
      <EvidenceBar
        evidence={common.envelope?.evidence ?? catalog.envelope?.evidence}
        knowledgeVersion={common.envelope?.knowledge_version ?? catalog.envelope?.knowledge_version}
        warnings={common.envelope?.warnings ?? catalog.envelope?.warnings}
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
                  "cves",
                  cveId,
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

      <div className="exposure-detail-layout">
        <main className="exposure-detail-content">
          {coreState.status === "unavailable" && !data && rows.length === 0 ? (
            <SourceSectionState
              sourceName="Scoped CVE findings"
              itemLabel="findings"
              state={coreState}
            />
          ) : (
            <>
              <section className="exposure-detail-summary" aria-labelledby="executive-risk-summary">
                <div className="card-header">
                  <div>
                    <p className="eyebrow">Decision summary</p>
                    <h2 id="executive-risk-summary">Executive risk summary</h2>
                  </div>
                  <StatusBadge
                    label={data?.cve.severity || "Unknown severity"}
                    tone={statusTone(data?.cve.severity)}
                  />
                </div>
                <div className="exposure-risk-summary-body">
                  <div>
                    <p>
                      {data?.cve.description ||
                        "Risk detail is limited until durable NVD metadata is available."}
                    </p>
                  </div>
                  {data?.cve.cvss?.vector && (
                    <div className="exposure-summary-radar">
                      <CvssRadarChart vector={data.cve.cvss.vector} radius={68} />
                    </div>
                  )}
                </div>
                <div className="exposure-key-facts" aria-label="Key vulnerability facts">
                  <MetricCard
                    label="CVSS"
                    value={
                      typeof data?.cve.cvss?.base_score === "number"
                        ? data.cve.cvss.base_score.toFixed(1)
                        : null
                    }
                    unit="/10"
                    detail={data?.cve.cvss?.severity || "Base score unavailable"}
                    completeness={metricCompleteness(nvdState.status)}
                  />
                  <MetricCard
                    label="EPSS"
                    value={
                      typeof data?.cve.epss_score === "number"
                        ? (data.cve.epss_score * 100).toFixed(1)
                        : null
                    }
                    unit="%"
                    detail={
                      typeof data?.cve.epss_percentile === "number"
                        ? `${(data.cve.epss_percentile * 100).toFixed(0)}th percentile`
                        : "Exploit probability unavailable"
                    }
                    completeness={metricCompleteness(epssState.status)}
                  />
                  <MetricCard
                    label="CISA KEV"
                    value={
                      data?.cve.is_known_exploited === true
                        ? "Listed"
                        : kevState.status === "healthy-empty"
                          ? "Not listed"
                          : null
                    }
                    detail={
                      data?.cve.kev_due_date
                        ? `Due ${data.cve.kev_due_date}`
                        : "Catalog disposition only"
                    }
                    size="text"
                    completeness={metricCompleteness(kevState.status)}
                  />
                  <MetricCard
                    label="Active exposure"
                    value={representedTargets ?? null}
                    unit="targets"
                    detail={`${findingPage?.contract.counts.excluded ?? "Unknown"} excluded from represented scope`}
                    completeness={metricCompleteness(coreState.status)}
                  />
                </div>
              </section>

              <section className="exposure-detail-section" aria-labelledby="affected-assets-heading">
                <div className="card-header">
                  <h2 id="affected-assets-heading">Affected assets and workload coverage</h2>
                </div>
                <dl className="exposure-definition-grid">
                  <div>
                    <dt>Represented targets</dt>
                    <dd>{representedTargets?.toLocaleString("en-US") ?? "—"}</dd>
                  </div>
                  <div>
                    <dt>Loaded findings</dt>
                    <dd>{rows.length.toLocaleString("en-US")}</dd>
                  </div>
                  <div>
                    <dt>Target coverage</dt>
                    <dd>
                      {containerOnly
                        ? "Container images"
                        : findingState.filters.target_kind === "server"
                          ? "Servers"
                          : "Servers and container images"}
                    </dd>
                  </div>
                  <div>
                    <dt>Workload mapping</dt>
                    <dd>
                      {loadedBusinessServices.length > 0
                        ? `${loadedBusinessServices.length.toLocaleString("en-US")} mapped ${
                            loadedBusinessServices.length === 1 ? "service" : "services"
                          }`
                        : "—"}
                    </dd>
                  </div>
                </dl>
              </section>

              <section className="exposure-detail-section" aria-labelledby="remediation-guidance-heading">
                <div className="card-header">
                  <h2 id="remediation-guidance-heading">Risk-specific remediation guidance</h2>
                </div>
                <p>{remediationGuidance}</p>
                <p className="muted">
                  Selected update:{" "}
                  {data?.recommended_patch ? (
                    <Link className="table-primary-link" href={kbHref(data.recommended_patch)}>
                      {data.recommended_patch}
                    </Link>
                  ) : (
                    "None. Catalog associations do not establish applicability; review the fix evidence matrix."
                  )}
                  . Approval and execution remain in the governed remediation workflow.
                </p>
              </section>
              <CveFixMatrix cveId={cveId} catalog={catalog.data} catalogScope={catalog.envelope?.scope ?? {}}
                page={findingPage} pageScope={findings.envelope?.scope ?? {}} query={findingState} kbHref={kbHref} />

              {containerOnly ? (
                <section role="region" aria-label="Attack path section">
                  <div className="card-header">
                    <h2>Attack path</h2>
                  </div>
                  <StatePanel
                    title="Not applicable"
                    message="Attack paths are not applicable to container image targets."
                    tone="empty"
                  />
                </section>
              ) : (
                <Section
                  label="Attack path"
                  sourceName="Attack path"
                  itemLabel="supported paths"
                  state={attackState}
                  emptyMessage="No reachable attack path was found for this CVE. This can mean the affected resource is not internet-exposed or reachable from an entry point, or Defender for Cloud has not yet completed a vulnerability scan or attack path analysis for this resource. It does not necessarily indicate missing data."
                >
                  {attack.data && <AttackPathGraphView graph={attack.data} />}
                </Section>
              )}

              <Section
                label="Findings"
                sourceName="Scoped CVE findings"
                itemLabel="findings"
                state={coreState}
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
                  <div className="table-scroll exposure-responsive-table" role="region" aria-label="Scoped CVE findings table" tabIndex={0}>
                    <p className="table-scroll-hint">Scroll horizontally to see all columns</p>
                    <table className="operations-table exposure-table">
                      <caption>Authorized findings for {cveId}</caption>
                      <thead><tr><th>Target</th><th>Kind</th><th>Service</th><th>Severity</th><th>Patch</th><th>Risk status</th></tr></thead>
                      <tbody>
                        {rows.map((finding) => (
                          <tr key={finding.exposure_id} id={finding.exposure_id} tabIndex={-1}>
                            <td data-label="Target">
                              <strong className="resource-id-cell" title={finding.server_id || finding.target_id}>
                                {finding.server_id || finding.target_id}
                              </strong>
                            </td>
                            <td data-label="Kind" className="cell-nowrap">{finding.target_kind === "container_image" ? "Container image" : "Server"}</td>
                            <td data-label="Service" className="cell-nowrap">{finding.business_service || "Unmapped service"}</td>
                            <td data-label="Severity" className="cell-nowrap">{finding.severity || data?.cve.severity || "Unknown"}</td>
                            <td data-label="Patch" className="cell-nowrap">
                              {finding.missing_kb ? (
                                <Link className="table-primary-link" href={kbHref(finding.missing_kb)}>
                                  {finding.missing_kb}
                                </Link>
                              ) : "—"}
                            </td>
                            <td data-label="Risk status" className="cell-nowrap">{finding.risk_accepted ? "Risk accepted" : "Open"}</td>
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

              <Section label="Related KBs" sourceName="MSRC KB mapping" itemLabel="KB mappings" state={kbState}>
                <div className="exposure-related-links">
                  {data?.cve.associated_kbs.map((kbId) => (
                    <Link className="button button-quiet" href={kbHref(kbId)} key={kbId}>
                      {kbId}
                    </Link>
                  ))}
                </div>
              </Section>

              <Section label="CVSS technical disclosure" sourceName="NVD and CVSS" itemLabel="NVD records" state={nvdState}>
                {data && (
                  <dl className="exposure-technical-list">
                    <div>
                      <dt>Base score</dt>
                      <dd>
                        {typeof data.cve.cvss?.base_score === "number"
                          ? `${data.cve.cvss.base_score.toFixed(1)}/10`
                          : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt>Version</dt>
                      <dd>{data.cve.cvss?.version || "—"}</dd>
                    </div>
                    <div>
                      <dt>Vector</dt>
                      <dd className="cvss-vector-string">{data.cve.cvss?.vector || "—"}</dd>
                    </div>
                  </dl>
                )}
              </Section>
            </>
          )}
        </main>
        <SourceFreshnessRail
          items={[
            { key: "exposure", label: "Exposure findings", state: coreState },
            { key: "attack", label: "Attack path", state: attackState },
            {
              key: "nvd",
              label: "NVD / CVSS",
              state: nvdState,
              providerStatus: nvdSource?.status,
              hasLastKnownGood: nvdSource?.has_last_known_good,
            },
            {
              key: "epss",
              label: "EPSS",
              state: epssState,
              providerStatus: epssSource?.status,
              hasLastKnownGood: epssSource?.has_last_known_good,
            },
            {
              key: "kev",
              label: "CISA KEV",
              state: kevState,
              providerStatus: kevSource?.status,
              hasLastKnownGood: kevSource?.has_last_known_good,
            },
            {
              key: "msrc",
              label: "MSRC",
              state: kbState,
              providerStatus: msrcSource?.status,
              hasLastKnownGood: msrcSource?.has_last_known_good,
            },
          ]}
        />
      </div>

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

      <CveEvidence key={exposureQueryKey(retainedQuery)} cveId={cveId.toUpperCase()} query={retainedQuery}
        ready={Boolean(findingPage && catalog.data && findingPage.generation === catalog.data.generation
          && !findings.loading && !findings.retained && !catalog.loading && !catalog.retained && !restartRequired)} />
      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel={data?.cve.cve_id ?? cveId}
        requestedScope={cveCopilot.requestedScope}
        snapshot={cveCopilot.snapshot}
        starterQuestions={cveCopilot.starterQuestions}
      />
    </div>
  );
}

/** Isolates local CVE filters, dialogs and asynchronous evidence at the URL/scope boundary. */
export default function CveDetailPage({ params }: { params: { id: string } }) {
  const { scope } = useScope();
  const searchParams = useSearchParams();
  const query = parseExposureQueryState(new URLSearchParams(searchParams.toString()), { authorizedScope: scope });
  return <CveDetailBody key={`${params.id}:${exposureQueryKey(query)}`} params={params} />;
}
