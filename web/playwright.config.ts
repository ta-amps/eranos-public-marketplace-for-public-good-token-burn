import fs from "node:fs";

import { chromium, defineConfig, devices } from "@playwright/test";

const useSystemChrome =
  !fs.existsSync(chromium.executablePath()) && fs.existsSync("/usr/bin/google-chrome");

const snapshotPort = Number(process.env.ERANOS_TEST_PORT ?? 4174);
const livePort = snapshotPort + 1;

export default defineConfig({
  testDir: "tests",
  outputDir: "test-results",
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${snapshotPort}`,
    screenshot: "on",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      // light.spec.ts runs in make light-check (playwright.light.config.ts), against the folder wrangler uploads.
      testIgnore: /perf\.spec\.ts|light\.spec\.ts|live-smoke\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        ...(useSystemChrome ? { channel: "chrome" } : {}),
      },
    },
    {
      // Timing tests run after the rest, one at a time.
      name: "perf",
      testMatch: /perf\.spec\.ts/,
      dependencies: ["chromium"],
      fullyParallel: false,
      use: {
        ...devices["Desktop Chrome"],
        ...(useSystemChrome ? { channel: "chrome" } : {}),
      },
    },
  ],
  webServer: [
    {
      // The offline snapshot build: every page reads the nouns bundled with it and sends nothing.
      command: `pnpm snapshot:build && pnpm exec vite preview --outDir dist-snapshot --port ${snapshotPort} --strictPort`,
      url: `http://localhost:${snapshotPort}`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      // The hosted build, for the request flow: tests answer its /api and Tessera calls themselves.
      command: `pnpm build:live-test && pnpm exec vite preview --outDir dist-live --port ${livePort} --strictPort`,
      url: `http://localhost:${livePort}`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
