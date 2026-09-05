import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
    css: true,
    // Playwright E2E specs (web/e2e/**) use their own test()/expect() API
    // and must never be collected by Vitest -- exclude them explicitly
    // alongside Vitest's own default excludes.
    exclude: ["**/node_modules/**", "**/dist/**", "e2e/**"],
    server: {
      deps: {
        inline: [/@fluentui\//],
      },
    },
  },
});
