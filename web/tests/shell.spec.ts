import fs from "node:fs";

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { findBannedWords } from "../src/lib/copy";

// The catalog the offline build bundles: every reviewed example kit.
const KIT_COUNT = (
  JSON.parse(fs.readFileSync(new URL("../snapshot/catalog.json", import.meta.url), "utf8")) as { kits: unknown[] }
).kits.length;

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "phone", width: 390, height: 844 },
] as const;

const ROUTES = [
  "/",
  "/help",
  "/nonprofits",
  "/library",
  "/requests/example",
  "/requests/example/result?part=1",
  "/requests/example-process/result?part=1",
  "/catalog",
  "/catalog/KIT-HOTLINE-02",
  "/contribute",
  "/tracks",
  "/fabric",
  "/about",
  "/connect",
] as const;

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.name} ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    for (const route of ROUTES) {
      test(`${route}: agent banner above the header, tile mark, no stamp strip, no banned words, no third-party requests`, async ({ page }) => {
        const offOrigin: string[] = [];
        page.on("request", (request) => {
          if (!request.url().startsWith("http://localhost:4174")) offOrigin.push(request.url());
        });

        await page.goto(route);
        const banner = page.locator("ta-agent-banner");
        await expect(banner).toHaveAttribute("data-ready", "true");
        const order = await page.evaluate(() => {
          const b = document.querySelector("ta-agent-banner");
          const h = document.querySelector("header.er-header");
          return Boolean(b && h && b.compareDocumentPosition(h) & Node.DOCUMENT_POSITION_FOLLOWING);
        });
        expect(order).toBe(true);
        await expect(page.locator("header svg.er-brand-logo")).toBeVisible();
        await expect(page.locator("footer.er-footer")).toBeVisible();
        await expect(page.getByTestId("synthetic-banner")).toHaveCount(0);

        const text = await page.locator("body").innerText();
        expect(findBannedWords(text)).toEqual([]);
        expect(text).not.toContain("<domain>");
        expect(text).not.toMatch(/SYNTHETIC DATA ONLY|Live API mode/);
        // F31-014: the ta-amps GitHub organization is gone; no rendered link (banner included) may point there.
        expect(await page.locator('a[href*="github.com/ta-amps"]').count()).toBe(0);
        // A synthetic example is said in a sentence, never stamped on as a chip or tag. Builder rules on the older
        // pages may still name the literal mark the verifier checks; the pages in the film never show it.
        const stamps = await page.$$eval("body *", (els) =>
          els.filter((e) => e.children.length === 0 && /^SYNTHETIC:?$/i.test((e.textContent ?? "").trim())).length,
        );
        expect(stamps).toBe(0);
        if (["/", "/help", "/nonprofits", "/library"].includes(route)) expect(text).not.toMatch(/\bSYNTHETIC\b/);
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
  await expect(page.locator("article.er-card")).toHaveCount(KIT_COUNT);

  await page.getByLabel("SPDX License").selectOption("CC-BY-4.0");
  await expect(page.locator("article.er-card")).toHaveCount(1);
  await expect(page.locator("article.er-card")).toContainText("KIT-HOTLINE-02");

  await page.getByLabel("Domain", { exact: true }).selectOption("nonprofit_ops");
  await expect(page.locator("article.er-card")).toHaveCount(0);
  const emptyState = page.getByTestId("catalog-empty-state");
  await expect(emptyState).toContainText("No verified kits match the selected filters.");

  await emptyState.getByRole("button", { name: "Reset filters" }).click();
  await expect(page.locator("article.er-card")).toHaveCount(KIT_COUNT);
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

test("kit detail says a different volunteer reviewed it, with the real reviewer and receipt, and that you decide", async ({ page }) => {
  const kit = (
    JSON.parse(fs.readFileSync(new URL("../snapshot/catalog/KIT-HOTLINE-02.json", import.meta.url), "utf8")) as {
      reviewed_by: string;
      review_receipt: string;
    }
  );
  await page.goto("/catalog/KIT-HOTLINE-02");
  const line = page.getByTestId("kit-reviewed");
  await expect(line).toContainText(`A different volunteer reviewed this: ${kit.reviewed_by}`);
  await expect(line).toContainText(`receipt ${kit.review_receipt.slice(0, 4)}`);
  await expect(line).toContainText("You decide whether to use it.");
  await expect(page.getByTestId("kit-tested-on")).toHaveText("Tested on synthetic sample files (no real case data).");
  // No SYNTHETIC chip or tag; each made-up case keeps its own SYNTHETIC mark in its text (AGENTS.md rule 1).
  expect(await page.locator(".er-chip", { hasText: /SYNTHETIC/ }).count()).toBe(0);
  expect(await page.locator('a[href*="github.com/ta-amps"]').count()).toBe(0);
});

test("missing kit renders an accessible role=alert banner, without a Retry that cannot help", async ({ page }) => {
  await page.goto("/catalog/KIT-MISSING-99");
  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible();
  await expect(alert.getByRole("button", { name: "Retry" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Back to catalog" })).toBeVisible();
});
