import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const styles = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

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
      <article class="copilot-insights">
        <div class="copilot-insights-heading"><strong>Operations Copilot insights</strong></div>
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

for (const width of [1440, 820, 768, 375, 320]) {
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
      const box = await select.boundingBox();
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
