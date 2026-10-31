import fs from "node:fs";

import { chromium, defineConfig, devices } from "@playwright/test";

const useSystemChrome =
  !fs.existsSync(chromium.executablePath()) && fs.existsSync("/usr/bin/google-chrome");

export default defineConfig({
  testDir: "tests",
  outputDir: "test-results",
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:4174",
    screenshot: "on",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        ...(useSystemChrome ? { channel: "chrome" } : {}),
      },
    },
  ],
  webServer: [
    {
      // The offline snapshot build: every page reads the nouns bundled with it and sends nothing.
      command: "pnpm snapshot:build && pnpm preview --strictPort",
      url: "http://localhost:4174",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      // The hosted build, for the request flow: tests answer its /api and Tessera calls themselves.
      command: "pnpm build:live-test && pnpm preview:live-test",
      url: "http://localhost:4175",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
