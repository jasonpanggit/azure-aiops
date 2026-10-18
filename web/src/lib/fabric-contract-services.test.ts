import { describe, expect, expectTypeOf, it, vi } from "vitest";
import { SCOPE_DIMENSIONS } from "./scope";
import { fabricMedallionApi } from "./services";
import type { Envelope, FabricDatasetContract } from "./types";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api-client", () => ({ apiRequest: request, resolveApiBaseUrl: vi.fn() }));

describe("Fabric declared contract adapter", () => {
  it("encodes the exact dataset and preserves all multi-valued scope dimensions on a read", async () => {
    request.mockResolvedValue({ data: {} });
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(dimension => [dimension, ["one", "two"]]));
    await fabricMedallionApi.datasetContract("gold_custom/name", scope);
    expect(request.mock.calls.at(-1)?.[0]).toBe("/fabric-medallion/datasets/gold_custom%2Fname/contract");
    const options = request.mock.calls.at(-1)?.[1];
    expect(options.method).toBeUndefined();
    for (const dimension of SCOPE_DIMENSIONS) expect(options.query.getAll(dimension)).toEqual(["one", "two"]);
    expectTypeOf(fabricMedallionApi.datasetContract).returns.toEqualTypeOf<Promise<Envelope<FabricDatasetContract>>>();
  });
});
