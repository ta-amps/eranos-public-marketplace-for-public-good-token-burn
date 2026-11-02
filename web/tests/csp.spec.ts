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
const routes = [
  "/",
  "/help",
  "/nonprofits",
  "/library",
  "/requests/example",
  "/requests/example/result?part=1",
  "/requests/example-process/result?part=1",
  "/catalog",
  "/tracks",
  "/catalog/KIT-RECRUIT-01",
  "/privacy",
  "/terms",
  "/report",
  "/video",
  "/?tour=judge",
  "/requests/REQ-INTAKE-07?tour=judge#step-ready",
];

for (const width of [1440, 390]) {
  test(`strict CSP loads the Paper & Ink tokens, fonts and the agent banner at ${width}px`, async ({ page }) => {
    // Ten full page loads through a re-headering proxy; under a parallel run that takes longer than one page's budget.
    test.setTimeout(90_000);
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
    await page.route(`http://localhost:${Number(process.env.ERANOS_TEST_PORT ?? 4174)}/**`, async (route) => {
      const response = await route.fetch();
      await route.fulfill({
        response,
        headers: { ...response.headers(), "content-security-policy": policy },
      });
    });
    for (const path of routes) {
      await page.goto(path);
      await expect(page.locator("main")).toBeVisible();
      await expect(page.locator("ta-agent-banner")).toHaveAttribute("data-ready", "true");
      await page.evaluate(() => document.fonts.ready);
      const check = await page.evaluate(() => ({
        violations: window.cspViolations,
        paper: getComputedStyle(document.documentElement).getPropertyValue("--bg").trim(),
        font: getComputedStyle(document.body).fontFamily,
        plexLoaded: document.fonts.check('16px "IBM Plex Sans"'),
        inlineStyles: document.querySelectorAll("style").length,
        bannerStyled: getComputedStyle(document.querySelector("ta-agent-banner")!.shadowRoot!.querySelector(".bar")!).display,
        overflow: document.documentElement.scrollWidth > window.innerWidth,
      }));
      expect(check.violations, path).toEqual([]);
      expect(check.paper, path).not.toBe("");
      expect(check.font, path).toContain("IBM Plex Sans");
      expect(check.plexLoaded, path).toBe(true);
      expect(check.inlineStyles, path).toBe(0);
      expect(check.bannerStyled, path).toBe("flex");
      expect(check.overflow, path).toBe(false);
    }
  });
}
