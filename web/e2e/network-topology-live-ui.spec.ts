import { expect, test, type Page } from "@playwright/test";
import type { Core } from "cytoscape";

const SUBSCRIPTION = "00000000-0000-0000-0000-000000000001";
const HUB =
  `/subscriptions/${SUBSCRIPTION}/resourceGroups/rg-network/providers/` +
  "Microsoft.Network/virtualNetworks/demo-vnet";
const SPOKE =
  `/subscriptions/${SUBSCRIPTION}/resourceGroups/rg-network/providers/` +
  "Microsoft.Network/virtualNetworks/app-vnet";

const envelope = <T,>(data: T, pagination?: Record<string, unknown>) => ({
  data,
  evidence: [
    {
      source_engine: "network.NetworkIntelligenceService",
      source_table: "ontology_entities",
      timestamp: "2026-09-08T00:00:00Z",
      confidence: "high",
      freshness: "fresh",
    },
  ],
  scope: { subscription: [SUBSCRIPTION] },
  knowledge_version: "network-e2e-v1",
  warnings: [],
  ...(pagination ? { pagination } : {}),
});

function topologyPayload() {
  const baseResource = {
    subscription_id: SUBSCRIPTION,
    resource_group: "rg-network",
    location: "australiaeast",
    connection_id: "conn-network",
    environment: "dev",
    business_service: "Platform",
    application: "",
    owner: "network@example.test",
    tags: {},
  };
  const resources = [
    {
      ...baseResource,
      id: HUB,
      name: "demo-vnet",
      entity_type: "VNet",
      role: "hub",
      details: { peer_count: 1, score: 4, signals: ["hosts_firewall"] },
    },
    {
      ...baseResource,
      id: SPOKE,
      name: "app-vnet",
      entity_type: "VNet",
      role: "spoke",
      details: { peer_count: 1 },
    },
    ...Array.from({ length: 12 }, (_, index) => ({
      ...baseResource,
      id:
        `/subscriptions/${SUBSCRIPTION}/resourceGroups/rg-data/providers/` +
        `Microsoft.Storage/storageAccounts/store${index}`,
      name: `store${index}`,
      entity_type: "StorageAccount",
      role: "private_link",
      details: {
        private_link_candidate: true,
        public_network_access: "Enabled",
      },
    })),
  ];
  const link = {
    local_vnet_id: HUB.toLowerCase(),
    remote_vnet_id: SPOKE.toLowerCase(),
    local_connection_id: "conn-network",
    remote_connection_id: "conn-network",
    is_bidirectional: true,
    is_healthy: true,
    is_cross_subscription: false,
    local_state: "Connected",
    remote_state: "Connected",
    allow_forwarded_traffic: false,
    allow_gateway_transit: false,
    use_remote_gateways: false,
    remote_vnet_observed: true,
  };
  return {
    topology: {
      hubs: [
        {
          vnet_id: HUB.toLowerCase(),
          name: "demo-vnet",
          role: "hub",
          score: 4,
          signals: ["hosts_firewall"],
          connection_id: "conn-network",
          subscription_id: SUBSCRIPTION,
          peer_count: 1,
        },
      ],
      spokes: [
        {
          vnet_id: SPOKE.toLowerCase(),
          name: "app-vnet",
          role: "spoke",
          score: 0,
          signals: [],
          connection_id: "conn-network",
          subscription_id: SUBSCRIPTION,
          peer_count: 1,
        },
      ],
      isolated: [],
      links: [link],
      shared_services: [],
      resources,
      relationships: [],
      unresolved_peer_vnet_ids: [],
      unresolved_peers: [],
      connection_ids: ["conn-network"],
      counts: {
        vnets: 2,
        private_link_resources: 12,
        relationships: 1,
        dropped_relationships: {},
      },
      coverage: {
        total: 14,
        returned: 14,
        truncated: false,
        nodes: { total: 14, returned: 14, truncated: false },
        relationships: { total: 1, returned: 1, truncated: false },
      },
      flow_log_provenance: {
        state: "not_ingested",
        observed_flow_count: 0,
      },
    },
    summary: {
      hub_count: 1,
      spoke_count: 1,
      isolated_vnet_count: 0,
      peering_count: 1,
      cross_subscription_peering_count: 0,
      unhealthy_peering_count: 0,
      shared_service_count: 0,
      connection_count: 1,
      gap_count: 77,
      gaps_by_severity: { high: 77 },
      gaps_by_category: { missing_nsg: 77 },
      rule_finding_count: 0,
      rule_findings_by_severity: {},
      rule_findings_by_category: {},
      intended_design_declared: true,
      resource_counts: { vnets: 2, private_link_resources: 12 },
      projected_full_node_count: 14,
      topology_build_duration_ms: 120,
    },
  };
}

