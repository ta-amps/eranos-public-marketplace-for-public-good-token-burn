import { expect, test, type Page } from "@playwright/test";

import { LIVE, mockSite, noun } from "./support/mocks";

// The two-sided marketplace after the Paper & Ink redesign: the agent banner on every page (owner requirement 1),
// the parallax landing with exactly two buttons (2), the request page and its bounds (3), the volunteer page
// (E09), and the older accessibility and wording guarantees.

const NGO_LABEL = "My NGO needs help";
const HELP_LABEL = "I want to help";
const OLD_NAMES = /shamash|kinema|kothar/i;
const TOOLS_WORD = /\btools?\b/i;

const helpNoun = noun<{ brief: string; brief_interests_goal: string }>("help");
const siteNoun = noun<{ headline: string; subline: string; title: string; privacy: string }>("site");
const askNoun = noun<{ bounds: { head: string; body: string }; form: { label: string; hint: string } }>("nonprofits-page");
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
        expect(box && header && box.y === 0 && box.height <= 40 && box.y + box.height <= header.y + 1, route).toBe(true);
        const copy = banner.locator(".bar button.copy");
        await expect(copy).toBeVisible();
        const copyBox = await copy.boundingBox();
        expect(copyBox && copyBox.x + copyBox.width <= viewport.width, route).toBe(true);
      }
    });
  }

  test("Copy puts the brief on the clipboard; More opens the instructions; Escape closes and returns focus", async ({ page }) => {
    await stubClipboard(page);
    await page.goto("/nonprofits");
    const banner = page.locator("ta-agent-banner");
    await expect(banner).toHaveAttribute("data-ready", "true");
    await banner.locator(".bar button.copy").click();
    expect(await copied(page)).toEqual([helpNoun.brief]);
    const more = banner.locator("button.more");
    await expect(more).toHaveAttribute("aria-expanded", "false");
    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "true");
    const panel = banner.locator(".panel");
    await expect(panel).toBeVisible();
    await expect(panel.locator("textarea")).toHaveValue(helpNoun.brief);
    await expect(panel.getByRole("link", { name: "MCP, HTTP or command line" })).toBeVisible();
    expect(await panel.evaluate((el) => el.getRootNode() instanceof ShadowRoot && (el.getRootNode() as ShadowRoot).activeElement === el)).toBe(true);
    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
    await expect(more).toHaveAttribute("aria-expanded", "false");
    expect(await more.evaluate((el) => (el.getRootNode() as ShadowRoot).activeElement === el)).toBe(true);
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

  test("the layers move only while the page scrolls, and never with reduced motion", async ({ browser }) => {
    for (const reducedMotion of ["no-preference", "reduce"] as const) {
      const context = await browser.newContext({ reducedMotion, viewport: { width: 1440, height: 900 } });
      const page = await context.newPage();
      await page.goto("/");
      await page.waitForTimeout(300);
      const before = await page.locator(".er-layer-a").evaluate((el) => getComputedStyle(el).transform);
      await page.waitForTimeout(600);
      expect(await page.locator(".er-layer-a").evaluate((el) => getComputedStyle(el).transform)).toBe(before);
      await page.mouse.wheel(0, 500);
      await page.waitForTimeout(400);
      const after = await page.locator(".er-layer-a").evaluate((el) => getComputedStyle(el).transform);
      if (reducedMotion === "reduce") expect(after).toBe(before);
      else expect(after).not.toBe(before);
      await context.close();
    }
  });
});

