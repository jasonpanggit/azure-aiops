import { NextResponse } from "next/server";

/**
 * Serves the local-development bearer token to the browser without requiring
 * a NEXT_PUBLIC_-prefixed env var. HERMES_DEV_TOKEN stays server-only; this
 * route handler runs on the server and can read it, then hands it to
 * getAccessToken() (see src/lib/auth.ts) over a same-origin fetch.
 *
 * Only ever used when NEXT_PUBLIC_ENTRA_CLIENT_ID is unset (local dev without
 * an Entra app registration). Never enable this path in production.
 *
 * Must stay dynamic: with no dynamic APIs used, Next.js would otherwise
 * prerender this route at build time (baking in whatever HERMES_DEV_TOKEN was
 * set during the Docker build, typically unset) instead of reading the
 * env var from the running container at request time.
 */
export const dynamic = "force-dynamic";

export async function GET() {
  if (process.env.NODE_ENV === "production") {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }
  return NextResponse.json({ token: process.env.HERMES_DEV_TOKEN ?? null });
}
