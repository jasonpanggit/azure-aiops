import { describe, expect, it } from "vitest";

import scenario from "../../../../../tests/fixtures/exposure_authoritative.json";

describe("Exposure independent source states — Wave 0", () => {
  it("uses the shared authoritative generation and source-state fixture", () => {
    expect(scenario.read_model_generation_id).toBe("exposure-generation-0001");
    expect(scenario.source_partitions.map((partition) => partition.state)).toEqual(
      expect.arrayContaining([
        "complete",
        "healthy-empty",
        "failed-with-lkg",
        "failed-without-lkg",
      ]),
    );
  });

  it.todo(
    "keeps healthy sibling sections usable when one source fails [Plan 03.1-15]",
  );
  it.todo(
    "retains last-known-good rows only for the identical authorized scope and query [Plan 03.1-15]",
  );
  it.todo(
    "clears retained rows before rendering a changed authorized scope [Plan 03.1-15]",
  );
  it.todo(
    "distinguishes loading, healthy-empty, stale, partial, and unavailable locally [Plan 03.1-15]",
  );
  it.todo(
    "keeps retry focus local and announces one progress and result update [Plan 03.1-15]",
  );
  it.todo(
    "renders all six Overview sections independently with conservative aggregate state [Plan 03.1-22]",
  );
  it.todo(
    "preserves scoped core truth when CVE or KB enrichment fails [Plan 03.1-25]",
  );
});
