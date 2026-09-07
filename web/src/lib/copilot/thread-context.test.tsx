import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

interface TestLockApi {
  request(
    name: string,
    options: LockOptions,
    callback: (lock: Lock | null) => unknown,
  ): Promise<unknown>;
}

class TestLockManager implements TestLockApi {
  private readonly held = new Set<string>();

  constructor(private readonly rejectRequests = false) {}

  request(
    name: string,
    _options: LockOptions,
    callback: (lock: Lock | null) => unknown,
  ): Promise<unknown> {
    if (this.rejectRequests) {
      return Promise.reject(new Error("lock manager unavailable"));
    }
    if (this.held.has(name)) {
      return Promise.resolve(callback(null));
    }
    this.held.add(name);
    return Promise.resolve(callback({
      name,
      mode: "exclusive",
    } as Lock)).finally(() => {
      this.held.delete(name);
    });
  }

  get heldNames(): string[] {
    return Array.from(this.held);
  }
}

class DeferredTestLockManager implements TestLockApi {
  private pending: {
    name: string;
    callback: (lock: Lock | null) => unknown;
  } | null = null;

  request(
    name: string,
    _options: LockOptions,
    callback: (lock: Lock | null) => unknown,
  ): Promise<unknown> {
    this.pending = { name, callback };
    return new Promise(() => undefined);
  }

  get hasPendingRequest(): boolean {
    return this.pending !== null;
  }

  grant(): void {
    const pending = this.pending;
    this.pending = null;
    if (!pending) throw new Error("No pending lock request");
    void pending.callback({
      name: pending.name,
      mode: "exclusive",
    } as Lock);
  }
}

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

function installWebLocks(lockManager: TestLockApi): void {
  vi.stubGlobal("navigator", Object.assign(
    Object.create(globalThis.navigator),
    { locks: lockManager },
  ));
  vi.stubGlobal("crypto", {
    subtle: {
      digest: async (_algorithm: string, value: BufferSource) => {
        const input = new Uint8Array(value as ArrayBuffer);
        const output = new Uint8Array(32);
        input.forEach((byte, index) => {
          output[index % output.length] ^= byte;
        });
        return output.buffer;
      },
    },
  });
}

function disableWebLocks(): void {
  vi.stubGlobal("navigator", Object.assign(
    Object.create(globalThis.navigator),
    { locks: undefined },
  ));
}

