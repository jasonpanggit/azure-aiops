import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "@/lib/api-client";
import { ApiError } from "@/lib/types";

function mockFetch(response: { status: number; body: unknown; headers?: Record<string, string> }) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: response.status >= 200 && response.status < 300,
    status: response.status,
    statusText: "",
    headers: {
      get: (key: string) => response.headers?.[key] ?? null,
    },
    json: async () => response.body,
  } as unknown as Response);
}

describe("apiRequest", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the envelope data on success", async () => {
    mockFetch({
      status: 200,
      body: { data: { id: "1" }, evidence: [], scope: {}, knowledge_version: "v1" },
    });
    const envelope = await apiRequest<{ id: string }>("/subscription-connections/1", { anonymous: true });
    expect(envelope.data).toEqual({ id: "1" });
  });

  it("throws a typed ApiError for an error contract response", async () => {
    mockFetch({
      status: 404,
      body: { error: { code: "not_found", message: "no such connection", details: {} } },
      headers: { "X-Correlation-ID": "abc-123" },
    });
    await expect(apiRequest("/subscription-connections/missing", { anonymous: true })).rejects.toMatchObject({
      code: "not_found",
      status: 404,
      correlationId: "abc-123",
    });
  });

  it("marks 501 responses as isNotImplemented", async () => {
    mockFetch({
      status: 501,
      body: {
        error: {
          code: "not_implemented",
          message: "network.topology is not implemented",
          details: { capability: "network.topology", roadmap: "Prompt 16" },
        },
      },
    });
    try {
      await apiRequest("/network/topology", { anonymous: true });
      throw new Error("expected apiRequest to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).isNotImplemented).toBe(true);
      expect((err as ApiError).details?.roadmap).toBe("Prompt 16");
    }
  });
});
