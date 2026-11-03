import { expect, test } from "@playwright/test";

import { LIVE, mockSite, noun, snapshot } from "./support/mocks";
import { fill, type RightNowWords } from "../src/lib/nouns";

// Claude Design's Nov 2 items for Eranos (CLAUDE-CODE-PROMPT-NOV2 §1.1–1.3, §1.9): the "Right now" strip under the
// doors, the open Tasks on /help, the calm request page at 1280 × 613 and a page that fails to draw.

interface HomeWords {
  right_now: Record<string, string>;
}
interface HelpWords {
  tasks: Record<string, unknown>;
  map_notice: string;
}

// Counts read right at 0, 1 and 2 (Agora review, Nov 2): the strip's count wording uses "{n:one:many}" forms, the
// same as Agora's network page, and the formatter picks the word by the count, so no brace ever shows.
test("the strip's count wording reads right at 0, 1 and 2 of each count", () => {
  const words = noun<{ right_now: RightNowWords }>("home").right_now;
  const headline = (workers: number, continents: number) => fill(words.headline, { workers, continents });
  expect(headline(1, 1)).toBe("1 worker on 1 continent is picking up Tasks");
  expect(headline(2, 1)).toBe("2 workers on 1 continent are picking up Tasks");
  expect(headline(1, 2)).toBe("1 worker on 2 continents is picking up Tasks");
  expect(headline(2, 2)).toBe("2 workers on 2 continents are picking up Tasks");
  expect(headline(0, 0)).toBe("0 workers on 0 continents are picking up Tasks");
  expect(fill(words.headline_short, { workers: 0 })).toBe("0 workers are picking up Tasks");
  expect(fill(words.headline_short, { workers: 1 })).toBe("1 worker is picking up Tasks");
  expect(fill(words.headline_short, { workers: 2 })).toBe("2 workers are picking up Tasks");
  for (const n of [0, 1, 2]) expect(fill(words.sub, { nonprofit_claims: n })).toMatch(new RegExp(`^${n} for nonprofits today\\.`));
  // Every template in the strip, at every count, leaves no hole or form behind.
  const values = (n: number) => ({ workers: n, continents: n, nonprofit_claims: n, kind: "Check", model: "Muse Spark", city: "Frankfurt", continent: "Europe", ago: "now" });
  for (const [key, template] of Object.entries(words) as [string, string][]) {
    for (const n of [0, 1, 2]) expect(fill(template, values(n)), `${key} at ${n}`).not.toMatch(/[{}]/);
  }
  // The formatter: a form without a value stays visible, so a gap is never hidden.
  expect(fill("{n} {n:Task:Tasks}", { n: 1 })).toBe("1 Task");
  expect(fill("{n} {n:Task:Tasks}", { n: 0 })).toBe("0 Tasks");
  expect(fill("{n} {n:Task:Tasks}", {})).toBe("{n} {n:Task:Tasks}");
});

