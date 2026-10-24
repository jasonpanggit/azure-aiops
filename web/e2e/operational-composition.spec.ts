import { expect, test, type Page } from "@playwright/test";

const envelope = (data: unknown) => ({
  data, evidence: [], warnings: [], scope: {}, knowledge_version: "composition-test",
});
const connection = {
  connection_id: "conn-a", name: "Production", subscription_id: "sub-a", tenant_id: "tenant",
  scope_key: "a", is_active: true, business_service: "Payroll", owner: "Operations",
  environment: "prod", criticality: "high", sync_status: "succeeded", sync_record_count: 8175,
  last_successful_sync_at: "2026-10-16T00:00:00Z", health_status: "healthy",
};
const observation = {
  observation_id: "observed-1", change_id: "CHG-1", change_type: "Update",
  summary: "Observed TLS setting changed", category: "Security", source: "Fixture projection",
  changed_at: "2026-10-16T12:00:00Z", resource_name: "fixture-resource", application: "Payments",
  business_service: "Checkout", environment: "production",
  configuration: {
    basis: "change_states", withheld_field_count: 2,
    fields: [
      { field: "httpsOnly", before: { status: "reported", value: false }, after: { status: "reported", value: true }, comparison: "changed" },
      { field: "minimumTlsVersion", before: { status: "unreported" }, after: { status: "withheld" }, comparison: "not_comparable" },
    ],
  },
};

async function mockSources(page: Page) {
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const data: Record<string, unknown> = {
      "/subscription-connections": [connection, { ...connection, connection_id: "conn-b", business_service: "" }],
      "/incidents": { incidents: [] },
      "/inventory/resources": {
        resources: [], scope_qualification: { status: "supported", unsupported_dimensions: [] },
        generation_id: "fixture-generation", family_availability: { paas: { family: "paas", state: "ready" } },
      },
      "/fabric-medallion/layers": { layers: {
        bronze: { healthy: 1, total: 2 }, silver: { healthy: 0, total: 0 }, gold: { healthy: 0, total: 1 },
      } },
      "/ontology-discovery/status": { generation: {
        status: "staged", active_generation: "", validation: { passed: false },
        compatibility: { all_consumers_compatible: false },
      } },
      "/fabric-medallion/capabilities": {
        capacity: { status: "healthy" }, semantic_readiness: { status: "deployment-blocked" },
        data_agent_readiness: { status: "disabled" },
      },
      "/changes/observations": {
        observations: [observation], authorized_count: 1, extent: "loaded_change_projection", read_only: true,
        facets: { category: ["Security"], source: ["Fixture projection"] },
        facet_metadata: { category: { total: 1, returned: 1, truncated: false }, source: { total: 1, returned: 1, truncated: false } },
      },
    };
    return path in data ? route.fulfill({
      json: { ...envelope(data[path]), pagination: { offset: 0, limit: 25, total: path === "/inventory/resources" ? 57 : 1, next_offset: null } },
    }) : route.fulfill({ status: 503, json: { error: { code: "unavailable", message: `Unmocked source: ${path}` } } });
  });
}

for (const width of [375, 1912, 2560]) {
  test(`actual service actions, readiness, and change details compose at ${width}px`, async ({ page }, info) => {
    await mockSources(page);
    await page.setViewportSize({ width, height: 1080 });
    await page.goto("/services");
    const mapped = page.getByRole("link", { name: "Review Payroll", exact: true });
    const unmapped = page.getByRole("link", { name: "Review Unmapped service", exact: true });
    await expect(mapped).toHaveText("Open brief");
    await expect(mapped).toHaveClass("button button-secondary");
    await expect(mapped).toHaveCSS("white-space", "nowrap");
    await expect(mapped).toHaveAttribute("href", "/services/Payroll");
    await expect(unmapped).toHaveText("Review mappings");
    expect((await mapped.boundingBox())!.width).toBeGreaterThanOrEqual(90);
    expect((await mapped.boundingBox())!.height).toBeGreaterThanOrEqual(width <= 820 ? 44 : 40);
    await page.goto("/connections?tab=subscriptions&connection=conn-a");
    const readiness = page.getByRole("region", { name: "Readiness for Production", exact: true });
    await expect(readiness.getByText(/57 authorized inventory resources/)).toBeVisible();
    await expect(readiness.getByText(/8175 discovery records/)).toBeVisible();
    const stages = readiness.locator(".connection-readiness-stages > li");
    await expect(stages).toHaveCount(7);
    await expect(stages.nth(2).getByText("degraded", { exact: true })).toBeVisible();
    await expect(stages.nth(3).getByText("unknown", { exact: true })).toBeVisible();
    for (const stage of await stages.all()) {
      const heading = (await stage.locator(".connection-readiness-heading").boundingBox())!;
      const badge = (await stage.locator(".status-badge").boundingBox())!;
      expect(badge.width).toBeLessThan(heading.width / 2);
    }
    const first = (await stages.nth(0).boundingBox())!;
    const second = (await stages.nth(1).boundingBox())!;
    if (width >= 1200) {
      expect(Math.abs(first.y - second.y)).toBeLessThanOrEqual(1);
      expect(second.x).toBeGreaterThan(first.x + first.width);
    } else {
      expect(second.y).toBeGreaterThanOrEqual(first.y + first.height);
    }
    await readiness.screenshot({ path: info.outputPath(`readiness-${width}.png`), style: ".shell-topbar { visibility: hidden; }" });
    await page.goto("/changes");
    const changes = page.getByRole("region", { name: "Independent change observations", exact: true });
    await expect(changes.getByText(observation.summary, { exact: true })).toBeVisible();
    const summary = (await changes.locator(".change-observation-summary").boundingBox())!;
    const comparison = changes.getByText("Compare reported configuration states", { exact: true });
    const compareBox = (await comparison.boundingBox())!;
    if (width >= 1200) expect(compareBox.x).toBeGreaterThan(summary.x + summary.width);
    else expect(compareBox.y).toBeGreaterThanOrEqual(summary.y + summary.height);
    await comparison.focus();
    await comparison.press("Enter");
    await expect(changes.getByText("Withheld: unsupported value", { exact: true })).toBeVisible();
    await expect(changes.getByText("Unreported", { exact: true })).toBeVisible();
    await changes.screenshot({ path: info.outputPath(`observations-${width}.png`), style: ".shell-topbar { visibility: hidden; }" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
