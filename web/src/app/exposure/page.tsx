"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import { SourceSectionState } from "@/components/exposure/SourceSectionState";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import {
  PageHeader,
  type AggregateCompleteness,
  type EvidenceFreshness,
  type PageHeaderCompleteness,
} from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import {
  type ExposureSectionResult,
  type ExposureSectionStatus,
  useExposureSection,
} from "@/hooks/useExposureSection";
import {
  DEFAULT_EXPOSURE_SORT,
  exposureQueryKey,
  exposureRetentionKey,
  type ExposureQueryState,
} from "@/lib/exposure-query-state";
import { useScope } from "@/lib/scope-context";
import {
  vulnerabilityApi,
} from "@/lib/services";
import { buildExposureCopilotContext } from "@/lib/copilot/page-adapters";
import type {
  Envelope,
  ExposureCommonContract,
  ExposureCursorPagination,
} from "@/lib/types";

interface OverviewSectionData<T> {
  value: T;
  loaded_count: number;
  total_count: number;
  contract: ExposureCommonContract;
}

interface OverviewSectionLike {
  status: ExposureSectionStatus;
  data: OverviewSectionData<unknown> | null;
  envelope: Envelope<OverviewSectionData<unknown>, ExposureCursorPagination> | null;
  metadata: ExposureSectionResult<unknown>["metadata"];
}

function finiteCount(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : undefined;
}

function loadedCount(value: unknown): number {
  if (Array.isArray(value)) return value.length;
  return value === null || value === undefined ? 0 : 1;
}

async function overviewSectionEnvelope<T>(
  queryState: ExposureQueryState,
  signal: AbortSignal,
  loadValue: () => Promise<Envelope<T>>,
): Promise<Envelope<OverviewSectionData<T>, ExposureCursorPagination>> {
  const [common, source] = await Promise.all([
    vulnerabilityApi.exposureOverview(queryState, { signal }),
    loadValue(),
  ]);
  const loaded = loadedCount(source.data);
  const sourceTotal = finiteCount(source.pagination?.total) ?? loaded;

  return {
    ...common,
    data: {
      value: source.data,
      loaded_count: loaded,
      total_count: sourceTotal,
      contract: common.data.contract,
    },
    evidence: [...common.evidence, ...source.evidence],
    warnings: [...(common.warnings ?? []), ...(source.warnings ?? [])],
    pagination: {
      limit: queryState.pageSize,
      total: sourceTotal,
      next_cursor: null,
    },
  };
}

function useOverviewSection<T>(
  sectionId: string,
  queryState: ExposureQueryState,
  loadValue: () => Promise<Envelope<T>>,
): ExposureSectionResult<OverviewSectionData<T>> {
  return useExposureSection<OverviewSectionData<T>>({
    queryKey: `${exposureQueryKey(queryState)}|overview-section=${sectionId}`,
    retentionKey: `${exposureRetentionKey(
      queryState,
    )}|overview-section=${sectionId}`,
    load: ({ signal }) =>
      overviewSectionEnvelope(queryState, signal, loadValue),
    isEmpty: (data) => data.loaded_count === 0,
  });
}

function withLocalMetadata<T>(
  section: ExposureSectionResult<OverviewSectionData<T>>,
): ExposureSectionResult<OverviewSectionData<T>> {
  const completeness = section.data?.contract.completeness;
  return {
    ...section,
    metadata: {
      ...section.metadata,
      loaded: section.data?.loaded_count ?? section.metadata.loaded,
      represented:
        finiteCount(completeness?.represented_connections) ??
        section.metadata.represented,
      expected:
        finiteCount(completeness?.expected_connections) ??
        section.metadata.expected,
      total: section.data?.total_count ?? section.metadata.total,
    },
  };
}

/** Projects a loaded Exposure section into the pure Copilot adapter contract. */
function toExposureCopilotSection<T>(
  section: ExposureSectionResult<OverviewSectionData<T>>,
) {
  const status = section.status;
  const available = status !== "unavailable" && status !== "loading";
  const freshness =
    status === "current" || status === "healthy-empty"
      ? ("fresh" as const)
      : status === "partial"
        ? ("partial" as const)
        : status === "stale"
          ? ("stale" as const)
          : ("unavailable" as const);
  return {
    value: section.data?.value,
    loadedCount: section.data?.loaded_count ?? 0,
    totalCount: section.data?.total_count ?? 0,
    freshness,
    available,
    observedAt: section.metadata.observedAt,
    evidence: section.envelope?.evidence ?? [],
  };
}

