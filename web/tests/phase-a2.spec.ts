import fs from "node:fs";

import { expect, test, type Page } from "@playwright/test";

import { LIVE, mockSite } from "./support/mocks";

// Phase A part 2 (Nov 1, owner v2) and the fixes from the independent review of part 1 (B1 to B6).

const PRINCIPAL = `r_${"cd".repeat(16)}`;
const REQUEST_ID = `rq-${PRINCIPAL}-mvwv3xwe`;
// A fixture copy of the models.meta Task Object, in tests only; the site reads the live one from Tessera.
const MODELS = JSON.parse(fs.readFileSync(new URL("./fixtures/models.meta.json", import.meta.url), "utf8")) as unknown;
const INK = /^rgb\((1[0-9]|2[0-9]|3[0-9]), (1[0-9]|2[0-9]|3[0-9]), (2[0-9]|3[0-9]|4[0-9])\)$/;

const fact = (version: number, value: Record<string, unknown>, at = 1_790_000_000) => ({
  version,
  created_at: at + version,
  value: { schema_version: 1, request_id: REQUEST_ID, status: "open_for_build", event: { at: at + version, ...value } },
});
const PLAN = { type: "planned", receipt: "b".repeat(64), parts: [{ part: 1, route: "public-only", text: "Summarize the laws.", report_id: "RPT-RAAAAAAA-01" }] };
const TWO_PARTS = {
  type: "planned",
  receipt: "b".repeat(64),
  parts: [
    { part: 1, route: "public-only", text: "Summarize the laws.", report_id: "RPT-RAAAAAAA-01" },
    { part: 2, route: "public-only", text: "List the grants.", report_id: "RPT-RAAAAAAA-02" },
  ],
};

/** Every value the token's data-pos takes from the first paint on, recorded by a MutationObserver. */
async function recordPositions(page: Page) {
  await page.addInitScript(() => {
    const seen: string[] = [];
    Object.defineProperty(window, "positions", { value: seen });
    const note = () => {
      const pos = document.querySelector("[data-testid='track-token']")?.getAttribute("data-pos");
      if (pos !== undefined && pos !== null && seen[seen.length - 1] !== pos) seen.push(pos);
    };
    new MutationObserver(note).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ["data-pos"] });
  });
}
const positions = (page: Page) => page.evaluate(() => (window as unknown as { positions: string[] }).positions);

test.describe("B1: on load the track shows only the last hop", () => {
  for (const [moment, from, to] of [
    ["your-turn", "4", "5"],
    ["review", "3", "4"],
  ] as const) {
    test(`/requests/example?moment=${moment}: the token starts at ${from} and moves once, to ${to}`, async ({ page }) => {
      await recordPositions(page);
      await page.goto(`/requests/example?moment=${moment}`);
      await expect(page.getByTestId("track-token")).toHaveAttribute("data-pos", to);
      await page.waitForTimeout(1200);
      expect(await positions(page)).toEqual([from, to]);
    });
  }

  test.describe("live pages", () => {
    test.use({ baseURL: LIVE });
    test("a request already at its decision opens one hop back, never at the start", async ({ page }) => {
      await recordPositions(page);
      const history = [
        fact(1, { type: "received", receipt: "a".repeat(64) }),
        fact(2, PLAN),
        fact(3, { type: "work_claimed", part: 1, receipt: "c".repeat(64), worker: "volunteer-7", model: "muse-spark-1.3" }),
        fact(4, { type: "work_submitted", part: 1, receipt: "d".repeat(64) }),
        fact(5, { type: "check_claimed", part: 1, receipt: "e".repeat(64), worker: "volunteer-9" }),
        fact(6, { type: "check_approved", part: 1, receipt: "f".repeat(64) }),
      ];
      await mockSite(page, { history, request: { request_id: REQUEST_ID, status: "open_for_build", text: "Summarize the laws." } });
      await page.goto(`/requests/${REQUEST_ID}`);
      await expect(page.getByTestId("track-token")).toHaveAttribute("data-pos", "5");
      await page.waitForTimeout(1200);
      expect(await positions(page)).toEqual(["4", "5"]);
    });

    test("a sent-back request opens moving backwards, never forwards", async ({ page }) => {
      await recordPositions(page);
      const history = [
        fact(1, { type: "received", receipt: "a".repeat(64) }),
        fact(2, PLAN),
        fact(3, { type: "work_claimed", part: 1, receipt: "c".repeat(64), worker: "volunteer-7" }),
        fact(4, { type: "work_submitted", part: 1, receipt: "d".repeat(64) }),
        fact(5, { type: "check_claimed", part: 1, receipt: "e".repeat(64), worker: "volunteer-9" }),
        fact(6, { type: "check_sent_back", part: 1, receipt: "f".repeat(64), findings: ["two points had no source"] }),
      ];
      await mockSite(page, { history, request: { request_id: REQUEST_ID, status: "open_for_build", text: "Summarize the laws." } });
      await page.goto(`/requests/${REQUEST_ID}`);
      const token = page.getByTestId("track-token");
      await expect(token).toHaveAttribute("data-pos", "2");
      await expect(token).toHaveAttribute("data-back", "true");
      await page.waitForTimeout(1200);
      expect(await positions(page)).toEqual(["4", "2"]);
    });
  });
});

