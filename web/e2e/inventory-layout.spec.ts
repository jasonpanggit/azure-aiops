import { readFile } from "node:fs/promises";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { buildInventoryFixtures } from "../src/test/inventory-fixtures";

const warning = "Inventory coverage is partial; missing resources are not established as absent.";
const envelope = (data: unknown) => ({
  data, scope: { subscription: ["sub-ui"] }, evidence: [], knowledge_version: "inventory-layout", warnings: [warning],
});

async function mockSources(page: Page, unavailable: string[] = [], empty = false) {
  const fixtures = buildInventoryFixtures();
  const exportColumns = ["family", "resource_name", "resource_type", "resource_id", "subscription_id", "resource_group", "environment", "location", "observed_at"];
  const exportRows = fixtures.resources.resources.map(resource => ({
    ...resource, location: "australiaeast", observed_at: "2026-09-20T12:00:00Z",
  }));
  const exportManifest = {
    export_id: "22222222-2222-4222-8222-222222222222", generation_id: "ui-generation",
    revision: 1, sha256: "a".repeat(64), batch_size: 500, total: exportRows.length,
    status: "ready", scope: {}, columns: exportColumns,
    observed_at: "2026-09-20T12:00:00Z", expires_at: "2099-01-01T00:00:00Z",
  };
  if (empty) {
    fixtures.os.groups = [];
    fixtures.software.groups = [];
    fixtures.azure.groups = [];
    fixtures.mappings.mappings = [];
    fixtures.narrative.fact_summary = "No inventory observations were returned for this scope.";
    fixtures.narrative.fact_items = [];
    for (const status of Object.values(fixtures.os.source_status)) Object.assign(status, { state: "ready", row_count: 0, error: "" });
  }
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = decodeURIComponent(url.pathname.replace("/api/v1", ""));
    if (path === "/inventory/exports/current") return route.fulfill({ json: envelope({ export: null }) });
    if (path === "/inventory/exports" && request.method() === "POST") {
      expect(request.postDataJSON()).toEqual({ expected_generation_id: "ui-generation" });
      return route.fulfill({ json: envelope({ export: exportManifest }) });
    }
    if (path === `/inventory/exports/${exportManifest.export_id}/batches`) {
      expect(url.searchParams.get("offset")).toBe("0");
      return route.fulfill({ json: envelope({
        manifest: exportManifest, offset: 0, next_offset: null, resources: exportRows,
      }) });
    }
    const failure = (message: string) => route.fulfill({
      status: 503, json: { error: { code: "upstream_unavailable", message } },
    });
    if (unavailable.includes(path)) return failure(`Source unavailable: ${path}`);
    const paginate = (data: object, key: string, rows: unknown[], maximum = 500) => {
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Math.min(Number(url.searchParams.get("limit") ?? 20), maximum);
      return route.fulfill({ json: {
        ...envelope({ ...data, [key]: rows.slice(offset, offset + limit) }),
        ...(empty ? { warnings: [] } : {}),
        pagination: { offset, limit, total: rows.length, next_offset: offset + limit < rows.length ? offset + limit : null },
      } });
    };
    if (path.endsWith("/lifecycle/confirm")) {
      const body: { manual_date?: string; candidate_id?: string } = request.postDataJSON();
      fixtures.review = { ...fixtures.review, status: "confirmed", catalog_revision: 4,
        classification: { ...fixtures.review.classification, status: "Supported", support_end: body.manual_date ?? "2030-01-01" } };
      return route.fulfill({ json: envelope(fixtures.review) });
    }
    if (path.endsWith("/lifecycle")) return route.fulfill({ json: envelope(fixtures.review) });
    if (path === "/inventory/software/mappings/approve" || path === "/inventory/software/mappings/reject") {
      fixtures.mappings.mappings[0] = { ...fixtures.mappings.mappings[0], revision: 4,
        status: path.endsWith("/approve") ? "approved" : "rejected" };
      return route.fulfill({ json: envelope(fixtures.mappings.mappings[0]) });
    }
    const collections = {
      "/inventory/os": fixtures.os,
      "/inventory/software": fixtures.software,
      "/inventory/paas": fixtures.azure,
    };
    if (path in collections) {
      const data = collections[path as keyof typeof collections];
      const search = (url.searchParams.get("q") ?? "").toLowerCase();
      const filtered = data.groups.filter(group => JSON.stringify(group).toLowerCase().includes(search));
      return paginate(data, "groups", filtered);
    }
    if (path === "/inventory/resources") return paginate(fixtures.resources, "resources", fixtures.resources.resources, 30);
    if (path === "/inventory/software/mappings") return route.fulfill({ json: envelope(fixtures.mappings) });
    const match = path.match(/^\/inventory\/(os|software|paas)\/[^/]+$/);
    if (match) {
      const data = match[1] === "os" ? fixtures.osDetail : match[1] === "software" ? fixtures.softwareDetail : fixtures.azureDetail;
      return "machines" in data ? paginate(data, "machines", data.machines) : paginate(data, "resources", data.resources);
    }
    const data: Record<string, unknown> = {
      "/subscription-connections": [],
      "/inventory/narrative": fixtures.narrative,
      "/copilot/investigate-context": { synthesis: { narration: "Review source gaps with the accountable owner." }, findings: [], warnings: [warning] },
      "/copilot/investigations": {
        contract_version: "1", policy_status: "fallback", fallback_reason: "planner_unavailable",
        tool_results: [], uncertainty: [warning], coverage: { visible_count: 20, total_count: 23, complete: false },
        thread_id: `thr-${"c".repeat(32)}`, thread_revision: 1, mutation_authorized: false,
        synthesis: { status: "degraded", warning, claims: [] },
      },
    };
    return path in data ? route.fulfill({ json: envelope(data[path]) }) : failure(`Unmocked source: ${path}`);
  });
}

