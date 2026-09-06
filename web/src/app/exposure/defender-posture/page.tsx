"use client";

import {
  AppsList24Regular,
  Box24Regular,
  Cloud24Regular,
  Database24Regular,
  QuestionCircle24Regular,
  Server24Regular,
} from "@fluentui/react-icons";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ComponentType, SVGProps } from "react";

import {
  DefenderHandoff,
  type GovernedDefenderHandoff,
} from "@/components/exposure/DefenderHandoff";
import { SourceSectionState } from "@/components/exposure/SourceSectionState";
import {
  type ExposureSectionResult,
  useExposureSection,
} from "@/hooks/useExposureSection";
import {
  exposureQueryKey,
  exposureRetentionKey,
  parseExposureQueryState,
  type ExposureQueryState,
} from "@/lib/exposure-query-state";
import { vulnerabilityApi } from "@/lib/services";
import { useScope } from "@/lib/scope-context";
import type {
  AggregateCompleteness,
  EvidenceFreshness,
  PageHeaderCompleteness,
} from "@/components/ui/PageHeader";
import { PageHeader } from "@/components/ui/PageHeader";
import { MetricCard } from "@/components/ui/MetricCard";
import { StatusBadge, statusTone } from "@/components/ui/StatusBadge";
import type {
  ContainerImageExposure,
  DefenderAlert,
  DefenderAttackPath,
  DefenderAttackPathNode,
  DefenderOverview,
  DefenderPostureFinding,
  DefenderSecureScore,
  DefenderSecureScoreControl,
  Envelope,
  ExposureCommonContract,
  ExposureCursorPagination,
} from "@/lib/types";
import {
  isDefenderPortalActionKind,
  type DefenderPortalAction,
  type DefenderPortalActionKind,
} from "@/lib/exposure-portal-links";
import {
  defenderAssetPresentation,
  type DefenderAssetIcon,
  type DefenderAssetPresentation,
} from "./asset-labels";

interface DefenderSectionData<T> {
  items: T[];
  total_count: number;
  contract: ExposureCommonContract;
}

interface ServerProjectedActions {
  portal_actions?: unknown;
  actions?: unknown;
  action?: unknown;
  governed_handoff?: unknown;
}

type DefenderAlertRow = DefenderAlert & ServerProjectedActions;
type DefenderAttackPathNodeRow = DefenderAttackPathNode &
  ServerProjectedActions;
type DefenderAttackPathRow = Omit<DefenderAttackPath, "nodes"> &
  ServerProjectedActions & {
    nodes: DefenderAttackPathNodeRow[];
  };
type DefenderRecommendationRow = DefenderPostureFinding &
  ServerProjectedActions;
type ContainerImageRow = ContainerImageExposure &
  ServerProjectedActions & {
    observed_cluster_ids?: string[];
    represented_workload_count?: number;
    total_workload_count?: number;
    unknown_workload_count?: number;
  };

interface NormalizedActionRecord {
  kind?: unknown;
  href?: unknown;
  evidenceId?: unknown;
  evidence_id?: unknown;
  resourceId?: unknown;
  resource_id?: unknown;
  disabledReason?: unknown;
  disabled_reason?: unknown;
}

interface NormalizedHandoffRecord {
  outcome?: unknown;
  href?: unknown;
  representedTargets?: unknown;
  represented_targets?: unknown;
  totalTargets?: unknown;
  total_targets?: unknown;
  excludedReasons?: unknown;
  excluded_reasons?: unknown;
  reason?: unknown;
}

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

