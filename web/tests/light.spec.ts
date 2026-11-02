import fs from "node:fs";

import { expect, test } from "@playwright/test";

import { darkPanels } from "./support/light";

// make light-check (MUST-FOLLOW rule 13): every route, under both OS colour schemes, stays light. It fails on any
// element larger than 5% of the viewport with a dark background, on a dark media query in the built CSS, and on a
// color-scheme meta other than "only light" or "light". The deploy's build step runs it next to the release guard.

const ROUTES = ["/", "/help", "/nonprofits", "/library", "/requests", "/requests/example", "/requests/example?moment=your-turn", "/requests/example/result?part=1", "/requests/example-process/result?part=1", "/catalog", "/catalog/KIT-HOTLINE-02", "/contribute", "/tracks", "/fabric", "/about", "/connect", "/privacy", "/terms", "/report", "/no-such-page"];

test("the detector fails an ink panel like the home FAQ that came back", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.setContent(`<body style="margin:0;background:#F5F2EA"><section class="er-safety" style="background:#11161F;color:#F5F2EA;height:332px">Questions people ask</section><a style="display:block;background:#11161F;height:300px">a primary button</a></body>`);
  expect(await page.evaluate(darkPanels)).toEqual(["section.er-safety rgb(17, 22, 31)"]);
});

test("the built CSS has no dark palette, and the scheme is only light", () => {
  const dist = ["dist-light", "dist"].map((d) => new URL(`../${d}/assets/`, import.meta.url)).find((u) => fs.existsSync(u));
  test.skip(!dist, "no build to read");
  const css = fs.readdirSync(dist!).filter((f) => f.endsWith(".css")).map((f) => fs.readFileSync(new URL(f, dist), "utf8")).join("\n");
  expect(css).not.toMatch(/prefers-color-scheme\s*:\s*dark/i);
  const schemes = [...css.matchAll(/color-scheme\s*:\s*([^;}]+)/g)].map((m) => (m[1] ?? "").trim());
  expect(schemes.length).toBeGreaterThan(0);
  for (const s of schemes) expect(["only light", "light only", "light"]).toContain(s);
});

for (const colorScheme of ["light", "dark"] as const) {
  test(`every route stays light with the ${colorScheme} scheme`, async ({ browser }) => {
    test.setTimeout(180_000);
    const context = await browser.newContext({ colorScheme, viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();
    const found: string[] = [];
    for (const route of ROUTES) {
      await page.goto(route);
      await expect(page.locator("main h1").first()).toBeVisible();
      const meta = await page.locator('meta[name="color-scheme"]').getAttribute("content");
      if (meta !== "only light" && meta !== "light") found.push(`${route}: color-scheme meta ${meta}`);
      for (const panel of await page.evaluate(darkPanels)) found.push(`${route}: ${panel}`);
    }
    await context.close();
    expect(found).toEqual([]);
  });
}
