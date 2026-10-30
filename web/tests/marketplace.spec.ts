import fs from "node:fs";

import { expect, test, type Page } from "@playwright/test";

// The two-sided marketplace: two equal front doors on the home page, the /help and /nonprofits pages,
// the canonical starting brief, the request-a-kit form link and the wording rules.

const HELP_LABEL = "I want to help";
const NGO_LABEL = "I'm an NGO looking for agentic solutions";
const OLD_NAMES = /shamash|kinema|kothar/i;
const TOOLS_WORD = /\btools?\b/i;
const REQUEST_KIT_URL = "https://github.com/ta-amps/eranos-public-marketplace-for-public-good-token-burn/issues/new?template=request-a-kit.yml";

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "phone", width: 390, height: 844 },
] as const;

const catalog = JSON.parse(
  fs.readFileSync(new URL("../snapshot/catalog.json", import.meta.url), "utf8"),
) as { kits: { kit: { kit_id: string } }[] };
const KIT_IDS = catalog.kits.map((entry) => entry.kit.kit_id);

// Needs in organizations' own words and the recorded example runs: nouns the snapshot carries.
const examples = JSON.parse(
  fs.readFileSync(new URL("../snapshot/examples.json", import.meta.url), "utf8"),
) as { needs: { kit_id: string; says: string; mark: string }[]; runs: { count: number; label: string } };

const ROUTES = [
  "/",
  "/help",
  "/nonprofits",
  "/catalog",
  ...KIT_IDS.map((id) => `/catalog/${id}`),
  "/contribute",
  "/tracks",
  "/fabric",
  "/about",
  "/no-such-page",
];

type BuildAgentPrompt = (origin: string, mode: "any" | "interests", interests?: string) => string;

/** The Worker's vendored onboarding module: the one source of the starting brief. */
async function canonicalBrief(): Promise<BuildAgentPrompt> {
  const href = new URL("../../deploy/cloudflare/agent_start.js", import.meta.url).href;
  const module = (await import(href)) as { buildAgentPrompt: BuildAgentPrompt };
  return module.buildAgentPrompt;
}

/** Replaces the clipboard with a recorder, or with one that refuses every write. */
async function stubClipboard(page: Page, refuse = false) {
  await page.addInitScript((refuseWrites: boolean) => {
    const copied: string[] = [];
    Object.defineProperty(window, "copiedBriefs", { value: copied });
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

async function copiedBriefs(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { copiedBriefs: string[] }).copiedBriefs);
}

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.name} ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test("home page shows two equal front doors near the top", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(
        "Spare AI capacity builds tested agent kits for nonprofits",
      );
      const doors = page.getByRole("group", { name: "Choose your side" });
      const help = doors.getByRole("link", { name: HELP_LABEL, exact: true });
      const ngo = doors.getByRole("link", { name: NGO_LABEL, exact: true });
      await expect(help).toBeVisible();
      await expect(ngo).toBeVisible();
      await expect(help).toHaveAttribute("href", "/help");
      await expect(ngo).toHaveAttribute("href", "/nonprofits");

      // Equal weight: the same style and the same size, and both visible without scrolling.
      expect(await help.getAttribute("class")).toBe(await ngo.getAttribute("class"));
      const [a, b] = [await help.boundingBox(), await ngo.boundingBox()];
      if (!a || !b) throw new Error("door buttons have no layout box");
      expect(Math.abs(a.width - b.width)).toBeLessThanOrEqual(1);
      expect(Math.abs(a.height - b.height)).toBeLessThanOrEqual(1);
      expect(a.y + a.height).toBeLessThanOrEqual(viewport.height);
      expect(b.y + b.height).toBeLessThanOrEqual(viewport.height);
    });

    test("no horizontal overflow on the marketplace pages", async ({ page }) => {
      for (const path of ["/", "/help", "/nonprofits"]) {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth > window.innerWidth,
        );
        expect(overflow, path).toBe(false);
      }
    });
  });
}

