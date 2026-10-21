import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import {
  buildAccessSignals, buildCostSignals, buildEnterpriseSettings, buildEvidencePack,
  buildHealthResources, buildHealthSnapshot,
} from "../src/test/accountability-fixtures";

const warning = "Coverage is limited to the authorized subscription; review source gaps.";
const envelope = (data: unknown) => ({
  data, scope: { subscription: ["sub-accountability"] }, knowledge_version: "accountability-layout",
  warnings: [warning],
  evidence: [{ source_engine: "ARG", source_table: "observed", timestamp: "2026-09-20T12:00:00Z", confidence: "low", freshness: "stale" }],
});

async function mockSources(page: Page, unavailable: string[] = [], emptyInventory = false) {
  const cost = buildCostSignals();
  const access = buildAccessSignals();
  const resources = emptyInventory ? [] : buildHealthResources();
  let settings = buildEnterpriseSettings();
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", "");
    if (unavailable.includes(path)) return route.fulfill({
      status: 503, json: { error: { code: "upstream_unavailable", message: `Source unavailable: ${path}` } },
    });
    if (path === "/resource-health/resource") {
      const resource = resources.find((item) => item.resource_id === url.searchParams.get("resource_id"));
      if (!resource || resource.resource_name === "payments-worker-1") {
        return route.fulfill({
          status: 503, json: { error: { code: "upstream_unavailable", message: "Metrics are unavailable for this resource." } },
        });
      }
      return route.fulfill({ json: envelope(buildHealthSnapshot(resource)) });
    }
    if (path === "/governance/settings" && request.method() === "PATCH") {
      const change = request.postDataJSON();
      if (change.expected_revision !== settings.revision) return route.fulfill({
        status: 409, json: { error: { code: "revision_conflict", message: "Reload the current settings revision." } },
      });
      settings = {
        ...settings,
        onboarding_policy: { ...settings.onboarding_policy, ...change.changes.onboarding_policy },
        revision: settings.revision! + 1,
      };
    }
    const data: Record<string, unknown> = {
      "/subscription-connections": [],
      "/governance/finops/summary": cost.summary,
      "/governance/finops/opportunities": { opportunities: cost.opportunities, count: 23 },
      "/governance/finops/waste": { waste: cost.waste, count: 23 },
      "/governance/finops/attribution": { groups: cost.groups, count: 23, dimension: url.searchParams.get("dimension") },
      "/governance/identity/summary": access.summary,
      "/governance/identity/principals": { principals: access.principals, count: 23 },
      "/governance/identity/subscription-owners": { owners: access.owners, count: 23 },
      "/governance/identity/stale-access": { assignments: access.assignments, count: 23 },
      "/governance/identity/non-human": { identities: access.identities, count: 23 },
      "/governance/spn/credentials": { credentials: access.credentials, summary: access.spnSummary, count: 23 },
      "/governance/access-reviews": { audiences: ["executive", "service_owner"] },
      "/governance/access-reviews/executive": buildEvidencePack(),
      "/governance/access-reviews/service_owner": buildEvidencePack("service_owner"),
      "/governance/exports": { kinds: ["identity", "network"] },
      "/governance/exports/identity": buildEvidencePack("identity"),
      "/governance/settings": settings,
      "/inventory/resources": { resources, family_availability: {}, requested_scope: {}, query_version: "inventory-resources-v1" },
      "/copilot/investigate-context": {
        synthesis: { narration: "Review source gaps with the accountable owner." },
        findings: [], synthesis_mode: "foundry", warnings: [warning],
      },
      "/copilot/investigations": {
        contract_version: "1", policy_status: "accepted", tool_results: [], uncertainty: [],
        synthesis: {
          status: "synthesized", warning: "",
          claims: [{ summary: "Review source gaps with the accountable owner.", evidence_refs: [], confidence: "low", uncertainty: [] }],
        },
      },
    };
    if (!(path in data)) return route.fulfill({ status: 503, json: { detail: `Unmocked source: ${path}` } });
    return route.fulfill({ json: { ...envelope(data[path]), ...(path === "/inventory/resources" ? {
      pagination: { offset: 0, limit: 500, total: resources.length, next_offset: null },
    } : {}) } });
  });
}

