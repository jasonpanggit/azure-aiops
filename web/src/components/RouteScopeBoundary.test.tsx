import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { EventType, type EventMessage } from "@azure/msal-browser";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useApi } from "@/hooks/useApi";
import { useThreadContinuity } from "@/lib/copilot/thread-context";
import { SCOPE_DIMENSIONS, type ScopeSelection } from "@/lib/scope";
import { ScopeProvider, useScope } from "@/lib/scope-context";

const mocks = vi.hoisted(() => ({
  query: "", path: "/resource-health", read: vi.fn(),
  callbacks: new Map<string, (message: EventMessage) => void>(), nextCallback: 0,
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(mocks.query),
  usePathname: () => mocks.path,
}));
vi.mock("@/lib/auth", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/auth")>();
  return { ...actual, isMsalConfigured: true, getMsalInstance: () => ({
    addEventCallback: (callback: (message: EventMessage) => void) => {
      const id = String(++mocks.nextCallback);
      mocks.callbacks.set(id, callback);
      return id;
    },
    removeEventCallback: (id: string) => { mocks.callbacks.delete(id); },
  }) };
});

import { RouteScopeBoundary } from "./RouteScopeBoundary";

function GlobalControls() {
  const { scope, setScope } = useScope();
  return <>
    <output aria-label="Global scope">{JSON.stringify(scope)}</output>
    <button onClick={() => setScope({ subscription: ["other"] })}>Select other subscription</button>
  </>;
}

function Probe() {
  const { scope } = useScope();
  const continuity = useThreadContinuity();
  const [draft, setDraft] = useState("");
  const source = useApi<{ marker: string }>(signal => mocks.read(scope, signal), [scope]);
  return <>
    <output aria-label="Page scope">{JSON.stringify(scope)}</output>
    <output aria-label="Loaded observation">{source.data?.marker ?? "Pending"}</output>
    <input aria-label="Review draft" value={draft} onChange={event => setDraft(event.target.value)} />
    <button onClick={() => continuity.acceptServerState({ threadId: `thr-${"a".repeat(32)}`, threadRevision: 1 })}>Accept server continuity</button>
    <output aria-label="Thread handle">{continuity.thread?.threadId ?? "None"}</output>
    <output aria-label="Thread revalidation">{String(continuity.requiresServerRevalidation)}</output>
  </>;
}

function Subject({ initialScope = {} }: { initialScope?: ScopeSelection }) {
  return <ScopeProvider initialScope={initialScope}><GlobalControls /><RouteScopeBoundary><Probe /></RouteScopeBoundary></ScopeProvider>;
}

