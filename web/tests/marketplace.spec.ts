import { expect, test, type Page } from "@playwright/test";

import type { NonprofitsPageNoun } from "../src/lib/nouns";
import { LIVE, mockSite, noun } from "./support/mocks";


/** Every hero text box a tile (or its lit layer) intersects, as "tile class x text class". Empty when none. */
function heroCrossings(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const boxes = (selector: string) => [...document.querySelectorAll(selector)].map((el) => ({ el, r: el.getBoundingClientRect() }));
    const text = boxes(".er-landing-words > *, .er-landing-words .er-door");
    const tiles = boxes(".er-hero-tile, .er-hero-tile-lit");
    const hit = (a: DOMRect, b: DOMRect) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    const out: string[] = [];
    for (const t of tiles) for (const w of text) if (hit(t.r, w.r)) out.push(`${t.el.className} x ${w.el.className || w.el.tagName}`);
    return out;
  });
}

// The two-sided marketplace after the Paper & Ink redesign: the agent banner on every page (owner requirement 1),
// the parallax landing with exactly two buttons (2), the request page and its bounds (3), the volunteer page
// (E09), and the older accessibility and wording guarantees.

const NGO_LABEL = "My NGO needs help";
const HELP_LABEL = "I want to help";
const OLD_NAMES = /shamash|kinema|kothar/i;
const TOOLS_WORD = /\btools?\b/i;

const helpNoun = noun<{ brief: string; brief_interests_goal: string }>("help");
const siteNoun = noun<{ headline: string; subline: string; title: string; privacy: string }>("site");
const askNoun = noun<NonprofitsPageNoun>("nonprofits-page");
const connectNoun = noun<{ title: string; authentication: string; machine_link: string; links: { machine: string } }>("connect");

const ROUTES = ["/", "/help", "/nonprofits", "/library", "/requests/example", "/requests/example/result?part=1", "/catalog", "/catalog/KIT-SHIFT-05", "/contribute", "/tracks", "/fabric", "/about", "/no-such-page"];

function briefFor(mode: "any" | "interests", interests = ""): string {
  if (mode === "any") return helpNoun.brief;
  const body = helpNoun.brief.split("\n\n").slice(1).join("\n\n");
  return `${helpNoun.brief_interests_goal} ${JSON.stringify(interests.trim().slice(0, 1500))}\n\n${body}`;
}

async function stubClipboard(page: Page, refuse = false) {
  await page.addInitScript((refuseWrites: boolean) => {
    const copied: string[] = [];
    Object.defineProperty(window, "copied", { value: copied });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText(text: string) {
          if (refuseWrites) return Promise.reject(new Error("clipboard refused"));
          copied.push(text);
          return Promise.resolve();
        },
      },
    });
  }, refuse);
}

const copied = (page: Page) => page.evaluate(() => (window as unknown as { copied: string[] }).copied);

