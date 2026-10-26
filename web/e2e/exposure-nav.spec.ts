import { expect, test } from "@playwright/test";

for (const width of [320, 375, 768, 820, 1912, 2560]) {
  test(`Exposure reveals the active route link at ${width}px without moving focus`, async ({ page }, testInfo) => {
    await page.route("**/api/v1/**", route =>
      route.fulfill({ status: 503, json: { detail: "Unavailable fixture source" } }));
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/exposure/patch-priorities");
    const nav = page.getByRole("navigation", { name: "Exposure views" });
    const active = nav.getByRole("link", { name: "Patch priorities", exact: true });
    await expect(active).toHaveAttribute("aria-current", "page");
    await expect.poll(async () => active.evaluate(element => {
      const parent = element.parentElement!;
      const rect = element.getBoundingClientRect();
      const container = parent.getBoundingClientRect();
      return rect.left >= container.left + parent.clientLeft - 1
        && rect.right <= container.left + parent.clientLeft + parent.clientWidth + 1;
    })).toBe(true);
    await expect(active).not.toBeFocused();
    if (width === 375 || width === 1912) {
      await page.screenshot({ path: testInfo.outputPath(`exposure-nav-${width}.png`) });
    }
    const target = active;
    await target.focus();
    await expect(target).toBeFocused();
    await page.setViewportSize({ width: 1912, height: 900 });
    await page.setViewportSize({ width: 375, height: 900 });
    await expect.poll(async () => active.evaluate(element => {
      const rect = element.getBoundingClientRect();
      const parent = element.parentElement!;
      const container = parent.getBoundingClientRect();
      return rect.right <= container.left + parent.clientLeft + parent.clientWidth + 1;
    })).toBe(true);
    await expect(target).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
  });
}
