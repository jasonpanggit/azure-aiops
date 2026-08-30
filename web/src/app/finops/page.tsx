"use client";

import { useMemo, useState } from "react";
import { EvidenceBar } from "@/components/ui/EvidenceBar";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatePanel } from "@/components/ui/StatePanel";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TablePagination } from "@/components/ui/TablePagination";
import { useApi } from "@/hooks/useApi";
import { titleize } from "@/lib/format";
import { useScope } from "@/lib/scope-context";
import { governanceApi } from "@/lib/services";
import { useTablePagination } from "@/lib/use-table-pagination";

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

  const attributionPaging = useTablePagination(attributionGroups);
  const opportunityPaging = useTablePagination(rows);
  const wastePaging = useTablePagination(wasteRows);

  return (
    <div className="page-container">
      <PageHeader
        eyebrow="Financial accountability"
        title="Where is spend signal available?"
        description="Review savings and waste attributed to the subscriptions, applications, business services, owners, and environments returned by Azure."
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
                    className={item === dimension ? "segmented-active" : ""}
                    onClick={() => setDimension(item)}
                  >
                    {titleize(item)}
                  </button>
                ))}
              </div>
            </div>
            <div className="card-body">
              {attribution.loading ? (
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
                            <div className="table-wrap">{row.resource_id || "—"}</div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
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
                              <span className="table-wrap">{row.resource_id}</span>
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
    </div>
  );
}
