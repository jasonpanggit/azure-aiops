import { expect, test, type Locator, type Page } from "@playwright/test";
import { buildAgentCatalog, buildAgentLedger, buildCanonicalReply, buildSearchRecords } from "../src/test/assistance-fixtures";
import { expectContentSized } from "./layout-density";

const envelope = (data: unknown) => ({
  data, scope: {}, knowledge_version: "assistance-layout", evidence: [],
  warnings: ["Review authorized source coverage before acting."],
});

async function mockSources(page: Page, options: {
  catalogUnavailable?: boolean; decisionUnavailable?: boolean; search?: "empty" | "unsupported" | "unavailable";
} = {}) {
  let ledger = buildAgentLedger();
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    const unavailable = (message: string) => route.fulfill({
      status: 503, json: { error: { code: "upstream_unavailable", message } },
    });
    if (path === "/agents/catalog" && options.catalogUnavailable) return unavailable("Manifest source unavailable.");
    if (path.endsWith("/actions")) {
      if (options.decisionUnavailable) return unavailable("Decision source unavailable.");
      const body: { action: string; payload: Record<string, unknown> } = request.postDataJSON();
      ledger = { ...ledger, decisions: [...ledger.decisions, { at: "2026-09-20T12:01:00Z", ...body }] };
      return route.fulfill({ json: envelope(ledger) });
    }
    if (path === "/search") {
      if (options.search === "unavailable") return unavailable("Search source unavailable.");
      if (options.search === "unsupported") return route.fulfill({
        status: 422, json: { error: { code: "validation_error", message: "Unsupported search intent." } },
      });
      const records = buildSearchRecords(options.search === "empty" ? 0 : 28);
      const offset = Number(new URL(request.url()).searchParams.get("offset") ?? 0);
      const all = records.results ?? [];
      return route.fulfill({ json: {
        ...envelope({ ...records, results: all.slice(offset, offset + 25), count: all.length, represented_count: all.length }),
        pagination: { offset, limit: 25, total: all.length, next_offset: offset + 25 < all.length ? offset + 25 : null },
      } });
    }
    const data: Record<string, unknown> = {
      "/subscription-connections": [],
      "/search/capabilities": {
        live: { state: "configured", can_query: true, phrases: ["resources missing ownership"], prerequisite: "Active connection required." },
        semantic: { state: "deferred", can_query: false, phrases: ["production applications"], prerequisite: "Published semantic snapshot required." },
        identity: { state: "configured", prerequisite: "Exact principal identifier required." },
      },
      "/agents/catalog": { agents: buildAgentCatalog() },
      "/agents/investigations": ledger,
      "/copilot/investigate": buildCanonicalReply(),
    };
    if (path === "/copilot/investigate") {
      return route.fulfill({ json: envelope({ ...buildCanonicalReply(), request_key: request.postDataJSON().request_key }) });
    }
    return path in data ? route.fulfill({ json: envelope(data[path]) }) : unavailable(`Unmocked source: ${path}`);
  });
}

async function assertBounds(page: Page, width: number) {
  await expect(async () => {
    const problems = await page.locator(".operational-page").evaluate((workspace) => {
      const overflow = Array.from(workspace.querySelectorAll("*")).flatMap((element) => {
        const scroller = element.closest(".copilot-tool-output, .agent-ledger-output, .search-raw-data");
        if (scroller && scroller !== element) return [];
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && (rect.left < -1 || rect.right > innerWidth + 1)
          ? [`${element.tagName}.${String(element.className)}: ${rect.left}, ${rect.right}`] : [];
      });
      for (let element: Element | null = workspace; element; element = element.parentElement) {
        if (element.scrollWidth > element.clientWidth + 1 || element.scrollLeft !== 0) {
          overflow.push(`${element.tagName}: ${element.scrollWidth}/${element.clientWidth}, scroll ${element.scrollLeft}`);
        }
      }
      return overflow;
    });
    expect(problems).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
  }).toPass({ timeout: 5000 });
}

