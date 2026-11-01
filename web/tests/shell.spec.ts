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
  "/privacy",
  "/terms",
  "/report",
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
        await expect(page.locator("main h1").first()).toBeVisible();
        await expect(page.getByTestId("synthetic-banner")).toHaveCount(0);

        const text = await page.locator("body").innerText();
        expect(findBannedWords(text)).toEqual([]);
        expect(text).not.toContain("<domain>");
        expect(text).not.toMatch(/SYNTHETIC DATA ONLY|Live API mode/);
        // Only /report links to the live public issue tracker and private security advisories; every other page keeps zero GitHub links.
        if (route === "/report") {
          const ghLinks = await page.$$eval('a[href*="github.com/ta-amps"]', (as) => as.map((a) => a.getAttribute("href") ?? ""));
          expect(ghLinks.length).toBeGreaterThan(0);
          for (const href of ghLinks) {
            expect(href).toMatch(
              /^https:\/\/github\.com\/ta-amps\/eranos-public-marketplace-for-public-good-token-burn\/(issues|security\/advisories)$/,
            );
          }
        } else {
          expect(await page.locator('a[href*="github.com/ta-amps"]').count()).toBe(0);
        }
        // Owner, Oct 31: "DO NOT INCLUDE SYNTHETIC." (the sweep below also covers kits and examples).
        expect(text).not.toMatch(/synthetic/i);
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
  // People-readable facts only: a "Record" link, never the receipt's hash.
  await expect(line).toContainText("Record");
  await expect(line).not.toContainText(kit.review_receipt.slice(0, 12));
  await expect(line).toContainText("You decide whether to use it.");
  await expect(page.getByTestId("kit-tested-on")).toHaveText("Tested with example files (no real case data).");
  // Each practice case carries its mark (AGENTS.md rule 1); no chip or tag.
  await expect(page.locator(".er-fixture-divider").first()).toContainText("Practice case: an example, not a real person or case.");
  expect(await page.locator('a[href*="github.com/ta-amps"]').count()).toBe(0);
});

test("missing kit renders an accessible role=alert banner, without a Retry that cannot help", async ({ page }) => {
  await page.goto("/catalog/KIT-MISSING-99");
  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible();
  await expect(alert.getByRole("button", { name: "Retry" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Back to catalog" })).toBeVisible();
});

// Owner, October 31: "DO NOT INCLUDE SYNTHETIC." No page, in either view, says it anywhere a visitor can read,
// the agent banner included.
// Owner's rules for Nov 1: no "synthetic", no Llama, no receipts or hashes, Tasks and Task Objects (never nouns or
// verbs), claim · do · report (never "prove"), no retired names, never "cloud" for a dedicated worker, no stamps.
const FORBIDDEN = [
  /synthetic/i,
  /\b(o)?llama\b/i,
  /receipt/i,
  /sha-?256/i,
  /\b[0-9a-f]{12,}\b/i,
  /\bnouns?\b/i,
  /\bverbs?\b/i,
  /\bprove/i,
  /kothar|kinema|shamash/i,
  /dedicated[^.]{0,60}\bcloud\b|\bcloud\b[^.]{0,60}dedicated/i,
  /\bnot yet\b|\bPLANNED\b|layout preview|coming soon|not ready yet/i,
];

test("no page says synthetic, in any case, anywhere a visitor can read", async ({ page }) => {
  test.setTimeout(180_000);
  const kits = fs
    .readdirSync(new URL("../snapshot/catalog/", import.meta.url))
    .filter((name) => name.startsWith("KIT-"))
    .map((name) => `/catalog/${name.replace(/\.json$/, "")}`);
  const routes = [
    ...ROUTES,
    "/?tour=judge",
    "/nonprofits?tour=judge",
    "/requests/REQ-INTAKE-07?tour=judge",
    "/requests/REQ-INTAKE-07?tour=judge#step-ready",
    "/requests",
    "/requests/example?moment=decided",
    "/requests/example?moment=decided&view=technical",
    "/requests/example-process?moment=decided",
    "/requests/example-process?moment=decided&view=technical",
    "/requests/REQ-INTAKE-07",
    "/requests/example/result?part=1",
    "/requests/example-process/result?part=1",
    ...kits,
  ];
  const said: string[] = [];
  for (const route of routes) {
    await page.goto(route);
    await expect(page.locator("ta-agent-banner")).toHaveAttribute("data-ready", "true");
    await expect(page.locator("main h1").first()).toBeVisible();
    const text = await page.evaluate(() => {
      const banner = document.querySelector("ta-agent-banner")?.shadowRoot?.textContent ?? "";
      // API paths in code examples (/api/nouns/..., /v1/verbs) are addresses, not words.
      const clone = document.body.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("code, pre, kbd, [data-testid='brief-text']").forEach((node) => node.remove());
      document.body.append(clone);
      clone.style.position = "absolute";
      const visible = clone.innerText;
      clone.remove();
      return `${document.title}\n${banner}\n${visible}`;
    });
    const strict = !/^\/(catalog|tracks|contribute|fabric|about|connect)\b/.test(route);
    for (const rule of strict ? FORBIDDEN : FORBIDDEN.filter((r) => /synthetic|llama|kothar|cloud/.test(r.source))) {
      const found = rule.exec(text);
      if (found) said.push(`${route}: ${found[0]}`);
    }
  }
  expect(said).toEqual([]);
});

test("light only: with the dark scheme emulated, every page stays on paper", async ({ browser }) => {
  const context = await browser.newContext({ colorScheme: "dark" });
  const page = await context.newPage();
  for (const route of ["/", "/nonprofits", "/help", "/requests", "/requests/example", "/library"]) {
    await page.goto(route);
    await expect(page.locator("main")).toBeVisible();
    const look = await page.evaluate(() => ({
      body: getComputedStyle(document.body).backgroundColor,
      scheme: getComputedStyle(document.documentElement).colorScheme,
      meta: document.querySelector('meta[name="color-scheme"]')?.getAttribute("content"),
      banner: getComputedStyle(document.querySelector("ta-agent-banner")!).backgroundColor,
    }));
    expect(look.body, route).toBe("rgb(245, 242, 234)");
    expect(look.scheme, route).toBe("light");
    expect(look.meta, route).toBe("light");
    expect(look.banner, route).toBe("rgb(237, 232, 220)");
  }
  await context.close();
});

test("the calm request page: a sticky request track with one token, the bands' anchors and a polite live region", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/requests/example?moment=your-turn");
  const track = page.getByRole("navigation", { name: "Where your request is" });
  await expect(track).toBeVisible();
  await expect(track.locator("li")).toHaveCount(6);
  await expect(track.locator('[aria-current="step"]')).toHaveCount(1);
  await expect(track.locator('[aria-current="step"]')).toContainText("Ready for you");
  await expect(page.getByTestId("track-token")).toHaveAttribute("data-pos", "4");
  for (const id of ["step-split", "step-build", "step-review", "step-ready"]) await expect(page.locator(`#${id}`)).toHaveCount(1);
  expect(await page.locator("#step-ready").evaluate((el) => getComputedStyle(el).scrollMarginTop)).not.toBe("0px");
  expect(await track.evaluate((el) => getComputedStyle(el).position)).toBe("sticky");
  await expect(page.getByTestId("track-live")).toHaveAttribute("aria-live", "polite");
});
