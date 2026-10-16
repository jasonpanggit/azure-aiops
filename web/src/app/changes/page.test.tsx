import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider, useScope } from "@/lib/scope-context";
import type { ScopeSelection } from "@/lib/scope";
import { scopedBookmark } from "@/lib/scope";
import type { ChangeObservation, ChangeObservationFeed, Envelope } from "@/lib/types";

const mocks = vi.hoisted(() => ({
  observations: vi.fn(), incidents: vi.fn(), push: vi.fn(), query: "",
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.query),
  useRouter: () => ({ push: mocks.push }),
}));
vi.mock("@/lib/services", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/services")>();
  return { ...actual, operationsApi: { ...actual.operationsApi, changeObservations: mocks.observations, incidents: mocks.incidents } };
});
vi.mock("@/components/ui/CopilotInsights", () => ({ CopilotInsights: () => null }));
vi.mock("@/components/ui/CopilotDrawer", () => ({
  CopilotDrawer: ({ snapshot, contextLabel }: { snapshot: unknown; contextLabel: string }) =>
    <output aria-label={`${contextLabel} snapshot`}>{JSON.stringify(snapshot)}</output>,
}));

import ChangesPage from "./page";
import { ChangeObservations } from "@/components/ChangeObservations";

const row: ChangeObservation = {
  observation_id: "observed-1", change_id: "CHG-1", change_type: "Update",
  summary: "Observed TLS setting changed", category: "Security", source: "Fixture projection",
  changed_at: "2026-10-16T12:00:00Z", resource_name: "fixture-resource", application: "Payments",
  business_service: "Checkout", environment: "production",
  configuration: {
    basis: "change_states", withheld_field_count: 2,
    fields: [
      { field: "httpsOnly", before: { status: "reported", value: false }, after: { status: "reported", value: true }, comparison: "changed" },
      { field: "minimumTlsVersion", before: { status: "unreported" }, after: { status: "withheld" }, comparison: "not_comparable" },
    ],
  },
};
function response(rows = [row], total = rows.length): Envelope<ChangeObservationFeed> {
  return {
    data: {
      observations: rows, authorized_count: 100, extent: "loaded_change_projection", read_only: true,
      facets: { category: ["Security", "Network"], source: ["Fixture projection"] },
      facet_metadata: { category: { total: 2, returned: 2, truncated: false }, source: { total: 1, returned: 1, truncated: false } },
    },
    evidence: [{ source_engine: "fixture", source_table: "independent", timestamp: row.changed_at, confidence: "unknown", freshness: "unknown" }],
    scope: {}, knowledge_version: "", warnings: [],
    pagination: { offset: 0, limit: 25, total, next_offset: total > 25 ? 25 : null },
  };
}
function subject(scope: ScopeSelection = {}, children = <ChangeObservations />) {
  return <ScopeProvider initialScope={scope}>{children}</ScopeProvider>;
}
function SwitchScope() {
  const { setScope } = useScope();
  return <button onClick={() => setScope({ subscription: ["new-sub"] })}>Switch scope</button>;
}

