import { expect, test } from "@playwright/test";

const TARGET =
  "/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/server-1";

function envelope<T>(data: T) {
  return {
    data,
    evidence: [],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: "generation-17",
  };
}

function exposurePage() {
  const contract = {
    version: "1.0.0",
    query: {
      scope: { subscription: ["sub-1"] },
      generation: "generation-17",
      filters: [],
      sort: { field: "priority_score", direction: "desc" },
      target_kind: "all",
    },
    counts: {
      unit: "findings",
      returned: 1,
      represented: 1,
      total: 1,
      excluded: 0,
    },
    units: {
      priority_score: "score",
      sla_age: "seconds",
      sla_due_at: "timestamp",
      rank: "ordinal",
    },
    completeness: {
      state: "complete",
      represented_connections: 1,
      expected_connections: 1,
      represented: 1,
      total: 1,
      excluded: 0,
      excluded_reasons: [],
    },
    freshness: {
      state: "current",
      as_of: "2026-09-06T08:00:00Z",
      source_family: "aum",
      threshold_seconds: 3600,
    },
    evidence_refs: [{ source_family: "aum", source_id: "aum-evidence-1" }],
    deep_link_action: {
      action_id: "open_exposure_detail",
      kind: "deep_link",
      path_field: "detail_path",
      fallback_path_template: "/exposure/{target_kind}/{exposure_id}",
    },
    safe_error: null,
  };
  return envelope({
    total_count: 1,
    items: [
      {
        exposure_id: "exposure-server-1-kb600001",
        target_id: TARGET,
        target_kind: "server",
        weakness_id: "KB600001",
        weakness_kind: "kb",
        subscription_id: "sub-1",
        connection_ids: ["connection-aum"],
        source_families: ["aum"],
        read_model_generation_id: "generation-17",
        completeness: "complete",
        severity: "Critical",
        priority_score: 91,
        recommendation: "Install KB600001",
        current_state: "missing",
        sla_state: "overdue",
        sla_age_seconds: 172800,
        sla_target_seconds: 86400,
        sla_due_at: "2026-09-05T08:00:00Z",
        sla_overdue: true,
        detail_path: "/exposure/kbs/KB600001",
        governed_action_id: "controlled-patch-recovery",
        execution_eligible: true,
      },
    ],
    next_cursor: null,
    generation: "generation-17",
    applied: contract.query,
    completeness: contract.completeness,
    freshness: contract.freshness,
    contract,
  });
}

async function mockExposureApis(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/vulnerabilities/exposure/items")) {
      return route.fulfill({ json: exposurePage() });
    }
    if (url.pathname.endsWith("/remediation/exposure-handoffs")) {
      return route.fulfill({
        json: envelope({
          cases: [],
          read_only: true,
          execution_transition: false,
        }),
      });
    }
    if (url.pathname.endsWith("/vulnerabilities/risk-exceptions")) {
      return route.fulfill({ json: envelope([]) });
    }
    if (url.pathname.endsWith("/remediation/plans")) {
      return route.fulfill({ json: envelope({ plans: [] }) });
    }
    return route.fulfill({ json: envelope({}) });
  });
}

for (const viewport of [
  { name: "mobile", width: 375, height: 812 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1440, height: 900 },
]) {
  test(`preserves responsive evidence-to-remediation-to-return continuity at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await mockExposureApis(page);
    await page.goto(
      "/exposure/patch-priorities?subscription=sub-1&q=kernel&page_size=25&generation=generation-17",
    );

    const region = page.getByRole("region", {
      name: "Patch priorities table",
    });
    const row = page.locator("#exposure-server-1-kb600001");
    await expect(region).toBeVisible();
    await expect(row).toBeVisible();

    const layout = await region.evaluate((element) => {
      const table = element.querySelector("table");
      const firstRow = element.querySelector("tbody tr");
      return {
        regionClientWidth: element.clientWidth,
        regionScrollWidth: element.scrollWidth,
        rowDisplay: firstRow ? getComputedStyle(firstRow).display : "",
        tableMinWidth: table ? getComputedStyle(table).minWidth : "",
        pageClientWidth: document.querySelector(".exposure-patch-priorities")
          ?.clientWidth,
        pageScrollWidth: document.querySelector(".exposure-patch-priorities")
          ?.scrollWidth,
      };
    });

    if (viewport.width === 375) {
      expect(layout.rowDisplay).toBe("block");
      expect(layout.pageScrollWidth).toBeLessThanOrEqual(layout.pageClientWidth ?? 0);
    } else if (viewport.width === 768) {
      expect(layout.tableMinWidth).toBe("960px");
      expect(layout.regionScrollWidth).toBeGreaterThan(layout.regionClientWidth);
    } else {
      expect(layout.rowDisplay).toBe("table-row");
    }

    const search = page.getByRole("searchbox", { name: "Search exposure" });
    await search.focus();
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("combobox", { name: "Filter by Target kind" }),
    ).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(region).toBeFocused();
    await page.keyboard.press("Tab");
    const sort = page.getByRole("button", {
      name: "Sort by operational priority",
    });
    await expect(sort).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).not.toHaveURL(/sort_by=severity/);

    const open = page.getByRole("link", {
      name: "Open governed remediation for KB600001",
    });
    const href = await open.getAttribute("href");
    expect(href).toContain("return_to=");
    await open.click();

    const back = page.getByRole("link", { name: "Back to exposure" });
    await expect(back).toBeVisible();
    await expect(page.getByText(/Nothing executes from Exposure/)).toBeVisible();
    await back.click();

    await expect(page).toHaveURL(/\/exposure\/patch-priorities/);
    await expect(row).toBeFocused();
  });
}
