// Plain words for stored record text on pages (MUST-FOLLOW rule 16: data a page shows passes the shared word list at
// display time; stored records are never changed). The rules come from the gitignored module that
// scripts/banned_list.mjs builds from the shared list outside this repository, so this file names no listed word.
const ELLIPSIS = "…";

/** Keeps a capital first letter, so a match at the start of a sentence stays one. */
function sameCase(match, to) {
  if (!to || to === ELLIPSIS) return to;
  const first = match.charAt(0);
  const capital = first !== first.toLowerCase();
  return capital && to.charAt(0) === to.charAt(0).toLowerCase() ? to.charAt(0).toUpperCase() + to.slice(1) : to;
}

/**
 * A filter for one configuration, { displayRules: [{ re, flags, to }] }: `to` is the replacement, or an object that
 * maps the lowercase match to it (an unknown match becomes an ellipsis). Only prose changes: a value without
 * whitespace is an id, a key, a link or a digest, and it is returned exactly as stored.
 */
export function makeNeutral(config) {
  const rules = (config?.displayRules ?? []).map((rule) => {
    const flags = String(rule.flags ?? "").includes("g") ? String(rule.flags) : `${rule.flags ?? ""}g`;
    const pick = typeof rule.to === "string" ? () => rule.to : (match) => rule.to?.[match.toLowerCase()] ?? ELLIPSIS;
    return { re: new RegExp(rule.re, flags), to: (match) => sameCase(match, pick(match)) };
  });
  return function neutral(text) {
    const value = String(text);
    if (!rules.length || !/\s/.test(value.trim())) return value;
    let out = value;
    for (const rule of rules) out = out.replace(rule.re, rule.to);
    return out;
  };
}