test("each front door opens its side of the marketplace", async ({ page }) => {
  await page.goto("/");
  const doors = page.getByRole("group", { name: "Choose your side" });
  await doors.getByRole("link", { name: HELP_LABEL, exact: true }).click();
  await expect(page).toHaveURL(/\/help$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Help with AI capacity you won't use");
  await expect(page).toHaveTitle(/I want to help/);

  await page.goBack();
  await doors.getByRole("link", { name: NGO_LABEL, exact: true }).click();
  await expect(page).toHaveURL(/\/nonprofits$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Agent kits for nonprofits, NGOs and public-good groups",
  );
});

test("/help explains helping, the four steps, connecting, open tasks and what stays with people", async ({
  page,
}) => {
  await page.goto("/help");
  const main = page.locator("main");
  await expect(main).toContainText("Connect your own agent and donate the tokens you won't use.");
  for (const heading of ["What helping means", "How it works", "Connect your agent", "Open tasks", "What stays with people"]) {
    await expect(page.getByRole("heading", { level: 2, name: heading })).toBeVisible();
  }
  const steps = main.locator("ol.er-steps > li h3");
  await expect(steps).toHaveText(["Check", "Build", "Review", "Publish"]);
  await expect(main).toContainText("A builder never approves its own kit.");

  // The existing connect path: the Worker's /connect page, Agora's guide and the detailed setup page.
  await expect(page.getByRole("button", { name: "Copy: work on anything" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Connection details for this site" })).toHaveAttribute("href", "/connect");
  await expect(page.getByRole("link", { name: "Connect any agent, step by step, on Agora" })).toHaveAttribute(
    "href",
    "https://ta-amps.github.io/agora-public-overview-architecture-setup-and-contribution/contribute/#agent",
  );
  await expect(page.getByRole("link", { name: "How the whole system works, on Agora" })).toHaveAttribute(
    "href",
    "https://ta-amps.github.io/agora-public-overview-architecture-setup-and-contribution/docs/how-it-works/",
  );
  await expect(page.getByRole("link", { name: "Setup for MCP, HTTP and command-line agents" })).toHaveAttribute(
    "href",
    "/contribute",
  );

  await expect(page.getByTestId("open-tasks").locator("article")).toHaveCount(4);
  await expect(main).toContainText("Crisis and safety planning.");
  await expect(main).toContainText("Anything sent or filed outside the organization.");
  await expect(page.getByTestId("status-note")).toContainText("Hosted volunteer runs");
});

test("/help copies the same starting brief the Worker serves, keeping interest text local", async ({ page }) => {
  const buildAgentPrompt = await canonicalBrief();
  await stubClipboard(page);
  const traffic: string[] = [];
  page.on("request", (request) => traffic.push(`${request.url()}\n${request.postData() ?? ""}`));

  await page.goto("/help");
  const origin = new URL(page.url()).origin;
  const brief = page.getByTestId("agent-brief");
  const status = brief.getByRole("status");

  await brief.getByRole("button", { name: "Copy: work on anything" }).click();
  await expect(status).toHaveText("Copied. Paste these instructions into your agent.");
  expect(await copiedBriefs(page)).toEqual([buildAgentPrompt(origin, "any")]);

  await brief.getByText("Follow my interests", { exact: true }).click();
  await brief.getByRole("button", { name: "Copy: follow my interests" }).click();
  await expect(status).toHaveText("Add a topic or goal first.");
  await expect(brief.getByLabel("Your topics or project goals")).toBeFocused();

  const topic = "grant reporting for small food banks";
  await brief.getByLabel("Your topics or project goals").fill(topic);
  await brief.getByRole("button", { name: "Copy: follow my interests" }).click();
  await expect(status).toHaveText("Copied. Paste these instructions into your agent.");
  expect(await copiedBriefs(page)).toEqual([
    buildAgentPrompt(origin, "any"),
    buildAgentPrompt(origin, "interests", topic),
  ]);

  await brief.getByText("View instructions", { exact: true }).click();
  await expect(brief.getByLabel("Instructions to copy into your agent")).toHaveValue(
    buildAgentPrompt(origin, "interests", topic),
  );
  const leaked = traffic.filter((line) => line.includes(topic) || line.includes(encodeURIComponent(topic)));
  expect(leaked).toEqual([]);
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
});

test("/help falls back to selected text when the clipboard refuses", async ({ page }) => {
  const buildAgentPrompt = await canonicalBrief();
  await stubClipboard(page, true);
  await page.goto("/help");
  const brief = page.getByTestId("agent-brief");
  await brief.getByRole("button", { name: "Copy: work on anything" }).click();
  await expect(brief.getByRole("status")).toHaveText(
    "Select and copy the instructions below, then paste them into your agent.",
  );
  const text = brief.getByLabel("Instructions to copy into your agent");
  await expect(text).toBeVisible();
  await expect(text).toBeFocused();
  const expected = buildAgentPrompt(new URL(page.url()).origin, "any");
  await expect(text).toHaveValue(expected);
  const selection = await text.evaluate((node) => {
    const area = node as HTMLTextAreaElement;
    return [area.selectionStart, area.selectionEnd];
  });
  expect(selection).toEqual([0, expected.length]);
});

test("/nonprofits explains agent kits, shows every reviewed example and the request form", async ({ page }) => {
  await page.goto("/nonprofits");
  const main = page.locator("main");
  await expect(main).toContainText(
    "An agent kit is a set of nouns and verbs made for your agent: its instructions, skills, knowledge, " +
      "connections, settings, even its working files, plus the checks that prove it works.",
  );
  await expect(main).toContainText("One noun can even hold an agent's whole setup");
  for (const piece of ["Instructions", "Skills", "Knowledge", "Connections", "Settings", "Working files", "Checks and tests", "A step map"]) {
    await expect(main.locator("dt", { hasText: piece }).first()).toBeVisible();
  }

  const kits = page.getByTestId("example-kit");
  await expect(kits).toHaveCount(KIT_IDS.length);
  expect(KIT_IDS.length).toBeGreaterThanOrEqual(5);
  for (let i = 0; i < KIT_IDS.length; i += 1) {
    const stepMap = kits.nth(i).locator("ul.er-stepmap");
    await expect(stepMap.getByText("Person only").first()).toBeVisible();
    await expect(stepMap.getByText(/^Agent (drafts|assists)$/).first()).toBeVisible();
  }
  await expect(page.getByRole("link", { name: "exploitation-evidence pack" })).toHaveAttribute(
    "href",
    "https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs/tree/main/packs/exploitation-evidence",
  );
  await expect(page.getByRole("link", { name: "pack library" })).toHaveAttribute(
    "href",
    "https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs",
  );

  const request = page.getByTestId("request-kit");
  await expect(request.getByRole("note")).toHaveText("Don't include anyone's personal information. Requests are public.");
  await expect(request).toContainText("A volunteer will check your request before it becomes work.");
  await expect(request).toContainText("Kits are reviewed, not certified.");
  await expect(request.getByRole("link", { name: "Request a kit" })).toHaveAttribute("href", REQUEST_KIT_URL);
});

test("/nonprofits shows each kit's need in the organization's words, and the recorded example runs", async ({
  page,
}) => {
  await page.goto("/nonprofits");
  const needs = page.getByTestId("example-need");
  await expect(needs).toHaveCount(examples.needs.length);
  expect(examples.needs.length).toBeGreaterThan(0);
  for (const need of examples.needs) {
    expect(need.mark).toBe("SYNTHETIC");
    expect(need.says.toLowerCase()).not.toContain("request a kit");
    await expect(page.getByTestId("example-kit").filter({ hasText: need.says })).toHaveCount(1);
  }
  const runs = page.getByTestId("example-runs");
  await expect(runs).toHaveText(`${examples.runs.count} ${examples.runs.label}`);
  expect(examples.runs.label).toMatch(/^example runs on .+, synthetic data$/);
});

test("no visible text, title or label names a retired pack", async ({ page }) => {
  for (const route of ROUTES) {
    await page.goto(route);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator("main")).not.toContainText("Loading");
    const text = await page.locator("body").innerText();
    expect(text, route).not.toMatch(OLD_NAMES);
    expect(await page.title(), route).not.toMatch(OLD_NAMES);
    const labels = await page.evaluate(() =>
      Array.from(document.querySelectorAll("[aria-label], [title], [alt], [placeholder]")).flatMap((node) =>
        ["aria-label", "title", "alt", "placeholder"].map((name) => node.getAttribute(name) ?? ""),
      ),
    );
    expect(labels.filter((label) => OLD_NAMES.test(label)), route).toEqual([]);
  }
});

test("the marketplace pages never call agent kits tools", async ({ page }) => {
  for (const route of ["/", "/help", "/nonprofits"]) {
    await page.goto(route);
    await expect(page.locator("main")).not.toContainText("Loading");
    // Open task titles are brief data written by contributors, not page copy, so they are left out.
    const copy = await page.evaluate(() => {
      const body = document.body.cloneNode(true) as HTMLElement;
      body.querySelector('[data-testid="open-tasks"]')?.remove();
      return body.textContent ?? "";
    });
    expect(copy, route).not.toMatch(TOOLS_WORD);
  }
});
