import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { InvestigationTeamWorkspacePanel } from "./InvestigationTeamWorkspace";
import type { InvestigationTeamWorkspace, InvestigationWorkspaceView } from "@/lib/investigation-workspaces";

const api = vi.hoisted(() => ({ create: vi.fn(), read: vi.fn(), replace: vi.fn(), share: vi.fn() }));
vi.mock("@/lib/investigation-workspaces", async importOriginal => ({
  ...await importOriginal<typeof import("@/lib/investigation-workspaces")>(),
  investigationWorkspacesApi: api,
}));

const ID = `wrk-${"a".repeat(32)}`;
const SCOPE = { subscription: ["sub-a"], support_team: ["sre"], criticality: ["high"] };
const VIEW: InvestigationWorkspaceView = { title: "Payments review", entry_type: "BusinessService", subject: "Payments", mode: "executive" };
const row = {
  revision: 1, actor: "owner", recorded_at: "2026-10-16T12:00:00+00:00", change: "created" as const,
  view: VIEW, readers: [], editors: [],
};
const record = (overrides: Partial<InvestigationTeamWorkspace> = {}): InvestigationTeamWorkspace => ({
  workspace_id: ID, owner: "owner", scope: SCOPE, latest_revision: 1, revision: row,
  current_access: { readers: [], editors: [] }, can_edit: true, can_share: true,
  history: [row], ...overrides,
});
const envelope = (data: InvestigationTeamWorkspace) => ({ data, evidence: [], scope: data.scope, warnings: [] });
const openDetails = () => fireEvent.click(screen.getByText("Team workspace: open or save server-backed navigation"));

