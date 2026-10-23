import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Locator } from "@playwright/test";

const styles = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");
const copy = "Review the returned observations and their evidence before making an operational decision. Missing measurements remain unknown, rather than being treated as healthy.";
const paragraphs = `<p>${copy}</p><p>${copy}</p>`;
const flowSurfaces = [
  ["card-body", "card-body"],
  ["health diagnostics", "health-resource-card"],
  ["compliance policy", "compliance-policy-explanation"],
  ["change observations", "change-observations"],
  ["network review", "network-review-context"],
  ["source recovery", "exposure-recovery"],
  ["inventory narrative", "narrative-summary"],
  ["saved views", "saved-views-body"],
  ["governance", "governance-retained"],
  ["service brief", "service-brief"],
] as const;

async function separation(first: Locator, second: Locator) {
  const [a, b] = await Promise.all([first.boundingBox(), second.boundingBox()]);
  expect(a).not.toBeNull();
  expect(b).not.toBeNull();
  return b!.y - (a!.y + a!.height);
}

for (const width of [1440, 820, 768, 375, 320]) {
  test(`keeps shared prose rhythm and compact data at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.setContent(`
      <main class="${width === 820 || width === 375 ? "page-shell" : "page-container"} inventory-page">
        <header class="page-header"><div class="page-header-copy">
          <h1>Review operational evidence</h1><p>${copy}</p>
        </div></header>
        ${flowSurfaces.map(([name, className]) => `
          <section class="card" aria-label="${name}">
            <div class="${className}"><h2>${name}</h2>
              ${className === "health-resource-card"
                ? `<details open><summary>Missing metric diagnostics</summary>${paragraphs}</details>`
                : paragraphs}
            </div>
          </section>`).join("")}
        <section class="card"><div class="card-body" data-testid="flow">
          <h2>Evidence and next checks</h2>${paragraphs}
          <h3>Source coverage</h3><p>${copy}</p>
          <ul><li>${copy}</li><li>${copy}</li></ul><p>${copy}</p>
          <details open><summary>Review diagnostics</summary>${paragraphs}</details>
        </div></section>
        <section class="card"><div class="card-body">
          <table><tbody><tr><td>${paragraphs}</td></tr></tbody></table>
          <button>${paragraphs}</button>
        </div></section>
        <aside class="copilot-drawer" style="position:static;width:auto;height:auto;transform:none">
          <div>${paragraphs}</div>
        </aside>
      </main>`);
    await page.addStyleTag({ content: styles });

    for (const [name] of flowSurfaces) {
      const ps = page.getByRole("region", { name, exact: true }).locator("p");
      expect(await separation(ps.nth(0), ps.nth(1)), name).toBeCloseTo(12, 0);
      await expect(ps.first()).toHaveCSS("line-height", "22.4px");
    }
    const flow = page.getByTestId("flow");
    const ps = flow.locator(":scope > p");
    expect(await separation(flow.locator("h2"), ps.nth(0))).toBeCloseTo(8, 0);
    expect(await separation(ps.nth(1), flow.locator("h3"))).toBeCloseTo(20, 0);
    expect(await separation(flow.locator("h3"), ps.nth(2))).toBeCloseTo(8, 0);
    expect(await separation(ps.nth(2), flow.locator("ul"))).toBeCloseTo(12, 0);
    expect(await separation(flow.locator("li").nth(0), flow.locator("li").nth(1))).toBeCloseTo(6, 0);
    expect(await separation(ps.nth(3), flow.locator("details"))).toBeCloseTo(12, 0);
    expect(await separation(flow.locator("summary"), flow.locator("details p").first())).toBeCloseTo(8, 0);
    await expect(page.locator("td p + p")).toHaveCSS("margin-top", "0px");
    await expect(page.locator("button p + p")).toHaveCSS("margin-top", "0px");
    expect(await separation(page.locator(".copilot-drawer p").nth(0), page.locator(".copilot-drawer p").nth(1))).toBeCloseTo(12, 0);
    for (const p of await page.locator("main p").all()) {
      expect(await p.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    }

    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
    if (width === 1440 || width === 375) {
      await flow.screenshot({ path: testInfo.outputPath(`text-flow-${width}.png`) });
    }
  });

  test(`does not double existing layout gaps at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.setContent(`<main class="page-container">
      ${[
        "executive-brief", "health-triage-body", "source-recovery-actions",
        "twin-history-body", "predeploy-intake", "network-history",
        "network-intents", "service-reliability-review", "saved-views-body",
      ].map(className => `<section class="${className}">${paragraphs}</section>`).join("")}
      ${["overview-history-workspace", "agents-job", "copilot-request-recovery", "situation-response-deadline",
        "remediation-rollouts", "remediation-verification-inbox", "service-reliability", "network-review-context"]
        .map(className => `<section class="${className}"><div class="card-body">${paragraphs}</div></section>`).join("")}
    </main>`);
    await page.addStyleTag({ content: styles });
    for (const second of await page.locator("p + p").all()) {
      await expect(second).toHaveCSS("margin-top", "0px");
      const gap = await second.evaluate(element => {
        const previous = element.previousElementSibling!;
        return element.getBoundingClientRect().top - previous.getBoundingClientRect().bottom;
      });
      const parentGap = await second.evaluate(element => Number.parseFloat(getComputedStyle(element.parentElement!).rowGap));
      expect(gap).toBeCloseTo(parentGap, 0);
    }
  });
}

for (const width of [1440, 375]) {
  test(`keeps published Assets text readable at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/v1/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/v1/inventory/resources") {
        return route.fulfill({ json: {
          data: {
            resources: [], facets: {}, requested_scope: {},
            query_version: "text-spacing-test", generation_id: "published-fixture",
            represented_count: 0,
            family_availability: {
              compute: { family: "compute", state: "ready", row_count: 0, logical_dataset: "compute" },
              software: { family: "software", state: "unavailable", row_count: 0, logical_dataset: "software" },
            },
          },
          scope: {}, evidence: [], warnings: [], knowledge_version: "text-spacing-test",
        } });
      }
      return route.fulfill({ status: 503, json: { detail: `No typography fixture for ${path}` } });
    });
    await page.goto("/inventory/assets");
    await expect(page.getByRole("heading", { name: "Inventory assets", exact: true })).toBeVisible();
    const facts = page.locator(".page-shell > p");
    await expect(facts).toHaveCount(4);
    for (const p of await facts.all()) {
      await expect(p).toHaveCSS("line-height", "22.4px");
    }
    const generation = facts.nth(1);
    const compute = facts.nth(2);
    const unavailable = facts.nth(3);
    expect(await separation(generation, compute)).toBeCloseTo(18, 0);
    expect(await separation(compute, unavailable)).toBeCloseTo(18, 0);
    await expect(unavailable).toContainText("unavailable");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
  });
}

test("keeps prose readable at 200 percent zoom", async ({ page }) => {
  await page.setViewportSize({ width: 820, height: 900 });
  await page.setContent(`<main class="page-container"><section class="card">
    <div class="card-body"><h2>Evidence coverage</h2>${paragraphs}
      <p>${"long-observation-identifier-".repeat(15)}</p>
      <details open><summary>More evidence</summary>${paragraphs}</details>
    </div></section></main>`);
  await page.addStyleTag({ content: styles });
  await page.evaluate(() => { document.body.style.zoom = "2"; });
  for (const p of await page.locator("p").all()) {
    expect(await p.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(821);
});