describe("ThreadContinuityProvider", () => {
  beforeEach(() => {
    authEvents.clear();
    window.sessionStorage.clear();
    disableWebLocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("persists only the opaque server thread ID and revision across navigation and remount", async () => {
    const lockManager = new TestLockManager();
    installWebLocks(lockManager);
    const view = render(<App><Harness route="/inventory" /></App>);

    fireEvent.click(screen.getByRole("button", { name: "Accept server thread" }));
    expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:7`);

    await waitFor(() => {
      expect(window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).not.toBeNull();
    });
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
    await waitFor(() => expect(lockManager.heldNames).toHaveLength(0));
    render(<App><Harness route="/remediation" /></App>);
    await waitFor(() => {
      expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:7`);
    });
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

  it("clears a stored handle when Web Locks is unavailable", async () => {
    const storage = new MemoryStorage();
    storage.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify({
      thread_id: THREAD_ID,
      thread_revision: 4,
    }));

    render(<App storage={storage}><Harness route="/inventory" /></App>);

    expect(screen.getByLabelText("thread")).toHaveTextContent("none");
    await waitFor(() => {
      expect(storage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
    });
  });

  it("clears a stored handle when ownership acquisition rejects", async () => {
    installWebLocks(new TestLockManager(true));
    const storage = new MemoryStorage();
    storage.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify({
      thread_id: THREAD_ID,
      thread_revision: 4,
    }));

    render(<App storage={storage}><Harness route="/inventory" /></App>);

    expect(screen.getByLabelText("thread")).toHaveTextContent("none");
    await waitFor(() => {
      expect(storage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
    });
  });

  it("removes restored storage while lock acquisition is pending", async () => {
    const lockManager = new DeferredTestLockManager();
    installWebLocks(lockManager);
    const storage = new MemoryStorage();
    storage.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify({
      thread_id: THREAD_ID,
      thread_revision: 4,
    }));

    render(<App storage={storage}><Harness route="/inventory" /></App>);

    expect(storage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
    expect(screen.getByLabelText("thread")).toHaveTextContent("none");
    await waitFor(() => expect(lockManager.hasPendingRequest).toBe(true));
    expect(storage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
    expect(screen.getByLabelText("thread")).toHaveTextContent("none");

    act(() => lockManager.grant());

    await waitFor(() => {
      expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:4`);
      expect(storage.getItem(COPILOT_THREAD_STORAGE_KEY)).not.toBeNull();
    });
  });

  it("preserves a pending restoration through React StrictMode initialization", async () => {
    const lockManager = new TestLockManager();
    installWebLocks(lockManager);
    const storage = new MemoryStorage();
    storage.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify({
      thread_id: THREAD_ID,
      thread_revision: 5,
    }));

    render(
      <StrictMode>
        <App storage={storage}><Harness route="/inventory" /></App>
      </StrictMode>,
    );

    expect(storage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
    await waitFor(() => {
      expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:5`);
      expect(storage.getItem(COPILOT_THREAD_STORAGE_KEY)).not.toBeNull();
    });
    expect(lockManager.heldNames).toHaveLength(1);
  });

  it("keeps a newly accepted thread in memory without persisting when locks are unavailable", async () => {
    const storage = new MemoryStorage();
    render(<App storage={storage}><Harness route="/inventory" /></App>);

    fireEvent.click(screen.getByRole("button", { name: "Accept server thread" }));

    expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:7`);
    await waitFor(() => {
      expect(storage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
    });
  });

  it("restores a copied session entry after a same-tab reload has no live owner", async () => {
    const lockManager = new TestLockManager();
    installWebLocks(lockManager);
    const storage = new MemoryStorage();
    storage.setItem(COPILOT_THREAD_STORAGE_KEY, JSON.stringify({
      thread_id: THREAD_ID,
      thread_revision: 5,
    }));

    const first = render(<App storage={storage}><Harness route="/inventory" /></App>);
    await waitFor(() => {
      expect(first.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:5`);
    });
    expect(lockManager.heldNames).toHaveLength(1);
    first.unmount();
    await waitFor(() => expect(lockManager.heldNames).toHaveLength(0));

    const reloaded = render(<App storage={storage}><Harness route="/inventory" /></App>);
    await waitFor(() => {
      expect(reloaded.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:5`);
    });
    expect(lockManager.heldNames).toHaveLength(1);
    expect(storage.getItem(COPILOT_THREAD_STORAGE_KEY)).not.toBeNull();
  });

  it("locks accepted continuity and clears a cloned entry in another live tab", async () => {
    const lockManager = new TestLockManager();
    installWebLocks(lockManager);
    const originalStorage = new MemoryStorage();

    const original = render(
      <App storage={originalStorage}><Harness route="/inventory" /></App>,
    );
    fireEvent.click(within(original.container).getByRole(
      "button",
      { name: "Accept server thread" },
    ));
    await waitFor(() => {
      expect(lockManager.heldNames).toHaveLength(1);
    });
    const serialized = originalStorage.getItem(COPILOT_THREAD_STORAGE_KEY);
    expect(serialized).not.toBeNull();
    expect(lockManager.heldNames[0]).not.toContain(THREAD_ID);
    expect(lockManager.heldNames[0]).toMatch(/[a-f0-9]{64}$/);

    const clonedStorage = new MemoryStorage();
    clonedStorage.setItem(COPILOT_THREAD_STORAGE_KEY, serialized!);
    const clone = render(
      <App storage={clonedStorage}><Harness route="/inventory" /></App>,
    );

    expect(within(clone.container).getByLabelText("thread")).toHaveTextContent("none");
    await waitFor(() => {
      expect(clonedStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
    });
    expect(within(original.container).getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:7`);
    expect(originalStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBe(serialized);
  });

  it("retains only the opaque handle on scope change and requires a server recheck", () => {
    installWebLocks(new TestLockManager());
    render(<App><Harness route="/inventory" /></App>);
    fireEvent.click(screen.getByRole("button", { name: "Accept server thread" }));

    fireEvent.click(screen.getByRole("button", { name: "Narrow scope" }));

    expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:7`);
    expect(screen.getByLabelText("revalidation")).toHaveTextContent("required");
    return waitFor(() => {
      expect(JSON.parse(
        window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)!,
      )).toEqual({
        thread_id: THREAD_ID,
        thread_revision: 7,
      });
    }).then(() => {
      fireEvent.click(screen.getByRole("button", { name: "Accept server thread" }));
      expect(screen.getByLabelText("thread")).toHaveTextContent(`${THREAD_ID}:8`);
      expect(screen.getByLabelText("revalidation")).toHaveTextContent("current");
    });
  });

  it("clears continuity when logout starts", async () => {
    installWebLocks(new TestLockManager());
    render(<App><Harness route="/inventory" /></App>);
    fireEvent.click(screen.getByRole("button", { name: "Accept server thread" }));

    act(() => {
      authEvents.forEach((callback) => callback({ eventType: "msal:logoutStart" }));
    });

    expect(screen.getByLabelText("thread")).toHaveTextContent("none");
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
    installWebLocks(new TestLockManager());
    render(<App><Harness route="/inventory" /></App>);
    fireEvent.click(screen.getByRole("button", { name: "Accept server thread" }));

    fireEvent.click(screen.getByRole("button", { name: "Server not found" }));

    expect(screen.getByLabelText("thread")).toHaveTextContent("none");
    expect(screen.getByLabelText("reset reason")).toHaveTextContent("not_found");
    expect(window.sessionStorage.getItem(COPILOT_THREAD_STORAGE_KEY)).toBeNull();
  });
});
