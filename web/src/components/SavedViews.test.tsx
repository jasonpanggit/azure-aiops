import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SavedViews as SavedViewsComponent } from "./SavedViews";
import type { ScopeSelection } from "@/lib/scope";
import type { SavedView, SavedViewCollection, SavedViewSettings } from "@/lib/saved-views";

const mocks = vi.hoisted(() => ({ read: vi.fn(), replace: vi.fn(), restore: vi.fn() }));
vi.mock("@/lib/services", () => ({ savedViewsApi: mocks }));
const current: SavedViewSettings = { kind: "search", query: "show list of VMs", entity_type: "", source: "" };
const search: SavedView = { ...current, view_id: "search-a", name: "My VMs" };
const triage: SavedView = {
  kind: "situations", view_id: "triage-a", name: "P1 queue", query: "", priority: "P1",
  assigned_owner: "", lifecycle_state: "", older_than_hours: null, sort: "default",
};
const collection = (views: SavedView[] = [search, triage], revision = 1): SavedViewCollection => ({
  schema_version: 1, actor: "reader", scope: {}, revision, updated_at: "2026-10-16T12:00:00Z", views,
});
const open = () => fireEvent.click(screen.getByRole("button", { name: "Open saved views" }));
const SavedViews = (props: { scope: ScopeSelection; current: SavedViewSettings; atFirstPage?: boolean }) =>
  <SavedViewsComponent {...props} atFirstPage={props.atFirstPage ?? true} onRestoreCurrent={mocks.restore} />;

