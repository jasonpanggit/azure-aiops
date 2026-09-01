import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Regression coverage for the sign-in/refresh behaviour of lib/auth.
 *
 * The bug these guard against: MSAL v3+ rejects every `acquireTokenSilent`
 * call until `initialize()` resolves, so a browser refresh raced page data
 * fetches against MSAL startup, silently produced a null token, and the API
 * answered every request with "A bearer token is required".
 */

const acquireTokenSilent = vi.fn();
const initialize = vi.fn();
const logoutRedirect = vi.fn();
const getAllAccounts = vi.fn();
const getActiveAccountMock = vi.fn();

class FakeInteractionRequiredAuthError extends Error {}

vi.mock("@azure/msal-browser", () => ({
  PublicClientApplication: class {
    initialize = initialize;
    acquireTokenSilent = acquireTokenSilent;
    logoutRedirect = logoutRedirect;
    getAllAccounts = getAllAccounts;
    getActiveAccount = getActiveAccountMock;
  },
  InteractionRequiredAuthError: FakeInteractionRequiredAuthError,
  LogLevel: { Error: 0 },
}));

const account = { homeAccountId: "abc", username: "operator@contoso.com", name: "Ops Operator" };

async function importAuth() {
  return import("@/lib/auth");
}

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID = "test-client-id";
  getActiveAccountMock.mockReturnValue(account);
  getAllAccounts.mockReturnValue([account]);
  initialize.mockResolvedValue(undefined);
  acquireTokenSilent.mockResolvedValue({ accessToken: "token-123" });
  window.sessionStorage.clear();
});

afterEach(() => {
  delete process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID;
  vi.restoreAllMocks();
});

describe("getAccessToken", () => {
  it("initializes MSAL before acquiring a token", async () => {
    const { getAccessToken } = await importAuth();

    const token = await getAccessToken();

    expect(token).toBe("token-123");
    expect(initialize).toHaveBeenCalled();
    // The ordering is the whole point: acquiring before initialize() resolves
    // is what produced the missing-bearer-token failures on refresh.
    expect(initialize.mock.invocationCallOrder[0]).toBeLessThan(
      acquireTokenSilent.mock.invocationCallOrder[0]
    );
  });

  it("only initializes once across repeated calls", async () => {
    const { getAccessToken } = await importAuth();

    await getAccessToken();
    await getAccessToken();

    expect(initialize).toHaveBeenCalledTimes(1);
  });

  it("returns null without acquiring a token when initialization fails", async () => {
    initialize.mockRejectedValue(new Error("init boom"));
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { getAccessToken } = await importAuth();

    expect(await getAccessToken()).toBeNull();
    expect(acquireTokenSilent).not.toHaveBeenCalled();
  });

  it("retries initialization after a transient failure rather than caching the rejection", async () => {
    initialize.mockRejectedValueOnce(new Error("transient")).mockResolvedValue(undefined);
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { getAccessToken } = await importAuth();

    expect(await getAccessToken()).toBeNull();
    expect(await getAccessToken()).toBe("token-123");
    expect(initialize).toHaveBeenCalledTimes(2);
  });

  it("signs the user out when the session has genuinely expired", async () => {
    acquireTokenSilent.mockRejectedValue(new FakeInteractionRequiredAuthError("expired"));
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { getAccessToken } = await importAuth();

    expect(await getAccessToken()).toBeNull();
    await vi.waitFor(() => expect(logoutRedirect).toHaveBeenCalled());
  });

  it("does not sign the user out for a transient acquisition failure", async () => {
    acquireTokenSilent.mockRejectedValue(new Error("transient network blip"));
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { getAccessToken } = await importAuth();

    expect(await getAccessToken()).toBeNull();
    expect(logoutRedirect).not.toHaveBeenCalled();
  });
});

describe("signOut", () => {
  it("logs out and returns the user to the app origin", async () => {
    const { signOut } = await importAuth();

    await signOut();

    expect(logoutRedirect).toHaveBeenCalledWith(
      expect.objectContaining({ postLogoutRedirectUri: window.location.origin })
    );
  });

  it("is not blocked by the one-shot re-authentication guard", async () => {
    const { forceReauthentication, signOut } = await importAuth();

    // Consume the guard, as an automatic recovery attempt would.
    await forceReauthentication();
    logoutRedirect.mockClear();

    await signOut();

    // A user-initiated sign-out must still work afterwards.
    expect(logoutRedirect).toHaveBeenCalled();
  });
});