const ASSET_ICONS: Record<DefenderAssetIcon, IconComponent> = {
  server: Server24Regular,
  "container-image": Box24Regular,
  registry: Database24Regular,
  cluster: Cloud24Regular,
  resource: AppsList24Regular,
  mixed: AppsList24Regular,
  unknown: QuestionCircle24Regular,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function finiteCount(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : undefined;
}

function normalizeAction(value: unknown): DefenderPortalAction | null {
  if (!isRecord(value)) return null;
  const action = value as NormalizedActionRecord;
  if (!isDefenderPortalActionKind(action.kind)) return null;
  return {
    kind: action.kind,
    href: stringValue(action.href),
    evidenceId:
      stringValue(action.evidenceId) || stringValue(action.evidence_id),
    resourceId:
      stringValue(action.resourceId) || stringValue(action.resource_id),
    disabledReason:
      stringValue(action.disabledReason) ||
      stringValue(action.disabled_reason),
  };
}

function portalActions(value: ServerProjectedActions): DefenderPortalAction[] {
  const candidates = [
    ...(Array.isArray(value.portal_actions) ? value.portal_actions : []),
    ...(Array.isArray(value.actions) ? value.actions : []),
    ...(value.action ? [value.action] : []),
  ];
  return candidates
    .map(normalizeAction)
    .filter((action): action is DefenderPortalAction => action !== null);
}

function governedHandoff(
  value: ServerProjectedActions,
): GovernedDefenderHandoff | null {
  if (!isRecord(value.governed_handoff)) return null;
  const handoff = value.governed_handoff as NormalizedHandoffRecord;
  if (
    handoff.outcome !== "eligible" &&
    handoff.outcome !== "review_handoff" &&
    handoff.outcome !== "no_safe_action"
  ) {
    return null;
  }
  const excluded = Array.isArray(handoff.excludedReasons)
    ? handoff.excludedReasons
    : Array.isArray(handoff.excluded_reasons)
      ? handoff.excluded_reasons
      : [];
  return {
    outcome: handoff.outcome,
    href: stringValue(handoff.href),
    representedTargets:
      finiteCount(handoff.representedTargets) ??
      finiteCount(handoff.represented_targets),
    totalTargets:
      finiteCount(handoff.totalTargets) ?? finiteCount(handoff.total_targets),
    excludedReasons: excluded.filter(
      (reason): reason is string =>
        typeof reason === "string" && Boolean(reason.trim()),
    ),
    reason: stringValue(handoff.reason),
  };
}

function withRequiredAction(
  actions: readonly DefenderPortalAction[],
  kind: DefenderPortalActionKind,
  {
    resourceId = "",
    evidenceId = "",
    disabledReason,
  }: {
    resourceId?: string;
    evidenceId?: string;
    disabledReason: string;
  },
): DefenderPortalAction[] {
  const matching = actions.some(
    (action) =>
      action.kind === kind &&
      (!resourceId ||
        action.resourceId?.toLocaleLowerCase("en-US") ===
          resourceId.toLocaleLowerCase("en-US")),
  );
  return matching
    ? [...actions]
    : [
        ...actions,
        {
          kind,
          href: null,
          resourceId,
          evidenceId,
          disabledReason,
        },
      ];
}

function requiredResourceActions(
  actions: readonly DefenderPortalAction[],
  resourceIds: readonly string[],
  evidenceId: string,
): DefenderPortalAction[] {
  return resourceIds.reduce(
    (result, resourceId) =>
      withRequiredAction(result, "open_azure_resource", {
        resourceId,
        evidenceId,
        disabledReason:
          "No authorized Azure resource destination was provided. Review the resource evidence in Exposure.",
      }),
    [...actions],
  );
}

async function sectionEnvelope<T>(
  queryState: ExposureQueryState,
  signal: AbortSignal,
  loadRows: () => Promise<Envelope<T[]>>,
): Promise<
  Envelope<DefenderSectionData<T>, ExposureCursorPagination>
> {
  const [common, rows] = await Promise.all([
    vulnerabilityApi.exposureOverview(queryState, { signal }),
    loadRows(),
  ]);
  const items = Array.isArray(rows.data) ? rows.data : [];
  const total = rows.pagination?.total ?? items.length;
  return {
    ...common,
    data: {
      items,
      total_count: total,
      contract: common.data.contract,
    },
    evidence: [...common.evidence, ...rows.evidence],
    warnings: [...(common.warnings ?? []), ...(rows.warnings ?? [])],
    pagination: {
      limit: queryState.pageSize,
      total,
      next_cursor: null,
    },
  };
}

function useDefenderSection<T>(
  sectionId: string,
  queryState: ExposureQueryState,
  loadRows: () => Promise<Envelope<T[]>>,
): ExposureSectionResult<DefenderSectionData<T>> {
  return useExposureSection<DefenderSectionData<T>>({
    queryKey: `${exposureQueryKey(queryState)}|defender-section=${sectionId}`,
    retentionKey: `${exposureRetentionKey(
      queryState,
    )}|defender-section=${sectionId}`,
    load: ({ signal }) =>
      sectionEnvelope(queryState, signal, loadRows),
    isEmpty: (data) => data.items.length === 0,
  });
}

function singleItemEnvelope<T>(
  queryState: ExposureQueryState,
  signal: AbortSignal,
  loadItem: () => Promise<Envelope<T>>,
): Promise<
  Envelope<DefenderSectionData<T>, ExposureCursorPagination>
> {
  return Promise.all([
    vulnerabilityApi.exposureOverview(queryState, { signal }),
    loadItem(),
  ]).then(([common, item]) => ({
    ...common,
    data: {
      items: [item.data],
      total_count: 1,
      contract: common.data.contract,
    },
    evidence: [...common.evidence, ...item.evidence],
    warnings: [...(common.warnings ?? []), ...(item.warnings ?? [])],
    pagination: {
      limit: queryState.pageSize,
      total: 1,
      next_cursor: null,
    },
  }));
}

function useDefenderOverviewSection(
  queryState: ExposureQueryState,
  loadItem: () => Promise<Envelope<DefenderOverview>>,
) {
  return useExposureSection<DefenderSectionData<DefenderOverview>>({
    queryKey: `${exposureQueryKey(queryState)}|defender-section=overview`,
    retentionKey: `${exposureRetentionKey(
      queryState,
    )}|defender-section=overview`,
    load: ({ signal }) =>
      singleItemEnvelope(queryState, signal, loadItem),
    isEmpty: () => false,
  });
}

function sectionCount<T>(
  section: ExposureSectionResult<DefenderSectionData<T>>,
): string {
  return section.data?.total_count.toLocaleString("en-US") ?? "—";
}

function sectionCompleteness(
  status: ExposureSectionResult<unknown>["status"],
): "complete" | "partial" | "stale" | "unavailable" {
  if (status === "current" || status === "healthy-empty") return "complete";
  if (status === "loading") return "unavailable";
  return status;
}

function pageCompleteness(
  sections: Array<ExposureSectionResult<unknown>>,
): PageHeaderCompleteness | undefined {
  const settled = sections.filter((section) => section.status !== "loading");
  if (settled.length === 0) return undefined;
  const usable = sections.filter((section) => section.data !== null);
  let state: AggregateCompleteness;
  if (usable.length === 0) {
    state = "unavailable";
  } else if (
    sections.some(
      (section) =>
        section.status === "unavailable" || section.status === "partial",
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
  const metadata = sections
    .map(connectionCoverage)
    .find(
      (coverage) =>
        coverage.expected !== undefined ||
        coverage.represented !== undefined,
    ) ?? sections[0].metadata;
  return {
    state,
    freshness,
    representedConnections: metadata.represented,
    expectedConnections: metadata.expected,
    excludedCount: metadata.excluded,
  };
}

function connectionCoverage(
  section: ExposureSectionResult<unknown>,
): ExposureSectionResult<unknown>["metadata"] {
  const data = isRecord(section.data) ? section.data : null;
  const contract = isRecord(data?.contract) ? data.contract : null;
  const completeness = isRecord(contract?.completeness)
    ? contract.completeness
    : null;
  return {
    ...section.metadata,
    represented:
      finiteCount(completeness?.represented_connections) ??
      section.metadata.represented,
    expected:
      finiteCount(completeness?.expected_connections) ??
      section.metadata.expected,
  };
}

function CommonEvidence<T>({
  section,
}: {
  section: ExposureSectionResult<DefenderSectionData<T>>;
}) {
  const evidenceIds =
    section.data?.contract.evidence_refs
      .map((reference) => reference.source_id)
      .filter((value): value is string => Boolean(value)) ?? [];
  const counts = section.data?.contract.counts;
  return (
    <p className="table-secondary">
      Generation:{" "}
      {section.data?.contract.query.generation ||
        section.envelope?.knowledge_version ||
        "unavailable"}
      {evidenceIds.length > 0
        ? ` · Evidence: ${evidenceIds.join(", ")}`
        : " · Evidence identifiers unavailable"}
      {counts
        ? ` · ${counts.represented.toLocaleString(
            "en-US",
          )} represented findings · ${counts.total.toLocaleString(
            "en-US",
          )} total findings · ${counts.excluded.toLocaleString(
            "en-US",
          )} excluded findings`
        : ""}
    </p>
  );
}

function DefenderSection<T>({
  id,
  title,
  sourceName,
  itemLabel,
  section,
  children,
}: {
  id: string;
  title: string;
  sourceName: string;
  itemLabel: string;
  section: ExposureSectionResult<DefenderSectionData<T>>;
  children: React.ReactNode;
}) {
  const presentationState = {
    ...section,
    metadata: connectionCoverage(section),
  };
  return (
    <section id={id} className="card queue-card" aria-labelledby={`${id}-title`}>
      <div className="card-header">
        <div>
          <h2 id={`${id}-title`}>{title}</h2>
          <p>{`${sectionCount(section)} ${itemLabel} in the represented result.`}</p>
        </div>
      </div>
      <div className="card-body">
        <SourceSectionState
          sourceName={sourceName}
          itemLabel={itemLabel}
          state={presentationState}
        >
          <CommonEvidence section={section} />
          {children}
        </SourceSectionState>
      </div>
    </section>
  );
}

function AssetKind({
  presentation,
}: {
  presentation: DefenderAssetPresentation;
}) {
  const Icon = ASSET_ICONS[presentation.icon];
  return (
    <span>
      <Icon aria-hidden="true" />
      <span>{presentation.kindLabel}</span>
    </span>
  );
}

function scoreTotals(scores: readonly DefenderSecureScore[]) {
  const valid = scores.filter(
    (score) =>
      Number.isFinite(score.currentScore) &&
      Number.isFinite(score.maxScore) &&
      score.currentScore >= 0 &&
      score.maxScore >= 0,
  );
  const current = valid.reduce((total, score) => total + score.currentScore, 0);
  const max = valid.reduce((total, score) => total + score.maxScore, 0);
  return {
    current,
    max,
    percentage: max > 0 ? (current / max) * 100 : null,
    subscriptions: new Set(valid.map((score) => score.subscription_id)).size,
  };
}

function controlPercentage(control: DefenderSecureScoreControl): number | null {
  return Number.isFinite(control.currentScore) &&
    Number.isFinite(control.maxScore) &&
    control.maxScore > 0
    ? (control.currentScore / control.maxScore) * 100
    : null;
}

function DefenderOverviewContent({
  overview,
  sections,
}: {
  overview: DefenderOverview | undefined;
  sections: {
    alerts: ExposureSectionResult<DefenderSectionData<DefenderAlertRow>>;
    attackPaths: ExposureSectionResult<
      DefenderSectionData<DefenderAttackPathRow>
    >;
    recommendations: ExposureSectionResult<
      DefenderSectionData<DefenderRecommendationRow>
    >;
    containers: ExposureSectionResult<
      DefenderSectionData<ContainerImageRow>
    >;
  };
}) {
  return (
    <div className="metric-grid">
      <MetricCard
        label="Active alerts"
        value={sections.alerts.data?.total_count}
        detail="Current Defender security alerts"
        tone="warning"
        completeness={sectionCompleteness(sections.alerts.status)}
      />
      <MetricCard
        label="Attack paths"
        value={sections.attackPaths.data?.total_count}
        detail="Represented Defender CSPM paths"
        tone="critical"
        completeness={sectionCompleteness(sections.attackPaths.status)}
      />
      <MetricCard
        label="Open recommendations"
        value={sections.recommendations.data?.total_count}
        detail="Unhealthy represented assessments"
        tone="warning"
        completeness={sectionCompleteness(sections.recommendations.status)}
      />
      <MetricCard
        label="Vulnerable container images"
        value={sections.containers.data?.total_count}
        detail={
          overview
            ? `${overview.container_image_cve_count.toLocaleString(
                "en-US",
              )} CVEs reported across represented images`
            : "Container CVE total unavailable"
        }
        tone="critical"
        completeness={sectionCompleteness(sections.containers.status)}
      />
    </div>
  );
}

function AlertContent({ alerts }: { alerts: readonly DefenderAlertRow[] }) {
  return (
    <div aria-label="Defender alert results">
      {alerts.map((alert) => {
        let actions = withRequiredAction(
          portalActions(alert),
          "open_defender_alert",
          {
            evidenceId: alert.id,
            disabledReason:
              "Defender did not provide a safe alert destination. Review the alert evidence in Exposure.",
          },
        );
        actions = requiredResourceActions(
          actions,
          alert.resourceIds ?? [],
          alert.id,
        );
        return (
          <article key={alert.id}>
            <h3>{alert.title}</h3>
            <StatusBadge
              label={alert.severity}
              tone={statusTone(alert.severity)}
              compact
            />
            <p>{alert.description || "No alert description was reported."}</p>
            <p>{`${(alert.resourceIds ?? []).length.toLocaleString(
              "en-US",
            )} affected resources represented.`}</p>
            <DefenderHandoff
              actions={actions}
              authorizedResourceIds={alert.resourceIds ?? []}
              governedHandoff={governedHandoff(alert)}
            />
          </article>
        );
      })}
    </div>
  );
}

function AttackPathContent({
  paths,
}: {
  paths: readonly DefenderAttackPathRow[];
}) {
  return (
    <div aria-label="Defender attack path results">
      {paths.map((path) => {
        const pathActions = withRequiredAction(
          portalActions(path),
          "open_defender_attack_path",
          {
            evidenceId: path.id,
            disabledReason:
              "Defender did not provide a safe attack-path destination. Review the path evidence in Exposure.",
          },
        );
        return (
          <article key={path.id}>
            <h3>{path.title || "Unnamed attack path"}</h3>
            <p>{path.description || "No path description was reported."}</p>
            <p>{`Potential impact: ${
              path.potentialImpact || "Not reported"
            }`}</p>
            <p>{`${path.nodes.length.toLocaleString(
              "en-US",
            )} represented nodes. Excluded nodes remain outside this result and must not be inferred.`}</p>
            <DefenderHandoff
              actions={pathActions}
              governedHandoff={governedHandoff(path)}
            />
            {path.nodes.length > 0 && (
              <ul aria-label={`${path.title || "Attack path"} nodes`}>
                {path.nodes.map((node) => {
                  const presentation = defenderAssetPresentation({
                    assetId: node.resourceId,
                    assetName: node.displayName,
                    resourceType: node.nodeType,
                    inventoryKind: node.nodeType,
                  });
                  const nodeActions = node.resourceId
                    ? requiredResourceActions(
                        portalActions(node),
                        [node.resourceId],
                        node.id,
                      )
                    : portalActions(node);
                  return (
                    <li key={node.id}>
                      <AssetKind presentation={presentation} />
                      <span>{presentation.label}</span>
                      <DefenderHandoff
                        actions={nodeActions}
                        authorizedResourceIds={
                          node.resourceId ? [node.resourceId] : []
                        }
                      />
                    </li>
                  );
                })}
              </ul>
            )}
          </article>
        );
      })}
    </div>
  );
}

function RecommendationContent({
  recommendations,
}: {
  recommendations: readonly DefenderRecommendationRow[];
}) {
  return (
    <div aria-label="Defender recommendation results">
      {recommendations.map((recommendation) => {
        const presentation = defenderAssetPresentation({
          assetId: recommendation.asset_id,
          assetName: recommendation.asset_name,
          resourceType: recommendation.resource_type,
          inventoryKind: recommendation.inventory_kind,
        });
        let actions = withRequiredAction(
          portalActions(recommendation),
          "open_defender_recommendation",
          {
            evidenceId: recommendation.assessment_id,
            disabledReason:
              "Defender did not provide a safe recommendation destination. Review the assessment evidence in Exposure.",
          },
        );
        const isCanonicalResource =
          recommendation.asset_id.startsWith("/subscriptions/");
        if (isCanonicalResource && presentation.icon !== "mixed") {
          actions = requiredResourceActions(
            actions,
            [recommendation.asset_id],
            recommendation.assessment_id,
          );
        }
        return (
          <article key={recommendation.assessment_id}>
            <h3>
              {recommendation.recommendation || "Unnamed recommendation"}
            </h3>
            <StatusBadge
              label={recommendation.severity}
              tone={statusTone(recommendation.severity)}
              compact
            />
            <p>
              <AssetKind presentation={presentation} />
              <span>{presentation.label}</span>
            </p>
            <p>
              {recommendation.description ||
                "No recommendation description was reported."}
            </p>
            {recommendation.remediation && (
              <p>{`Guidance: ${recommendation.remediation}`}</p>
            )}
            <DefenderHandoff
              actions={actions}
              authorizedResourceIds={
                isCanonicalResource && presentation.icon !== "mixed"
                  ? [recommendation.asset_id]
                  : []
              }
              governedHandoff={governedHandoff(recommendation)}
            />
          </article>
        );
      })}
    </div>
  );
}

function ControlContent({
  controls,
}: {
  controls: readonly DefenderSecureScoreControl[];
}) {
  return (
    <div aria-label="Defender secure-score control results">
      {controls.map((control) => {
        const percentage = controlPercentage(control);
        return (
          <article key={control.id}>
            <h3>{control.title || "Unnamed secure-score control"}</h3>
            <p>
              {`${control.currentScore.toLocaleString(
                "en-US",
              )} / ${control.maxScore.toLocaleString("en-US")} points · ${
                percentage === null ? "—" : `${percentage.toFixed(1)}%`
              }`}
            </p>
            <p>{`${control.unhealthyResourceCount.toLocaleString(
              "en-US",
            )} unhealthy and ${control.healthyResourceCount.toLocaleString(
              "en-US",
            )} healthy represented resources.`}</p>
          </article>
        );
      })}
    </div>
  );
}

function ContainerContent({
  images,
}: {
  images: readonly ContainerImageRow[];
}) {
  return (
    <div aria-label="Defender container image results">
      {images.map((image) => {
        let actions = withRequiredAction(
          portalActions(image),
          "open_registry",
          {
            resourceId: image.registry_resource_id,
            evidenceId: image.id,
            disabledReason:
              "No authorized registry destination was provided. Review the image evidence in Exposure.",
          },
        );
        for (const clusterId of image.observed_cluster_ids ?? []) {
          actions = withRequiredAction(actions, "open_cluster", {
            resourceId: clusterId,
            evidenceId: image.id,
            disabledReason:
              "No authorized observed-cluster destination was provided. Review workload evidence in Exposure.",
          });
        }
        const represented = finiteCount(image.represented_workload_count);
        const total = finiteCount(image.total_workload_count);
        const unknown = finiteCount(image.unknown_workload_count);
        const projectedHandoff = governedHandoff(image);
        const handoff =
          projectedHandoff?.outcome === "review_handoff" ||
          projectedHandoff?.outcome === "no_safe_action"
            ? projectedHandoff
            : projectedHandoff?.outcome === "eligible"
              ? ({
                  outcome: "no_safe_action",
                  reason:
                    "Container findings permit review-only handoffs; execution eligibility was rejected.",
                } satisfies GovernedDefenderHandoff)
              : ({
            outcome: "no_safe_action",
            reason:
              "No server-projected review handoff is available. Review exact digest and observed workload evidence.",
                } satisfies GovernedDefenderHandoff);
        return (
          <article key={image.id}>
            <h3>
              {image.repository || "Unnamed image"}
              {image.image_tags?.length ? `:${image.image_tags[0]}` : ""}
            </h3>
            <StatusBadge
              label={image.severity}
              tone={statusTone(image.severity)}
              compact
            />
            <p>{`Registry: ${image.registry_host || "Not reported"}`}</p>
            <p>{`Digest: ${image.image_digest || "Not reported"}`}</p>
            <p>
              {represented !== undefined && total !== undefined
                ? `${represented.toLocaleString(
                    "en-US",
                  )} of ${total.toLocaleString(
                    "en-US",
                  )} observed workloads represented; ${(
                    unknown ?? Math.max(0, total - represented)
                  ).toLocaleString(
                    "en-US",
                  )} excluded or unknown. This is not a full blast radius.`
                : "Workload coverage is unknown. No full blast radius is claimed."}
            </p>
            <p>
              CVEs:{" "}
              {image.cve_ids?.length
                ? image.cve_ids.map((cveId, index) => (
                    <span key={cveId}>
                      {index > 0 && ", "}
                      <Link
                        className="table-primary-link"
                        href={`/exposure/cves/${encodeURIComponent(cveId)}`}
                      >
                        {cveId}
                      </Link>
                    </span>
                  ))
                : "No CVEs listed"}
            </p>
            <DefenderHandoff
              actions={actions}
              authorizedResourceIds={[
                image.registry_resource_id,
                ...(image.observed_cluster_ids ?? []),
              ].filter(Boolean)}
              governedHandoff={handoff}
            />
          </article>
        );
      })}
    </div>
  );
}

/** Defender evidence remains usable section-by-section under partial provider failure. */
export default function DefenderPosturePage() {
  const { scope } = useScope();
  const searchParams = useSearchParams();
  const parsedQuery = parseExposureQueryState(
    new URLSearchParams(searchParams.toString()),
    { authorizedScope: scope },
  );
  const defenderQuery: ExposureQueryState = {
    ...parsedQuery,
    filters: {
      ...parsedQuery.filters,
      source_family: "defender",
    },
  };
  const containerQuery: ExposureQueryState = {
    ...defenderQuery,
    filters: {
      ...defenderQuery.filters,
      target_kind: "container_image",
    },
  };

  const overview = useDefenderOverviewSection(defenderQuery, () =>
    vulnerabilityApi.defenderOverview(scope),
  );
  const alerts = useDefenderSection<DefenderAlertRow>(
    "alerts",
    defenderQuery,
    () => vulnerabilityApi.defenderAlerts(scope),
  );
  const attackPaths = useDefenderSection<DefenderAttackPathRow>(
    "attack-paths",
    defenderQuery,
    () =>
      vulnerabilityApi.defenderAttackPaths(
        scope,
      ) as Promise<Envelope<DefenderAttackPathRow[]>>,
  );
  const secureScore = useDefenderSection<DefenderSecureScore>(
    "secure-score",
    defenderQuery,
    () => vulnerabilityApi.defenderSecureScore(scope),
  );
  const controls = useDefenderSection<DefenderSecureScoreControl>(
    "secure-score-controls",
    defenderQuery,
    () => vulnerabilityApi.defenderSecureScoreControls(scope),
  );
  const recommendations = useDefenderSection<DefenderRecommendationRow>(
    "recommendations",
    defenderQuery,
    () =>
      vulnerabilityApi.defenderPosture(
        scope,
      ) as Promise<Envelope<DefenderRecommendationRow[]>>,
  );
  const containers = useDefenderSection<ContainerImageRow>(
    "container-images",
    containerQuery,
    () =>
      vulnerabilityApi.containerImageExposures(
        scope,
      ) as Promise<Envelope<ContainerImageRow[]>>,
  );

  const sections: Array<ExposureSectionResult<unknown>> = [
    overview,
    alerts,
    attackPaths,
    secureScore,
    controls,
    recommendations,
    containers,
  ];
  const headerState = pageCompleteness(sections);
  const overviewValue = overview.data?.items[0];
  const scores = secureScore.data?.items ?? [];
  const score = scoreTotals(scores);

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Exposure management"
        title="Defender posture"
        description="Review Defender alerts, attack paths, recommendations, secure score, and container-image evidence without hiding partial scope."
        completeness={headerState}
      />

      <nav aria-label="Defender posture sections">
        <a href="#defender-overview">{`Overview (${sectionCount(
          overview,
        )}, ${overview.status})`}</a>
        <a href="#defender-secure-score">{`Secure score (${sectionCount(
          secureScore,
        )}, ${secureScore.status})`}</a>
        <a href="#defender-alerts">{`Active alerts (${sectionCount(
          alerts,
        )}, ${alerts.status})`}</a>
        <a href="#defender-attack-paths">{`Attack paths (${sectionCount(
          attackPaths,
        )}, ${attackPaths.status})`}</a>
        <a href="#defender-recommendations">{`Recommendations (${sectionCount(
          recommendations,
        )}, ${recommendations.status})`}</a>
        <a href="#defender-controls">{`Controls (${sectionCount(
          controls,
        )}, ${controls.status})`}</a>
        <a href="#defender-container-images">{`Container images (${sectionCount(
          containers,
        )}, ${containers.status})`}</a>
      </nav>

      <DefenderSection
        id="defender-overview"
        title="Security overview"
        sourceName="Defender overview"
        itemLabel="overview"
        section={overview}
      >
        <DefenderOverviewContent
          overview={overviewValue}
          sections={{ alerts, attackPaths, recommendations, containers }}
        />
      </DefenderSection>

      <DefenderSection
        id="defender-secure-score"
        title="Secure score"
        sourceName="Defender secure score"
        itemLabel="subscription scores"
        section={secureScore}
      >
        <div className="metric-grid">
          <MetricCard
            label="Secure score — all authorized subscriptions"
            value={
              score.percentage === null
                ? null
                : `${score.percentage.toFixed(1)}%`
            }
            detail={
              score.percentage === null
                ? "Current and maximum score evidence is unavailable"
                : `${score.current.toLocaleString(
                    "en-US",
                  )} of ${score.max.toLocaleString(
                    "en-US",
                  )} points across ${score.subscriptions.toLocaleString(
                    "en-US",
                  )} authorized subscriptions`
            }
            tone="default"
            completeness={sectionCompleteness(secureScore.status)}
          />
        </div>
      </DefenderSection>

      <DefenderSection
        id="defender-alerts"
        title="Active alerts"
        sourceName="Defender alerts"
        itemLabel="alerts"
        section={alerts}
      >
        <AlertContent alerts={alerts.data?.items ?? []} />
      </DefenderSection>

      <DefenderSection
        id="defender-attack-paths"
        title="Attack paths"
        sourceName="Defender attack paths"
        itemLabel="attack paths"
        section={attackPaths}
      >
        <AttackPathContent paths={attackPaths.data?.items ?? []} />
      </DefenderSection>

      <DefenderSection
        id="defender-recommendations"
        title="Unhealthy recommendations"
        sourceName="Defender recommendations"
        itemLabel="recommendations"
        section={recommendations}
      >
        <RecommendationContent
          recommendations={recommendations.data?.items ?? []}
        />
      </DefenderSection>

      <DefenderSection
        id="defender-controls"
        title="Secure-score controls"
        sourceName="Defender secure-score controls"
        itemLabel="controls"
        section={controls}
      >
        <ControlContent controls={controls.data?.items ?? []} />
      </DefenderSection>

      <DefenderSection
        id="defender-container-images"
        title="Container image vulnerabilities"
        sourceName="Defender container images"
        itemLabel="images"
        section={containers}
      >
        <ContainerContent images={containers.data?.items ?? []} />
      </DefenderSection>
    </div>
  );
}