/** The WCAG contrast ratio of the focused element's text against its own background. */
async function focusedContrast(page: Page): Promise<number> {
  return page.evaluate(() => {
    const rgb = (value: string) => (value.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
    const luminance = (value: string) => {
      const [r = 0, g = 0, b = 0] = rgb(value)
        .map((v) => v / 255)
        .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const style = getComputedStyle(document.activeElement as Element);
    const [a, b] = [luminance(style.color), luminance(style.backgroundColor)];
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  });
}

test.describe("owner 1: the agent instructions banner", () => {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    test(`is one thin line above the header on every page, at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      for (const route of ["/", "/help", "/nonprofits", "/library", "/requests/example", "/catalog", "/about"]) {
        await page.goto(route);
        const banner = page.locator("ta-agent-banner");
        await expect(banner).toHaveAttribute("data-ready", "true");
        const box = await banner.boundingBox();
        const header = await page.locator("header.er-header").boundingBox();
        expect(box && header && box.y === 0 && box.height <= 41 && box.y + box.height <= header.y + 1, route).toBe(true);
        const copy = banner.locator(".bar button.copy");
        await expect(copy).toBeVisible();
        const copyBox = await copy.boundingBox();
        expect(copyBox && copyBox.x + copyBox.width <= viewport.width, route).toBe(true);
      }
    });
  }

  test("AgentBanner board: Copy puts the llms.txt line on the clipboard; How opens the panel; Escape closes and returns focus", async ({ page }) => {
    await stubClipboard(page);
    await page.goto("/nonprofits");
    const banner = page.locator("ta-agent-banner");
    await expect(banner).toHaveAttribute("data-ready", "true");
    await expect(banner.locator(".bar")).toContainText("Have an AI agent?");
    await expect(banner.getByRole("region", { name: "Use this site with your AI agent" })).toBeVisible();
    await banner.locator(".bar button.copy").click();
    expect(await copied(page)).toEqual(["Read https://eranosforgood.org/llms.txt and follow it."]);
    const toggle = banner.locator("button.toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    const panel = banner.locator(".panel");
    await expect(panel).toBeVisible();
    for (const text of ["Paste this into your agent", "What it can do here", "Rules it follows", "Pick up open Tasks as a volunteer"]) {
      await expect(panel).toContainText(text);
    }
    await expect(panel.getByRole("link", { name: "Full agent guide (/connect)" })).toHaveAttribute("href", /\/connect$/);
    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(await toggle.evaluate((el) => (el.getRootNode() as ShadowRoot).activeElement === el)).toBe(true);
  });
});

test.describe("owner 2: the landing", () => {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    test(`has exactly two buttons, "${NGO_LABEL}" first and left, at ${viewport.width}px`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(siteNoun.headline);
      await expect(page).toHaveTitle(`Eranos · ${siteNoun.title}`);
      const buttons = page.locator("main a.er-btn-primary, main a.er-btn-secondary, main button");
      await expect(buttons).toHaveCount(2);
      const group = page.getByRole("group", { name: "Choose your side" });
      const ngo = group.getByRole("link", { name: NGO_LABEL });
      const help = group.getByRole("link", { name: HELP_LABEL });
      await expect(ngo).toHaveAttribute("href", "/nonprofits");
      await expect(help).toHaveAttribute("href", "/help");
      const [a, b] = [await ngo.boundingBox(), await help.boundingBox()];
      if (!a || !b) throw new Error("no layout box");
      expect(viewport.width > 600 ? a.x < b.x : a.y < b.y).toBe(true);
      expect(a.y + a.height).toBeLessThanOrEqual(viewport.height);
      expect(b.y + b.height).toBeLessThanOrEqual(viewport.height);
    });
  }

  test("the hero overlap check fails on its own when a tile sits over the hero's text (its fixture)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 613 });
    await page.goto("/");
    await expect(page.locator(".er-hero-tile")).toHaveCount(4);
    expect(await heroCrossings(page)).toEqual([]);
    await page.evaluate(() => {
      const h1 = document.querySelector(".er-landing-words h1") as HTMLElement;
      const r = h1.getBoundingClientRect();
      const chip = document.createElement("div");
      chip.className = "er-hero-tile er-hero-tile-fixture";
      Object.assign(chip.style, { position: "fixed", left: `${r.left + 10}px`, top: `${r.top + 5}px`, width: "90px", height: "28px", minHeight: "0", padding: "0" });
      document.body.append(chip);
    });
    expect(await heroCrossings(page)).toContain("er-hero-tile er-hero-tile-fixture x er-display");
  });

  // The film's opening shot (Nov 2): the hero's tiles must never cover its text, at any moment of the load animation
  // or while the page scrolls. Sampled every 100 ms for 4 s, then every 40 px of scroll.
  for (const [width, height, scale] of [
    [1280, 613, 1.5],
    [390, 844, 3],
  ] as const) {
    test(`the hero's tiles never cross its text at ${width} x ${height}, during the animation or a scroll`, async ({ browser }) => {
      test.setTimeout(60_000);
      const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: scale });
      const page = await context.newPage();
      await page.goto("/");
      await expect(page.locator(".er-hero-tile")).toHaveCount(4);
      if (width >= 1024) {
        // The film's window: both doors are whole above the fold.
        for (const box of await page.locator(".er-door").evaluateAll((els) => els.map((el) => el.getBoundingClientRect().bottom))) {
          expect(box).toBeLessThanOrEqual(height);
        }
      }
      const crossings = () => heroCrossings(page);
      const seen = new Set<string>();
      const moves = new Set<string>();
      const first = await page.locator(".er-hero-tile").first().boundingBox();
      for (let t = 0; t < 40; t++) {
        for (const c of await crossings()) seen.add(`${t * 100} ms: ${c}`);
        const now = await page.locator(".er-hero-tile").first().boundingBox();
        if (first && now && (now.x !== first.x || now.y !== first.y)) moves.add(`${t * 100} ms`);
        await page.waitForTimeout(100);
      }
      for (let y = 0; y <= 600; y += 40) {
        await page.evaluate((top) => window.scrollTo(0, top), y);
        for (const c of await crossings()) seen.add(`scroll ${y}: ${c}`);
      }
      expect([...seen]).toEqual([]);
      expect([...moves], "the tiles light up in place; they never move").toEqual([]);
      await context.close();
    });
  }
});

