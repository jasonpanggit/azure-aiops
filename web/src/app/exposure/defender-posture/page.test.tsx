import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  exposureItems: vi.fn(),
  defenderOverview: vi.fn(),
  defenderAlerts: vi.fn(),
  defenderAttackPaths: vi.fn(),
  defenderSecureScore: vi.fn(),
  defenderSecureScoreControls: vi.fn(),
  defenderPosture: vi.fn(),
  containerImageExposures: vi.fn(),
}));
const router = vi.hoisted(() => ({ replace: vi.fn() }));
const navigation = vi.hoisted(() => ({
  params: new URLSearchParams("subscription=sub-1&page_size=25"),
}));
const authorized = vi.hoisted(() => ({
  scope: { subscription: ["sub-1"] },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/exposure/defender-posture",
  useRouter: () => router,
  useSearchParams: () => navigation.params,
}));

vi.mock("@/lib/scope-context", () => ({
  useScope: () => ({ scope: authorized.scope }),
}));

vi.mock("@/lib/services", () => ({ vulnerabilityApi: api }));

import DefenderPosturePage from "./page";
import { ApiError } from "@/lib/types";

const generation = "exposure-gold-1";

function envelope(nextCursor: string | null = null) {
  const completeness = { state: "partial" as const, represented: 7, total: 7, excluded: 0 };
  const freshness = { state: "reported", as_of: "2026-09-10T04:48:09Z" };
  return {
    data: {
      total_count: 7,
      generation,
      next_cursor: nextCursor,
      applied: {
        scope: { subscription: ["sub-1"] },
        filters: [
          { field: "source_family", operator: "eq", value: "defender_image" },
          { field: "target_kind", operator: "eq", value: "container_image" },
        ],
        sort: { field: "priority_score", direction: "desc" },
      },
      completeness,
      freshness,
      contract: {
        version: "1.0.0",
        query: {
          scope: { subscription: ["sub-1"] },
          generation,
          filters: [],
          sort: { field: "priority_score", direction: "desc" },
          target_kind: "container_image",
        },
        counts: { unit: "findings", returned: 1, represented: 7, total: 7, excluded: 0 },
        units: { finding_count: "count" },
        completeness,
        freshness,
        evidence_refs: [],
        deep_link_action: {
          action_id: "open_exposure_detail",
          kind: "deep_link",
          path_field: "detail_path",
          fallback_path_template: "/exposure/{target_kind}/{exposure_id}",
        },
        safe_error: null,
      },
      items: [{
        exposure_id: "exposure-1",
        target_id: "digest-1",
        target_kind: "container_image",
        weakness_id: "CVE-2026-2001",
        weakness_kind: "cve",
        severity: "Critical",
        source_family: "defender_image",
        priority_score: 100,
        recommendation: "Update the affected image",
        subscription_id: "sub-1",
        connection_ids: [],
        source_families: [],
        read_model_generation_id: generation,
        completeness: "unknown",
      }],
    },
    evidence: [],
    warnings: [],
    scope: { subscription: ["sub-1"] },
    knowledge_version: generation,
    pagination: { limit: 25, total: 7, next_cursor: null },
  };
}

