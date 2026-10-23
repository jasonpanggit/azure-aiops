import { expect, test, type Locator, type Page } from "@playwright/test";

const subscriptionId = "00000000-0000-0000-0000-000000000001";
const situationId = "situation-layout-00000000-0000-0000-0000-000000000001";
const timestamp = "2026-09-06T08:00:00Z";
const datasetName = "bronze_operational_resources_for_subscription_health";
const envelope = (data: unknown) => ({
  data, evidence: [], warnings: [], scope: {}, knowledge_version: "operational-layout-test",
});
const connection = {
  connection_id: "production",
  name: "Production subscription for operational consistency checks",
  subscription_id: subscriptionId,
  tenant_id: "00000000-0000-0000-0000-000000000002",
  is_active: true,
  health_status: "healthy",
  sync_status: "succeeded",
  last_successful_sync_at: timestamp,
  business_service: "Payments",
  environment: "Production",
  criticality: "critical",
};
const evidence = {
  evidence_id: "evidence-layout",
  source_family: "activity",
  source_object_id: "observed-change-00000000-0000-0000-0000-000000000001",
  locator: "activity://observed-change",
  resource_ids: [`/subscriptions/${subscriptionId}/resourceGroups/payments/providers/Microsoft.Compute/virtualMachines/payments-01`],
  entity_ids: [],
  observed_at: timestamp,
  ingested_at: timestamp,
  watermark: timestamp,
  ingestion_status: "succeeded",
  provenance: { query_version: "layout-test" },
  freshness: "fresh",
  quality: "contradictory",
  availability: "available",
  confidence: "high",
  assertion: "A deployment change was observed; the reported health sources disagree.",
  fingerprint: "layout-evidence",
  situation_id: situationId,
};
const situation = {
  situation_id: situationId,
  resource_id: situationId,
  title: "Payments sources require review",
  situation_type: "resource_change",
  lifecycle_state: "open",
  severity: "high",
  priority: "P1",
  scope: { subscription: [subscriptionId], business_service: ["Payments"] },
  owner: "Payments operations",
  support_team: "Payments SRE",
  affected_resource_ids: evidence.resource_ids,
  linked_evidence_ids: [evidence.evidence_id],
  started_at: timestamp,
  last_observed_at: timestamp,
  evidence_state: "contradictory",
  warnings: ["Source observations conflict; review the original records."],
  contradiction_ids: [evidence.evidence_id],
  unknowns: ["Deployment impact has not been confirmed."],
  run_id: "layout-run",
  evidence: [evidence],
  links: [{
    link_id: "layout-link", entity_type: "business_service", entity_id: "Payments",
    relation: "affects", quality: "unresolved", provenance: {}, situation_id: situationId,
  }],
  source_status: [],
};

async function mockOperations(page: Page, unavailable: string[] = []) {
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const serviceContext = {
      subject: { name: "Payments", entity_type: "BusinessService", owner: "Payments operations", environment: "Production" },
      sections: { upstream_dependencies: ["payments-database"], qualification: "Deployment impact is unconfirmed." },
      graph_freshness: "fresh",
      live_observed_at: timestamp,
      source_status: { graph: "available" },
    };
    const data: Record<string, unknown> = {
      "/subscription-connections": [connection],
      "/incidents": { incidents: [] },
      "/business-services/Payments": serviceContext,
      "/risk/Payments": serviceContext,
      "/impact/Payments": serviceContext,
      "/situations": [situation],
      [`/situations/${situationId}`]: situation,
      [`/situations/${situationId}/audit`]: [{
        event_id: "audit-layout", actor: "service", action: "recorded", timestamp,
        scope_snapshot: situation.scope, situation_id: situationId,
        evidence_ids: [evidence.evidence_id], source_references: ["activity"], run_id: "layout-run",
      }],
      "/fabric-medallion/layers": {
        layers: { bronze: { healthy: 0, total: 1 }, silver: { healthy: 0, total: 0 }, gold: { healthy: 0, total: 0 } },
        tables: { bronze: [datasetName], silver: [], gold: [] },
      },
      [`/fabric-medallion/datasets/${datasetName}`]: {
        table_name: datasetName, availability: "healthy-empty", freshness: "fresh", quality: "complete",
        row_count: 0, observed_at: timestamp, ingested_at: timestamp, watermark: timestamp,
        stale_after_seconds: 3600, lineage_ref: "lineage://bronze_layout", error: "",
      },
      "/fabric-medallion/manifest": { entries: [] },
      "/fabric-medallion/governance": { gaps: [], ownership_gap_count: 0, tag_gap_count: 0, referential_integrity_blockers: 0 },
      "/fabric-medallion/ingestion-history": { runs: [] },
      "/fabric-medallion/capabilities": {
        capacity: { status: "paused", capacity_name: "layout-capacity" },
        semantic_readiness: { status: "deployment-blocked", reason: "Manual promotion is required." },
        data_agent_readiness: { status: "unavailable", configured: false },
        data_access_roles: { status: "unknown" },
        maintenance: { status: "unknown" },
        lineage: { datasets: [] },
      },
    };
    if (unavailable.includes(path) || !(path in data)) {
      return route.fulfill({ status: 503, json: { detail: `Source unavailable: ${path}` } });
    }
    return route.fulfill({ json: envelope(data[path]) });
  });
}

