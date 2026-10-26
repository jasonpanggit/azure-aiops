import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const styles = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");
const families = ["saved-views", "network-review-context", "predeploy-artifact", "predeploy-history"];

for (const width of [320, 375, 700, 701, 820, 1912, 2560]) {
  test(`column card headers use content height at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1080 });
    await page.setContent(`<main class="page-container">${families.map(name => `
      <section class="card ${name}">
        <div class="card-header">
          <div><h2>Retained evidence</h2><p>Review the current authorized scope before opening retained evidence.</p></div>
          <button class="button button-secondary">Open evidence</button>
        </div>
      </section>`).join("")}</main>`);
    await page.addStyleTag({ content: styles });
    for (const family of families) {
      const header = page.locator(`.${family} .card-header`);
      await expect(header.locator(":scope > div").first()).toHaveCSS("flex-basis", width <= 700 ? "auto" : "320px");
      const geometry = await header.evaluate(element => {
        const text = element.querySelector("p")!.getBoundingClientRect();
        const action = element.querySelector("button")!.getBoundingClientRect();
        return { gap: action.top - text.bottom, bottom: action.bottom, right: action.right };
      });
      if (width <= 700) {
        expect(geometry.gap).toBeGreaterThanOrEqual(7);
        expect(geometry.gap).toBeLessThanOrEqual(9);
      }
      expect(geometry.right).toBeLessThanOrEqual(width);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}

for (const width of [375, 1912, 2560]) {
  for (const route of ["/search", "/changes/predeploy"]) {
    test(`${route} keeps real card header content compact at ${width}px`, async ({ page }, info) => {
      await page.route("**/api/v1/**", route => route.fulfill({
        status: 503, json: { detail: "Unavailable fixture source" },
      }));
      await page.setViewportSize({ width, height: 1080 });
      await page.goto(route);
      const header = page.locator(route === "/search" ? ".saved-views .card-header" : ".predeploy-history .card-header");
      const text = header.locator(":scope > div").first();
      await expect(text).toHaveCSS("flex-basis", width <= 700 ? "auto" : "320px");
      if (width === 375) {
        expect((await text.boundingBox())!.height).toBeLessThan(200);
      }
      if (route === "/search") {
        const toggle = page.getByRole("button", { name: "Open saved views", exact: true });
        await toggle.click();
        await expect(page.getByRole("button", { name: "Close saved views", exact: true })).toHaveAttribute("aria-expanded", "true");
        await page.getByRole("button", { name: "Close saved views", exact: true }).click();
        await expect(toggle).toHaveAttribute("aria-expanded", "false");
      }
      if (width === 375 || width === 1912) {
        await header.scrollIntoViewIfNeeded();
        await header.screenshot({ path: info.outputPath(`${route === "/search" ? "search" : "predeploy"}-${width}.png`) });
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    });
  }
}
