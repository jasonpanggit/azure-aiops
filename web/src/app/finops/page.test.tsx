import { beforeEach, describe, expect, it, vi } from "vitest";

const { services, scope } = vi.hoisted(() => ({
  scope: {},
  services: {
    finopsSummary: vi.fn(),
    finopsOpportunities: vi.fn(),
    finopsWaste: vi.fn(),
    finopsAttribution: vi.fn(),
  },
}));

vi.mock("@/lib/services", () => ({ governanceApi: services }));
vi.mock("@/lib/scope-context", () => ({ useScope: () => ({ scope }) }));
vi.mock("@/lib/copilot/page-adapters", () => ({
  buildFinOpsCopilotContext: () => ({
    snapshot: {},
    requestedScope: {},
    starterQuestions: [],
  }),
}));
vi.mock("@/components/ui/CopilotInsights", () => ({ CopilotInsights: () => null }));
vi.mock("@/components/ui/CopilotDrawer", () => ({
  CopilotDrawer: () => null,
}));

import { fireEvent, render, screen, within } from "@testing-library/react";
import FinOpsPage from "./page";

function envelope(data: object) {
  return {
    data,
    evidence: [],
    warnings: [],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  services.finopsSummary.mockResolvedValue(
    envelope({
      identified_annual_savings: null,
      currency: "mixed",
      identified_annual_savings_currency_totals: [
        { currency: "EUR", amount: 200, count: 1 },
        { currency: "USD", amount: 100, count: 1 },
        { currency: "unreported", amount: null, count: 1 },
      ],
      savings_opportunity_count: 4,
      quantified_opportunity_count: 3,
      waste_item_count: 0,
      actual_spend: null,
      actual_spend_currency: "mixed",
      actual_spend_currency_totals: [
        { currency: "EUR", amount: 17.75, count: 1 },
        { currency: "USD", amount: 12.25, count: 1 },
        { currency: "unreported", amount: null, count: 1 },
      ],
      actual_spend_period_start: "2026-01-14",
      actual_spend_period_end: "2026-01-16",
      actual_spend_record_count: 3,
      unavailable_metrics: [
        {
          metric: "realized_savings",
          reason:
            "No verified remediation-to-resource change is linked to comparable pre-change and post-change Cost Management actuals. Spend movement alone is not evidence of realized savings.",
        },
      ],
    }),
  );
  services.finopsOpportunities.mockResolvedValue(
    envelope({
      count: 4,
      opportunities: [
        {
          recommendation_id: "advisor-eur",
          resource_id: "/vm/eur",
          problem: "EUR recommendation",
          solution: "Review",
          impact: "Medium",
          annual_savings: 200,
          currency: "EUR",
          savings_source: "azure_advisor",
          application: "App",
        },
        {
          recommendation_id: "advisor-usd",
          resource_id: "/vm/usd",
          problem: "USD recommendation",
          solution: "Review",
          impact: "Medium",
          annual_savings: 100,
          currency: "USD",
          savings_source: "azure_advisor",
          application: "App",
        },
        {
          recommendation_id: "advisor-unreported",
          resource_id: "/vm/unreported",
          problem: "Unreported currency",
          solution: "Review",
          impact: "Low",
          annual_savings: 50,
          currency: "",
          savings_source: "azure_advisor",
          application: "App",
        },
        {
          recommendation_id: "advisor-unquantified",
          resource_id: "/vm/unquantified",
          problem: "Unquantified recommendation",
          solution: "Review",
          impact: "Low",
          annual_savings: null,
          currency: "USD",
          savings_source: "azure_advisor",
          application: "App",
        },
      ],
    }),
  );
  services.finopsWaste.mockResolvedValue(envelope({ count: 0, waste: [] }));
  services.finopsAttribution.mockResolvedValue(
    envelope({
      dimension: "subscription",
      count: 1,
      groups: [
        {
          subscription: "sub-a",
          identified_annual_savings: null,
          currency: "mixed",
          identified_annual_savings_currency_totals: [
            { currency: "EUR", amount: 200, count: 1 },
            { currency: "USD", amount: 100, count: 1 },
            { currency: "unreported", amount: null, count: 1 },
          ],
          savings_opportunity_count: 4,
          waste_item_count: 0,
        },
      ],
    }),
  );
});

describe("FinOps currency normalization", () => {
  it("keeps mixed and unreported currencies separate instead of summing them", async () => {
    render(<FinOpsPage />);

    expect(
      await screen.findByRole("heading", { name: "Financial totals by currency" }),
    ).toBeTruthy();
    expect(
      screen.getAllByText("Mixed currencies — not aggregated").length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("200 EUR").length).toBeGreaterThan(0);
    expect(screen.getAllByText("100 USD").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/currency unreported/).length).toBeGreaterThan(0);
    expect(screen.queryByText("350")).toBeNull();
    expect(screen.getByText("Realized Savings")).toBeTruthy();
    expect(screen.getByText(/Spend movement alone is not evidence/)).toBeTruthy();
  });

  it("compares temporary scenarios without combining currencies or asserting outcomes", async () => {
    render(<FinOpsPage />);

    const scenarioA = await screen.findByRole("heading", {
      name: "Review scenarios",
    });
    expect(scenarioA).toBeTruthy();

    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Include EUR recommendation in Scenario A",
      }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Include USD recommendation in Scenario A",
      }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Include EUR recommendation in Scenario B",
      }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Include Unreported currency in Scenario B",
      }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Include Unquantified recommendation in Scenario B",
      }),
    );

    const scenarioSection = screen
      .getByRole("heading", { name: "Review scenarios" })
      .closest("section");
    if (!scenarioSection) throw new Error("Scenario review section is missing");
    const scenarioRows = within(scenarioSection).getAllByRole("row");
    const rowA = scenarioRows[1];
    const rowB = scenarioRows[2];
    expect(rowA.textContent).toContain("2");
    expect(rowA.textContent).toContain("200 EUR; 100 USD");
    expect(rowB.textContent).toContain("3");
    expect(rowB.textContent).toContain("200 EUR");
    expect(rowB.textContent).toContain("1 excluded from totals");
    expect(rowB.textContent).toContain("1 unquantified");
    expect(
      screen.getByText(/not realized, approved, or guaranteed/),
    ).toBeTruthy();
  });
});
