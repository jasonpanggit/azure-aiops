import { getAccessToken, refreshAccessToken } from "./auth";
import { ApiError, type ApiErrorBody, type Envelope } from "./types";

/**
 * Base URL of the deployed Operations API, e.g. `https://hermes-api.example.com`.
 * The API itself is mounted at `/api/v1` (see docs/OPERATIONS_API.md).
 *
 * Keeps the NEXT_PUBLIC_ prefix intentionally: this file runs in the browser
 * (every apiRequest() call is a client-side fetch), so the value must be
 * inlined into the public bundle to be readable at all. Unlike the bearer
 * token, a base URL isn't a secret — it's already visible to anyone via the
 * browser's network tab — so there's no confidentiality to protect by
 * routing it through a server-side handler like /api/dev-token.
 */
const CONFIGURED_API_BASE_URL = process.env.NEXT_PUBLIC_HERMES_API_BASE_URL;
const API_BASE_URL = CONFIGURED_API_BASE_URL ?? "http://127.0.0.1:8080";
const API_PREFIX = "/api/v1";

/**
 * Resolves the API base URL, preferring runtime configuration over the
 * build-time constant.
 *
 * In a container deployment the API's FQDN is only known after the
 * infrastructure is applied, which is strictly after the image is built — so
 * a `NEXT_PUBLIC_` value baked in at `next build` time cannot be correct.
 * `/api/config` reads `HERMES_API_BASE_URL` from the running server process,
 * letting one image serve every environment. The result is memoized because
 * it cannot change within the lifetime of a page, and falls back to the
 * build-time constant so local development is unaffected.
 */
let runtimeBaseUrl: Promise<string> | null = null;

function fallbackApiBaseUrl(): string {
  if (process.env.NODE_ENV === "production" && !CONFIGURED_API_BASE_URL) {
    throw new Error("HERMES_API_BASE_URL is not configured for this production deployment");
  }
  return API_BASE_URL;
}

export function resolveApiBaseUrl(): Promise<string> {
  if (typeof window === "undefined") {
    return Promise.resolve(process.env.HERMES_API_BASE_URL ?? API_BASE_URL);
  }
  runtimeBaseUrl ??= fetch("/api/config")
    .then((response) => (response.ok ? response.json() : null))
    .then((config: { apiBaseUrl?: string | null } | null) => config?.apiBaseUrl || fallbackApiBaseUrl())
    .catch(() => fallbackApiBaseUrl());
  return runtimeBaseUrl;
}

function generateCorrelationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `corr-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  query?: URLSearchParams | Record<string, string | string[] | undefined>;
  body?: unknown;
  /** Skip attaching an Authorization header, e.g. for /health. */
  anonymous?: boolean;
  /** Bypass the /api/v1 prefix. Only /health lives outside it. */
  rawPath?: boolean;
  signal?: AbortSignal;
}

function buildQuery(query: RequestOptions["query"]): string {
  if (!query) return "";
  const params = query instanceof URLSearchParams ? query : new URLSearchParams();
  if (!(query instanceof URLSearchParams)) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined) continue;
      if (Array.isArray(value)) {
        for (const v of value) params.append(key, v);
      } else {
        params.append(key, value);
      }
    }
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

/**
 * Thin, typed wrapper around fetch that speaks the Operations API envelope
 * and error contract. Every call attaches a bearer token (unless anonymous)
 * and an `X-Correlation-ID`, and unwraps `{ error: {...} }` bodies into a
 * thrown `ApiError` so callers only handle the success shape.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<Envelope<T>> {
  const correlationId = generateCorrelationId();

  const prefix = options.rawPath ? "" : API_PREFIX;
  const baseUrl = await resolveApiBaseUrl();
  const url = `${baseUrl}${prefix}${path}${buildQuery(options.query)}`;

  const doFetch = async (token: string | null): Promise<Response> => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "X-Correlation-ID": correlationId,
    };
    if (token) headers.Authorization = `Bearer ${token}`;
    return fetch(url, {
      method: options.method ?? "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  };

  let token: string | null = null;
  if (!options.anonymous) {
    token = await getAccessToken();
  }

  let response: Response;
  try {
    response = await doFetch(token);
  } catch (cause) {
    throw new ApiError(0, "unknown", "Network request failed", { cause: String(cause) }, correlationId);
  }

  // A cached MSAL access token predating an Entra app-role assignment can be
  // silently reused by acquireTokenSilent and still pass signature/expiry
  // checks while carrying no `roles` claim. Retry once with a forced token
  // refresh before surfacing the failure, so a role granted moments ago
  // takes effect without requiring the user to fully sign out.
  if (!options.anonymous && response.status === 401) {
    let code: string | undefined;
    try {
      const cloned = response.clone();
      const body = (await cloned.json()) as ApiErrorBody;
      code = body?.error?.code;
    } catch {
      // ignore
    }
    if (code === "unauthenticated") {
      const freshToken = await refreshAccessToken();
      if (freshToken && freshToken !== token) {
        try {
          response = await doFetch(freshToken);
        } catch (cause) {
          throw new ApiError(0, "unknown", "Network request failed", { cause: String(cause) }, correlationId);
        }
      }
    }
  }

  const responseCorrelationId = response.headers.get("X-Correlation-ID") ?? correlationId;

  if (!response.ok) {
    let parsed: ApiErrorBody | undefined;
    try {
      parsed = (await response.json()) as ApiErrorBody;
    } catch {
      // Non-JSON error body (e.g. a gateway 502 HTML page).
    }
    if (parsed?.error) {
      throw new ApiError(
        response.status,
        parsed.error.code,
        parsed.error.message,
        parsed.error.details,
        responseCorrelationId
      );
    }
    throw new ApiError(response.status, "unknown", response.statusText || "Request failed", undefined, responseCorrelationId);
  }

  if (response.status === 204) {
    return { data: undefined as T, evidence: [], scope: {} };
  }

  return (await response.json()) as Envelope<T>;
}

export { API_BASE_URL };
