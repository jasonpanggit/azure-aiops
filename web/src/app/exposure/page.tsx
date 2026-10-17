"use client";

import Link from "next/link";
import { Suspense, useCallback, useMemo, useState, type ReactNode } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { SourceSectionState } from "@/components/exposure/SourceSectionState";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { CountBarChart } from "@/components/ui/CountBarChart";
import { DonutChart } from "@/components/ui/DonutChart";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { RiskGauge } from "@/components/ui/RiskGauge";
import {
  PageHeader,
  type AggregateCompleteness,
  type EvidenceFreshness,
  type PageHeaderCompleteness,
} from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { statusTone, toneColor } from "@/components/ui/StatusBadge";
import {
  type ExposureSectionResult,
  type ExposureSectionStatus,
  useExposureSection,
} from "@/hooks/useExposureSection";
import { buildExposureCopilotContext } from "@/lib/copilot/page-adapters";
import {
  DEFAULT_EXPOSURE_SORT,
  encodeExposureQueryState,
  exposureDetailHref,
  exposureQueryKey,
  exposureRetentionKey,
  type ExposureQueryState,
} from "@/lib/exposure-query-state";
import { useScope } from "@/lib/scope-context";
import { ScopeBookmarkError, scopedBookmark, scopeToSearchParams, type ScopeSelection } from "@/lib/scope";
import { vulnerabilityApi } from "@/lib/services";
import type {
  ExposureFacets,
  ExposureFinding,
} from "@/lib/types";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

const OVERVIEW_FACETS = [
  "severity",
  "target_kind",
  "source_family",
  "sla_state",
  "completeness",
  "current_state",
] as const;

interface OverviewFinding extends ExposureFinding {
  weakness_kind?: string;
  severity?: string;
  source_family?: string;
  current_state?: string;
  sla_state?: string;
  priority_score?: number | null;
  recommendation?: string;
}

interface OverviewSectionProps<T> {
  title: string;
  description: string;
  sourceName: string;
  itemLabel: string;
  section: ExposureSectionResult<T>;
  action?: ReactNode;
  children?: ReactNode;
}

function sectionCompleteness(
  status: ExposureSectionStatus,
): "complete" | "partial" | "stale" | "unavailable" {
  if (status === "current" || status === "healthy-empty") return "complete";
  if (status === "loading") return "unavailable";
  return status;
}

function pageCompleteness(
  primary: ExposureSectionResult<ExposureFacets>,
): PageHeaderCompleteness {
  const usable = primary.data;
  const statuses = [primary.status];
  let state: AggregateCompleteness;
  if (!usable) state = "unavailable";
  else if (statuses.some((status) => status === "partial" || status === "unavailable" || status === "loading")) state = "partial";
  else if (statuses.some((status) => status === "stale")) state = "stale";
  else state = "complete";

  const freshness: EvidenceFreshness = statuses.some((status) => status === "stale")
    ? "stale"
    : statuses.every((status) => status === "current" || status === "healthy-empty")
      ? "current"
      : "unknown";
  const completeness = usable?.contract.completeness;
  return {
    state,
    freshness,
    representedConnections: completeness?.represented_connections,
    expectedConnections: completeness?.expected_connections,
    representedCount: completeness?.represented ?? completeness?.represented_count,
    totalCount: completeness?.total ?? completeness?.total_count,
    excludedCount: completeness?.excluded ?? completeness?.excluded_count,
    excludedReasons: completeness?.excluded_reasons ?? [],
  };
}

function facetCount(
  facets: ExposureFacets | null,
  name: string,
  value: string,
): number | null {
  if (!facets || !Object.hasOwn(facets.facets, name)) return null;
  const folded = value.toLocaleLowerCase("en-US");
  const match = (facets.facets[name] ?? []).find(
    (item) => item.value.toLocaleLowerCase("en-US") === folded,
  );
  return match?.count ?? 0;
}

function facetCountMatching(
  facets: ExposureFacets | null,
  name: string,
  predicate: (value: string) => boolean,
): number | null {
  if (!facets || !Object.hasOwn(facets.facets, name)) return null;
  return (facets.facets[name] ?? []).reduce(
    (total, item) => total + (predicate(item.value) ? item.count : 0),
    0,
  );
}

