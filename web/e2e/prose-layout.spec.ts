import { test, expect } from "@playwright/test";
import path from "node:path";
import { expectFullWidthProse } from "./layout-density";

const explanation = "Review the authoritative evidence and its scope before deciding what to do next. ";
const surfaces = [
  '<section><p data-prose>TEXT</p><ul data-prose><li>TEXT</li></ul><p>TEXT</p><ol data-prose><li>TEXT</li></ol></section>',
  '<div class="page-header"><div class="page-header-copy"><h1>Operational scope</h1><p data-prose>TEXT</p></div><button class="button">Review</button></div>',
  '<div class="command-center-copy"><h2 data-prose>TEXT</h2><p data-prose>TEXT</p></div>',
  '<div class="state-panel"><span class="state-symbol">?</span><h2>Not yet available</h2><p data-prose>TEXT</p></div>',
  '<div class="state-panel state-error"><span class="state-symbol">!</span><h2>Source unavailable</h2><p data-prose>TEXT</p></div>',
  '<div class="source-recovery-actions"><p data-prose>TEXT</p><button class="button">Retry source</button></div>',
  '<div class="flow-verdict"><p data-prose>TEXT</p></div>',
  '<div class="copilot-welcome"><h2>Operations Copilot</h2><p data-prose>Short welcome.</p></div>',
  '<div class="remediation-handoff-copy"><p data-prose>TEXT</p></div>',
  '<div class="compliance-review-heading"><h2>Review context</h2><p data-prose>TEXT</p></div>',
].map(markup => markup.replaceAll("TEXT", explanation.repeat(4)));

for (const width of [375, 1912, 2560]) {
  test(`Narrative sections fill their allocated width at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1080 });
    await page.setContent(`<main class="page-container">${surfaces.join("")}</main>`);
    await page.addStyleTag({ path: path.resolve("src/app/globals.css") });
    const paragraphs = page.locator("[data-prose]");
    await expect(paragraphs).toHaveCount(13);
    for (const paragraph of await paragraphs.all()) {
      const geometry = await paragraph.evaluate(element => {
        const parent = element.parentElement!;
        const style = getComputedStyle(parent);
        const available = parent.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
        const iconTrack = parent.classList.contains("state-error") ? 52 : 0;
        return { width: element.getBoundingClientRect().width, available: available - iconTrack };
      });
      expect(geometry.width).toBeCloseTo(geometry.available, 0);
      await expect(paragraph).toHaveCSS("max-inline-size", "none");
    }
    await expectFullWidthProse(page.locator(".page-header p, .copilot-welcome > p"));
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const header = page.locator(".page-header-copy");
    await expect(header).toHaveCSS("max-width", "none");
  });
}
