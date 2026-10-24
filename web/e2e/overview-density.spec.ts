import { expect, test, type Page } from "@playwright/test";
import { expectContentSized } from "./layout-density";

const observation = (index: number) => ({
  observation_id: `${index}1111111-1111-4111-8111-111111111111`,
  captured_at: `2026-10-${15 + index}T06:00:00Z`,
  formula_version: "overview-v1",
  critical_situations: index, exposed_findings: 3 - index, network_gaps: 0,
  sources: [],
});

async function mockOverview(page: Page, count: number, unavailable = false) {
  const captures: unknown[] = [];
  await page.route("**/api/v1/**", route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const envelope = (data: unknown) => ({ data, evidence: [], warnings: [], scope: {}, knowledge_version: "density-test" });
    if (path === "/overview/history") {
      if (route.request().method() === "POST") {
        captures.push(route.request().postDataJSON());
        return route.fulfill({ status: 409, json: { error: { code: "conflict", message: "History changed; reload" } } });
      }
      if (unavailable) return route.fulfill({ status: 503, json: { error: { code: "unavailable", message: "History storage unavailable" } } });
      return route.fulfill({ json: envelope({
        schema_version: 1, actor: "reader", scope: {}, revision: count,
        observations: Array.from({ length: count }, (_, index) => observation(index)),
      }) });
    }
    const data: Record<string, unknown> = {
      "/subscription-connections": [],
      "/situations": [],
      "/network/summary": { gap_count: 0, rule_finding_count: 0 },
      "/vulnerabilities/summary": { internet_exposed_count: 0, reachable_server_count: 0 },
    };
    return path in data
      ? route.fulfill({ json: envelope(data[path]) })
      : route.fulfill({ status: 503, json: { detail: `Unmocked source: ${path}` } });
  });
  return captures;
}

for (const width of [2560, 1912, 1440, 820, 768, 375, 320]) {
  for (const count of [0, 2]) {
    test(`Home ${count} retained observations stay compact and readable at ${width}px`, async ({ page }, info) => {
      const captures = await mockOverview(page, count);
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      const workspace = page.getByRole("region", { name: "Retained Overview observations", exact: true });
      await expect(workspace.getByText(`History revision ${count};`, { exact: false })).toBeVisible();
      const guidance = workspace.getByText("Retention and source limitations", { exact: true });
      const copy = workspace.getByText(/Private to your principal/);
      await expect(copy).toBeHidden();
      await expect(workspace.getByRole("button", { name: "Capture server observation", exact: true })).toBeEnabled();
      if (count === 0) {
        await expect(workspace.getByRole("table")).toHaveCount(0);
        expect((await workspace.boundingBox())!.height).toBeLessThanOrEqual(width >= 768 ? 320 : 580);
      } else {
        const charts = workspace.getByRole("group", { name: "Retained count comparison charts" });
        await expect(charts.getByRole("list")).toHaveCount(3);
        await expect(workspace.getByRole("row", { name: "Loaded P1 situations 0 1 +1" })).toBeVisible();
        await expect(workspace.getByText(/not a continuous trend/)).toBeVisible();
        await expect(workspace.getByRole("combobox", { name: "Earlier observation" })).toHaveValue(observation(0).observation_id);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
      await expectContentSized(page.locator(".dashboard-grid > .card"));
      const score = page.getByRole("region", { name: "Overview score and evidence", exact: true });
      const explanations = score.locator(".evidence-explanation-grid > div");
      const left = (await explanations.nth(0).boundingBox())!;
      const right = (await explanations.nth(1).boundingBox())!;
      const grid = (await score.locator(".evidence-explanation-grid").boundingBox())!;
      if (width >= 1200) {
        expect(Math.abs(left.y - right.y)).toBeLessThanOrEqual(1);
        expect(right.x).toBeGreaterThanOrEqual(left.x + left.width + 24);
        expect(Math.abs(left.width - right.width)).toBeLessThanOrEqual(1);
        expect(right.x + right.width).toBeGreaterThanOrEqual(grid.x + grid.width - 1);
      } else {
        expect(right.y).toBeGreaterThanOrEqual(left.y + left.height + 20);
        expect(Math.abs(left.x - right.x)).toBeLessThanOrEqual(1);
      }
      for (const table of await score.locator(".data-table-wrap").all()) {
        expect(Math.abs((await table.boundingBox())!.width - grid.width)).toBeLessThanOrEqual(1);
      }
      await expect(score.getByText(/Synchronization does not prove Fabric publication/)).toBeVisible();
      await expect(score.getByText(/Connection readiness does not contribute/)).toBeVisible();
      if (count === 0) await score.screenshot({ path: info.outputPath(`home-score-evidence-${width}.png`), style: ".shell-topbar { visibility: hidden; }" });
      await workspace.screenshot({ path: info.outputPath(`home-${count}-${width}.png`) });
      await guidance.focus();
      await guidance.press("Enter");
      await expect(copy).toBeVisible();
      await expect(copy).toContainText("All source reads must succeed or no observation is saved.");
      await guidance.press("Enter");
      await expect(copy).toBeHidden();
      expect(captures).toEqual([]);
    });
  }
}

test("Home history failures and capture conflicts stay visible without claiming success", async ({ page }) => {
  const captures = await mockOverview(page, 2);
  await page.goto("/");
  const workspace = page.getByRole("region", { name: "Retained Overview observations", exact: true });
  await expect(workspace.getByText(/History revision 2/)).toBeVisible();
  await workspace.getByRole("button", { name: "Capture server observation", exact: true }).click();
  await expect(workspace.getByRole("alert")).toContainText("History changed; reload");
  await expect(workspace.getByRole("table")).toBeVisible();
  await expect(workspace.getByText(/Server observation retained/)).toHaveCount(0);
  expect(captures).toEqual([{ expected_revision: 2 }]);
});

test("Home unavailable history keeps recovery actionable without an invented baseline", async ({ page }) => {
  await mockOverview(page, 0, true);
  await page.goto("/");
  const workspace = page.getByRole("region", { name: "Retained Overview observations", exact: true });
  await expect(workspace.getByRole("alert")).toContainText("History storage unavailable");
  await expect(workspace.getByRole("button", { name: "Capture server observation", exact: true })).toBeDisabled();
  await expect(workspace.getByRole("button", { name: "Reload observations", exact: true })).toBeEnabled();
  await expect(workspace.getByRole("group", { name: "Retained count comparison charts" })).toHaveCount(0);
});
