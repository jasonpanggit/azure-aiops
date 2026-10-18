import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NetworkIntentSuite, NetworkIntentTest } from "@/lib/types";
import { ConnectivityIntents } from "./ConnectivityIntents";

const api = vi.hoisted(() => ({ intents: vi.fn(), saveIntents: vi.fn(), runIntents: vi.fn() }));
vi.mock("@/lib/services", () => ({ networkApi: api }));
const scope = { subscription: ["sub-a"] };
const test: NetworkIntentTest = {
  test_id: "expected-denial", name: "Database isolation", source: "10.0.0.4",
  destination: "10.1.0.4", port: 443, protocol: "Tcp", expected_verdict: "denied",
};
const empty: NetworkIntentSuite = { schema_version: 1, actor: "reader", scope, revision: 0, tests: [], runs: [] };
const saved: NetworkIntentSuite = { ...empty, revision: 1, tests: [test] };
const executed: NetworkIntentSuite = { ...saved, revision: 2, runs: [{
  run_id: "11111111-1111-4111-8111-111111111111", reviewed_revision: 1,
  started_at: "2026-10-16T12:00:00Z", finished_at: "2026-10-16T12:00:01Z",
  source_observed_at: "", results: [{
    test, verdict: "denied", outcome: "indeterminate", unknown_count: 1, missing_enforcement_count: 0,
  }],
}] };
const envelope = (data: NetworkIntentSuite) => ({ data });