describe("shared page bookmark scope boundary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    mocks.callbacks.clear();
    mocks.query = "";
    mocks.path = "/resource-health";
    mocks.read.mockReset().mockResolvedValue({ marker: "Current authorized observation" });
  });

  it.each(SCOPE_DIMENSIONS)("restores bookmarked %s before mounting the source and leaves the global selector unchanged", async dimension => {
    mocks.query = `${dimension}=Selected`;
    render(<Subject />);
    await screen.findByText("Current authorized observation");
    expect(mocks.read).toHaveBeenCalledWith({ [dimension]: ["Selected"] }, expect.any(AbortSignal));
    expect(screen.getByLabelText("Global scope")).toHaveTextContent("{}");
    expect(screen.getByLabelText("Bookmarked page scope")).toHaveTextContent("Selected");
  });

  it("retains omitted global constraints and accepts only a selected subset with case-insensitive deduplication", async () => {
    mocks.query = "subscription=SUB-A&subscription=sub-a";
    render(<Subject initialScope={{ subscription: ["sub-a", "sub-b"], environment: ["prod"] }} />);
    await screen.findByText("Current authorized observation");
    expect(mocks.read).toHaveBeenCalledWith({ subscription: ["sub-a"], environment: ["prod"] }, expect.any(AbortSignal));
  });

  it.each(["subscription=other", "subscription=", "subscription=%00selected", "subscription=selected%0A"])("rejects %s without mounting the page", bookmark => {
    mocks.query = `view=diagnostics&health_q=database&${bookmark}`;
    render(<Subject initialScope={{ subscription: ["selected"] }} />);
    expect(screen.getByRole("heading", { name: "Page bookmark scope unavailable" })).toBeInTheDocument();
    expect(mocks.read).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Page scope")).not.toBeInTheDocument();
  });

  it("preserves non-scope query fields and the global constraints in the explicit recovery link", () => {
    mocks.query = "view=diagnostics&health_q=database&subscription=outside&region=";
    render(<Subject initialScope={{ subscription: ["selected"], environment: ["prod"] }} />);
    expect(screen.getByRole("heading", { name: "Page bookmark scope unavailable" })).toBeInTheDocument();
    expect(mocks.read).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Page scope")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Use current operating context" })).toHaveAttribute("href", "/resource-health?view=diagnostics&health_q=database&environment=prod&subscription=selected");
    expect(screen.getByLabelText("Global scope")).toHaveTextContent('"selected"');
  });

  it("does not remount or reread providers for unrelated URL filters or ordinary same-scope navigation", async () => {
    mocks.query = "subscription=selected&health_q=first";
    const view = render(<Subject />);
    await screen.findByText("Current authorized observation");
    fireEvent.change(screen.getByLabelText("Review draft"), { target: { value: "Keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept server continuity" }));
    mocks.query = "subscription=selected&health_q=second";
    mocks.path = "/twin";
    view.rerender(<Subject />);
    expect(screen.getByLabelText("Review draft")).toHaveValue("Keep this draft");
    expect(mocks.read).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Thread handle")).toHaveTextContent(`thr-${"a".repeat(32)}`);
    expect(screen.getByLabelText("Thread revalidation")).toHaveTextContent("false");
  });

  it("remounts data and drafts immediately on URL scope changes and rejects a late old response", async () => {
    mocks.query = "subscription=first";
    let finish!: (value: { marker: string }) => void;
    mocks.read.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const view = render(<Subject />);
    await waitFor(() => expect(mocks.read).toHaveBeenCalledTimes(1));
    const oldSignal: AbortSignal = mocks.read.mock.calls[0][1];
    fireEvent.change(screen.getByLabelText("Review draft"), { target: { value: "Old-scope draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept server continuity" }));
    mocks.read.mockResolvedValue({ marker: "Second scope observation" });
    mocks.query = "subscription=second";
    view.rerender(<Subject />);
    expect(screen.getByLabelText("Review draft")).toHaveValue("");
    expect(oldSignal.aborted).toBe(true);
    await screen.findByText("Second scope observation");
    expect(screen.getByLabelText("Thread revalidation")).toHaveTextContent("true");
    await act(async () => { finish({ marker: "Late first scope observation" }); });
    expect(screen.queryByText("Late first scope observation")).not.toBeInTheDocument();
  });

  it("withholds an incompatible bookmark after the global selector changes", async () => {
    mocks.query = "subscription=selected";
    render(<Subject />);
    await screen.findByText("Current authorized observation");
    fireEvent.click(screen.getByRole("button", { name: "Select other subscription" }));
    expect(screen.getByRole("heading", { name: "Page bookmark scope unavailable" })).toBeInTheDocument();
    expect(screen.queryByText("Current authorized observation")).not.toBeInTheDocument();
    expect(mocks.read).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "Use current operating context" })).toHaveAttribute("href", "/resource-health?subscription=other");
  });

  it("keeps sign-out handling mounted while an invalid bookmark withholds the page", async () => {
    mocks.query = "subscription=selected";
    const view = render(<Subject />);
    await screen.findByText("Current authorized observation");
    fireEvent.click(screen.getByRole("button", { name: "Accept server continuity" }));
    expect(screen.getByLabelText("Thread handle")).not.toHaveTextContent("None");
    const callbackIds = Array.from(mocks.callbacks.keys());
    expect(callbackIds).toHaveLength(1);
    mocks.query = "subscription=";
    view.rerender(<Subject />);
    expect(screen.getByRole("heading", { name: "Page bookmark scope unavailable" })).toBeInTheDocument();
    expect(Array.from(mocks.callbacks.keys())).toEqual(callbackIds);
    act(() => {
      const event: EventMessage = { eventType: EventType.LOGOUT_SUCCESS, interactionType: null, payload: null, error: null, timestamp: Date.now(), correlationId: "bookmark-signout" };
      mocks.callbacks.forEach(callback => callback(event));
    });
    mocks.query = "subscription=selected";
    view.rerender(<Subject />);
    await screen.findByText("Current authorized observation");
    expect(screen.getByLabelText("Thread handle")).toHaveTextContent("None");
    expect(screen.getByLabelText("Thread revalidation")).toHaveTextContent("false");
  });

  it("leaves an unbookmarked page on the incumbent global selection without a notice", async () => {
    render(<Subject initialScope={{ environment: ["prod"] }} />);
    await screen.findByText("Current authorized observation");
    expect(mocks.read).toHaveBeenCalledWith({ environment: ["prod"] }, expect.any(AbortSignal));
    expect(screen.queryByLabelText("Bookmarked page scope")).not.toBeInTheDocument();
  });
});
