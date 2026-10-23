import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const styles = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");
const explanation = "Review available measurements before making an operational decision. Missing observations remain unknown, not healthy or zero.";

for (const width of [375, 1440, 1912, 2560]) {
  for (const container of ["page-container", "page-shell"]) {
    test(`${container} uses available operational space at ${width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.setContent(`
        <div class="shell-main">
          <main class="${container} inventory-page">
            <section class="card">
              <header class="card-header"><div><h2>Source coverage</h2><p>${explanation}</p></div></header>
              <div class="card-body">
                <div class="state-panel state-partial">
                  <div class="state-symbol" aria-hidden="true">!</div>
                  <h2>Some metrics are unavailable</h2><p>${explanation}</p>
                </div>
              </div>
            </section>
            <section id="inventory-narrative" class="detail-panel">
              <h2>Inventory risk narrative</h2>
              <div class="narrative-body">
                <div class="narrative-section narrative-summary"><h3>Summary</h3><p>${`${explanation} `.repeat(4)}</p></div>
                <div class="narrative-section"><h3>Deterministic facts</h3><dl class="narrative-fact-grid"><div><dt>Machines</dt><dd>5</dd></div></dl></div>
                <div class="narrative-section"><h3>Sources</h3><p>Returned inventory</p></div>
                <div class="narrative-section narrative-warnings"><h3>Warnings</h3><p>Some measurements are unavailable.</p></div>
              </div>
            </section>
          </main>
        </div>`);
      await page.addStyleTag({ content: styles });

      const bounds = await page.locator("main").boundingBox();
      const shell = await page.locator(".shell-main").evaluate(element => {
        const style = getComputedStyle(element);
        return element.clientWidth - Number.parseFloat(style.paddingLeft);
      });
      expect(bounds!.width).toBeCloseTo(Math.min(shell, 1920), 0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);

      const header = page.locator(".card-header > div");
      const headerText = page.locator(".card-header p");
      const headerBox = await header.boundingBox();
      const textBox = await headerText.boundingBox();
      expect(textBox!.width).toBeCloseTo(headerBox!.width, 0);
      const statusText = page.locator(".state-panel p");
      expect(await statusText.evaluate(element => getComputedStyle(element).maxInlineSize)).toBe("none");

      const summary = await page.locator(".narrative-summary").boundingBox();
      const facts = await page.locator(".narrative-section").nth(1).boundingBox();
      const body = await page.locator(".narrative-body").boundingBox();
      if (body!.width >= 960) {
        expect(facts!.y).toBeCloseTo(summary!.y, 0);
        expect(facts!.x).toBeGreaterThan(summary!.x + summary!.width);
        expect(summary!.width).toBeLessThanOrEqual(900);
      } else {
        expect(facts!.y).toBeGreaterThan(summary!.y);
      }
      const proseLimit = await page.locator(".narrative-summary p").evaluate(element =>
        getComputedStyle(element).maxInlineSize,
      );
      expect(proseLimit).not.toBe("none");
      expect(Number.parseFloat(proseLimit)).toBeLessThan(800);
      await page.screenshot({ path: testInfo.outputPath(`${container}-${width}.png`), fullPage: true });
    });
  }
}
