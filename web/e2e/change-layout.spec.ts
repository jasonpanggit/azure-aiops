import { expect, test, type Page } from "@playwright/test";
import { buildChangeAssessment, buildChangeHistory, buildChangeReport } from "../src/test/change-fixtures";

const warning = "Source coverage is incomplete; validate current state before acting.";
const envelope = (data: unknown) => ({
  data, scope: {}, knowledge_version: "change-layout", warnings: [warning],
  evidence: [{ source_engine: "ARG", source_table: "activity", timestamp: "2026-09-06T08:00:00Z", confidence: "low", freshness: "stale" }],
});

async function mockChanges(page: Page, unavailable: string[] = [], empty = false) {
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const data: Record<string, unknown> = {
      "/subscription-connections": [],
      "/incidents": buildChangeReport(empty ? 0 : 23),
      "/changes/assessment-sources": {
        sources: ["terraform_plan", "bicep_what_if", "github_pull_request"],
        simulation_domains: ["network"], verdicts: ["approve_with_conditions"], risk_levels: ["high"],
      },
      "/changes/assessments": buildChangeHistory(),
      "/changes/assess": buildChangeAssessment(),
      "/copilot/investigate-context": {
        synthesis: { narration: "Review uncertainty and accountable owners before acting." },
        findings: [], synthesis_mode: "foundry", warnings: [warning],
      },
      "/copilot/investigations": {
        contract_version: "1", policy_status: "accepted", tool_results: [], uncertainty: [],
        synthesis: {
          status: "synthesized", warning: "",
          claims: [{ summary: "Review uncertainty and accountable owners before acting.", evidence_refs: [], confidence: "low", uncertainty: [] }],
        },
      },
    };
    if (unavailable.includes(path) || !(path in data)) {
      return route.fulfill({ status: 503, json: { detail: `Source unavailable: ${path}` } });
    }
    return route.fulfill({ json: envelope(data[path]) });
  });
}

async function assertLayout(page: Page, width: number) {
  await expect(async () => {
    const overflow = await page.locator(".operational-page").evaluate((workspace) =>
      Array.from(workspace.querySelectorAll("*")).flatMap((element) => {
        const rect = element.getBoundingClientRect();
        const scroller = element.closest(".table-scroll, .tab-list");
        if (scroller && scroller !== element) return [];
        return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1)
          ? [{ tag: element.tagName, className: String(element.className), left: rect.left, right: rect.right }]
          : [];
      }));
    expect(overflow).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
  }).toPass({ timeout: 5000 });
  await expect(page.locator(".copilot-insights")).toHaveCount(1);
  for (const button of await page.locator(".table-footer .button").all()) {
    await expect(button).toHaveCSS("white-space", "nowrap");
  }
}