function gapsPayload(url: URL) {
  const total = 77;
  const offset = Number(url.searchParams.get("offset") ?? 0);
  const limit = Number(url.searchParams.get("limit") ?? 20);
  const returned = Math.min(limit, total - offset);
  const gaps = Array.from({ length: returned }, (_, index) => {
    const item = offset + index;
    return {
      gap_id: `gap-${item}`,
      category: "missing_nsg",
      severity: "high",
      title: `Subnet ${item} has no NSG`,
      detail: "Synthetic browser acceptance gap",
      resource_id: `${SPOKE}/subnets/subnet-${item}`,
      resource_name: `subnet-${item}`,
      resource_type: "Subnet",
      evidence: {},
      recommendation: "Associate an approved NSG.",
      basis: "configuration",
      connection_id: "conn-network",
      subscription_id: SUBSCRIPTION,
      environment: "dev",
    };
  });
  return envelope(
    {
      gaps,
      intended_design_declared: true,
      summary: topologyPayload().summary,
      coverage: { total, returned, truncated: returned < total },
    },
    {
      offset,
      limit,
      total,
      next_offset: offset + returned < total ? offset + returned : null,
    },
  );
}

async function mockNetworkApis(
  page: Page,
  options: { slowFullDetail?: boolean } = {},
) {
  await page.route("**/api/v1/network/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/network/topology")) {
      if (
        options.slowFullDetail &&
        url.searchParams.get("detail") === "full"
      ) {
        await new Promise((resolve) => setTimeout(resolve, 5_000));
      }
      await route.fulfill({ json: envelope(topologyPayload()) });
      return;
    }
    if (url.pathname.endsWith("/network/gaps")) {
      await route.fulfill({ json: gapsPayload(url) });
      return;
    }
    if (url.pathname.endsWith("/network/rule-findings")) {
      await route.fulfill({
        json: envelope(
          {
            findings: [],
            summary: topologyPayload().summary,
            coverage: { total: 0, returned: 0, truncated: false },
          },
          { offset: 0, limit: 20, total: 0, next_offset: null },
        ),
      });
      return;
    }
    if (url.pathname.endsWith("/network/firewall-bypass")) {
      await route.fulfill({ json: envelope({ gaps: [], count: 0 }) });
      return;
    }
    if (url.pathname.endsWith("/network/policy")) {
      await route.fulfill({
        json: envelope({
          name: "Network policy",
          description: "",
          is_declared: true,
          source_path: "test",
          rules: [],
          supported_targets: [],
          supported_operators: [],
        }),
      });
      return;
    }
    await route.fulfill({ status: 404, json: { error: { message: "Unhandled mock" } } });
  });
}

async function canvasHasInk(page: Page) {
  return page.locator(".topology-canvas canvas").evaluateAll((canvases) =>
    canvases.some((canvas) => {
      const element = canvas as HTMLCanvasElement;
      const context = element.getContext("2d");
      if (!context || element.width === 0 || element.height === 0) return false;
      const pixels = context.getImageData(
        0,
        0,
        element.width,
        element.height,
      ).data;
      for (let index = 3; index < pixels.length; index += 64) {
        if (pixels[index] !== 0) return true;
      }
      return false;
    }),
  );
}

async function canvasInkWidthRatio(page: Page) {
  return page.locator(".topology-canvas canvas").evaluateAll((canvases) => {
    let minimumX = Number.POSITIVE_INFINITY;
    let maximumX = Number.NEGATIVE_INFINITY;
    let canvasWidth = 0;
    for (const canvas of canvases) {
      const element = canvas as HTMLCanvasElement;
      const context = element.getContext("2d");
      if (!context || element.width === 0 || element.height === 0) continue;
      canvasWidth = Math.max(canvasWidth, element.width);
      const pixels = context.getImageData(
        0,
        0,
        element.width,
        element.height,
      ).data;
      for (let y = 0; y < element.height; y += 2) {
        for (let x = 0; x < element.width; x += 2) {
          if (pixels[(y * element.width + x) * 4 + 3] !== 0) {
            minimumX = Math.min(minimumX, x);
            maximumX = Math.max(maximumX, x);
          }
        }
      }
    }
    if (!Number.isFinite(minimumX) || canvasWidth === 0) return 0;
    return (maximumX - minimumX + 1) / canvasWidth;
  });
}