function pageCompleteness(
  sections: OverviewSectionLike[],
): PageHeaderCompleteness {
  const usable = sections.filter((section) => section.data !== null);
  let state: AggregateCompleteness;
  if (usable.length === 0) {
    state = "unavailable";
  } else if (
    sections.some(
      (section) =>
        section.status === "unavailable" ||
        section.status === "partial" ||
        section.status === "loading",
    )
  ) {
    state = "partial";
  } else if (sections.some((section) => section.status === "stale")) {
    state = "stale";
  } else {
    state = "complete";
  }

  const freshness: EvidenceFreshness = sections.some(
    (section) => section.status === "stale",
  )
    ? "stale"
    : sections.every(
          (section) =>
            section.status === "current" ||
            section.status === "healthy-empty",
        )
      ? "current"
      : "unknown";
  const completeness = usable[0]?.data?.contract.completeness;

  return {
    state,
    freshness,
    representedConnections: finiteCount(
      completeness?.represented_connections,
    ),
    expectedConnections: finiteCount(completeness?.expected_connections),
    representedCount:
      finiteCount(completeness?.represented) ??
      finiteCount(completeness?.represented_count),
    totalCount:
      finiteCount(completeness?.total) ??
      finiteCount(completeness?.total_count),
    excludedCount:
      finiteCount(completeness?.excluded) ??
      finiteCount(completeness?.excluded_count),
    excludedReasons: completeness?.excluded_reasons ?? [],
  };
}

function sectionCompleteness(
  status: ExposureSectionStatus,
): "complete" | "partial" | "stale" | "unavailable" {
  if (status === "current" || status === "healthy-empty") return "complete";
  if (status === "loading") return "unavailable";
  return status;
}

function sectionEvidenceCopy(section: OverviewSectionLike): string {
  const metadata = section.metadata;
  const details: string[] = [section.status];
  if (metadata.freshnessSourceFamily) {
    details.push(`source family ${metadata.freshnessSourceFamily}`);
  }
  if (metadata.freshnessThresholdSeconds !== undefined) {
    details.push(
      `freshness threshold ${metadata.freshnessThresholdSeconds.toLocaleString(
        "en-US",
      )} seconds`,
    );
  }
  if (metadata.observedAt) details.push(`observed ${metadata.observedAt}`);
  if (
    metadata.represented !== undefined &&
    metadata.expected !== undefined
  ) {
    details.push(
      `${metadata.represented.toLocaleString(
        "en-US",
      )} of ${metadata.expected.toLocaleString("en-US")} connections represented`,
    );
  }
  if (metadata.loaded !== undefined) {
    details.push(`${metadata.loaded.toLocaleString("en-US")} loaded`);
  }
  if (metadata.total !== undefined) {
    details.push(`${metadata.total.toLocaleString("en-US")} total`);
  }
  if (metadata.excluded !== undefined) {
    details.push(`${metadata.excluded.toLocaleString("en-US")} excluded`);
  }
  details.push(...metadata.excludedReasons);
  return details.join(" · ");
}

function countCopy(value: number | null | undefined): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString("en-US");
}

function countTone(
  value: number | null | undefined,
  alertTone: "critical" | "warning",
): "default" | "critical" | "warning" | "success" {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "default";
  }
  return value > 0 ? alertTone : "success";
}

function OverviewSection<T>({
  title,
  description,
  sourceName,
  itemLabel,
  section,
  action,
  children,
}: {
  title: string;
  description: string;
  sourceName: string;
  itemLabel: string;
  section: ExposureSectionResult<OverviewSectionData<T>>;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="card queue-card">
      <div className="card-header">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        {action}
      </div>
      <div className="card-body">
        <SourceSectionState
          sourceName={sourceName}
          itemLabel={itemLabel}
          state={section}
        >
          {children}
        </SourceSectionState>
      </div>
    </section>
  );
}

/**
 * Exposure landing page. Every decision summary owns its request lifecycle;
 * full operational queues remain on their dedicated routes.
 */
