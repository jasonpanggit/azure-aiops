import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const styles = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

for (const width of [320, 375, 700, 701, 820, 1912, 2560]) {
  for (const disabled of [false, true]) {
    test(`network path action follows control height at ${width}px, disabled=${disabled}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1080 });
      await page.setContent(`
        <main class="page-container">
          <form class="flow-query-form">
            <label>Source<select class="form-control"><option>Source resource</option></select></label>
            <span class="flow-arrow" aria-hidden="true">→</span>
            <label>Destination<select class="form-control"><option>Destination resource</option></select></label>
            <label>Port<input class="form-control" value="443"></label>
            <label>Protocol<select class="form-control"><option>TCP</option></select></label>
            <button type="button" class="button button-primary" ${disabled ? "disabled" : ""}>Analyze path</button>
          </form>
          <button type="button" class="button button-secondary">Reference control</button>
        </main>`);
      await page.addStyleTag({ content: styles });
      const action = page.getByRole("button", { name: "Analyze path", exact: true });
      const reference = page.getByRole("button", { name: "Reference control" });
      const expectedHeight = await reference.evaluate(element => getComputedStyle(element).minHeight);
      await expect(action).toHaveCSS("min-height", expectedHeight);
      expect((await action.boundingBox())!.height).toBeGreaterThanOrEqual(parseFloat(expectedHeight));
      await expect(action).toHaveCSS("background-color", "rgb(15, 108, 189)");
      await expect(action).toHaveCSS("color", "rgb(255, 255, 255)");
      await expect(action).toHaveCSS("opacity", disabled ? "0.55" : "1");
      if (disabled) {
        await expect(action).toBeDisabled();
      } else {
        await action.focus();
        await expect(action).toBeFocused();
        await expect(action).toHaveCSS("outline-style", "solid");
        await action.hover();
        await expect(action).toHaveCSS("background-color", "rgb(17, 94, 163)");
      }

      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    });
  }
}

for (const width of [375, 1912]) {
  test(`real Network path form uses shared sizing at ${width}px`, async ({ page }, info) => {
    await page.route("**/api/v1/**", route => route.fulfill({
      status: 503, json: { detail: "Unavailable fixture source" },
    }));
    await page.setViewportSize({ width, height: 1080 });
    await page.goto("/network");
    const action = page.getByRole("button", { name: "Analyze path", exact: true });
    await expect(action).toBeDisabled();
    await expect(action).toHaveCSS("min-height", width === 375 ? "44px" : "40px");
    expect((await action.boundingBox())!.height).toBe(width === 375 ? 44 : 40);
    if (width === 375) {
      await expect.poll(() => page.locator(".shell-sidebar").evaluate(element => element.getBoundingClientRect().right)).toBeLessThanOrEqual(1);
    }
    await page.locator(".flow-query-form").screenshot({ path: info.outputPath(`network-form-${width}.png`) });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