test.describe("owner 3: the request page (RequestForm board)", () => {
  test("states the bounds first, asks what would help most (one or both) and how often, with the board's tooltip and 3 examples", async ({ page }) => {
    await page.goto("/nonprofits");
    const bounds = page.getByTestId("request-bounds");
    await expect(bounds).toHaveText(`${askNoun.bounds.head} ${askNoun.bounds.body}`);
    const box = await page.locator("#need").boundingBox();
    const boundsBox = await bounds.boundingBox();
    expect(boundsBox && box && boundsBox.y < box.y).toBe(true);
    await expect(page.getByText("What would help most?")).toBeVisible();
    const process = page.getByRole("checkbox", { name: /A reusable process/ });
    const information = page.getByRole("checkbox", { name: /Information/ });
    await information.check();
    await process.check();
    await expect(process).toBeChecked();
    await expect(information).toBeChecked();
    await expect(page.getByTestId("frequency-help")).toHaveText(askNoun.frequency.help.none);
    await page.getByRole("radio", { name: "Regularly" }).check();
    // Regularly adds a second row, Every month by default, and the help line follows type and frequency.
    await expect(page.getByRole("radio", { name: "Every month" })).toBeChecked();
    await expect(page.getByRole("radio", { name: "Every quarter" })).toBeVisible();
    await expect(page.getByTestId("frequency-help")).toContainText("We run it again every month");
    await page.getByRole("button", { name: "What is a reusable process?" }).focus();
    const tip = page.getByRole("tooltip");
    await expect(tip).toContainText("A reusable process");
    await expect(tip).toContainText("It is also saved to the shared library, so other groups can use it.");
    const chips = page.locator(".er-examples").first().getByRole("button");
    await expect(chips).toHaveText(["Tenant deposit rules", "Read handwritten intake forms", "New grants every month"]);
    for (const example of askNoun.form.examples) {
      await page.getByRole("button", { name: example.short }).click();
      await expect(page.locator("#need")).toHaveValue(example.text);
      expect(example.text).not.toMatch(/\b(transcribe|intake statements?|client files?)\b/i);
    }
    await expect(page.getByRole("radio", { name: "Every month" })).toBeChecked();
  });

  test("E02: the privacy check runs as you type over every box; Send needs a type, 20 characters, nothing private and the tick", async ({ page }) => {
    await page.goto("/nonprofits");
    await expect(page.locator("#need")).toHaveAccessibleDescription(askNoun.form.hint);
    const send = page.getByRole("button", { name: "Send request", exact: true });
    await expect(send).toHaveAttribute("aria-disabled", "true");
    await expect(page.getByTestId("check-line")).toHaveText(askNoun.form.check.empty);
    await expect(page.getByTestId("send-note")).toHaveText(
      "Before sending: choose what would help most, describe it in a sentence or two, tick the box, add your organization\u2019s name and add the type of organization.",
    );
    await page.getByRole("button", { name: "Tenant deposit rules" }).click();
    await expect(page.getByTestId("check-line")).toHaveText(askNoun.form.check.clean);
    await page.getByLabel(/Your organization[’']s name/).fill("Riverside Tenant Clinic");
    await page.getByLabel("Type of organization").fill("Tenant legal-aid clinic");
    await expect(send).toHaveAttribute("aria-disabled", "true");
    await page.getByRole("checkbox", { name: /private information/ }).check();
    await expect(send).toHaveAttribute("aria-disabled", "false");
    await expect(page.getByTestId("send-note")).toHaveText(askNoun.form.ready_note);
    for (const sample of ["Call me at 555-123-4567 about this.", "Write to dana@clinic-mail.org about this."]) {
      await page.locator("#need").fill(sample);
      await expect(page.getByTestId("personal-data-hint")).toBeVisible();
      await expect(send).toHaveAttribute("aria-disabled", "true");
    }
    await expect(page.getByTestId("personal-data-hint")).toContainText("Please take it out before sending.");
    await page.locator("#need").fill("Help us.");
    await expect(send).toHaveAttribute("aria-disabled", "true");
    // aria-disabled keeps the button reachable: a click explains what is missing (Playwright needs force for that).
    await send.click({ force: true });
    await expect(page.getByTestId("send-note")).toHaveText("To send it, describe it in a sentence or two.");
    // An "Other" box and the improvement note are checked too, even with the main box empty.
    await page.locator("#need").fill("");
    await page.getByTestId("advanced-settings").locator("summary").click();
    const tools = page.locator('[data-question="tools"]');
    await tools.getByRole("button", { name: "Other\u2026" }).click();
    await tools.getByLabel("Tools your team works in: other").fill("Email dana@clinic-mail.org");
    await expect(page.getByTestId("personal-data-hint")).toBeVisible();
    await expect(tools.getByRole("button", { name: /^\u2713 Other: / })).toBeVisible();
    await expect(page.locator("details.er-more-details")).not.toHaveAttribute("open", "");
  });

  test("Advanced settings: 'Improve an earlier request' asks for the link and what should be better, and offers recent public requests", async ({ page }) => {
    await page.goto("/nonprofits");
    const advanced = page.getByTestId("advanced-settings");
    await expect(page.getByTestId("advanced-count")).toHaveText("none chosen");
    await advanced.locator("summary").click();
    for (const question of askNoun.advanced.questions.slice(1)) {
      await expect(advanced.locator(`[data-question="${question.id}"]`).getByRole("button", { name: "Other\u2026" })).toBeVisible();
    }
    await expect(advanced.locator('[data-question="start"]').getByRole("button", { name: "Other\u2026" })).toHaveCount(0);
    await advanced.getByRole("radio", { name: "Improve an earlier request" }).check();
    const improve = page.getByTestId("improve-panel");
    await expect(improve.getByLabel("Link to the earlier request or result")).toBeVisible();
    await expect(improve.getByLabel("What should be better?")).toBeVisible();
    // Requests are public, so the recent ones come from their public records, never from this browser.
    await expect(improve).toContainText("Or pick a recent public request:");
    await expect(improve).toContainText("No public requests to pick from right now.");
    await advanced.getByRole("checkbox", { name: "Spreadsheets" }).check();
    await expect(page.getByTestId("advanced-count")).toHaveText("2 chosen");
  });

  test("a flagged request that isn't a reusable process offers to switch to one", async ({ page }) => {
    await page.goto("/nonprofits");
    await page.getByRole("checkbox", { name: /Information/ }).check();
    await page.locator("#need").fill("Write to dana@clinic-mail.org about the forms.");
    const banner = page.getByTestId("switch-to-process");
    await expect(banner).toContainText("Need to work with private files? Ask for a reusable process instead.");
    await banner.getByRole("button", { name: "Switch to a reusable process" }).click();
    await expect(page.getByRole("checkbox", { name: /A reusable process/ })).toBeChecked();
    await expect(page.getByTestId("switch-to-process")).toHaveCount(0);
  });

  test("the offline copy of the site says it does not send", async ({ page }) => {
    await page.goto("/nonprofits");
    await page.getByRole("button", { name: "New grants every month" }).click();
    await page.getByLabel(/Your organization[’']s name/).fill("Riverside Pantry");
    await page.getByLabel("Type of organization").fill("Food pantry");
    await page.getByRole("checkbox", { name: /private information/ }).check();
    await page.getByRole("button", { name: "Send request", exact: true }).click();
    await expect(page.getByTestId("request-problem")).toContainText("This offline copy of the site does not send requests.");
  });

  test("the request box lays out right-to-left text from its first letter", async ({ page }) => {
    await page.goto("/nonprofits");
    for (const id of ["need", "name", "type"]) await expect(page.locator(`#${id}`), id).toHaveAttribute("dir", "auto");
    await page.locator("#need").fill("نحتاج ملخصاً لقوانين الإيجار (2026).");
    expect(await page.locator("#need").evaluate((node) => node.matches(":dir(rtl)"))).toBe(true);
  });
});

test.describe("on the hosted build", () => {
  test.use({ baseURL: LIVE });

  test("the live bundle carries none of the owner's forbidden words", async ({ page, request }) => {
    await mockSite(page);
    await page.goto("/");
    const scripts = await page.$$eval("script[src]", (nodes) => nodes.map((n) => (n as HTMLScriptElement).src));
    const html = await (await request.get("/")).text();
    let text = html;
    for (const src of scripts) text += await (await request.get(src)).text();
    expect(scripts.length).toBeGreaterThan(0);
    expect(text).not.toMatch(/synthetic|\bo?l{2}ama\b|kothar|kinema|shamash/i);
  });

  test("B2: /help lists the live open tasks, and a task copies as a claim for your agent", async ({ page }) => {
    await stubClipboard(page);
    const now = Math.floor(Date.now() / 1000);
    await mockSite(page, {
      openTasks: [
        { task_id: "t-research-1", queue: "eq02", kind: "research", title: "Practice case: an example, not a real person or case. Summarize tenant deposit rules", created_at: now - 600, open_to_anonymous: true },
        { task_id: "t-check-2", queue: "eq03", kind: "report_review", title: "Check a cited report", created_at: now - 7200, open_to_anonymous: false },
      ],
    });
    await page.goto("/help");
    const list = page.getByTestId("open-task-list");
    await expect(list.locator("li")).toHaveCount(2);
    await expect(list.locator("li").first()).toContainText("Summarize tenant deposit rules");
    // An example task keeps its practice-case mark (AGENTS.md rule 1), in the words the site serves.
    await expect(list.locator("li").first()).toContainText("Practice case: an example, not a real person or case. Summarize tenant deposit rules");
    await expect(list.locator("li").nth(1)).toContainText("needs a volunteer key");
    await list.locator("li").first().getByRole("button", { name: "Copy for my agent" }).click();
    expect((await copied(page)).at(-1)).toMatch(/Claim the open task t-research-1 on Eranos[’']s queue eq02/);
  });


  test("E01: when the queue can't be reached, the 'Right now' strip is absent, not zeros", async ({ page }) => {
    await mockSite(page, { fabricFails: true });
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByTestId("right-now")).toHaveCount(0);
    await expect(page.locator(".er-safety-grid")).toContainText("the site calls no AI model");
    await expect(page.locator(".er-safety-grid")).toContainText("a dedicated worker run by ta-amps picks it up, at any hour");
    await page.unroute(`${LIVE}/api/**`);
    await mockSite(page, {
      fabric: {
        queues: [
          { name: "eq01", ready: 2, leased: 1, waiting: 0, done: 0, dead: 0, cancelled: 0 },
          { name: "eq02", ready: 1, leased: 0, waiting: 0, done: 0, dead: 0, cancelled: 0 },
        ],
      },
    });
    await page.reload();
    await expect(page.getByTestId("right-now")).toContainText("4 requests in progress");
    await expect(page.getByTestId("right-now")).toContainText("3 open tasks");
    await page.unroute(`${LIVE}/api/**`);
    await mockSite(page, {
      fabric: {
        queues: [
          { name: "eq01", ready: 0, leased: 0, waiting: 0, done: 8, dead: 0, cancelled: 0 },
          { name: "eq02", ready: 1, leased: 0, waiting: 0, done: 5, dead: 0, cancelled: 0 },
          { name: "eq03", ready: 0, leased: 0, waiting: 0, done: 4, dead: 0, cancelled: 0 },
        ],
        swarm: {
          ngo_ready: 7,
          ngo_leased: 2,
          ngo_done: 112,
          general_ready: 11,
          general_leased: 3,
          general_done: 263,
          registered_workers: 51,
          stored_task_objects: 1103,
        },
      },
    });
    await page.reload();
    await expect(page.getByTestId("right-now")).toContainText("1 request in progress");
    await expect(page.getByTestId("right-now")).toContainText("1 open task");
    await expect(page.getByTestId("right-now-swarm")).toContainText("18 tasks open for nonprofits and public-good groups across the shared work queue");
    await expect(page.getByTestId("right-now-swarm")).toContainText("51 volunteer and dedicated workers");
    await expect(page.getByTestId("right-now-swarm")).toContainText("375 finished");
  });


  test("F31-002: before the app runs, the page is styled and shows no fallback; the fallback is only for no-script readers", async ({ page }) => {
    await mockSite(page);
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route(/\/assets\/index-.*\.js$/, async (route) => {
      await held;
      await route.continue();
    });
    await page.goto("/", { waitUntil: "commit" });
    await page.waitForFunction(() => document.body && getComputedStyle(document.body).backgroundColor === "rgb(245, 242, 234)");
    const before = await page.evaluate(() => ({
      background: getComputedStyle(document.body).backgroundColor,
      // innerText: what is rendered. A <noscript> body is raw text while scripts run, and is never shown.
      visibleText: (document.querySelector("#root") as HTMLElement | null)?.innerText?.trim() ?? "",
      fallback: document.querySelectorAll("#root noscript").length,
    }));
    expect(before.background).toBe("rgb(245, 242, 234)");
    expect(before.visibleText).toBe("");
    expect(before.fallback).toBe(1);
    release();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(siteNoun.headline);
  });
});

test.describe("E09: I want to help", () => {
  test("Copy instructions puts the exact brief on the clipboard, with interests kept in this browser", async ({ page }) => {
    await stubClipboard(page);
    const traffic: string[] = [];
    page.on("request", (request) => traffic.push(`${request.url()}\n${request.postData() ?? ""}`));
    await page.goto("/help");
    const card = page.getByTestId("agent-brief");
    await card.getByRole("button", { name: "Copy instructions" }).click();
    await expect(card.getByRole("status")).toHaveText("Copied. Paste it into your agent.");
    expect(await copied(page)).toEqual([briefFor("any")]);
    await card.getByRole("radio", { name: "Only my interests" }).click();
    await card.getByRole("button", { name: "Copy instructions" }).click();
    await expect(card.getByRole("status")).toHaveText("Add a topic or goal first.");
    await expect(card.getByLabel("Your topics or goals")).toBeFocused();
    const topic = "housing, food access, grants";
    await card.getByLabel("Your topics or goals").fill(topic);
    await card.getByRole("button", { name: "Copy instructions" }).click();
    expect(await copied(page)).toEqual([briefFor("any"), briefFor("interests", topic)]);
    await expect(card.getByTestId("brief-text")).toHaveText(briefFor("interests", topic));
    expect(traffic.filter((line) => line.includes("food access"))).toEqual([]);
  });

  test("without a volunteer key, what your tokens did is the empty state", async ({ page }) => {
    await page.goto("/help");
    await expect(page.getByTestId("tokens-empty")).toContainText("After your agent finishes a task, what it did shows up here");
    await expect(page.getByTestId("your-agent")).toContainText("No agent connected in this browser.");
  });
});

test.describe("wording and accessibility", () => {
  test("no visible text, title or label names a retired pack, and no page shows a status stamp", async ({ page }) => {
    for (const route of ROUTES) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const text = await page.locator("body").innerText();
      expect(text, route).not.toMatch(OLD_NAMES);
      expect(text, route).not.toMatch(/\b(PLANNED|ILLUSTRATION|SYNTHETIC DATA ONLY|demo mode)\b/);
      expect(await page.title(), route).not.toMatch(OLD_NAMES);
    }
  });

  test("the marketplace pages never call agent kits tools", async ({ page }) => {
    for (const route of ["/", "/nonprofits", "/help"]) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      // The brief is the agents' own canonical text, the tooltip is the owner's wording, and the Advanced settings ask
      // about the team's own software ("Tools your team works in", "Free tools only", RequestForm board); none of
      // them calls a kit a tool.
      const copy = await page.locator("main").evaluate((main) => {
        const clone = main.cloneNode(true) as HTMLElement;
        clone
          .querySelectorAll('[data-testid="brief-text"], [role="tooltip"], [data-testid="advanced-settings"]')
          .forEach((node) => node.remove());
        return clone.innerText ?? clone.textContent ?? "";
      });
      expect(copy, route).not.toMatch(TOOLS_WORD);
    }
  });

  test("F31-003: a link to Agora's overview deck says it is a deck", async ({ page }) => {
    for (const route of ["/", "/nonprofits", "/requests/example/result?part=1"]) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const links = await page.$$eval('a[href*="/decks/"]', (as) => as.map((a) => a.textContent ?? ""));
      // The header's "How it works ↗" now opens Agora's How it works page; any link that does open a deck says so.
      for (const label of links) expect(label, route).toMatch(/deck/i);
    }
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`the skip link is first and readable when it has focus, ${scheme} theme`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      for (const path of ["/", "/nonprofits"]) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await page.keyboard.press("Tab");
        const skip = page.getByRole("link", { name: "Skip to content" });
        await expect(skip).toBeFocused();
        await expect(skip).toBeInViewport();
        expect(await focusedContrast(page), `${path} ${scheme}`).toBeGreaterThanOrEqual(4.5);
      }
    });
  }

  test("no page scrolls sideways at 320 or 390 px, and the phone header is one 56 px row with a Menu button", async ({ page }) => {
    for (const width of [320, 390]) {
      await page.setViewportSize({ width, height: 700 });
      for (const path of ["/", "/help", "/nonprofits", "/library", "/requests/example", "/requests/example/result?part=1", "/connect"]) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow, `${path} at ${width}`).toBeLessThanOrEqual(0);
        const header = await page.locator("header.er-header").boundingBox();
        expect(header && header.height <= 57, `${path} at ${width}`).toBe(true);
        const menu = page.getByRole("button", { name: "Menu" });
        const box = await menu.boundingBox();
        expect(box && box.width >= 44 && box.height >= 44).toBe(true);
      }
    }
  });

  test("B03: the phone menu reports its state, takes focus, and Escape returns focus to the button", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const menu = page.getByRole("button", { name: "Menu" });
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    await menu.click();
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("dialog", { name: "Menu" }).getByRole("link", { name: "My NGO needs help" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    await expect(menu).toBeFocused();
  });

  test("B03: at 1440 the navigation is one row", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    const tops = await page.$$eval("nav.er-nav a", (as) => as.map((a) => Math.round(a.getBoundingClientRect().top)));
    expect(new Set(tops).size).toBe(1);
  });

  test("a kit address with a broken percent escape is a missing page, not a blank one", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/catalog");
    await page.evaluate(() => {
      window.history.pushState(null, "", "/catalog/%E0%A4%A");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("/connect is a page of the site, with its layout and title, light only", async ({ page }) => {
    await page.goto("/connect");
    await expect(page).toHaveTitle("Connect to Eranos");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(connectNoun.title);
    await expect(page.locator("main")).toContainText(connectNoun.authentication);
    await expect(page.getByRole("navigation", { name: "Primary navigation" }).first()).toBeAttached();
    await expect(page.getByRole("link", { name: connectNoun.machine_link })).toHaveAttribute("href", connectNoun.links.machine);
    const colours = () =>
      page.evaluate(() => ({ text: getComputedStyle(document.querySelector("main") as Element).color, background: getComputedStyle(document.body).backgroundColor }));
    const light = await colours();
    expect(light.background).toBe("rgb(245, 242, 234)");
    await page.emulateMedia({ colorScheme: "dark" });
    const dark = await colours();
    // Light only (owner, Nov 1): the dark scheme changes nothing, and the page stays on paper.
    expect(dark.background).toBe(light.background);
    expect(dark.background).toBe("rgb(245, 242, 234)");
    expect(dark.text).toBe(light.text);
  });

  test("the footer is the standard one: one row of links and one short line (ta-amps.footer/1, rule 13)", async ({ page }) => {
    for (const path of ["/", "/help", "/nonprofits", "/connect"]) {
      await page.goto(path);
      await expect(page.getByTestId("footer-line")).toHaveText("We don’t accept private information at this stage.");
    }
    const footer = page.locator("footer.er-footer");
    const links = footer.getByRole("navigation", { name: "Site information" }).getByRole("link");
    await expect(links).toHaveText(["Agora ↗", "Teleion Labs ↗", "Library", "Requests", "Network ↗", "Models used ↗", "Status ↗", "Source ↗", "Privacy", "Terms", "Report a problem"]);
    await expect(footer.getByRole("link", { name: "Privacy" })).toHaveAttribute("href", "/privacy");
    await expect(footer.getByRole("link", { name: "Status ↗" })).toHaveAttribute("href", "https://agora.eranosforgood.org/status/");
    // One row: at desktop width every link sits on the same line.
    await page.setViewportSize({ width: 1440, height: 900 });
    const tops = await links.evaluateAll((els) => [...new Set(els.map((el) => Math.round(el.getBoundingClientRect().top)))]);
    expect(tops).toHaveLength(1);
  });

  test("trust pages (/privacy, /terms, /report) and 404 render plain-language guidance without status stamps", async ({ page }) => {
    await page.goto("/privacy");
    await expect(page.getByRole("heading", { level: 1, name: "Privacy, in plain words" })).toBeVisible();
    await expect(page.locator("main")).toContainText("#k=");
    await expect(page.locator("main")).toContainText("history.replaceState");
    await expect(page.locator("main")).toContainText("one of Eranos’s own workers");
    await expect(page.locator("main")).toContainText("tasks (things to do)");
    await expect(page.locator("main")).toContainText("Task Objects");

    await page.goto("/terms");
    await expect(page.getByRole("heading", { level: 1, name: "Terms of use" })).toBeVisible();
    await expect(page.locator("main")).toContainText("CC BY 4.0");
    await expect(page.locator("main")).toContainText("Apache-2.0");
    await expect(page.locator("main")).toContainText("A person decides. Nothing is used before that.");

    await page.goto("/report");
    await expect(page.getByRole("heading", { level: 1, name: "Report a problem" })).toBeVisible();
    await expect(page.locator('main a[href="https://github.com/ta-amps/eranos-public-marketplace-for-public-good-token-burn/issues"]')).toBeVisible();
    await expect(page.locator('main a[href="/.well-known/security.txt"]')).toBeVisible();

    await page.goto("/missing-route-way-forward");
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    await expect(page.getByTestId("not-found")).toContainText("/missing-route-way-forward");
    await expect(page.getByTestId("not-found").getByRole("link", { name: /My NGO needs help/ })).toHaveAttribute("href", "/nonprofits");
    await expect(page.getByTestId("not-found").getByRole("link", { name: /I want to help/ })).toHaveAttribute("href", "/help");
  });

  test("opt-in ?tour=judge renders the 5-step tour strip below the header, tracks steps, fits 320px, and closes cleanly", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    await expect(page.getByTestId("judge-tour")).toHaveCount(0);

    await page.goto("/nonprofits?tour=judge");
    const tour = page.getByTestId("judge-tour");
    await expect(tour).toBeVisible();
    const headerBox = await page.locator("header.er-header").boundingBox();
    const tourBox = await tour.boundingBox();
    const mainBox = await page.locator("main#main").boundingBox();
    expect(headerBox && tourBox && mainBox && tourBox.y >= headerBox.y + headerBox.height - 1 && mainBox.y >= tourBox.y + tourBox.height - 1).toBe(true);

    await expect(tour.getByRole("link", { name: /Agora/ }).first()).toHaveAttribute("href", "https://agora.eranosforgood.org/?tour=judge");
    const askStep = tour.locator("ol a", { hasText: "Ask" });
    await expect(askStep).toHaveAttribute("aria-current", "step");
    await expect(askStep).toHaveAttribute("href", "/nonprofits?tour=judge");
    await expect(tour.locator("ol a", { hasText: "Watch a request" })).toHaveAttribute("href", "/requests/REQ-INTAKE-07?tour=judge");
    await expect(tour.locator("ol a", { hasText: "The result" })).toHaveAttribute("href", "/requests/REQ-INTAKE-07?tour=judge#step-ready");
    await expect(tour.locator("ol a", { hasText: "Live queue" })).toHaveAttribute("href", "https://agora.eranosforgood.org/studio/?tour=judge");

    await tour.locator("ol a", { hasText: "Watch a request" }).click();
    await expect(page).toHaveURL(/\/requests\/REQ-INTAKE-07\?tour=judge$/);
    await expect(tour.locator("ol a", { hasText: "Watch a request" })).toHaveAttribute("aria-current", "step");

    await tour.locator("ol a", { hasText: "The result" }).click();
    await expect(page).toHaveURL(/\/requests\/REQ-INTAKE-07\?tour=judge#step-ready$/);
    await expect(tour.locator("ol a", { hasText: "The result" })).toHaveAttribute("aria-current", "step");
    await expect(page.locator("#step-ready")).toHaveAttribute("data-state", "now");

    for (const width of [320, 390]) {
      await page.setViewportSize({ width, height: 700 });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `tour at ${width}px`).toBeLessThanOrEqual(0);
    }

    await tour.getByRole("button", { name: "Close the tour" }).click();
    await expect(page.getByTestId("judge-tour")).toHaveCount(0);
    await expect(page).not.toHaveURL(/tour=judge/);
  });
});
