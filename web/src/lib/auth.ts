import { type Configuration, LogLevel, PublicClientApplication } from "@azure/msal-browser";

/**
 * MSAL configuration for the Azure AI Operations Workbench.
 *
 * All three values are required for real sign-in and must be supplied via
 * environment variables at build/deploy time. In local development without
 * an Entra app registration, `getAccessToken()` degrades to a static dev
 * token fetched from the `/api/dev-token` route handler, which reads the
 * server-only `HERMES_DEV_TOKEN` env var (matching the API's
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

export function getMsalInstance(): PublicClientApplication {
  if (!msalInstance) {
    msalInstance = new PublicClientApplication(msalConfig);
  }
  return msalInstance;
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

  const instance = getMsalInstance();
  const account = instance.getActiveAccount() ?? instance.getAllAccounts()[0];
  if (!account) return null;

  try {
    const result = await instance.acquireTokenSilent({ ...apiLoginRequest, account });
    return result.accessToken;
  } catch {
    // Silent acquisition failed (e.g. consent or interaction required).
    // The caller-facing AuthProvider surfaces sign-in; API calls will 401
    // until the user completes an interactive login.
    return null;
  }
}
