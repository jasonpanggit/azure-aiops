import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";

import { vulnerabilityApi } from "@/lib/services";
import { SCOPE_DIMENSIONS } from "@/lib/scope";
import type {
  Envelope,
  ExposureCollection,
  ExposureCursorPagination,
  ExposureExternalCatalog,
  ExposureExternalCatalogItem,
  Pagination,
} from "@/lib/types";

const GENERATION = "exposure-generation-0001";

function captureFetch<T, TPagination = Pagination>(body: Envelope<T, TPagination>) {
  const spy = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
    if (String(input) === "/api/dev-token") {
      return {
        ok: true,
        status: 200,
        statusText: "",
        headers: { get: () => null },
        json: async () => ({ token: "test-token" }),
      } as unknown as Response;
    }
    return {
      ok: true,
      status: 200,
      statusText: "",
      headers: { get: () => null },
      json: async () => body,
    } as unknown as Response;
  });
  global.fetch = spy;
  return spy;
}

describe("vulnerabilityApi authoritative Exposure envelope", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("separates retained reads from explicit revision-bound capture across all scope dimensions", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(dimension => [dimension, ["one", "two"]]));
    const fetchSpy = captureFetch({ data: {}, evidence: [], scope, warnings: [] });
    const controller = new AbortController();
    await vulnerabilityApi.exposureHistory(scope, controller.signal);
    await vulnerabilityApi.captureExposureObservation(scope, 4, GENERATION);
    const calls = fetchSpy.mock.calls.filter(([input]) => String(input).includes("/api/v1/"));
    expect(calls).toHaveLength(2);
    for (const [input] of calls) {
      const url = new URL(String(input));
      expect(url.pathname).toBe("/api/v1/vulnerabilities/exposure/history");
      for (const dimension of SCOPE_DIMENSIONS) expect(url.searchParams.getAll(dimension)).toEqual(["one", "two"]);
    }
    expect(calls[0][1]).toMatchObject({ method: "GET", signal: controller.signal });
    expect(calls[1][1]).toMatchObject({ method: "POST", body: JSON.stringify({ expected_revision: 4, generation: GENERATION }) });
  });

  it("separates recovery reads and explicit review declarations across all nine dimensions", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(dimension => [dimension, ["one", "two"]]));
    const fetchSpy = captureFetch({ data: {}, evidence: [], scope, warnings: [] });
    const controller = new AbortController();
    const payload = {
      expected_revision: 3, observation_id: `exo-${"1".repeat(32)}`, reason: "connection_coverage" as const,
      disposition: "queued" as const, owner: "Operations", target_date: "2026-11-01", note: "Review recorded gap",
    };
    await vulnerabilityApi.exposureRecovery(scope, controller.signal);
    await vulnerabilityApi.reviewExposureRecovery(scope, payload);
    const calls = fetchSpy.mock.calls.filter(([input]) => String(input).includes("/api/v1/"));
    expect(calls).toHaveLength(2);
    for (const [input] of calls) {
      const url = new URL(String(input));
      expect(url.pathname).toBe("/api/v1/vulnerabilities/exposure/recovery");
      for (const dimension of SCOPE_DIMENSIONS) expect(url.searchParams.getAll(dimension)).toEqual(["one", "two"]);
    }
    expect(calls[0][1]).toMatchObject({ method: "GET", signal: controller.signal });
    expect(calls[1][1]).toMatchObject({ method: "POST", body: JSON.stringify(payload) });
  });

  it("reacquires a bounded review selection without submitting source rows", async () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(dimension => [dimension, ["one", "two"]]));
    const fetchSpy = captureFetch({ data: {}, evidence: [], scope, warnings: [] });
    const controller = new AbortController();
    const query = {
      scope, filters: { severity: "critical", active: true }, sort: { field: "priority_score" as const, direction: "desc" as const },
      pageSize: 25 as const, page: 2, cursor: "opaque-next", cursorHistory: [""], generation: GENERATION, target: "", drawer: "",
    };
    await vulnerabilityApi.patchReviews(scope, controller.signal);
    await vulnerabilityApi.createPatchReview(query, 2, ["finding-one"], "Operations", "Review before planning");
    const calls = fetchSpy.mock.calls.filter(([input]) => String(input).includes("/api/v1/"));
    expect(calls).toHaveLength(2);
    for (const [input] of calls) {
      const url = new URL(String(input));
      expect(url.pathname).toBe("/api/v1/vulnerabilities/exposure/patch-reviews");
      for (const dimension of SCOPE_DIMENSIONS) expect(url.searchParams.getAll(dimension)).toEqual(["one", "two"]);
    }
    expect(calls[0][1]).toMatchObject({ method: "GET", signal: controller.signal });
    expect(JSON.parse(calls[1][1].body)).toEqual({
      expected_revision: 2, generation: GENERATION, cursor: "opaque-next", page_size: 25,
      sort_by: "priority_score", sort_direction: "desc", filters: query.filters,
      exposure_ids: ["finding-one"], owner: "Operations", note: "Review before planning",
    });
  });

  it("preserves findings, generation, counts, completeness, and source attribution", async () => {
    const envelope: Envelope<ExposureCollection> = {
      data: {
        findings: [
          {
            exposure_id: "exposure:aum-only:vm-a:cve-2026-1001",
            target_id: "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-a",
            target_kind: "server",
            weakness_id: "CVE-2026-1001",
            subscription_id: "sub-a",
            connection_ids: ["connection-aum-east"],
            source_families: ["aum"],
            read_model_generation_id: GENERATION,
            completeness: "complete",
          },
        ],
        read_model_generation_id: GENERATION,
        returned_count: 1,
        total_count: 4,
        completeness: {
          state: "partial",
          represented_connections: 1,
          expected_connections: 2,
        },
        source_attribution: [
          { source_family: "aum", finding_count: 1 },
        ],
      },
      evidence: [],
      scope: { subscription: ["sub-a"] },
      pagination: { offset: 0, limit: 100, total: 4, next_offset: null },
    };
    const fetchSpy = captureFetch(envelope);

    const response = await vulnerabilityApi.authoritativeExposures(
      { subscription: ["sub-a"] },
      { q: "CVE-2026", reachableOnly: true },
    );

    expectTypeOf(response).toEqualTypeOf<Envelope<ExposureCollection>>();
    expect(response).toEqual(envelope);
    expect(response.data.findings[0].source_families).toEqual(["aum"]);
    expect(response.data.read_model_generation_id).toBe(GENERATION);
    expect(response.data.returned_count).toBe(1);
    expect(response.data.total_count).toBe(4);
    expect(response.data.completeness).toEqual({
      state: "partial",
      represented_connections: 1,
      expected_connections: 2,
    });
    expect(response.data.source_attribution).toEqual([
      { source_family: "aum", finding_count: 1 },
    ]);

    const apiCall = fetchSpy.mock.calls.find(([input]) =>
      String(input).includes("/api/v1/vulnerabilities/exposures"),
    );
    expect(apiCall).toBeDefined();
    const url = new URL(String(apiCall?.[0]));
    expect(url.searchParams.getAll("subscription")).toEqual(["sub-a"]);
    expect(url.searchParams.get("q")).toBe("CVE-2026");
    expect(url.searchParams.get("reachable_only")).toBe("true");
    expect(url.searchParams.has("read_model_generation_id")).toBe(false);
  });

  it("requests external catalog metadata at the pinned generation", async () => {
    const catalogEnvelope: Envelope<
      ExposureExternalCatalog<ExposureExternalCatalogItem>,
      ExposureCursorPagination
    > = {
      data: {
        contract_version: "1.0.0",
        catalog_scope: "external_public_metadata",
        environment_membership_included: false,
        generation: GENERATION,
        item: { cve_id: "CVE-2026-1001", sources: {} },
      },
      evidence: [],
      scope: { subscription: ["sub-a"] },
      pagination: { limit: 0, total: 0, next_cursor: null },
    };
    const fetchSpy = captureFetch(catalogEnvelope);

    await vulnerabilityApi.exposureExternalCatalog(
      "CVE-2026-1001",
      { subscription: ["sub-a"] },
      { generation: GENERATION },
    );

    const apiCall = fetchSpy.mock.calls.find(([input]) =>
      String(input).includes("/api/v1/vulnerabilities/exposure/external-catalog/"),
    );
    expect(apiCall).toBeDefined();
    const url = new URL(String(apiCall?.[0]));
    expect(url.pathname).toBe(
      "/api/v1/vulnerabilities/exposure/external-catalog/CVE-2026-1001",
    );
    expect(url.searchParams.getAll("subscription")).toEqual(["sub-a"]);
    expect(url.searchParams.get("generation")).toBe(GENERATION);
  });
});