describe("team Investigation navigation", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    for (const method of Object.values(api)) method.mockResolvedValue(envelope(record()));
    api.replace.mockImplementation((_id, revision, view) => Promise.resolve(envelope(record({
      latest_revision: revision + 1, revision: { ...row, revision: revision + 1, view, change: "view_updated" },
    }))));
    api.share.mockImplementation((_id, revision, readers, editors) => Promise.resolve(envelope(record({
      latest_revision: revision + 1, revision: { ...row, revision: revision + 1, readers, editors, change: "access_updated" },
      current_access: { readers, editors },
    }))));
  });

  it("does not read, write or restore anything from the unselected initial surface", () => {
    const restore = vi.fn();
    render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} onRestore={restore} />);
    for (const method of Object.values(api)) expect(method).not.toHaveBeenCalled();
    expect(restore).not.toHaveBeenCalled();
  });

  it("opens a bookmarked exact revision without applying navigation or dispatching a write", async () => {
    const restore = vi.fn();
    render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} initialId={ID} initialRevision={1} onRestore={restore} />);
    await screen.findByText("Saved subject");
    expect(api.read).toHaveBeenCalledWith(ID, SCOPE, 1, expect.any(AbortSignal));
    expect(api.create).not.toHaveBeenCalled();
    expect(restore).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Apply navigation and load current evidence" }));
    expect(restore).toHaveBeenCalledWith(VIEW);
  });

  it("creates privately at a known identity and does not infer collaborators", async () => {
    render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} onRestore={vi.fn()} />);
    openDetails();
    fireEvent.change(screen.getByRole("textbox", { name: "Workspace identity" }), { target: { value: ID } });
    fireEvent.click(screen.getByRole("button", { name: "Create private workspace" }));
    await screen.findByText("Saved subject");
    expect(api.create).toHaveBeenCalledWith(ID, VIEW, SCOPE, expect.any(AbortSignal));
    expect(api.share).not.toHaveBeenCalled();
    expect(api.read).not.toHaveBeenCalled();
  });

  it("preserves a generated identity after a lost create reply and recovers it by explicit read", async () => {
    const generated = "11111111-1111-4111-8111-111111111111";
    const generate = vi.spyOn(crypto, "randomUUID").mockReturnValue(generated);
    api.create.mockRejectedValueOnce(new Error("reply lost after write"));
    api.read.mockResolvedValueOnce(envelope(record({ workspace_id: `wrk-${generated.replaceAll("-", "")}` })));
    try {
      render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} onRestore={vi.fn()} />);
      openDetails();
      fireEvent.click(screen.getByRole("button", { name: "Create private workspace" }));
      await screen.findByText("Workspace operation not confirmed");
      const known = `wrk-${generated.replaceAll("-", "")}`;
      expect(screen.getByRole("textbox", { name: "Workspace identity" })).toHaveValue(known);
      expect(generate).toHaveBeenCalledOnce();
      expect(api.create).toHaveBeenCalledOnce();
      fireEvent.click(screen.getByRole("button", { name: "Open latest workspace" }));
      await screen.findByText("Saved subject");
      expect(api.read).toHaveBeenCalledWith(known, SCOPE, undefined, expect.any(AbortSignal));
      expect(api.create).toHaveBeenCalledOnce();
    } finally { generate.mockRestore(); }
  });

  it("saves the current explicit navigation at the selected latest revision", async () => {
    render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} initialId={ID} onRestore={vi.fn()} />);
    await screen.findByText("Saved subject");
    fireEvent.change(screen.getByRole("textbox", { name: "Workspace title" }), { target: { value: "Reviewed payments" } });
    fireEvent.click(screen.getByRole("button", { name: "Save current navigation revision" }));
    await waitFor(() => expect(api.replace).toHaveBeenCalledWith(
      ID, 1, { ...VIEW, title: "Reviewed payments" }, SCOPE, expect.any(AbortSignal),
    ));
    expect(api.share).not.toHaveBeenCalled();
  });

  it("requires owner review before saving explicit reader/editor principal memberships", async () => {
    render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} initialId={ID} onRestore={vi.fn()} />);
    await screen.findByText("Saved subject");
    fireEvent.change(screen.getByRole("textbox", { name: "Reader subjects" }), { target: { value: "reader-a\n reader-b \n" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Editor subjects" }), { target: { value: "editor-a" } });
    expect(api.share).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save membership revision" }));
    await waitFor(() => expect(api.share).toHaveBeenCalledWith(
      ID, 1, ["reader-a", "reader-b"], ["editor-a"], SCOPE, expect.any(AbortSignal),
    ));
  });

  it.each([
    { can_edit: false, can_share: false },
    { can_edit: true, can_share: false },
  ])("respects server-reported member permissions %j", async permissions => {
    api.read.mockResolvedValueOnce(envelope(record(permissions)));
    render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} initialId={ID} onRestore={vi.fn()} />);
    await screen.findByText("Saved subject");
    const save = screen.getByRole("button", { name: "Save current navigation revision" });
    if (permissions.can_edit) expect(save).toBeEnabled();
    else expect(save).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Reader subjects" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save membership revision" })).toBeDisabled();
  });

  it("withholds mutations while reviewing an older navigation revision", async () => {
    api.read.mockResolvedValueOnce(envelope(record({ latest_revision: 2, history: [row, { ...row, revision: 2 }] })));
    render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} initialId={ID} initialRevision={1} onRestore={vi.fn()} />);
    await screen.findByText("Saved subject");
    expect(screen.getByRole("button", { name: "Save current navigation revision" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save membership revision" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Apply navigation and load current evidence" })).toBeEnabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Saved revision" }), { target: { value: "2" } });
    expect(api.read).toHaveBeenCalledTimes(1);
    api.read.mockResolvedValueOnce(envelope(record({
      latest_revision: 2, revision: { ...row, revision: 2 }, history: [row, { ...row, revision: 2 }],
    })));
    fireEvent.click(screen.getByRole("button", { name: "Open selected revision" }));
    await waitFor(() => expect(api.read).toHaveBeenCalledWith(ID, SCOPE, 2, expect.any(AbortSignal)));
    expect(await screen.findByText("2 of 2")).toBeInTheDocument();
  });

  it("returns a scoped exact-revision navigation link without granting membership", async () => {
    render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} initialId={ID} onRestore={vi.fn()} />);
    const link = await screen.findByRole("link", { name: "Open or share this exact navigation revision" });
    const url = new URL(link.getAttribute("href")!, "http://localhost");
    expect(url.searchParams.get("workspace_id")).toBe(ID);
    expect(url.searchParams.get("workspace_revision")).toBe("1");
    expect(url.searchParams.get("subscription")).toBe("sub-a");
    expect(url.searchParams.get("support_team")).toBe("sre");
    expect(url.searchParams.get("criticality")).toBe("high");
    expect(url.searchParams.get("value")).toBe("Payments");
    expect(api.share).not.toHaveBeenCalled();
  });

  it("discards a late metadata read after the component crosses its operating scope", async () => {
    let resolve!: (value: unknown) => void;
    api.read.mockReturnValueOnce(new Promise(accept => { resolve = accept; }));
    const nextScope = { subscription: ["sub-b"] };
    api.read.mockResolvedValueOnce(envelope(record({ owner: "next-owner", scope: nextScope })));
    const view = render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} initialId={ID} onRestore={vi.fn()} />);
    view.rerender(<InvestigationTeamWorkspacePanel scope={nextScope} view={VIEW} initialId={ID} onRestore={vi.fn()} />);
    await screen.findByText("next-owner");
    await act(async () => resolve(envelope(record())));
    expect(screen.queryByText("owner", { selector: "dd" })).not.toBeInTheDocument();
    expect(screen.getByText("next-owner")).toBeInTheDocument();
  });

  it("shows storage/conflict failure without a false revision or automatic retry", async () => {
    api.replace.mockRejectedValueOnce(new Error("Workspace changed; reload before saving"));
    render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} initialId={ID} onRestore={vi.fn()} />);
    await screen.findByText("Saved subject");
    fireEvent.click(screen.getByRole("button", { name: "Save current navigation revision" }));
    await screen.findByText("Workspace operation not confirmed");
    expect(screen.getByText("1 of 1")).toBeInTheDocument();
    expect(api.replace).toHaveBeenCalledOnce();
    expect(api.read).toHaveBeenCalledOnce();
  });

  it("does not display a workspace returned under another identity", async () => {
    api.read.mockResolvedValueOnce(envelope(record({ workspace_id: `wrk-${"b".repeat(32)}` })));
    render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} initialId={ID} onRestore={vi.fn()} />);
    await screen.findByText("Workspace operation not confirmed");
    expect(screen.queryByText("Saved subject")).not.toBeInTheDocument();
  });

  it("rejects an unexpected response revision instead of silently opening a different revision", async () => {
    api.read.mockResolvedValueOnce(envelope(record({ latest_revision: 2, revision: { ...row, revision: 2 } })));
    render(<InvestigationTeamWorkspacePanel scope={SCOPE} view={VIEW} initialId={ID} initialRevision={1} onRestore={vi.fn()} />);
    await screen.findByText("Workspace operation not confirmed");
    expect(screen.queryByText("Saved subject")).not.toBeInTheDocument();
  });
});
