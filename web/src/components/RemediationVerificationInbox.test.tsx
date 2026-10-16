import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RemediationVerificationInbox } from "./RemediationVerificationInbox";
import type { RemediationNotificationInbox } from "@/lib/remediation-notifications";
import type { Envelope } from "@/lib/types";

const api = vi.hoisted(() => ({ notifications: vi.fn() }));
vi.mock("@/lib/services", () => ({ remediationApi: api }));
const scope = { subscription: ["sub-a"], region: ["eastus"] };
function response(title = "Recorded outcome", next: number | null = null): Envelope<RemediationNotificationInbox> {
  return {
    data: {
      notifications: [{
        notification_id: `notification-${title}`, execution_id: "RME-1", plan_id: "retired-plan", revision: 7,
        kind: "attention", title, execution_status: "succeeded", reconciliation_status: "unreported",
        recorded_at: null, target_id: "/subscriptions/sub-a/vm", authority: "none",
      }],
      authorized_execution_count: 30, latest_outcome_count: 26, read_only: true, boundary: "Stored only",
    },
    evidence: [], scope, warnings: [], knowledge_version: "",
    pagination: { offset: 0, limit: 25, total: 26, next_offset: next },
  };
}
async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Open verification notifications" }));
  await screen.findByText("Recorded outcome");
}

describe("read-only verification notification inbox", () => {
  beforeEach(() => api.notifications.mockReset().mockResolvedValue(response()));
  it("does not acquire executions until explicitly opened; reports source meanings and missing time", async () => {
    render(<RemediationVerificationInbox scope={scope} />);
    expect(api.notifications).not.toHaveBeenCalled();
    await open();
    expect(api.notifications).toHaveBeenCalledWith(scope, "", 0, expect.any(AbortSignal));
    expect(screen.getByRole("status")).toHaveTextContent("30 authorized stored execution records; 26 latest outcomes");
    expect(screen.getByText(/Last stored update: Unreported/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Recorded execution identifiers"));
    expect(screen.getByText("retired-plan")).toBeInTheDocument();
    expect(screen.getByText(/does not submit, retry, cancel/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execute|approve|retry execution/i })).not.toBeInTheDocument();
  });
  it("filters on the server and discards old observations immediately", async () => {
    render(<RemediationVerificationInbox scope={scope} />); await open();
    api.notifications.mockImplementationOnce(() => new Promise(() => {}));
    fireEvent.change(screen.getByLabelText("Recorded outcome filter"), { target: { value: "complete" } });
    expect(screen.queryByText("Recorded outcome")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Reading stored");
    await waitFor(() => expect(api.notifications.mock.lastCall).toEqual([scope, "complete", 0, expect.any(AbortSignal)]));
  });
  it("uses server next offsets, previous paging and resets on explicit refresh", async () => {
    api.notifications.mockResolvedValueOnce(response("Recorded outcome", 25)).mockResolvedValueOnce(response("Second page"));
    render(<RemediationVerificationInbox scope={scope} />); await open();
    expect(screen.getByRole("button", { name: "Previous notifications" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next notifications" }));
    await screen.findByText("Second page");
    expect(api.notifications.mock.lastCall?.[2]).toBe(25);
    fireEvent.click(screen.getByRole("button", { name: "Previous notifications" }));
    await screen.findByText("Recorded outcome");
    expect(api.notifications.mock.lastCall?.[2]).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Refresh verification notifications" }));
    await screen.findByText("Recorded outcome");
    expect(api.notifications).toHaveBeenCalledTimes(4);
  });
  it("keeps source failure distinct from an empty inbox and permits an unchanged retry", async () => {
    api.notifications.mockRejectedValueOnce(new Error("Stored outcomes unavailable"));
    render(<RemediationVerificationInbox scope={scope} />);
    fireEvent.click(screen.getByRole("button", { name: "Open verification notifications" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Stored outcomes unavailable");
    expect(screen.queryByText(/No stored outcome matches/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh verification notifications" }));
    await screen.findByText("Recorded outcome");
    expect(api.notifications).toHaveBeenCalledTimes(2);
  });
  it("never interprets an empty filtered result as healthy or completed work", async () => {
    const empty = response(); empty.data.notifications = []; empty.pagination!.total = 0;
    api.notifications.mockResolvedValue({ ...empty });
    render(<RemediationVerificationInbox scope={scope} />);
    fireEvent.click(screen.getByRole("button", { name: "Open verification notifications" }));
    expect(await screen.findByText(/absence does not prove a healthy estate/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next notifications" })).toBeDisabled();
  });
  it.each(["scope", "close", "filter"])("aborts and ignores late results after %s transition", async transition => {
    let resolve!: (value: Envelope<RemediationNotificationInbox>) => void;
    api.notifications.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const { rerender } = render(<RemediationVerificationInbox scope={scope} />);
    fireEvent.click(screen.getByRole("button", { name: "Open verification notifications" }));
    await waitFor(() => expect(api.notifications).toHaveBeenCalledTimes(1));
    const signal = api.notifications.mock.calls[0][3] as AbortSignal;
    if (transition === "scope") rerender(<RemediationVerificationInbox scope={{ subscription: ["sub-b"] }} />);
    else if (transition === "close") fireEvent.click(screen.getByRole("button", { name: "Close verification notifications" }));
    else fireEvent.change(screen.getByLabelText("Recorded outcome filter"), { target: { value: "attention" } });
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(response("Late foreign result")));
    expect(screen.queryByText("Late foreign result")).not.toBeInTheDocument();
  });
});