async function assertScroll(region: Locator, maxHeight: number) {
  await expect(region).toBeVisible();
  expect((await region.boundingBox())!.height).toBeLessThanOrEqual(maxHeight + 0.01);
  expect(await region.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  await region.focus();
  const scrollEnd = region.evaluate((element) => new Promise<number>((resolve) => {
    element.addEventListener("scrollend", () => resolve(element.scrollTop), { once: true });
  }));
  await region.press("ArrowDown");
  expect(await scrollEnd).toBeGreaterThan(0);
}

async function assertNavigation(page: Page, label: string) {
  const links = page.getByRole("navigation", { name: label, exact: true }).getByRole("link");
  for (const link of await links.all()) {
    await expect(page.locator((await link.getAttribute("href"))!)).toHaveCount(1);
  }
  await links.last().focus();
  await links.last().press("Enter");
  await expect(page.locator((await links.last().getAttribute("href"))!)).toBeInViewport();
}

for (const width of [2560, 1912, 1440, 820, 768, 375, 320]) {
  test(`Copilot keeps the composer, evidence and disclosed output usable at ${width}px`, async ({ page }, testInfo) => {
    await mockSources(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/copilot");
    const form = page.getByRole("form", { name: "Ask Operations Copilot" });
    const ask = form.getByRole("button", { name: "Ask Copilot", exact: true });
    const prompt = page.locator(".copilot-prompts button").first();
    await expect(prompt).toHaveCSS("background-image", "none");
    await expect(prompt).toHaveCSS("background-color", "rgb(15, 108, 189)");
    await expect(ask).toHaveCSS("background-image", "none");
    await expect(ask).toHaveCSS("background-color", "rgb(15, 108, 189)");
    const input = form.getByRole("textbox", { name: "Copilot question", exact: true });
    expect((await input.boundingBox())!.width).toBeGreaterThanOrEqual(100);
    if (width <= 820) {
      await expect(form).toHaveCSS("position", "static");
      const prompts = (await page.locator(".copilot-prompts").boundingBox())!;
      const composer = (await form.boundingBox())!;
      expect(composer.y).toBeGreaterThanOrEqual(prompts.y + prompts.height);
    } else {
      await expect(form).toHaveCSS("position", "fixed");
    }
    await input.fill("Review Payments");
    await input.press("Shift+Enter");
    await expect(input).toHaveValue("Review Payments\n");
    const request = page.waitForRequest((item) => new URL(item.url()).pathname === "/api/v1/copilot/investigate");
    await input.press("Enter");
    expect((await request).postDataJSON()).toEqual({
      question: "Review Payments", session_id: "aiops-root-copilot", tool: "", tool_arguments: {},
      request_key: expect.stringMatching(/^req-/),
    });
    await expect(page.getByLabel("Copilot degradation")).toHaveText("Specialist evidence is shown; narration is unavailable.");
    await expect(page.getByLabel("Copilot uncertainty")).toContainText("coverage is incomplete");
    await expect(page.getByLabel("Copilot citations")).toContainText("Azure Resource Graph");
    await expect(page.getByText("Inventory evidence is stale; validate current state.", { exact: true })).toBeVisible();
    await expect(page.getByText("The vulnerability provider is unavailable; absence of exposure is not established.", { exact: true })).toBeVisible();
    await expect(page.locator(".copilot-tool-output")).toBeHidden();
    await page.getByText("Inspect tool output", { exact: true }).click();
    await assertScroll(page.getByRole("region", { name: "Output from inventory_resources" }), 480);
    await assertNavigation(page, "Copilot sections");
    await expect(page.getByRole("complementary", { name: "Trust boundary", exact: true })).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    const trust = (await page.locator("#copilot-trust").boundingBox())!;
    const composer = (await form.boundingBox())!;
    const lastTurn = (await page.locator(".copilot-turn").last().boundingBox())!;
    expect(lastTurn.y + lastTurn.height).toBeLessThanOrEqual(composer.y);
    if (width <= 820) {
      expect(trust.y).toBeGreaterThanOrEqual(composer.y + composer.height);
      await form.scrollIntoViewIfNeeded();
      expect((await form.boundingBox())!.y + composer.height).toBeLessThanOrEqual(900);
    } else {
      expect(composer.y + composer.height).toBeLessThanOrEqual(900);
      expect(trust.y + trust.height).toBeLessThanOrEqual(composer.y);
    }
    await expectContentSized(page.locator("#copilot-trust"));
    await assertBounds(page, width);
    if (width === 375) {
      await page.screenshot({ path: testInfo.outputPath("ui-copilot-trust-375.png") });
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: testInfo.outputPath("ui-copilot-375.png"), fullPage: true });
    }
  });

  test(`Search keeps authorized links, paging and provenance readable at ${width}px`, async ({ page }, testInfo) => {
    await mockSources(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/search?q=resources%20missing%20ownership");
    await expect(page.getByRole("form", { name: "Find authorized records", exact: true })).toBeVisible();
    await expect(page.locator(".search-suggestions button").first()).toBeVisible();
    for (const suggestion of await page.locator(".search-suggestions button").all()) {
      await expect(suggestion).toHaveClass(/button button-secondary/);
      await expect(suggestion).toHaveCSS("min-height", width <= 820 ? "44px" : "40px");
    }
    const records = page.getByRole("region", { name: "Authorized records", exact: true });
    await expect(records.getByRole("article")).toHaveCount(25);
    await expect(page.getByText(/The source result is truncated/)).toBeVisible();
    await expect(page.getByRole("button", { name: /Copilot/ })).toHaveCount(0);
    await expect(records.getByRole("link", { name: /Open service/ }).first()).toHaveAttribute("href", "/services/Payments%20API");
    await expect(records.getByRole("link", { name: /Open situation/ }).first()).toHaveAttribute("href", "/situations/Incident-1");
    await expect(records.getByRole("link", { name: /Open exposure/ }).first()).toHaveAttribute("href", "/exposure/cves/CVE-2");
    await expect(records.getByRole("link", { name: /Open authorized context/ }).first()).toHaveAttribute("href", "/investigate?type=Resource&value=Resource-3");
    const first = records.getByRole("article").first();
    expect((await first.boundingBox())!.width).toBeGreaterThanOrEqual(240);
    expect((await first.locator("dd").first().boundingBox())!.width).toBeGreaterThanOrEqual(100);
    await expect(first.getByText("stale", { exact: true })).toBeVisible();
    await expect(first.locator(".search-result-scope")).toHaveCSS("white-space", "normal");
    await first.getByText("View raw structured data", { exact: true }).click();
    await assertScroll(first.getByRole("region", { name: /^Raw data for / }), 360);
    if (width === 375) await first.screenshot({ path: testInfo.outputPath("ui-search-record-375.png") });
    await records.getByRole("button", { name: "Next results", exact: true }).click();
    await expect(records.getByRole("article")).toHaveCount(3);
    await page.getByRole("textbox", { name: "Operational search intent" }).fill("servers with failed patches");
    await page.getByRole("button", { name: "Find authorized records", exact: true }).click();
    await expect(records.getByRole("article")).toHaveCount(25);
    await expect(page.getByRole("textbox", { name: "Operational search intent" })).toHaveCSS("min-height", width <= 820 ? "44px" : "40px");
    await assertNavigation(page, "Search sections");
    await assertBounds(page, width);
    if (width === 375) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: testInfo.outputPath("ui-search-375.png") });
    }
  });

  test(`Agents keeps review before decisions and ledger output bounded at ${width}px`, async ({ page }, testInfo) => {
    await mockSources(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/agents");
    const launch = page.getByRole("button", { name: "Run deterministic investigation", exact: true });
    await expect(launch).toHaveCSS("background-image", "none");
    await expect(launch).toHaveCSS("background-color", "rgb(15, 108, 189)");
    await expect(page.getByLabel("Available specialized agents")).toContainText("Foundry available - inactive");
    await expect(page.getByLabel("Available specialized agents")).toContainText("Foundry unavailable");
    await launch.click();
    const decisions = page.getByRole("region", { name: "Human-in-the-loop controls", exact: true });
    await expect(decisions).toBeVisible();
    await expect(page.getByRole("region", { name: "Evidence reconciliation", exact: true })).toContainText("Provider records disagree");
    await expect(page.getByRole("region", { name: "Deterministic synthesis", exact: true })).toContainText("Current vulnerability coverage remains unknown.");
    const sectionIds = await page.locator(".workspace-grid > section").evaluateAll((sections) => sections.map((section) => section.id));
    expect(sectionIds).toEqual(["agent-reconciliation", "agent-synthesis", "agent-decisions", "agent-activity", "agent-evaluation", "agent-ledger"]);
    await expectContentSized(page.locator(".workspace-grid > section"));
    expect(await page.getByRole("navigation", { name: "Agent investigation sections" }).getByRole("link")
      .evaluateAll(links => links.map(link => link.getAttribute("href")))).toEqual([
      "#agent-objective", ...sectionIds.map(id => `#${id}`),
    ]);
    const owner = decisions.getByRole("textbox", { name: "Owner", exact: true });
    await expect(owner).toHaveCSS("min-height", width <= 820 ? "44px" : "40px");
    await owner.fill("Payments Ops");
    const assignment = page.waitForRequest((item) => item.url().endsWith("/mai-layout/actions"));
    await decisions.getByRole("button", { name: "Assign owner", exact: true }).click();
    expect((await assignment).postDataJSON()).toEqual({ action: "assign_owner", payload: { owner: "Payments Ops" } });
    const approval = page.waitForRequest((item) => item.url().endsWith("/mai-layout/actions"));
    const approve = decisions.getByRole("button", { name: "Approve plan", exact: true });
    await expect(approve).toBeEnabled();
    await expect(approve).toHaveCSS("background-image", "none");
    await expect(approve).toHaveCSS("background-color", "rgb(15, 108, 189)");
    await approve.click();
    expect((await approval).postDataJSON()).toEqual({
      action: "approve_plan", payload: { approved_by: "Payments Ops", guardrail: "governed handoff only" },
    });
    await expect(page.getByRole("button", { name: /execute|apply remediation|run remediation/i })).toHaveCount(0);
    await assertScroll(page.getByRole("region", { name: "Complete shared task ledger" }), 480);
    await assertNavigation(page, "Agent investigation sections");
    await assertBounds(page, width);
    if (width === 375) {
      await decisions.scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath("ui-agents-decisions-375.png") });
    }
  });
}

