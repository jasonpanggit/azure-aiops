import {
  type AccountInfo,
  type Configuration,
  InteractionRequiredAuthError,
  LogLevel,
  PublicClientApplication,
} from "@azure/msal-browser";

/**
 * MSAL configuration for the Azure AI Operations Workbench.
 *
 * All three values are required for real sign-in and must be supplied via
 * environment variables at build/deploy time. In local development without
 * an Entra app registration, `getAccessToken()` degrades to a static dev
 * token fetched from the `/api/dev-token` route handler, which reads the
 * server-only `AIOPS_DEV_TOKEN` env var (matching the API's
 * `StaticTokenAuthenticator`, see docs/OPERATIONS_API.md) so the UI is usable
 * without a tenant.
 */
export const msalConfig: Configuration = {
  auth: {
    clientId: process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID ?? "",
    authority: process.env.NEXT_PUBLIC_ENTRA_TENANT_ID
      ? `https://login.microsoftonline.com/${process.env.NEXT_PUBLIC_ENTRA_TENANT_ID}`
      : "https://login.microsoftonline.com/common",
    redirectUri: typeof window !== "undefined" ? window.location.origin : undefined,
  },
  cache: {
    cacheLocation: "sessionStorage",
  },
  system: {
    loggerOptions: {
      loggerCallback: (level, message, containsPii) => {
        if (containsPii) return;
        if (level === LogLevel.Error) console.error(message);
      },
    },
  },
};

/** Scopes requested for the Operations API. Configure the API's app-id-uri via env. */
export const apiLoginRequest = {
  scopes: process.env.NEXT_PUBLIC_ENTRA_API_SCOPE ? [process.env.NEXT_PUBLIC_ENTRA_API_SCOPE] : ["User.Read"],
};

export const isMsalConfigured = Boolean(process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID);

let msalInstance: PublicClientApplication | null = null;
let msalReady: Promise<void> | null = null;

export function getMsalInstance(): PublicClientApplication {
  if (!msalInstance) {
    msalInstance = new PublicClientApplication(msalConfig);
  }
  return msalInstance;
}

/**
 * Resolves once MSAL has finished `initialize()`.
 *
 * MSAL v3+ refuses every `acquireTokenSilent` call with `uninitialized_public_client_application`
 * until `initialize()` has resolved. `MsalProvider` does call it, but asynchronously — so on a
 * browser refresh the app's own data fetches start before initialization completes, token
 * acquisition throws, `getAccessToken()` returns null, and the request goes out with no
 * Authorization header. The API then rejects it with "A bearer token is required", which looks
 * like an expired session but is really a startup race that a second refresh appears to "fix".
 *
 * Awaiting the same memoized promise here makes every token acquisition wait for a ready
 * instance instead of racing it. `initialize()` is idempotent, so calling it here as well as in
 * MsalProvider is safe.
 */
export function ensureMsalInitialized(): Promise<void> {
  if (!isMsalConfigured) return Promise.resolve();
  const instance = getMsalInstance();
  msalReady ??= instance.initialize().catch((error: unknown) => {
    // Do not cache a rejected promise: a transient initialization failure would
    // otherwise permanently poison every future token acquisition.
    msalReady = null;
    throw error;
  });
  return msalReady;
}

/** The signed-in account, or null when nobody is signed in. */
export function getActiveAccount(): AccountInfo | null {
  if (!isMsalConfigured) return null;
  const instance = getMsalInstance();
  return instance.getActiveAccount() ?? instance.getAllAccounts()[0] ?? null;
}

/**
 * Resolves the bearer token for API calls: a real MSAL access token when an
 * Entra app registration is configured and a user is signed in, otherwise a
 * static dev token fetched from `/api/dev-token` (local development only,
 * never used when NEXT_PUBLIC_ENTRA_CLIENT_ID is set).
 */
export async function getAccessToken(): Promise<string | null> {
  if (!isMsalConfigured) {
    try {
      const res = await fetch("/api/dev-token");
      if (!res.ok) return null;
      const { token } = (await res.json()) as { token: string | null };
      return token;
    } catch {
      return null;
    }
  }

  try {
    await ensureMsalInitialized();
  } catch (error) {
    console.warn("getAccessToken: MSAL initialization failed", error);
    return null;
  }

  const instance = getMsalInstance();
  const account = getActiveAccount();
  if (!account) return null;

  try {
    const result = await instance.acquireTokenSilent({ ...apiLoginRequest, account });
    return result.accessToken;
  } catch (error) {
    // An InteractionRequiredAuthError is the definitive signal that the
    // refresh token itself is expired or revoked: no silent path can recover,
    // only an interactive sign-in. Sign the user out here rather than letting
    // them keep browsing a shell whose every API call 401s.
    if (error instanceof InteractionRequiredAuthError) {
      console.warn("getAccessToken: session expired, signing out", error);
      void forceReauthentication();
      return null;
    }
    // Any other failure (consent, transient refresh hiccup) is logged so a
    // burst of silent-acquisition failures is distinguishable in the console
    // from a genuine server-side auth outage.
    console.warn("getAccessToken: silent token acquisition failed", error);
    return null;
  }
}

