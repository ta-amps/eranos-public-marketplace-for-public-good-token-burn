import fs from "node:fs";

import { chromium, defineConfig, devices } from "@playwright/test";

// make live-smoke: serves the folder wrangler uploads (web/dist) and runs tests/live-smoke.spec.ts, answering page
// text from the build's own export and every other /api read from the live site.
const useSystemChrome = !fs.existsSync(chromium.executablePath()) && fs.existsSync("/usr/bin/google-chrome");

export default defineConfig({
  testDir: "tests",
  testMatch: /live-smoke\.spec\.ts/,
  outputDir: "test-results-smoke",
  reporter: [["list"]],
  use: { baseURL: "http://localhost:4177", ...devices["Desktop Chrome"], ...(useSystemChrome ? { channel: "chrome" } : {}) },
  webServer: {
    command: "pnpm exec vite preview --outDir dist --port 4177 --strictPort",
    url: "http://localhost:4177",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
