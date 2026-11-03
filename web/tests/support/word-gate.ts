import { execFileSync } from "node:child_process";
import fs from "node:fs";

import type { Page } from "@playwright/test";

/**
 * The deploy's word gate (MUST-FOLLOW rules 15 and 16): page text checked against the ONE shared word list. The list
 * is read from outside the repository through the gitignored module scripts/banned_list.mjs writes; a hit is reported
 * by its group and number only, never the word. The gate fails closed: a module with no patterns is an error.
 */
export interface Check {
  group: string;
  re: string;
  flags: string;
}

interface ListModule {
  checks?: Check[];
  source?: string;
}

const ROOT = new URL("../../../", import.meta.url);
const GENERATED = new URL("deploy/cloudflare/banned_words.generated.js", ROOT);

/** The list's patterns. `ensure` writes the module first (from the made-up fixtures where the real list is absent). */
export async function loadChecks({ ensure = false, allowFixture = true } = {}): Promise<{ checks: Check[]; source: string }> {
  if (ensure && !fs.existsSync(GENERATED)) {
    execFileSync("node", [new URL("scripts/banned_list.mjs", ROOT).pathname, "--ensure"], { stdio: "ignore" });
  }
  if (!fs.existsSync(GENERATED)) throw new Error("the word list module is missing: run node scripts/banned_list.mjs");
  const config = listConfig(await import(GENERATED.href));
  if (!allowFixture && config.source === "fixture") throw new Error("the word list module was built from the test fixtures");
  return config;
}

/**
 * The patterns from an imported list module, whichever way the loader wraps its default export (under Playwright's
 * loader it arrives one level down, as default.default). No patterns is an error: an empty gate checks nothing.
 */
export function listConfig(loaded: unknown): { checks: Check[]; source: string } {
  const outer = (loaded as { default?: ListModule & { default?: ListModule } } | null)?.default;
  const config = Array.isArray(outer?.checks) ? outer : outer?.default;
  const checks = config?.checks;
  if (!config || !Array.isArray(checks) || checks.length === 0) throw new Error("the word list module has no checks: the gate would check nothing");
  return { checks, source: config.source ?? "unknown" };
}

/** The display filter this build's Worker will run, from the same generated rules. */
export async function thisBuildsFilter(): Promise<(text: string) => string> {
  const words = await import(new URL("deploy/cloudflare/display_words.js", ROOT).href);
  const makeNeutral = words.makeNeutral ?? words.default?.makeNeutral;
  const outer = (await import(GENERATED.href)).default;
  return makeNeutral(Array.isArray(outer?.displayRules) ? outer : outer?.default);
}

/** A page's text: visible prose (code excluded) for most groups, and all text, attributes included, for "always". */
export function pageText(page: Page): Promise<{ prose: string; all: string }> {
  return page.evaluate(() => {
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
}

/** The checks a text trips, as "group #n". */
export function hits(checks: Check[], text: { prose: string; all: string }): string[] {
  return checks
    .map((check, index) => ({ check, index }))
    .filter(({ check }) => new RegExp(check.re, check.flags.includes("m") ? check.flags : `${check.flags}m`).test(check.group === "always" ? text.all : text.prose))
    .map(({ check, index }) => `${check.group} #${index}`);
}

/** A word the list itself bans, read from its simplest pattern, to plant in a negative control (never written here). */
export function plantable(checks: Check[]): string {
  for (const check of checks) {
    const word = /^(?:\\b)?([A-Za-z]{4,})(?:\\b)?$/.exec(check.re)?.[1];
    if (word) return word;
  }
  throw new Error("no plain word in the list to plant");
}
