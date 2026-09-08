import { lstatSync } from "node:fs";
import { resolve } from "node:path";

import { defineConfig, devices } from "@playwright/test";

const WEB_URL_ENV = "AIOPS_ONTOLOGY_WEB_URL";
const STORAGE_STATE_ENV = "AIOPS_ONTOLOGY_PLAYWRIGHT_STORAGE_STATE";

function requiredEnvironmentValue(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required for the deployed ontology browser audit.`);
  }
  return value;
}

function deployedWebOrigin(): string {
  const rawUrl = requiredEnvironmentValue(WEB_URL_ENV);
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new Error(`${WEB_URL_ENV} must be an absolute deployed HTTPS URL.`);
  }

  const hostname = url.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  const isLocal =
    hostname === "localhost" ||
    hostname.endsWith(".localhost") ||
    hostname === "localhost.localdomain" ||
    hostname === "::1" ||
    hostname === "0.0.0.0" ||
    hostname.startsWith("127.");

  if (url.protocol !== "https:" || isLocal) {
    throw new Error(`${WEB_URL_ENV} must use HTTPS and must not target a local server.`);
  }
  if (url.username || url.password) {
    throw new Error(`${WEB_URL_ENV} must not contain embedded credentials.`);
  }

  return url.origin;
}

function secureStorageStatePath(): string {
  const storageState = resolve(requiredEnvironmentValue(STORAGE_STATE_ENV));
  const file = lstatSync(storageState);
  if (!file.isFile() || file.isSymbolicLink()) {
    throw new Error(`${STORAGE_STATE_ENV} must reference a regular file.`);
  }
  if ((file.mode & 0o777) !== 0o600) {
    throw new Error(`${STORAGE_STATE_ENV} must have mode 0600.`);
  }
  return storageState;
}

export default defineConfig({
  testDir: "./e2e",
  testMatch: "ontology-automation-live.spec.ts",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 120_000,
  expect: {
    timeout: 30_000,
  },
  reporter: "list",
  use: {
    baseURL: deployedWebOrigin(),
    storageState: secureStorageStatePath(),
    trace: "off",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