async function assertLayout(page: Page, width: number) {
  for (const scroller of await page.locator(".operational-page .table-scroll").filter({ has: page.locator("table.operations-table") }).all()) {
    for (const cell of await scroller.locator("thead th, tbody tr:first-child td").all()) {
      expect((await cell.boundingBox())!.width).toBeGreaterThanOrEqual(100);
    }
    if (await scroller.evaluate((element) => element.scrollWidth > element.clientWidth)) {
      await scroller.focus();
      await scroller.press("ArrowRight");
      await expect.poll(() => scroller.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);
      await scroller.press("ArrowLeft");
      await expect.poll(() => scroller.evaluate((element) => element.scrollLeft)).toBe(0);
    }
  }
  await expect(async () => {
    const overflow = await page.locator(".operational-page").evaluate((workspace) => {
      const results = Array.from(workspace.querySelectorAll("*")).flatMap((element) => {
        const rect = element.getBoundingClientRect();
        const scroller = element.closest(".table-scroll, .report-preview");
        if (scroller && scroller !== element) return [];
        return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1)
          ? [{ tag: element.tagName, className: String(element.className), left: rect.left, right: rect.right }]
          : [];
      });
      for (let element: Element | null = workspace; element; element = element.parentElement) {
        if (element.scrollWidth > element.clientWidth + 1 || element.scrollLeft !== 0) {
          results.push({ tag: element.tagName, className: String(element.className), left: element.scrollLeft, right: element.scrollWidth });
        }
      }
      return results;
    });
    expect(overflow).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
  }).toPass({ timeout: 5000 });
  await expect(page.locator(".copilot-insights")).toHaveCount(1);
}

async function assertInsightLast(page: Page, taskSelector: string) {
  expect(await page.locator(taskSelector).evaluate((element) =>
    Boolean(element.compareDocumentPosition(document.querySelector(".copilot-insights")!) & Node.DOCUMENT_POSITION_FOLLOWING),
  )).toBe(true);
}

async function assertNavigation(page: Page, name: string) {
  const links = page.getByRole("navigation", { name, exact: true }).getByRole("link");
  for (const link of await links.all()) {
    await expect(page.locator((await link.getAttribute("href"))!)).toHaveCount(1);
  }
  const last = links.last();
  await last.focus();
  await last.press("Enter");
  const target = page.locator((await last.getAttribute("href"))!);
  await expect(target).toBeInViewport();
  expect((await target.boundingBox())!.y).toBeGreaterThanOrEqual(55);
}

