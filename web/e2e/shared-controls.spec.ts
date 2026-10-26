import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const styles = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

for (const width of [375, 820, 821, 1912]) {
  test(`sizes remaining audited controls without changing adjacent surfaces at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1080 });
    await page.setContent(`
      <main class="page-container">
        <div class="change-filters">
          <label>Subscription<select><option>All subscriptions</option></select></label>
          <label>Resource group<input value="resource-group"></label>
          <label>Resource ID<input value="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1"></label>
          <label>Change type<select><option>All types</option></select></label>
          <label>From<input type="datetime-local" value="2026-10-26T00:00"></label>
          <label>To<input type="datetime-local" value="2026-10-26T01:00"></label>
        </div>
        <div class="compliance-domain-filter"><label>Domain<select><option>All domains</option></select></label></div>
        <div class="compliance-policy-grid">
          <label>Policy name<input value="Audit policy"></label>
          <label>Expiry<input type="date" value="2026-10-27"></label>
          <label>Notes<textarea>Evidence remains partial</textarea></label>
          <label><input type="checkbox" checked>Enabled</label>
        </div>
        <div class="investigation-team-controls">
          <label>Workspace identity<input class="form-control" value="wrk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"></label>
          <label>Workspace title<input class="form-control" value="Bounded investigation"></label>
        </div>
        <label class="remediation-search-field">Search fixes<input type="search" value="review"></label>
        <article class="exposure-source-item"><button class="button button-secondary" type="button">Retry source</button></article>
        <div class="service-brief"><label>Unchanged service input<input value="service"></label></div>
        <div class="remediation-approval-form"><label>Unchanged approval<input value="approval"></label></div>
      </main>
    `);
    await page.addStyleTag({ content: styles });
    const controls = page.locator([
      ".change-filters input", ".change-filters select",
      ".compliance-domain-filter select", '.compliance-policy-grid input:not([type="checkbox"])',
      ".compliance-policy-grid textarea", ".investigation-team-controls input",
      ".remediation-search-field input",
    ].join(","));
    await expect(controls).toHaveCount(13);
    for (const control of await controls.all()) {
      const value = await control.inputValue();
      await control.focus();
      await expect(control).toBeFocused();
      await expect(control).toHaveValue(value);
      const box = (await control.boundingBox())!;
      expect(box.height).toBeGreaterThanOrEqual(width <= 820 ? 44 : 40);
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
    }
    await expect(page.locator(".service-brief input")).toHaveCSS("min-height", "36px");
    const retry = page.getByRole("button", { name: "Retry source" });
    await retry.focus();
    await expect(retry).toBeFocused();
    expect((await retry.boundingBox())!.height).toBeGreaterThanOrEqual(width <= 820 ? 44 : 40);
    await expect(page.locator(".remediation-approval-form input")).toHaveCSS("min-height", "38px");
    await expect(page.getByRole("checkbox", { name: "Enabled" })).toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Enabled" })).toHaveCSS("min-height", "38px");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

test.beforeEach(async ({ page }) => {
  await page.setContent(`
    <main class="page-container">
      <header class="page-header">
        <div class="page-header-copy">
          <div class="eyebrow">Inventory</div>
          <h1>Inventory</h1>
          <p>Find authorized operating system, installed-software, and Azure resource coverage across the selected operating scope.</p>
        </div>
        <div class="page-header-actions">
          <a href="/inventory/assets" class="button">Explore assets</a>
          <a href="/inventory" class="button">Save view in URL</a>
          <button class="button button-ai copilot-drawer-trigger" aria-label="Ask Copilot about inventory">
            <span class="copilot-mark" aria-hidden="true">AI</span>
            <span class="copilot-drawer-trigger-label">Ask Copilot about inventory</span>
          </button>
        </div>
      </header>
      <article class="callout copilot-insights">
        <div class="copilot-insights-heading"><strong>Operations Copilot insights</strong></div>
        <span class="status-badge">Insight unavailable</span>
        <p>No grounded insight was produced for this scope.</p>
        <details class="copilot-insights-details">
          <summary>Evidence limitations and diagnostics</summary>
          <p>${"Unavailable evidence and incomplete source coverage require review. ".repeat(10)}</p>
        </details>
        <small>Specialists: inventory_resources, resource_health. Confidence: medium.</small>
        <div class="button-row">
          <button class="button button-secondary">Refresh insights</button>
          <button class="button button-ai">Ask a follow-up</button>
        </div>
      </article>
      <section class="card">
        <div class="card-body">
          <div class="table-column-filters">
            <div class="table-column-filter-controls">
              <label>Type<select><option>microsoft.compute/virtualmachines</option></select></label>
              <label>Reason<select><option>Public IP Address Is Not Associated With Any Resource</option></select></label>
              <label>Owner<select><option>All owners</option></select></label>
            </div>
            <div class="table-column-filter-summary"><span>2 of 2 shown</span></div>
          </div>
          <details class="twin-export-details">
            <summary>Inspect export data</summary>
            <div class="twin-export-data" role="region" aria-label="Raw twin export data" tabindex="0">
              ${Array.from({ length: 80 }, (_, index) => `<p>Export record ${index}</p>`).join("")}
            </div>
          </details>
        </div>
      </section>
      <div class="table-footer">
        <span>Showing 1-20 of 50 records</span>
        <span class="table-footer-actions">
          <select class="table-footer-size" aria-label="Rows per page"><option>20 / page</option></select>
          <button class="button" aria-label="Next page">Next</button>
        </span>
      </div>
      <div class="copilot-drawer-composer">
        <textarea aria-label="Question"></textarea>
        <button class="button button-ai">Ask</button>
      </div>
      <div class="copilot-composer">
        <textarea aria-label="Copilot question"></textarea>
        <button class="button button-ai" disabled>Ask Copilot</button>
      </div>
    </main>
  `);
  await page.addStyleTag({ content: styles });
});

test("matches Copilot launch, follow-up and composer colors to ordinary primary actions", async ({ page }) => {
  const actions = page.locator(".button-ai");
  const backgrounds = await actions.evaluateAll((elements) =>
    elements.map((element) => getComputedStyle(element).backgroundImage));

  expect(backgrounds).toHaveLength(4);
  expect(new Set(backgrounds).size).toBe(1);
  expect(backgrounds[0]).toBe("none");
  for (const action of await actions.all()) {
    await expect(action).toHaveCSS("background-color", "rgb(15, 108, 189)");
    await expect(action).toHaveCSS("color", "rgb(255, 255, 255)");
    await expect(action).toHaveCSS("box-shadow", "none");
  }
  await expect(page.getByRole("button", { name: "Refresh insights" }))
    .toHaveCSS("background-image", "none");
  await expect(page.getByRole("button", { name: "Refresh insights" }))
    .toHaveCSS("border-top-style", "solid");
  await expect(page.getByRole("button", { name: "Refresh insights" }))
    .toHaveCSS("border-radius", "4px");
  const [refresh, followUp] = await Promise.all([
    page.getByRole("button", { name: "Refresh insights" }).boundingBox(),
    page.getByRole("button", { name: "Ask a follow-up" }).boundingBox(),
  ]);
  expect(refresh).not.toBeNull();
  expect(followUp).not.toBeNull();
  expect(followUp!.x - (refresh!.x + refresh!.width)).toBeGreaterThanOrEqual(8);
});

test("keeps disabled and keyboard-focus states distinct", async ({ page }) => {
  const disabled = page.getByRole("button", { name: "Ask Copilot", exact: true });
  await expect(disabled).toBeDisabled();
  await expect(disabled).toHaveCSS("cursor", "not-allowed");
  await disabled.hover();
  await expect(disabled).toHaveCSS("filter", "none");

  const refresh = page.getByRole("button", { name: "Refresh insights" });
  await refresh.focus();
  await expect(refresh).toHaveCSS("outline-style", "solid");
  await expect(refresh).toHaveCSS("outline-width", "3px");
});

for (const width of [2560, 1912, 1440, 820, 768, 375, 320]) {
  test(`lays out the production Copilot callout classes and diagnostics at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const panel = page.locator(".callout.copilot-insights");
    await expect(panel).toHaveCSS("display", "grid");
    const heading = (await panel.locator(".copilot-insights-heading").boundingBox())!;
    const badge = (await panel.locator(".status-badge").boundingBox())!;
    const status = (await panel.getByText("No grounded insight was produced for this scope.", { exact: true }).boundingBox())!;
    expect(badge.y).toBeGreaterThanOrEqual(heading.y + heading.height);
    expect(status.y).toBeGreaterThanOrEqual(badge.y + badge.height);
    await panel.locator("summary").focus();
    await panel.locator("summary").press("Enter");
    const diagnostics = panel.locator("details p");
    await expect(diagnostics).toBeVisible();
    const diagnosticBox = (await diagnostics.boundingBox())!;
    const buttons = (await panel.locator(".button-row").boundingBox())!;
    expect(buttons.y).toBeGreaterThanOrEqual(diagnosticBox.y + diagnosticBox.height);
    for (const item of await panel.locator(":scope > *").all()) {
      const box = (await item.boundingBox())!;
      const outer = (await panel.boundingBox())!;
      expect(box.x).toBeGreaterThanOrEqual(outer.x);
      expect(box.x + box.width).toBeLessThanOrEqual(outer.x + outer.width);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });

  test(`keeps header actions readable and bounded at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const header = page.locator(".page-header");
    const links = page.locator(".page-header-actions a");
    for (const link of await links.all()) {
      const box = await link.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.height).toBe(width <= 820 ? 44 : 40);
      expect(box!.width).toBeGreaterThan(100);
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    }
    const headerBox = await header.boundingBox();
    expect(headerBox!.x + headerBox!.width).toBeLessThanOrEqual(width);
    const copilot = page.getByRole("button", { name: "Ask Copilot about inventory" });
    const box = await copilot.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(width <= 820 ? 44 : 40);
    if (width <= 640) expect(box!.width).toBe(44);
  });

  test(`contains long filter options and expanded export at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const control of await page.locator(".table-footer select,.table-footer button").all()) {
      expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(width <= 820 ? 44 : 40);
      await expect(control).toHaveCSS("font-size", "14px");
    }
    const filters = page.locator(".table-column-filters");
    const filterBox = await filters.boundingBox();
    expect(filterBox).not.toBeNull();
    for (const select of await filters.locator("select").all()) {
      const value = await select.inputValue();
      const label = await select.evaluate(element => (element as HTMLSelectElement).labels?.[0]?.textContent);
      expect(label?.trim()).toBeTruthy();
      await select.focus();
      await expect(select).toBeFocused();
      await expect(select).toHaveValue(value);
      await expect(select).toHaveCSS("box-shadow", "rgba(15, 108, 189, 0.15) 0px 0px 0px 3px");
      const box = await select.boundingBox();
      expect(box!.height).toBe(width <= 820 ? 44 : 40);
      expect(box!.x).toBeGreaterThanOrEqual(filterBox!.x);
      expect(box!.x + box!.width).toBeLessThanOrEqual(filterBox!.x + filterBox!.width);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    }
    const data = page.getByRole("region", { name: "Raw twin export data" });
    await expect(data).toBeHidden();
    await page.getByText("Inspect export data").click();
    await expect(data).toBeVisible();
    const box = await data.boundingBox();
    expect(box!.height).toBeLessThanOrEqual(480);
    expect(await data.evaluate((element) => element.scrollHeight))
      .toBeGreaterThan(box!.height);
    await data.focus();
    await page.keyboard.press("End");
    await expect.poll(() => data.evaluate((element) => element.scrollTop))
      .toBeGreaterThan(0);
  });
}
