import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PortfolioService, ServicePortfolioHistory as History, ServicePortfolioObservation } from "@/lib/types";
import { comparePortfolio, portfolioDelta } from "@/lib/portfolio-comparison";
import { ServicePortfolioHistory } from "./ServicePortfolioHistory";

const api = vi.hoisted(() => ({ history: vi.fn(), capture: vi.fn() }));
vi.mock("@/lib/services", () => ({ servicePortfolioApi: api }));
const scope = { subscription: ["sub-a"] };
const row = (name: string, count = 1): PortfolioService => ({
  service_key: name, kind: "service", name, connection_rows: 2, mapped_rows: count,
  missing_owner: 2 - count, missing_support_team: 0, missing_environment: 0,
  subscription_count: 1, incident_associations: 2 - count, critical_associations: 0,
});
const observation = (index: number): ServicePortfolioObservation => ({
  observation_id: `${index}1111111-1111-4111-8111-111111111111`,
  captured_at: `2026-10-${15 + index}T06:00:00Z`,
  services: [row("Payments", index + 1)],
  sources: (["connections", "incidents"] as const).map(id => ({
    id, started_at: "2026-10-15T05:59:00Z", finished_at: "2026-10-15T06:00:00Z",
    observed_at: [], source_tables: ["fixture-only"], knowledge_version: "", reported_freshness: ["unknown"],
    loaded: 2, total: id === "incidents" ? 350 : 2, partial: id === "incidents", warning_count: 0,
  })),
});
const empty: History = { schema_version: 1, actor: "reader", scope, revision: 0, observations: [] };
const history: History = { ...empty, revision: 2, observations: [observation(0), observation(1)] };
const envelope = (data: History) => ({ data, evidence: [], scope, warnings: [] });

describe("Retained service portfolio", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.history.mockResolvedValue(envelope(history));
    api.capture.mockResolvedValue(envelope({ ...history, revision: 3,
      observations: [...history.observations, { ...observation(2), services: [row("Payments", 2)] }] }));
  });

  it("compares actual counts, exposes collection extents, and preserves scoped navigation", async () => {
    render(<ServicePortfolioHistory scope={scope} />);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("+1")).toBeInTheDocument();
    expect(within(table).getByText("-1")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: "Payments" })).toHaveAttribute("href", "/services/Payments?subscription=sub-a");
    fireEvent.click(screen.getByText("Inspect both portfolio source extents and freshness"));
    expect(screen.getAllByText(/2 loaded \/ 350 reported; partial report/)).toHaveLength(2);
    expect(screen.getByText(/no automatic schedule, time-based expiry/i)).toBeInTheDocument();
    expect(api.capture).not.toHaveBeenCalled();
  });

  it("captures only with explicit action, reviewed revision and exact scope", async () => {
    render(<ServicePortfolioHistory scope={scope} />);
    await screen.findByText(/Portfolio revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Capture service portfolio" }));
    await screen.findByText(/Server portfolio retained/);
    expect(api.capture).toHaveBeenCalledWith(scope, 2);
    expect(screen.getByText(/Portfolio revision 3/)).toBeInTheDocument();
  });

  it("does not invent a baseline and withholds reversed or coincident comparisons", async () => {
    api.history.mockResolvedValueOnce(envelope(empty));
    const { unmount } = render(<ServicePortfolioHistory scope={scope} />);
    await screen.findByText(/Two retained portfolios are needed/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    unmount();
    render(<ServicePortfolioHistory scope={scope} />);
    await screen.findByText(/Portfolio revision 2/);
    fireEvent.change(screen.getByRole("combobox", { name: "Earlier portfolio" }), { target: { value: observation(1).observation_id } });
    expect(screen.getByText("Choose different portfolios in chronological order.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Later portfolio" }), { target: { value: observation(0).observation_id } });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("recovers retained state on retry without a successful capture claim", async () => {
    api.history.mockRejectedValueOnce(new Error("Storage unavailable"));
    render(<ServicePortfolioHistory scope={scope} />);
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Capture service portfolio" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload service portfolios" }));
    await screen.findByText(/Retained portfolio reloaded/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.capture).not.toHaveBeenCalled();
  });

  it("preserves the reviewed observation on capture conflict and never claims success", async () => {
    api.capture.mockRejectedValueOnce(new Error("Portfolio changed; reload"));
    render(<ServicePortfolioHistory scope={scope} />);
    await screen.findByText(/Portfolio revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Capture service portfolio" }));
    await screen.findByRole("alert");
    expect(screen.queryByText(/Server portfolio retained/)).not.toBeInTheDocument();
    expect(screen.getByText(/Portfolio revision 2/)).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("filters beyond the explicit render cap and never equates an absent label with zero", async () => {
    const left = { ...observation(0), services: Array.from({ length: 60 }, (_, i) => row(`Service ${String(i).padStart(2, "0")}`)) };
    const right = { ...observation(1), services: [...left.services.slice(1), row("New label")] };
    api.history.mockResolvedValueOnce(envelope({ ...history, observations: [left, right] }));
    render(<ServicePortfolioHistory scope={scope} />);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(51);
    expect(screen.getByText(/61 matching label comparisons/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Find service label" }), { target: { value: "Service 59" } });
    expect(within(table).getByRole("link", { name: "Service 59" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Find service label" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Only changed observations" }));
    expect(within(table).getAllByText("Not comparable")).toHaveLength(4);
    expect(within(table).queryByText("0/0 mapped")).not.toBeInTheDocument();
  });

  it("immediately discards old-scope comparison and a late capture response", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    api.capture.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const { rerender } = render(<ServicePortfolioHistory scope={scope} />);
    await screen.findByText(/Portfolio revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Capture service portfolio" }));
    await waitFor(() => expect(api.capture).toHaveBeenCalledOnce());
    const other = { subscription: ["sub-b"] };
    api.history.mockResolvedValueOnce(envelope({ ...empty, scope: other }));
    rerender(<ServicePortfolioHistory scope={other} />);
    await screen.findByText(/Portfolio revision 0/);
    await act(async () => resolve(envelope({ ...history, revision: 3 })));
    expect(screen.queryByText(/Server portfolio retained/)).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(api.history).toHaveBeenLastCalledWith(other);
  });

  it("compares semantic counts rather than property insertion order", () => {
    const same = row("Payments");
    const reordered = { ...same, ...Object.fromEntries(Object.entries(same).reverse()) };
    const comparison = comparePortfolio({ ...observation(0), services: [same] }, { ...observation(1), services: [reordered] });
    expect(comparison[0].changed).toBe(false);
    expect(portfolioDelta(null, same, "mapped_rows")).toBe("Not comparable");
  });
});
