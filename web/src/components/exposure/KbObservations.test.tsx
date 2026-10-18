import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { KbObservation, KbObservationHistory } from "@/lib/types";
import { KbObservations } from "./KbObservations";

const api = vi.hoisted(() => ({ observations: vi.fn(), captureObservation: vi.fn() }));
vi.mock("@/lib/services", () => ({ kbApi: api }));
const scope = { subscription: ["sub-a"] };
const first: KbObservation = {
  observation_id: `kbo-${"1".repeat(32)}`, captured_at: "2026-10-17T00:00:00Z", generation: "silver-patch:one",
  source_observed_at: "2026-10-16T00:00:00Z", completeness: "partial", freshness: "stale",
  counts: { observed_targets: 1000, missing: 100, installation_failed: 3, installed: 800, other: 97 },
  targets: [{ target_id: "vm-one", status: "missing", observed_at: "2026-10-16T00:00:00Z" },
    { target_id: "first-only", status: "installed", observed_at: "" }], targets_truncated: true,
  msrc: { status: "failed", stale: true, has_last_known_good: true, source_at: "2026-10-15T00:00:00Z" },
};
const second: KbObservation = { ...first, observation_id: `kbo-${"2".repeat(32)}`, captured_at: "2026-10-18T00:00:00Z",
  generation: "silver-patch:two", targets: [
    { target_id: "vm-one", status: "installed", observed_at: "2026-10-17T00:00:00Z" },
    { target_id: "second-only", status: "other", observed_at: "" },
  ] };
const empty: KbObservationHistory = { schema_version: 1, actor: "reader", scope, kb_id: "KB6000001", revision: 0, observations: [] };
const saved = { ...empty, revision: 1, observations: [first] };
const envelope = (data: KbObservationHistory) => ({ data, scope: data.scope, evidence: [], warnings: [] });
function mount(generation: string | undefined = "silver-patch:one") {
  return render(<KbObservations kbId="KB6000001" scope={scope} generation={generation} />);
}

describe("KB retained source observation lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks(); api.observations.mockResolvedValue(envelope(empty)); api.captureObservation.mockResolvedValue(envelope(saved));
  });
  it("never captures automatically and binds explicit capture to displayed Silver generation", async () => {
    mount(); await screen.findByText(/KB observation revision 0/);
    expect(api.captureObservation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Capture KB source observation" }));
    await screen.findByText(/KB source observation retained/);
    expect(api.captureObservation).toHaveBeenCalledWith("KB6000001", scope, 0, "silver-patch:one");
    fireEvent.click(screen.getByText(/kbo-1{32} — captured/));
    expect(screen.getByText(/1000 observed; 100 missing; 3 failed; 800 installed; 97 other/)).toBeVisible();
    expect(screen.getByText(/last-known-good retained; 2026-10-15/)).toBeVisible();
  });
  it("locks ambiguous writes until explicit retained reload and never retries POST", async () => {
    api.captureObservation.mockRejectedValueOnce(new Error("Reply lost"));
    mount(); await screen.findByText(/KB observation revision 0/);
    fireEvent.click(screen.getByRole("button", { name: "Capture KB source observation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/lost reply may have persisted/);
    expect(screen.getByRole("button", { name: "Capture KB source observation" })).toBeDisabled();
    api.observations.mockResolvedValueOnce(envelope(saved));
    fireEvent.click(screen.getByRole("button", { name: "Reload KB observations" }));
    await screen.findByText(/KB observation revision 1/);
    expect(api.captureObservation).toHaveBeenCalledTimes(1);
  });
  it.each([
    ["actor", { ...saved, actor: "other" }],
    ["generation", { ...saved, observations: [{ ...first, generation: "other" }] }],
    ["scope", { ...saved, scope: { subscription: ["outside"] } }],
    ["kb", { ...saved, kb_id: "KB6000002" }],
    ["distribution", { ...saved, observations: [{ ...first, counts: { ...first.counts!, installed: 801 } }] }],
  ])("rejects successful-looking incorrect %s capture responses", async (_, value) => {
    api.captureObservation.mockResolvedValueOnce(envelope(value));
    mount(); await screen.findByText(/KB observation revision 0/);
    fireEvent.click(screen.getByRole("button", { name: "Capture KB source observation" }));
    await screen.findByRole("alert");
    expect(screen.getByText(/KB observation revision 0/)).toBeVisible();
    expect(screen.queryByText(/KB source observation retained/)).not.toBeInTheDocument();
  });
  it("compares recorded status on common targets separately from sample membership without acquisition", async () => {
    api.observations.mockResolvedValueOnce(envelope({ ...empty, revision: 2, observations: [first, second] }));
    mount(); await screen.findByText(/KB observation revision 2/);
    fireEvent.change(screen.getByRole("combobox", { name: "First KB observation" }), { target: { value: first.observation_id } });
    fireEvent.change(screen.getByRole("combobox", { name: "Second KB observation" }), { target: { value: second.observation_id } });
    expect(screen.getByText(/vm-one: missing → installed;/)).toHaveTextContent("Not a verified fix.");
    expect(screen.getByText("First sample only (1): first-only.")).toBeVisible();
    expect(screen.getByText("Second sample only (1): second-only.")).toBeVisible();
    expect(api.observations).toHaveBeenCalledTimes(1);
    expect(api.captureObservation).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("combobox", { name: "Second KB observation" }), { target: { value: first.observation_id } });
    expect(screen.queryByLabelText("KB source observation comparison")).not.toBeInTheDocument();
  });
  it("allows retained history when current metadata is unavailable", async () => {
    api.observations.mockResolvedValueOnce(envelope(saved));
    render(<KbObservations kbId="KB6000001" scope={scope} />);
    await screen.findByText(/KB observation revision 1/);
    expect(screen.getByRole("button", { name: "Capture KB source observation" })).toBeDisabled();
    expect(screen.getByText(/Retained observations remain readable/)).toBeVisible();
  });
  it("does not reset failed read to empty history", async () => {
    api.observations.mockRejectedValueOnce(new Error("Storage unavailable"));
    mount(); expect(await screen.findByRole("alert")).toHaveTextContent("Storage unavailable");
    expect(screen.queryByText(/No retained source observations/)).not.toBeInTheDocument();
  });
  it("rejects rewritten retained prefix on reload", async () => {
    api.observations.mockResolvedValueOnce(envelope(saved));
    mount(); await screen.findByText(/KB observation revision 1/);
    api.observations.mockResolvedValueOnce(envelope({ ...saved, observations: [{ ...first, freshness: "fresh" }] }));
    fireEvent.click(screen.getByRole("button", { name: "Reload KB observations" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/immutable history/);
    expect(screen.getByRole("button", { name: "Capture KB source observation" })).toBeDisabled();
  });
  it("fences late capture after an identity remount", async () => {
    let resolve!: (value: ReturnType<typeof envelope>) => void;
    api.captureObservation.mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const view = mount(); await screen.findByText(/KB observation revision 0/);
    fireEvent.click(screen.getByRole("button", { name: "Capture KB source observation" }));
    await waitFor(() => expect(api.captureObservation).toHaveBeenCalledOnce());
    view.unmount(); await act(async () => resolve(envelope(saved)));
    expect(screen.queryByText(/KB source observation retained/)).not.toBeInTheDocument();
  });
});
