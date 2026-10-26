import { expect, test } from "@playwright/test";

for (const width of [375, 1912]) {
  test(`bounded investigation escapes hovered cards and uses shared controls at ${width}px`, async ({ page }, info) => {
    let investigationRequests = 0;
    await page.route("**/api/v1/**", route => {
      if (new URL(route.request().url()).pathname === "/api/v1/copilot/investigations"
        && route.request().method() === "POST"
        && route.request().postDataJSON()?.hint?.tool === "incidents") investigationRequests += 1;
      return route.fulfill({ status: 503, json: { detail: "Unavailable local fixture source" } });
    });
    await page.setViewportSize({ width, height: 1080 });
    await page.goto("/changes");
    const card = page.getByRole("region", { name: "Incident and change investigation" });
    await expect(card).toBeVisible();
    const resource = card.getByLabel("Investigation resource ARM id");
    await resource.fill("/subscriptions/fixture-sub/resourceGroups/fixture-rg/providers/Microsoft.Compute/virtualMachines/fixture-vm");
    await card.getByLabel("Investigation from", { exact: true }).fill("2026-10-26T00:00:00Z");
    await card.getByLabel("Investigation through", { exact: true }).fill("2026-10-26T01:00:00Z");
    for (const input of await card.locator("input").all()) {
      await expect(input).toHaveCSS("min-height", width === 375 ? "44px" : "40px");
      expect((await input.boundingBox())!.height).toBeGreaterThanOrEqual(width === 375 ? 44 : 40);
    }
    await card.screenshot({ path: info.outputPath(`investigation-form-${width}.png`) });
    const open = card.getByRole("button", { name: "Open bounded investigation" });
    await open.hover();
    await open.click();
    await page.mouse.move(0, 0);
    const drawer = page.getByRole("dialog", { name: "Operations Copilot" });
    await expect(drawer).toBeFocused();
    await expect(drawer).toHaveCSS("opacity", "1");
    await expect(drawer).toHaveCSS("background-color", "rgb(255, 255, 255)");
    expect(await drawer.evaluate(element => element.parentElement === document.body)).toBe(true);
    const assertViewport = async () => {
      await expect.poll(async () => {
        const bounds = await drawer.boundingBox();
        return bounds && { top: Math.round(bounds.y), height: Math.round(bounds.height) };
      }).toEqual({ top: 0, height: 1080 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
    };
    await assertViewport();
    for (const starter of await drawer.locator(".copilot-prompts button").all()) {
      await expect(starter).toHaveClass(/button-ai/);
      await expect(starter).toHaveCSS("background-color", "rgb(15, 108, 189)");
      await expect(starter).toHaveCSS("color", "rgb(255, 255, 255)");
      await expect(starter).toBeInViewport();
    }
    await expect(drawer.getByRole("button", { name: "Send", exact: true })).toBeInViewport();
    await expect(drawer.getByRole("button", { name: "Send", exact: true })).toBeDisabled();
    await page.screenshot({ path: info.outputPath(`investigation-drawer-${width}.png`) });
    if (width === 1912) {
      await drawer.getByRole("button", { name: "Widen panel" }).click();
      await expect(drawer).toHaveCSS("width", "760px");
      await assertViewport();
      await page.setViewportSize({ width: 375, height: 1080 });
      await expect(drawer).toHaveCSS("width", "375px");
      await assertViewport();
    }
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await open.click();
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await expect(drawer).toHaveCount(0);
    expect(investigationRequests).toBe(0);
  });
}
