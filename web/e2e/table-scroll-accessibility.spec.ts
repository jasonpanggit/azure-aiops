import { expect, test, type Locator, type Page } from "@playwright/test";
import { buildCostSignals } from "../src/test/accountability-fixtures";

const envelope = (data: unknown) => ({
  data, scope: {}, evidence: [], warnings: [], knowledge_version: "table-scroll-test",
});

async function mockSources(page: Page) {
  const cost = buildCostSignals();
  await page.route("**/api/v1/**", route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    const data: Record<string, unknown> = {
      "/subscription-connections": [{
        connection_id: "production", name: "Production operational subscription",
        subscription_id: "00000000-0000-0000-0000-000000000001",
        tenant_id: "00000000-0000-0000-0000-000000000002",
        is_active: true, health_status: "healthy", sync_status: "succeeded",
        last_successful_sync_at: "2026-10-22T06:00:00Z", business_service: "Payments",
        environment: "Production", criticality: "critical",
      }],
      "/governance/finops/summary": {
        ...cost.summary, currency: "mixed", identified_annual_savings: null,
        identified_annual_savings_currency_totals: [
          { currency: "AUD", amount: 125000, count: 22 },
          { currency: "USD", amount: 500, count: 1 },
        ],
      },
      "/governance/finops/opportunities": { opportunities: cost.opportunities, count: 23 },
      "/governance/finops/waste": { waste: cost.waste, count: 23 },
      "/governance/finops/attribution": { groups: cost.groups, count: 23, dimension: url.searchParams.get("dimension") },
      "/inventory/resources": {
        resources: [{
          family: "paas", resource_name: "Published payments application",
          resource_id: "/subscriptions/sub-table/resourceGroups/payments/providers/Microsoft.Web/sites/payments",
          resource_type: "microsoft.web/sites", subscription_id: "sub-table",
          resource_group: "payments", environment: "production",
        }],
        family_availability: {}, represented_count: 1,
        generation_id: "table-scroll-generation", query_version: "inventory-resources-v1",
      },
    };
    if (!(path in data)) return route.fulfill({
      status: 503, json: { detail: `Unmocked source: ${path}` },
    });
    return route.fulfill({ json: {
      ...envelope(data[path]),
      ...(path === "/inventory/resources" ? {
        pagination: { offset: 0, limit: 25, total: 1, next_offset: null },
      } : {}),
    } });
  });
}

async function checkScroller(page: Page, scroller: Locator, width: number) {
  await expect(scroller).toHaveAttribute("tabindex", "0");
  await expect(scroller.locator("table")).toBeVisible();
  await scroller.focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(scroller).toBeFocused();
  await expect(scroller).toHaveCSS("outline-style", "solid");
  await expect(scroller).toHaveCSS("outline-width", "3px");
  const overflowing = await scroller.evaluate(element => element.scrollWidth > element.clientWidth);
  if (width <= 820) expect(overflowing).toBe(true);
  if (overflowing) {
    await scroller.evaluate(element => { element.scrollLeft = 0; });
    await expect.poll(() => scroller.evaluate(element => element.scrollLeft)).toBe(0);
    const forward = scroller.evaluate(element => new Promise<number>(resolve => {
      element.addEventListener("scrollend", () => resolve(element.scrollLeft), { once: true });
    }));
    await scroller.press("ArrowRight");
    expect(await forward).toBeGreaterThan(0);
    const backward = scroller.evaluate(element => new Promise<number>(resolve => {
      element.addEventListener("scrollend", () => resolve(element.scrollLeft), { once: true });
    }));
    await scroller.press("ArrowLeft");
    expect(await backward).toBe(0);
  }
  expect(await page.evaluate(() => document.documentElement.scrollLeft)).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
}

for (const width of [1440, 820, 768, 375, 320]) {
  test(`Connections registry supports named keyboard scrolling at ${width}px`, async ({ page }) => {
    await mockSources(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/connections");
    const records = page.getByRole("region", { name: "Connection registry records", exact: true });
    await expect(records.locator("tbody tr")).toHaveCount(1);
    await checkScroller(page, records, width);
    await expect(records.getByRole("button", { name: "Sync now", exact: true })).toBeEnabled();
  });

  test(`FinOps totals and scenarios support named keyboard scrolling at ${width}px`, async ({ page }) => {
    await mockSources(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/finops");
    const totals = page.getByRole("region", { name: "Financial totals by currency", exact: true });
    await expect(totals.locator("tbody tr")).toHaveCount(2);
    await checkScroller(page, totals, width);
    const scenarios = page.getByRole("region", { name: "Cost review scenarios", exact: true });
    await expect(scenarios.locator("tbody tr")).toHaveCount(2);
    await checkScroller(page, scenarios, width);
    for (const scroller of await page.locator(".table-scroll").all()) {
      await expect(scroller).toHaveAttribute("role", "region");
      await expect(scroller).toHaveAttribute("aria-label", /.+/);
      await expect(scroller).toHaveAttribute("tabindex", "0");
    }
  });

  test(`Published assets support named keyboard scrolling at ${width}px`, async ({ page }, testInfo) => {
    await mockSources(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/inventory/assets");
    const records = page.getByRole("region", { name: "Published asset records", exact: true });
    await expect(records.locator("tbody tr")).toHaveCount(1);
    await checkScroller(page, records, width);
    await expect(records.getByRole("link", { name: "Published payments application" })).toHaveAttribute("href", /resource_id=/);
    if (width === 375) await page.screenshot({ path: testInfo.outputPath("assets-focus-375.png") });
  });
}
