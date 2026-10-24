import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const styles = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

for (const width of [2560, 1912, 1440, 820, 768, 375, 320]) {
  test(`composes operational sections without narrow left columns at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.setContent(`<main class="page-container exposure-overview-page">
      <div class="exposure-landing-sections">
        <section class="card exposure-decision">
          <div class="card-body"><p>Prioritized findings for review, not an approval decision.</p>
            <ul class="exposure-decision-list">
              ${[1, 2, 3, 4].map(index => `<li>Review affected target ${index}</li>`).join("")}
            </ul>
          </div>
        </section>
        ${[1, 2].map(index => `<section class="card" aria-label="Exposure section ${index}">
          <div class="card-body"><h2>Exposure evidence ${index}</h2>
            <div class="metric-grid exposure-metrics">
              <div class="metric-card"><strong>12</strong><span>Loaded findings</span></div>
              <div class="metric-card"><strong>Unknown</strong><span>Unreported coverage</span></div>
            </div>
          </div></section>`).join("")}
      </div>
      <section class="card"><div class="card-body">
        <p>Read-only change observations.</p><ol class="change-observation-list">
          <li><div class="change-observation-summary">
            <h3>Reported configuration changed</h3><p>Resource: production-service</p>
          </div><details><summary>Observation identity and mapping</summary><p>Mapped evidence.</p></details>
            <details><summary>Compare reported configuration states</summary><p>Before and after.</p></details></li>
        </ol>
      </div></section>
      <section class="card connection-readiness">
        <div class="card-header"><h2>Connection readiness journey</h2></div>
        <ol class="card-body connection-readiness-stages">
          ${[1, 2].map(index => `<li>
            <div class="connection-readiness-heading"><strong>Stage ${index}</strong><span class="status-badge">unknown</span></div>
            <p>Publication coverage is not established by discovery alone.</p>
            <a href="#review" class="inline-link">Inspect evidence</a>
          </li>`).join("")}
        </ol>
      </section>
      <section class="card"><div class="card-body">
        <p>Ordinary prose retains readable line length.</p><ul><li>Prose item</li></ul>
        <a href="#review" class="button button-secondary">Open brief</a>
      </div></section>
    </main>`);
    await page.addStyleTag({ content: styles });
    const decision = page.locator(".exposure-decision-list");
    const changes = page.locator(".change-observation-list");
    for (const list of [decision, changes]) {
      const parentWidth = await list.evaluate(element => element.parentElement!.clientWidth -
        parseFloat(getComputedStyle(element.parentElement!).paddingLeft) -
        parseFloat(getComputedStyle(element.parentElement!).paddingRight));
      expect((await list.boundingBox())!.width).toBeGreaterThanOrEqual(parentWidth - 1);
    }
    await expect(page.locator(".card-body > ul:not([class])")).toHaveCSS("max-inline-size", /^[\d.]+px$/);
    const sections = page.getByRole("region", { name: /Exposure section/ });
    const left = (await sections.nth(0).boundingBox())!;
    const right = (await sections.nth(1).boundingBox())!;
    const readiness = page.locator(".connection-readiness-stages");
    const stage1 = (await readiness.locator(":scope > li").nth(0).boundingBox())!;
    const stage2 = (await readiness.locator(":scope > li").nth(1).boundingBox())!;
    const comparison = (await changes.locator("details").first().boundingBox())!;
    const summary = (await changes.locator(".change-observation-summary").boundingBox())!;
    if (width >= 1200) {
      expect(Math.abs(left.y - right.y)).toBeLessThanOrEqual(1);
      expect(right.x).toBeGreaterThan(left.x + left.width);
      expect(Math.abs(stage1.y - stage2.y)).toBeLessThanOrEqual(1);
      expect(stage2.x).toBeGreaterThan(stage1.x + stage1.width);
      expect(comparison.x).toBeGreaterThan(summary.x + summary.width);
      expect(Math.abs(comparison.y - summary.y)).toBeLessThanOrEqual(1);
    } else {
      expect(right.y).toBeGreaterThanOrEqual(left.y + left.height);
      expect(stage2.y).toBeGreaterThanOrEqual(stage1.y + stage1.height);
      expect(comparison.y).toBeGreaterThanOrEqual(summary.y + summary.height);
    }
    const stageHeader = (await readiness.locator(".connection-readiness-heading").first().boundingBox())!;
    const badge = (await readiness.locator(".status-badge").first().boundingBox())!;
    expect(badge.width).toBeLessThan(stageHeader.width / 2);
    const padding = await readiness.evaluate(element => parseFloat(getComputedStyle(element).paddingLeft));
    expect(padding).toBeGreaterThanOrEqual(16);
    const action = page.getByRole("link", { name: "Open brief", exact: true });
    expect((await action.boundingBox())!.width).toBeGreaterThan(90);
    expect((await action.boundingBox())!.height).toBeGreaterThanOrEqual(width <= 820 ? 44 : 40);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: info.outputPath(`section-composition-${width}.png`), fullPage: true });
  });
}
