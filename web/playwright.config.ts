import { defineConfig, devices } from "@playwright/test";

/**
 * Phase 03.6 Plan 06: Playwright E2E infrastructure.
 *
 * Every spec in this suite mocks its own `/api/v1/**` responses via
 * `page.route()` -- the real Python API never needs to be running for
 * `npm run test:e2e` to pass. The spawned dev server runs in dev-token
 * auth mode (leaving `NEXT_PUBLIC_ENTRA_CLIENT_ID` unset routes auth
 * through the `/api/dev-token` bearer-token path instead of real MSAL,
 * per `.env.local.example`'s documented mechanism).
 *
 * `AIOPS_DEV_TOKEN` here is a fixed local test-only value scoped to this
 * spawned dev server -- never a real credential. NEVER set
 * `NEXT_PUBLIC_ENTRA_CLIENT_ID`/a real `AIOPS_DEV_TOKEN` in a production
 * deployment.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_ENTRA_CLIENT_ID: "",
      AIOPS_DEV_TOKEN: "local-e2e-test-token-0000",
    },
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
