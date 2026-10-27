import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { findBannedWords } from "../src/lib/copy";

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "phone", width: 390, height: 844 },
] as const;

const ROUTES = [
  "/",
  "/catalog",
  "/catalog/KIT-HOTLINE-02",
  "/contribute",
  "/tracks",
  "/fabric",
  "/about",
] as const;

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.name} ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    for (const route of ROUTES) {
      test(`${route}: SYNTHETIC banner visible, no banned words, no third-party requests`, async ({ page }) => {
        const offOrigin: string[] = [];
        page.on("request", (request) => {
          if (!request.url().startsWith("http://localhost:4174")) offOrigin.push(request.url());
        });

        await page.goto(route);
        const banner = page.getByTestId("synthetic-banner");
        await expect(banner).toBeVisible();

        const text = await page.locator("body").innerText();
        expect(findBannedWords(text)).toEqual([]);
        expect(text).not.toContain("<domain>");
        expect(offOrigin).toEqual([]);

        const scan = await new AxeBuilder({ page }).analyze();
        const serious = scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
        expect(serious.map((v) => v.id)).toEqual([]);
      });
    }
  });
}