for (const width of [1440, 820, 768, 375, 320]) {
  test(`FinOps keeps currency, coverage and cost controls readable at ${width}px`, async ({ page }, testInfo) => {
    await mockSources(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/finops");
    const opportunities = page.getByRole("region", { name: "Savings opportunities", exact: true });
    await expect(opportunities.locator("tbody tr")).toHaveCount(20);
    await expect(opportunities.getByText("Not quantified", { exact: true })).toBeVisible();
    await expect(page.getByText("A forecast has not been returned for this scope.", { exact: true })).toBeVisible();
    await expect(page.getByText(/2026-09-01 to 2026-09-20 from Cost Management/)).toBeVisible();
    await expect(page.getByText("125,000 AUD", { exact: true }).first()).toBeVisible();
    await expect(page.getByText(warning, { exact: true }).first()).toBeVisible();
    await opportunities.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(opportunities.locator("tbody tr")).toHaveCount(3);
    const modes = page.getByRole("group", { name: "Attribution dimension", exact: true });
    const request = page.waitForRequest((item) => item.url().includes("/finops/attribution") && new URL(item.url()).searchParams.get("dimension") === "owner");
    await modes.getByRole("button", { name: "Owner", exact: true }).click();
    await request;
    await expect(modes.getByRole("button", { name: "Owner", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(modes.getByRole("button", { name: "Owner", exact: true })).toHaveCSS("min-height", width <= 820 ? "44px" : "40px");
    const attribution = page.getByRole("region", { name: "Attribution", exact: true });
    await attribution.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(attribution.locator("tbody tr")).toHaveCount(3);
    const waste = page.getByRole("region", { name: "Waste", exact: true });
    await waste.getByRole("combobox", { name: "Filter by Reason", exact: true }).selectOption("deallocated_resource");
    await expect(waste.locator("tbody tr")).toHaveCount(11);
    await waste.getByRole("button", { name: "Clear filters", exact: true }).click();
    await expect(waste.locator("tbody tr")).toHaveCount(20);
    await assertNavigation(page, "Cost sections");
    await assertInsightLast(page, "#cost-waste");
    await assertLayout(page, width);
    if (width === 375) await page.locator("#cost-attribution").screenshot({ path: testInfo.outputPath("finops-attribution-375.png") });
  });

  test(`Identity keeps access and credential qualifications navigable at ${width}px`, async ({ page }, testInfo) => {
    await mockSources(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/identity");
    const principals = page.getByRole("region", { name: "Principals and observed grant breadth", exact: true });
    await expect(principals.locator("tbody tr")).toHaveCount(20);
    await expect(principals.getByRole("link", { name: "principal-0", exact: true })).toHaveAttribute("href", "/search?q=principal-0");
    await principals.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(principals.locator("tbody tr")).toHaveCount(3);
    const credentials = page.getByRole("region", { name: "Service principal governance", exact: true });
    await expect(credentials.getByText("Not resolvable", { exact: true })).toHaveCount(20);
    await expect(credentials.getByText("Not recorded", { exact: true })).toHaveCount(20);
    await expect(credentials.getByText("Expiry is not recorded; rotation cannot be verified.", { exact: true })).toHaveCount(20);
    await credentials.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(credentials.locator("tbody tr")).toHaveCount(3);
    await assertNavigation(page, "Identity sections");
    await assertInsightLast(page, "#identity-credentials");
    await assertLayout(page, width);
    if (width === 375) await credentials.screenshot({ path: testInfo.outputPath("identity-credentials-375.png") });
  });

  test(`Resource Health keeps cards, partial coverage and chart readable at ${width}px`, async ({ page }, testInfo) => {
    await mockSources(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/resource-health");
    const resources = page.getByRole("region", { name: "Resource utilization", exact: true });
    const cards = resources.locator(".health-resource-grid").getByRole("article");
    await expect(cards).toHaveCount(3);
    await expect(resources.getByText("2 of 3 resources returned metrics", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Some metrics are unavailable", exact: true })).toBeVisible();
    const failed = resources.getByRole("article", { name: "payments-worker-1", exact: true });
    await expect(failed.getByRole("alert")).toContainText("Metrics are unavailable");
    expect((await failed.getByRole("alert").boundingBox())!.height).toBeLessThanOrEqual(160);
    expect((await page.locator(".health-source-warnings").boundingBox())!.height).toBeLessThanOrEqual(180);
    const retry = page.waitForRequest((item) => item.url().includes("/resource-health/resource") && new URL(item.url()).searchParams.get("force_refresh") === "true");
    await failed.getByRole("button", { name: "Retry health for payments-worker-1", exact: true }).click();
    expect(new URL((await retry).url()).searchParams.get("resource_id")).toBe(buildHealthResources()[1].resource_id);
    await expect(failed.getByRole("alert")).toBeVisible();
    for (const card of await cards.all()) {
      expect((await card.boundingBox())!.width).toBeGreaterThanOrEqual(245);
    }
    const scroller = page.getByRole("region", { name: "Scrollable CPU chart", exact: true });
    await expect(scroller).toBeVisible();
    const chartOverflows = await scroller.evaluate((element) => element.scrollWidth > element.clientWidth);
    if (width <= 375) expect(chartOverflows).toBe(true);
    if (chartOverflows) {
      await scroller.focus();
      const settled = scroller.evaluate(element => new Promise<number>(resolve => {
        element.addEventListener("scrollend", () => resolve(element.scrollLeft), { once: true });
      }));
      await scroller.press("ArrowRight");
      expect(await settled).toBeGreaterThan(0);
    }
    await assertNavigation(page, "Health sections");
    await assertInsightLast(page, "#health-comparison");
    await assertLayout(page, width);
    if (width === 375) await resources.screenshot({ path: testInfo.outputPath("health-resources-375.png") });
  });

  test(`Governance keeps generation, raw evidence and explicit policy saves usable at ${width}px`, async ({ page }, testInfo) => {
    await mockSources(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/governance");
    const views = page.getByRole("group", { name: "Governance section", exact: true });
    const review = page.getByRole("region", { name: "Access reviews", exact: true });
    const generate = review.getByRole("button", { name: "Generate", exact: true }).first();
    await expect(generate).toHaveClass(/button-primary/);
    await expect(generate).toHaveCSS("background-image", "none");
    await generate.click();
    const pack = page.getByRole("region", { name: "Executive pack", exact: true });
    await expect(pack.getByRole("heading", { name: "This pack is partial", exact: true })).toBeVisible();
    await expect(pack.getByText("This pack excludes assignments outside the authorized subscription.", { exact: true })).toBeVisible();
    const disclosure = pack.getByText("Inspect generated JSON", { exact: true });
    await expect(disclosure.locator("..")).not.toHaveAttribute("open");
    await disclosure.focus();
    await disclosure.press("Enter");
    const preview = pack.getByLabel("Generated pack JSON", { exact: true });
    await expect(preview).toBeVisible();
    expect((await preview.boundingBox())!.height).toBeLessThanOrEqual(480);
    await preview.focus();
    await preview.press("PageDown");
    await expect.poll(() => preview.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    const downloading = page.waitForEvent("download");
    await pack.getByRole("button", { name: "Download JSON", exact: true }).click();
    const downloaded = await downloading;
    expect(JSON.parse(await readFile((await downloaded.path())!, "utf8"))).toEqual(buildEvidencePack());
    await views.getByRole("button", { name: "Audit evidence", exact: true }).click();
    await expect(views.getByRole("button", { name: "Audit evidence", exact: true })).toHaveAttribute("aria-pressed", "true");
    const audit = page.getByRole("region", { name: "Audit evidence", exact: true });
    await audit.getByRole("button", { name: "Generate", exact: true }).first().click();
    await expect(page.getByRole("region", { name: "Identity pack", exact: true })).toBeVisible();
    await views.getByRole("button", { name: "Administration", exact: true }).click();
    const administration = page.getByRole("region", { name: "Administration", exact: true });
    await administration.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(administration.locator("tbody tr")).toHaveCount(3);
    const days = administration.getByRole("spinbutton", { name: "Review Days", exact: true });
    await expect(days).toHaveCSS("min-height", width <= 820 ? "44px" : "40px");
    await expect(days).toHaveCSS("border-top-width", "1px");
    await expect(days).toHaveCSS("border-top-style", "solid");
    await days.fill("45");
    await administration.getByRole("textbox", { name: "Change reason", exact: true }).fill("Review interval approved for the next governed cycle.");
    await administration.getByRole("button", { name: "Review 1 change", exact: true }).click();
    await expect(administration.getByRole("heading", { name: "Review enterprise-wide change", exact: true })).toBeVisible();
    const saving = page.waitForRequest((item) => item.method() === "PATCH" && item.url().includes("/governance/settings"));
    await administration.getByRole("button", { name: "Confirm enterprise-wide change", exact: true }).click();
    expect((await saving).postDataJSON()).toEqual({
      expected_revision: 4,
      reason: "Review interval approved for the next governed cycle.",
      changes: { onboarding_policy: { review_days: 45 } },
    });
    await expect(administration.getByText("Enterprise-wide settings saved at revision 5.", { exact: true })).toBeVisible();
    await expect(days).toHaveValue("45");
    await assertInsightLast(page, "#generated-pack-heading");
    await assertLayout(page, width);
    if (width === 375) await administration.locator(".policy-editor").screenshot({ path: testInfo.outputPath("governance-policy-375.png") });
  });
}

test("FinOps keeps unavailable attribution distinct from an empty successful grouping", async ({ page }) => {
  await mockSources(page, ["/governance/finops/attribution"]);
  await page.goto("/finops");
  await expect(page.getByRole("heading", { name: "Attribution is unavailable", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No attributed savings", exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Savings opportunities", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry attribution", exact: true })).toBeVisible();
});

test("FinOps keeps primary source failure explicit without rendering zero-valued summaries", async ({ page }) => {
  await mockSources(page, ["/governance/finops/summary"]);
  await page.goto("/finops");
  await expect(page.getByRole("heading", { name: "Cost intelligence is unavailable", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Cost overview", exact: true })).toHaveCount(0);
});

test("Identity keeps independent unavailable sources separate from empty access claims", async ({ page }) => {
  await mockSources(page, [
    "/governance/identity/subscription-owners", "/governance/identity/stale-access", "/governance/identity/non-human",
  ]);
  await page.goto("/identity");
  await expect(page.getByRole("heading", { name: "Identity intelligence is unavailable", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry failed identity reads", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No stale access", exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Principals and observed grant breadth", exact: true })).toHaveCount(0);
});

test("Resource Health keeps unavailable inventory distinct from an empty authorized scope", async ({ page }) => {
  await mockSources(page, ["/inventory/resources"]);
  await page.goto("/resource-health");
  await expect(page.getByRole("heading", { name: "Resource inventory is unavailable", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No compute resources found in scope", exact: true })).toHaveCount(0);
  await assertNavigation(page, "Health sections");
});

test("Resource Health retains a named empty task and neutral refresh", async ({ page }) => {
  await mockSources(page, [], true);
  await page.goto("/resource-health");
  await expect(page.getByRole("heading", { name: "No supported resources found in scope", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh now", exact: true })).toBeDisabled();
  await expect(page.getByRole("region", { name: "CPU comparison", exact: true })).toHaveCount(0);
  await expect(page.locator(".copilot-insights")).toHaveCount(1);
});

test("Governance keeps independent catalog and settings errors visible in their selected workspaces", async ({ page }) => {
  await mockSources(page, ["/governance/access-reviews", "/governance/exports", "/governance/settings"]);
  await page.goto("/governance");
  await expect(page.getByRole("heading", { name: "Review audiences are unavailable", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Audit evidence", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Export kinds are unavailable", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Administration", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Settings are unavailable", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save policy settings", exact: true })).toHaveCount(0);
});
