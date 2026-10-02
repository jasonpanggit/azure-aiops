"use client";

import { useMemo, useState } from "react";
import { CopilotDrawer } from "@/components/ui/CopilotDrawer";
import { CopilotDrawerButton } from "@/components/ui/CopilotDrawerButton";
import { CountBarChart } from "@/components/ui/CountBarChart";
import { DonutChart } from "@/components/ui/DonutChart";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TableColumnFilters } from "@/components/ui/TableColumnFilters";
import { TablePagination } from "@/components/ui/TablePagination";
import { useApi } from "@/hooks/useApi";
import { buildFinOpsCopilotContext } from "@/lib/copilot/page-adapters";
import { titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { governanceApi } from "@/lib/services";
import { useColumnFilters } from "@/lib/table-column-filters";
import { useTablePagination } from "@/lib/use-table-pagination";
import { CopilotInsights } from "@/components/ui/CopilotInsights";

const DIMENSIONS = [
  "subscription",
  "application",
  "business_service",
  "owner",
  "environment",
] as const;

type Dimension = (typeof DIMENSIONS)[number];

/** Renders a saving, keeping "not quantified" visibly distinct from zero. */
function money(amount: number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined) return "Not quantified";
  const suffix = currency && currency !== "mixed" ? ` ${currency}` : "";
  return `${Math.round(amount).toLocaleString()}${suffix}`;
}

