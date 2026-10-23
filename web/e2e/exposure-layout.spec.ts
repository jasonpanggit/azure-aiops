import { expect, test, type Page } from "@playwright/test";

const contract = {
  version: "1.0.0",
  query: {
    scope: {}, generation: "layout-generation", filters: [],
    sort: { field: "priority_score", direction: "desc" }, target_kind: "all",
  },
  counts: { unit: "findings", returned: 1, represented: 1, total: 1, excluded: 0 },
  units: { finding_count: "count", priority_score: "score", sla_age: "seconds" },
  completeness: {
    state: "complete", represented_connections: 1, expected_connections: 1,
    represented: 1, total: 1, excluded: 0, excluded_reasons: [],
  },
  freshness: { state: "current", as_of: "2026-09-06T08:00:00Z", source_family: "aum", threshold_seconds: 3600 },
  evidence_refs: [{ source_family: "aum", source_id: "layout-finding" }],
  deep_link_action: { action_id: "open_exposure_detail", kind: "deep_link", path_field: "detail_path", fallback_path_template: "/exposure/{target_kind}/{exposure_id}" },
  safe_error: null,
};

function envelope(data: unknown) {
  return { data, evidence: [], warnings: [], scope: {}, knowledge_version: "layout-generation" };
}

const cve = {
  cve_id: "CVE-2026-0001",
  title: "Kernel remote execution",
  description: "A remote execution vulnerability.",
  severity: "Critical",
  cvss: { version: "3.1", base_score: 9.8, vector: "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", severity: "Critical" },
  associated_kbs: ["KB600001"],
  epss_score: 0.73,
  epss_percentile: 0.92,
  is_known_exploited: true,
  kev_due_date: "2026-08-22",
  kev_ransomware_use: "Known",
  exploit_references: [],
};

const enrichment = {
  status: "complete", complete: true, stale: false, expected_count: 4, available_count: 4,
  sources: Object.fromEntries(["nvd", "epss", "kev", "msrc:KB600001"].map((source) => [
    source,
    { source: source.split(":")[0], identifier: source.startsWith("msrc") ? "KB600001" : cve.cve_id, status: "succeeded", stale: false, has_last_known_good: true, source_at: "2026-09-06T08:00:00Z" },
  ])),
};

async function mockExposureLayout(page: Page) {
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const common = {
      total_count: 1, generation: "layout-generation", applied: contract.query,
      completeness: contract.completeness, freshness: contract.freshness, contract,
    };
    const data: Record<string, unknown> = {
      "/vulnerabilities/exposure/overview": common,
      "/vulnerabilities/exposure/items": {
        ...common, next_cursor: null,
        items: [{
          exposure_id: "layout-finding",
          target_id: "server-1", target_kind: "server", server_id: "server-1",
          weakness_id: "KB600001", weakness_kind: "kb", cve_id: cve.cve_id,
          missing_kb: "KB600001", severity: "Critical", business_service: "Payments",
          subscription_id: "test", connection_ids: ["aum"], source_families: ["aum"],
          read_model_generation_id: "layout-generation", completeness: "complete",
          priority_score: 91, recommendation: "Review KB600001", current_state: "missing",
          detail_path: "/exposure/kbs/KB600001", governed_action_id: "", execution_eligible: false,
          sla_state: "indeterminate", sla_age_seconds: null, sla_target_seconds: null,
          sla_due_at: null, sla_overdue: null,
        }],
      },
      "/vulnerabilities/summary": {
        critical_count: 1, cve_count: 1, affected_server_count: 1, affected_asset_count: 1,
        affected_application_count: 1, affected_business_service_count: 1,
        reachable_server_count: 1, internet_exposed_count: 1, defender_observed_asset_count: 1,
      },
      "/vulnerabilities/patch-priorities": [],
      "/vulnerabilities/asset-exposures": [],
      "/vulnerabilities/defender-posture": [],
      "/vulnerabilities/container-image-exposures": [],
      "/vulnerabilities/risk-exceptions": [],
      "/vulnerabilities/sla-compliance": { overall_compliance_rate: null, compliant_count: 0, tracked_count: 0, overdue_count: 0, open_count: 1 },
      "/defender/overview": {
        active_alert_count: 0, critical_alert_count: 0, attack_path_count: 0,
        unhealthy_recommendation_count: 0, vulnerable_container_image_count: 0,
        container_image_cve_count: 0, secure_scores: [], top_controls: [], coverage: {},
      },
      "/defender/alerts": [],
      "/defender/attack-paths": [],
      "/defender/secure-score": [],
      "/defender/secure-score-controls": [],
      "/cves/CVE-2026-0001": {
        cve, enrichment, findings: [], exploitability_signals: [],
        affected_servers: ["server-1"], affected_applications: ["Checkout"],
        affected_business_services: ["Payments"], recommended_patch: "KB600001",
      },
      "/cves/CVE-2026-0001/attack-path": { nodes: [], edges: [] },
      "/kbs/KB600001": {
        kb_id: "KB600001", title: "Kernel security update", severity: "Critical",
        published_at: "2026-08-01", cve_ids: [cve.cve_id], cves: [cve],
        affected_servers: ["server-1"], affected_business_services: ["Payments"],
        findings: [], enrichment,
      },
      "/remediation/exposure-handoffs": { cases: [], read_only: true, execution_transition: false },
    };
    return path in data
      ? route.fulfill({ json: envelope(data[path]) })
      : route.fulfill({ status: 503, json: { detail: `No test source for ${path}` } });
  });
}

