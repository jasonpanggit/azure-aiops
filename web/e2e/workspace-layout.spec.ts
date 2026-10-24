import { expect, test, type Locator, type Page } from "@playwright/test";

const timestamp = "2026-09-06T08:00:00Z";
const resourceId = "/subscriptions/sub-layout/resourceGroups/payments/providers/Microsoft.Compute/virtualMachines/payments-01";
const sourceWarning = "Topology observations are stale; validate against current configuration.";
const envelope = (data: unknown, warnings: string[] = []) => ({
  data, warnings, scope: {}, knowledge_version: "workspace-layout",
  evidence: [{ source_engine: "ARG", source_table: "resources", timestamp, confidence: "medium", freshness: "stale" }],
});
const summary = {
  hub_count: 1, spoke_count: 1, isolated_vnet_count: 0, peering_count: 0,
  cross_subscription_peering_count: 0, unhealthy_peering_count: 0,
  shared_service_count: 0, connection_count: 1, gap_count: 1,
  gaps_by_severity: { high: 1 }, gaps_by_category: { missing_nsg: 1 },
  rule_finding_count: 1, rule_findings_by_severity: { high: 1 },
  rule_findings_by_category: { broad_source: 1 }, intended_design_declared: false,
  resource_counts: { vnets: 2 }, projected_full_node_count: 2,
};
const resources = ["hub", "spoke"].map((role) => ({
  id: `/subscriptions/sub-layout/resourceGroups/payments/providers/Microsoft.Network/virtualNetworks/payments-${role}`,
  name: `payments-${role}`, entity_type: "VNet", role, subscription_id: "sub-layout",
  resource_group: "payments", location: "australiaeast", connection_id: "layout",
  environment: "Production", business_service: "Payments", application: "Payments API",
  owner: "Payments SRE", tags: {}, details: {},
}));
const classification = (index: number) => ({
  vnet_id: resources[index].id, name: resources[index].name,
  role: resources[index].role, score: index === 0 ? 4 : 0,
  signals: index === 0 ? ["hosts_firewall"] : [], connection_id: "layout",
  subscription_id: "sub-layout", peer_count: 0,
});
const topology = {
  hubs: [classification(0)], spokes: [classification(1)], isolated: [], links: [],
  shared_services: [], resources, relationships: [], unresolved_peer_vnet_ids: [],
  connection_ids: ["layout"], counts: { vnets: 2 },
};
const gap = {
  gap_id: "gap-layout", title: "Payments subnet has no NSG", severity: "high", category: "missing_nsg",
  resource_id: `${resources[1].id}/subnets/application`, resource_name: "payments-application",
  resource_type: "Subnet", detail: "Observed subnet has no associated NSG.",
  recommendation: "Review approved controls before making a change.", evidence: {}, basis: "configuration",
  connection_id: "layout", subscription_id: "sub-layout", environment: "Production",
};
const finding = {
  finding_id: "finding-layout", title: "Broad source on payments rule", severity: "high", category: "broad_source",
  rule_id: "payments-rule", rule_name: "payments-rule", control: "NetworkSecurityGroup",
  control_id: `${resourceId}/controls/nsg`, detail: "Source scope requires operator review.",
  recommendation: "Validate traffic requirements before narrowing the rule.", evidence: {},
  connection_id: "layout", subscription_id: "sub-layout", environment: "Production",
};
const entities = [
  { id: `resource:${resourceId}`, kind: "resource", name: "payments-01" },
  { id: "application:Payments API", kind: "application", name: "Payments API" },
  { id: "business_service:Payments", kind: "business_service", name: "Payments" },
].map((entity) => ({
  ...entity, version: "v1", state: "current", confidence: "medium", provenance: [],
  properties: { business_service: "Payments", resource_id: resourceId },
}));
const snapshot = {
  twin_id: "operational-twin", version: "v1", previous_version: "v0", observed_at: timestamp,
  scope: {}, entities, relationships: [{
    id: "supports-payments", source: entities[0].id, target: entities[2].id,
    type: "supports", confidence: "medium", provenance: [],
  }],
  timeline: [{ timestamp, type: "resource_observed", entity: entities[0].id, summary: "Payments dependency observed." }],
  provenance: [], confidence: "medium",
  temporal: {
    current_state_version: "v1", previous_state_version: "v0", change_history: [{ change_type: "resource_observed" }],
    risk_trend: [{ risk_score: 32 }],
    dependency_evolution: [{ relationship_type: "supports", current_count: 1, previous_count: 0 }],
  },
};
const context = {
  subject: { name: "Payments", entity_type: "business_service", owner: "Payments SRE" },
  sections: { ownership: [{ name: "Payments SRE" }], dependencies: ["Payments API"] },
  risk: { score: 82 },
};
const canonicalResult = {
  question: "Summarize the investigation", tool_calls: [], answer: null, fact_status: "ok",
  warnings: ["Visible subset is incomplete; widen scope for full coverage."],
  contract_version: "1", thread_id: `thr-${"a".repeat(32)}`, thread_revision: 1,
  policy_status: "fallback", fallback_reason: "planner_unavailable",
  coverage: { visible_count: 1, total_count: 2, complete: false },
  citations: [{ citation_id: "tool:0:resources:1", source: "azure-resource-graph", status: "ok", observed_at: timestamp, resource_id: resourceId }],
  synthesis: {
    status: "synthesized", reason: "multi_domain", domain_count: 2, warning: "",
    claims: [{
      finding_id: "f1", summary: "Payments needs operator review before patching.",
      evidence_refs: ["tool:0:resources:1"], confidence: "medium", freshness: "stale", uncertainty: [],
    }],
  },
};

