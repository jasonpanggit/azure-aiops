import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const styles = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");
const groups = [
  {
    className: "operations-table connections-registry-table",
    headers: ["Connection", "Business context", "Health", "Sync", "Last successful sync", "Actions"],
    cells: ["Production subscription", "Business critical production payments service", "Healthy", "16356 records discovered", "26 October 2026, 12:59:01 UTC", '<button type="button">Sync now</button><button type="button">Delete</button>'],
    widths: [260, 280, 120, 180, 240, 200],
  },
  {
    className: "data-table inventory-azure-groups-table",
    headers: ["Resource type", "Provider", "SKU / tier", "Resources", "Details"],
    cells: ["Virtual machines Microsoft.Compute/virtualMachines", "Microsoft.Compute", "Standard / D4s_v5", "1", '<button type="button">View resources</button>'],
    widths: [340, 220, 180, 100, 160],
  },
  {
    className: "detail-table inventory-azure-detail-table",
    headers: ["Resource", "Resource group", "Location", "SKU / tier", "State", "Observed"],
    cells: ["production-payments-virtual-machine", "production-resource-group", "Australia East", "—", "Succeeded", "26 October 2026, 12:59:01 UTC"],
    widths: [384, 216, 144, 144, 120, 192],
  },
  {
    className: "operations-table finops-opportunities-table",
    headers: ["Scenario A", "Scenario B", "Recommendation", "Impact", "Annual saving", "Owner", "Resource"],
    cells: ['<input type="checkbox" aria-label="Scenario A">', '<input type="checkbox" aria-label="Scenario B">', "Right-size the underutilized production virtual machine.<div>Review usage and retain the recommendation evidence.</div>", "High", "AUD 1234", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", '<span title="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm">/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm</span>'],
    widths: [80, 80, 480, 100, 140, 240, 280],
  },
];

for (const width of [375, 820, 821, 1912]) {
  test(`allocates audited text and compact columns with local scrolling at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1080 });
    await page.setContent(`
      <main class="page-container">
        ${groups.map(group => `
          <section class="${group.className.includes("inventory") ? "inventory-page" : group.className.includes("finops") ? "finops-workspace" : "connections-workspace"}">
          <div class="table-scroll" tabindex="0" role="region" aria-label="${group.className}">
            <table class="${group.className}">
              <colgroup>${group.headers.map(() => "<col>").join("")}</colgroup>
              <thead><tr>${group.headers.map(header => `<th>${header}</th>`).join("")}</tr></thead>
              <tbody><tr>${group.cells.map(cell => `<td>${cell}</td>`).join("")}</tr></tbody>
            </table>
          </div></section>`).join("")}
      </main>`);
    await page.addStyleTag({ content: styles });
    for (const group of groups) {
      const table = page.locator(`.${group.className.split(" ").at(-1)}`);
      const cells = table.locator("tbody > tr > td");
      for (let index = 0; index < group.widths.length; index++) {
        expect((await cells.nth(index).boundingBox())!.width).toBeGreaterThanOrEqual(group.widths[index] - 1);
      }
      expect((await table.locator("tbody > tr").boundingBox())!.height).toBeLessThan(180);
      const scroller = table.locator("..");
      await scroller.focus();
      await expect(scroller).toBeFocused();
      if (width === 375) {
        expect(await scroller.evaluate(element => element.scrollWidth)).toBeGreaterThan(await scroller.evaluate(element => element.clientWidth));
      }
      for (const control of await table.locator("button, input").all()) {
        const text = await control.textContent();
        await control.focus();
        await expect(control).toBeFocused();
        const box = (await control.boundingBox())!;
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
        expect(await control.textContent()).toBe(text);
      }
      await scroller.evaluate(element => { element.scrollLeft = element.scrollWidth; });
      if (width === 375) {
        expect(await scroller.evaluate(element => element.scrollLeft)).toBeGreaterThan(0);
      }
    }
    await expect(page.getByRole("checkbox", { name: "Scenario A", exact: true })).not.toBeChecked();
    await expect(page.getByRole("checkbox", { name: "Scenario B", exact: true })).not.toBeChecked();
    await expect(page.getByText("Review usage and retain the recommendation evidence.")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  });
}
