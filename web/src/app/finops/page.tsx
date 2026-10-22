"use client";

import { useMemo, useState, type FormEvent } from "react";
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
import type { FinOpsVerifiedRemediation } from "@/lib/types";
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
type ScenarioName = "A" | "B";

interface ScenarioSummary {
  name: ScenarioName;
  selectedCount: number;
  currencyTotals: Array<{ currency: string; amount: number }>;
  unreportedCurrencyCount: number;
  unquantifiedCount: number;
}

const EMPTY_SELECTION = new Set<string>();

function opportunityKey(row: {
  recommendation_id: string;
  resource_id: string;
  problem: string;
  solution: string;
  currency: string;
}): string {
  return JSON.stringify([
    row.recommendation_id,
    row.resource_id,
    row.problem,
    row.solution,
    row.currency,
  ]);
}

/** Renders a saving, keeping "not quantified" visibly distinct from zero. */
function money(amount: number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined) return "Not quantified";
  const formatted = Math.round(amount).toLocaleString();
  return currency ? `${formatted} ${currency}` : `${formatted} (currency unreported)`;
}

function aggregateMoney(amount: number | null | undefined, currency: string): string {
  if (currency === "mixed") return "Mixed currencies — not aggregated";
  if (currency === "unreported") return "Currency unreported — not aggregated";
  return money(amount, currency);
}

function currencyTotalsText(
  totals: Array<{ currency: string; amount: number | null; count: number }>,
): string {
  return totals
    .map((total) =>
      total.currency === "unreported"
        ? `${total.count} ${total.count === 1 ? "amount" : "amounts"} with currency unreported`
        : money(total.amount, total.currency),
    )
    .join("; ");
}

