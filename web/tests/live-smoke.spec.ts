import fs from "node:fs";

import { expect, test } from "@playwright/test";

// The release guard's smoke test against live data (Nov 2, after the b3e42273 rollback): this build's pages, with
// their own page text, render home, /library, /requests/example and /help without a page error when every other
// /api read is answered by the live site. Read-only GETs; nothing is written.
const LIVE = process.env.ERANOS_LIVE_SMOKE_ORIGIN ?? "https://eranosforgood.org";

for (const route of ["/", "/library", "/requests/example", "/help"]) {
  test(`${route} renders with live data and no page error`, async ({ page }) => {
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
      const response = await fetch(`${LIVE}${url.pathname}${url.search}`, { headers: { accept: "application/json" } });
      await r.fulfill({ status: response.status, contentType: response.headers.get("content-type") ?? "application/json", body: await response.text() });
    });
    await page.goto(route);
    await expect(page.locator("main h1").first()).toBeVisible();
    await page.waitForTimeout(1500);
    expect(errors).toEqual([]);
  });
}
