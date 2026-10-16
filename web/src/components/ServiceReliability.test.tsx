import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ServiceReliability } from "./ServiceReliability";
import type { ServiceObjectivePolicy } from "@/lib/service-reliability";

const api = vi.hoisted(() => ({ objectives: vi.fn(), components: vi.fn(), save: vi.fn(), remove: vi.fn(), metrics: vi.fn() }));
vi.mock("@/lib/services", () => ({ serviceReliabilityApi: api }));
const scope = { subscription: ["sub-a"], region: ["eastus"] };
const resource = "/subscriptions/sub-a/resourcegroups/apps/providers/microsoft.insights/components/payroll";
const policy: ServiceObjectivePolicy = {
  schema_version: 1, scope, revision: 1, updated_at: "2026-01-02T00:00:00Z", updated_by: "admin",
  objectives: [{ resource_id: resource, business_service: "payroll", success_target_basis_points: 9950, window_hours: 24 }],
};
const component = { resource_id: resource, resource_name: "Payroll telemetry", business_service: "payroll", subscription_id: "sub-a", subscription_connection: "conn-a", observed_at: policy.updated_at };
const measurement = {
  data: {
    resource_id: resource, business_service: "payroll", objective: policy.objectives[0], objective_policy_revision: 1,
    window_started_at: "2026-01-01T00:00:00Z", window_finished_at: policy.updated_at,
    aggregate: { record_count: 100, represented_count: 150, failed_count: 2, unknown_success_records: 0, invalid_weight_records: 0, sampled_records: 50, invalid_duration_records: 0, first_observed_at: policy.updated_at, last_observed_at: policy.updated_at },
    request_success_percent: 98, p95_observed_record_duration_ms: 120, allowed_failed_requests: 0.75,
    remaining_failed_request_budget: -1.25, consumed_budget_percent: 266.67, sampling_estimated: true,
    interpretation: "Approximate unweighted p95. Not whole-service uptime or execution approval.",
  }, evidence: [], warnings: [],
};

async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Open request reliability" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Reload reliability workspace" })).toBeEnabled());
}
function select() {
  fireEvent.change(screen.getByRole("combobox", { name: "Published component" }), { target: { value: resource } });
}