test.describe("B2: the token follows the request's state, the same source as aria-current", () => {
  test.use({ baseURL: LIVE });
  const open = async (page: Page, events: Record<string, unknown>[]) => {
    await mockSite(page, {
      history: events.map((value, i) => fact(i + 1, value)),
      request: { request_id: REQUEST_ID, status: "open_for_build", text: "Summarize the laws. List the grants." },
    });
    await page.goto(`/requests/${REQUEST_ID}`);
    return { token: page.getByTestId("track-token"), track: page.getByTestId("request-track") };
  };
  const made = (part: number, n: number) => [
    { type: "work_claimed", part, receipt: `${n}1`.padEnd(64, "a"), worker: "eranos-worker-pc01", dedicated: true, model: "muse-spark-1.3" },
    { type: "work_submitted", part, receipt: `${n}2`.padEnd(64, "a") },
    { type: "check_claimed", part, receipt: `${n}3`.padEnd(64, "a"), worker: "eranos-review-pc02", dedicated: true, model: "muse-spark-1.3" },
  ];
  // The live workers write check_approved, delivered and library_added together (worker_loop.py review_facts).
  const delivered = (part: number, n: number) => [
    { type: "check_approved", part, receipt: `${n}4`.padEnd(64, "a") },
    { type: "delivered", part, receipt: `${n}5`.padEnd(64, "a") },
    { type: "library_added", part, receipt: `${n}6`.padEnd(64, "a"), library_ref: "eranos.solutions/RPT-RAAAAAAA-01" },
  ];

  test("the workers' own order: delivered and in the library, then a later decision, never moves back", async ({ page }) => {
    const { token, track } = await open(page, [{ type: "received", receipt: "a".repeat(64) }, PLAN, ...made(1, 1), ...delivered(1, 1), { type: "decided", part: 1, choice: "use", receipt: "9".repeat(64) }]);
    await expect(token).toHaveAttribute("data-pos", "5");
    await expect(token).toHaveAttribute("data-tone", "done");
    await expect(token).toHaveAttribute("data-back", "false");
    await expect(track.locator('li[data-step="5"]')).toHaveAttribute("data-state", "done");
    await expect(track.locator('[aria-current="step"]')).toHaveCount(0);
  });

  test("two parts: the second part's check after the first part's library entry is the request's place, not a send-back", async ({ page }) => {
    const { token, track } = await open(page, [{ type: "received", receipt: "a".repeat(64) }, TWO_PARTS, ...made(1, 1), ...made(2, 2).slice(0, 2), ...delivered(1, 1), made(2, 2)[2] as Record<string, unknown>]);
    await expect(token).toHaveAttribute("data-pos", "4");
    await expect(token).toHaveAttribute("data-back", "false");
    await expect(track.locator('[aria-current="step"]')).toHaveCount(1);
    await expect(track.locator('[aria-current="step"]')).toContainText("Being checked");
    await expect(track.locator('li[data-state="now"]')).toHaveCount(1);
  });

  test("B5: dedicated planners, makers and checkers are named as ta-amps' own, in the plain view and the details", async ({ page }) => {
    await open(page, [
      { type: "received", receipt: "a".repeat(64) },
      { type: "plan_claimed", receipt: "1".repeat(64), worker: "eranos-plan-pc03", dedicated: true },
      PLAN,
      ...made(1, 1),
    ]);
    const happened = page.getByTestId("plain-happened");
    const more = page.getByRole("button", { name: /Show everything/ });
    if (await more.count()) await more.click();
    await expect(happened).toContainText("A dedicated worker run by ta-amps started checking it.");
    await expect(happened).toContainText("A dedicated worker run by ta-amps started planning your request.");
    await expect(page.locator('[data-band="3"]')).toContainText("A dedicated worker run by ta-amps is checking it");
    const plainText = await page.getByTestId("plain-status").innerText();
    expect(plainText).not.toMatch(/second volunteer|different volunteer/i);
    await page.getByTestId("view-switch").click();
    const details = await page.locator("main").innerText();
    expect(details).not.toMatch(/eranos-(plan|worker|review)-pc0|different volunteer|\b(Green|Orange|Blue|Amber):/i);
    expect(details).toContain("dedicated worker 2 (run by ta-amps)");
  });
});