test.describe("Phase 12 network topology live-review acceptance", () => {
  test("keeps hub dependency Copilot requests bound to visible network context", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    const failedRequests: string[] = [];
    const copilotRequests: Array<Record<string, unknown>> = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("requestfailed", (request) => {
      const url = new URL(request.url());
      if (
        url.hostname === "127.0.0.1"
        && url.port === "8080"
        && url.pathname === "/health"
      ) {
        return;
      }
      failedRequests.push(`${request.method()} ${request.url()}`);
    });
    await mockNetworkApis(page);
    await page.route("**/api/v1/copilot/investigate-context*", (route) =>
      route.fulfill({
        status: 503,
        json: {
          error: {
            code: "provider_unavailable",
            message: "Automatic narration is unavailable during this controlled replay.",
          },
        },
      }));
    await page.route("**/api/v1/copilot/investigations*", async (route) => {
      const request = route.request().postDataJSON() as Record<string, unknown>;
      copilotRequests.push(request);
      if (copilotRequests.length > 1) {
        await route.fulfill({
          status: 422,
          json: {
            error: {
              code: "validation_error",
              message: "A VNet outside the bound page selection cannot execute.",
            },
          },
        });
        return;
      }
      await route.fulfill({
        json: envelope({
          contract_version: "1",
          status: "ok",
          policy_status: "accepted",
          fallback_reason: "",
          selected_specialists: ["network"],
          selected_tools: ["hub_dependents"],
          tool_results: [{
            call_id: "network:hub-dependents:0",
            specialist_id: "network",
            tool: "hub_dependents",
            status: "ok",
            data: {
              hub_vnet_id: HUB.toLowerCase(),
              dependents: [{ vnet_id: SPOKE.toLowerCase(), name: "app-vnet" }],
            },
            evidence: [],
            warning: "",
          }],
          uncertainty: [
            "Dependency evidence covers the currently visible topology snapshot.",
          ],
          coverage: { visible_count: 1, total_count: 1, complete: true },
          citations: [{
            citation_id: "network:hub:demo-vnet",
            source: "network/hub-dependents",
            status: "ok",
            observed_at: "2026-09-08T00:00:00Z",
            resource_id: HUB.toLowerCase(),
            observation_status: "current",
          }],
          synthesis: {
            status: "deterministic",
            claims: [{
              finding_id: "network:hub:demo-vnet",
              summary: "demo-vnet has one direct dependent: app-vnet.",
              evidence_refs: ["network:hub:demo-vnet"],
              confidence: "high",
              freshness: "fresh",
              uncertainty: [],
            }],
          },
          thread_id: "thr-00000000000000000000000000000001",
          thread_revision: 1,
          mutation_authorized: false,
        }),
      });
    });

    await page.goto("/network");
    await page.getByRole("tab", { name: "Topology", exact: true }).click();
    const canvas = page.locator(".topology-canvas");
    await expect(canvas).toBeVisible();
    await canvas.scrollIntoViewIfNeeded();
    await expect.poll(() => canvas.evaluate((element, id) => {
      const registry = (element as HTMLElement & { _cyreg?: { cy?: Core } })._cyreg;
      return registry?.cy?.nodes().filter((node) =>
        node.id().toLowerCase() === id.toLowerCase()).length ?? 0;
    }, HUB)).toBe(1);
    const hubPosition = await canvas.evaluate((element, id) => {
      const registry = (element as HTMLElement & { _cyreg?: { cy?: Core } })._cyreg;
      const node = registry?.cy?.nodes().filter((candidate) =>
        candidate.id().toLowerCase() === id.toLowerCase());
      if (!node?.length) throw new Error("Expected the visible hub node");
      return node.renderedPosition();
    }, HUB);
    await canvas.click({ position: hubPosition });
    await expect(page.getByRole("dialog", { name: "Topology element details" })
      .getByRole("heading", { name: "demo-vnet", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Ask Copilot about network paths" }).click();
    const drawer = page.getByRole("dialog", { name: "Operations Copilot" });
    await expect(drawer).toBeVisible();
    await drawer.getByRole("textbox").fill("What depends on demo-vnet?");
    await drawer.getByRole("button", { name: "Send" }).click();

    await expect(
      drawer.getByText("demo-vnet has one direct dependent: app-vnet."),
    ).toBeVisible();
    await drawer.getByRole("button", { name: "Citations (1)", exact: true }).click();
    await expect(
      drawer.getByText("network:hub:demo-vnet", { exact: true }),
    ).toBeVisible();
    await expect(
      drawer.getByText(
        "Dependency evidence covers the currently visible topology snapshot.",
      ),
    ).toBeVisible();
    await expect.poll(() => copilotRequests.length).toBe(1);
    expect(copilotRequests[0]).toMatchObject({
      question: "What depends on demo-vnet?",
      snapshot: {
        page_kind: "network",
        page_id: "network-topology",
        selected_entities: [{ type: "azure", resource_id: HUB.toLowerCase() }],
      },
    });
    expect(copilotRequests[0]).not.toHaveProperty("hint");

    await drawer.getByRole("textbox").fill("What depends on unselected-vnet?");
    await drawer.getByRole("button", { name: "Send" }).click();
    await expect.poll(() => copilotRequests.length).toBe(2);
    expect(copilotRequests[1]).toMatchObject({
      question: "What depends on unselected-vnet?",
      snapshot: { page_kind: "network", page_id: "network-topology" },
    });
    expect(copilotRequests[1]).not.toHaveProperty("hint");
    await expect(
      drawer.getByText("A VNet outside the bound page selection cannot execute."),
    ).toBeVisible();
    expect(pageErrors).toEqual([]);
    expect(failedRequests).toEqual([]);
  });

  test("keeps the connected graph primary and makes unattached candidates available on demand", async ({
    page,
  }) => {
    const warnings: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "warning") warnings.push(message.text());
    });
    await mockNetworkApis(page);
    await page.goto("/network");
    await page.getByRole("tab", { name: "Topology", exact: true }).click();

    await expect(
      page.getByText(
        "12 unattached private link candidates hidden; enable the filter to show them.",
      ),
    ).toBeVisible();
    const candidateToggle = page.getByRole("checkbox", {
      name: "Unattached private link candidates",
    });
    await expect(candidateToggle).not.toBeChecked();
    await expect.poll(() => canvasHasInk(page)).toBe(true);
    await expect.poll(() => canvasInkWidthRatio(page)).toBeGreaterThan(0.55);
    expect(
      warnings.some((warning) => /wheel sensitivity/i.test(warning)),
    ).toBe(false);

    await candidateToggle.check();
    await expect(
      page.getByText(/unattached private link candidates hidden/),
    ).toHaveCount(0);
  });

  test("retains summary context and offers Cancel while full detail is slow", async ({
    page,
  }) => {
    await mockNetworkApis(page, { slowFullDetail: true });
    await page.goto("/network");
    await page.getByRole("tab", { name: "Topology", exact: true }).click();
    await expect(page.getByText("Rendering 2 of 14 nodes at summary detail.")).toBeVisible();

    await page.getByRole("button", { name: "Full detail" }).click();

    await expect(
      page.getByRole("region", { name: "Network topology" }),
    ).toHaveAttribute("aria-busy", "true");
    await expect(page.getByText("Rendering 2 of 14 nodes at summary detail.")).toBeVisible();
    const cancel = page.getByRole("button", {
      name: "Cancel full-detail load",
    });
    await expect(cancel).toBeVisible({ timeout: 5_000 });
    await cancel.click();
    await expect(
      page.getByRole("button", { name: "Summary" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  test("keeps the graph painted and all five tabs usable at 390px", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockNetworkApis(page);
    await page.goto("/network");
    await page.getByRole("tab", { name: "Topology", exact: true }).click();
    await expect.poll(() => canvasHasInk(page)).toBe(true);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(250);
    await expect.poll(() => canvasHasInk(page)).toBe(true);

    const tabs = page.locator(".workspace-tabs");
    await expect(tabs).toHaveCSS("overflow-x", "auto");
    const bounds = await tabs.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);

    const policyTab = page.getByRole("tab", { name: "Design policy" });
    await policyTab.scrollIntoViewIfNeeded();
    await policyTab.click();
    await expect(
      page.getByRole("heading", { name: "Rule-based network design policy" }),
    ).toBeVisible();

    await page.getByRole("tab", { name: "Inspection gaps" }).click();
    await expect(page.locator(".finding-row")).toHaveCount(20);
    await expect(
      page.getByText("Showing 1–20 of 77 inspection gaps"),
    ).toBeVisible();
  });
});
