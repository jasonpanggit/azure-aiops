import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeProvider, useScope } from "@/lib/scope-context";
import {
  COPILOT_THREAD_STORAGE_KEY,
  ThreadContinuityProvider,
  useThreadContinuity,
} from "./thread-context";

const authEvents = vi.hoisted(() => new Set<(message: { eventType: string }) => void>());

vi.mock("@/lib/auth", () => ({
  isMsalConfigured: true,
  getMsalInstance: () => ({
    addEventCallback: vi.fn((callback: (message: { eventType: string }) => void) => {
      authEvents.add(callback);
      return "thread-context-test";
    }),
    removeEventCallback: vi.fn((callbackId: string) => {
      if (callbackId === "thread-context-test") authEvents.clear();
    }),
  }),
}));

const THREAD_ID = "thr-0123456789abcdef0123456789abcdef";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return Array.from(this.values.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

function Harness({ route }: { route: string }) {
  const { setScope } = useScope();
  const {
    thread,
    requiresServerRevalidation,
    resetReason,
    acceptServerState,
    resetContinuity,
  } = useThreadContinuity();

  return (
    <>
      <output aria-label="route">{route}</output>
      <output aria-label="thread">
        {thread ? `${thread.threadId}:${thread.threadRevision}` : "none"}
      </output>
      <output aria-label="revalidation">
        {requiresServerRevalidation ? "required" : "current"}
      </output>
      <output aria-label="reset reason">{resetReason ?? "none"}</output>
      <button
        type="button"
        onClick={() => acceptServerState({
          threadId: THREAD_ID,
          threadRevision: thread ? thread.threadRevision + 1 : 7,
        })}
      >
        Accept server thread
      </button>
      <button
        type="button"
        onClick={() => setScope({ subscription: ["sub-narrow"] })}
      >
        Narrow scope
      </button>
      <button type="button" onClick={() => resetContinuity("not_found")}>
        Server not found
      </button>
    </>
  );
}

function App({
  children,
  storage,
}: {
  children: ReactNode;
  storage?: Storage;
}) {
  return (
    <ScopeProvider initialScope={{ subscription: ["sub-wide", "sub-narrow"] }}>
      <ThreadContinuityProvider storage={storage}>
        {children}
      </ThreadContinuityProvider>
    </ScopeProvider>
  );
}

describe("ThreadContinuityProvider", () => {
  beforeEach(() => {
    authEvents.clear();
    window.sessionStorage.clear();
  });

  it("persists only the opaque server thread ID and revision across navigation and remount", async () => {
    const view = render(<App><Harness route="/inventory" /></App>);

    fireEvent.click(screen.getByRole("button", { name: "Accept server thread" }));
    expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:7`);

    const serialized = window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY);
    expect(serialized).not.toBeNull();
    expect(JSON.parse(serialized!)).toEqual({
      thread_id: THREAD_ID,
      thread_revision: 7,
    });
    expect(Object.keys(JSON.parse(serialized!))).toEqual([
      "thread_id",
      "thread_revision",
    ]);

    view.rerender(<App><Harness route="/services/api" /></App>);
    expect(screen.getByLabelText("route")).toHaveTextContent("/services/api");
    expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:7`);

    view.unmount();
    render(<App><Harness route="/remediation" /></App>);
    expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:7`);
    expect(screen.getByLabelText("revalidation")).toHaveTextContent("required");
  });

  it("does not discover continuity from another tab storage area", () => {
    const firstTab = new MemoryStorage();
    const secondTab = new MemoryStorage();
    firstTab.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify({
      thread_id: THREAD_ID,
      thread_revision: 3,
    }));

    render(<App storage={secondTab}><Harness route="/inventory" /></App>);

    expect(screen.getByLabelText("thread")).toHaveTextContent("none");
    expect(secondTab.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
  });

  it("retains only the opaque handle on scope change and requires a server recheck", () => {
    render(<App><Harness route="/inventory" /></App>);
    fireEvent.click(screen.getByRole("button", { name: "Accept server thread" }));

    fireEvent.click(screen.getByRole("button", { name: "Narrow scope" }));

    expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:7`);
    expect(screen.getByLabelText("revalidation")).toHaveTextContent("required");
    expect(JSON.parse(
      window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)!,
    )).toEqual({
      thread_id: THREAD_ID,
      thread_revision: 7,
    });

    fireEvent.click(screen.getByRole("button", { name: "Accept server thread" }));
    expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:8`);
    expect(screen.getByLabelText("revalidation")).toHaveTextContent("current");
  });

  it("clears continuity when logout starts", async () => {
    render(<App><Harness route="/inventory" /></App>);
    fireEvent.click(screen.getByRole("button", { name: "Accept server thread" }));

    authEvents.forEach((callback) => callback({ eventType: "msal:logoutStart" }));

    await waitFor(() => {
      expect(screen.getByLabelText("thread")).toHaveTextContent("none");
    });
    expect(window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
    expect(screen.getByLabelText("reset reason")).toHaveTextContent("session_end");
  });

  it.each([
    "not-json",
    JSON.stringify({ thread_id: "not-opaque", thread_revision: 1 }),
    JSON.stringify({ thread_id: THREAD_ID, thread_revision: 0 }),
    JSON.stringify({
      thread_id: THREAD_ID,
      thread_revision: 1,
      transcript: ["must not be retained"],
    }),
  ])("rejects malformed or authority-bearing stored continuity: %s", (stored) => {
    window.sessionStorage.setItem(COPILOT_THREAD_STORAGE_KEY, stored);

    render(<App><Harness route="/inventory" /></App>);

    expect(screen.getByLabelText("thread")).toHaveTextContent("none");
    expect(window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
  });

  it("uses one generic reset path for server not-found semantics", () => {
    render(<App><Harness route="/inventory" /></App>);
    fireEvent.click(screen.getByRole("button", { name: "Accept server thread" }));

    fireEvent.click(screen.getByRole("button", { name: "Server not found" }));

    expect(screen.getByLabelText("thread")).toHaveTextContent("none");
    expect(screen.getByLabelText("reset reason")).toHaveTextContent("not_found");
    expect(window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
  });
});