test.describe("on the hosted build", () => {
  test.use({ baseURL: LIVE });

  test("the Right now strip is off, never a made-up number, while Herma has no network summary", async ({ page }) => {
    const words = noun<HomeWords>("home").right_now;
    await mockSite(page);
    await page.goto("/");
    const strip = page.getByTestId("right-now-strip");
    await expect(strip).toHaveAttribute("data-state", "off");
    await expect(strip).toContainText(words.off_text ?? "");
    expect(await strip.innerText()).not.toMatch(/\d/);
    // Directly under the two doors, in the words column, never over the tiles.
    const [doors, box] = [await page.getByRole("group", { name: "Choose your side" }).boundingBox(), await strip.boundingBox()];
    if (!doors || !box) throw new Error("no layout box");
    expect(box.y).toBeGreaterThan(doors.y + doors.height);
  });

  test("live, the strip names workers, continents and the last claim's model, a volunteer's marked declared", async ({ page }) => {
    const at = new Date(Date.now() - 2 * 60_000).toISOString();
    await mockSite(page, {
      network: {
        available: true,
        recent_minutes: 10,
        totals: { workers: 12, continents: 3, claims: 40, nonprofit_claims: 9 },
        last: { at, kind_label: "Nonprofit Task", model: { name: "Muse Spark 1.3", declared: true }, via: { type: "data_centre", city: "Frankfurt", continent: "Europe" } },
      },
    });
    await page.goto("/");
    const strip = page.getByTestId("right-now-strip");
    await expect(strip).toHaveAttribute("data-state", "live");
    await expect(strip).toContainText("12 workers on 3 continents are picking up Tasks");
    await expect(strip).toContainText("9 for nonprofits today.");
    await expect(strip).toContainText("Last claim: Nonprofit Task claimed · Muse Spark 1.3 (declared) · Frankfurt region · 2 minutes ago");
    await expect(strip.getByRole("link", { name: "See the network ↗" })).toHaveAttribute("href", "https://agora.eranosforgood.org/network/");
  });

  test("a request whose reused answer does not fit stays off the public list, and others still show", async ({ page }) => {
    await mockSite(page, {});
    const record = (key: string, text: string) => ({ key, value: { text } });
    await page.route("**/api/nouns/eranos.requests", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          records: [
            record("rq-r_e685d17b84d146cfbee59bb0fb880abe-mvywfy1j", "What are the key food-safety rules for a community food pantry?"),
            record("rq-r_09efc75a7edb494684d80cfa195d3614-mvyalefo", "We need plain-language summaries of new rules."),
          ],
        }),
      }),
    );
    await page.goto("/requests");
    const list = page.getByTestId("public-requests");
    await expect(list).toContainText("We need plain-language summaries of new rules");
    await expect(list).not.toContainText("food-safety");
  });

  test("live, the strip's counts read right at 0, 1 and 2 workers, continents and nonprofit claims", async ({ page }) => {
    const at = new Date(Date.now() - 2 * 60_000).toISOString();
    const last = { at, kind_label: "Check", model: null, via: { type: "data_centre", city: "Frankfurt", continent: "Europe" } };
    const mocks: { network: Record<string, unknown> } = { network: { available: false } };
    await mockSite(page, mocks);
    const strip = page.getByTestId("right-now-strip");
    for (const [workers, continents, nonprofit, headline] of [
      [1, 1, 0, "1 worker on 1 continent is picking up Tasks"],
      [2, 1, 1, "2 workers on 1 continent are picking up Tasks"],
      [1, 2, 2, "1 worker on 2 continents is picking up Tasks"],
      [2, 2, 0, "2 workers on 2 continents are picking up Tasks"],
      [1, 0, 1, "1 worker is picking up Tasks"],
      [2, 0, 2, "2 workers are picking up Tasks"],
    ] as const) {
      mocks.network = { available: true, recent_minutes: 10, totals: { workers, continents, claims: 3, nonprofit_claims: nonprofit }, last };
      await page.goto("/");
      await expect(strip).toHaveAttribute("data-state", "live");
      await expect(strip.locator(".er-now-strip-headline")).toHaveText(headline);
      await expect(strip.locator(".er-now-strip-sub")).toContainText(`${nonprofit} for nonprofits today.`);
      expect(await strip.innerText()).not.toMatch(/[{}]/);
    }
    mocks.network = { available: true, recent_minutes: 10, totals: { workers: 0, continents: 0, claims: 0, nonprofit_claims: 0 }, last: null };
    await page.goto("/");
    await expect(strip).toHaveAttribute("data-state", "empty");
    expect(await strip.innerText()).not.toMatch(/\d|[{}]/);
    // A live claim with no known region or continent says where it can, never that the network is quiet.
    mocks.network = { available: true, recent_minutes: 10, totals: { workers: 1, continents: 0, claims: 1, nonprofit_claims: 0 }, last: { ...last, via: { type: "continent", city: null, continent: null } } };
    await page.goto("/");
    await expect(strip).toHaveAttribute("data-state", "live");
    await expect(strip).toContainText("Last claim: Check claimed · Model not declared · 2 minutes ago");
    await expect(strip).not.toContainText("Quiet on the network");
  });

  test("the strip keeps one height in every state, loading included, so the hero never moves (E01)", async ({ page }) => {
    test.setTimeout(120_000); // 15 page loads: five states at three widths
    // Review of 2396c1c: a cold load grew the hero from 545 to 618 px when the strip appeared. Now the card holds its
    // place while /api/network answers, and every state shares the live card's height at each width.
    const ago = (m: number) => new Date(Date.now() - m * 60_000).toISOString();
    const states: (Record<string, unknown> | null)[] = [
      null,
      { available: false },
      { available: true, recent_minutes: 10, totals: { workers: 0, continents: 0, claims: 0, nonprofit_claims: 0 }, last: null },
      { available: true, recent_minutes: 10, totals: { workers: 4, continents: 1, claims: 6, nonprofit_claims: 2 }, last: { at: ago(45), kind_label: "Check", model: null, via: { type: "continent", city: null, continent: "Africa" } } },
      { available: true, recent_minutes: 10, totals: { workers: 12, continents: 3, claims: 40, nonprofit_claims: 9 }, last: { at: ago(2), kind_label: "Nonprofit research Task", model: { name: "Muse Wonder 1.0", declared: true }, via: { type: "data_centre", city: "Rio de Janeiro", continent: "South America" } } },
    ];
    let current: Record<string, unknown> | null = null;
    await mockSite(page);
    await page.route(`${LIVE}/api/network`, async (route) => {
      if (current) await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(current) });
      // null: never answers, so the strip stays in its loading state
    });
    const strip = page.getByTestId("right-now-strip");
    for (const width of [1280, 1024, 390]) {
      await page.setViewportSize({ width, height: 900 });
      const seen: string[] = [];
      for (const state of states) {
        current = state;
        await page.goto("/");
        await expect(strip).toHaveAttribute("data-state", state === null ? "loading" : /^(off|empty|quiet|live)$/);
        const box = await strip.boundingBox();
        const hero = await page.getByTestId("landing").boundingBox();
        if (!box || !hero) throw new Error("no layout box");
        seen.push(`${Math.round(box.height)}/${Math.round(hero.height)}`);
      }
      expect(new Set(seen).size, `${width}px: strip/hero heights ${seen.join(", ")}`).toBe(1);
    }
  });

  test("quiet: no claim in the last 10 minutes says so, with the counts the summary gave", async ({ page }) => {
    const at = new Date(Date.now() - 45 * 60_000).toISOString();
    await mockSite(page, {
      network: { available: true, recent_minutes: 10, totals: { workers: 4, continents: 1, claims: 6, nonprofit_claims: 2 }, last: { at, kind_label: "Check", model: null, via: { type: "continent", city: null, continent: "Africa" } } },
    });
    await page.goto("/");
    const strip = page.getByTestId("right-now-strip");
    await expect(strip).toHaveAttribute("data-state", "quiet");
    await expect(strip).toContainText("Quiet on the network");
  });

  test("/help lists the shared queue's open Tasks in plain words, with the map notice", async ({ page }) => {
    const words = noun<HelpWords>("help-page");
    await mockSite(page, {
      sharedTasks: {
        available: true,
        total: 607,
        tasks: [
          { title: "NGO: Print the consent-flag question onto the field sheet", tier: "ngo_priority", created_at: new Date(Date.now() - 30 * 60_000).toISOString() },
          { title: "Compare two open food-safety checklists", tier: "public_general", created_at: null },
        ],
      },
    });
    await page.goto("/help");
    const list = page.getByTestId("shared-task-list");
    await expect(list.getByRole("heading", { level: 3 })).toHaveText(String(words.tasks.shared_title));
    await expect(list.locator("li")).toHaveCount(2);
    await expect(list.locator("li").first()).toContainText("For nonprofits");
    await expect(list).toContainText("607 open Tasks");
    await expect(page.getByTestId("map-notice")).toHaveText(words.map_notice);
  });
});