async function assertBounds(page: Page, width: number) {
  const overflow = await page.locator(".operational-page").evaluate((workspace) =>
    Array.from(workspace.querySelectorAll("*")).flatMap((element) => {
      const rect = element.getBoundingClientRect();
      const scroller = element.closest(".table-scroll, .data-table-wrap, .tab-list");
      if (scroller && scroller !== element) return [];
      return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1)
        ? [{ tag: element.tagName, className: element.className, left: rect.left, right: rect.right }]
        : [];
    }));
  expect(overflow).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
}

async function assertBeforeInsight(page: Page, content: Locator) {
  const insight = page.locator(".copilot-insights");
  await expect(insight).toHaveCount(1);
  await expect(content).toBeVisible();
  expect(await content.evaluate((element) =>
    Boolean(element.compareDocumentPosition(document.querySelector(".copilot-insights")!) & Node.DOCUMENT_POSITION_FOLLOWING),
  )).toBe(true);
}

async function assertNavigation(page: Page, name: string) {
  const links = page.getByRole("navigation", { name, exact: true }).getByRole("link");
  expect(await links.count()).toBeGreaterThan(0);
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
  test(`Connections keeps management and Fabric scope controls bounded at ${width}px`, async ({ page }) => {
    await mockOperations(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/connections");
    const registry = page.getByRole("region", { name: "Connection registry", exact: true });
    await assertBeforeInsight(page, registry);
    await expect(registry.getByRole("button", { name: "Sync now" })).toBeVisible();
    await page.getByRole("button", { name: "Add subscription connection" }).click();
    await expect(page.getByLabel("Client secret *", { exact: true })).toBeVisible();
    await assertBounds(page, width);
    await page.getByRole("button", { name: "Close onboarding form" }).click();
    const firstTab = page.getByRole("tab", { name: "Subscriptions", exact: true });
    await firstTab.focus();
    await firstTab.press("End");
    const lastTab = page.getByRole("tab", { name: "Ontology automation", exact: true });
    await expect(lastTab).toBeFocused();
    await expect.poll(async () => {
      const box = await lastTab.boundingBox();
      return box !== null && box.x >= 0 && box.x + box.width <= width;
    }).toBe(true);
    await page.getByRole("tab", { name: "Fabric Medallion", exact: true }).click();
    const selector = page.getByRole("combobox", { name: "Subscription connection", exact: true });
    await expect(selector).toHaveValue(connection.connection_id);
    await expect(selector).toHaveCSS("min-height", width <= 820 ? "44px" : "40px");
    await expect(page.getByText("Fabric capacity layout-capacity is paused.")).toBeVisible();
    await assertBeforeInsight(page, page.getByRole("heading", { name: "Bronze layer", exact: true }));
    await assertBounds(page, width);
    await assertNavigation(page, "Fabric sections");
    await page.getByRole("tab", { name: "Ontology automation", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "Connection", exact: true })).toHaveValue(connection.connection_id);
    await expect(page.getByRole("heading", { name: "Native entry point is unavailable", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Run discovery now", exact: true })).toHaveCount(0);
    await assertBounds(page, width);
    await assertBeforeInsight(page, page.getByRole("heading", { name: "Native entry point is unavailable", exact: true }));
  });

  test(`Fabric page keeps scope before health and readiness reachable at ${width}px`, async ({ page }, testInfo) => {
    await mockOperations(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/connections/fabric?subscription=${subscriptionId}`);
    await expect(page.getByRole("combobox", { name: "Subscription connection", exact: true })).toHaveValue(subscriptionId);
    await expect(page.getByRole("heading", { name: "Bronze layer", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Semantic model and Data Agent readiness", exact: true })).toBeVisible();
    const dataset = page.locator(".fabric-dataset-card").filter({ hasText: datasetName });
    await expect(dataset).toBeVisible();
    expect((await dataset.boundingBox())!.width).toBeGreaterThanOrEqual(220);
    await assertBeforeInsight(page, page.getByRole("heading", { name: "Bronze layer", exact: true }));
    await assertBounds(page, width);
    await assertNavigation(page, "Fabric sections");
    if (width === 375) await page.screenshot({ path: testInfo.outputPath("fabric-375.png"), fullPage: true });
  });

  test(`Services leads with the catalog before supporting analysis at ${width}px`, async ({ page }) => {
    await mockOperations(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/services");
    const catalog = page.getByRole("region", { name: "Service catalog", exact: true });
    const risk = page.locator("#service-risk-map");
    await expect(catalog.getByRole("link", { name: "Review Payments", exact: true })).toHaveAttribute("href", "/services/Payments");
    expect(await catalog.evaluate((element) =>
      Boolean(element.compareDocumentPosition(document.getElementById("service-risk-map")!) & Node.DOCUMENT_POSITION_FOLLOWING),
    )).toBe(true);
    await assertBeforeInsight(page, risk);
    await assertBounds(page, width);
    await assertNavigation(page, "Services sections");
  });

  test(`Service detail retains qualified source sections and consistent headers at ${width}px`, async ({ page }) => {
    await mockOperations(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/services/Payments");
    for (const name of ["Service context", "Aggregated risk", "Dependency impact"]) {
      const section = page.getByRole("region", { name, exact: true });
      await assertBeforeInsight(page, section);
      await expect(section.getByRole("heading")).toHaveCSS("font-size", "18px");
      await expect(section.locator(".card-header p")).toHaveCSS("font-size", "14px");
      const disclosure = section.locator("details > summary");
      await disclosure.click();
      await expect(section.getByText("Deployment impact is unconfirmed.")).toBeVisible();
    }
    await assertBounds(page, width);
    await assertNavigation(page, "Service detail sections");
  });

  test(`Situations keeps triage controls first with a visible priority selection at ${width}px`, async ({ page }) => {
    await mockOperations(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/situations");
    await expect(page.getByRole("link", { name: situation.title, exact: true })).toBeVisible();
    await assertBeforeInsight(page, page.locator(".queue-card"));
    const priority = page.getByRole("button", { name: "P1", exact: true });
    await priority.click();
    await expect(priority).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "All priorities" })).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByRole("link", { name: situation.title, exact: true })).toBeVisible();
    await assertBounds(page, width);
  });

  test(`Situation detail keeps conflicts, unknowns and evidence review accessible at ${width}px`, async ({ page }, testInfo) => {
    await mockOperations(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/situations/${situationId}`);
    await expect(page.getByRole("heading", { name: "Evidence conflicts", exact: true })).toBeVisible();
    await expect(page.getByText(situation.unknowns[0], { exact: true })).toBeVisible();
    await expect(page.getByText(/Source records remain read-only/)).toBeVisible();
    await assertBeforeInsight(page, page.getByRole("region", { name: "Audit history", exact: true }));
    await assertBounds(page, width);
    await assertNavigation(page, "Situation detail sections");
    await expect(page.getByRole("region", { name: "Evidence timeline", exact: true }).getByText(evidence.assertion, { exact: true })).toBeVisible();
    const trigger = page.getByRole("button", { name: "View evidence details" });
    await trigger.click();
    const drawer = page.getByRole("complementary", { name: "Evidence detail drawer" });
    await expect(drawer).toBeFocused();
    await expect(drawer.getByText(evidence.locator, { exact: true })).toBeVisible();
    await assertBounds(page, width);
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(trigger).toBeFocused();
    if (width === 375) await page.screenshot({ path: testInfo.outputPath("situation-375.png"), fullPage: true });
  });
}

test("Connections tabs support automatic keyboard activation and wrap at mobile width", async ({ page }) => {
  await mockOperations(page);
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("/connections");
  const tabs = page.getByRole("tablist");
  const first = tabs.getByRole("tab").first();
  const last = tabs.getByRole("tab").last();
  await first.focus();
  await first.press("ArrowLeft");
  await expect(last).toBeFocused();
  await expect(last).toHaveAttribute("aria-selected", "true");
  await last.press("Home");
  await expect(first).toBeFocused();
  await expect(first).toHaveAttribute("aria-selected", "true");
  await first.press("End");
  await expect(last).toBeFocused();
  await last.press("ArrowRight");
  await expect(first).toBeFocused();
  await expect(tabs.locator('[tabindex="0"]')).toHaveCount(1);
  await assertBounds(page, 375);
});

test("Fabric section destinations survive independent unavailable sources", async ({ page }) => {
  await mockOperations(page, ["/fabric-medallion/manifest", "/fabric-medallion/capabilities"]);
  await page.goto(`/connections/fabric?subscription=${subscriptionId}`);
  await expect(page.getByText("Publication manifest is unavailable", { exact: true })).toBeVisible();
  await expect(page.getByText("Fabric medallion health is unavailable", { exact: true })).toBeVisible();
  await expect(page.getByText("Healthy · Empty", { exact: true })).toBeVisible();
  await assertNavigation(page, "Fabric sections");
  await assertBeforeInsight(page, page.getByRole("region", { name: "Governance gaps", exact: true }));
});

test("Situation audit failure stays explicit alongside available evidence", async ({ page }) => {
  await mockOperations(page, [`/situations/${situationId}/audit`]);
  await page.goto(`/situations/${situationId}`);
  await expect(page.getByText("Audit history unavailable from the service", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "View evidence details" })).toBeVisible();
  await assertNavigation(page, "Situation detail sections");
  await assertBeforeInsight(page, page.getByRole("region", { name: "Evidence by source", exact: true }));
});