function displayFacet(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toLocaleUpperCase("en-US"));
}

function countTone(
  value: number | null,
  alertTone: "critical" | "warning",
): "default" | "critical" | "warning" | "success" {
  if (value === null) return "default";
  return value > 0 ? alertTone : "success";
}

function priorityHref(item: OverviewFinding, state: ExposureQueryState): string {
  const segment = item.weakness_kind === "kb" ? "kbs" : "cves";
  return exposureDetailHref(segment, item.weakness_id, state, {
    origin: "/exposure", row: item.exposure_id, scroll: null,
  });
}

function sourceStatus<T>(section: ExposureSectionResult<T>): string {
  const metadata = section.metadata;
  const details: string[] = [section.status];
  if (metadata.observedAt) details.push(`observed ${metadata.observedAt}`);
  if (metadata.total !== undefined) details.push(`${metadata.total.toLocaleString("en-US")} total`);
  return details.join(" · ");
}

function OverviewSection<T>({
  title,
  description,
  sourceName,
  itemLabel,
  section,
  action,
  children,
}: OverviewSectionProps<T>) {
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
        <SourceSectionState sourceName={sourceName} itemLabel={itemLabel} state={section}>
          {children}
        </SourceSectionState>
      </div>
    </section>
  );
}

/** Exposure Overview backed only by bounded, generation-pinned Fabric SQL reads. */
export default function ExposurePage() {
  return <Suspense fallback={<StatePanel title="Reading exposure bookmark" message="Validating the selected scope and generation before reading findings." tone="loading" />}><ScopedExposure /></Suspense>;
}

function ScopedExposure() {
  const { scope } = useScope();
  const search = useSearchParams();
  let effectiveScope: ScopeSelection;
  let generation = "";
  try {
    effectiveScope = scopedBookmark(search, scope);
    if (search.has("generation")) {
      generation = search.get("generation") ?? "";
      if (search.getAll("generation").length !== 1 || !/^[a-zA-Z0-9._:-]{1,256}$/.test(generation)) {
        throw new ScopeBookmarkError("Use one exact exposure generation of at most 256 letters, digits, dots, underscores, colons or hyphens.");
      }
    }
  } catch (error) {
    if (!(error instanceof ScopeBookmarkError)) throw error;
    const query = scopeToSearchParams(scope);
    return <main className="page-container"><StatePanel title="Exposure bookmark unavailable" message={error.message} tone="error" /><Link className="button" href={`/exposure${query.size ? `?${query}` : ""}`}>Clear exposure bookmark</Link></main>;
  }
  return <ExposureOverview key={`${JSON.stringify(effectiveScope)}::${generation}`} scope={effectiveScope} generation={generation} />;
}