// The calm request page (owner, Nov 2: "all steps visible on one wide screen without scrolling, the open step expanded,
// finished ones collapsed"): at 1280 x 613 (scale 1.5), with no scroll, the four step headers and the open step's last
// line sit above the fold, the open step needs no scroll of its own, and folded steps are the board's 45 px rows.
test("the calm request page fits 1280 × 613 (scale 1.5) with no scroll in the making, checking, ready and library moments", async ({ browser }) => {
  test.setTimeout(60_000);
  const context = await browser.newContext({ viewport: { width: 1280, height: 613 }, deviceScaleFactor: 1.5 });
  const page = await context.newPage();
  for (const moment of ["working", "review", "your-turn", "decided", "planned"]) {
    await page.goto(`/requests/example?moment=${moment}`);
    await expect(page.getByTestId("band-toggle-4")).toBeVisible();
    await page.waitForTimeout(300);
    const fit = await page.evaluate(() => {
      const heads = [1, 2, 3, 4].map((n) => (document.querySelector(`[data-testid='band-toggle-${n}']`) as HTMLElement).getBoundingClientRect().bottom);
      const body = document.querySelector(".er-band-body:not([hidden])") as HTMLElement | null;
      const lines = body ? [...body.querySelectorAll("*")].filter((el) => el.getClientRects().length && !el.children.length && (el.textContent ?? "").trim()) : [];
      const last = lines.length ? Math.max(...lines.map((el) => el.getBoundingClientRect().bottom)) : 0;
      const folded = [...document.querySelectorAll("[data-band][data-open='false']")].map((el) => Math.round(el.getBoundingClientRect().height));
      return {
        scrollY: window.scrollY,
        heads,
        last,
        inner: body ? body.scrollHeight - body.clientHeight : 0,
        folded,
        height: window.innerHeight,
      };
    });
    expect(fit.scrollY, moment).toBe(0);
    for (const b of [...fit.heads, fit.last]) expect(b, moment).toBeLessThanOrEqual(fit.height);
    expect(fit.inner, `${moment}: the open step scrolls inside`).toBeLessThanOrEqual(0);
    for (const h of fit.folded) expect(h, `${moment}: a folded step`).toBeLessThanOrEqual(46);
  }
  await context.close();
});