test.describe("the model in the details comes from the models.meta Task Object", () => {
  test.use({ baseURL: LIVE });
  const events = [
    { type: "received", receipt: "a".repeat(64) },
    PLAN,
    { type: "work_claimed", part: 1, receipt: "c".repeat(64), worker: "eranos-worker-pc01", dedicated: true, model: "muse-spark-1.3" },
  ];
  for (const [label, models, name] of [
    ["with the catalog in Tessera", MODELS, "Muse Spark 1.3"],
    ["before it is written there", null, "Meta’s latest Muse model"],
  ] as const) {
    test(label, async ({ page }) => {
      await mockSite(page, { history: events.map((value, i) => fact(i + 1, value)), models, request: { request_id: REQUEST_ID, status: "open_for_build", text: "Summarize the laws." } });
      await page.goto(`/requests/${REQUEST_ID}?view=technical`);
      await expect(page.locator("main")).toContainText(`dedicated worker 1 (run by ta-amps) · model: ${name}, through the Meta API`);
      expect(await page.locator("main").innerText()).not.toContain("muse-spark-1.3");
    });
  }
});

test.describe("part 2 pages", () => {
  test("the home: the doors, the mini request track, and 'What you can ask for' on paper", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    const doors = page.getByRole("group", { name: "Choose your side" }).getByRole("link");
    await expect(doors).toHaveText([/^My NGO needs help/, /^I want to help/]);
    await expect(page.locator(".er-landing-track li")).toHaveText(["Your request", "In line", "Agent working", "Checked", "Shared library"]);
    const asks = page.locator("section.er-asks");
    expect(await asks.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(237, 232, 220)");
    for (const card of await asks.locator(".er-ask-card").all()) expect(await card.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(255, 253, 248)");
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".er-landing-track")).toBeHidden();
  });

  test("/library searches solutions, filters them, and offers 'Ask for this' when nothing fits", async ({ page }) => {
    await page.goto("/library");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Find a solution");
    await page.getByLabel("What do you need help with?").fill("volunteer shift");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    const results = page.getByTestId("solutions").locator("li");
    await expect(results.first()).toBeVisible();
    await expect(page.getByTestId("find-count")).toContainText("for “volunteer shift”");
    await expect(results.first()).toContainText("A process you run");
    expect(await page.locator("main").innerText()).not.toMatch(/receipt|sha-?256|\b[0-9a-f]{12,}\b/i);
    await page.getByRole("button", { name: "Answers", exact: true }).click();
    await expect(page.getByTestId("find-empty")).toBeVisible();
    await page.getByRole("button", { name: "Any", exact: true }).click();
    await page.getByLabel("What do you need help with?").fill("zebra giraffe telescope");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    const empty = page.getByTestId("find-empty");
    await expect(empty).toContainText("No solution for “zebra giraffe telescope” yet");
    await empty.getByRole("link", { name: "Ask for this →" }).click();
    await expect(page).toHaveURL(/\/nonprofits\?q=zebra/);
    await expect(page.locator("#need")).toHaveValue("zebra giraffe telescope");
  });

  test("'Adapt it for my group' opens the ask form as an improvement of that solution", async ({ page }) => {
    await page.goto("/library?q=volunteer%20shift");
    const first = page.getByTestId("solutions").locator("li").first();
    await first.getByRole("link", { name: /^Adapt it for my group/ }).click();
    await expect(page).toHaveURL(/\/nonprofits\?improve=/);
    await expect(page.getByTestId("advanced-settings")).toHaveAttribute("open", "");
    await expect(page.locator("#improve-link")).toHaveValue(/\/catalog\/KIT-/);
  });

  test("the build band links 'Which model does what ↗' after 'One helper at a time. Every step is recorded.'", async ({ page }) => {
    await page.goto("/requests/example?moment=review");
    const band = page.locator("#step-build");
    await expect(band).toContainText("One helper at a time. Every step is recorded.");
    await expect(band.getByRole("link", { name: "Which model does what ↗" })).toHaveAttribute("href", "https://agora.ta-amps.workers.dev/models/");
  });
});

