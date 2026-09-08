import { readFileSync } from "node:fs";
import {
  expect,
  test,
  type Page,
  type Response,
  type TestInfo,
} from "@playwright/test";
import {
  HANDLER_TIMING_HEADER,
  HTTP_P95_BUDGET_MS,
  LATENCY_SAMPLE_COUNT,
  SERVER_HANDLER_P95_BUDGET_MS,
  handlerDurationMs,
  latencyDistribution,
} from "../src/lib/network-topology-latency";

const liveEnabled = process.env.AIOPS_LIVE_NETWORK_E2E === "1";
const liveSessionStoragePath =
  process.env.PLAYWRIGHT_SESSION_STORAGE_STATE;
const FULL_DETAIL_GUARD_NODES = 1_500;
const FULL_DETAIL_GUARD_BUILD_MS = 3_000;

interface LiveRelationship {
  source: string;
  target: string;
}

interface LiveResource {
  id: string;
  details?: { private_link_candidate?: boolean };
}

interface LiveTopology {
  hubs?: Array<{ vnet_id: string }>;
  links?: Array<{ local_vnet_id: string; remote_vnet_id: string }>;
  relationships?: LiveRelationship[];
  resources?: LiveResource[];
}

interface LiveSummary {
  gap_count: number;
  projected_full_node_count?: number;
  topology_build_duration_ms?: number;
}

interface LiveTopologyEnvelope {
  data: {
    topology: LiveTopology;
    summary: LiveSummary;
  };
}

interface LoadedTopology {
  response: Response;
  topology: LiveTopology;
  summary: LiveSummary;
}

async function canvasInkMetrics(page: Page) {
  return page.locator(".topology-canvas canvas").evaluateAll((canvases) => {
    let minimumX = 1;
    let maximumX = 0;
    let hasInk = false;
    for (const canvas of canvases) {
      const element = canvas as HTMLCanvasElement;
      const context = element.getContext("2d");
      if (!context || element.width === 0 || element.height === 0) continue;
      const pixels = context.getImageData(
        0,
        0,
        element.width,
        element.height,
      ).data;
      for (let y = 0; y < element.height; y += 4) {
        for (let x = 0; x < element.width; x += 4) {
          const alpha = pixels[(y * element.width + x) * 4 + 3];
          if (alpha === 0) continue;
          hasInk = true;
          minimumX = Math.min(minimumX, x / element.width);
          maximumX = Math.max(maximumX, (x + 1) / element.width);
        }
      }
    }
    return {
      hasInk,
      widthRatio: hasInk ? maximumX - minimumX : 0,
    };
  });
}

async function openTopology(page: Page): Promise<LoadedTopology> {
  const summaryResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/network/topology") &&
      response.url().includes("detail=summary"),
  );
  await page.goto("/network");
  const response = await summaryResponsePromise;
  expect(response.ok()).toBe(true);
  const envelope = (await response.json()) as LiveTopologyEnvelope;

  await page.getByRole("tab", { name: "Topology" }).click();
  await expect(
    page.getByRole("region", { name: "Network topology" }),
  ).toBeVisible();

  return {
    response,
    topology: envelope.data.topology,
    summary: envelope.data.summary,
  };
}

function requiresFullDetailConfirmation(summary: LiveSummary) {
  return (
    summary.projected_full_node_count === undefined ||
    summary.projected_full_node_count > FULL_DETAIL_GUARD_NODES ||
    (summary.topology_build_duration_ms ?? 0) >
      FULL_DETAIL_GUARD_BUILD_MS
  );
}

async function startFullDetail(page: Page, summary: LiveSummary) {
  await page.getByRole("button", { name: "Full detail" }).click();
  const confirmation = page.getByRole("button", {
    name: "Load full detail",
  });
  if (requiresFullDetailConfirmation(summary)) {
    await expect(confirmation).toBeVisible();
    await confirmation.click();
  } else {
    await expect(confirmation).toHaveCount(0);
  }
}

async function authorizationFrom(response: Response) {
  const requestHeaders = await response.request().allHeaders();
  expect(requestHeaders.authorization).toBeTruthy();
  return requestHeaders.authorization;
}

function fullDetailUrl(summaryResponse: Response) {
  const url = new URL(summaryResponse.url());
  url.searchParams.set("detail", "full");
  return url;
}

function unattachedPrivateLinkCandidateCount(topology: LiveTopology) {
  const incidentIds = new Set<string>();
  for (const relationship of topology.relationships ?? []) {
    incidentIds.add(String(relationship.source).toLowerCase());
    incidentIds.add(String(relationship.target).toLowerCase());
  }
  for (const link of topology.links ?? []) {
    incidentIds.add(String(link.local_vnet_id).toLowerCase());
    incidentIds.add(String(link.remote_vnet_id).toLowerCase());
  }
  return (topology.resources ?? []).filter(
    (resource) =>
      resource.details?.private_link_candidate === true &&
      !incidentIds.has(resource.id.toLowerCase()),
  ).length;
}