async function mockWorkspaces(page: Page, unavailable: string[] = []) {
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const data: Record<string, unknown> = {
      "/subscription-connections": [],
      "/network/topology": { topology, summary, coverage: { total: 2, returned: 2, truncated: false } },
      "/network/summary": summary,
      "/network/firewall-bypass": { gaps: [], count: 0 },
      "/network/gaps": { gaps: [gap], intended_design_declared: false, summary },
      "/network/rule-findings": { findings: [finding], summary },
      "/network/policy": {
        name: "Operator-declared network intent", description: "Review intended design before changing controls.",
        is_declared: false, source_path: "fixture", hub_vnet_names: [],
        require_firewall_in_hub: true, require_default_route_to_firewall: true,
        require_nsg_on_every_subnet: true, forbid_spoke_to_spoke_peering: true,
        forbid_public_ip_on_spoke_nics: true, require_private_endpoint_for_services: [],
        require_private_dns_zone_link: true, require_bidirectional_peering: true,
        approved_peerings: [], exempt_subnet_names: [], exempt_vnet_names: [], rules: [],
        supported_targets: ["subnets", "vnets"], supported_operators: ["exists", "equals"],
      },
      "/business-services/Payments": context, "/risk/Payments": context, "/impact/Payments": context,
      "/incidents": {
        incidents: [{
          incident: { incident_id: "INC-layout", title: "Payments latency", severity: "high", status: "active", started_at: timestamp },
          business_impact: { applications: ["Payments API"], services: [], business_services: ["Payments"], owners: ["Payments SRE"], support_teams: [] },
          timeline: [{ event_id: "event-layout", event_type: "Alert", timestamp, summary: "Payments latency requires investigation.", source: "Monitor", evidence: ["ARG"] }],
        }],
        read_only: true, freshness: timestamp, operational_patterns: [], audience_summaries: {},
      },
      "/vulnerabilities/summary": { critical_count: 1, internet_exposed_count: 1 },
      "/vulnerabilities/exposures": [{
        cve_id: "CVE-2026-0001", severity: "critical", priority_score: 91,
        recommended_patch: "Install KB500", affected_business_service_count: 1,
      }],
      "/remediation-plans": { plans: [{ plan_id: "plan-layout", title: "Review payments patch", status: "candidate" }] },
      "/copilot/investigate": canonicalResult,
      "/copilot/investigate-context": {
        synthesis: { narration: "Review source uncertainty before acting." }, findings: [],
        synthesis_mode: "foundry", warnings: [sourceWarning],
      },
      "/copilot/investigations": {
        ...canonicalResult,
      },
      "/twin/graph": snapshot,
      "/twin/compare": { current_version: "v1", previous_version: "v0", added: [], removed: [], changed: [], summary: "Prior revision retained for comparison." },
      "/twin/scenarios": {
        scenario: route.request().method() === "POST" ? route.request().postDataJSON().scenario : "firewall_failure",
        target: resourceId, version: "v1", likely_impact: "Payments dependencies may lose inspection.",
        risk_delta: 20, impacted_entities: entities, assumptions: ["Operator validation required."],
      },
      [`/twin/traverse/${encodeURIComponent(resourceId)}`]: {
        resource_id: resourceId, path: entities, relationships: snapshot.relationships, business_consequence: ["Payments", "Payments API"],
      },
      "/twin/export": {
        format: "operational-twin-export", exported_at: timestamp, snapshot,
        records: Array.from({ length: 40 }, (_, index) => ({ resource_id: resourceId, index })),
      },
    };
    if (unavailable.includes(path) || !(path in data)) {
      return route.fulfill({ status: 503, json: { detail: `Source unavailable: ${path}` } });
    }
    return route.fulfill({ json: envelope(data[path], path === "/network/topology" || path === "/twin/graph" ? [sourceWarning] : []) });
  });
}