describe("Saved connectivity declarations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.intents.mockResolvedValue(envelope(saved));
    api.saveIntents.mockImplementation(async (_scope, revision, tests) => envelope({ ...saved, revision: revision + 1, tests }));
    api.runIntents.mockResolvedValue(envelope(executed));
  });

  it("reads declarations only, then explicitly runs the saved revision", async () => {
    render(<ConnectivityIntents scope={scope} />);
    await screen.findByText("Database isolation");
    expect(api.runIntents).not.toHaveBeenCalled();
    expect(api.saveIntents).not.toHaveBeenCalled();
    expect(api.intents).toHaveBeenCalledWith(scope, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    fireEvent.click(screen.getByRole("button", { name: "Run saved tests" }));
    await screen.findByText("Configuration-only outcomes");
    expect(api.runIntents).toHaveBeenCalledWith(scope, 1, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    const results = within(screen.getByRole("region", { name: "Retained connectivity results" }));
    expect(results.getByText("indeterminate")).toBeInTheDocument();
    expect(results.getByText("denied / denied")).toBeInTheDocument();
    expect(screen.getByText(/Source observed: Not reported/)).toBeInTheDocument();
    expect(screen.getByText(/exact declarations tested at revision 1/)).toBeInTheDocument();
  });

  it("stages declarations before saving and withholds run while dirty or editing", async () => {
    api.intents.mockResolvedValueOnce(envelope(empty));
    render(<ConnectivityIntents scope={scope} />);
    await screen.findByText(/No declarations in this scope/);
    fireEvent.change(screen.getByRole("textbox", { name: "Test name" }), { target: { value: "Internet blocked" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Source endpoint" }), { target: { value: "10.0.0.7" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Destination endpoint" }), { target: { value: "Internet" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Expected configuration verdict" }), { target: { value: "denied" } });
    expect(screen.getByRole("button", { name: "Run saved tests" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Stage test" }));
    expect(screen.getByRole("button", { name: "Run saved tests" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Test name" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Save tests" }));
    await screen.findByText(/Declarations saved/);
    expect(api.saveIntents).toHaveBeenCalledWith(scope, 0, [expect.objectContaining({
      name: "Internet blocked", source: "10.0.0.7", destination: "Internet",
      port: 443, protocol: "Tcp", expected_verdict: "denied",
    })], expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByRole("button", { name: "Run saved tests" })).toBeEnabled();
    expect(api.runIntents).not.toHaveBeenCalled();
  });

  it("edits and removes declarations without rewriting historical runs", async () => {
    api.intents.mockResolvedValueOnce(envelope(executed));
    render(<ConnectivityIntents scope={scope} />);
    await screen.findByText("Configuration-only outcomes");
    fireEvent.click(screen.getByRole("button", { name: "Edit Database isolation" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Test name" }), { target: { value: "Updated declaration" } });
    expect(screen.getByRole("button", { name: "Save tests" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Stage edited test" }));
    const results = within(screen.getByRole("region", { name: "Retained connectivity results" }));
    expect(results.getByText("Database isolation")).toBeInTheDocument();
    expect(results.queryByText("Updated declaration")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove Updated declaration" }));
    expect(screen.getByText(/No declarations in this scope/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save tests" }));
    await screen.findByText(/Declarations saved/);
    expect(api.saveIntents).toHaveBeenCalledWith(scope, 2, [], expect.anything());
  });

  it("requires reload after an unconfirmed save rather than reusing a stale revision", async () => {
    api.saveIntents.mockRejectedValueOnce(new Error("Revision conflict"));
    render(<ConnectivityIntents scope={scope} />);
    await screen.findByText("Database isolation");
    fireEvent.click(screen.getByRole("button", { name: "Remove Database isolation" }));
    fireEvent.click(screen.getByRole("button", { name: "Save tests" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Revision conflict.*Reload saved tests/);
    expect(screen.queryByRole("button", { name: "Run saved tests" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload saved tests" }));
    await screen.findByText("Database isolation");
    expect(api.intents).toHaveBeenCalledTimes(2);
    expect(api.runIntents).not.toHaveBeenCalled();
  });

  it("recovers a read failure without making a run", async () => {
    api.intents.mockRejectedValueOnce(new Error("Document storage unavailable"));
    render(<ConnectivityIntents scope={scope} />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Reload saved tests" }));
    await screen.findByText("Database isolation");
    expect(api.runIntents).not.toHaveBeenCalled();
  });

  it("blocks duplicate submissions and recovers an unconfirmed run", async () => {
    let reject: (reason: Error) => void = () => {};
    api.runIntents.mockReturnValueOnce(new Promise((_resolve, rejectPromise) => { reject = rejectPromise; }));
    render(<ConnectivityIntents scope={scope} />);
    await screen.findByText("Database isolation");
    const run = screen.getByRole("button", { name: "Run saved tests" });
    fireEvent.click(run); fireEvent.click(run);
    expect(api.runIntents).toHaveBeenCalledTimes(1);
    expect(run).toBeDisabled();
    await act(async () => reject(new Error("Network source unavailable")));
    expect(await screen.findByRole("alert")).toHaveTextContent("Result was not confirmed");
    expect(screen.queryByText("Configuration-only outcomes")).not.toBeInTheDocument();
  });

  it("immediately isolates scope changes and ignores a late run", async () => {
    let resolve: (value: unknown) => void = () => {};
    api.runIntents.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const view = render(<ConnectivityIntents scope={scope} />);
    await screen.findByText("Database isolation");
    fireEvent.click(screen.getByRole("button", { name: "Run saved tests" }));
    const signal: AbortSignal = api.runIntents.mock.calls[0][2].signal;
    api.intents.mockResolvedValueOnce(envelope({ ...empty, scope: { region: ["westus"] } }));
    view.rerender(<ConnectivityIntents scope={{ region: ["westus"] }} />);
    expect(screen.queryByText("Database isolation")).not.toBeInTheDocument();
    await screen.findByText(/No declarations in this scope/);
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(envelope(executed)));
    expect(screen.queryByText("Configuration-only outcomes")).not.toBeInTheDocument();
    expect(api.intents).toHaveBeenLastCalledWith({ region: ["westus"] }, expect.anything());
  });

  it("bounds declarations and keeps results keyboard-scrollable", async () => {
    api.intents.mockResolvedValueOnce(envelope({ ...executed, tests: Array.from({ length: 20 }, (_, i) => ({ ...test, test_id: `test-${i}`, name: `Test ${i}` })) }));
    render(<ConnectivityIntents scope={scope} />);
    await screen.findByText("Test 19");
    expect(screen.getByRole("button", { name: "Stage test" })).toBeDisabled();
    expect(screen.getByRole("region", { name: "Retained connectivity results" })).toHaveAttribute("tabindex", "0");
    fireEvent.click(screen.getByRole("button", { name: "Edit Test 19" }));
    expect(screen.getByRole("button", { name: "Stage edited test" })).toBeEnabled();
  });

  it("aborts a pending read when unmounted", async () => {
    api.intents.mockReturnValueOnce(new Promise(() => {}));
    const view = render(<ConnectivityIntents scope={scope} />);
    await waitFor(() => expect(api.intents).toHaveBeenCalledTimes(1));
    const signal: AbortSignal = api.intents.mock.calls[0][1].signal;
    view.unmount();
    expect(signal.aborted).toBe(true);
  });
});
