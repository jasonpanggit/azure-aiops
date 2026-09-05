import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";

import { vulnerabilityApi } from "@/lib/services";
import type { Envelope, ExposureCollection } from "@/lib/types";

const GENERATION = "exposure-generation-0001";

function captureFetch(body: Envelope<ExposureCollection>) {
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
});
