import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { hits, loadChecks, pageText, plantable } from "./support/word-gate";

// The release guard's smoke test against live data (Nov 2, after the b3e42273 rollback): this build's pages, with
// their own page text, render home, /library, /requests/example and /help without a page error when every other
// /api read is answered by the live site. Read-only GETs; nothing is written.
//
// It is also the deploy's word gate (MUST-FOLLOW rules 15 and 16): the four pages' text, with live records shown the
// way the pages show them, must pass the ONE shared word list (support/word-gate.ts). The gate fails closed: no
// patterns is an error, and a planted listed word must fail it (the negative control below).
const LIVE = process.env.ERANOS_LIVE_SMOKE_ORIGIN ?? "https://eranosforgood.org";

test("the word gate has the list's patterns and catches a planted listed word (negative control)", async ({ page }) => {
  const { checks } = await loadChecks({ allowFixture: process.env.CI === "true" });
  expect(checks.length).toBeGreaterThan(0);
  const word = plantable(checks);
  await page.setContent(`<main><h1>Gate check</h1><p>A ${word} sample line.</p></main>`);
  expect(hits(checks, await pageText(page))).not.toEqual([]);
  await page.setContent("<main><h1>Gate check</h1><p>A plain sample line.</p></main>");
  expect(hits(checks, await pageText(page))).toEqual([]);
});

for (const route of ["/", "/library", "/requests/example", "/help", "/video"]) {
  test(`${route} renders with live data, no page error and no listed word`, async ({ page }) => {
    const { checks } = await loadChecks({ allowFixture: process.env.CI === "true" });
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.route("**/api/**", async (r) => {
      const url = new URL(r.request().url());
      if (r.request().method() !== "GET") return r.abort();
      // Page text ships with this build: the Worker serves it from the deploy's export (web/dist/snapshot) first.
      if (url.pathname.startsWith("/api/nouns/eranos.instructions/")) {
        const key = decodeURIComponent(url.pathname.split("/").pop() ?? "");
        const file = new URL(`../dist/snapshot/nouns/eranos.instructions/${key}.json`, import.meta.url);
        return fs.existsSync(file)
          ? r.fulfill({ status: 200, contentType: "application/json", body: fs.readFileSync(file, "utf8") })
          : r.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"no such page text"}' });
      }
      // A page's read asks for the page view (x-eranos-view), so live records arrive in the site's plain words.
      const view = r.request().headers()["x-eranos-view"];
      const response = await fetch(`${LIVE}${url.pathname}${url.search}`, {
        headers: { accept: "application/json", ...(view ? { "x-eranos-view": view } : {}) },
      });
      await r.fulfill({ status: response.status, contentType: response.headers.get("content-type") ?? "application/json", body: await response.text() });
    });
    await page.goto(route);
    await expect(page.locator("main h1").first()).toBeVisible();
    await page.waitForTimeout(1500);
    expect(errors).toEqual([]);
    expect(hits(checks, await pageText(page)), "listed words on the page (group and number only)").toEqual([]);
  });
}
