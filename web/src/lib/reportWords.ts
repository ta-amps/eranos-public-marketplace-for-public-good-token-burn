/** The stored title limit: a title this long may have been cut by the old pipeline. */
const STORED_TITLE_LIMIT = 140;

/**
 * A stored report title, for reading. Older records were cut at 140 characters, sometimes inside a word. The stored
 * record stays as it is; this shows the title without a broken word, using the full question to tell whether the last
 * word really ended.
 */
export function readableTitle(title: string, question?: string): string {
  if (title.length < STORED_TITLE_LIMIT || title.endsWith("…")) return title;
  const colon = title.indexOf(": ");
  const body = colon >= 0 ? title.slice(colon + 2) : title;
  const at = question ? question.indexOf(body) : -1;
  if (at >= 0) {
    const next = question?.[at + body.length];
    if (next === undefined) return title;
    if (/\s/.test(next)) return `${title.trimEnd()}…`;
  }
  const lastSpace = title.lastIndexOf(" ");
  return `${(lastSpace > 0 ? title.slice(0, lastSpace) : title).replace(/[\s,;:]+$/, "")}…`;
}

/** Older stored summaries always said "points" and "sources"; one of either reads as singular. */
export function readableSummary(summary: string): string {
  return summary.replace(/\b1 cited points\b/g, "1 cited point").replace(/\b1 public sources\b/g, "1 public source");
}
