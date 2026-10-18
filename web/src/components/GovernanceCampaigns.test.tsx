import { createHash, webcrypto } from "node:crypto";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccessCampaignCollection, AccessCampaignDetail, CampaignPrincipal } from "@/lib/access-campaigns";
import { GovernanceCampaigns } from "./GovernanceCampaigns";

const api = vi.hoisted(() => ({
  campaigns: vi.fn(), campaign: vi.fn(), createCampaign: vi.fn(),
  decideCampaign: vi.fn(), closeCampaign: vi.fn(), removeCampaign: vi.fn(),
}));
vi.mock("@/lib/services", () => ({ governanceApi: api }));
const item: CampaignPrincipal = {
  principal_id: "principal-0", roles: ["Contributor"], principal_type: "User", assignment_count: 1,
  privileged: true, stale: false, widest_scope: "/subscriptions/a", widest_scope_breadth: "subscription",
  last_changed: "", blast_radius: { subscriptions: 1 },
};
const content = JSON.stringify({ data: { principals: [item] }, warnings: ["Partial observed scope"] }) + "\n";
const initial: AccessCampaignCollection = {
  current_subject: "reader", can_manage: true, revision: 4, scope: {}, as_of: "2026-10-16T12:00:00Z",
  campaigns: [{
    campaign_id: "a".repeat(32), title: "Quarterly review", audience: "auditor", reviewer_subject: "reader",
    created_by: "admin", created_at: "2026-10-15T12:00:00Z", due_at: "2026-10-18T12:00:00Z",
    status: "open", source_sha256: createHash("sha256").update(content).digest("hex"),
    source_size_bytes: Buffer.byteLength(content), item_count: 1, decided_count: 0, overdue: false,
    generated_at: "2026-10-15T12:00:00Z", observed_at: "", warning_count: 1, closure: null,
  }],
};
const initialDetail: AccessCampaignDetail = {
  current_subject: "reader", can_manage: true, scope: {}, revision: 4,
  campaign: initial.campaigns[0], source_content: content, items: [item], decisions: [],
};
const response = <T,>(data: T) => ({ data, scope: {}, evidence: [], warnings: [] });
let collection: AccessCampaignCollection;
let detail: AccessCampaignDetail;