function ExposureOverview({ scope, generation }: { scope: ScopeSelection; generation: string }) {
  const router = useRouter();
  const [copilotOpen, setCopilotOpen] = useState(false);
  const queryState = useMemo<ExposureQueryState>(
    () => ({
      scope,
      filters: {},
      sort: DEFAULT_EXPOSURE_SORT,
      pageSize: 25,
      cursor: null,
      cursorHistory: [],
      page: 1,
      target: "",
      drawer: "",
      generation,
    }),
    [scope, generation],
  );

  const facets = useExposureSection<ExposureFacets>({
    queryKey: `${exposureQueryKey(queryState)}|overview=facets`,
    retentionKey: `${exposureRetentionKey(queryState)}|overview=facets`,
    load: ({ signal }) =>
      vulnerabilityApi.exposureFacets(queryState, [...OVERVIEW_FACETS], { signal }),
    isEmpty: (data) => data.total_count === 0,
  });
  const facetData = facets.data;
  const critical = facetCount(facetData, "severity", "critical");
  const high = facetCount(facetData, "severity", "high");
  const medium = facetCount(facetData, "severity", "medium");
  const serverFindings = facetCount(facetData, "target_kind", "server");
  const imageFindings = facetCount(facetData, "target_kind", "container_image");
  const defenderFindings = facetCount(
    facetData,
    "source_family",
    "defender_image",
  );
  const aumFindings = facetCountMatching(
    facetData,
    "source_family",
    (value) => {
      const normalized = value.toLocaleLowerCase("en-US");
      return normalized.includes("aum") || normalized.startsWith("azure_update_manager");
    },
  );
  const aggregate = pageCompleteness(facets);
  const allUnavailable = !facetData && !facets.loading;
  const evidence = facets.envelope?.evidence ?? [];
  const warnings = facets.envelope?.warnings ?? [];
  const knowledgeVersion = facetData?.generation;
  const observedAt = facets.metadata.observedAt;
  const loadedQuery = { ...queryState, generation: facetData?.generation ?? generation };
  const collectionHref = (path: string) => `${path}?${encodeExposureQueryState(loadedQuery)}`;

  const severityBreakdown = useMemo(() => {
    const order = ["critical", "high", "medium", "low", "unknown"];
    const items = facetData?.facets.severity ?? [];
    const byValue = new Map(items.map((item) => [item.value.toLocaleLowerCase("en-US"), item]));
    const extra = items.filter((item) => !order.includes(item.value.toLocaleLowerCase("en-US")));
    const canonical = order.map((key) => byValue.get(key) ?? { value: key, count: 0 });
    return [...canonical, ...extra].map((item) => ({
      label: displayFacet(item.value),
      value: item.count,
      color: toneColor(statusTone(item.value)),
      filterValue: item.value.toLocaleLowerCase("en-US"),
    }));
  }, [facetData]);

  const goToSeverity = useCallback(
    (value: string) => {
      const query = encodeExposureQueryState({
        ...queryState,
        generation: facetData?.generation ?? generation,
        filters: { severity: value },
      });
      router.push(`/exposure/patch-priorities?${query}`);
    },
    [router, queryState, facetData?.generation, generation],
  );

  const targetKindBreakdown = useMemo(
    () =>
      (facetData?.facets.target_kind ?? [])
        .slice()
        .sort((a, b) => b.count - a.count)
        .map((item) => ({ id: item.value, label: displayFacet(item.value), value: item.count })),
    [facetData],
  );

  const slaCounts = useMemo(() => {
    const items = facetData?.facets.sla_state ?? [];
    let scored = 0, overdue = 0, unclassified = 0;
    for (const item of items) {
      const state = item.value.toLocaleLowerCase("en-US");
      if (state === "overdue" || state === "within_sla") {
        scored += item.count;
        if (state === "overdue") overdue += item.count;
      } else unclassified += item.count;
    }
    return { scored, overdue, unclassified, percent: scored ? Math.round(overdue / scored * 100) : null };
  }, [facetData]);
  const topFindings = (facetData?.items ?? []).slice(0, 3) as OverviewFinding[];
  const copilotFreshness = facets.status === "current"
    ? "fresh" as const
    : facets.status === "stale"
      ? "stale" as const
      : facets.status === "partial"
        ? "partial" as const
        : "unavailable" as const;
  const exposureCopilot = buildExposureCopilotContext({
    scope,
    filters: {},
    sort: { field: queryState.sort.field, direction: queryState.sort.direction },
    records: topFindings.map((item, index) => ({
      identity: item.exposure_id,
      namespace: "vulnerability",
      kind: "exposure_finding",
      source: "fabric_sql",
      resourceId: item.target_id,
      observedAt,
      priority: index,
      data: {
        weakness_id: item.weakness_id,
        weakness_kind: item.weakness_kind,
        target_kind: item.target_kind,
        severity: item.severity,
        source_family: item.source_family,
        current_state: item.current_state,
        sla_state: item.sla_state,
        priority_score: item.priority_score,
        recommendation: item.recommendation,
        generation: knowledgeVersion,
      },
    })),
    evidence,
    coverage: [{
      key: "exposure_findings",
      visibleCount: topFindings.length,
      totalCount: facetData?.total_count ?? 0,
      truncated: topFindings.length < (facetData?.total_count ?? 0),
      available: Boolean(facetData),
    }],
    sourceStatuses: [{
      source: "fabric_sql",
      observedAt,
      status: copilotFreshness,
    }],
  });

  return (
    <div className="page-container exposure-overview-page">
      <PageHeader
        eyebrow="Exposure management"
        title="Which exposure should be reduced first?"
        description="Prioritize generation-pinned exposure findings without loading the full operational ontology into the API process."
        completeness={aggregate}
        actions={<CopilotDrawerButton onClick={() => setCopilotOpen(true)} label="Ask Copilot about exposure" />}
        metadata={
          <>
            <span>{facetData?.total_count.toLocaleString("en-US") ?? "Unknown"} exposure findings</span>
            <span>{critical?.toLocaleString("en-US") ?? "Unknown"} critical</span>
            <span>{imageFindings?.toLocaleString("en-US") ?? "Unknown"} container image findings</span>
            <span>Generation-pinned Fabric SQL</span>
          </>
        }
      />

      <CopilotInsights
        snapshot={exposureCopilot.snapshot}
        ready={!facets.loading}
        requestedScope={exposureCopilot.requestedScope}
        contextLabel="Vulnerability exposure"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      <EvidenceBar
        evidence={evidence}
        aggregateState={aggregate}
        knowledgeVersion={knowledgeVersion}
        warnings={warnings}
        fallbackTimestamp={observedAt}
        sourceStatus={{
          "Exposure aggregates": sourceStatus(facets),
          "Priority preview": sourceStatus(facets),
        }}
      />

      {allUnavailable && (
        <StatePanel
          title="Exposure intelligence is unavailable"
          message="The bounded Exposure read model is unavailable. Missing evidence is not treated as an all-clear state."
          tone="error"
        />
      )}

      <div className="exposure-landing-sections">
        <OverviewSection
          title="Exposure findings"
          description="Current findings in the authorized, generation-pinned Fabric SQL partition."
          sourceName="Exposure findings"
          itemLabel="findings"
          section={facets}
        >
          <div className="metric-grid exposure-metrics">
            <MetricCard
              label="Current exposure findings"
              value={facetData?.total_count}
              unit="findings"
              detail={facetData ? `Generation ${facetData.generation}` : "Generation unavailable"}
              completeness={sectionCompleteness(facets.status)}
            />
          </div>
        </OverviewSection>

        <OverviewSection
          title="Findings dashboard"
          description="At-a-glance visual summary of the current generation-pinned partition."
          sourceName="Findings dashboard"
          itemLabel="findings"
          section={facets}
        >
          <div className="dashboard-charts-row">
            <div className="chart-card">
              <h3 className="chart-card-title">Severity distribution</h3>
              {facetData?.facets.severity ? <DonutChart
                segments={severityBreakdown}
                centerValue={facetData?.total_count ?? "—"}
                centerLabel="findings"
                onSegmentClick={goToSeverity}
              /> : <StatePanel title="Severity distribution unavailable" message="The response did not include severity classifications. Missing classifications are not zero findings." tone="partial" />}
            </div>
            <div className="chart-card">
              <h3 className="chart-card-title">Findings by target kind</h3>
              <CountBarChart data={targetKindBreakdown} unit="target kind" />
            </div>
            {slaCounts.percent !== null ? (
              <div className="chart-card">
                <h3 className="chart-card-title">SLA overdue rate</h3>
                <RiskGauge
                  score={slaCounts.percent}
                  label="Overdue findings"
                />
                <p>{slaCounts.overdue.toLocaleString("en-US")} overdue / {slaCounts.scored.toLocaleString("en-US")} classified findings. {slaCounts.unclassified.toLocaleString("en-US")} unclassified findings excluded; this is not an estate-wide SLA rate.</p>
              </div>
            ) : <StatePanel title="SLA rate unavailable" message="No findings have a recorded overdue or within_sla classification. Indeterminate or missing SLA evidence is not treated as compliant." tone="empty" />}
          </div>
        </OverviewSection>

        <OverviewSection
          title="Severity distribution"
          description="Finding counts by provider-reported severity."
          sourceName="Severity distribution"
          itemLabel="severity groups"
          section={facets}
        >
          <div className="metric-grid exposure-metrics">
            <MetricCard label="Critical findings" value={critical} detail="Provider-reported critical severity" tone={countTone(critical, "critical")} completeness={sectionCompleteness(facets.status)} />
            <MetricCard label="High findings" value={high} detail="Provider-reported high severity" tone={countTone(high, "warning")} completeness={sectionCompleteness(facets.status)} />
            <MetricCard label="Medium findings" value={medium} detail="Provider-reported medium severity" tone={countTone(medium, "warning")} completeness={sectionCompleteness(facets.status)} />
          </div>
        </OverviewSection>

        <OverviewSection
          title="Target distribution"
          description="Finding counts by target kind; these are not distinct asset totals."
          sourceName="Target distribution"
          itemLabel="target groups"
          section={facets}
        >
          <div className="metric-grid exposure-metrics">
            <MetricCard label="Container image findings" value={imageFindings} detail="Findings attached to immutable image targets" completeness={sectionCompleteness(facets.status)} />
            <MetricCard label="Server findings" value={serverFindings} detail="Findings attached to server targets" completeness={sectionCompleteness(facets.status)} />
          </div>
        </OverviewSection>

        <OverviewSection
          title="Priority preview"
          description="Highest-ranked findings from the current query; the complete queue remains on Patch priorities."
          sourceName="Priority preview"
          itemLabel="priority findings"
          section={facets}
          action={<Link className="button" href={collectionHref("/exposure/patch-priorities")}>Open Patch priorities</Link>}
        >
          <div className="metric-grid exposure-metrics">
            {topFindings.map((item) => (
              <MetricCard
                key={item.exposure_id}
                label="Top priority finding"
                value={item.weakness_id}
                size="text"
                detail={`${item.severity ?? "Unknown"} severity · Priority ${item.priority_score ?? "unknown"}`}
                tone={item.severity?.toLocaleLowerCase("en-US") === "critical" ? "critical" : "warning"}
                completeness={sectionCompleteness(facets.status)}
                action={<Link href={priorityHref(item, loadedQuery)}>Open {item.weakness_id}</Link>}
              />
            ))}
          </div>
        </OverviewSection>

        <OverviewSection
          title="Source distribution"
          description="Finding counts by durable source family, without inferring alerts or posture records."
          sourceName="Source distribution"
          itemLabel="source groups"
          section={facets}
          action={<Link className="button" href={collectionHref("/exposure/defender-posture")}>Open Defender exposure</Link>}
        >
          <div className="metric-grid exposure-metrics">
            <MetricCard label="Defender image findings" value={defenderFindings} detail="Container image findings sourced from Defender" completeness={sectionCompleteness(facets.status)} />
            <MetricCard label="Update Manager findings" value={aumFindings} detail="Server patch findings sourced from Azure Update Manager" completeness={sectionCompleteness(facets.status)} />
          </div>
        </OverviewSection>

        <OverviewSection
          title="SLA classification"
          description="Finding counts by recorded SLA state; indeterminate evidence is never treated as compliant."
          sourceName="SLA classification"
          itemLabel="SLA groups"
          section={facets}
          action={<Link className="button" href={collectionHref("/exposure/patch-priorities")}>Review priorities</Link>}
        >
          <div className="metric-grid exposure-metrics">
            {(facetData?.facets.sla_state ?? []).map((item) => (
              <MetricCard
                key={item.value}
                label={`${displayFacet(item.value)} SLA findings`}
                value={item.count}
                detail={`Provider-reported SLA state: ${item.value}`}
                tone={item.value.toLocaleLowerCase("en-US") === "overdue" ? "critical" : "default"}
                completeness={sectionCompleteness(facets.status)}
              />
            ))}
          </div>
        </OverviewSection>

        <OverviewSection
          title="Evidence classification"
          description="Finding counts by source completeness and current lifecycle state."
          sourceName="Evidence classification"
          itemLabel="evidence groups"
          section={facets}
        >
          <div className="metric-grid exposure-metrics">
            {(facetData?.facets.completeness ?? []).map((item) => (
              <MetricCard key={`completeness-${item.value}`} label={`${displayFacet(item.value)} evidence findings`} value={item.count} detail={`Source completeness: ${item.value}`} completeness={sectionCompleteness(facets.status)} />
            ))}
            {(facetData?.facets.current_state ?? []).map((item) => (
              <MetricCard key={`state-${item.value}`} label={`${displayFacet(item.value)} findings`} value={item.count} detail={`Current lifecycle state: ${item.value}`} completeness={sectionCompleteness(facets.status)} />
            ))}
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