async function assertBounds(page: Page, width: number) {
  await expect(async () => {
    const overflow = await page.locator(".inventory-page").evaluate((workspace) => {
      const problems = Array.from(workspace.querySelectorAll("*")).flatMap((element) => {
        const scroller = element.closest(".table-scroll, .tab-list");
        if (scroller && scroller !== element) return [];
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1)
          ? [`${element.tagName}.${String(element.className)}: ${rect.left},${rect.right}`] : [];
      });
      for (let element: Element | null = workspace; element; element = element.parentElement) {
        if (element.scrollWidth > element.clientWidth + 1 || element.scrollLeft !== 0) {
          problems.push(`${element.tagName}: ${element.scrollWidth}/${element.clientWidth}, scroll ${element.scrollLeft}`);
        }
      }
      return problems;
    });
    expect(overflow).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
  }).toPass({ timeout: 5000 });
}

async function checkTable(table: Locator) {
  for (const cell of await table.locator(":scope > table > thead th").all()) {
    expect((await cell.boundingBox())!.width).toBeGreaterThanOrEqual(130);
  }
  if (await table.evaluate((element) => element.scrollWidth > element.clientWidth)) {
    await table.focus();
    await table.evaluate((element) => new Promise<void>((resolve) => {
      if (element.scrollLeft === 0) return resolve();
      element.addEventListener("scrollend", () => resolve(), { once: true });
      element.scrollLeft = 0;
    }));
    const forward = table.evaluate((element) => new Promise<number>((resolve) => {
      element.addEventListener("scrollend", () => resolve(element.scrollLeft), { once: true });
    }));
    await table.press("ArrowRight");
    expect(await forward).toBeGreaterThan(0);
    const backward = table.evaluate((element) => new Promise<number>((resolve) => {
      element.addEventListener("scrollend", () => resolve(element.scrollLeft), { once: true });
    }));
    await table.press("ArrowLeft");
    expect(await backward).toBe(0);
  }
}

const views = [
  { key: "os", tab: "OS Inventory", groups: "OS inventory groups", table: "OS group table", search: "Search OS", filter: "production-release-0",
    detail: "OS machine details", detailTable: "OS machine table", noun: "machines" },
  { key: "software", tab: "Installed Software", groups: "Installed software groups", table: "Installed software group table",
    search: "Search software", filter: "runtime 0", detail: "Installed software machine details", detailTable: "Installed software machine table", noun: "installations" },
  { key: "azure", tab: "Azure Inventory", groups: "Azure inventory groups", table: "Azure group table", search: "Search resources", filter: "production-sku-0",
    detail: "Azure resource detail", detailTable: "Azure resource detail table", noun: "resources" },
] as const;