test("B4: no hash in any title or aria attribute, and Record is a real link", async ({ page }) => {
  for (const route of ["/requests/example?moment=your-turn&view=technical", "/requests/example/result?part=1", "/catalog/KIT-HOTLINE-02"]) {
    await page.goto(route);
    await expect(page.locator("main h1").first()).toBeVisible();
    const attributes = await page.evaluate(() =>
      [...document.querySelectorAll("*")].flatMap((el) => [...el.attributes].filter((a) => a.name === "title" || a.name.startsWith("aria-")).map((a) => a.value)),
    );
    expect(attributes.filter((v) => /\b[0-9a-f]{12,}\b|receipt/i.test(v)), route).toEqual([]);
    const records = page.locator("main").getByText(/^Record ↗$/);
    for (const record of await records.all()) expect(await record.evaluate((el) => el.tagName), route).toBe("A");
  }
});

test("B6: no ink panels: no large element on the touched pages has an ink background, with either scheme", async ({ browser }) => {
  for (const colorScheme of ["light", "dark"] as const) {
    const context = await browser.newContext({ colorScheme });
    const page = await context.newPage();
    for (const route of ["/", "/nonprofits", "/help", "/library", "/requests", "/requests/example?moment=your-turn", "/requests/example/result?part=1", "/catalog/KIT-HOTLINE-02", "/privacy"]) {
      await page.goto(route);
      await expect(page.locator("main h1").first()).toBeVisible();
      const panels = await page.evaluate((ink) => {
        const pattern = new RegExp(ink);
        const out: string[] = [];
        for (const el of document.querySelectorAll("body *")) {
          // Ink is for text, primary buttons and the logo (the skip link is a button while focused).
          if (el.closest("a, button, summary, [role=button], [role=radio], input, svg, .er-skip-link")) continue;
          const box = el.getBoundingClientRect();
          if (box.width * box.height < 2000) continue;
          const bg = getComputedStyle(el).backgroundColor;
          if (pattern.test(bg)) out.push(`${el.tagName.toLowerCase()}.${(el.getAttribute("class") ?? "").split(" ")[0]} ${bg}`);
        }
        return out;
      }, INK.source);
      expect(panels, `${colorScheme} ${route}`).toEqual([]);
    }
    await context.close();
  }
});

test("no horizontal scroll at 390 px, or at 640 px (a 1280 px window at 200% zoom), on any page", async ({ page }) => {
  test.setTimeout(120_000);
  const routes = ["/", "/nonprofits", "/help", "/library", "/requests", "/requests/example?moment=your-turn", "/requests/example/result?part=1", "/catalog", "/catalog/KIT-HOTLINE-02", "/contribute", "/tracks", "/fabric", "/about", "/connect", "/privacy", "/terms", "/report"];
  const wide: string[] = [];
  for (const width of [390, 640]) {
    await page.setViewportSize({ width, height: 800 });
    for (const route of routes) {
      await page.goto(route);
      await expect(page.locator("main h1").first()).toBeVisible();
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (over > 0) wide.push(`${width} ${route}: ${over}px`);
    }
  }
  expect(wide).toEqual([]);
});

test("the header's How it works ↗ opens Agora's How it works page", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(page.locator("header").getByRole("link", { name: /How it works/ })).toHaveAttribute("href", "https://agora.ta-amps.workers.dev/how-it-works/");
});