describe("DefenderPosturePage bounded read model", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    navigation.params = new URLSearchParams("subscription=sub-1&page_size=25");
    authorized.scope = { subscription: ["sub-1"] };
    api.exposureItems.mockResolvedValue(envelope("opaque-next-cursor"));
    for (const method of [
      "defenderOverview",
      "defenderAlerts",
      "defenderAttackPaths",
      "defenderSecureScore",
      "defenderSecureScoreControls",
      "defenderPosture",
      "containerImageExposures",
    ] as const) {
      api[method].mockRejectedValue(new Error(`${method} must not be called`));
    }
  });

  it("renders Defender image findings from one bounded SQL request", async () => {
    render(<DefenderPosturePage />);

    expect(await screen.findByRole("heading", { name: "Defender image exposure" })).toBeInTheDocument();
    expect(screen.getByLabelText("Total Defender image findings value")).toHaveTextContent("7");
    expect(screen.getByText("CVE-2026-2001")).toBeInTheDocument();
    expect(screen.getByText("Update the affected image")).toBeInTheDocument();
    expect(screen.getByText("Review only. Nothing executes from Exposure.")).toBeInTheDocument();

    expect(api.exposureItems).toHaveBeenCalledTimes(1);
    const state = api.exposureItems.mock.calls[0][0];
    expect(state.filters).toMatchObject({
      source_family: "defender_image",
      target_kind: "container_image",
    });
    for (const method of [
      "defenderOverview",
      "defenderAlerts",
      "defenderAttackPaths",
      "defenderSecureScore",
      "defenderSecureScoreControls",
      "defenderPosture",
      "containerImageExposures",
    ] as const) {
      expect(api[method]).not.toHaveBeenCalled();
    }
  });

  it("shows an honest unavailable state when the bounded request fails", async () => {
    api.exposureItems.mockRejectedValue(new Error("Defender image query unavailable"));
    render(<DefenderPosturePage />);

    expect(await screen.findByText("Defender image exposure is unavailable")).toBeInTheDocument();
  });

  it("retains generation and origin in detail links", async () => {
    render(<DefenderPosturePage />);
    await waitFor(() => expect(api.exposureItems).toHaveBeenCalled());

    expect(await screen.findByRole("link", { name: "CVE-2026-2001" })).toHaveAttribute(
      "href",
      expect.stringContaining("generation=exposure-gold-1"),
    );
    expect(screen.getByRole("link", { name: "CVE-2026-2001" })).toHaveAttribute(
      "href",
      expect.stringContaining("origin=%2Fexposure%2Fdefender-posture"),
    );
  });

  it("moves to the next bounded cursor page", async () => {
    render(<DefenderPosturePage />);
    const next = await screen.findByRole("button", { name: "Next page" });
    expect(next).toBeEnabled();

    fireEvent.click(next);

    expect(router.replace).toHaveBeenCalledWith(
      expect.stringContaining("cursor=opaque-next-cursor"),
      { scroll: false },
    );
    expect(router.replace.mock.calls[0][0]).not.toContain("cursor_back");
  });

  it("restarts after an expired generation conflict", async () => {
    navigation.params = new URLSearchParams(
      "subscription=sub-1&page_size=25&cursor=expired-cursor&page=2&generation=old-generation",
    );
    api.exposureItems.mockRejectedValue(
      new ApiError(409, "conflict", "Generation expired", {
        restart_required: true,
        reason_code: "exposure_generation_expired",
        generation: "old-generation",
      }),
    );
    render(<DefenderPosturePage />);

    fireEvent.click(await screen.findByRole("button", { name: "Restart results" }));

    const destination = router.replace.mock.calls.at(-1)?.[0] as string;
    expect(destination).not.toContain("cursor=");
    expect(destination).not.toContain("generation=");
    expect(destination).not.toContain("cursor_back");
  });

  it("clears a scope-bound cursor when authorized scope changes", async () => {
    navigation.params = new URLSearchParams(
      "subscription=sub-1&page_size=25&cursor=scope-one-cursor&page=2&generation=generation-one",
    );
    const view = render(<DefenderPosturePage />);
    await waitFor(() => expect(api.exposureItems).toHaveBeenCalled());
    router.replace.mockClear();

    authorized.scope = { subscription: ["sub-2"] };
    view.rerender(<DefenderPosturePage />);

    await waitFor(() => expect(router.replace).toHaveBeenCalled());
    const destination = router.replace.mock.calls.at(-1)?.[0] as string;
    expect(destination).toContain("subscription=sub-2");
    expect(destination).not.toContain("cursor=");
    expect(destination).not.toContain("generation=");
    expect(destination).not.toContain("cursor_back");
  });
});