/**
 * Forces MSAL to bypass its cached access token and request a fresh one from
 * Entra, still silently (no interactive prompt). A cached token issued
 * before an app-role assignment change can otherwise be served from
 * sessionStorage indefinitely, missing the `roles` claim the API requires to
 * resolve AIOps grants. Call this once after an "Entra principal has no
 * configured AIOps grants" 401 to pick up a newly-assigned role without
 * requiring the user to fully sign out.
 */
export async function refreshAccessToken(): Promise<string | null> {
  if (!isMsalConfigured) return getAccessToken();

  try {
    await ensureMsalInitialized();
  } catch (error) {
    console.warn("refreshAccessToken: MSAL initialization failed", error);
    return null;
  }

  const instance = getMsalInstance();
  const account = getActiveAccount();
  if (!account) return null;

  try {
    const result = await instance.acquireTokenSilent({
      ...apiLoginRequest,
      account,
      forceRefresh: true,
    });
    return result.accessToken;
  } catch (error) {
    console.warn("refreshAccessToken: forced token refresh failed", error);
    return null;
  }
}

/**
 * Signs the current user fully out of MSAL (clearing the cached session and
 * account) and immediately redirects back into an interactive sign-in.
 *
 * Called when the API rejects a request as unauthenticated even after a
 * forced token refresh -- e.g. the account's Entra session itself has
 * expired or been revoked, not just the cached access token. A silent
 * refresh cannot recover from that; only a fresh interactive login can, so
 * this forces one instead of leaving the user stuck behind a permanent
 * "bearer token is required" error.
 *
 * Guarded so this can happen at most once per browser session. When the 401
 * is caused by something a new sign-in cannot fix -- a server-side auth
 * misconfiguration, or a principal with no configured AIOps grants -- the
 * post-logout redirect returns to the same page, which re-issues the same
 * failing request and logs the user straight back out. That is an infinite
 * sign-in/sign-out loop with no way for the user to break out. After the
 * first attempt the error is allowed to surface instead, so the UI can show
 * an honest failure state.
 */
const REAUTH_ATTEMPTED_KEY = "aiops.reauth-attempted";

/** True when a forced re-authentication has already been tried this session. */
export function hasAttemptedReauthentication(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.sessionStorage.getItem(REAUTH_ATTEMPTED_KEY) === "1";
  } catch {
    // sessionStorage unavailable (private mode/blocked): treat re-auth as
    // already attempted so a failure can never become an unbreakable loop.
    return true;
  }
}

/** Clears the guard once a request succeeds, so a later genuine expiry can re-auth. */
export function clearReauthenticationAttempt(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(REAUTH_ATTEMPTED_KEY);
  } catch {
    // ignore
  }
}

export async function forceReauthentication(): Promise<void> {
  if (!isMsalConfigured) return;
  if (hasAttemptedReauthentication()) return;

  try {
    window.sessionStorage.setItem(REAUTH_ATTEMPTED_KEY, "1");
  } catch {
    // Cannot persist the guard, so cannot guarantee loop termination.
    return;
  }

  const instance = getMsalInstance();
  const account = getActiveAccount();
  try {
    await ensureMsalInitialized();
    await instance.logoutRedirect({
      account,
      postLogoutRedirectUri: typeof window !== "undefined" ? window.location.href : undefined,
    });
  } catch {
    // logoutRedirect navigates the page away on success; if it throws before
    // navigating, fall back to a hard reload so the app re-renders into the
    // sign-in prompt rather than staying stuck showing stale 401s.
    if (typeof window !== "undefined") window.location.reload();
  }
}

/**
 * Signs the user out at their own request, returning them to the app's
 * sign-in screen.
 *
 * Unlike {@link forceReauthentication} this is deliberate rather than a
 * recovery path, so it is not subject to the once-per-session loop guard —
 * the user asked for it, and there is no automatic retry that could loop.
 * The guard is cleared so a later genuine expiry can still self-recover, and
 * the post-logout redirect targets the app origin rather than the current
 * deep-linked page, which may not be meaningful once signed out.
 */
export async function signOut(): Promise<void> {
  if (!isMsalConfigured) return;

  clearReauthenticationAttempt();

  const instance = getMsalInstance();
  const account = getActiveAccount();
  try {
    await ensureMsalInitialized();
    await instance.logoutRedirect({
      account,
      postLogoutRedirectUri: typeof window !== "undefined" ? window.location.origin : undefined,
    });
  } catch {
    if (typeof window !== "undefined") window.location.reload();
  }
}
