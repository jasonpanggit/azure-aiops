import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const styles = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

for (const width of [375, 820, 821, 1912]) {
  test(`keeps Identity role and breadth words readable at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1080 });
    await page.setContent(`
      <main class="page-container identity-workspace">
        <div class="table-scroll identity-principals-table" tabindex="0" role="region" aria-label="Observed principal assignments">
          <table class="operations-table identity-principals-grid">
            <colgroup><col><col><col><col><col><col></colgroup>
            <thead><tr>${["Principal", "Type", "Roles", "Widest scope", "Grant breadth", "Status"].map(text => `<th>${text}</th>`).join("")}</tr></thead>
            <tbody>
              <tr>
                <td><a href="#principal" class="table-primary-link"><span class="table-wrap resource-id-cell">69472a39-717d-47d0-85f2-45a63aacdcdc</span></a><div class="table-secondary">5 assignments</div></td>
                <td class="cell-nowrap">Service Principal</td>
                <td><div class="table-wrap">Unresolved</div></td>
                <td>Subscription<div class="table-secondary"><span class="resource-id-cell" title="/subscriptions/890c9bfc-d09c-4143-9ce5-465000000000">/subscriptions/890c9bfc-d09c-4143-9ce5-465000000000</span></div></td>
                <td>2 subscription, 1 resource group, 2 resource</td>
                <td><span>incomplete classification</span><div class="table-secondary">5 unresolved role/action records; 0 unknown change ages</div></td>
              </tr>
              <tr>
                <td><a href="#long-principal" class="table-primary-link"><span class="table-wrap resource-id-cell">${"long-principal-".repeat(12)}</span></a></td>
                <td class="cell-nowrap">Managed Identity</td>
                <td><div class="table-wrap">Reader, Storage Blob Data Contributor, User Access Administrator, ${"LongRole".repeat(12)}</div></td>
                <td>Management Group<div class="table-secondary"><span class="resource-id-cell">${"/providers/Microsoft.Management/managementGroups/".repeat(4)}</span></div></td>
                <td>12 management group, 123 subscription, 456 resource group, 789 resource</td>
                <td>privileged signal<div class="table-secondary">Classification coverage and change ages unreported</div></td>
              </tr>
            </tbody>
          </table>
        </div>
      </main>`);
    await page.addStyleTag({ content: styles });
    const region = page.getByRole("region", { name: "Observed principal assignments" });
    const cells = page.locator("tbody tr").first().locator("td");
    const minima = [340, 180, 240, 300, 240, 300];
    for (let index = 0; index < minima.length; index++) {
      expect((await cells.nth(index).boundingBox())!.width).toBeGreaterThanOrEqual(minima[index] - 1);
    }
    for (const [index, word] of [[2, "Unresolved"], [4, "subscription"]] as const) {
      const lineCount = await cells.nth(index).evaluate((element, word) => {
        const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          const start = node.textContent?.indexOf(word) ?? -1;
          if (start < 0) continue;
          const range = document.createRange();
          range.setStart(node, start);
          range.setEnd(node, start + word.length);
          return range.getClientRects().length;
        }
        return 0;
      }, word);
      expect(lineCount).toBe(1);
    }
    expect((await page.locator("tbody tr").first().boundingBox())!.height).toBeLessThan(150);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await region.focus();
    await expect(region).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath(`identity-${width}-left.png`) });
    await region.evaluate(element => { element.scrollLeft = element.scrollWidth; });
    if (width <= 821) expect(await region.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
    const statusBox = (await cells.last().boundingBox())!;
    expect(statusBox.x).toBeGreaterThanOrEqual(0);
    expect(statusBox.x + statusBox.width).toBeLessThanOrEqual(width);
    await page.screenshot({ path: testInfo.outputPath(`identity-${width}-right.png`) });
    await page.getByRole("link").first().focus();
    await expect(page.getByRole("link").first()).toBeFocused();
    expect((await page.getByRole("link").first().boundingBox())!.x).toBeGreaterThanOrEqual(0);
  });
}
