import fs from "node:fs";
import { expect, test } from "@playwright/test";

declare global {
  interface Window { cspViolations: string[] }
}

// Exercise the production bundle under the exact CSP emitted by the Worker.
const workerSource = fs.readFileSync(
  new URL("../../deploy/cloudflare/worker.js", import.meta.url),
  "utf8",
);
const policySource = workerSource.match(
  /const CONTENT_SECURITY_POLICY = \[([\s\S]*?)\]\.join/,
);
if (!policySource) throw new Error("Worker CSP declaration not found");
const policy = (
  JSON.parse(`[${policySource[1]!.replace(/,\s*$/, "")}]`) as string[]
).join("; ");
const routes = ["/", "/catalog", "/tracks", "/catalog/KIT-RECRUIT-01"];

for (const width of [1440, 390]) {
  test(`strict CSP loads external theme at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript(() => {
      const state = window;
      state.cspViolations = [];
      document.addEventListener("securitypolicyviolation", (event) => {
        state.cspViolations.push(
          `${event.effectiveDirective}: ${event.blockedURI}`,
        );
      });
    });
    await page.route("http://localhost:4174/**", async (route) => {
      const response = await route.fetch();
      await route.fulfill({
        response,
        headers: { ...response.headers(), "content-security-policy": policy },
      });
    });
    for (const path of routes) {
      await page.goto(path);
      await expect(
        page.locator('#root > [data-astryx-theme="neutral"]'),
      ).toBeAttached();
      await expect(page.locator("main")).toBeVisible();
      const check = await page.evaluate(() => {
        const theme = document.querySelector('#root > [data-astryx-theme="neutral"]')!;
        return {
          violations: window.cspViolations,
          themeToken: getComputedStyle(theme)
            .getPropertyValue("--font-size-base")
            .trim(),
          injectedStyles: document.querySelectorAll(
            "style[data-astryx-theme], style[data-astryx-theme-prose]",
          ).length,
          overflow: document.documentElement.scrollWidth > window.innerWidth,
        };
      });
      expect(check.violations, path).toEqual([]);
      expect(check.injectedStyles, path).toBe(0);
      expect(check.themeToken, path).not.toBe("");
      expect(check.overflow, path).toBe(false);
    }
  });
}
