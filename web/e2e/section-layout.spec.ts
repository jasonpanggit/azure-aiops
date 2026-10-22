import { expect, test, type Page } from "@playwright/test";
import { expectContentSized } from "./layout-density";

const envelope = (data: unknown) => ({
  data,
  evidence: [],
  warnings: [],
  scope: {},
  knowledge_version: "section-layout-test",
});

async function mockSections(page: Page) {
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const data: Record<string, unknown> = {
      "/situations": [],
      "/connections": [],
      "/network/summary": { gap_count: 0, rule_finding_count: 0 },
      "/vulnerabilities/summary": { internet_exposed_count: 0, reachable_server_count: 0 },
      "/vulnerabilities/exposures": [],
      "/network/topology": { topology: { links: [], resources: [], hubs: [], spokes: [], isolated: [], shared_services: [], relationships: [], counts: {} }, summary: {} },
      "/network/rule-findings": { findings: [], summary: {} },
      "/network/gaps": {
        gaps: Array.from({ length: 45 }, (_, index) => ({
          gap_id: `routing-${index}`,
          title: `Routing finding ${index}`,
          category: "routing",
          severity: "high",
          detail: `Review routing evidence ${index}`,
          resource_id: `/subscriptions/test/resourceGroups/network/providers/Microsoft.Network/routeTables/route-${index}`,
          resource_name: `route-${index}`,
          recommendation: "Review the route",
          basis: "Observed routing",
        })),
        summary: {},
      },
      "/compliance/policy-deviations": Array.from({ length: 23 }, (_, index) => ({
        deviation_id: `deviation-${index}`,
        kind: "policy",
        severity: "high",
        control: `Control ${index}`,
        status: "open",
      })),
      "/compliance/security-deviations": [],
      "/compliance/configuration-drift": Array.from({ length: 23 }, (_, index) => ({
        resource: { name: `Drift resource ${index}`, entity_type: "Virtual machine" },
      })),
      "/compliance/summary": {},
      "/compliance/design-policy": {
        revision: 4, policy_revision: 4, scope: {}, exceptions: [], audit: [],
        policy: {
          name: "Approved hub-spoke landing-zone baseline",
          requiredHubRouting: true, firewallInspectionRequired: true, environmentIsolationRequired: true,
          allowedPorts: "443, 1433, 5671", privateEndpointRequiredFor: "microsoft.sql, microsoft.storage, microsoft.keyvault, microsoft.web",
          requiredDnsZones: "privatelink.database.windows.net, privatelink.blob.core.windows.net, privatelink.vaultcore.azure.net",
          loggingRequired: true, ownerTag: "owner", allowCrossSubscriptionPeering: false,
        },
      },
      "/remediation-plans": { plans: [] },
      "/remediation/exposure-handoffs": { cases: [], read_only: true, execution_transition: false },
    };
    if (!(path in data)) {
      return route.fulfill({ status: 503, json: { detail: `No test source for ${path}` } });
    }
    return route.fulfill({ json: envelope(data[path]) });
  });
}

test.beforeEach(async ({ page }) => {
  await mockSections(page);
});

for (const width of [1440, 820, 768, 375, 320]) {
  test(`keeps real Compliance sections navigable and bounded at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/compliance");
    const violations = page.locator("#compliance-findings");
    await expect(violations.getByText("Showing 1–20 of 45 violations")).toBeVisible();
    await expect(page.locator(".copilot-insights")).toHaveCount(1);
    await expect(violations.locator(".compliance-row")).toHaveCount(20);
    await expectContentSized(page.locator(".compliance-workspace section.card"));

    const navigation = page.getByRole("navigation", { name: "Compliance sections" });
    const links = navigation.getByRole("link");
    await expect(links).toHaveCount(5);
    for (const element of [
      ...await links.all(),
      ...await page.locator(".compliance-workspace .card-header h2, .compliance-workspace .card-header p").all(),
    ]) {
      const box = await element.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
    }
    await expect(violations.getByRole("heading")).toHaveCSS("font-size", "18px");
    await expect(violations.locator(".card-header p")).toHaveCSS("font-size", "14px");

    await violations.getByRole("button", { name: "Next page" }).click();
    await expect(violations.getByText("Showing 21–40 of 45 violations")).toBeVisible();
    await expect(violations.getByRole("button", { name: /Routing finding 20 / })).toHaveAttribute("aria-expanded", "true");
    await navigation.getByRole("link", { name: "Policy administration", exact: true }).click();
    const policyTitle = page.getByRole("heading", { name: "Policy administration" });
    await expect(policyTitle).toBeInViewport();
    expect((await policyTitle.boundingBox())!.y).toBeGreaterThanOrEqual(56);
    await expect(page.getByLabel("Policy pack name")).toBeVisible();
    const overflow = await page.locator(".compliance-workspace").evaluate((workspace) =>
      Array.from(workspace.querySelectorAll("*")).flatMap((element) => {
        const scroller = element.closest(".table-scroll, .data-table-wrap");
        if (scroller && scroller !== element) return [];
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1)
          ? [{ element: element.tagName, className: element.className, left: rect.left, right: rect.right }]
          : [];
      }));
    expect(overflow).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
    if (width === 375) {
      await page.screenshot({
        path: testInfo.outputPath("compliance-sections-375.png"),
        fullPage: true,
      });
    }
  });
}

test("places the real Home queue before supporting metrics and Copilot insights", async ({ page }) => {
  await page.goto("/");
  const queue = page.getByRole("region", { name: "Priority situations" });
  await expect(queue.getByText("No active situations in this scope")).toBeVisible();
  await expect(page.locator(".copilot-insights")).toHaveCount(1);
  for (const supporting of [
    page.getByText("Critical situations", { exact: true }),
    page.getByRole("heading", { name: "Signal concentration" }),
    page.getByText("Operations Copilot insights"),
  ]) {
    expect(await supporting.evaluate(element =>
      Boolean(document.querySelector('[aria-labelledby="priority-situations"]')!.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING),
    )).toBe(true);
  }
});

for (const width of [1440, 375]) {
  test(`renders a single real Remediation empty state without an unused detail column at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/remediation");
    await expect(page.getByText("No fixes generated", { exact: true })).toBeVisible();
    await expect(page.locator(".remediation-workflow-main")).toHaveCount(0);
    const layout = await page.locator(".remediation-workflow-empty").boundingBox();
    const selection = await page.locator(".remediation-workflow-selection").boundingBox();
    expect(selection!.width).toBeCloseTo(layout!.width, 0);
    await expect(page.getByRole("navigation", { name: "Remediation workflow" })).toBeVisible();
    await expect(page.locator(".copilot-insights")).toHaveCount(1);
    expect(await page.locator(".remediation-workflow-empty").evaluate((element) =>
      Boolean(element.compareDocumentPosition(document.querySelector(".copilot-insights")!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
  });
}

test("legacy vulnerabilities destination opens Exposure rather than a duplicate workspace", async ({ page }) => {
  await page.goto("/vulnerabilities");
  await expect(page).toHaveURL(/\/exposure\/patch-priorities$/);
  await expect(page.getByRole("heading", { name: "Patch priorities", exact: true })).toBeVisible();
});
