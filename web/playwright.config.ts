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
  webServer: {
    command: "pnpm snapshot:build && pnpm preview --strictPort",
    url: "http://localhost:4174",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