describe("Independent change observations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.query = "";
    window.history.replaceState({}, "", "/changes");
    mocks.observations.mockResolvedValue(response());
    mocks.incidents.mockRejectedValue(new Error("Incident provider deferred"));
  });

  it("keeps the independent feed usable when incident timelines are unavailable", async () => {
    render(subject({}, <ChangesPage />));
    expect(await screen.findByRole("heading", { name: row.summary })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Incident timeline associations unavailable" })).toBeInTheDocument();
    expect(screen.getByText(/1 matching observations in 100 authorized projection rows/)).toBeInTheDocument();
    const snapshot = screen.getByLabelText("Independent change observations snapshot").textContent;
    expect(snapshot).toContain("observed_change");
    expect(snapshot).not.toContain('"confirmed_cause":true');
    expect(snapshot).not.toContain('"status":"fresh"');
    expect(snapshot).not.toContain("incident_id");
  });

  it("restores a directly opened scoped bookmark before either provider reads", async () => {
    mocks.query = "subscription=sub-1&business_service=Checkout";
    render(subject({}, <ChangesPage />));
    await screen.findByRole("heading", { name: row.summary });
    expect(mocks.observations).toHaveBeenCalledWith(
      { subscription: ["sub-1"], business_service: ["Checkout"] }, expect.any(Object), expect.any(AbortSignal),
    );
    expect(mocks.incidents).toHaveBeenCalledWith({ subscription: ["sub-1"], business_service: ["Checkout"] });
    expect(screen.getByText(/Effective view scope:/)).toHaveTextContent("subscription: sub-1");
  });

  it("rejects a bookmark outside the selected context without reading either source", async () => {
    mocks.query = "subscription=other";
    render(subject({ subscription: ["selected"] }, <ChangesPage />));
    expect(screen.getByRole("heading", { name: "Change bookmark scope unavailable" })).toBeInTheDocument();
    expect(mocks.observations).not.toHaveBeenCalled();
    expect(mocks.incidents).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Use current operating context" })).toHaveAttribute("href", "/changes?subscription=selected");
  });

  it("retains actual false values and explicitly unreported/withheld states", async () => {
    render(subject());
    await screen.findByRole("heading", { name: row.summary });
    fireEvent.click(screen.getByText("Compare reported configuration states"));
    const table = screen.getByRole("table");
    expect(within(table).getByText("false")).toBeInTheDocument();
    expect(within(table).getByText("true")).toBeInTheDocument();
    expect(within(table).getByText("Changed")).toBeInTheDocument();
    expect(within(table).getByText("Unreported")).toBeInTheDocument();
    expect(within(table).getByText("Withheld: unsupported value")).toBeInTheDocument();
    expect(within(table).getByText("Not comparable")).toBeInTheDocument();
    expect(screen.getByText("2 other property names withheld.")).toBeInTheDocument();
  });

  it("keeps maximum-width multilingual source text and all safe comparison fields within contextual row bounds", async () => {
    const text = "\u4e2d".repeat(512);
    const fields = [
      "publicNetworkAccess", "encryption", "minimumTlsVersion", "httpsOnly", "allowBlobPublicAccess", "enableSoftDelete", "sku", "vmSize",
      "properties.publicNetworkAccess", "properties.encryption", "properties.minimumTlsVersion", "properties.httpsOnly",
      "properties.allowBlobPublicAccess", "properties.enableSoftDelete", "properties.hardwareProfile.vmSize", "sku.name",
    ];
    mocks.observations.mockResolvedValue(response([{
      ...row, summary: text, resource_name: text, business_service: text, environment: text.slice(0, 128),
      source: text.slice(0, 256), change_id: text.slice(0, 256),
      configuration: { ...row.configuration, fields: fields.map(field => ({
        field, comparison: "changed", before: { status: "reported", value: "Standard_D999zzzz_v99" },
        after: { status: "reported", value: "Standard_D999zzzz_v98" },
      })) },
    }]));
    render(subject());
    expect(await screen.findByRole("heading", { name: text })).toBeInTheDocument();
    const snapshot = screen.getByLabelText("Independent change observations snapshot").textContent;
    expect(snapshot).toContain('"text_truncated":true');
    expect(snapshot).toContain("properties.hardwareProfile.vmSize");
  });

  describe("Scope bookmark narrowing", () => {
    it("preserves constraints, narrows repeated values case-insensitively, and never mutates the selected scope", () => {
      const selected = { subscription: ["a", "b"], owner: ["Owner"] };
      expect(scopedBookmark(new URLSearchParams("subscription=B&subscription=b&environment=prod"), selected))
        .toEqual({ subscription: ["b"], owner: ["Owner"], environment: ["prod"] });
      expect(selected.subscription).toEqual(["a", "b"]);
    });
    it.each(["subscription=", "subscription=a&subscription=outside", "owner=%0Ainvalid"])("fails invalid or broadening bookmarks (%s)", query => {
      expect(() => scopedBookmark(new URLSearchParams(query), { subscription: ["a"] })).toThrow();
    });
  });

  it("restores bookmark filters and emits scoped, canonical continuation on submit", async () => {
    mocks.query = "change_q=Checkout&change_category=Security&change_order=oldest&change_page=2&change_source=Fixture+projection";
    render(subject({ subscription: ["sub-1"] }));
    await screen.findByRole("heading", { name: row.summary });
    expect(screen.getByLabelText("Category")).toHaveValue("Security");
    expect(mocks.observations).toHaveBeenCalledWith(
      { subscription: ["sub-1"] }, expect.objectContaining({ q: "Checkout", offset: "50", order: "oldest" }), expect.any(AbortSignal),
    );
    fireEvent.change(screen.getByLabelText("Find observed changes"), { target: { value: "new query" } });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "Network" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply change filters" }));
    const query = new URL(mocks.push.mock.calls[0][0], "http://localhost").searchParams;
    expect(query.get("subscription")).toBe("sub-1");
    expect(query.get("change_q")).toBe("new query");
    expect(query.get("change_category")).toBe("Network");
    expect(query.has("change_page")).toBe(false);
    expect(screen.getByRole("link", { name: "Clear change filters" })).toHaveAttribute("href", "/changes?subscription=sub-1");
  });

  it.each(["change_page=no", "change_page=-1", "change_order=random", "change_q=a&change_q=b"])("rejects invalid bookmarks without a success-shaped default (%s)", async query => {
    mocks.query = query;
    render(subject());
    expect(await screen.findByRole("heading", { name: "Independent changes unavailable" })).toBeInTheDocument();
    expect(mocks.observations).not.toHaveBeenCalled();
    expect(screen.queryByText(/matching observations in/)).not.toBeInTheDocument();
  });

  it("uses full server totals for paging and does not treat an out-of-range page as an empty source", async () => {
    mocks.observations.mockResolvedValue(response([row], 60));
    const view = render(subject());
    await screen.findByRole("heading", { name: row.summary });
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(mocks.push.mock.calls[0][0]).toContain("change_page=1");
    mocks.query = "change_page=4";
    mocks.observations.mockResolvedValue(response([], 60));
    view.rerender(subject());
    expect(await screen.findByRole("heading", { name: "No matching observations in the loaded projection" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review previous change page" })).toBeInTheDocument();
    expect(screen.queryByText(/Showing 101/)).not.toBeInTheDocument();
  });

  it("restores a different URL query and immediately drops observations and late responses", async () => {
    const view = render(subject());
    await screen.findByRole("heading", { name: row.summary });
    let finish!: (value: Envelope<ChangeObservationFeed>) => void;
    mocks.observations.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    mocks.query = "change_q=earlier";
    view.rerender(subject());
    expect(screen.queryByRole("heading", { name: row.summary })).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.observations).toHaveBeenCalledTimes(2));
    mocks.query = "";
    mocks.observations.mockResolvedValue(response([{ ...row, summary: "Current URL observation" }]));
    view.rerender(subject());
    await screen.findByRole("heading", { name: "Current URL observation" });
    await act(async () => { finish(response([{ ...row, summary: "Late old URL observation" }])); });
    expect(screen.queryByText("Late old URL observation")).not.toBeInTheDocument();
  });

  it("discards the old scope immediately even while the new source is pending", async () => {
    render(subject({}, <><SwitchScope /><ChangeObservations /></>));
    await screen.findByRole("heading", { name: row.summary });
    mocks.observations.mockImplementation(() => new Promise(() => undefined));
    fireEvent.click(screen.getByRole("button", { name: "Switch scope" }));
    expect(screen.queryByRole("heading", { name: row.summary })).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.observations).toHaveBeenLastCalledWith(
      { subscription: ["new-sub"] }, expect.any(Object), expect.any(AbortSignal),
    ));
  });

  it("keeps timeline evidence available when the independent source fails", async () => {
    mocks.observations.mockRejectedValue(new Error("Change projection deferred"));
    mocks.incidents.mockResolvedValue({
      ...response([]), data: { incidents: [{
        incident: { incident_id: "incident-1", title: "Authorized incident" },
        blast_radius: { business_services: ["Checkout"] },
        timeline: [{ event_id: "event-1", event_type: "change", summary: "Timeline-only association", timestamp: row.changed_at, source: "Legacy fixture", evidence: [] }],
      }] },
    });
    render(subject({ subscription: ["sub-1"] }, <ChangesPage />));
    expect(await screen.findByRole("heading", { name: "Independent changes unavailable" })).toBeInTheDocument();
    expect(await screen.findByText("Timeline-only association")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Authorized incident" })).toHaveAttribute("href", "/situations/incident-1?subscription=sub-1");
  });
});