/** Reviews scoped cost evidence without treating unknown savings as zero. */
export default function FinOpsPage() {
  const { scope } = useScope();
  const [dimension, setDimension] = useState<Dimension>("subscription");
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [executionOffset, setExecutionOffset] = useState(0);
  const [selectedExecution, setSelectedExecution] = useState<{
    scopeKey: string;
    executionId: string;
  }>(() => ({ scopeKey: JSON.stringify(scope), executionId: "" }));
  const [baselineStart, setBaselineStart] = useState("");
  const [baselineEnd, setBaselineEnd] = useState("");
  const [followupStart, setFollowupStart] = useState("");
  const [followupEnd, setFollowupEnd] = useState("");
  const [comparisonRequest, setComparisonRequest] = useState<{
    scopeKey: string;
    execution_id: string;
    baseline_start: string;
    baseline_end: string;
    followup_start: string;
    followup_end: string;
  } | null>(null);
  const [scenarioSelection, setScenarioSelection] = useState<{
    scopeKey: string;
    a: Set<string>;
    b: Set<string>;
  }>(() => ({ scopeKey: JSON.stringify(scope), a: new Set(), b: new Set() }));
  const scenarioScopeKey = JSON.stringify(scope);
  const scenarioASelection =
    scenarioSelection.scopeKey === scenarioScopeKey
      ? scenarioSelection.a
      : EMPTY_SELECTION;
  const scenarioBSelection =
    scenarioSelection.scopeKey === scenarioScopeKey
      ? scenarioSelection.b
      : EMPTY_SELECTION;

  const summary = useApi(() => governanceApi.finopsSummary(scope), [scope]);
  const opportunities = useApi(() => governanceApi.finopsOpportunities(scope), [scope]);
  const waste = useApi(() => governanceApi.finopsWaste(scope), [scope]);
  const verifiedRemediations = useApi(
    () => governanceApi.finopsVerifiedRemediations(scope, executionOffset),
    [scope, executionOffset],
  );
  const costComparison = useApi(
    () =>
      comparisonRequest?.scopeKey === scenarioScopeKey
        ? governanceApi.finopsRemediationCostComparison(scope, {
            execution_id: comparisonRequest.execution_id,
            baseline_start: comparisonRequest.baseline_start,
            baseline_end: comparisonRequest.baseline_end,
            followup_start: comparisonRequest.followup_start,
            followup_end: comparisonRequest.followup_end,
          })
        : Promise.resolve(null),
    [scope, comparisonRequest],
  );
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
    totals?.actual_spend !== undefined && totals.actual_spend !== null
      ? `${totals.actual_spend_period_start || "Current period"} to ${
          totals.actual_spend_period_end || "latest"
        } from Cost Management (${totals.actual_spend_record_count ?? 0} rows). ` +
        "Not real-time — refreshed on sync. Go to Connections, click \"Sync now\" to refresh."
      : totals?.actual_spend === null
        ? `${totals.actual_spend_record_count ?? 0} Cost Management rows from ${
            totals.actual_spend_period_start || "an unknown start"
          } to ${totals.actual_spend_period_end || "an unknown end"} were observed, but their currencies cannot be combined. No foreign-exchange conversion is applied.`
      : "Not real-time — synced periodically from Cost Management. " +
        "Go to Connections, click \"Sync now\" on the subscription connection to refresh.";

  const rows = useMemo(
    () => opportunities.data?.data.opportunities ?? [],
    [opportunities.data],
  );
  const scenarioSummaries = useMemo(() => {
    const summarize = (
      name: ScenarioName,
      selectedIds: Set<string>,
    ): ScenarioSummary => {
      const totals = new Map<string, number>();
      let selectedCount = 0;
      let unreportedCurrencyCount = 0;
      let unquantifiedCount = 0;

      for (const row of rows) {
        if (!selectedIds.has(opportunityKey(row))) continue;
        selectedCount += 1;
        if (
          typeof row.annual_savings !== "number" ||
          !Number.isFinite(row.annual_savings) ||
          row.annual_savings < 0
        ) {
          unquantifiedCount += 1;
          continue;
        }
        const code = row.currency.trim().toUpperCase();
        if (!/^[A-Z]{3}$/.test(code)) {
          unreportedCurrencyCount += 1;
          continue;
        }
        totals.set(code, (totals.get(code) ?? 0) + row.annual_savings);
      }

      return {
        name,
        selectedCount,
        currencyTotals: Array.from(totals.entries())
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([currencyCode, amount]) => ({ currency: currencyCode, amount })),
        unreportedCurrencyCount,
        unquantifiedCount,
      };
    };

    return [
      summarize("A", scenarioASelection),
      summarize("B", scenarioBSelection),
    ];
  }, [rows, scenarioASelection, scenarioBSelection]);
  const wasteRows = useMemo(() => waste.data?.data.waste ?? [], [waste.data]);
  const attributionGroups = useMemo(
    () => attribution.data?.data.groups ?? [],
    [attribution.data],
  );
  const remediationExecutions =
    verifiedRemediations.data?.data.executions ?? [];
  const selectedExecutionId =
    selectedExecution.scopeKey === scenarioScopeKey
      ? selectedExecution.executionId
      : "";
  const comparisonResult = costComparison.data?.data ?? null;
  const currencyBreakdownVisible =
    totals?.currency === "mixed" ||
    totals?.currency === "unreported" ||
    totals?.actual_spend_currency === "mixed" ||
    totals?.actual_spend_currency === "unreported";

  const {
    filteredRows: filteredAttributionGroups,
    filters: attributionFilters,
    resetFilters: resetAttributionFilters,
  } = useColumnFilters(attributionGroups, [
    {
      id: "group",
      label: titleize(dimension),
      getValues: (group) => {
        const value = group[dimension];
        return typeof value === "string" ? value : "Unattributed";
      },
    },
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
      const currencyCode = opportunity.currency.trim().toUpperCase();
      if (
        opportunity.annual_savings === null ||
        !/^[A-Z]{3}$/.test(currencyCode)
      ) {
        continue;
      }
      const key = `${titleize(opportunity.savings_source || "unknown")} (${currencyCode})`;
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

  const toggleScenarioSelection = (
    scenario: ScenarioName,
    key: string,
  ) => {
    setScenarioSelection((current) => {
      const base =
        current.scopeKey === scenarioScopeKey
          ? current
          : { scopeKey: scenarioScopeKey, a: new Set<string>(), b: new Set<string>() };
      const field = scenario === "A" ? "a" : "b";
      const next = new Set(base[field]);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return scenario === "A"
        ? { ...base, scopeKey: scenarioScopeKey, a: next }
        : { ...base, scopeKey: scenarioScopeKey, b: next };
    });
  };

  const clearScenarioSelection = (scenario: ScenarioName) => {
    setScenarioSelection((current) => {
      const base =
        current.scopeKey === scenarioScopeKey
          ? current
          : { scopeKey: scenarioScopeKey, a: new Set<string>(), b: new Set<string>() };
      return scenario === "A"
        ? { ...base, scopeKey: scenarioScopeKey, a: new Set() }
        : { ...base, scopeKey: scenarioScopeKey, b: new Set() };
    });
  };

  const submitCostComparison = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      !selectedExecutionId ||
      !baselineStart ||
      !baselineEnd ||
      !followupStart ||
      !followupEnd
    ) {
      return;
    }
    setComparisonRequest({
      scopeKey: scenarioScopeKey,
      execution_id: selectedExecutionId,
      baseline_start: baselineStart,
      baseline_end: baselineEnd,
      followup_start: followupStart,
      followup_end: followupEnd,
    });
  };

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
          identified_annual_savings_currency_totals:
            totals.identified_annual_savings_currency_totals ?? [],
          savings_opportunity_count: totals.savings_opportunity_count,
          quantified_opportunity_count: totals.quantified_opportunity_count,
          waste_item_count: totals.waste_item_count,
          actual_spend: totals.actual_spend,
          actual_spend_currency: totals.actual_spend_currency,
          actual_spend_currency_totals: totals.actual_spend_currency_totals ?? [],
          actual_spend_period_start: totals.actual_spend_period_start,
          actual_spend_period_end: totals.actual_spend_period_end,
          unavailable_metrics: totals.unavailable_metrics ?? [],
        }
      : null,
    dimension,
    attribution: attributionGroups.map((group) => ({
      dimension,
      group: String(group[dimension] ?? "Unattributed"),
      identified_annual_savings: group.identified_annual_savings,
      currency: group.currency,
      identified_annual_savings_currency_totals:
        group.identified_annual_savings_currency_totals ?? [],
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
    <div className="page-container operational-page finops-workspace">
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

      {!error && !loading && (
        <nav className="section-nav" aria-label="Cost sections">
          <a href="#cost-overview">Overview</a>
          {(totals?.unavailable_metrics?.length ?? 0) > 0 && <a href="#cost-coverage">Coverage gaps</a>}
          <a href="#cost-attribution">Attribution</a>
          <a href="#cost-opportunities">Savings opportunities</a>
          <a href="#cost-waste">Waste</a>
        </nav>
      )}

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
          <div id="cost-overview" className="metric-grid" role="region" aria-label="Cost overview">
            <MetricCard
              label="Identified annual savings"
              value={aggregateMoney(
                totals?.identified_annual_savings,
                currency,
              )}
              detail="Azure Advisor's own computation, not an estimate of ours"
              tone={
                typeof totals?.identified_annual_savings === "number"
                  ? "success"
                  : "warning"
              }
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
              value={totals?.actual_spend === undefined
                ? "Unavailable"
                : aggregateMoney(totals.actual_spend, billedSpendCurrency)}
              detail={billedSpendDetail}
              tone={
                typeof totals?.actual_spend === "number"
                  ? "success"
                  : totals?.actual_spend === null
                    ? "warning"
                    : "critical"
              }
            />
          </div>

          {(savingsByCategory.length > 0 || wasteByType.length > 0) && (
            <div className="card dashboard-charts-row">
              {savingsByCategory.length > 0 && (
                <div className="chart-card">
                  <h3 className="chart-card-title">Savings by source and currency</h3>
                  <DonutChart
                    segments={savingsByCategory}
                    centerValue={aggregateMoney(
                      totals?.identified_annual_savings,
                      currency,
                    )}
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
            <section id="cost-coverage" className="card" aria-labelledby="cost-coverage-heading">
              <div className="card-header">
                <div>
                  <h2 id="cost-coverage-heading">Coverage gaps</h2>
                  <p>
                These figures are deliberately absent rather than estimated
                or inferred from unrelated observations.
                  </p>
                </div>
              </div>
              <div className="card-body">
                <div className="table-scroll" tabIndex={0} role="region" aria-label="Unavailable cost metrics">
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

          {currencyBreakdownVisible && (
            <section className="card">
              <div className="card-header">
                <div>
                  <h2>Financial totals by currency</h2>
                  <p>
                    Amounts are grouped only when Azure reports the same
                    currency. No exchange-rate conversion is applied.
                  </p>
                </div>
              </div>
              <div className="card-body">
                <div className="table-scroll" tabIndex={0} role="region" aria-label="Financial totals by currency">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Evidence</th>
                        <th>Currency</th>
                        <th>Amount</th>
                        <th>Records</th>
                        <th>Period</th>
                      </tr>
                    </thead>
                    <tbody>
                      {totals?.identified_annual_savings_currency_totals?.map(
                        (total) => (
                          <tr key={`savings-${total.currency}`}>
                            <td>Azure Advisor annual savings</td>
                            <td>
                              {total.currency === "unreported"
                                ? "Not reported"
                                : total.currency}
                            </td>
                            <td>
                              {total.amount === null
                                ? "Not aggregated — currency unreported"
                                : money(total.amount, total.currency)}
                            </td>
                            <td>{total.count} opportunities</td>
                            <td>Annualized</td>
                          </tr>
                        ),
                      )}
                      {totals?.actual_spend_currency_totals?.map((total) => (
                        <tr key={`spend-${total.currency}`}>
                          <td>Cost Management actual spend</td>
                          <td>
                            {total.currency === "unreported"
                              ? "Not reported"
                              : total.currency}
                          </td>
                          <td>
                            {total.amount === null
                              ? "Not aggregated — currency unreported"
                              : money(total.amount, total.currency)}
                          </td>
                          <td>{total.count} rows</td>
                          <td>
                            {totals.actual_spend_period_start || "Unknown"} to{" "}
                            {totals.actual_spend_period_end || "Unknown"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          <section id="cost-attribution" className="card" aria-labelledby="cost-attribution-heading">
            <div className="card-header">
              <div>
                <h2 id="cost-attribution-heading">Attribution</h2>
                <p>Which part of the business owns the identified savings.</p>
              </div>
              <div className="segmented-control" role="group" aria-label="Attribution dimension">
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
                  message={attribution.error.message}
                  tone="error"
                  action={<button className="button button-secondary" type="button" onClick={attribution.refetch}>Retry attribution</button>}
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
                <div className="table-scroll" tabIndex={0} role="region" aria-label="Attributed savings records">
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
                            {group.identified_annual_savings_currency_totals?.length
                              ? currencyTotalsText(
                                  group.identified_annual_savings_currency_totals,
                                )
                              : aggregateMoney(
                                  group.identified_annual_savings,
                                  group.currency ?? currency,
                                )}
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
              {!attribution.error && !attribution.loading && <TablePagination
                total={attributionPaging.total}
                pageRows={attributionPaging.pageRows.length}
                page={attributionPaging.page}
                onPageChange={attributionPaging.setPage}
                pageSize={attributionPaging.pageSize}
                onPageSizeChange={attributionPaging.setPageSize}
                label="groups"
              />}
            </div>
          </section>

          <section id="cost-scenarios" className="card" aria-labelledby="cost-scenarios-heading">
            <div className="card-header">
              <div>
                <h2 id="cost-scenarios-heading">Review scenarios</h2>
                <p>
                  Compare temporary selections of Azure Advisor opportunities.
                  The annualized figures stay separate by currency and are
                  potential amounts only—not realized, approved, or guaranteed.
                </p>
              </div>
            </div>
            <div className="card-body">
              <div className="table-scroll" tabIndex={0} role="region" aria-label="Cost review scenarios">
                <table className="operations-table">
                  <thead>
                    <tr>
                      <th>Scenario</th>
                      <th>Selected opportunities</th>
                      <th>Potential annualized amounts</th>
                      <th>Unreported currency</th>
                      <th>Not quantified</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scenarioSummaries.map((scenario) => {
                      const amounts = scenario.currencyTotals
                        .map((total) => money(total.amount, total.currency))
                        .join("; ");
                      const detail = [
                        amounts || "No comparable quantified amounts",
                        scenario.unreportedCurrencyCount > 0
                          ? `${scenario.unreportedCurrencyCount} excluded from totals`
                          : null,
                        scenario.unquantifiedCount > 0
                          ? `${scenario.unquantifiedCount} unquantified`
                          : null,
                      ]
                        .filter(Boolean)
                        .join("; ");
                      return (
                        <tr key={scenario.name}>
                          <td>
                            <span className="table-primary-link">
                              Scenario {scenario.name}
                            </span>
                          </td>
                          <td>{scenario.selectedCount}</td>
                          <td>{detail}</td>
                          <td>{scenario.unreportedCurrencyCount}</td>
                          <td>{scenario.unquantifiedCount}</td>
                          <td>
                            <button
                              type="button"
                              aria-label={`Clear Scenario ${scenario.name}`}
                              onClick={() => clearScenarioSelection(scenario.name)}
                              disabled={scenario.selectedCount === 0}
                            >
                              Clear
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="table-secondary">
                Selections are held only in this page session. They do not save
                a decision, approve an action, or trigger remediation.
              </p>
            </div>
          </section>

          <section className="card">
            <div className="card-header">
              <div>
                <h2>Compare cost around a verified change</h2>
                <p>
                  Compare equal-length Cost Management windows for the exact
                  resource in a successfully executed, cleanly reconciled
                  remediation. This is observed cost movement, not proof of
                  realized savings or causality.
                </p>
              </div>
            </div>
            <div className="card-body">
              {verifiedRemediations.error ? (
                <StatePanel
                  title="Verified remediation evidence is unavailable"
                  message={
                    verifiedRemediations.error.message ??
                    "Stored remediation evidence could not be confirmed."
                  }
                  tone="error"
                />
              ) : verifiedRemediations.loading ? (
                <StatePanel
                  title="Reading verified changes"
                  message="Checking successful remediation records and their stored evidence reconciliation."
                  tone="loading"
                />
              ) : remediationExecutions.length === 0 ? (
                <StatePanel
                  title="No verified remediation changes in this scope"
                  message="Only successful executions with clean stored evidence reconciliation are eligible for a cost comparison."
                />
              ) : (
                <>
                  <form
                    className="form-grid"
                    onSubmit={submitCostComparison}
                    aria-label="Compare cost around a verified change"
                  >
                    <label className="form-field form-span">
                      <span>Verified remediation</span>
                      <select
                        value={selectedExecutionId}
                        onChange={(event) => {
                          setSelectedExecution({
                            scopeKey: scenarioScopeKey,
                            executionId: event.target.value,
                          });
                          setComparisonRequest(null);
                        }}
                        required
                      >
                        <option value="">Select a verified change</option>
                        {remediationExecutions.map(
                          (execution: FinOpsVerifiedRemediation) => (
                            <option
                              key={execution.execution_id}
                              value={execution.execution_id}
                            >
                              {execution.changed_at.slice(0, 10)} —{" "}
                              {execution.target_resource_id} (
                              {execution.execution_id})
                            </option>
                          ),
                        )}
                      </select>
                    </label>
                    <label className="form-field">
                      <span>Baseline start</span>
                      <input
                        type="date"
                        value={baselineStart}
                        onChange={(event) => setBaselineStart(event.target.value)}
                        required
                      />
                    </label>
                    <label className="form-field">
                      <span>Baseline end</span>
                      <input
                        type="date"
                        value={baselineEnd}
                        onChange={(event) => setBaselineEnd(event.target.value)}
                        required
                      />
                    </label>
                    <label className="form-field">
                      <span>Follow-up start</span>
                      <input
                        type="date"
                        value={followupStart}
                        onChange={(event) => setFollowupStart(event.target.value)}
                        required
                      />
                    </label>
                    <label className="form-field">
                      <span>Follow-up end</span>
                      <input
                        type="date"
                        value={followupEnd}
                        onChange={(event) => setFollowupEnd(event.target.value)}
                        required
                      />
                    </label>
                    <div className="form-actions">
                      <button
                        type="submit"
                        disabled={costComparison.loading || !selectedExecutionId}
                      >
                        {costComparison.loading
                          ? "Comparing…"
                          : "Compare observed costs"}
                      </button>
                    </div>
                  </form>
                  {verifiedRemediations.data?.pagination?.next_offset !==
                    undefined &&
                    verifiedRemediations.data.pagination.next_offset !== null && (
                      <div className="form-actions">
                        <button
                          type="button"
                          disabled={executionOffset === 0}
                          onClick={() =>
                            setExecutionOffset((offset) => Math.max(0, offset - 50))
                          }
                        >
                          Previous changes
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            setExecutionOffset(
                              verifiedRemediations.data?.pagination?.next_offset ?? 0,
                            )
                          }
                        >
                          Next changes
                        </button>
                      </div>
                    )}
                  {costComparison.error && (
                    <StatePanel
                      title="Cost comparison could not be completed"
                      message={
                        costComparison.error.message ??
                        "The requested comparison was rejected."
                      }
                      tone="error"
                    />
                  )}
                  {comparisonResult && (
                    <div className="card" aria-live="polite">
                      {comparisonResult.available &&
                      comparisonResult.baseline &&
                      comparisonResult.followup &&
                      comparisonResult.currency &&
                      typeof comparisonResult.baseline.average_daily_cost ===
                        "number" &&
                      typeof comparisonResult.followup.average_daily_cost ===
                        "number" ? (
                        <>
                          <h3>Observed cost movement</h3>
                          <p>
                            Baseline average:{" "}
                            {comparisonResult.baseline.average_daily_cost.toFixed(
                              2,
                            )}{" "}
                            {comparisonResult.currency}/day (
                            {comparisonResult.baseline.start} to{" "}
                            {comparisonResult.baseline.end}). Follow-up average:{" "}
                            {comparisonResult.followup.average_daily_cost.toFixed(
                              2,
                            )}{" "}
                            {comparisonResult.currency}/day (
                            {comparisonResult.followup.start} to{" "}
                            {comparisonResult.followup.end}).
                          </p>
                          <p>
                            Average daily cost change:{" "}
                            {comparisonResult.observed_average_daily_cost_change?.toFixed(
                              2,
                            )}{" "}
                            {comparisonResult.currency}/day; positive means the
                            observed average was lower in the follow-up period.
                          </p>
                        </>
                      ) : (
                        <>
                          <h3>Comparison unavailable</h3>
                          <p>{comparisonResult.reason}</p>
                        </>
                      )}
                      <p className="table-secondary">
                        Coverage:{" "}
                        {comparisonResult.coverage.baseline_days_observed}/
                        {comparisonResult.coverage.expected_days_per_window}{" "}
                        baseline days and{" "}
                        {comparisonResult.coverage.followup_days_observed}/
                        {comparisonResult.coverage.expected_days_per_window}{" "}
                        follow-up days. Snapshot observed at{" "}
                        {comparisonResult.coverage.snapshot_observed_at || "unknown"}.
                      </p>
                      <ul>
                        {comparisonResult.limitations.map((limitation) => (
                          <li key={limitation}>{limitation}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <p className="table-secondary">
                    Windows must be equal length, non-overlapping, no more than
                    30 days each, and fully covered by same-currency daily
                    records. This read-only comparison does not approve or
                    execute remediation.
                  </p>
                </>
              )}
            </div>
          </section>

          <section id="cost-opportunities" className="card" aria-labelledby="cost-opportunities-heading">
            <div className="card-header">
              <div>
                <h2 id="cost-opportunities-heading">Savings opportunities</h2>
                <p>
                  Azure Advisor cost recommendations, richest quantified saving
                  first. Use the checkboxes to compare opportunities above.
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
                <div className="table-scroll" tabIndex={0} role="region" aria-label="Savings opportunity records">
                  <table className="operations-table">
                    <thead>
                      <tr>
                        <th>Scenario A</th>
                        <th>Scenario B</th>
                        <th>Recommendation</th>
                        <th>Impact</th>
                        <th>Annual saving</th>
                        <th>Owner</th>
                        <th>Resource</th>
                      </tr>
                    </thead>
                    <tbody>
                      {opportunityPaging.pageRows.map((row) => {
                        const key = opportunityKey(row);
                        return (
                        <tr key={key}>
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`Include ${row.problem || "cost recommendation"} in Scenario A`}
                              checked={scenarioASelection.has(key)}
                              onChange={() => toggleScenarioSelection("A", key)}
                            />
                          </td>
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`Include ${row.problem || "cost recommendation"} in Scenario B`}
                              checked={scenarioBSelection.has(key)}
                              onChange={() => toggleScenarioSelection("B", key)}
                            />
                          </td>
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
                        );
                      })}
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

          <section id="cost-waste" className="card" aria-labelledby="cost-waste-heading">
            <div className="card-header">
              <div>
                <h2 id="cost-waste-heading">Waste</h2>
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
                <div className="table-scroll" tabIndex={0} role="region" aria-label="Waste resource records">
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



      <CopilotInsights
        snapshot={finopsCopilot.snapshot}
        ready={!loading}
        requestedScope={finopsCopilot.requestedScope}
        contextLabel="Financial accountability"
        onOpenCopilot={() => setCopilotOpen(true)}
      />

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
