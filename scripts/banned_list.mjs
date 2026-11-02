// Reads the ONE shared word list (MUST-FOLLOW rule 16) from OUTSIDE this repository, plus Eranos's plain-word
// replacements (also outside it), and writes the gitignored module the Worker's page view imports. No listed word or
// pattern is written into a tracked file, and the module stays in the Worker: it is never sent to a browser.
//
//   node scripts/banned_list.mjs            write deploy/cloudflare/banned_words.generated.js (the deploy's build step)
//   node scripts/banned_list.mjs --check    fail when that module is missing, stale or built from the test fixtures
//   node scripts/banned_list.mjs --ensure   tests and local work: write it when needed; without the shared list on
//                                           this machine, fall back to the made-up fixtures in tests/fixtures
//
// Where the files are: ERANOS_BANNED_WORDS and ERANOS_NEUTRAL_WORDS, or else the first parent folder of this checkout
// that holds coordination-2026-10-31/rules/banned-words.json and claude-work-2026-10-31/eranos-impl/eranos-neutral-words.json.
// A missing list fails every release step; only --ensure may use the fixtures, and a module built from them says so.

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const GENERATED = path.join(ROOT, "deploy/cloudflare/banned_words.generated.js");
const LIST_REL = "coordination-2026-10-31/rules/banned-words.json";
const NEUTRAL_REL = "claude-work-2026-10-31/eranos-impl/eranos-neutral-words.json";
const FIXTURE_LIST = path.join(ROOT, "tests/fixtures/made-up-banned-words.json");
const FIXTURE_NEUTRAL = path.join(ROOT, "tests/fixtures/made-up-neutral-words.json");
const ELLIPSIS = "…";

function findUp(rel) {
  for (let dir = path.dirname(ROOT); ; dir = path.dirname(dir)) {
    const candidate = path.join(dir, rel);
    if (fs.existsSync(candidate)) return candidate;
    if (path.dirname(dir) === dir) return null;
  }
}

function read(file, what) {
  if (!file || !fs.existsSync(file)) throw new Error(`${what} is missing (${file || "not found above this checkout"})`);
  const raw = fs.readFileSync(file, "utf8");
  return { raw, parsed: JSON.parse(raw) };
}

/** The shared list and Eranos's replacements, with a digest of their exact text so a changed list is noticed. */
export function readInputs({ fixtureOk = false } = {}) {
  const override = Boolean(process.env.ERANOS_BANNED_WORDS || process.env.ERANOS_NEUTRAL_WORDS);
  let list;
  let neutral;
  let source = override ? "override" : "shared";
  try {
    list = read(process.env.ERANOS_BANNED_WORDS || findUp(LIST_REL), "the shared word list");
    neutral = read(process.env.ERANOS_NEUTRAL_WORDS || findUp(NEUTRAL_REL), "Eranos's plain-word replacements");
  } catch (error) {
    if (!fixtureOk || override) throw error;
    list = read(FIXTURE_LIST, "the made-up word list");
    neutral = read(FIXTURE_NEUTRAL, "the made-up replacements");
    source = "fixture";
  }
  const digest = crypto.createHash("sha256").update(source).update("\0").update(list.raw).update("\0").update(neutral.raw).digest("hex");
  return { list: list.parsed, neutral: neutral.parsed, digest, source };
}

/** The display rules in the order they run: the extra rules, the list's patterns with a replacement, then an ellipsis. */
export function displayRules(list, neutral) {
  const flags = list?.case_insensitive === false ? "" : "i";
  const take = (group) => (Array.isArray(list?.[group]?.patterns) ? list[group].patterns.map(String) : []);
  const listed = [...take("always"), ...take("visible_text"), ...take("agent_apps_outside_models_page")];
  const rule = (pattern, to) => {
    new RegExp(pattern, flags); // a pattern that does not compile fails the build
    return { re: String(pattern), flags, to };
  };
  const rules = [];
  const used = new Set();
  for (const r of neutral?.rules ?? []) if (r.extra) rules.push(rule(r.pattern, r.to));
  for (const r of neutral?.rules ?? []) {
    if (r.extra || !listed.includes(String(r.pattern))) continue;
    rules.push(rule(r.pattern, r.to));
    used.add(String(r.pattern));
  }
  for (const pattern of listed) if (!used.has(pattern)) rules.push(rule(pattern, ELLIPSIS));
  return rules;
}

/** The list's own patterns by group, for the gates (the extra display rules never add a banned word). */
export function checks(list) {
  const flags = list?.case_insensitive === false ? "" : "i";
  const take = (group) => (Array.isArray(list?.[group]?.patterns) ? list[group].patterns.map(String) : []);
  return [
    ...take("always").map((re) => ({ group: "always", re, flags })),
    ...take("visible_text").map((re) => ({ group: "visible_text", re, flags })),
    ...take("agent_apps_outside_models_page").map((re) => ({ group: "agent_apps_outside_models_page", re, flags })),
  ];
}

function moduleText({ list, neutral, digest, source }) {
  const body = {
    inputs_digest: digest,
    source,
    version: list.version ?? null,
    updated: list.updated ?? null,
    displayRules: displayRules(list, neutral),
    checks: checks(list),
  };
  return (
    "// GENERATED by scripts/banned_list.mjs from the shared word list (MUST-FOLLOW rule 16).\n" +
    "// Gitignored: never commit it. The Worker uses it on its page view only; it is never sent to a browser.\n" +
    `export default Object.freeze(${JSON.stringify(body, null, 1)});\n`
  );
}

function isCurrent(digest) {
  return fs.existsSync(GENERATED) && fs.readFileSync(GENERATED, "utf8").includes(`"inputs_digest": "${digest}"`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.includes("--check")) {
      const { digest, source, list } = readInputs();
      if (source === "fixture" || !isCurrent(digest)) throw new Error("the generated module is missing, stale or built from the fixtures: run node scripts/banned_list.mjs");
      console.log(`word list: the generated module matches the shared list (version ${list.version}, ${list.updated})`);
    } else {
      const inputs = readInputs({ fixtureOk: process.argv.includes("--ensure") });
      if (!process.argv.includes("--ensure") || !isCurrent(inputs.digest)) fs.writeFileSync(GENERATED, moduleText(inputs), "utf8");
      console.log(`word list: ${path.relative(ROOT, GENERATED)} is ready (${inputs.source}, version ${inputs.list.version ?? "?"})`);
    }
  } catch (error) {
    console.error(`word list FAILED: ${error.message}`);
    process.exit(1);
  }
}