describe("On-demand personal saved views", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.read.mockResolvedValue({ data: collection() });
    mocks.replace.mockImplementation((_scope, revision, views) => Promise.resolve({ data: collection(views, revision + 1) }));
  });

  it("acquires no storage until opened and only shows the current kind", async () => {
    render(<SavedViews scope={{}} current={current} />);
    expect(mocks.read).not.toHaveBeenCalled();
    open();
    expect(await screen.findByRole("link", { name: "My VMs" })).toHaveAttribute("href", "/search?q=show+list+of+VMs");
    expect(screen.queryByRole("link", { name: "P1 queue" })).not.toBeInTheDocument();
    expect(screen.getByText(/1 saved view for this page; 2\/20 total/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close saved views" }));
    expect(screen.queryByRole("link", { name: "My VMs" })).not.toBeInTheDocument();
  });

  it("explicitly saves submitted settings while preserving the other page's views", async () => {
    render(<SavedViews scope={{ subscription: ["sub-a"] }} current={current} />);
    open(); await screen.findByRole("link", { name: "My VMs" });
    fireEvent.change(screen.getByRole("textbox", { name: "New view name" }), { target: { value: "Daily discovery" } });
    fireEvent.click(screen.getByRole("button", { name: "Save current view" }));
    await screen.findByText("View saved. No source query was performed.");
    const [scope, revision, views, options] = mocks.replace.mock.calls[0];
    expect(scope).toEqual({ subscription: ["sub-a"] });
    expect(revision).toBe(1);
    expect(views.slice(0, 2)).toEqual([search, triage]);
    expect(views[2]).toEqual({ ...current, view_id: expect.stringMatching(/^[a-f0-9-]+$/), name: "Daily discovery" });
    expect(options.signal).toBeInstanceOf(AbortSignal);
  });

  it("replaces only the selected identity and deletes explicitly at the latest revision", async () => {
    render(<SavedViews scope={{}} current={{ ...current, query: "production applications" }} />);
    open(); await screen.findByRole("link", { name: "My VMs" });
    fireEvent.click(screen.getByRole("button", { name: "Replace My VMs with current filters" }));
    await screen.findByText("View filters replaced. No source query was performed.");
    expect(mocks.replace.mock.calls[0][2]).toEqual([{ ...search, query: "production applications" }, triage]);
    fireEvent.click(screen.getByRole("button", { name: "Delete saved view My VMs" }));
    await screen.findByText("Saved view deleted. Source records were not changed.");
    expect(mocks.replace.mock.calls[1][1]).toBe(2);
    expect(mocks.replace.mock.calls[1][2]).toEqual([triage]);
    expect(screen.getByText(/No saved views for this page/)).toBeInTheDocument();
  });

  it("requires explicit reload after an uncertain update and preserves an unsent name", async () => {
    mocks.replace.mockRejectedValueOnce(new Error("Revision conflict"));
    render(<SavedViews scope={{}} current={current} />);
    open(); await screen.findByRole("link", { name: "My VMs" });
    fireEvent.change(screen.getByRole("textbox", { name: "New view name" }), { target: { value: "Keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Save current view" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Reload saved views before explicitly retrying");
    expect(mocks.replace).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Save current view" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload saved views" }));
    expect(await screen.findByRole("textbox", { name: "New view name" })).toHaveValue("Keep this draft");
    expect(mocks.replace).toHaveBeenCalledTimes(1);
  });

  it("withholds old views on scope change and ignores late replies after abort", async () => {
    let resolve!: (value: { data: SavedViewCollection }) => void;
    mocks.read.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const view = render(<SavedViews scope={{ subscription: ["sub-a"] }} current={current} />);
    open();
    const signal = mocks.read.mock.calls[0][1].signal;
    view.rerender(<SavedViews scope={{ subscription: ["sub-b"] }} current={current} />);
    expect(signal.aborted).toBe(true);
    expect(screen.queryByText("Loading or saving personal views...")).not.toBeInTheDocument();
    await act(async () => { resolve({ data: collection([{ ...search, name: "Private old scope" }]) }); });
    expect(screen.queryByText("Private old scope")).not.toBeInTheDocument();
    open();
    await screen.findByRole("link", { name: "My VMs" });
    expect(mocks.read).toHaveBeenLastCalledWith({ subscription: ["sub-b"] }, expect.any(Object));
  });

  it("blocks saving or replacing blank Search input without blocking saved query recovery", async () => {
    render(<SavedViews scope={{}} current={{ ...current, query: " " }} />);
    open(); await screen.findByRole("link", { name: "My VMs" });
    fireEvent.change(screen.getByRole("textbox", { name: "New view name" }), { target: { value: "Blank" } });
    expect(screen.getByRole("button", { name: "Save current view" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Replace My VMs with current filters" })).toBeDisabled();
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it("counts both kinds against the limit but permits explicit replacement and deletion", async () => {
    mocks.read.mockResolvedValue({ data: collection(Array.from({ length: 20 }, (_, i) => ({ ...search, view_id: `v-${i}`, name: `View ${i}` }))) });
    render(<SavedViews scope={{}} current={current} />);
    open(); await screen.findByRole("link", { name: "View 0" });
    fireEvent.change(screen.getByRole("textbox", { name: "New view name" }), { target: { value: "Overflow" } });
    expect(screen.getByRole("button", { name: "Save current view" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Replace View 0 with current filters" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Delete saved view View 0" })).toBeEnabled();
  });

  it("displays storage failure without success-shaped empty state and recovers on explicit reload", async () => {
    mocks.read.mockRejectedValueOnce(new Error("Storage unavailable"));
    render(<SavedViews scope={{}} current={current} />);
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("Storage unavailable");
    expect(screen.queryByText(/No saved views for this page/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload saved views" }));
    await screen.findByRole("link", { name: "My VMs" });
  });

  it("shows Situation filter details and restores first-page triage without saved selections", async () => {
    render(<SavedViews scope={{ region: ["eastus"] }} current={triage} />);
    open();
    const link = await screen.findByRole("link", { name: "P1 queue" });
    expect(link).toHaveAttribute("href", "/situations?region=eastus&priority=P1");
    const item = link.closest("li")!;
    expect(within(item).getByText("All authorized situations")).toBeInTheDocument();
    expect(within(item).getByText("priority")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "My VMs" })).not.toBeInTheDocument();
  });

  it("does not issue duplicate mutations while a save is pending", async () => {
    let resolve!: (value: { data: SavedViewCollection }) => void;
    mocks.replace.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    render(<SavedViews scope={{}} current={current} />);
    open(); await screen.findByRole("link", { name: "My VMs" });
    fireEvent.change(screen.getByRole("textbox", { name: "New view name" }), { target: { value: "One save" } });
    const button = screen.getByRole("button", { name: "Save current view" });
    fireEvent.click(button); fireEvent.click(button);
    expect(mocks.replace).toHaveBeenCalledTimes(1);
    await act(async () => { resolve({ data: collection() }); });
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("reaquires current evidence when an unmodified saved view click would not change the URL", async () => {
    render(<SavedViews scope={{}} current={current} />);
    open();
    const link = await screen.findByRole("link", { name: "My VMs" });
    fireEvent.click(link);
    expect(mocks.restore).toHaveBeenCalledTimes(1);
    fireEvent.click(link, { ctrlKey: true });
    expect(mocks.restore).toHaveBeenCalledTimes(1);
  });

  it("navigates to the first page instead of reloading the current later page", async () => {
    render(<SavedViews scope={{}} current={current} atFirstPage={false} />);
    open();
    const link = await screen.findByRole("link", { name: "My VMs" });
    fireEvent.click(link);
    expect(mocks.restore).not.toHaveBeenCalled();
    expect(link).toHaveAttribute("href", "/search?q=show+list+of+VMs");
  });
});
