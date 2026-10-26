import { expect, test } from "@playwright/test";

for (const route of ["/inventory", "/connections"]) {
  for (const width of [375, 1912, 2560]) {
    test(`${route} keeps its selected tab visible from ${width}px`, async ({ page }, testInfo) => {
      await page.route("**/api/v1/**", route => route.fulfill({
        status: 503, json: { detail: "Unavailable fixture source" },
      }));
      await page.setViewportSize({ width: 1912, height: 1080 });
      await page.goto(route);
      const list = page.getByRole("tablist", {
        name: route === "/inventory" ? "Inventory views" : "Data & integrations views",
      });
      const tab = list.getByRole("tab").last();
      await tab.click();
      await page.getByRole("heading").first().click();
      const visible = () => tab.evaluate(element => {
        const container = element.parentElement!;
        const bounds = container.getBoundingClientRect();
        const rect = element.getBoundingClientRect();
        return rect.left >= bounds.left + container.clientLeft - 1
          && rect.right <= bounds.left + container.clientLeft + container.clientWidth + 1;
      });
      await page.setViewportSize({ width, height: 1080 });
      await expect.poll(visible).toBe(true);
      await expect(tab).toHaveAttribute("aria-selected", "true");
      await expect(tab).not.toBeFocused();
      if (width === 375 || width === 1912) {
        if (width === 375) {
          await page.waitForFunction(() => document.querySelector(".shell-sidebar")!.getBoundingClientRect().right <= 1);
        }
        await page.screenshot({ path: testInfo.outputPath(`${route.slice(1)}-${width}.png`) });
      }
      await page.setViewportSize({ width: 375, height: 1080 });
      await expect.poll(visible).toBe(true);
      await tab.focus();
      await page.keyboard.press("Home");
      const first = list.getByRole("tab").first();
      await expect(first).toBeFocused();
      await expect(first).toHaveAttribute("aria-selected", "true");
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    });
  }
}
