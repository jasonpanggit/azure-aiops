import { describe, expect, it } from "vitest";

import scenario from "../../../../tests/fixtures/exposure_authoritative.json";

describe("Exposure query state — Wave 0", () => {
  it("anchors web query fixtures to the shared backend scope and generation", () => {
    expect(scenario.scope.authorized_subscriptions).toHaveLength(2);
    expect(scenario.scope.unauthorized_subscriptions).toHaveLength(1);
    expect(scenario.cursor_case.page_size).toBe(50);
    expect(scenario.cursor_case.row_count).toBe(101);
  });

  it.todo("resets cursor when authorized scope changes [Plan 03.1-15]");
  it.todo("resets cursor when search or filters change [Plan 03.1-15]");
  it.todo("resets cursor when sort or page size changes [Plan 03.1-15]");
  it.todo("round-trips only allowlisted canonical URL query fields [Plan 03.1-15]");
  it.todo("keeps opaque next and previous cursor history without decoding tokens [Plan 03.1-15]");
  it.todo("debounces search by 300ms while Enter submits immediately [Plan 03.1-15]");
  it.todo("rejects stale responses after a query or scope change [Plan 03.1-15]");
  it.todo("turns an expired generation into an explicit restart state [Plan 03.1-15]");
});
