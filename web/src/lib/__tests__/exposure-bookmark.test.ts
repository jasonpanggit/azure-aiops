import { describe, expect, it } from "vitest";
import {
  EXPOSURE_COLLECTION_QUERY_KEYS,
  legacyExposureBookmark,
  encodeExposureQueryState,
  parseExposureQueryState,
} from "../exposure-query-state";

describe("legacy Exposure bookmarks", () => {
  it("translates known historical names and preserves repeated subscriptions", () => {
    const { query, translatedNames } = legacyExposureBookmark({
      search: "kernel", subscription_id: ["sub-a", "sub-b"], source: "defender",
      status: "open", sort: "severity", direction: "asc", pageSize: "25",
    });
    expect(Object.fromEntries(query)).toMatchObject({
      q: "kernel", source_family: "defender", current_state: "open",
      sort_by: "severity", sort_direction: "asc", page_size: "25",
    });
    expect(query.getAll("subscription")).toEqual(["sub-a", "sub-b"]);
    expect(translatedNames).toContain("search");
  });

  it("always prefers canonical parameters even when blank or in a different order", () => {
    for (const input of [
      { search: "legacy", q: "canonical" },
      { q: "canonical", search: "legacy" },
    ]) expect(legacyExposureBookmark(input).query.getAll("q")).toEqual(["canonical"]);
    expect(legacyExposureBookmark({ q: "", search: "legacy" }).query.has("q")).toBe(false);
  });

  it("rejects cursor/origin and malformed values without leaking them into telemetry", () => {
    const result = legacyExposureBookmark({
      cursor: "private", origin: "//evil.example", privateSecretName: "secret",
      search: "x".repeat(2049), q: ["valid", "bad\nvalue", "\u0000", ""],
    });
    expect(result.query.toString()).toBe("q=valid");
    expect(result.discardedKeyCount).toBe(3);
    expect(result.translatedNames).toEqual(["search"]);
    expect(JSON.stringify({ ...result, query: undefined })).not.toContain("privateSecretName");
  });

  it.each(Array.from(EXPOSURE_COLLECTION_QUERY_KEYS))("retains the shared %s contract", key => {
    expect(legacyExposureBookmark({ [key]: "value" }).query.get(key)).toBe("value");
  });

  it("keeps serializer parameters within the centralized bookmark contract", () => {
    const state = parseExposureQueryState(new URLSearchParams(
      "q=kernel&severity=high&deployment_state=running&source_state=complete&weakness_id=CVE-2026-1"
      + "&sort_by=severity&sort_direction=asc&page_size=25&target=asset&drawer=details&generation=gen",
    ), { authorizedScope: {} });
    for (const key of Array.from(encodeExposureQueryState(state).keys())) {
      expect(EXPOSURE_COLLECTION_QUERY_KEYS.has(key), key).toBe(true);
    }
  });
});
