/**
 * Owner, October 31: "DO NOT INCLUDE SYNTHETIC." The site's own words never say it. Records bound by a digest (an
 * example kit, say) are served exactly as stored, so their digests verify; this page shows their labels in the
 * site's words: "example", and "Practice case: an example, not a real person or case." for a practice case's mark.
 * Quotes, a source's own text and a request's own words are shown verbatim. Display only: nothing is sent back.
 * eranos/visible.py and the Worker hold the same rules.
 */
const CASE_MARK = "Practice case: an example, not a real person or case.";
const RULES: [RegExp, string | ((match: string, word: string) => string)][] = [
  [/SYNTHETIC:\s*/g, `${CASE_MARK} `],
  [/\bSYNTHETIC\b/g, "practice-case"],
  [/synthetic_example/g, "example"],
  [/synthetic_/g, "example_"],
  [/_synthetic\b/g, "_example"],
  [/\bSynthetic (examples?)\b/g, (_match, word) => word.charAt(0).toUpperCase() + word.slice(1)],
  [/\bsynthetic (examples?)\b/g, "$1"],
  [/Synthetic/g, "Example"],
  [/synthetic/gi, "example"],
];
const VERBATIM_KEYS = new Set(["quote", "quotes", "excerpt", "source_text", "text"]);

export function shownText(text: string): string {
  let out = text;
  for (const [pattern, replacement] of RULES) out = out.replace(pattern, replacement as string);
  return out;
}

/** String values in the site's words (keys untouched, verbatim fields untouched). */
export function shownWords<T>(value: T): T {
  if (typeof value === "string") return shownText(value) as T;
  if (Array.isArray(value)) return value.map((item) => shownWords(item)) as T;
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) out[key] = VERBATIM_KEYS.has(key) ? item : shownWords(item);
    return out as T;
  }
  return value;
}
