import { afterEach, describe, expect, it, vi } from "vitest";
import { networkApi } from "@/lib/services";

/** Captures the URL each call builds, so query serialization is asserted
 * rather than assumed — a dropped scope parameter would silently widen a
 * scoped user's view. */
function captureFetch(body: unknown = {}) {
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
      json: async () => ({ data: body, evidence: [], scope: {}, knowledge_version: "v1" }),
    } as unknown as Response;
  });
  global.fetch = spy;
  return spy;
}

function calledUrl(spy: ReturnType<typeof captureFetch>): URL {
  const apiCall = spy.mock.calls.find(([input]) => String(input).includes("/api/v1/"));
  if (!apiCall) throw new Error("Expected an Operations API request");
  return new URL(String(apiCall[0]));
}

function calledPath(spy: ReturnType<typeof captureFetch>): string {
  const apiCall = spy.mock.calls.find(([input]) => String(input).includes("/api/v1/"));
  if (!apiCall) throw new Error("Expected an Operations API request");
  return String(apiCall[0]);
}

describe("networkApi", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("passes the full scope selection through to the topology endpoint", async () => {
    const spy = captureFetch({ topology: {}, summary: {} });
    await networkApi.topology({ subscription: ["sub-a", "sub-b"], environment: ["prod"] });
    const url = calledUrl(spy);
    expect(url.pathname).toBe("/api/v1/network/topology");
    expect(url.searchParams.getAll("subscription")).toEqual(["sub-a", "sub-b"]);
    expect(url.searchParams.getAll("environment")).toEqual(["prod"]);
  });

  it("forwards an AbortSignal to the topology request", async () => {
    const spy = captureFetch({ topology: {}, summary: {} });
    const controller = new AbortController();

    await networkApi.topology(
      { subscription: ["sub-a"] },
      { detail: "full" },
      { signal: controller.signal },
    );

    const apiCall = spy.mock.calls.find(([input]) =>
      String(input).includes("/api/v1/"),
    );
    expect(apiCall?.[1]).toEqual(
      expect.objectContaining({ signal: controller.signal }),
    );
  });

  it("sends source, destination and port for a traffic-flow query", async () => {
    const spy = captureFetch({ verdict: "denied" });
    await networkApi.trafficFlow({ source: "10.2.1.10", destination: "10.1.1.10", port: 1433 });
    const url = calledUrl(spy);
    expect(url.pathname).toBe("/api/v1/network/traffic-flow");
    expect(url.searchParams.get("source")).toBe("10.2.1.10");
    expect(url.searchParams.get("destination")).toBe("10.1.1.10");
    expect(url.searchParams.get("port")).toBe("1433");
  });

  it("omits the port when none is supplied rather than sending an empty value", async () => {
    const spy = captureFetch({ verdict: "indeterminate" });
    await networkApi.trafficFlow({ source: "a", destination: "b" });
    expect(calledUrl(spy).searchParams.has("port")).toBe(false);
  });

  it("uses a routable hub path without encoding a leading empty segment", async () => {
    const spy = captureFetch({ dependent_count: 0 });
    await networkApi.hubDependents("/subscriptions/s/providers/microsoft.network/virtualnetworks/v");
    expect(calledPath(spy)).toContain(
      "/network/topology/hubs/subscriptions%2Fs%2Fproviders%2F",
    );
    expect(calledPath(spy)).not.toContain("/hubs/%2Fsubscriptions");
  });

  it("applies severity and category filters to gaps", async () => {
    const spy = captureFetch({ gaps: [], intended_design_declared: false, summary: {} });
    await networkApi.gaps({ environment: ["prod"] }, { severity: "critical", category: "firewall_bypass" });
    const url = calledUrl(spy);
    expect(url.searchParams.get("severity")).toBe("critical");
    expect(url.searchParams.get("category")).toBe("firewall_bypass");
    expect(url.searchParams.getAll("environment")).toEqual(["prod"]);
  });

  it("applies filters to rule findings", async () => {
    const spy = captureFetch({ findings: [], summary: {} });
    await networkApi.ruleFindings({}, { severity: "high" });
    const url = calledUrl(spy);
    expect(url.pathname).toBe("/api/v1/network/rule-findings");
    expect(url.searchParams.get("severity")).toBe("high");
  });

  it("requests firewall bypass under the current scope", async () => {
    const spy = captureFetch({ gaps: [], count: 0 });
    await networkApi.firewallBypass({ subscription: ["sub-a"] });
    const url = calledUrl(spy);
    expect(url.pathname).toBe("/api/v1/network/firewall-bypass");
    expect(url.searchParams.getAll("subscription")).toEqual(["sub-a"]);
  });

  it("requests the design policy under the current scope", async () => {
    const spy = captureFetch({ rules: [] });
    await networkApi.policy({ subscription: ["sub-a"] });
    const url = calledUrl(spy);
    expect(url.pathname).toBe("/api/v1/network/policy");
    expect(url.searchParams.getAll("subscription")).toEqual(["sub-a"]);
  });

  it("sends a PATCH with the rule changes when updating the design policy", async () => {
    const spy = captureFetch({ rules: [] });
    await networkApi.updatePolicy({
      rules: [{ rule_id: "internet-via-firewall", name: "x", enabled: false }],
    });
    const apiCall = spy.mock.calls.find(([input]) => String(input).includes("/api/v1/"));
    expect(apiCall).toBeDefined();
    const [input, init] = apiCall as [RequestInfo | URL, RequestInit];
    expect(String(input)).toContain("/api/v1/network/policy");
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(String(init?.body))).toEqual({
      rules: [{ rule_id: "internet-via-firewall", name: "x", enabled: false }],
    });
  });
});
