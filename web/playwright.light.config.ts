import fs from "node:fs";

import { chromium, defineConfig, devices } from "@playwright/test";

// make light-check: builds the site into dist-light (never touching dist, which the release guard checks), serves
// it, and runs tests/light.spec.ts under both colour schemes.
const useSystemChrome = !fs.existsSync(chromium.executablePath()) && fs.existsSync("/usr/bin/google-chrome");

export default defineConfig({
  testDir: "tests",
  testMatch: /light\.spec\.ts/,
  outputDir: "test-results-light",
  reporter: [["list"]],
  use: { baseURL: "http://localhost:4176", ...devices["Desktop Chrome"], ...(useSystemChrome ? { channel: "chrome" } : {}) },
  webServer: {
    command: "VITE_SNAPSHOT=1 pnpm exec vite build --outDir dist-light --emptyOutDir && pnpm exec vite preview --outDir dist-light --port 4176 --strictPort",
    url: "http://localhost:4176",
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