async function assertBounds(page: Page, width: number) {
  await expect(async () => {
    const overflow = await page.locator(".operational-page").evaluate((workspace) =>
      Array.from(workspace.querySelectorAll("*")).flatMap((element) => {
        const rect = element.getBoundingClientRect();
        const scroller = element.closest(".table-scroll, .tab-list, .workspace-tabs, .twin-export-data");
        if (scroller && scroller !== element) return [];
        return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1)
          ? [{ tag: element.tagName, className: String(element.className), left: rect.left, right: rect.right }]
          : [];
      }));
    const scrollState = await page.locator(".operational-page").evaluate((workspace) => {
      const containers = [];
      for (let element: Element | null = workspace; element; element = element.parentElement) {
        const style = getComputedStyle(element);
        containers.push({
          tag: element.tagName, className: String(element.className),
          left: element.getBoundingClientRect().left, scrollLeft: element.scrollLeft,
          client: element.clientWidth, scroll: element.scrollWidth, overflow: style.overflowX,
        });
      }
      return { x: scrollX, containers };
    });
    expect(overflow, JSON.stringify(scrollState)).toEqual([]);
    expect(scrollState.containers.filter((container) =>
      container.scroll > container.client + 1 || container.scrollLeft !== 0,
    )).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
  }).toPass({ timeout: 5000 });
}