for (const width of [2560, 1912, 1440, 820, 768, 375, 320]) {
  for (const view of views) {
    test(`Inventory ${view.key} keeps scoped records, inline detail and controls readable at ${width}px`, async ({ page }, testInfo) => {
      await mockSources(page);
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/inventory");
      await page.getByRole("tab", { name: view.tab, exact: true }).click();
      const groups = page.getByRole("region", { name: view.groups, exact: true });
      const table = page.getByRole("region", { name: view.table, exact: true });
      const rows = table.locator(":scope > table > tbody > tr:not(.detail-row)");
      await expect(rows).toHaveCount(20);
      await expect(page.locator(".copilot-insights")).toHaveCount(1);
      await expect(page.getByText(warning, { exact: true }).first()).toBeVisible();
      await expect(page.getByText(/Filters search authorized groups before pagination/)).toBeVisible();
      await expect(page.getByRole("tab", { name: view.tab, exact: true })).toHaveCSS("min-height", width <= 820 ? "44px" : "40px");
      const search = page.getByRole("textbox", { name: view.search, exact: true });
      await expect(search).toHaveCSS("min-height", width <= 820 ? "44px" : "40px");
      const pager = groups.locator(":scope > .table-footer");
      expect(await pager.evaluate((element) => element.closest(".table-scroll") === null)).toBe(true);
      await pager.getByRole("button", { name: "Next page", exact: true }).click();
      await expect(rows).toHaveCount(3);
      await pager.getByRole("button", { name: "Previous page", exact: true }).click();
      await expect(rows).toHaveCount(20);
      await search.fill(view.filter);
      await expect(rows).toHaveCount(1);
      await search.fill("");
      await expect(rows).toHaveCount(20);
      await checkTable(table);
      await rows.first().getByRole("button", { name: /View machines|View resources/ }).click();
      const detail = page.getByRole("region", { name: view.detail, exact: true });
      await expect(detail).toBeVisible();
      const detailCount = (count: number) => `${count} of 27 ${view.noun}${view.key === "software" ? " · exact server lookup" : ""}`;
      await expect(detail.getByText(detailCount(25), { exact: true })).toBeVisible();
      await detail.getByRole("button", { name: "Next page", exact: true }).click();
      await expect(detail.getByText(detailCount(2), { exact: true })).toBeVisible();
      await detail.getByRole("button", { name: "Previous page", exact: true }).click();
      await expect(detail.getByText(detailCount(25), { exact: true })).toBeVisible();
      await table.evaluate((element) => { element.scrollLeft = 0; });
      await checkTable(page.getByRole("region", { name: view.detailTable, exact: true }));
      if (width === 375) await detail.screenshot({ path: testInfo.outputPath(`ui-inventory-${view.key}-detail-375.png`) });
      await detail.getByRole("button", { name: "Close", exact: true }).click();
      await expect(page.locator(".inline-detail")).toHaveCount(0);
      const task = page.locator("#inventory-records");
      const dashboard = page.getByRole("region", { name: view.key === "software" ? "Installed software dashboard" : view.key === "azure" ? "Azure inventory dashboard" : "OS inventory dashboard", exact: true });
      expect(await task.evaluate((element) => Boolean(element.compareDocumentPosition(document.querySelector(".dashboard-charts-row")!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
      expect(await dashboard.evaluate((element) =>
        Boolean(element.compareDocumentPosition(document.querySelector(".copilot-insights")!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
      for (const link of await page.getByRole("navigation", { name: "Inventory sections" }).getByRole("link").all()) {
        await expect(page.locator((await link.getAttribute("href"))!)).toHaveCount(1);
      }
      await assertBounds(page, width);
      if (width === 375 || width >= 1912) {
        await page.screenshot({ path: testInfo.outputPath(`ui-inventory-${view.key}-${width}.png`), fullPage: true });
      }
    });
  }
}

test("Inventory tab arrows wrap and retain one active, reachable panel", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await mockSources(page);
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("/inventory");
  const tabs = page.getByRole("tablist", { name: "Inventory views" });
  await tabs.getByRole("tab", { name: "OS Inventory", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "Installed Software", exact: true })).toBeFocused();
  await expect(page.getByRole("tabpanel", { name: "Installed Software", exact: true })).toBeVisible();
  await page.keyboard.press("End");
  const selected = page.getByRole("tab", { name: "Azure Inventory" });
  await expect(selected).toBeFocused();
  await expect.poll(async () => {
    const box = await selected.boundingBox();
    return box !== null && box.x >= 0 && box.x + box.width <= 375;
  }).toBe(true);
  await expect(page.getByRole("tabpanel", { name: "Azure Inventory", exact: true })).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "OS Inventory", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(tabs.getByRole("tab", { name: "Azure Inventory", exact: true })).toBeFocused();
  await page.keyboard.press("Home");
  await expect(tabs.getByRole("tab", { name: "OS Inventory", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(tabs.locator('[tabindex="0"]')).toHaveCount(1);
  await assertBounds(page, 375);
});

test("Unavailable OS does not become healthy zero or block healthy software", async ({ page }) => {
  await mockSources(page, ["/inventory/os"]);
  await page.goto("/inventory");
  await expect(page.getByText("OS inventory unavailable", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "OS inventory summary", exact: true }).getByText("—", { exact: true })).toHaveCount(4);
  await page.getByRole("tab", { name: "Installed Software", exact: true }).click();
  await expect(page.getByRole("region", { name: "Installed software group table", exact: true }).locator("tbody tr")).toHaveCount(20);
  await expect(page.getByText("Source unavailable: /inventory/os", { exact: true })).toHaveCount(0);
});

for (const source of ["mappings", "narrative"] as const) {
  test(`Inventory exposes and retries independent ${source} failure`, async ({ page }) => {
    const path = source === "mappings" ? "/inventory/software/mappings" : "/inventory/narrative";
    await mockSources(page, [path]);
    await page.goto("/inventory");
    if (source === "mappings") await page.getByRole("tab", { name: "Installed Software", exact: true }).click();
    await expect(page.getByText(`Source unavailable: ${path}`, { exact: true })).toBeVisible();
    await page.route(`**/api/v1${path}**`, (route) => route.fulfill({ json: envelope(buildInventoryFixtures()[source]) }));
    await page.getByRole("button", { name: source === "mappings" ? "Retry normalization mappings" : "Retry risk narrative", exact: true }).click();
    await expect(page.getByText(`Source unavailable: ${path}`, { exact: true })).toHaveCount(0);
    await expect(page.getByRole("region", { name: source === "mappings" ? "Software normalization review" : "Inventory risk narrative", exact: true })).toBeVisible();
  });
}

test("Healthy empty Inventory remains distinguishable from an unavailable provider", async ({ page }) => {
  await mockSources(page, [], true);
  await page.goto("/inventory");
  await expect(page.getByText("No OS observations", { exact: true })).toBeVisible();
  await expect(page.getByText("OS inventory unavailable", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "OS inventory summary", exact: true })).toBeVisible();
  await expect(page.locator(".inventory-dashboard")).toHaveCount(0);
});

test("Lifecycle confirmation and mapping approval keep explicit revisions and payloads", async ({ page }) => {
  await mockSources(page);
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("/inventory");
  await page.getByRole("button", { name: "Review EOL date", exact: true }).click();
  const review = page.getByRole("region", { name: "EOL lifecycle review", exact: true });
  await expect(review.getByText("No catalog winner was selected. Review every cited candidate before confirming.", { exact: true })).toBeVisible();
  await expect(review.getByRole("link", { name: "Citation", exact: true })).toHaveAttribute("href", "https://learn.microsoft.com/lifecycle/");
  await review.getByLabel("Or enter a date", { exact: true }).fill("2031-12-31");
  const confirmation = page.waitForRequest((item) => item.url().includes("/lifecycle/confirm"));
  await review.getByRole("button", { name: "Confirm manual date", exact: true }).click();
  expect((await confirmation).postDataJSON()).toEqual({
    normalized_os_key: "windows server|2022", expected_revision: 3, manual_date: "2031-12-31",
  });
  await expect(review.getByText("Confirmed 2031-12-31.", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Installed Software", exact: true }).click();
  const approval = page.waitForRequest((item) => item.url().includes("/mappings/approve"));
  const approve = page.getByRole("button", { name: "Approve mapping", exact: true });
  await expect(approve).toHaveCSS("background-image", "none");
  await approve.click();
  expect((await approval).postDataJSON()).toEqual({ mapping_id: "map-ui", expected_revision: 3, reason: "" });
});

test("CSV actions retain loaded-detail and complete cross-family export semantics", async ({ page }) => {
  await mockSources(page);
  const batches: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith("/batches")) batches.push(new URL(request.url()).searchParams.get("offset")!);
  });
  await page.goto("/inventory");
  await page.getByRole("tab", { name: "Installed Software", exact: true }).click();
  await page.getByRole("button", { name: /View machines for Payments enterprise runtime 0 / }).click();
  const detail = page.getByRole("region", { name: "Installed software machine details", exact: true });
  const download = page.waitForEvent("download");
  await detail.getByRole("button", { name: "Export CSV", exact: true }).click();
  const csv = await readFile((await (await download).path())!, "utf8");
  expect(csv.trim().split(/\r?\n/)).toHaveLength(26);
  expect(csv).toContain("raw_software_name");
  expect(csv).toContain("agent-0");
  await page.getByRole("tab", { name: "Azure Inventory", exact: true }).click();
  await page.getByRole("button", { name: "Capture resource export", exact: true }).click();
  const fullDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download selected batch (CSV)", exact: true }).click();
  const fullCsv = await readFile((await (await fullDownload).path())!, "utf8");
  expect(fullCsv.trim().split(/\r?\n/)).toHaveLength(55);
  expect(fullCsv).toContain("payments-api-26");
  expect(fullCsv).toContain("virtualMachines/payments-worker-0");
  expect(batches).toEqual(["0"]);
});
