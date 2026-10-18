import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ExposureHistory, ExposureObservation } from "@/lib/types";
import { ExposureMovement } from "./ExposureMovement";

const api = vi.hoisted(() => ({ exposureHistory: vi.fn(), captureExposureObservation: vi.fn() }));
vi.mock("@/lib/services", () => ({ vulnerabilityApi: api }));
vi.mock("./ExposureRecovery", () => ({ ExposureRecovery: () => <div>Recovery review workspace</div> }));
const scope = { subscription: ["sub-a"] }, generation = "generation-one";
const observation = (index: number): ExposureObservation => ({
  observation_id: `exo-${String(index).padStart(32, "0")}`,
  captured_at: `2026-10-17T06:00:0${index}Z`, generation: `generation-${index}`,
  total_count: 10 - index, facets: { severity: [{ value: "critical", count: 5 - index }] },
  completeness_state: "partial", represented_connections: 1, expected_connections: 2,
  excluded_count: 3, coverage_total_count: 13, freshness_state: "reported", source_observed_at: "2026-10-15T00:00:00Z",
  source_table: "gold_exposure_facts",
});
const empty: ExposureHistory = { schema_version: 1, actor: "reader", scope, revision: 0, observations: [] };
const history: ExposureHistory = { ...empty, revision: 2, observations: [observation(1), observation(2)] };
const envelope = (data: ExposureHistory) => ({ data, scope: data.scope, evidence: [], warnings: [] });

describe("Retained Exposure movement", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.exposureHistory.mockResolvedValue(envelope(history));
    api.captureExposureObservation.mockResolvedValue(envelope({ ...history, revision: 3, observations: [...history.observations, { ...observation(3), generation }] }));
  });
  it("compares actual retained counts and provenance without identity or cause claims", async () => {
    render(<ExposureMovement scope={scope} generation={generation} />);
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("row", { name: "All represented findings 9 8 -1" })).toBeVisible();
    expect(within(table).getByRole("row", { name: "severity: critical 4 3 -1" })).toBeVisible();
    expect(screen.getByText(/Different generations: source population/)).toBeVisible();
    fireEvent.click(screen.getByText("Inspect retained source extents and generations"));
    expect(screen.getAllByText(/Source observed 2026-10-15T00:00:00Z/)).toHaveLength(2);
    expect(api.captureExposureObservation).not.toHaveBeenCalled();
  });
  it("requires explicit capture with reviewed revision, generation and scope", async () => {
    render(<ExposureMovement scope={scope} generation={generation} />);
    await screen.findByText(/History revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Capture exposure observation" }));
    await screen.findByText(/Server aggregate observation retained/);
    expect(api.captureExposureObservation).toHaveBeenCalledWith(scope, 2, generation);
    expect(screen.getByRole("combobox", { name: "Later exposure observation" })).toHaveValue(observation(3).observation_id);
  });
  it("does not infer a baseline, and disables capture before a generation exists", async () => {
    api.exposureHistory.mockResolvedValueOnce(envelope(empty));
    render(<ExposureMovement scope={scope} generation="" />);
    await screen.findByText(/No historical baseline is inferred/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Capture exposure observation" })).toBeDisabled();
  });
  it("requires reload after an ambiguous capture without automatic POST replay", async () => {
    api.captureExposureObservation.mockRejectedValueOnce(new Error("Admission reply lost"));
    render(<ExposureMovement scope={scope} generation={generation} />);
    await screen.findByText(/History revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Capture exposure observation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/lost reply may still have retained/);
    expect(screen.getByRole("button", { name: "Capture exposure observation" })).toBeDisabled();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(api.captureExposureObservation).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Reload exposure observations" }));
    await screen.findByText(/Retained observations reloaded/);
    expect(screen.getByRole("button", { name: "Capture exposure observation" })).toBeEnabled();
  });
  it("preserves unavailable facet groups rather than manufacturing zero", async () => {
    const earlier = { ...observation(1), facets: { source_family: [{ value: "defender_image", count: 9 }] } };
    api.exposureHistory.mockResolvedValueOnce(envelope({ ...history, observations: [earlier, observation(2)] }));
    render(<ExposureMovement scope={scope} generation={generation} />);
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("row", { name: "source_family: defender_image 9 Unavailable Unavailable" })).toBeVisible();
  });
  it("rejects reversed and identical pairs", async () => {
    render(<ExposureMovement scope={scope} generation={generation} />);
    await screen.findByRole("table");
    fireEvent.change(screen.getByRole("combobox", { name: "Earlier exposure observation" }), { target: { value: observation(2).observation_id } });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(/Choose two different observations/)).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "Later exposure observation" }), { target: { value: observation(1).observation_id } });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
  it("fences a late capture when the selected scope changes", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    api.captureExposureObservation.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const view = render(<ExposureMovement scope={scope} generation={generation} />);
    await screen.findByText(/History revision 2/);
    fireEvent.click(screen.getByRole("button", { name: "Capture exposure observation" }));
    await waitFor(() => expect(api.captureExposureObservation).toHaveBeenCalledOnce());
    const other = { subscription: ["sub-b"] };
    api.exposureHistory.mockResolvedValueOnce(envelope({ ...empty, scope: other }));
    view.rerender(<ExposureMovement scope={other} generation={generation} />);
    await screen.findByText(/History revision 0/);
    await act(async () => resolve(envelope(history)));
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText(/Server aggregate observation retained/)).not.toBeInTheDocument();
  });
  it("rejects mismatched scope responses before attaching retained data", async () => {
    api.exposureHistory.mockResolvedValueOnce({ ...envelope(history), scope: {} });
    render(<ExposureMovement scope={scope} generation={generation} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/scope does not match/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Capture exposure observation" })).toBeDisabled();
  });
  it("does not evict receipts or permit capture beyond capacity", async () => {
    const full = { ...history, revision: 30, observations: Array.from({ length: 30 }, (_, index) => ({ ...observation(1), observation_id: `exo-${index.toString(16).padStart(32, "0")}` })) };
    api.exposureHistory.mockResolvedValueOnce(envelope(full));
    render(<ExposureMovement scope={scope} generation={generation} />);
    await screen.findByText(/Observation capacity reached/);
    expect(screen.getByRole("button", { name: "Capture exposure observation" })).toBeDisabled();
  });
  it("rejects a success-shaped capture for another generation without losing the reviewed pair", async () => {
    api.captureExposureObservation.mockResolvedValueOnce(envelope({ ...history, revision: 3, observations: [...history.observations, observation(3)] }));
    render(<ExposureMovement scope={scope} generation={generation} />);
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: "Capture exposure observation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/exact generation/);
    expect(screen.getByText(/History revision 2/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Capture exposure observation" })).toBeDisabled();
  });
});
