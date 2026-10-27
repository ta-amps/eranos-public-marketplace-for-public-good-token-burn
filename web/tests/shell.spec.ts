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
        await expect(page.locator("header svg.er-brand-logo")).toBeVisible();
        await expect(page.locator("footer.er-footer")).toBeVisible();

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

test("catalog filters narrow kits, show empty state, and reset cleanly", async ({ page }) => {
  await page.goto("/catalog");
  await expect(page.locator("article.er-card")).toHaveCount(5);

  await page.getByLabel("SPDX License").selectOption("CC-BY-4.0");
  await expect(page.locator("article.er-card")).toHaveCount(1);
  await expect(page.locator("article.er-card")).toContainText("KIT-HOTLINE-02");

  // Combine with non-matching domain to trigger empty state
  await page.getByLabel("Domain", { exact: true }).selectOption("nonprofit_ops");
  await expect(page.locator("article.er-card")).toHaveCount(0);
  const emptyState = page.getByTestId("catalog-empty-state");
  await expect(emptyState).toContainText("No verified kits match the selected filters.");

  await emptyState.getByRole("button", { name: "Reset filters" }).click();
  await expect(page.locator("article.er-card")).toHaveCount(5);
});

test("kit detail runs zero-storage practice verifier with persisted: false", async ({ page }) => {
  await page.goto("/catalog/KIT-HOTLINE-02");
  await page.getByTestId("run-practice-verifier").click();

  const result = page.getByTestId("practice-verifier-result");
  await expect(result).toBeVisible();
  await expect(result).toContainText("PASSED");
  await expect(result).toContainText("persisted: false");
  await expect(result).toContainText("SPDX: CC-BY-4.0");
});

test("missing kit renders accessible role=alert banner with Retry button", async ({ page }) => {
  await page.goto("/catalog/KIT-MISSING-99");
  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible();
  const retryBtn = alert.getByRole("button", { name: "Retry" });
  await expect(retryBtn).toBeVisible();
  await retryBtn.click();
  await expect(alert).toBeVisible();
});
