import { expect, test, type Page } from "@playwright/test";
import { buildCostSignals } from "../src/test/accountability-fixtures";

async function mockCosts(page: Page) {
  const cost = buildCostSignals(9);
  const opportunities = cost.opportunities.map((row, index) => ({
    ...row,
    annual_savings: index === 8 ? null : index === 7 ? 900 : index * 100.25,
    currency: index === 7 ? "" : index === 6 ? "USD" : "AUD",
    savings_source: `Observed recommendation source ${index} with a detailed provider label`,
  }));
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const data: Record<string, unknown> = {
      "/subscription-connections": [],
      "/governance/finops/summary": { ...cost.summary, currency: "mixed", identified_annual_savings: null },
      "/governance/finops/opportunities": { opportunities, count: opportunities.length },
      "/governance/finops/waste": { waste: [], count: 0 },
      "/governance/finops/attribution": { groups: [], count: 0, dimension: "subscription" },
      "/governance/finops/verified-remediations": { executions: [], count: 0 },
    };
    return path in data
      ? route.fulfill({ json: { data: data[path], scope: {}, warnings: [], evidence: [] } })
      : route.fulfill({ status: 503, json: { error: { code: "unavailable", message: `Unmocked source: ${path}` } } });
  });
}

for (const width of [1440, 820, 768, 375, 320]) {
  test(`Financial charts separate currencies and preserve readable values at ${width}px`, async ({ page }, info) => {
    await mockCosts(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/finops");
    const charts = page.getByRole("region", { name: "Identified annual savings by currency", exact: true });
    await expect(charts.getByRole("list")).toHaveCount(2);
    await expect(charts.getByText("AUD: 1,503.75 identified annually", { exact: true })).toBeVisible();
    await expect(charts.getByText("USD: 601.5 identified annually", { exact: true })).toBeVisible();
    const aud = charts.getByRole("list", { name: "Identified annual savings in AUD", exact: true });
    await expect(aud.getByRole("listitem")).toHaveCount(6);
    await expect(aud.getByText("0 AUD", { exact: true })).toBeVisible();
    await expect(charts.getByText(/1 unquantified or invalid amounts; 1 quantified amounts with unreported currency/)).toBeVisible();
    for (const text of await charts.locator(".count-bar-label, .count-bar-value").all()) {
      expect(await text.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
    const review = charts.getByRole("link", { name: "Review filtered opportunity records", exact: true });
    await review.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#cost-opportunities$/);
    const records = page.getByRole("region", { name: "Savings opportunities", exact: true });
    await expect(records.getByRole("heading", { name: "Savings opportunities", exact: true })).toBeInViewport();
    await records.getByRole("combobox", { name: "Filter by Impact", exact: true }).selectOption("Medium");
    await expect(charts.getByText("AUD: 902.25 identified annually", { exact: true })).toBeVisible();
    await expect(charts.getByRole("list", { name: "Identified annual savings in USD", exact: true })).toHaveCount(0);
    await records.getByRole("button", { name: "Clear filters", exact: true }).click();
    await expect(charts.getByRole("list")).toHaveCount(2);
    if (width === 1440 || width === 375) {
      await charts.scrollIntoViewIfNeeded();
      await charts.screenshot({ path: info.outputPath(`savings-currencies-${width}.png`) });
    }
  });
}