const routes = [
  { path: "/exposure", nav: "Exposure overview sections", links: 8 },
  { path: "/exposure/defender-posture", nav: "Defender posture sections", links: 2 },
  { path: "/exposure/patch-priorities", nav: "Patch priority sections", links: 2 },
  { path: "/exposure/cves/CVE-2026-0001", nav: "CVE detail sections", links: 4 },
  { path: "/exposure/kbs/KB600001", nav: "KB detail sections", links: 3 },
];

for (const width of [1440, 820, 768, 375, 320]) {
  for (const route of routes) {
    test(`${route.path} has task-first sections and one insight at ${width}px`, async ({ page }, testInfo) => {
      const pageErrors: string[] = [];
      page.on("pageerror", (error) => pageErrors.push(error.message));
      await page.setViewportSize({ width, height: 900 });
      await mockExposureLayout(page);
      await page.goto(route.path);
      const nav = page.getByRole("navigation", { name: route.nav });
      await expect(nav.getByRole("link")).toHaveCount(route.links);
      await expect(page.locator(".state-loading")).toHaveCount(0);
      await expect(page.locator(".copilot-insights")).toHaveCount(1);
      if (route.path === "/exposure/patch-priorities") {
        const coverage = page.getByRole("list", { name: "Counts by query coverage", exact: true });
        await expect(coverage).toHaveText("Represented1Query total1");
        await expect(page.getByText("Query coverage, not a health or remediation verdict.")).toBeVisible();
        await expect(page.getByRole("img", { name: /Represented of total/ })).toHaveCount(0);
      }
      const insight = page.locator(".copilot-insights");
      for (const link of await nav.getByRole("link").all()) {
        const box = await link.boundingBox();
        expect(box!.x).toBeGreaterThanOrEqual(0);
        expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
        const target = page.locator((await link.getAttribute("href"))!);
        await expect(target).toHaveCount(1);
        expect((await target.boundingBox())!.y).toBeLessThan((await insight.boundingBox())!.y);
      }
      await nav.getByRole("link").last().click();
      const destination = page.locator((await nav.getByRole("link").last().getAttribute("href"))!);
      await expect(destination).toBeInViewport();
      const freshness = page.locator("details.source-section-details").filter({
        has: page.locator("summary", { hasText: "Source freshness details" }),
      }).first();
      if (await freshness.count()) {
        await expect(freshness).not.toHaveAttribute("open");
        await freshness.locator("summary").click();
        await expect(freshness).toHaveAttribute("open");
        await expect(freshness.locator(".source-section-freshness")).toBeVisible();
      }
      if (route.path.includes("/cves/") || route.path.includes("/kbs/")) {
        const trigger = page.locator(".page-header-actions .copilot-drawer-trigger");
        const buttonBox = await trigger.boundingBox();
        if (width <= 640) {
          expect(buttonBox!.width).toBe(44);
          expect(buttonBox!.height).toBe(44);
        }
        await expect(page.getByText(route.path.includes("/cves/")
          ? /Approval and execution remain in the governed remediation workflow/
          : /Exposure does not install updates/)).toBeVisible();
      }
      const signal = page.locator(".page-header-signal");
      if (width === 1440 || width === 375) {
        await page.locator(".page-header").screenshot({ path: testInfo.outputPath(`exposure-header-${width}.png`) });
      }
      if (width <= 560 && await signal.count()) {
        for (const item of await signal.locator(":scope > span").all()) {
          const brokenWord = await item.evaluate(element => {
            const text = element.firstChild;
            if (!text || text.nodeType !== Node.TEXT_NODE) return false;
            const value = text.textContent ?? "";
            return Array.from(value.matchAll(/\S+/g)).some(match => {
              const range = document.createRange();
              range.setStart(text, match.index!);
              range.setEnd(text, match.index! + match[0].length);
              return range.getClientRects().length > 1;
            });
          });
          expect(brokenWord).toBe(false);
        }
      }
      expect(pageErrors).toEqual([]);
    });
  }
}
