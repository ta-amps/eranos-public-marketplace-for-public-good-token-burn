import { expect, test } from "@playwright/test";

import { LIVE, mockSite } from "./support/mocks";

// Exercise the production-mode bundle, including CSS under the visitor's dark OS setting.
for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`retired surface exclusion (${colorScheme} OS)`, () => {
    test.use({ baseURL: LIVE, colorScheme, viewport: { width: 1262, height: 956 }, reducedMotion: "reduce" });
    for (const route of ["/", "/requests/example?moment=decided"]) {
      test(`${route} remains light and uses the reviewed surface`, async ({ page }) => {
        await mockSite(page);
        await page.goto(route);
        await expect(page.locator('meta[name="color-scheme"]')).toHaveAttribute("content", "light");
        await expect(page.locator("html")).toHaveCSS("color-scheme", "light");
        await expect(page.locator("body")).toHaveCSS("background-color", "rgb(245, 242, 234)");
        if (route.startsWith("/requests/")) {
          const toggles = page.locator('[data-testid^="band-toggle-"]');
          await expect(toggles).toHaveCount(4);
          for (let n = 1; n <= 4; n++) await expect(page.getByTestId(`band-toggle-${n}`)).toBeInViewport();
          const first = page.getByTestId("band-toggle-1");
          await expect(first).toHaveAttribute("aria-expanded", "false");
          await first.focus();
          await page.keyboard.press("Enter");
          await expect(first).toHaveAttribute("aria-expanded", "true");
          await page.keyboard.press("Space");
          await expect(first).toHaveAttribute("aria-expanded", "false");
        }
      });
    }
  });
}