test.describe("owner 3: the request page", () => {
  test("states the bounds first, asks the kind of output (one or both) and how often, and its examples need no private data", async ({ page }) => {
    await page.goto("/nonprofits");
    const bounds = page.getByTestId("request-bounds");
    await expect(bounds).toHaveText(`${askNoun.bounds.head} ${askNoun.bounds.body}`);
    const box = await page.locator("#need").boundingBox();
    const boundsBox = await bounds.boundingBox();
    expect(boundsBox && box && boundsBox.y < box.y).toBe(true);
    const process = page.getByRole("checkbox", { name: /A reusable process/ });
    const information = page.getByRole("checkbox", { name: /Information/ });
    await process.check();
    await information.check();
    await expect(process).toBeChecked();
    await expect(information).toBeChecked();
    await page.getByRole("radio", { name: "Recurring" }).check();
    await expect(page.getByLabel("How often should it run?")).toBeVisible();
    // The tooltip on "A reusable process".
    await page.getByRole("button", { name: "What is a reusable process?" }).focus();
    await expect(page.getByRole("tooltip")).toContainText("ready to launch locally or in the cloud");
    for (const name of ["Tenant deposit laws", "Grant deadlines every month", "A process for handwritten case notes"]) {
      await page.getByRole("button", { name }).click();
      const text = await page.locator("#need").inputValue();
      expect(text.length).toBeGreaterThan(20);
      expect(text).not.toMatch(/\b(transcribe|intake statements?|client files?)\b/i);
    }
    await expect(page.getByRole("checkbox", { name: /A reusable process/ })).toBeChecked();
    await expect(page.getByRole("radio", { name: "Recurring" })).toBeChecked();
  });

  test("E02: examples fill the box; personal data is flagged within a second; Send waits for text and consent; details start closed", async ({ page }) => {
    await page.goto("/nonprofits");
    await expect(page.locator("#need")).toHaveAccessibleDescription(askNoun.form.hint);
    const send = page.getByRole("button", { name: "Send", exact: true });
    await expect(send).toBeDisabled();
    await page.getByRole("button", { name: "Tenant deposit laws" }).click();
    await expect(page.locator("#need")).not.toHaveValue("");
    await expect(send).toBeDisabled();
    await page.getByRole("checkbox", { name: /personal information/ }).check();
    await expect(send).toBeEnabled();
    for (const sample of ["Call me at 555-123-4567 about this.", "Write to dana@clinic-mail.org about this."]) {
      await page.locator("#need").fill(sample);
      await expect(page.getByTestId("personal-data-hint")).toBeVisible({ timeout: 1000 });
    }
    await expect(page.getByTestId("personal-data-hint")).toContainText("Please take it out: requests are public.");
    await expect(page.locator("details.er-more-details")).not.toHaveAttribute("open", "");
    await expect(page.getByText(askNoun.form.label, { exact: true })).toBeVisible();
    await page.locator("#need").fill("Help us.");
    await expect(page.getByTestId("too-short-hint")).toBeVisible({ timeout: 1000 });
  });

  test("the offline copy of the site says it does not send", async ({ page }) => {
    await page.goto("/nonprofits");
    await page.getByRole("button", { name: "Grant deadlines every month" }).click();
    await page.getByLabel("Your organization's name").fill("Synthetic Pantry");
    await page.getByLabel("Type of organization").fill("Food pantry");
    await page.getByLabel("How often should it run?").selectOption("monthly");
    await page.getByRole("checkbox", { name: /personal information/ }).check();
    await page.getByRole("button", { name: "Send", exact: true }).click();
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

  test("B2: /help lists the live open tasks, and a task copies as a claim for your agent", async ({ page }) => {
    await stubClipboard(page);
    const now = Math.floor(Date.now() / 1000);
    await mockSite(page, {
      openTasks: [
        { task_id: "t-research-1", queue: "eq02", kind: "research", title: "SYNTHETIC: Summarize tenant deposit rules", created_at: now - 600, open_to_anonymous: true },
        { task_id: "t-check-2", queue: "eq03", kind: "report_review", title: "Check a cited report", created_at: now - 7200, open_to_anonymous: false },
      ],
    });
    await page.goto("/help");
    const list = page.getByTestId("open-task-list");
    await expect(list.locator("li")).toHaveCount(2);
    await expect(list.locator("li").first()).toContainText("Summarize tenant deposit rules");
    await expect(list).not.toContainText("SYNTHETIC");
    await expect(list.locator("li").nth(1)).toContainText("needs a volunteer key");
    await list.locator("li").first().getByRole("button", { name: "Copy for my agent" }).click();
    expect((await copied(page)).at(-1)).toContain("Claim the open task t-research-1 on Eranos's queue eq02");
  });


  test("E01: when the queue can't be reached, the 'Right now' strip is absent, not zeros", async ({ page }) => {
    await mockSite(page, { fabricFails: true });
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByTestId("right-now")).toHaveCount(0);
    await page.unroute(`${LIVE}/api/**`);
    await mockSite(page, { fabric: { queues: [{ name: "eq01", ready: 2, leased: 1, waiting: 0, done: 0, dead: 0, cancelled: 0 }, { name: "eq02", ready: 1, leased: 0, waiting: 0, done: 0, dead: 0, cancelled: 0 }] } });
    await page.reload();
    await expect(page.getByTestId("right-now")).toContainText("3 requests in progress");
    await expect(page.getByTestId("right-now")).toContainText("3 open tasks");
  });

  test("E01: a cold load paints the largest text within 2.5 s and shifts nothing (simulated slow 4G)", async ({ page }) => {
    await mockSite(page);
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 });
    await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
    await page.addInitScript(() => {
      const w = window as unknown as { lcp: number; cls: number };
      w.lcp = 0;
      w.cls = 0;
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) w.lcp = entry.startTime;
      }).observe({ type: "largest-contentful-paint", buffered: true });
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries() as (PerformanceEntry & { value: number; hadRecentInput: boolean })[]) if (!entry.hadRecentInput) w.cls += entry.value;
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto("/", { waitUntil: "load" });
    await page.waitForTimeout(1500);
    const { lcp, cls } = await page.evaluate(() => {
      const w = window as unknown as { lcp: number; cls: number };
      return { lcp: w.lcp, cls: w.cls };
    });
    console.log(`cold load: LCP ${Math.round(lcp)} ms, CLS ${cls.toFixed(3)}`);
    expect(lcp).toBeGreaterThan(0);
    expect(lcp).toBeLessThan(2500);
    expect(cls).toBeLessThan(0.1);
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
    await expect(page.getByTestId("tokens-empty")).toContainText("After your agent finishes a task, its receipts show up here");
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
      // The brief is the agents' own canonical text, and the tooltip is the owner's wording about the
      // organization's own tools; neither calls a kit a tool.
      const copy = await page.locator("main").evaluate((main) => {
        const clone = main.cloneNode(true) as HTMLElement;
        clone.querySelectorAll('[data-testid="brief-text"], [role="tooltip"]').forEach((node) => node.remove());
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
      expect(links.length, route).toBeGreaterThan(0);
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
    await expect(page.getByRole("dialog", { name: "Menu" }).getByRole("link", { name: "I want to help" })).toBeFocused();
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

  test("/connect is a page of the site, with its layout, title and both themes", async ({ page }) => {
    await page.goto("/connect");
    await expect(page).toHaveTitle("Connect to Eranos");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(connectNoun.title);
    await expect(page.locator("main")).toContainText(connectNoun.authentication);
    await expect(page.getByRole("navigation", { name: "Primary navigation" }).first()).toBeAttached();
    await expect(page.getByRole("link", { name: connectNoun.machine_link })).toHaveAttribute("href", connectNoun.links.machine);
    const colours = () =>
      page.evaluate(() => ({ text: getComputedStyle(document.querySelector("main") as Element).color, background: getComputedStyle(document.body).backgroundColor }));
    const light = await colours();
    await page.emulateMedia({ colorScheme: "dark" });
    const dark = await colours();
    expect(dark.background).not.toBe(light.background);
    expect(dark.text).not.toBe(light.text);
  });

  test("the footer says what the site loads and keeps, from the site noun", async ({ page }) => {
    for (const path of ["/", "/help", "/nonprofits", "/connect"]) {
      await page.goto(path);
      await expect(page.getByTestId("privacy-line")).toHaveText(siteNoun.privacy);
    }
  });
});
