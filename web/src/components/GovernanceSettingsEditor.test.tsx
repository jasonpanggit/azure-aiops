import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EnterpriseSettings } from "@/lib/types";
import { GovernanceSettingsEditor } from "./GovernanceSettingsEditor";

const api = vi.hoisted(() => ({ settings: vi.fn(), updateSettings: vi.fn() }));
vi.mock("@/lib/services", () => ({ governanceApi: api }));
const initial: EnterpriseSettings = {
  roles: [], taxonomies: {}, onboarding_policy: {}, architecture_policy: {},
  agent_policy: { require_human_approval: true },
  retention_policy: { audit_log_days: 365 }, revision: 4,
  persistent: true, can_write: true, last_change: null,
};
const response = (settings = initial) => ({ data: settings, evidence: [], scope: {}, warnings: [] });

async function editAndReview() {
  fireEvent.change(await screen.findByLabelText("Audit Log Days"), { target: { value: "30" } });
  fireEvent.change(screen.getByLabelText("Change reason"), { target: { value: "Reviewed retention" } });
  fireEvent.click(screen.getByRole("button", { name: "Review 1 change" }));
}

describe("enterprise-wide settings review", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.settings.mockResolvedValue(response());
    api.updateSettings.mockResolvedValue(response({ ...initial, revision: 5, retention_policy: { audit_log_days: 30 } }));
  });

  it("reviews only changed keys against an immutable base before an attributed save", async () => {
    render(<GovernanceSettingsEditor scope={{ subscription: ["sub-a"] }} />);
    expect(await screen.findByText(/Inventory filters do not limit this change/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review 0 changes" })).toBeDisabled();
    await editAndReview();
    expect(api.updateSettings).not.toHaveBeenCalled();
    expect(screen.getByRole("region", { name: "Policy change comparison" })).toHaveTextContent("365");
    expect(screen.getByRole("region", { name: "Policy change comparison" })).toHaveTextContent("30");
    fireEvent.click(screen.getByRole("button", { name: "Confirm enterprise-wide change" }));
    await screen.findByText("Enterprise-wide settings saved at revision 5.");
    expect(api.updateSettings).toHaveBeenCalledWith({
      expected_revision: 4, reason: "Reviewed retention",
      changes: { retention_policy: { audit_log_days: 30 } },
    }, expect.any(AbortSignal));
    expect(screen.getByRole("button", { name: "Review 0 changes" })).toBeDisabled();
    expect(initial.retention_policy).toEqual({ audit_log_days: 365 });
  });

  it.each([{ can_write: undefined }, { can_write: false }, { persistent: false }, { revision: undefined }])(
    "is read only without complete durable versioned write capability %s", async overrides => {
      api.settings.mockResolvedValue(response({ ...initial, ...overrides }));
      render(<GovernanceSettingsEditor scope={{}} />);
      expect(await screen.findByLabelText("Audit Log Days")).toBeDisabled();
      expect(screen.getByText(/Read only: durable versioned settings/)).toBeInTheDocument();
      expect(api.updateSettings).not.toHaveBeenCalled();
    },
  );

  it("invalidates review after an edit and never turns an empty number into zero", async () => {
    render(<GovernanceSettingsEditor scope={{}} />);
    await editAndReview();
    fireEvent.click(screen.getByRole("button", { name: "Back to editing" }));
    fireEvent.change(screen.getByLabelText("Audit Log Days"), { target: { value: "" } });
    expect(screen.getByRole("alert")).toHaveTextContent("positive whole numbers");
    expect(screen.getByRole("button", { name: "Review 1 change" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Confirm enterprise-wide change" })).not.toBeInTheDocument();
  });

  it.each(["Settings changed", "Save was not confirmed"])(
    "requires explicit reload after %s, with no replay", async message => {
      api.updateSettings.mockRejectedValueOnce(new Error(message));
      render(<GovernanceSettingsEditor scope={{}} />);
      await editAndReview();
      fireEvent.click(screen.getByRole("button", { name: "Confirm enterprise-wide change" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("No change will be replayed automatically");
      expect(screen.getByLabelText("Audit Log Days")).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: "Reload enterprise settings" }));
      expect(await screen.findByLabelText("Audit Log Days")).toHaveValue(365);
      expect(api.updateSettings).toHaveBeenCalledTimes(1);
      expect(screen.getByLabelText("Change reason")).toHaveValue("");
    },
  );

  it("does not substitute editable defaults when reads fail and supports reload", async () => {
    api.settings.mockRejectedValueOnce(new Error("Storage is unavailable"));
    render(<GovernanceSettingsEditor scope={{}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No editable defaults");
    expect(screen.queryByLabelText("Audit Log Days")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload enterprise settings" }));
    expect(await screen.findByLabelText("Audit Log Days")).toHaveValue(365);
  });

  it("aborts scope changes and ignores a late save from the previous workspace", async () => {
    let resolve!: (value: ReturnType<typeof response>) => void;
    api.updateSettings.mockImplementationOnce(() => new Promise(value => { resolve = value; }));
    const view = render(<GovernanceSettingsEditor scope={{ subscription: ["sub-a"] }} />);
    await editAndReview();
    fireEvent.click(screen.getByRole("button", { name: "Confirm enterprise-wide change" }));
    const signal = api.updateSettings.mock.calls[0][1] as AbortSignal;
    view.rerender(<GovernanceSettingsEditor scope={{ subscription: ["sub-b"] }} />);
    expect(signal.aborted).toBe(true);
    await act(async () => { resolve(response({ ...initial, revision: 999 })); });
    expect(await screen.findByLabelText("Audit Log Days")).toHaveValue(365);
    expect(screen.queryByText(/revision 999/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Change reason")).toHaveValue("");
  });

  it("aborts an outstanding initial read on unmount", async () => {
    api.settings.mockReturnValueOnce(new Promise(() => {}));
    const view = render(<GovernanceSettingsEditor scope={{}} />);
    await waitFor(() => expect(api.settings).toHaveBeenCalled());
    const signal = api.settings.mock.calls[0][1] as AbortSignal;
    view.unmount();
    expect(signal.aborted).toBe(true);
  });
});
