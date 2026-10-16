import { describe, expect, it, vi } from "vitest";
import { apiRequest } from "./api-client";
import { predeployApi } from "./services";

vi.mock("./api-client", () => ({ apiRequest: vi.fn() }));

describe("retained assessment API boundaries", () => {
  it("preserves repeated scope dimensions and AbortSignal on all operations", () => {
    const scope = { subscription: ["a", "b"], region: ["eastus"], owner: ["sre"] };
    const signal = new AbortController().signal;
    predeployApi.retained(scope, signal);
    predeployApi.retain(scope, "a".repeat(32), "b".repeat(64), 2, signal);
    predeployApi.removeRetained(scope, "a".repeat(32), 3, signal);
    predeployApi.compareRetained(scope, "a".repeat(32), "c".repeat(32), signal);
    const calls = vi.mocked(apiRequest).mock.calls;
    expect(calls).toHaveLength(4);
    for (const [, options] of calls) {
      expect(options?.signal).toBe(signal);
      if (!(options?.query instanceof URLSearchParams)) throw new Error("Expected scoped URLSearchParams");
      const query = options.query;
      expect(query.getAll("subscription")).toEqual(["a", "b"]);
      expect(query.getAll("region")).toEqual(["eastus"]);
      expect(query.getAll("owner")).toEqual(["sre"]);
    }
    expect(calls[1][1]?.body).toEqual({ assessment_id: "a".repeat(32), artifact_sha256: "b".repeat(64), expected_revision: 2 });
    expect(calls[2][1]?.body).toEqual({ assessment_id: "a".repeat(32), expected_revision: 3 });
    expect(calls[3][1]?.method).toBeUndefined();
  });
});
