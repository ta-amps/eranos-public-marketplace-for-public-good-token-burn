import { expect, test } from "@playwright/test";

import { hits, listConfig, loadChecks, pageText, plantable } from "./support/word-gate";

// F1 (review of 8d8f50a): the deploy's word gate once loaded zero patterns, so a listed word planted in the build still
// passed. This runs with the main suite (and in CI, on the made-up fixture list), so the gate can never go empty again
// unnoticed: it must load patterns, fail on a planted listed word, pass a clean page, and fail closed on no patterns.
test("the word gate loads the list, fails on a planted listed word and passes a clean page", async ({ page }) => {
  const { checks } = await loadChecks({ ensure: true });
  expect(checks.length).toBeGreaterThan(0);
  const word = plantable(checks);
  await page.setContent(`<main><h1>Gate check</h1><p>A ${word} sample line.</p></main>`);
  expect(hits(checks, await pageText(page))).not.toEqual([]);
  await page.setContent("<main><h1>Gate check</h1><p>A plain sample line.</p></main>");
  expect(hits(checks, await pageText(page))).toEqual([]);
});

test("the word gate reads the list however the loader wraps it, and fails closed on no patterns", () => {
  const checks = [{ group: "always", re: "zorblat", flags: "i" }];
  expect(listConfig({ default: { checks, source: "fixture" } }).checks).toEqual(checks);
  expect(listConfig({ default: { default: { checks, source: "fixture" } } }).checks).toEqual(checks);
  expect(() => listConfig({ default: { default: { checks: [] } } })).toThrow(/no checks/);
  expect(() => listConfig({ default: {} })).toThrow(/no checks/);
  expect(() => listConfig(null)).toThrow(/no checks/);
});
