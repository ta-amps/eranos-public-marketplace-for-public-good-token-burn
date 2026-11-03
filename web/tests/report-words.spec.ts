import { expect, test } from "@playwright/test";
import { readableSummary, readableTitle } from "../src/lib/reportWords";

const prefix = "Volunteer center: ";

test.describe("stored report words", () => {
  test("a title cut inside a word ends on the last whole word", () => {
    const body = `${"word ".repeat(23)}without tu`;
    const title = `${prefix}${body}`.padEnd(140, "x").slice(0, 140);
    const shown = readableTitle(title);
    expect(shown.endsWith("…")).toBe(true);
    expect(shown.length).toBeLessThanOrEqual(140);
    expect(title.startsWith(shown.slice(0, -1))).toBe(true);
    expect(title.charAt(shown.length - 1)).toBe(" ");
  });

  test("the question shows when the last word really ended", () => {
    const body = "b".repeat(122);
    const title = `${prefix}${body}`;
    expect(title).toHaveLength(140);
    expect(readableTitle(title, body)).toBe(title);
    expect(readableTitle(title, `${body} and more`)).toBe(`${title}…`);
    expect(readableTitle(title, `${body}more words`).endsWith("…")).toBe(true);
  });

  test("a shorter title stays as stored", () => {
    expect(readableTitle("A short title")).toBe("A short title");
  });

  test("counts of one read as singular", () => {
    expect(readableSummary("6 cited points from 1 public sources. Text.")).toBe("6 cited points from 1 public source. Text.");
    expect(readableSummary("1 cited points from 2 public sources.")).toBe("1 cited point from 2 public sources.");
    expect(readableSummary("11 public sources")).toBe("11 public sources");
  });
});