test.describe("on the hosted build, a page that fails to draw", () => {
  test.use({ baseURL: LIVE });

  test("shows a readable message and a way home, never a blank page", async ({ page }) => {
    const words = noun<{ page_error: Record<string, string> }>("shell").page_error;
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await mockSite(page);
    // Page text of a very different shape (the Nov 2 rollback's case): only a title and a lead.
    await page.route(`${LIVE}/snapshot/nouns/eranos.instructions/library.json`, (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ store: "eranos.instructions", key: "library", value: { title: "Library", lead: "Older words." } }) }),
    );
    await page.goto("/library");
    const shown = page.getByTestId("page-error").or(page.getByRole("heading", { level: 1 }));
    await expect(shown.first()).toBeVisible();
    if (await page.getByTestId("page-error").isVisible()) {
      await expect(page.getByTestId("page-error")).toContainText(words.title ?? "");
      await expect(page.getByRole("link", { name: words.home })).toHaveAttribute("href", "/");
    }
    expect((await page.locator("main").innerText()).trim().length).toBeGreaterThan(10);
  });
});

test.describe("on the hosted build, every page at 390 px with live-shaped data", () => {
  test.use({ baseURL: LIVE });

  // Live data is wider than the snapshot's (Nov 2: a track listing three kits pushed /tracks 79 px sideways on a phone).
  // This loads every page at 390 px with data shaped like the live site's and fails on any sideways scroll.
  test("no page scrolls sideways", async ({ page }) => {
    test.setTimeout(120_000);
    const tracks = snapshot<{ tracks: Record<string, unknown>[] }>("tracks.json");
    const wide = {
      ...tracks,
      tracks: tracks.tracks.map((t, i) => ({ ...t, kit_ready: true, catalog_kit_ids: [`KIT-IMPACT-0${i % 9}`, "KIT-RENEWAL-10", "PRC-31C684-01"] })),
    };
    const longTitle = "NGO: Field-test the revised surge decision band for the clinic's shelter inverter logs, with a printable checklist and two practice cases";
    await mockSite(page, {
      tracks: wide,
      openTasks: [{ task_id: "t-eq02-1", queue: "eq02", kind: "build", title: longTitle, created_at: Math.floor(Date.now() / 1000) - 600, open_to_anonymous: true }],
      sharedTasks: { available: true, total: 607, tasks: [{ title: longTitle, tier: "ngo_priority", created_at: new Date().toISOString() }] },
      network: {
        available: true,
        recent_minutes: 10,
        totals: { workers: 320, continents: 6, claims: 1890, nonprofit_claims: 190 },
        last: { at: new Date().toISOString(), kind_label: "Nonprofit Task", model: { name: "Muse Spark 1.3", declared: true }, via: { type: "data_centre", city: "Johannesburg", continent: "Africa" } },
      },
    });
    await page.setViewportSize({ width: 390, height: 844 });
    const wideOnes: string[] = [];
    for (const route of ["/", "/nonprofits", "/help", "/library", "/requests", "/requests/example", "/requests/example?moment=your-turn", "/requests/example/result?part=1", "/catalog", "/catalog/KIT-HOTLINE-02", "/contribute", "/tracks", "/fabric", "/about", "/connect", "/privacy", "/terms", "/report"]) {
      await page.goto(route);
      await expect(page.locator("main h1").first()).toBeVisible();
      await page.waitForTimeout(300);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (over > 0) wideOnes.push(`${route}: ${over}px`);
    }
    expect(wideOnes).toEqual([]);
  });
});