describe("explicit component reliability workspace", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.objectives.mockResolvedValue({ data: structuredClone(policy) });
    api.components.mockResolvedValue({ data: { components: [component] }, pagination: { total: 1 } });
    api.metrics.mockResolvedValue(structuredClone(measurement));
    api.save.mockResolvedValue({ data: { ...policy, revision: 2 } });
    api.remove.mockResolvedValue({ data: { ...policy, revision: 2, objectives: [] } });
  });

  it("loads only on demand and measures only an explicitly selected saved objective", async () => {
    render(<ServiceReliability scope={scope} />);
    expect(api.objectives).not.toHaveBeenCalled();
    await open();
    expect(api.metrics).not.toHaveBeenCalled();
    select();
    fireEvent.click(screen.getByRole("button", { name: "Read measured requests" }));
    await screen.findByRole("region", { name: "Measured component requests" });
    expect(screen.getByText("98%")).toBeInTheDocument();
    expect(screen.getByText("-1.25")).toBeInTheDocument();
    expect(screen.getByText(/Sample-weighted counts are estimates/)).toBeInTheDocument();
    expect(api.metrics).toHaveBeenCalledWith(scope, resource, expect.any(AbortSignal));
    expect(api.save).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("combobox", { name: "Published component" }), { target: { value: "" } });
    expect(screen.queryByRole("region", { name: "Measured component requests" })).not.toBeInTheDocument();
  });

  it("never prepopulates a new target or measured result", async () => {
    api.objectives.mockResolvedValue({ data: { ...policy, revision: 0, objectives: [], updated_by: "", updated_at: "" } });
    render(<ServiceReliability scope={scope} />);
    await open(); select();
    expect(screen.getByRole("spinbutton", { name: "Request success target (%)" })).toHaveValue(null);
    expect(screen.getByRole("combobox", { name: "Objective window" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "Read measured requests" })).toBeDisabled();
    fireEvent.change(screen.getByRole("spinbutton", { name: "Request success target (%)" }), { target: { value: "99.99" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Objective window" }), { target: { value: "168" } });
    fireEvent.click(screen.getByRole("button", { name: "Save declared objective" }));
    await screen.findByText(/Declared objective saved/);
    expect(api.save).toHaveBeenCalledWith(scope, { resource_id: resource, success_target_basis_points: 9999, window_hours: 168 }, 0, expect.any(AbortSignal));
    expect(api.metrics).not.toHaveBeenCalled();
  });

  it("retains explicit unknown measurements rather than zero or 100 percent", async () => {
    api.metrics.mockResolvedValue({
      ...measurement, data: { ...measurement.data, request_success_percent: null, p95_observed_record_duration_ms: null,
        allowed_failed_requests: null, remaining_failed_request_budget: null, consumed_budget_percent: null },
    });
    render(<ServiceReliability scope={scope} />);
    await open(); select();
    fireEvent.click(screen.getByRole("button", { name: "Read measured requests" }));
    await screen.findByRole("region", { name: "Measured component requests" });
    expect(Array.from(screen.getByRole("region", { name: "Measured component requests" }).querySelectorAll(".service-reliability-values dd")).map(node => node.textContent)).toEqual(Array(5).fill("Unknown"));
    expect(screen.queryByText("100%")).not.toBeInTheDocument();
  });

  it("requires confirmation before removing one reviewed objective", async () => {
    render(<ServiceReliability scope={scope} />);
    await open(); select();
    fireEvent.click(screen.getByRole("button", { name: "Remove declared objective" }));
    expect(api.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm remove objective" }));
    await screen.findByText(/Declared objective removed/);
    expect(api.remove).toHaveBeenCalledWith(scope, resource, 1, expect.any(AbortSignal));
    expect(api.metrics).not.toHaveBeenCalled();
  });

  it("recovers and removes declarations even when current inventory is unavailable", async () => {
    api.components.mockRejectedValue(new Error("Published source unavailable"));
    render(<ServiceReliability scope={scope} />);
    await open();
    expect(screen.getByRole("alert")).toHaveTextContent("No clean or empty estate is inferred");
    fireEvent.click(screen.getByText("Review saved objectives (1)"));
    fireEvent.click(screen.getByRole("button", { name: `Review payroll · ${resource}` }));
    expect(screen.getByRole("button", { name: "Save declared objective" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove declared objective" })).toBeEnabled();
  });

  it.each(["save", "remove"])("blocks %s replay after an uncertain write until explicit recovery", async action => {
    api[action as "save" | "remove"].mockRejectedValue(new Error("Revision conflict"));
    render(<ServiceReliability scope={scope} />);
    await open(); select();
    fireEvent.click(screen.getByRole("button", { name: action === "save" ? "Save declared objective" : "Remove declared objective" }));
    if (action === "remove") fireEvent.click(screen.getByRole("button", { name: "Confirm remove objective" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("reload before retrying"));
    expect(screen.getByRole("button", { name: "Save declared objective" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Read measured requests" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload reliability workspace" }));
    await waitFor(() => expect(api.objectives).toHaveBeenCalledTimes(2));
    expect(api[action as "save" | "remove"]).toHaveBeenCalledTimes(1);
    expect(api.metrics).not.toHaveBeenCalled();
  });

  it("uses explicit server search/pagination and clears former selection", async () => {
    api.components.mockResolvedValue({ data: { components: [component] }, pagination: { total: 51 } });
    render(<ServiceReliability scope={scope} />);
    await open(); select();
    fireEvent.click(screen.getByRole("button", { name: "Next components" }));
    await waitFor(() => expect(api.components).toHaveBeenCalledWith(scope, "", 25, expect.any(AbortSignal)));
    expect(screen.queryByRole("button", { name: "Read measured requests" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Find telemetry component" }), { target: { value: "API" } });
    fireEvent.click(screen.getByRole("button", { name: "Search components" }));
    await waitFor(() => expect(api.components).toHaveBeenCalledWith(scope, "API", 0, expect.any(AbortSignal)));
  });

  it("aborts closed/superseded scopes and ignores late measurement responses", async () => {
    let resolve!: (value: typeof measurement) => void;
    api.metrics.mockImplementation(() => new Promise(value => { resolve = value; }));
    const view = render(<ServiceReliability scope={scope} />);
    await open(); select();
    fireEvent.click(screen.getByRole("button", { name: "Read measured requests" }));
    const signal = api.metrics.mock.calls[0][2];
    view.rerender(<ServiceReliability scope={{ subscription: ["sub-b"] }} />);
    expect(signal.aborted).toBe(true);
    await act(async () => { resolve(measurement); });
    expect(screen.queryByRole("region", { name: "Measured component requests" })).not.toBeInTheDocument();
    expect(api.metrics).toHaveBeenCalledTimes(1);
    expect(api.objectives).toHaveBeenCalledTimes(1);
  });
});