async function assertBeforeInsight(page: Page, content: Locator) {
  await expect(page.locator(".copilot-insights, .topology-insights")).toHaveCount(1);
  expect(await content.evaluate((element) =>
    Boolean(element.compareDocumentPosition(document.querySelector(".copilot-insights, .topology-insights")!) & Node.DOCUMENT_POSITION_FOLLOWING),
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

for (const width of [2560, 1912, 1440, 820, 768, 375, 320]) {
  test(`Network keeps all five task views before one qualified insight at ${width}px`, async ({ page }, testInfo) => {
    await mockWorkspaces(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/network");
    await expect(page.getByText("Intended design is not declared.", { exact: true })).toBeVisible();
    await expect(page.getByText(sourceWarning, { exact: true }).first()).toBeVisible();
    for (const name of ["Path analysis", "Topology", "Inspection gaps", "Rule findings", "Design policy"]) {
      const tab = page.getByRole("tab", { name, exact: true });
      await tab.focus();
      await tab.press("Enter");
      await expect(tab).toHaveAttribute("aria-selected", "true");
      const panel = page.getByRole("tabpanel", { name, exact: true });
      await expect(panel).toBeVisible();
      await assertBeforeInsight(page, panel);
      await assertBounds(page, width);
    }
    await page.getByRole("tab", { name: "Topology", exact: true }).click();
    await expect(page.getByRole("region", { name: "Network topology", exact: true })).toBeVisible();
    if (width === 375 || width === 1440) await page.screenshot({ path: testInfo.outputPath(`network-${width}.png`), fullPage: true });
  });

  test(`Investigate keeps modes, conclusions and local history usable at ${width}px`, async ({ page }, testInfo) => {
    await mockWorkspaces(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/investigate?type=BusinessService&value=Payments");
    await expect(page.getByRole("heading", { name: "Business service: Payments", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Recommended actions", exact: true }).getByText("Review payments patch", { exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Entry point", exact: true })).toHaveValue("BusinessService");
    await expect(page.getByRole("combobox", { name: "Entry point", exact: true })).toHaveCSS("min-height", width <= 820 ? "44px" : "40px");
    const executive = page.getByRole("button", { name: "Executive", exact: true });
    const engineer = page.getByRole("button", { name: "Engineer", exact: true });
    await expect(executive).toHaveAttribute("aria-pressed", "true");
    await engineer.click();
    await expect(engineer).toHaveClass(/segmented-active/);
    await expect(engineer).toHaveAttribute("aria-pressed", "true");
    await assertBounds(page, width);
    await executive.click();
    const generate = page.getByRole("button", { name: "Generate conclusion", exact: true });
    await expect(generate).toHaveClass(/button-ai/);
    await expect(generate).toHaveCSS("background-image", "none");
    await expect(generate).toHaveCSS("background-color", "rgb(15, 108, 189)");
    const request = page.waitForRequest((item) => item.url().includes("/copilot/investigations") && item.method() === "POST");
    await generate.click();
    expect((await request).postDataJSON().contract_version).toBe("1");
    await expect(page.getByText("Payments needs operator review before patching.", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Investigation degradation")).toBeVisible();
    await expect(page.getByLabel("Investigation citations")).toContainText("azure-resource-graph");
    await expect(page.getByLabel("Investigation uncertainty")).toContainText("Visible subset is incomplete");
    await page.getByRole("button", { name: "Save view locally", exact: true }).click();
    const saved = page.getByText("Open saved investigations", { exact: true });
    await expect(saved.locator("..")).not.toHaveAttribute("open");
    await saved.focus();
    await saved.press("Enter");
    await page.getByRole("button", { name: /BusinessService: Payments/ }).click();
    await expect(page.getByLabel("Subject", { exact: true })).toHaveValue("Payments");
    await expect(page.getByText("Browser-session actions, not service-recorded audit history.", { exact: true })).toBeVisible();
    const activity = page.getByText("View local activity", { exact: true });
    await activity.focus();
    await activity.press("Enter");
    await expect(activity.locator("..")).toHaveAttribute("open");
    await assertBounds(page, width);
    await assertNavigation(page, "Investigation sections");
    if (width === 375 || width === 1440) {
      await page.screenshot({ path: testInfo.outputPath(`investigate-${width}.png`), fullPage: true });
      await page.getByRole("region", { name: "Business impact and dependency context", exact: true }).screenshot({ path: testInfo.outputPath(`investigate-impact-${width}.png`) });
    }
  });

  test(`Twin keeps scenario work first and export bounded at ${width}px`, async ({ page }, testInfo) => {
    await mockWorkspaces(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/twin");
    await page.getByRole("combobox", { name: "Resource for impact analysis", exact: true }).selectOption(entities[0].id);
    await expect(page.getByText("Payments dependencies may lose inspection.", { exact: true })).toBeVisible();
    await expect(page.getByText(sourceWarning, { exact: true }).first()).toBeVisible();
    const scenario = page.locator("#twin-scenario");
    for (const section of await page.locator(".twin-grid > .card").all()) {
      expect((await section.boundingBox())!.width).toBeGreaterThanOrEqual(220);
    }
    const gridBox = (await page.locator(".twin-grid").boundingBox())!;
    const contextBox = (await page.locator(".twin-grid > .card").last().boundingBox())!;
    expect(Math.abs(contextBox.width - gridBox.width)).toBeLessThanOrEqual(1);
    expect(Math.abs(contextBox.x - gridBox.x)).toBeLessThanOrEqual(1);
    expect(await scenario.evaluate((element) =>
      Boolean(element.compareDocumentPosition(document.getElementById("twin-temporal")!) & Node.DOCUMENT_POSITION_FOLLOWING),
    )).toBe(true);
    await assertBeforeInsight(page, page.locator("#twin-export"));
    const selector = page.getByLabel("Scenario", { exact: true });
    await expect(selector).toHaveCSS("min-height", width <= 820 ? "44px" : "40px");
    const request = page.waitForRequest((item) => item.url().includes("/twin/scenarios") && item.method() === "POST");
    await selector.selectOption("cve_exploitation");
    expect((await request).postDataJSON()).toEqual({ scenario: "cve_exploitation", target: resourceId });
    await expect(page.getByRole("region", { name: "Raw twin export", exact: true })).toBeHidden();
    const disclosure = page.getByText("Inspect full twin export", { exact: true });
    await expect(page.locator(".twin-export-data")).toHaveCount(0);
    const suggestedQuestions = page.getByText("View suggested questions", { exact: true });
    const question = page.getByText("What changed since the previous twin revision?", { exact: true });
    await expect(question).toBeHidden();
    await suggestedQuestions.click();
    await expect(question).toBeVisible();
    await suggestedQuestions.click();
    await expect(question).toBeHidden();
    await disclosure.focus();
    await disclosure.press("Enter");
    const data = page.getByRole("region", { name: "Raw twin export", exact: true });
    await expect(data).toContainText("operational-twin-export");
    expect((await data.boundingBox())!.height).toBeLessThanOrEqual(480);
    expect(await data.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
    await page.keyboard.press("Tab");
    await expect(data).toBeFocused();
    await assertBounds(page, width);
    await assertNavigation(page, "Twin sections");
    if (width === 375 || width === 1440) {
      await page.screenshot({ path: testInfo.outputPath(`twin-${width}.png`), fullPage: true });
      await scenario.screenshot({ path: testInfo.outputPath(`twin-scenario-${width}.png`) });
    }
    await disclosure.click();
    await expect(data).toHaveCount(0);
    await disclosure.click();
    await expect(data).toContainText("operational-twin-export");
    await disclosure.click();
    await expect(data).toHaveCount(0);
    await page.getByRole("button", { name: "Ask Copilot about the twin", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Operations Copilot", exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Operations Copilot", exact: true })).toHaveCount(0);
  });
}

test("Network tabs support automatic keyboard activation and wrap at mobile width", async ({ page }) => {
  await mockWorkspaces(page);
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("/network");
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

test("Network keeps independent unavailable topology retry and source warnings visible", async ({ page }) => {
  await mockWorkspaces(page, ["/network/topology"]);
  await page.goto("/network");
  await page.getByRole("tab", { name: "Topology", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Topology is unavailable", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry loading topology", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Inspection gaps", exact: true }).click();
  await expect(page.getByRole("heading", { name: gap.title, exact: true })).toBeVisible();
});

test("Investigate keeps source failures visible above available operational context", async ({ page }) => {
  await mockWorkspaces(page, ["/network/topology"]);
  await page.goto("/investigate?type=BusinessService&value=Payments");
  await expect(page.getByText("topology unavailable", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Recommended actions", exact: true }).getByText("Review payments patch", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Topology is unavailable", exact: true })).toBeVisible();
});

test("Twin keeps graph failure visible and technical export unopened", async ({ page }) => {
  await mockWorkspaces(page, ["/twin/graph"]);
  await page.goto("/twin");
  await expect(page.getByRole("heading", { name: "Twin unavailable", exact: true })).toBeVisible();
  await expect(page.getByText("Inspect full twin export", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Raw twin export data", exact: true })).toHaveCount(0);
  await expect(page.locator(".copilot-insights")).toHaveCount(1);
});
