import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SCOPE_DIMENSIONS } from "@/lib/scope";
import type { CanonicalCopilotCitation, CanonicalSynthesisClaim } from "@/lib/types";
import { CopilotFindings } from "./CopilotFindings";

const resource = "/subscriptions/sub-a/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/vm1";
const citation: CanonicalCopilotCitation = { citation_id: "tool:read:0", source: "inventory", status: "ok", resource_id: resource, observed_at: "2020-01-01T00:00:00Z", query_version: "query-v1" };
const claim: CanonicalSynthesisClaim = { finding_id: "finding-1", summary: "Recorded resource observation", confidence: "medium", freshness: "stale", evidence_refs: [citation.citation_id], uncertainty: ["No live probe"] };
const threadId = `thr-${"a".repeat(32)}`;

describe("Typed Copilot explanatory actions", () => {
  it("shows structured evidence and scope-preserving internal destinations without source requery", () => {
    const scope = Object.fromEntries(SCOPE_DIMENSIONS.map(key => [key, [`${key}-a`, `${key}-b`]]));
    render(<CopilotFindings claims={[claim]} citations={[citation]} scope={scope} threadId={threadId} threadRevision={4} />);
    expect(screen.getByText("Confidence: medium")).toBeVisible();
    expect(screen.getByText("Source freshness: stale")).toBeVisible();
    expect(screen.getByText("No live probe")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: `Inspect source ${citation.citation_id}` }));
    const source = screen.getByRole("region", { name: "Selected finding source" });
    expect(within(source).getByText(resource)).toBeVisible();
    expect(within(source).getByText("query-v1")).toBeVisible();
    expect(within(source).getByText(/no publication generation is inferred/)).toBeVisible();
    const asset = new URL(screen.getByRole("link", { name: "Review current asset vm1" }).getAttribute("href")!, "https://local");
    expect(asset.pathname).toBe("/inventory/assets");
    expect(asset.searchParams.get("resource_id")).toBe(resource);
    const retained = new URL(screen.getByRole("link", { name: /Review retained evidence/ }).getAttribute("href")!, "https://local");
    expect(retained.searchParams.get("thread_id")).toBe(threadId);
    expect(retained.searchParams.get("thread_revision")).toBe("4");
    for (const key of SCOPE_DIMENSIONS) {
      expect(asset.searchParams.getAll(key)).toEqual(scope[key]);
      expect(retained.searchParams.getAll(key)).toEqual(scope[key]);
    }
  });

  it.each(["missing", "ambiguous", "denied", "unavailable"])("withholds actions for %s evidence", state => {
    const citations = state === "missing" ? [] : state === "ambiguous" ? [citation, citation] : [{ ...citation, status: state }];
    render(<CopilotFindings claims={[claim]} citations={citations} scope={{}} />);
    expect(screen.getByText(/Navigation for this finding is withheld/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /Inspect source/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it.each(["https://evil.example/path", "javascript:alert(1)", "/not-an-arm-resource", `${resource}\n`])("never links unsafe or unsupported source identity %s", resource_id => {
    render(<CopilotFindings claims={[claim]} citations={[{ ...citation, resource_id }]} scope={{}} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("No supported exact asset destination supplied.")).toBeVisible();
  });

  it("does not infer structured claims from an answer or fabricate retained identity", () => {
    render(<CopilotFindings claims={[]} citations={[citation]} scope={{}} threadId="invalid" threadRevision={0} />);
    expect(screen.getByText("No structured findings returned")).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