for (const state of ["empty", "unsupported", "unavailable"] as const) {
  test(`Search distinguishes ${state} from a successful populated result`, async ({ page }) => {
    await mockSources(page, { search: state });
    await page.goto("/search?q=resources%20missing%20ownership");
    await expect(page.getByText({
      empty: "No authorized records found", unsupported: "Unsupported search intent", unavailable: "Search is unavailable",
    }[state], { exact: true })).toBeVisible();
    await expect(page.locator(".search-result-card")).toHaveCount(0);
  });
}

test("Agent catalog failure remains independent and recoverable", async ({ page }) => {
  await mockSources(page, { catalogUnavailable: true });
  await page.goto("/agents");
  await expect(page.getByText("Manifest source unavailable.", { exact: true })).toBeVisible();
  await page.route("**/api/v1/agents/catalog", (route) => route.fulfill({ json: envelope({ agents: buildAgentCatalog() }) }));
  await page.getByRole("button", { name: "Retry agent catalog", exact: true }).click();
  await expect(page.getByLabel("Available specialized agents")).toContainText("Network Agent");
});

test("A failed agent decision preserves the evidence and does not report success", async ({ page }) => {
  await mockSources(page, { decisionUnavailable: true });
  await page.goto("/agents");
  await page.getByRole("button", { name: "Run deterministic investigation", exact: true }).click();
  await page.getByRole("textbox", { name: "Owner", exact: true }).fill("Payments Ops");
  await page.getByRole("button", { name: "Approve plan", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Investigation unavailable", exact: true })).toBeVisible();
  await expect(page.getByText("Decision source unavailable.", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Deterministic synthesis", exact: true })).toContainText(buildAgentLedger().synthesis.summary);
  await expect(page.getByRole("button", { name: "Approve plan", exact: true })).toBeEnabled();
});

test("Copilot keeps a draft and prevents a second request while evidence is pending", async ({ page }) => {
  await mockSources(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const questions: string[] = [];
  await page.route("**/api/v1/copilot/investigate", async (route) => {
    questions.push(route.request().postDataJSON().question);
    await gate;
    await route.fulfill({ json: envelope({ ...buildCanonicalReply(), request_key: route.request().postDataJSON().request_key }) });
  });
  await page.goto("/copilot");
  const input = page.getByRole("textbox", { name: "Copilot question" });
  await input.fill("Review Payments");
  await input.press("Enter");
  await expect.poll(() => questions.length).toBe(1);
  await expect(page.getByRole("button", { name: "Stop waiting for this response", exact: true })).toBeVisible();
  await input.fill("Retain my next question");
  await input.press("Enter");
  release();
  await expect(page.getByRole("button", { name: "Ask Copilot", exact: true })).toBeEnabled();
  await expect(input).toHaveValue("Retain my next question");
  expect(questions).toEqual(["Review Payments"]);
});

test("Agents disables competing decisions and investigation launches during a handoff", async ({ page }) => {
  await mockSources(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/v1/agents/investigations/mai-layout/actions", async (route) => {
    await gate;
    await route.fulfill({ json: envelope(buildAgentLedger()) });
  });
  await page.goto("/agents");
  await page.getByRole("button", { name: "Run deterministic investigation", exact: true }).click();
  await page.getByRole("textbox", { name: "Owner", exact: true }).fill("Payments Ops");
  await page.getByRole("button", { name: "Approve plan", exact: true }).click();
  for (const button of await page.locator(".agents-decision-actions button").all()) await expect(button).toBeDisabled();
  await expect(page.getByRole("button", { name: "Run deterministic investigation", exact: true })).toBeDisabled();
  release();
  await expect(page.getByRole("button", { name: "Run deterministic investigation", exact: true })).toBeEnabled();
});