async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Open campaigns" }));
  await screen.findByRole("button", { name: "Reload campaigns" });
}
async function inspect() {
  fireEvent.click(screen.getByRole("button", { name: "Open campaign Quarterly review" }));
  await screen.findByLabelText("Captured principal");
}
function createReview() {
  fireEvent.click(screen.getByRole("button", { name: "New campaign" }));
  fireEvent.change(screen.getByLabelText("Campaign title"), { target: { value: "New review" } });
  fireEvent.change(screen.getByLabelText("Review audience"), { target: { value: "auditor" } });
  fireEvent.click(screen.getByRole("button", { name: "Assign to me" }));
  const future = new Date(Date.now() + 3 * 86400_000);
  const local = new Date(future.valueOf() - future.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  fireEvent.change(screen.getByLabelText("Review deadline (local time)"), { target: { value: local } });
  fireEvent.click(screen.getByRole("button", { name: "Review campaign creation" }));
}

describe("shared advisory access campaigns", () => {
  beforeEach(() => {
    vi.clearAllMocks(); vi.stubGlobal("crypto", webcrypto);
    collection = structuredClone(initial); detail = structuredClone(initialDetail);
    api.campaigns.mockImplementation(async () => response(collection));
    api.campaign.mockImplementation(async () => response(detail));
    api.createCampaign.mockImplementation(async () => {
      collection = { ...collection, revision: 5 };
      detail = { ...detail, revision: 5 }; return response(collection);
    });
    api.decideCampaign.mockImplementation(async (_scope, body) => {
      collection = { ...collection, revision: 5, campaigns: [{ ...collection.campaigns[0], decided_count: 1 }] };
      detail = { ...detail, revision: 5, campaign: collection.campaigns[0],
        decisions: [{ principal_id: body.principal_id, recommendation: body.recommendation,
          reason: body.reason, actor: "reader", recorded_at: "2026-10-16T12:00:00Z" }] };
      return response(collection);
    });
    api.closeCampaign.mockImplementation(async (_scope, action, body) => {
      collection = { ...collection, revision: 5, campaigns: [{
        ...collection.campaigns[0], status: action === "complete" ? "completed" : "cancelled",
        closure: { actor: "admin", reason: body.reason, recorded_at: "2026-10-16T12:00:00Z" },
      }] };
      detail = { ...detail, revision: 5, campaign: collection.campaigns[0] }; return response(collection);
    });
    api.removeCampaign.mockResolvedValue(response({ ...initial, revision: 6, campaigns: [] }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("opens on demand and separately reviews assigned-source creation", async () => {
    render(<GovernanceCampaigns scope={{ subscription: ["a"] }} />);
    expect(api.campaigns).not.toHaveBeenCalled();
    await open(); createReview();
    expect(api.createCampaign).not.toHaveBeenCalled();
    expect(screen.getByRole("region", { name: "Campaign action review" })).toHaveTextContent("Assign reader");
    fireEvent.click(screen.getByRole("button", { name: "Confirm campaign creation" }));
    await screen.findByText(/Campaign change recorded/);
    expect(api.createCampaign.mock.calls[0][0]).toEqual({ subscription: ["a"] });
    expect(api.createCampaign.mock.calls[0][1]).toMatchObject({ title: "New review", audience: "auditor", reviewer_subject: "reader", expected_revision: 4 });
    expect(screen.queryByLabelText("Campaign title")).not.toBeInTheDocument();
  });

  it("records only an explicit recommendation against the verified frozen principal", async () => {
    render(<GovernanceCampaigns scope={{}} />); await open(); await inspect();
    expect(screen.getByText(/observed Unknown/)).toHaveTextContent("1 source warnings preserved");
    expect(screen.getByRole("button", { name: "Review completion" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Access recommendation"), { target: { value: "investigate" } });
    fireEvent.change(screen.getByLabelText("Recommendation rationale"), { target: { value: "Confirm owner" } });
    fireEvent.click(screen.getByRole("button", { name: "Review recommendation" }));
    expect(api.decideCampaign).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm recommendation" }));
    await screen.findByText(/Recorded Investigate by reader/);
    expect(api.decideCampaign.mock.calls[0][1]).toEqual({
      campaign_id: initial.campaigns[0].campaign_id, expected_revision: 4,
      principal_id: item.principal_id, recommendation: "investigate", reason: "Confirm owner",
    });
    expect(screen.queryByLabelText("Access recommendation")).not.toBeInTheDocument();
  });

  it("allows assigned readers to review without manager authority, but administrators cannot impersonate them", async () => {
    collection.can_manage = false;
    render(<GovernanceCampaigns scope={{}} />); await open(); await inspect();
    expect(screen.queryByLabelText("Campaign title")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Access recommendation")).toBeEnabled();
    collection = { ...initial, current_subject: "admin" };
    fireEvent.click(screen.getByRole("button", { name: "Reload campaigns" }));
    await screen.findByRole("button", { name: "Open campaign Quarterly review" }); await inspect();
    expect(screen.getByLabelText("Access recommendation")).toBeDisabled();
  });

  it("requires reason and confirmation for cancellation, then confirmed terminal-copy removal", async () => {
    render(<GovernanceCampaigns scope={{}} />); await open(); await inspect();
    expect(screen.getByRole("button", { name: "Review cancellation" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Campaign closure rationale"), { target: { value: "Repeat with corrected assignment" } });
    fireEvent.click(screen.getByRole("button", { name: "Review cancellation" }));
    expect(api.closeCampaign).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm cancellation" }));
    await screen.findByRole("button", { name: "Review stored-copy removal" });
    fireEvent.click(screen.getByRole("button", { name: "Review stored-copy removal" }));
    expect(api.removeCampaign).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm stored-copy removal" }));
    await screen.findByText("No access campaigns in this exact scope.");
    expect(api.removeCampaign.mock.calls[0][1]).toEqual({ campaign_id: initial.campaigns[0].campaign_id, expected_revision: 5 });
  });

  it.each(["Conflict", "Operation unavailable"])("locks %s writes until explicit reload, without replay", async message => {
    api.createCampaign.mockRejectedValueOnce(new Error(message));
    render(<GovernanceCampaigns scope={{}} />); await open(); createReview();
    fireEvent.click(screen.getByRole("button", { name: "Confirm campaign creation" }));
    await screen.findByText(/No request will be replayed automatically/);
    expect(screen.getByLabelText("Campaign title")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload campaigns" }));
    await screen.findByRole("button", { name: "New campaign" });
    fireEvent.click(screen.getByRole("button", { name: "New campaign" }));
    expect(screen.getByLabelText("Campaign title")).toHaveValue("");
    expect(api.createCampaign).toHaveBeenCalledTimes(1);
  });

  it("distinguishes an acknowledged write from failed record recovery", async () => {
    api.campaign.mockRejectedValueOnce(new Error("Historical read unavailable"));
    render(<GovernanceCampaigns scope={{}} />); await open(); createReview();
    fireEvent.click(screen.getByRole("button", { name: "Confirm campaign creation" }));
    await screen.findByText(/Change acknowledged, but record recovery failed/);
    expect(api.createCampaign).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Campaign title")).toBeDisabled();
    expect(screen.queryByLabelText("Captured principal")).not.toBeInTheDocument();
  });

  it("blocks review on mismatched source bytes and does not invent an empty workspace on read failure", async () => {
    api.campaign.mockResolvedValueOnce(response({ ...detail, source_content: content + " " }));
    render(<GovernanceCampaigns scope={{}} />); await open();
    fireEvent.click(screen.getByRole("button", { name: "Open campaign Quarterly review" }));
    await screen.findByText(/byte count/);
    expect(screen.queryByLabelText("Captured principal")).not.toBeInTheDocument();
    api.campaigns.mockRejectedValueOnce(new Error("Storage unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Reload campaigns" }));
    await screen.findByText(/No empty workspace/);
    expect(screen.queryByText("No access campaigns in this exact scope.")).not.toBeInTheDocument();
  });

  it("aborts scope changes and ignores late writes, and aborts detail reads on close", async () => {
    let resolve!: (value: ReturnType<typeof response<AccessCampaignCollection>>) => void;
    api.createCampaign.mockImplementationOnce(() => new Promise(value => { resolve = value; }));
    const view = render(<GovernanceCampaigns scope={{ subscription: ["a"] }} />);
    await open(); createReview(); fireEvent.click(screen.getByRole("button", { name: "Confirm campaign creation" }));
    const signal = api.createCampaign.mock.calls[0][2] as AbortSignal;
    view.rerender(<GovernanceCampaigns scope={{ subscription: ["b"] }} />);
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(response({ ...initial, revision: 999 })));
    expect(screen.queryByText(/Revision 999/)).not.toBeInTheDocument();
    await open();
    api.campaign.mockReturnValueOnce(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: "Open campaign Quarterly review" }));
    const detailSignal = api.campaign.mock.calls[0][2] as AbortSignal;
    fireEvent.click(screen.getByRole("button", { name: "Close campaigns" }));
    expect(detailSignal.aborted).toBe(true);
  });
});
