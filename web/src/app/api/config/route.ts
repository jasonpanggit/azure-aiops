import { NextResponse } from "next/server";

/**
 * Runtime (not build-time) configuration for the browser bundle.
 *
 * `NEXT_PUBLIC_*` values are inlined by Next.js at `next build` time, which
 * would bind one container image to one environment: the Container App's API
 * FQDN is only known after Terraform apply, i.e. after the image is built.
 * This route reads the value from the server process environment at request
 * time so the same image runs in every environment.
 *
 * Only non-secret values belong here — this response is public.
 */
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({
    apiBaseUrl: process.env.AIOPS_API_BASE_URL ?? null,
  });
}