async function assertNavigation(page: Page) {
  const links = page.getByRole("navigation", { name: "Assessment sections", exact: true }).getByRole("link");
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
  test(`Changes keeps source-qualified event text readable before Copilot at ${width}px`, async ({ page }, testInfo) => {
    await mockChanges(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/changes");
    const stream = page.getByRole("region", { name: "Incident timeline associations", exact: true });
    await expect(stream.getByText("Observed payments change 0", { exact: true })).toBeVisible();
    await expect(stream.locator(".timeline-event")).toHaveCount(20);
    await expect(stream.getByText("Evidence unavailable from source", { exact: true })).toBeVisible();
    await expect(stream.getByText("Source link unavailable", { exact: true })).toBeVisible();
    await expect(page.getByText(warning, { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Assess a proposed change", exact: true })).toHaveAttribute("href", "/changes/predeploy");
    await expect(stream.getByRole("link", { name: "Payments latency investigation", exact: true }).first()).toHaveAttribute("href", "/situations/INC-layout");
    for (const content of await stream.locator(".timeline-event > div:last-child").all()) {
      expect((await content.boundingBox())!.width).toBeGreaterThanOrEqual(180);
    }
    expect(await stream.evaluate((element) =>
      Boolean(element.compareDocumentPosition(document.querySelector(".copilot-insights")!) & Node.DOCUMENT_POSITION_FOLLOWING),
    )).toBe(true);
    await assertLayout(page, width);
    await stream.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(stream.locator(".timeline-event")).toHaveCount(3);
    await expect(stream.getByText("Observed payments change 22", { exact: true })).toBeVisible();
    await assertLayout(page, width);
    if (width === 375 || width === 1440) {
      await stream.screenshot({ path: testInfo.outputPath(`changes-${width}.png`) });
      await page.screenshot({ path: testInfo.outputPath(`changes-page-${width}.png`), fullPage: true });
    }
  });

  test(`Predeploy keeps advisory results, unknowns and scoped history navigable at ${width}px`, async ({ page }, testInfo) => {
    await mockChanges(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/changes/predeploy");
    const form = page.getByRole("form", { name: "Submit a proposed change", exact: true });
    const submit = form.getByRole("button", { name: "Assess impact", exact: true });
    await expect(submit).toBeDisabled();
    await expect(submit).toHaveClass(/button-primary/);
    await expect(submit).toHaveCSS("background-image", "none");
    await expect(form.getByRole("combobox", { name: "Change source", exact: true })).toHaveCSS("min-height", width <= 820 ? "44px" : "40px");
    await expect(page.getByRole("navigation", { name: "Assessment sections" }).getByRole("link")).toHaveCount(2);
    const artifact = form.getByRole("textbox", { name: "Change artifact (JSON)", exact: true });
    await artifact.fill("{");
    await form.getByRole("button", { name: "Inspect artifact locally", exact: true }).click();
    await expect(form.getByRole("alert")).toBeVisible();
    await expect(submit).toBeDisabled();
    await artifact.fill('{"resource_changes":[]}');
    await form.getByRole("button", { name: "Inspect artifact locally", exact: true }).click();
    await form.getByRole("checkbox", { name: /I reviewed this artifact/ }).check();
    const request = page.waitForRequest((item) => item.url().includes("/changes/assess") && item.method() === "POST");
    await submit.click();
    expect((await request).postDataJSON()).toEqual({ source: "terraform_plan", payload: { resource_changes: [] }, change_id: "" });
    const recommendation = page.getByRole("region", { name: "Recommendation", exact: true });
    await expect(recommendation).toBeVisible();
    await expect(recommendation.getByText("Validate traffic before deployment.", { exact: true })).toBeVisible();
    await expect(recommendation.getByText("Network Owner", { exact: true })).toBeVisible();
    const unknowns = page.getByRole("region", { name: "Confidence and unknowns", exact: true });
    await expect(unknowns.getByText("Current traffic has not been observed.", { exact: true })).toBeVisible();
    await expect(unknowns.getByText(/2 discovered resource/)).toBeVisible();
    expect(await unknowns.evaluate((element) =>
      Boolean(element.compareDocumentPosition(document.getElementById("change-evidence")!) & Node.DOCUMENT_POSITION_FOLLOWING),
    )).toBe(true);
    await expect(page.getByText("Predicted dependencies, not confirmed impact. Traversal is incomplete.", { exact: true })).toBeVisible();
    await expect(page.getByRole("img", { name: "Blast radius graph of impacted resources", exact: true })).toBeVisible();
    const evidence = page.getByRole("region", { name: "Risk evidence", exact: true });
    await expect(evidence.locator("tbody tr")).toHaveCount(20);
    await evidence.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(evidence.locator("tbody tr")).toHaveCount(3);
    await evidence.getByRole("combobox", { name: "Filter by Factor", exact: true }).selectOption("network_factor_3");
    await expect(evidence.locator("tbody tr")).toHaveCount(1);
    await evidence.getByRole("button", { name: "Clear filters", exact: true }).click();
    const history = page.getByRole("region", { name: "Recent assessments", exact: true });
    const disclosure = history.getByText("Browse recent assessments", { exact: true });
    await expect(disclosure.locator("..")).not.toHaveAttribute("open");
    await disclosure.focus();
    await disclosure.press("Enter");
    await expect(history.locator("tbody tr")).toHaveCount(20);
    await history.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(history.locator("tbody tr")).toHaveCount(3);
    expect(await history.evaluate((element) =>
      Boolean(element.compareDocumentPosition(document.querySelector(".copilot-insights")!) & Node.DOCUMENT_POSITION_FOLLOWING),
    )).toBe(true);
    await assertNavigation(page);
    await assertLayout(page, width);
    if (width === 375 || width === 1440) {
      await recommendation.screenshot({ path: testInfo.outputPath(`predeploy-recommendation-${width}.png`) });
      await form.screenshot({ path: testInfo.outputPath(`predeploy-form-${width}.png`) });
    }
  });
}

test("Changes keeps unavailable records distinct from an empty observation stream", async ({ page }) => {
  await mockChanges(page, ["/incidents"]);
  await page.goto("/changes");
  await expect(page.getByRole("heading", { name: "Incident timeline associations unavailable", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "No correlated changes", exact: true })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Incident timeline associations", exact: true })).toBeVisible();
});

test("Changes retains a named empty stream and proposal entry point", async ({ page }) => {
  await mockChanges(page, [], true);
  await page.goto("/changes");
  await expect(page.getByRole("heading", { name: "No change associations in the loaded report", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Assess a proposed change", exact: true })).toBeVisible();
  await expect(page.locator(".copilot-insights")).toHaveCount(1);
});

test("Predeploy keeps independent catalog/history errors outside disclosures", async ({ page }) => {
  await mockChanges(page, ["/changes/assessment-sources", "/changes/assessments"]);
  await page.goto("/changes/predeploy");
  await expect(page.getByRole("heading", { name: "Change source catalog is unavailable", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Assessment history is unavailable", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry change sources", exact: true })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Change source", exact: true })).toHaveValue("terraform_plan");
  await expect(page.getByText("Browse recent assessments", { exact: true })).toHaveCount(0);
});

test("Changes keeps seven-page navigation and complete labels bounded at 320px", async ({ page }) => {
  await mockChanges(page);
  await page.route("**/api/v1/incidents**", (route) => route.fulfill({ json: envelope(buildChangeReport(140)) }));
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto("/changes");
  const warningBanner = page.locator(".dev-auth-warning");
  await expect(warningBanner).toContainText("Do not use this configuration in production.");
  await expect(warningBanner).toHaveCSS("white-space", "normal");
  const wrapperWidths = await page.locator(".operational-page").evaluate((workspace) => {
    const widths = [];
    for (let element: Element | null = workspace; element; element = element.parentElement) {
      widths.push({ className: String(element.className), client: element.clientWidth, scroll: element.scrollWidth });
    }
    return widths;
  });
  for (const wrapper of wrapperWidths) {
    expect(wrapper.scroll, wrapper.className).toBeLessThanOrEqual(wrapper.client + 1);
  }
  const stream = page.getByRole("region", { name: "Incident timeline associations", exact: true });
  await expect(stream.locator(".table-footer-page")).toHaveCount(7);
  await stream.getByRole("button", { name: "Page 7", exact: true }).click();
  await expect(stream.getByText("Observed payments change 139", { exact: true })).toBeVisible();
  await expect(stream.getByRole("button", { name: "Next page", exact: true })).toBeDisabled();
  await assertLayout(page, 320);
});
