import { afterEach, describe, expect, it, vi } from "vitest";

import scenario from "../../../../tests/fixtures/exposure_authoritative.json";
import {
  advanceExposureCursor,
  createExposureSearchCommitter,
  encodeExposureQueryState,
  exposureRestartFromError,
  parseExposureQueryState,
  retreatExposureCursor,
  toExposureApiSearchParams,
  updateExposureQueryState,
} from "@/lib/exposure-query-state";
import { vulnerabilityApi } from "@/lib/services";
import { ApiError } from "@/lib/types";

const AUTHORIZED_SCOPE = {
  subscription: scenario.scope.authorized_subscriptions,
  subscription_connection: scenario.scope.connections
    .filter((connection) => connection.authorized)
    .map((connection) => connection.connection_id),
} as const;

function captureFetch(body: unknown) {
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

function apiUrl(spy: ReturnType<typeof captureFetch>): URL {
  const call = spy.mock.calls.find(([input]) =>
    String(input).includes("/api/v1/"),
  );
  if (!call) throw new Error("Expected an Operations API request");
  return new URL(String(call[0]));
}

describe("Exposure query state", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("anchors web query fixtures to the shared backend scope and generation", () => {
    expect(scenario.scope.authorized_subscriptions).toHaveLength(2);
    expect(scenario.scope.unauthorized_subscriptions).toHaveLength(1);
    expect(scenario.cursor_case.page_size).toBe(50);
    expect(scenario.cursor_case.row_count).toBe(101);
  });

  it("round-trips supported scope, filters, sort, page, target, drawer, and generation canonically", () => {
    const params = new URLSearchParams();
    params.append("subscription", scenario.scope.authorized_subscriptions[1]);
    params.append("subscription", scenario.scope.authorized_subscriptions[0]);
    params.append("subscription_connection", "connection-defender-west");
    params.set("q", "  CVE-2026  ");
    params.set("severity", "CRITICAL");
    params.set("target_kind", "container_image");
    params.set("source_family", "defender");
    params.set("current_state", "OPEN");
    params.set("sla_state", "overdue");
    params.set("completeness", "partial");
    params.set("active", "true");
    params.set("sla_overdue", "false");
    params.set("sort_by", "severity");
    params.set("sort_direction", "asc");
    params.set("page_size", "100");
    params.set("cursor", "opaque.+/cursor==");
    params.append("cursor_back", "opaque.previous.1");
    params.append("cursor_back", "opaque.previous.2");
    params.set("page", "4");
    params.set("target", "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm-a");
    params.set("drawer", "evidence");
    params.set("generation", scenario.read_model_generation_id);

    const state = parseExposureQueryState(params, {
      authorizedScope: AUTHORIZED_SCOPE,
    });
    const encoded = encodeExposureQueryState(state);
    const reparsed = parseExposureQueryState(encoded, {
      authorizedScope: AUTHORIZED_SCOPE,
    });

    expect(reparsed).toEqual(state);
    expect(encoded.getAll("subscription")).toEqual(
      [...scenario.scope.authorized_subscriptions].sort(),
    );
    expect(encoded.get("q")).toBe("CVE-2026");
    expect(encoded.get("severity")).toBe("critical");
    expect(encoded.getAll("cursor_back")).toEqual([
      "opaque.previous.1",
      "opaque.previous.2",
    ]);
  });

  it("rejects unknown, invalid, and unauthorized URL values instead of forwarding them", async () => {
    const params = new URLSearchParams({
      subscription: scenario.scope.unauthorized_subscriptions[0],
      severity: "DROP TABLE findings",
      target_kind: "virtual_machine",
      active: "yes",
      page_size: "10000",
      sort_by: "tenant_id",
      sort_direction: "sideways",
      cursor: "",
      evil: "forward-me",
    });
    const state = parseExposureQueryState(params, {
      authorizedScope: AUTHORIZED_SCOPE,
    });

    expect(state.scope).toEqual({
      subscription: [...scenario.scope.authorized_subscriptions].sort(),
      subscription_connection: [
        "connection-aum-east",
        "connection-defender-west",
      ],
    });
    expect(state.filters).toEqual({});
    expect(state.sort).toEqual({
      field: "priority_score",
      direction: "desc",
    });
    expect(state.pageSize).toBe(50);

    const responseBody = {
      data: {
        total_count: 1,
        items: [{ exposure_id: "exposure-1" }],
        next_cursor: null,
        generation: scenario.read_model_generation_id,
        applied: {
          scope: state.scope,
          filters: [],
          sort: state.sort,
        },
        completeness: { state: "complete" },
        freshness: { state: "current" },
        contract: {
          version: "1.0.0",
          query: {
            scope: state.scope,
            generation: scenario.read_model_generation_id,
            filters: [],
            sort: state.sort,
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
            finding_count: "count",
            priority_score: "score",
            secure_score: "percent",
            sla_age: "seconds",
            sla_target: "seconds",
            workload_count: "count",
          },
          completeness: {
            state: "complete",
            represented: 1,
            total: 1,
            excluded: 0,
          },
          freshness: {
            state: "current",
            thresholds: [{
              source_family: "aum",
              threshold_seconds: 3600,
            }],
          },
          evidence_refs: [{
            source_family: "aum",
            source_id: "finding-1",
          }],
          deep_link_action: {
            action_id: "open_exposure_detail",
            kind: "deep_link",
            path_field: "detail_path",
            fallback_path_template: "/exposure/{target_kind}/{exposure_id}",
          },
          safe_error: null,
        },
      },
      evidence: [{
        source_engine: "fabric_sql",
        source_table: "gold_exposure_facts",
        timestamp: "2026-09-06T08:00:00Z",
        confidence: "high",
        freshness: "fresh",
        freshness_source_family: "aum",
        freshness_threshold_seconds: 3600,
      }],
      scope: state.scope,
      knowledge_version: scenario.read_model_generation_id,
      pagination: { limit: 50, total: 1, next_cursor: null },
    };
    const fetchSpy = captureFetch(responseBody);

    const response = await vulnerabilityApi.exposureItems(state);

    expect(response).toEqual(responseBody);
    expect(response.data.contract.counts).toEqual({
      unit: "findings",
      returned: 1,
      represented: 1,
      total: 1,
      excluded: 0,
    });
    expect(response.evidence[0]).toMatchObject({
      freshness_source_family: "aum",
      freshness_threshold_seconds: 3600,
    });
    const url = apiUrl(fetchSpy);
    expect(url.pathname).toBe("/api/v1/vulnerabilities/exposure/items");
    expect(url.searchParams.getAll("subscription")).toEqual(
      [...scenario.scope.authorized_subscriptions].sort(),
    );
    expect(url.searchParams.has("evil")).toBe(false);
    expect(url.searchParams.has("target")).toBe(false);
    expect(url.searchParams.has("drawer")).toBe(false);
    expect(url.searchParams.has("generation")).toBe(false);
    expect(url.searchParams.get("page_size")).toBe("50");
  });

  it("forwards a validated generation to the bounded API", () => {
    const state = parseExposureQueryState(
      new URLSearchParams({ generation: scenario.read_model_generation_id }),
      { authorizedScope: AUTHORIZED_SCOPE },
    );

    expect(toExposureApiSearchParams(state).get("generation")).toBe(
      scenario.read_model_generation_id,
    );
  });

  it("forwards a weakness identifier to the bounded API", () => {
    const state = parseExposureQueryState(
      new URLSearchParams(
        `weakness_id=CVE-2026-0001&generation=${scenario.read_model_generation_id}`,
      ),
      { authorizedScope: AUTHORIZED_SCOPE },
    );

    expect(toExposureApiSearchParams(state).get("weakness_id")).toBe(
      "CVE-2026-0001",
    );
  });

  it("labels Overview as the parent of Overview-origin details", async () => {
    const { exposureDetailParentLabel } = await import(
      "@/lib/exposure-query-state"
    );
    expect(exposureDetailParentLabel("/exposure")).toBe("Overview");
  });

  it.each([
    ["scope", { scope: { subscription: [scenario.scope.authorized_subscriptions[0]] } }],
    ["search", { filters: { search: "CVE-2026-1001" } }],
    ["filters", { filters: { severity: "high" } }],
    ["sort", { sort: { field: "target_id", direction: "asc" } }],
    ["page size", { pageSize: 25 }],
  ] as const)("resets cursor history when %s changes", (_label, patch) => {
    const initial = parseExposureQueryState(
      new URLSearchParams({
        cursor: "opaque-current",
        cursor_back: "opaque-previous",
        page: "3",
      }),
      { authorizedScope: AUTHORIZED_SCOPE },
    );

    const updated = updateExposureQueryState(initial, patch);

    expect(updated.cursor).toBeNull();
    expect(updated.cursorHistory).toEqual([]);
    expect(updated.page).toBe(1);
  });

  it("keeps opaque next and previous cursor history without decoding tokens", () => {
    const initial = parseExposureQueryState(new URLSearchParams(), {
      authorizedScope: AUTHORIZED_SCOPE,
    });
    const pageTwo = advanceExposureCursor(initial, "opaque.+/first==");
    const pageThree = advanceExposureCursor(pageTwo, "opaque.+/second==");

    expect(pageThree.cursor).toBe("opaque.+/second==");
    expect(pageThree.cursorHistory).toEqual(["opaque.+/first=="]);
    expect(pageThree.page).toBe(3);

    const backToTwo = retreatExposureCursor(pageThree);
    const backToOne = retreatExposureCursor(backToTwo);
    expect(backToTwo.cursor).toBe("opaque.+/first==");
    expect(backToOne.cursor).toBeNull();
    expect(backToOne.page).toBe(1);
  });

  it("debounces search by 300ms while Enter submits immediately", () => {
    vi.useFakeTimers();
    const commit = vi.fn();
    const controller = createExposureSearchCommitter(commit);

    controller.schedule("CVE-2026");
    vi.advanceTimersByTime(299);
    expect(commit).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(commit).toHaveBeenLastCalledWith("CVE-2026");

    controller.schedule("CVE-2026-1001");
    controller.submit("CVE-2026-1001");
    expect(commit).toHaveBeenLastCalledWith("CVE-2026-1001");
    vi.advanceTimersByTime(300);
    expect(commit).toHaveBeenCalledTimes(2);
    controller.dispose();
  });

  it("turns an expired or evicted generation conflict into an explicit restart state", () => {
    const error = new ApiError(
      409,
      "conflict",
      "Exposure snapshot is no longer readable; restart without a cursor",
      {
        reason_code: "exposure_generation_expired",
        restart_required: true,
        generation: "generation-expired",
      },
    );

    expect(exposureRestartFromError(error)).toEqual({
      required: true,
      reason: "exposure_generation_expired",
      generation: "generation-expired",
    });
    expect(exposureRestartFromError(new Error("ordinary failure"))).toEqual({
      required: false,
      reason: "",
      generation: "",
    });
  });
});