export default function ExposurePage() {
  const { scope } = useScope();
  const [copilotOpen, setCopilotOpen] = useState(false);
  const queryState = useMemo<ExposureQueryState>(
    () => ({
      scope,
      filters: {},
      sort: DEFAULT_EXPOSURE_SORT,
      pageSize: 50,
      cursor: null,
      cursorHistory: [],
      page: 1,
      target: "",
      drawer: "",
      generation: "",
    }),
    [scope],
  );

  const summary = withLocalMetadata(
    useOverviewSection("summary", queryState, () =>
      vulnerabilityApi.summary(scope),
    ),
  );
  const patches = withLocalMetadata(
    useOverviewSection("patch-priority-preview", queryState, () =>
      vulnerabilityApi.patchPriorities(scope, {}),
    ),
  );
  const assets = withLocalMetadata(
    useOverviewSection("asset-counts", queryState, () =>
      vulnerabilityApi.assetExposures(scope, {}),
    ),
  );
  const defender = withLocalMetadata(
    useOverviewSection("defender-overview", queryState, () =>
      vulnerabilityApi.defenderOverview(scope),
    ),
  );
  const sla = withLocalMetadata(
    useOverviewSection("sla", queryState, () =>
      vulnerabilityApi.slaCompliance(scope),
    ),
  );
  const riskExceptions = withLocalMetadata(
    useOverviewSection("risk-exceptions", queryState, () =>
      vulnerabilityApi.riskExceptions(scope),
    ),
  );

  const summaryValue = summary.data?.value;
  const patchRows = useMemo(
    () => patches.data?.value ?? [],
    [patches.data],
  );
  const bestPatch = patchRows[0];
  const assetRows = useMemo(
    () => assets.data?.value ?? [],
    [assets.data],
  );
  const defenderValue = defender.data?.value;
  const slaValue = sla.data?.value;
  const exceptionRows = useMemo(
    () => riskExceptions.data?.value ?? [],
    [riskExceptions.data],
  );
  const assetCounts = useMemo(
    () =>
      assetRows.reduce<Record<string, number>>((counts, asset) => {
        counts[asset.inventory_kind] = (counts[asset.inventory_kind] ?? 0) + 1;
        return counts;
      }, {}),
    [assetRows],
  );
  const assetSummary = Object.entries(assetCounts)
    .map(([kind, count]) => `${kind}: ${count.toLocaleString("en-US")}`)
    .join(" · ");
  const expiringExceptionCount = useMemo(() => {
    if (!riskExceptions.data) return null;
    const cutoff = Date.now() + 7 * 24 * 60 * 60 * 1000;
    return exceptionRows.reduce((count, exception) => {
      if (!exception.expires_at) return count;
      const expiresAt = Date.parse(exception.expires_at);
      return !Number.isNaN(expiresAt) && expiresAt <= cutoff
        ? count + 1
        : count;
    }, 0);
  }, [exceptionRows, riskExceptions.data]);

  const sections = [
    summary,
    patches,
    assets,
    defender,
    sla,
    riskExceptions,
  ] as unknown as OverviewSectionLike[];
  const aggregate = pageCompleteness(sections);
  const allUnavailable = sections.every(
    (section) => section.status === "unavailable",
  );
  const evidence = sections.flatMap(
    (section) => section.envelope?.evidence ?? [],
  );
  const warnings = sections.flatMap(
    (section) => section.envelope?.warnings ?? [],
  );
  const sourceStatus = Object.fromEntries(
    [
      ["Summary", summary],
      ["Patch priority preview", patches],
      ["Asset counts", assets],
      ["Defender overview", defender],
      ["SLA", sla],
      ["Risk exceptions", riskExceptions],
    ].map(([label, section]) => [
      label,
      sectionEvidenceCopy(section as unknown as OverviewSectionLike),
    ]),
  );
  const defenderCoverage = defenderValue?.coverage
    ? Object.values(defenderValue.coverage)
    : [];
  const availableDefenderSources = defenderCoverage.length
    ? defenderCoverage.filter((state) => state.availability === "available")
        .length
    : null;

  const exposureCopilot = buildExposureCopilotContext({
    scope,
    summary: toExposureCopilotSection(summary),
    patchPriorities: toExposureCopilotSection(patches),
    assets: toExposureCopilotSection(assets),
    defender: toExposureCopilotSection(defender),
    sla: toExposureCopilotSection(sla),
    riskExceptions: toExposureCopilotSection(riskExceptions),
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Exposure management"
        title="Which exposure should be reduced first?"
        description="Prioritize Defender for Cloud exposure across servers, containers, databases, storage, applications, and the rest of the discovered subscription inventory."
        completeness={aggregate}
        actions={
          <CopilotDrawerButton
            onClick={() => setCopilotOpen(true)}
            label="Ask Copilot about exposure"
          />
        }
        metadata={
          <>
            <span>
              {countCopy(summaryValue?.affected_business_service_count)} affected
              business services
            </span>
            <span>
              {countCopy(summaryValue?.affected_asset_count)} affected assets
            </span>
            <span>
              {countCopy(summaryValue?.defender_observed_asset_count)}{" "}
              Defender-observed vulnerable assets
            </span>
            <span>
              {assetSummary || "Subscription inventory grouping unavailable"}
            </span>
            <span>Patch recommendations are advisory</span>
          </>
        }
      />

      <EvidenceBar
        evidence={evidence}
        aggregateState={aggregate}
        knowledgeVersion={
          sections.find((section) => section.envelope?.knowledge_version)
            ?.envelope?.knowledge_version
        }
        warnings={warnings}
        fallbackTimestamp={sections.find(
          (section) => section.metadata.observedAt,
        )?.metadata.observedAt}
        sourceStatus={sourceStatus}
      />

      {allUnavailable && (
        <StatePanel
          title="Exposure intelligence is unavailable"
          message="No usable authorized Exposure partition remains. Retry the affected source sections; missing evidence is not treated as an all-clear state."
          tone="error"
        />
      )}

      <div className="exposure-landing-sections">
        <OverviewSection
          title="Exposure summary"
          description="Scoped vulnerability and reachability totals for the authorized environment."
          sourceName="Exposure summary"
          itemLabel="summary"
          section={summary}
        >
          <div className="metric-grid exposure-metrics">
            <MetricCard
              label="Critical CVEs"
              value={summaryValue?.critical_count}
              detail={
                summaryValue?.cve_count === undefined
                  ? "CVE total unavailable"
                  : `${summaryValue.cve_count.toLocaleString(
                      "en-US",
                    )} CVEs observed in the current scope`
              }
              tone={countTone(summaryValue?.critical_count, "critical")}
              completeness={sectionCompleteness(summary.status)}
            />
            <MetricCard
              label="Internet exposed"
              value={summaryValue?.internet_exposed_count}
              detail="Findings with an observed Internet-reachable path"
              tone={countTone(
                summaryValue?.internet_exposed_count,
                "critical",
              )}
              completeness={sectionCompleteness(summary.status)}
            />
          </div>
        </OverviewSection>

        <OverviewSection
          title="Asset counts"
          description="Affected resources grouped from the scoped subscription inventory."
          sourceName="Exposure asset counts"
          itemLabel="assets"
          section={assets}
        >
          <div className="metric-grid exposure-metrics">
            <MetricCard
              label="Exposed inventory"
              value={assets.data?.total_count}
              detail={
                assetSummary ||
                "Affected resource type counts are unavailable for this scope"
              }
              tone={countTone(summaryValue?.reachable_server_count, "warning")}
              completeness={sectionCompleteness(assets.status)}
            />
          </div>
        </OverviewSection>

        <OverviewSection
          title="Patch priority preview"
          description="The highest-value advisory action; the complete queue remains on Patch priorities."
          sourceName="Patch priority preview"
          itemLabel="patch priorities"
          section={patches}
          action={
            <Link className="button" href="/exposure/patch-priorities">
              Open Patch priorities →
            </Link>
          }
        >
          <div className="metric-grid exposure-metrics">
            <MetricCard
              label="Highest-value patch"
              value={bestPatch?.kb_id}
              detail={
                bestPatch
                  ? `Risk reduction score ${bestPatch.expected_risk_reduction.toLocaleString(
                      "en-US",
                    )}/100 across ${bestPatch.affected_business_service_count.toLocaleString(
                      "en-US",
                    )} business services`
                  : "Patch priority is unavailable"
              }
              tone="default"
              completeness={sectionCompleteness(patches.status)}
              action={
                bestPatch ? (
                  <Link
                    href={`/exposure/kbs/${encodeURIComponent(
                      bestPatch.kb_id,
                    )}`}
                  >
                    Open {bestPatch.kb_id} details
                  </Link>
                ) : undefined
              }
            />
          </div>
        </OverviewSection>

        <OverviewSection
          title="Defender overview"
          description="Alerts, attack paths, recommendations, and source coverage from Defender for Cloud."
          sourceName="Defender overview"
          itemLabel="posture signals"
          section={defender}
          action={
            <Link className="button" href="/exposure/defender-posture">
              Open Defender posture →
            </Link>
          }
        >
          <div className="metric-grid exposure-metrics">
            <MetricCard
              label="Active alerts"
              value={defenderValue?.active_alert_count}
              detail={
                defenderValue?.critical_alert_count === undefined
                  ? "Critical alert count unavailable"
                  : `${defenderValue.critical_alert_count.toLocaleString(
                      "en-US",
                    )} critical alerts`
              }
              tone={countTone(
                defenderValue?.critical_alert_count,
                "critical",
              )}
              completeness={sectionCompleteness(defender.status)}
            />
            <MetricCard
              label="Attack paths"
              value={defenderValue?.attack_path_count}
              detail="Exploitable routes reported by Defender CSPM"
              tone={countTone(defenderValue?.attack_path_count, "critical")}
              completeness={sectionCompleteness(defender.status)}
            />
            <MetricCard
              label="Defender recommendations"
              value={
                defenderValue?.unhealthy_recommendation_count ??
                summaryValue?.defender_posture_count ??
                summaryValue?.defender_recommendation_count
              }
              detail="Unhealthy recommendations across protected resource families"
              tone={countTone(
                defenderValue?.unhealthy_recommendation_count ??
                  summaryValue?.defender_posture_count ??
                  summaryValue?.defender_recommendation_count,
                "warning",
              )}
              completeness={sectionCompleteness(defender.status)}
            />
            <MetricCard
              label="Signal coverage"
              value={
                availableDefenderSources === null
                  ? null
                  : `${availableDefenderSources}/${defenderCoverage.length}`
              }
              detail="Unavailable sources remain unknown, never healthy"
              tone={
                availableDefenderSources === null
                  ? "default"
                  : availableDefenderSources === defenderCoverage.length
                    ? "success"
                    : "warning"
              }
              completeness={sectionCompleteness(defender.status)}
            />
          </div>
        </OverviewSection>

        <OverviewSection
          title="SLA status"
          description="Tracked finding compliance without classifying unknown first detection as overdue."
          sourceName="Exposure SLA"
          itemLabel="SLA reports"
          section={sla}
          action={
            <Link className="button" href="/exposure/patch-priorities">
              Review Patch priorities →
            </Link>
          }
        >
          <div className="metric-grid exposure-metrics">
            <MetricCard
              label="Overall compliance"
              value={
                slaValue?.overall_compliance_rate === null ||
                slaValue?.overall_compliance_rate === undefined
                  ? null
                  : `${(slaValue.overall_compliance_rate * 100).toFixed(1)}%`
              }
              detail={
                slaValue
                  ? `${slaValue.compliant_count.toLocaleString(
                      "en-US",
                    )} of ${slaValue.tracked_count.toLocaleString(
                      "en-US",
                    )} tracked findings within SLA`
                  : "SLA data unavailable"
              }
              tone={countTone(slaValue?.overdue_count, "warning")}
              completeness={sectionCompleteness(sla.status)}
            />
            <MetricCard
              label="Overdue findings"
              value={slaValue?.overdue_count}
              detail={
                slaValue
                  ? `${slaValue.open_count.toLocaleString(
                      "en-US",
                    )} total open findings`
                  : "SLA data unavailable"
              }
              tone={countTone(slaValue?.overdue_count, "critical")}
              completeness={sectionCompleteness(sla.status)}
            />
          </div>
        </OverviewSection>

        <OverviewSection
          title="Risk exceptions"
          description="Active governed exceptions and near-term expirations in the authorized scope."
          sourceName="Risk exceptions"
          itemLabel="risk exceptions"
          section={riskExceptions}
          action={
            <Link className="button" href="/exposure/patch-priorities">
              Review risk exceptions →
            </Link>
          }
        >
          <div className="metric-grid exposure-metrics">
            <MetricCard
              label="Active risk exceptions"
              value={
                riskExceptions.data ? riskExceptions.data.total_count : null
              }
              detail={
                expiringExceptionCount === null
                  ? "Expiration evidence unavailable"
                  : expiringExceptionCount > 0
                    ? `${expiringExceptionCount.toLocaleString(
                        "en-US",
                      )} expiring within 7 days`
                    : "None expiring within 7 days"
              }
              tone={countTone(expiringExceptionCount, "warning")}
              completeness={sectionCompleteness(riskExceptions.status)}
            />
          </div>
        </OverviewSection>
      </div>

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Vulnerability exposure"
        requestedScope={exposureCopilot.requestedScope}
        snapshot={exposureCopilot.snapshot}
        starterQuestions={exposureCopilot.starterQuestions}
      />
    </div>
  );
}