test.describe("deployed Phase 12 network topology acceptance", () => {
  test.skip(
    !liveEnabled,
    "Set AIOPS_LIVE_NETWORK_E2E=1 with PLAYWRIGHT_BASE_URL and PLAYWRIGHT_STORAGE_STATE after deployment.",
  );

  test.beforeEach(async ({ page }) => {
    test.setTimeout(240_000);
    if (liveSessionStoragePath) {
      const sessionState = JSON.parse(
        readFileSync(liveSessionStoragePath, "utf8"),
      ) as Record<string, string>;
      await page.addInitScript((state) => {
        for (const [key, value] of Object.entries(state)) {
          window.sessionStorage.setItem(key, value);
        }
      }, sessionState);
    }
  });

  test("[Finding 1] retains the summary canvas while full detail loads", async ({
    page,
  }) => {
    await page.route("**/api/v1/network/topology?**", async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("detail") === "full") {
        await new Promise((resolve) => setTimeout(resolve, 750));
      }
      await route.continue();
    });
    const { summary } = await openTopology(page);
    const fullResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/api/v1/network/topology") &&
        response.url().includes("detail=full"),
      { timeout: 180_000 },
    );

    await startFullDetail(page, summary);

    await expect(
      page.getByRole("region", { name: "Network topology" }),
    ).toHaveAttribute("aria-busy", "true");
    await expect(page.getByText(/nodes at summary detail\./)).toBeVisible();
    await expect.poll(async () => (await canvasInkMetrics(page)).hasInk).toBe(true);
    expect((await fullResponsePromise).ok()).toBe(true);
  });

  test("[Finding 2] exposes elapsed progress and Cancel for a slow full-detail load", async ({
    page,
  }) => {
    let delayedFullRequests = 0;
    await page.route("**/api/v1/network/topology?**", async (route) => {
      const url = new URL(route.request().url());
      const isFullDetail = url.searchParams.get("detail") === "full";
      if (isFullDetail) {
        delayedFullRequests += 1;
        await new Promise((resolve) => setTimeout(resolve, 3_500));
      }
      try {
        await route.continue();
      } catch (error) {
        if (!isFullDetail) throw error;
      }
    });
    const { summary } = await openTopology(page);

    await startFullDetail(page, summary);

    await expect(
      page.getByText(/Loading full detail — \d+ seconds elapsed\./),
    ).toBeVisible({ timeout: 5_000 });
    const cancel = page.getByRole("button", {
      name: "Cancel full-detail load",
    });
    await expect(cancel).toBeVisible();
    await cancel.click();
    await expect(
      page.getByRole("button", { name: "Summary" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(delayedFullRequests).toBe(1);
    await page.unrouteAll({ behavior: "wait" });
  });

  test("[Finding 2] keeps five-sample server and HTTP p95 within separate budgets", async ({
    page,
    request,
  }, testInfo) => {
    const { response } = await openTopology(page);
    const authorization = await authorizationFrom(response);
    const topologyUrl = fullDetailUrl(response);
    const serverHandlerSamplesMs: number[] = [];
    const httpSamplesMs: number[] = [];

    for (let sample = 0; sample < LATENCY_SAMPLE_COUNT; sample += 1) {
      const started = Date.now();
      const sampleResponse = await request.get(topologyUrl.toString(), {
        headers: { Authorization: authorization },
      });
      httpSamplesMs.push(Date.now() - started);
      expect(sampleResponse.ok()).toBe(true);
      serverHandlerSamplesMs.push(
        handlerDurationMs(
          sampleResponse.headers()[HANDLER_TIMING_HEADER],
        ),
      );
    }

    const serverHandler = latencyDistribution(serverHandlerSamplesMs);
    const endToEndHttp = latencyDistribution(httpSamplesMs);
    const diagnostics = {
      server_handler: {
        ...serverHandler,
        strict_budget_ms: SERVER_HANDLER_P95_BUDGET_MS,
      },
      end_to_end_http: {
        ...endToEndHttp,
        strict_budget_ms: HTTP_P95_BUDGET_MS,
      },
    };
    await testInfo.attach("full-detail-latency.json", {
      body: JSON.stringify(diagnostics, null, 2),
      contentType: "application/json",
    });
    const diagnosticText = JSON.stringify(diagnostics);
    expect.soft(
      serverHandler.p95Ms,
      `server handler p95 must be <${SERVER_HANDLER_P95_BUDGET_MS}ms; ${diagnosticText}`,
    ).toBeLessThan(SERVER_HANDLER_P95_BUDGET_MS);
    expect.soft(
      endToEndHttp.p95Ms,
      `end-to-end HTTP p95 must be <${HTTP_P95_BUDGET_MS}ms; ${diagnosticText}`,
    ).toBeLessThan(HTTP_P95_BUDGET_MS);
  });

  test("[Finding 3] returns a routable hub envelope with an explicit empty/non-empty disposition", async ({
    page,
    request,
  }) => {
    const { response, topology } = await openTopology(page);
    const hubId = String(topology.hubs?.[0]?.vnet_id ?? "");
    test.skip(
      !hubId,
      "Live precondition unavailable: the authorized summary contains no hub VNet.",
    );
    expect(hubId).toMatch(/^\/subscriptions\//i);

    const topologyUrl = fullDetailUrl(response);
    const hubUrl = new URL(
      "/api/v1/network/topology/hubs/dependents",
      topologyUrl.origin,
    );
    hubUrl.searchParams.set("vnet_id", hubId);
    topologyUrl.searchParams.forEach((value, key) => {
      if (key !== "detail") hubUrl.searchParams.append(key, value);
    });
    const hubResponse = await request.get(hubUrl.toString(), {
      headers: { Authorization: await authorizationFrom(response) },
    });

    expect(hubResponse.status()).toBe(200);
    const hubEnvelope = await hubResponse.json();
    const dependentCount = Number(hubEnvelope.data.dependent_count);
    const dependents = hubEnvelope.data.dependent_vnets;
    expect(dependentCount).toBeGreaterThanOrEqual(0);
    expect(dependents).toHaveLength(dependentCount);
    if (dependentCount === 0) {
      expect(dependents).toEqual([]);
    } else {
      expect(dependents.length).toBeGreaterThan(0);
    }
  });

  test("[Finding 4] keeps painted canvas pixels after a 1440-to-390 resize", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1_440, height: 900 });
    await openTopology(page);
    await expect.poll(async () => (await canvasInkMetrics(page)).hasInk).toBe(true);

    await page.setViewportSize({ width: 390, height: 844 });

    await expect.poll(async () => (await canvasInkMetrics(page)).hasInk).toBe(true);
  });

  test("[Finding 5] discloses and toggles unattached private-link candidates", async ({
    page,
  }) => {
    const { topology } = await openTopology(page);
    const hiddenCandidates = unattachedPrivateLinkCandidateCount(topology);
    test.skip(
      hiddenCandidates === 0,
      "Live precondition unavailable: the authorized summary has no unattached private-link candidates.",
    );

    await expect(
      page.getByText(
        new RegExp(`^${hiddenCandidates} unattached private link candidate`),
      ),
    ).toBeVisible();
    const toggle = page.getByRole("checkbox", {
      name: "Unattached private link candidates",
    });
    await expect(toggle).not.toBeChecked();
    await toggle.check();
    await expect(toggle).toBeChecked();
    await expect(
      page.getByText(
        new RegExp(`^${hiddenCandidates} unattached private link candidate`),
      ),
    ).toHaveCount(0);
  });

  test("[Finding 6] uses more than 55 percent of the canvas width", async ({
    page,
  }, testInfo) => {
    await openTopology(page);

    await expect
      .poll(async () => (await canvasInkMetrics(page)).widthRatio)
      .toBeGreaterThan(0.55);
    const metrics = await canvasInkMetrics(page);
    await testInfo.attach("canvas-ink-metrics.json", {
      body: JSON.stringify(metrics, null, 2),
      contentType: "application/json",
    });
  });

  test("[Finding 7] contains and exercises all five tabs at 390px", async ({
    page,
  }, testInfo: TestInfo) => {
    await openTopology(page);
    await page.setViewportSize({ width: 390, height: 844 });

    const tabs = page.locator(".workspace-tabs");
    const tabsBox = await tabs.boundingBox();
    expect(tabsBox).not.toBeNull();
    expect(tabsBox!.x + tabsBox!.width).toBeLessThanOrEqual(390);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(390);

    for (const name of [
      "Path analysis",
      "Topology",
      "Inspection gaps",
      "Rule findings",
      "Design policy",
    ]) {
      const tab = page.getByRole("tab", { name });
      await tab.scrollIntoViewIfNeeded();
      await expect(tab).toBeVisible();
      await tab.click();
      await expect(tab).toHaveAttribute("aria-selected", "true");
    }

    await page.screenshot({
      path: testInfo.outputPath("network-topology-390.png"),
      fullPage: true,
    });
  });

  test("[Finding 8] limits the first inspection-gap page to 20 cards", async ({
    page,
  }) => {
    const { summary } = await openTopology(page);
    test.skip(
      summary.gap_count === 0,
      "Live precondition unavailable: the authorized summary contains no inspection gaps.",
    );

    await page.getByRole("tab", { name: "Inspection gaps" }).click();
    const expectedRows = Math.min(20, summary.gap_count);
    await expect(page.locator(".finding-row")).toHaveCount(expectedRows);
    await expect(
      page.getByText(
        `Showing 1–${expectedRows} of ${summary.gap_count} inspection gaps`,
      ),
    ).toBeVisible();
  });

  test("[Finding 9] emits no wheel-sensitivity console warning", async ({
    page,
  }) => {
    const consoleWarnings: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "warning") consoleWarnings.push(message.text());
    });

    await openTopology(page);
    await expect.poll(async () => (await canvasInkMetrics(page)).hasInk).toBe(true);

    expect(
      consoleWarnings.some((warning) => /wheel sensitivity/i.test(warning)),
    ).toBe(false);
  });
});
