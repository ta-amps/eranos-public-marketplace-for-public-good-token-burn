import fs from "node:fs";

import { expect, test } from "@playwright/test";

// The release guard's smoke test against live data (Nov 2, after the b3e42273 rollback): this build's pages, with
// their own page text, render home, /library, /requests/example and /help without a page error when every other
// /api read is answered by the live site. Read-only GETs; nothing is written.
//
// It is also the deploy's word gate (MUST-FOLLOW rules 15 and 16): every page's text, with live records shown the way
// the pages show them, must pass the ONE shared word list. The list is read from outside this repository through the
// gitignored module that scripts/banned_list.mjs writes in the same build step; a hit is reported by its group and
// number only, never the word.
const LIVE = process.env.ERANOS_LIVE_SMOKE_ORIGIN ?? "https://eranosforgood.org";
const GENERATED = new URL("../../deploy/cloudflare/banned_words.generated.js", import.meta.url);

interface Check {
  group: string;
  re: string;
  flags: string;
}

async function wordChecks(): Promise<Check[]> {
  if (!fs.existsSync(GENERATED)) throw new Error("the word list module is missing: run node scripts/banned_list.mjs");
  const loaded = (await import(GENERATED.href)) as { default: { checks?: Check[]; source?: string } };
  if (process.env.CI !== "true" && loaded.default.source === "fixture") throw new Error("the word list module was built from the test fixtures");
  return loaded.default.checks ?? [];
}

for (const route of ["/", "/library", "/requests/example", "/help"]) {
  test(`${route} renders with live data, no page error and no listed word`, async ({ page }) => {
    const checks = await wordChecks();
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

    const text = await page.evaluate(() => {
      const prose: string[] = [];
      const all: string[] = [];
      const visible = (el: Element) => {
        const cs = getComputedStyle(el);
        return cs.display !== "none" && cs.visibility !== "hidden" && el.getClientRects().length > 0;
      };
      const walk = (root: Node) => {
        const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        for (let n = tw.nextNode(); n; n = tw.nextNode()) {
          const parent = n.parentElement;
          if (!parent || parent.closest("script, style, noscript, template")) continue;
          all.push(n.nodeValue ?? "");
          if (!parent.closest("code, pre, kbd, samp, tt, var") && visible(parent)) prose.push(n.nodeValue ?? "");
        }
        for (const el of (root as ParentNode).querySelectorAll("*")) if (el.shadowRoot) walk(el.shadowRoot);
      };
      walk(document.body);
      for (const el of document.querySelectorAll("[alt], [title], [aria-label], [placeholder]")) {
        for (const name of ["alt", "title", "aria-label", "placeholder"]) all.push(el.getAttribute(name) ?? "");
      }
      return { prose: prose.join(" \n"), all: all.join(" \n") };
    });
    const hits = checks
      .map((check, index) => ({ check, index }))
      .filter(({ check }) => new RegExp(check.re, check.flags.includes("m") ? check.flags : `${check.flags}m`).test(check.group === "always" ? text.all : text.prose))
      .map(({ check, index }) => `${check.group} #${index}`);
    expect(hits, "listed words on the page (group and number only)").toEqual([]);
  });
}
