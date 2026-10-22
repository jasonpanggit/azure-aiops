import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OverviewHistory as History, OverviewObservation } from "@/lib/types";
import { OverviewHistory } from "./OverviewHistory";

const api = vi.hoisted(() => ({ history: vi.fn(), capture: vi.fn() }));
vi.mock("@/lib/services", () => ({ overviewApi: api }));
const scope = { subscription: ["sub-a"] };
const envelope = (data: History) => ({ data, evidence: [], scope, warnings: [] });
const observation = (index: number): OverviewObservation => ({
  observation_id: `${index}1111111-1111-4111-8111-111111111111`,
  captured_at: `2026-10-${15 + index}T06:00:00Z`, formula_version: "overview-v1",
  critical_situations: index, exposed_findings: 3 - index, network_gaps: 0,
  sources: ["situations", "network", "exposure"].map(id => ({
    id: id as "situations" | "network" | "exposure",
    started_at: "2026-10-16T05:59:00Z", finished_at: "2026-10-16T06:00:00Z",
    observed_at: ["2026-10-15T06:00:00Z"], source_tables: ["test-only"], knowledge_version: "",
    loaded: id === "situations" ? 100 : null, total: id === "situations" ? 350 : null,
    partial: id === "situations", warning_count: 0,
  })),
});
const empty: History = { schema_version: 1, actor: "reader", scope, revision: 0, observations: [] };
const history: History = { ...empty, revision: 2, observations: [observation(0), observation(1)] };

describe("Retained Overview comparisons", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.history.mockResolvedValue(envelope(history));
    api.capture.mockResolvedValue(envelope({ ...history, revision: 3, observations: [...history.observations, observation(2)] }));
  });
  it("shows actual retained arithmetic with source extents and explicit causality boundaries", async () => {
    render(<OverviewHistory scope={scope} />);
    const region = await screen.findByRole("region", { name: "Observation count comparison, horizontally scrollable" });
    const row = within(region).getByRole("row", { name: "Loaded P1 situations 0 1 +1" });
    expect(row).toBeInTheDocument();
    expect(within(region).getByRole("row", { name: "Internet-exposed findings 3 2 -1" })).toBeInTheDocument();
    expect(screen.getByText(/A difference is not a new\/resolved-resource count/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Counts by Network gaps" })).toHaveTextContent("Earlier0Later0");
    expect(screen.getByText(/No automatic schedule, seven-day backfill/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Inspect both collection extents and source provenance"));
    expect(screen.getAllByText(/partial page; warnings 0/)).toHaveLength(2);
    expect(api.capture).not.toHaveBeenCalled();
  });
  it("does not plot an unexpected null API count as zero or invent a continuous trend", async () => {
    api.history.mockResolvedValueOnce({
      ...envelope(history),
      data: {
        ...history,
        observations: [{ ...observation(0), network_gaps: null }, observation(1)],
      },
    });
    render(<OverviewHistory scope={scope} />);
    const charts = await screen.findByRole("group", { name: "Retained count comparison charts" });
    expect(within(charts).getAllByRole("list")).toHaveLength(2);
    expect(within(charts).getByRole("list", { name: "Counts by Loaded P1 situations" })).toHaveTextContent("Earlier0Later1");
    expect(within(charts).getByRole("list", { name: "Counts by Internet-exposed findings" })).toHaveTextContent("Earlier3Later2");
    expect(within(charts).getByText(/Comparison unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/not a continuous trend/)).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
  it("captures only after an explicit action with the reviewed revision and scope", async () => {
    render(<OverviewHistory scope={scope} />);
    await screen.findByText(/History revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Capture server observation" }));
    await screen.findByText(/Server observation retained/);
    expect(api.capture).toHaveBeenCalledWith(scope, 2);
    expect(screen.getByRole("combobox", { name: "Later observation" })).toHaveValue(observation(2).observation_id);
    expect(screen.getByRole("list", { name: "Counts by Loaded P1 situations" })).toHaveTextContent("Earlier1Later2");
    fireEvent.change(screen.getByRole("combobox", { name: "Earlier observation" }), { target: { value: observation(0).observation_id } });
    expect(screen.getByRole("list", { name: "Counts by Loaded P1 situations" })).toHaveTextContent("Earlier0Later2");
    expect(screen.getByText(/History revision 3/)).toBeInTheDocument();
  });
  it("does not invent a prior baseline and rejects reversed or identical selections", async () => {
    api.history.mockResolvedValueOnce(envelope(empty));
    const { unmount } = render(<OverviewHistory scope={scope} />);
    await screen.findByText(/Two retained observations are needed/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Retained count comparison charts" })).not.toBeInTheDocument();
    unmount();
    render(<OverviewHistory scope={scope} />);
    await screen.findByText(/History revision 2/);
    fireEvent.change(screen.getByRole("combobox", { name: "Earlier observation" }), { target: { value: observation(1).observation_id } });
    expect(screen.getByText("Choose two different observations in chronological order.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Retained count comparison charts" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Later observation" }), { target: { value: observation(0).observation_id } });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Retained count comparison charts" })).not.toBeInTheDocument();
  });
  it("keeps empty history actions visible and discloses complete retention guidance on demand", async () => {
    api.history.mockResolvedValueOnce(envelope(empty));
    render(<OverviewHistory scope={scope} />);
    await screen.findByText(/History revision 0/);
    expect(screen.getByRole("button", { name: "Capture server observation" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reload observations" })).toBeEnabled();
    const summary = screen.getByText("Retention and source limitations");
    const disclosure = summary.closest("details")!;
    expect(disclosure).not.toHaveAttribute("open");
    fireEvent.click(summary);
    expect(disclosure).toHaveAttribute("open");
    expect(within(disclosure).getByText(/All source reads must succeed or no observation is saved/)).toBeVisible();
    expect(api.capture).not.toHaveBeenCalled();
    fireEvent.click(summary);
    expect(disclosure).not.toHaveAttribute("open");
  });
  it("recovers history after a read error without fabricating a capture", async () => {
    api.history.mockRejectedValueOnce(new Error("Storage unavailable"));
    render(<OverviewHistory scope={scope} />);
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Capture server observation" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload observations" }));
    await screen.findByText(/Retained observations reloaded/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(api.capture).not.toHaveBeenCalled();
  });
  it("retains reviewed comparison on capture conflict without claiming success", async () => {
    api.capture.mockRejectedValueOnce(new Error("History changed; reload"));
    render(<OverviewHistory scope={scope} />);
    await screen.findByText(/History revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Capture server observation" }));
    await screen.findByRole("alert");
    expect(screen.queryByText(/Server observation retained/)).not.toBeInTheDocument();
    expect(screen.getByText(/History revision 2/)).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
  it("drops late capture completion immediately on a scope change", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    api.capture.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const { rerender } = render(<OverviewHistory scope={scope} />);
    await screen.findByText(/History revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Capture server observation" }));
    await waitFor(() => expect(api.capture).toHaveBeenCalledOnce());
    const other = { subscription: ["sub-b"] };
    api.history.mockResolvedValueOnce(envelope({ ...empty, scope: other }));
    rerender(<OverviewHistory scope={other} />);
    await screen.findByText(/History revision 0/);
    await act(async () => resolve(envelope({ ...history, revision: 3 })));
    expect(screen.queryByText(/Server observation retained/)).not.toBeInTheDocument();
    expect(screen.getByText(/History revision 0/)).toBeInTheDocument();
    expect(api.history).toHaveBeenLastCalledWith(other);
  });
});
