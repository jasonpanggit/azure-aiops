import { describe, expect, it } from "vitest";
import { networkReviewBookmark, networkReviewHref } from "./network-review";

const digest = "a".repeat(64);
describe("Exact Network review bookmarks", () => {
  it("distinguishes absence from malformed context without ignoring errors", () => {
    expect(networkReviewBookmark(new URLSearchParams()).present).toBe(false);
    for (const query of [
      "network_kind=gap",
      `network_kind=fix&network_finding=a&network_digest=${digest}`,
      `network_kind=gap&network_finding=a&network_digest=bad`,
      `network_kind=gap&network_finding=a&network_finding=b&network_digest=${digest}`,
      `network_kind=gap&network_finding=%0A&network_digest=${digest}`,
      `network_kind=gap&network_finding=${"a".repeat(257)}&network_digest=${digest}`,
    ]) {
      const result = networkReviewBookmark(new URLSearchParams(query));
      expect(result.present).toBe(true);
      expect(result.reference).toBeNull();
      expect(result.error).toBeTruthy();
    }
  });

  it("preserves every repeated scope dimension without source finding text", () => {
    const scope = {
      subscription: ["a", "b"], business_service: ["Payments"], application: ["Portal"],
      environment: ["prod"], owner: ["Platform"], support_team: ["SRE"],
      region: ["eastus"], criticality: ["high"], subscription_connection: ["connection-a"],
    };
    const href = networkReviewHref("rule", "rule&special", digest, scope);
    expect(href).toBeTruthy();
    const url = new URL(href!, "http://127.0.0.1");
    Object.entries(scope).forEach(([key, values]) => expect(url.searchParams.getAll(key)).toEqual(values));
    expect(networkReviewBookmark(url.searchParams).reference).toEqual({
      kind: "rule", finding_id: "rule&special", reviewed_digest: digest,
    });
    expect(Array.from(new Set(url.searchParams.keys())).sort()).toEqual([...Object.keys(scope), "network_kind", "network_finding", "network_digest"].sort());
  });

  it("withholds a handoff link when the source has no valid server digest", () => {
    expect(networkReviewHref("gap", "gap-a", undefined, {})).toBeNull();
    expect(networkReviewHref("gap", "gap-a", "invalid", {})).toBeNull();
  });
});
