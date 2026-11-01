import { expect, test } from "@playwright/test";

import { LIVE, mockSite } from "./support/mocks";

// A timing test: it runs in its own project after every other test has finished, so parallel page loads on the
// same machine don't eat into the 2.5 s budget it measures.
test.describe("on the hosted build, measured alone", () => {
  test.use({ baseURL: LIVE });

  test("E01: a cold load paints the largest text within 2.5 s and shifts nothing (simulated slow 4G)", async ({ page }) => {
    await mockSite(page);
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
    await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
    await page.addInitScript(() => {
      const w = window as unknown as { lcp: number; cls: number };
      w.lcp = 0;
      w.cls = 0;
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) w.lcp = entry.startTime;
      }).observe({ type: "largest-contentful-paint", buffered: true });
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) if (!entry.hadRecentInput) w.cls += entry.value;
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto("/", { waitUntil: "load" });
    await page.waitForTimeout(1500);
    const { lcp, cls } = await page.evaluate(() => {
      const w = window as unknown as { lcp: number; cls: number };
      return { lcp: w.lcp, cls: w.cls };
    });
    console.log(`cold load: LCP ${Math.round(lcp)} ms, CLS ${cls.toFixed(3)}`);
    expect(lcp).toBeGreaterThan(0);
    expect(lcp).toBeLessThan(2500);
    expect(cls).toBeLessThan(0.1);
  });
});
