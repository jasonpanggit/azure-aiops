import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const styles = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

for (const width of [375, 820, 821, 1912]) {
  test(`keeps only visible sidebar links in keyboard order at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1080 });
    await page.setContent(`
      <button id="before">Before navigation</button>
      <aside class="shell-sidebar" aria-label="Primary navigation">
        <nav><a href="#home">Home</a><a href="#services">Services</a></nav>
      </aside>
      <button id="after">After navigation</button>
    `);
    await page.addStyleTag({ content: styles });
    const sidebar = page.locator(".shell-sidebar");
    const before = page.getByRole("button", { name: "Before navigation" });
    const after = page.getByRole("button", { name: "After navigation" });
    const home = page.getByRole("link", { name: "Home" });

    await before.focus();
    await page.keyboard.press("Tab");
    if (width <= 820) {
      await expect(after).toBeFocused();
      await expect(home).toHaveCount(0);
      await page.keyboard.press("Shift+Tab");
      await expect(before).toBeFocused();
    } else {
      await expect(home).toBeFocused();
    }

    await sidebar.evaluate(element => element.classList.add("shell-sidebar-open"));
    await before.focus();
    await page.keyboard.press("Tab");
    await expect(home).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Services" })).toBeFocused();

    await before.focus();
    await sidebar.evaluate(element => element.classList.remove("shell-sidebar-open"));
    await page.setViewportSize({ width: width <= 820 ? 1912 : 375, height: 1080 });
    await page.keyboard.press("Tab");
    if (width <= 820) await expect(home).toBeFocused();
    else {
      await expect(after).toBeFocused();
      await expect(home).toHaveCount(0);
    }
  });
}
