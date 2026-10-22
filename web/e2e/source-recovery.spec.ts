import { expect, test, type Page } from "@playwright/test";
import { buildCostSignals } from "../src/test/accountability-fixtures";

const envelope = (data: unknown) => ({ data, scope: {}, evidence: [], warnings: [] });

async function assertRecoveryBounds(page: Page, width: number) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
  for (const control of await page.locator(".source-recovery-actions .button, .source-recovery-actions a").all()) {
    const box = await control.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
    expect(await control.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  }
}

for (const width of [1440, 820, 768, 375, 320]) {
  test(`Search recovers independently and preserves the submitted query at ${width}px`, async ({ page }, info) => {
    let searchAttempts = 0;
    let readinessAttempts = 0;
    let searchAvailable = false;
    let readinessAvailable = false;
    const requests: URL[] = [];
    await page.route("**/api/v1/**", route => {
      const url = new URL(route.request().url());
      const path = url.pathname.replace("/api/v1", "");
      if (path === "/search") {
        requests.push(url);
        ++searchAttempts;
        if (!searchAvailable) return route.fulfill({
          status: 503, json: { error: { code: "unavailable", message: "Search provider is temporarily unavailable." } },
        });
        return route.fulfill({ json: {
          ...envelope({
            intent: "resources missing ownership", results: [{ id: "vm-recovered", name: "Recovered VM", entity_type: "VirtualMachine" }],
            count: 1, represented_count: 30,
          }), pagination: { offset: 25, limit: 25, total: 30, next_offset: null },
        } });
      }
      if (path === "/search/capabilities") {
        ++readinessAttempts;
        if (!readinessAvailable) return route.fulfill({
          status: 503, json: { error: { code: "unavailable", message: "Readiness provider is temporarily unavailable." } },
        });
      }
      const data: Record<string, unknown> = {
        "/subscription-connections": [],
        "/saved-views": { schema_version: 1, revision: 1, views: [], actor: "test", scope: {} },
        "/search/capabilities": {
          live: { state: "configured", can_query: true, phrases: ["resources missing ownership"], prerequisite: "Active connection required." },
          semantic: { state: "deferred", can_query: false, phrases: ["production applications"], prerequisite: "Published semantic snapshot required." },
          identity: { state: "configured", prerequisite: "Exact principal identifier required." },
        },
      };
      return path in data ? route.fulfill({ json: envelope(data[path]) })
        : route.fulfill({ status: 503, json: { error: { message: `Unmocked source: ${path}` } } });
    });
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/search?q=resources+missing+ownership&entity_type=VirtualMachine&source=ARG&offset=25&subscription=sub-a&subscription=sub-b");
    await expect(page.getByRole("button", { name: "Retry submitted search", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry search readiness", exact: true })).toBeVisible();
    await page.waitForLoadState("networkidle");
    const before = { search: searchAttempts, readiness: readinessAttempts };
    await assertRecoveryBounds(page, width);
    if (width === 1440 || width === 375) await page.screenshot({ path: info.outputPath(`search-recovery-${width}.png`), fullPage: true });
    const input = page.getByRole("textbox", { name: "Operational search intent" });
    await input.fill("unsent draft");
    const retry = page.getByRole("button", { name: "Retry submitted search", exact: true });
    searchAvailable = true;
    await retry.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Recovered VM", exact: true })).toBeVisible();
    await expect(input).toHaveValue("unsent draft");
    expect(searchAttempts).toBe(before.search + 1);
    expect(readinessAttempts).toBe(before.readiness);
    expect(requests.at(-1)!.search).toBe(requests[before.search - 1].search);
    expect(requests.at(-1)!.searchParams.getAll("subscription")).toEqual(["sub-a", "sub-b"]);
    const readiness = page.getByRole("button", { name: "Retry search readiness", exact: true });
    readinessAvailable = true;
    await readiness.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "resources missing ownership", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "production applications", exact: true })).toBeDisabled();
    await expect(page.getByRole("heading", { name: "Recovered VM", exact: true })).toBeVisible();
    expect(readinessAttempts).toBe(before.readiness + 1);
    expect(searchAttempts).toBe(before.search + 1);
    expect(requests.at(-1)!.searchParams.get("offset")).toBe("25");
  });

  test(`FinOps retries failed sources without refreshing healthy sources at ${width}px`, async ({ page }, info) => {
    const cost = buildCostSignals(3);
    const counts: Record<string, number> = {};
    let summaryAvailable = false;
    let verifiedAvailable = false;
    await page.route("**/api/v1/**", route => {
      const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
      counts[path] = (counts[path] ?? 0) + 1;
      if (path === "/governance/finops/summary" && !summaryAvailable) return route.fulfill({
        status: 503, json: { error: { code: "unavailable", message: "Cost summary provider is temporarily unavailable. Reference: subscription-connection-with-long-provider-diagnostic-identifier-1234567890." } },
      });
      if (path === "/governance/finops/verified-remediations" && !verifiedAvailable) return route.fulfill({
        status: 503, json: { error: { code: "unavailable", message: "Stored verification evidence is temporarily unavailable." } },
      });
      const data: Record<string, unknown> = {
        "/subscription-connections": [],
        "/governance/finops/summary": cost.summary,
        "/governance/finops/opportunities": { opportunities: cost.opportunities, count: cost.opportunities.length },
        "/governance/finops/waste": { waste: cost.waste, count: cost.waste.length },
        "/governance/finops/attribution": { groups: cost.groups, count: cost.groups.length, dimension: "subscription" },
        "/governance/finops/verified-remediations": { executions: [], count: 0 },
      };
      return path in data ? route.fulfill({ json: envelope(data[path]) })
        : route.fulfill({ status: 503, json: { error: { message: `Unmocked source: ${path}` } } });
    });
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/finops?subscription=sub-a");
    await expect(page.getByRole("list", { name: "Cost source recovery" })).toBeVisible();
    await expect(page.getByText("Loaded for the current scope; not a guarantee of source freshness.", { exact: true })).toHaveCount(2);
    await page.waitForLoadState("networkidle");
    const before = { ...counts };
    await assertRecoveryBounds(page, width);
    if (width === 1440 || width === 375) await page.screenshot({ path: info.outputPath(`finops-recovery-${width}.png`), fullPage: true });
    const connection = new URL((await page.getByRole("link", { name: "Review scoped connections" }).getAttribute("href"))!, "http://local");
    expect(connection.searchParams.get("subscription")).toBe("sub-a");
    summaryAvailable = true;
    await page.getByRole("button", { name: "Retry cost summary", exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("region", { name: "Cost overview", exact: true })).toBeVisible();
    expect(counts["/governance/finops/summary"]).toBe(before["/governance/finops/summary"] + 1);
    for (const source of ["opportunities", "waste", "attribution", "verified-remediations"]) {
      expect(counts[`/governance/finops/${source}`]).toBe(before[`/governance/finops/${source}`]);
    }
    const records = page.getByRole("region", { name: "Savings opportunities", exact: true });
    const filter = records.getByRole("combobox", { name: "Filter by Impact" });
    await filter.selectOption("Medium");
    const evidence = page.getByRole("button", { name: "Retry verified remediation evidence", exact: true });
    verifiedAvailable = true;
    await evidence.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "No verified remediation changes in this scope" })).toBeVisible();
    await expect(filter).toHaveValue("Medium");
    expect(counts["/governance/finops/verified-remediations"]).toBe(before["/governance/finops/verified-remediations"] + 1);
    expect(counts["/governance/finops/summary"]).toBe(before["/governance/finops/summary"] + 1);
    expect(counts["/governance/finops/opportunities"]).toBe(before["/governance/finops/opportunities"]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
  });
}