export default function FinOpsPage() {
  const { scope } = useScope();
  const [dimension, setDimension] = useState<Dimension>("subscription");
  const [copilotOpen, setCopilotOpen] = useState(false);

  const summary = useApi(() => governanceApi.finopsSummary(scope), [scope]);
  const opportunities = useApi(() => governanceApi.finopsOpportunities(scope), [scope]);
  const waste = useApi(() => governanceApi.finopsWaste(scope), [scope]);
  const attribution = useApi(
    () => governanceApi.finopsAttribution(dimension, scope),
    [scope, dimension],
  );

  const loading = summary.loading || opportunities.loading || waste.loading;
  const error = summary.error ?? opportunities.error ?? waste.error;

  const totals = summary.data?.data;
  const currency = totals?.currency ?? "";
  const billedSpendCurrency = totals?.actual_spend_currency ?? currency;
  const billedSpendDetail =
    totals?.actual_spend !== undefined
      ? `${totals.actual_spend_period_start || "Current period"} to ${
          totals.actual_spend_period_end || "latest"
        } from Cost Management (${totals.actual_spend_record_count ?? 0} rows). ` +
        "Not real-time — refreshed on sync. Go to Connections, click \"Sync now\" to refresh."
      : "Not real-time — synced periodically from Cost Management. " +
        "Go to Connections, click \"Sync now\" on the subscription connection to refresh.";

  const rows = useMemo(
    () => opportunities.data?.data.opportunities ?? [],
    [opportunities.data],
  );
  const wasteRows = useMemo(() => waste.data?.data.waste ?? [], [waste.data]);
  const attributionGroups = useMemo(
    () => attribution.data?.data.groups ?? [],
    [attribution.data],
  );

  const {
    filteredRows: filteredAttributionGroups,
    filters: attributionFilters,
    resetFilters: resetAttributionFilters,
  } = useColumnFilters(attributionGroups, [
    { id: "group", label: titleize(dimension), getValues: (group) => group[dimension] ?? "Unattributed" },
  ]);
  const {
    filteredRows: filteredOpportunities,
    filters: opportunityFilters,
    resetFilters: resetOpportunityFilters,
  } = useColumnFilters(rows, [
    { id: "impact", label: "Impact", getValues: (row) => row.impact || "unknown" },
    { id: "owner", label: "Owner", getValues: (row) => row.owner || row.business_service || row.subscription || "Unattributed" },
  ]);
  const savingsByCategory = useMemo(() => {
    const palette = ["var(--color-brand)", "#3ea3e0", "var(--color-success)", "var(--color-warning)", "var(--color-text-muted)"];
    const totalsBySource = new Map<string, number>();
    for (const opportunity of filteredOpportunities) {
      const key = titleize(opportunity.savings_source || "unknown");
      totalsBySource.set(key, (totalsBySource.get(key) ?? 0) + (opportunity.annual_savings ?? 0));
    }
    return Array.from(totalsBySource.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([label, value], index) => ({ label, value, color: palette[index % palette.length] }));
  }, [filteredOpportunities]);
  const {
    filteredRows: filteredWasteRows,
    filters: wasteFilters,
    resetFilters: resetWasteFilters,
  } = useColumnFilters(wasteRows, [
    { id: "type", label: "Type", getValues: (row) => row.resource_type || "Resource" },
    { id: "reason", label: "Reason", getValues: (row) => row.reason || "unknown", formatOption: titleize },
    { id: "owner", label: "Owner", getValues: (row) => row.owner || row.business_service || row.subscription || "Unattributed" },
  ]);
  const wasteByType = useMemo(() => {
    const totalsByType = new Map<string, number>();
    for (const item of filteredWasteRows) {
      const key = titleize(item.resource_type || "Resource");
      totalsByType.set(key, (totalsByType.get(key) ?? 0) + (item.annual_savings ?? 0));
    }
    return Array.from(totalsByType.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([label, value], index) => ({ id: `waste-${index}`, label, value }));
  }, [filteredWasteRows]);

  const attributionPaging = useTablePagination(filteredAttributionGroups);
  const opportunityPaging = useTablePagination(filteredOpportunities);
  const wastePaging = useTablePagination(filteredWasteRows);

  // Read-only contextual Copilot over already-loaded cost evidence. Currency,
  // observation window, totals, and genuinely-unavailable metrics stay explicit
  // and null savings remain "not quantified" (D-03, D-04, D-06, D-09).
  const finopsAvailable = !error && Boolean(summary.data);
  const finopsCopilot = buildFinOpsCopilotContext({
    scope,
    summary: totals
      ? {
          identified_annual_savings: totals.identified_annual_savings,
          currency: totals.currency,
          savings_opportunity_count: totals.savings_opportunity_count,
          quantified_opportunity_count: totals.quantified_opportunity_count,
          waste_item_count: totals.waste_item_count,
          actual_spend: totals.actual_spend,
          actual_spend_currency: totals.actual_spend_currency,
          actual_spend_period_start: totals.actual_spend_period_start,
          actual_spend_period_end: totals.actual_spend_period_end,
          unavailable_metrics: totals.unavailable_metrics ?? [],
        }
      : null,
    dimension,
    attribution: attributionGroups.map((group) => ({
      dimension,
      group: String(group[dimension] ?? "Unattributed"),
      identified_annual_savings: Number(group.identified_annual_savings ?? 0),
      savings_opportunity_count: Number(group.savings_opportunity_count ?? 0),
      waste_item_count: Number(group.waste_item_count ?? 0),
    })),
    attributionTotalCount: attribution.data?.data.count ?? attributionGroups.length,
    opportunities: rows.map((opportunity) => ({
      recommendation_id: opportunity.recommendation_id,
      resource_id: opportunity.resource_id,
      problem: opportunity.problem,
      impact: opportunity.impact,
      annual_savings: opportunity.annual_savings,
      currency: opportunity.currency,
      owner: opportunity.owner,
      business_service: opportunity.business_service,
      subscription: opportunity.subscription,
    })),
    opportunitiesTotalCount: opportunities.data?.data.count ?? rows.length,
    waste: wasteRows.map((waste) => ({
      resource_id: waste.resource_id,
      resource_type: waste.resource_type,
      reason: waste.reason,
      annual_savings: waste.annual_savings,
      currency: waste.currency,
      owner: waste.owner,
      business_service: waste.business_service,
    })),
    wasteTotalCount: waste.data?.data.count ?? wasteRows.length,
    available: finopsAvailable,
    freshness: finopsAvailable ? "fresh" : "unavailable",
    evidence: [...(summary.data?.evidence ?? []), ...(opportunities.data?.evidence ?? [])],
  });

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Financial accountability"
        title="Where is spend signal available?"
        description="Review savings and waste attributed to the subscriptions, applications, business services, owners, and environments returned by Azure."
        actions={
          <CopilotDrawerButton
            onClick={() => setCopilotOpen(true)}
            label="Ask Copilot about cost"
          />
        }
        metadata={
          <>
            <span>Savings figures are issued by Azure Advisor</span>
            <span>Scope-limited to your subscriptions</span>
            <span>Billed spend is not real-time — refresh via Connections &gt; Sync now</span>
          </>
        }
      />

      <CopilotInsights
        snapshot={finopsCopilot.snapshot}
        requestedScope={finopsCopilot.requestedScope}
        contextLabel="Financial accountability"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

      <EvidenceBar
        evidence={[
          ...(summary.data?.evidence ?? []),
          ...(opportunities.data?.evidence ?? []),
        ]}
        knowledgeVersion={summary.data?.knowledge_version}
        warnings={[
          ...(summary.data?.warnings ?? []),
          ...(opportunities.data?.warnings ?? []),
        ]}
      />

      {error ? (
        <StatePanel
          title="Cost intelligence is unavailable"
          message={
            error.message ??
            "No governance response was returned. Sync a subscription connection first."
          }
          tone="error"
        />
      ) : loading ? (
        <StatePanel
          title="Reading cost signals"
          message="Collecting Advisor recommendations and inventory waste."
          tone="loading"
        />
      ) : (
        <>
          <div className="metric-grid">
            <MetricCard
              label="Identified annual savings"
              value={money(totals?.identified_annual_savings ?? null, currency)}
              detail="Azure Advisor's own computation, not an estimate of ours"
              tone="success"
            />
            <MetricCard
              label="Savings opportunities"
              value={totals?.savings_opportunity_count ?? 0}
              detail={`${totals?.quantified_opportunity_count ?? 0} carry a quantified figure`}
            />
            <MetricCard
              label="Waste items"
              value={totals?.waste_item_count ?? 0}
              detail="Provisioned but not delivering value"
              tone="warning"
            />
            <MetricCard
              label="Billed spend"
              value={
                totals?.actual_spend !== undefined
                  ? money(totals.actual_spend, billedSpendCurrency)
                  : "Unavailable"
              }
              detail={billedSpendDetail}
              tone={totals?.actual_spend !== undefined ? "success" : "critical"}
            />
          </div>

          {(savingsByCategory.length > 0 || wasteByType.length > 0) && (
            <div className="card dashboard-charts-row">
              {savingsByCategory.length > 0 && (
                <div className="chart-card">
                  <h3 className="chart-card-title">Savings by category</h3>
                  <DonutChart
                    segments={savingsByCategory}
                    centerValue={money(totals?.identified_annual_savings ?? null, currency)}
                    centerLabel="Identified"
                  />
                </div>
              )}
              {wasteByType.length > 0 && (
                <div className="chart-card">
                  <h3 className="chart-card-title">Waste by resource type</h3>
                  <CountBarChart data={wasteByType} unit="resource type" />
                </div>
              )}
            </div>
          )}

          {(totals?.unavailable_metrics?.length ?? 0) > 0 && (
            <section className="card">
              <div className="card-header">
                <div>
                  <h2>What this page cannot tell you</h2>
                  <p>
                    These figures are deliberately absent rather than estimated,
                    so nothing here is mistaken for billed cost.
                  </p>
                </div>
              </div>
              <div className="card-body">
                <div className="table-scroll">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th>Why it is unavailable</th>
                      </tr>
                    </thead>
                    <tbody>
                      {totals?.unavailable_metrics.map((item) => (
                        <tr key={item.metric}>
                          <td>
                            <span className="table-primary-link">
                              {titleize(item.metric)}
                            </span>
                          </td>
                          <td>{item.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          <section className="card">
            <div className="card-header">
              <div>
                <h2>Attribution</h2>
                <p>Which part of the business owns the identified savings.</p>
              </div>
              <div className="segmented-control" aria-label="Attribution dimension">
                {DIMENSIONS.map((item) => (
                  <button
                    key={item}
                    type="button"
                    aria-pressed={item === dimension}
                    className={item === dimension ? "segmented-active" : ""}
                    onClick={() => setDimension(item)}
                  >
                    {titleize(item)}
                  </button>
                ))}
              </div>
            </div>
            <div className="card-body">
              {attribution.error ? (
                <StatePanel
                  title="Attribution is unavailable"
                  message={
                    attribution.error.message ??
                    "Cost attribution could not be loaded for this dimension."
                  }
                  tone="error"
                />
              ) : attribution.loading ? (
                <StatePanel
                  title="Grouping"
                  message={`Attributing savings by ${titleize(dimension).toLowerCase()}.`}
                  tone="loading"
                />
              ) : (attribution.data?.data.groups.length ?? 0) === 0 ? (
                <StatePanel
                  title="No attributed savings"
                  message="No Advisor cost recommendation carries this dimension in the current scope."
                />
              ) : (
                <>
                <TableColumnFilters
                  filters={attributionFilters}
                  onReset={resetAttributionFilters}
                  resultCount={filteredAttributionGroups.length}
                  totalCount={attributionGroups.length}
                />
                <div className="table-scroll">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>{titleize(dimension)}</th>
                        <th>Identified savings</th>
                        <th>Opportunities</th>
                        <th>Waste items</th>
                      </tr>
                    </thead>
                    <tbody>
                      {attributionPaging.pageRows.map((group, index) => (
                        <tr key={String(group[dimension] ?? index)}>
                          <td>
                            <span className="table-primary-link">
                              {String(group[dimension] ?? "Unattributed")}
                            </span>
                          </td>
                          <td>
                            {money(Number(group.identified_annual_savings), currency)}
                          </td>
                          <td>{group.savings_opportunity_count}</td>
                          <td>{group.waste_item_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
              )}
              <TablePagination
                total={attributionPaging.total}
                pageRows={attributionPaging.pageRows.length}
                page={attributionPaging.page}
                onPageChange={attributionPaging.setPage}
                pageSize={attributionPaging.pageSize}
                onPageSizeChange={attributionPaging.setPageSize}
                label="groups"
              />
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <div>
                <h2>Savings opportunities</h2>
                <p>
                  Azure Advisor cost recommendations, richest quantified saving
                  first.
                </p>
              </div>
            </div>
            <div className="card-body">
              {rows.length === 0 ? (
                <StatePanel
                  title="No cost recommendations"
                  message="Azure Advisor has issued no cost recommendation for the subscriptions in scope."
                />
              ) : (
                <>
                <TableColumnFilters
                  filters={opportunityFilters}
                  onReset={resetOpportunityFilters}
                  resultCount={filteredOpportunities.length}
                  totalCount={rows.length}
                />
                <div className="table-scroll">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Recommendation</th>
                        <th>Impact</th>
                        <th>Annual saving</th>
                        <th>Owner</th>
                        <th>Resource</th>
                      </tr>
                    </thead>
                    <tbody>
                      {opportunityPaging.pageRows.map((row, index) => (
                        <tr key={row.recommendation_id || row.resource_id || index}>
                          <td>
                            <span className="table-primary-link">
                              {row.problem || "Cost recommendation"}
                            </span>
                            <div className="table-secondary">{row.solution}</div>
                          </td>
                          <td>
                            <StatusBadge
                              label={row.impact || "unknown"}
                              tone={
                                row.impact?.toLowerCase() === "high"
                                  ? "critical"
                                  : "warning"
                              }
                            />
                          </td>
                          <td>{money(row.annual_savings, row.currency)}</td>
                          <td>
                            {row.owner ||
                              row.business_service ||
                              row.subscription ||
                              "Unattributed"}
                          </td>
                          <td>
                            <div className="resource-id-cell" title={row.resource_id || undefined}>
                              {row.resource_id || "—"}
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
                total={opportunityPaging.total}
                pageRows={opportunityPaging.pageRows.length}
                page={opportunityPaging.page}
                onPageChange={opportunityPaging.setPage}
                pageSize={opportunityPaging.pageSize}
                onPageSizeChange={opportunityPaging.setPageSize}
                label="opportunities"
              />
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <div>
                <h2>Waste</h2>
                <p>
                  Resources that are provisioned but not delivering value, from
                  Advisor and from observed inventory state.
                </p>
              </div>
            </div>
            <div className="card-body">
              {wasteRows.length === 0 ? (
                <StatePanel
                  title="No waste detected"
                  message="No idle, deallocated, or unattached resource was observed in the current scope."
                />
              ) : (
                <>
                <TableColumnFilters
                  filters={wasteFilters}
                  onReset={resetWasteFilters}
                  resultCount={filteredWasteRows.length}
                  totalCount={wasteRows.length}
                />
                <div className="table-scroll">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Resource</th>
                        <th>Reason</th>
                        <th>Annual saving</th>
                        <th>Owner</th>
                      </tr>
                    </thead>
                    <tbody>
                      {wastePaging.pageRows.map((row, index) => (
                        <tr key={row.resource_id || index}>
                          <td>
                            <span className="table-primary-link">
                              {row.resource_type || "Resource"}
                            </span>
                            <div className="table-secondary">
                              <span className="resource-id-cell" title={row.resource_id}>
                                {row.resource_id}
                              </span>
                            </div>
                          </td>
                          <td>
                            <span className="table-primary-link">
                              {titleize(row.reason || "unknown")}
                            </span>
                            <div className="table-secondary">{row.detail}</div>
                          </td>
                          <td>{money(row.annual_savings, row.currency)}</td>
                          <td>
                            {row.owner ||
                              row.business_service ||
                              row.subscription ||
                              "Unattributed"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                </>
              )}
              <TablePagination
                total={wastePaging.total}
                pageRows={wastePaging.pageRows.length}
                page={wastePaging.page}
                onPageChange={wastePaging.setPage}
                pageSize={wastePaging.pageSize}
                onPageSizeChange={wastePaging.setPageSize}
                label="waste items"
              />
            </div>
          </section>
        </>
      )}

      <CopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        contextLabel="Financial accountability"
        requestedScope={finopsCopilot.requestedScope}
        snapshot={finopsCopilot.snapshot}
        starterQuestions={finopsCopilot.starterQuestions}
      />
    </div>
  );
}
