import { useEffect, useState } from "react";

import { fill, type AdvancedQuestion, type AdvancedWords } from "../lib/nouns";
import { getJson } from "../lib/api";
import { firstSentence } from "../lib/status/live";
import { shortRequestId } from "../lib/status/receipts";

/** The request's optional settings, as they ride in its public brief. */
export interface Prefs {
  start: string;
  skill: string;
  runs: string[];
  agents: string[];
  models: string[];
  tools: string[];
  limits: string[];
  other: Partial<Record<AdvancedQuestion["id"], string>>;
  improve_link: string;
  improve_what: string;
}

export const EMPTY_PREFS: Prefs = {
  start: "",
  skill: "",
  runs: [],
  agents: [],
  models: [],
  tools: [],
  limits: [],
  other: {},
  improve_link: "",
  improve_what: "",
};

type ListField = "runs" | "agents" | "models" | "tools" | "limits";
const LIST_FIELDS: ListField[] = ["runs", "agents", "models", "tools", "limits"];

export function parsePrefs(raw: string): Prefs {
  try {
    const found = JSON.parse(raw) as Partial<Prefs>;
    const out: Prefs = { ...EMPTY_PREFS, other: { ...(found.other ?? {}) } };
    if (typeof found.start === "string") out.start = found.start;
    if (typeof found.skill === "string") out.skill = found.skill;
    for (const field of LIST_FIELDS) if (Array.isArray(found[field])) out[field] = found[field].filter((v) => typeof v === "string");
    if (typeof found.improve_link === "string") out.improve_link = found.improve_link;
    if (typeof found.improve_what === "string") out.improve_what = found.improve_what;
    return out;
  } catch {
    return EMPTY_PREFS;
  }
}

export function improving(prefs: Prefs, words: AdvancedWords): boolean {
  return prefs.start === words.improve.value;
}

/** How many choices the person made; the default "Something new" is not one. */
export function prefsCount(prefs: Prefs, words: AdvancedWords): number {
  const others = Object.values(prefs.other).filter((text) => text && text.trim()).length;
  return (improving(prefs, words) ? 1 : 0) + (prefs.skill ? 1 : 0) + LIST_FIELDS.reduce((n, f) => n + prefs[f].length, 0) + others;
}

/** Everything typed into the settings, for the same privacy check as the main box. */
export function prefsText(prefs: Prefs, words: AdvancedWords): string {
  return [...Object.values(prefs.other), improving(prefs, words) ? prefs.improve_what : ""].filter(Boolean).join("\n");
}

/** The settings as they go into the brief: only what was chosen. */
export function prefsBrief(prefs: Prefs, words: AdvancedWords): Record<string, unknown> | null {
  if (!prefsCount(prefs, words)) return null;
  const other = Object.fromEntries(Object.entries(prefs.other).filter(([, text]) => text && text.trim()).map(([k, text]) => [k, (text ?? "").trim()]));
  return {
    start: prefs.start || words.questions[0]?.default || "",
    ...(prefs.skill ? { skill: prefs.skill } : {}),
    ...Object.fromEntries(LIST_FIELDS.filter((f) => prefs[f].length).map((f) => [f, prefs[f]])),
    ...(Object.keys(other).length ? { other } : {}),
    ...(improving(prefs, words) ? { improve_link: prefs.improve_link.trim(), improve_what: prefs.improve_what.trim() } : {}),
  };
}

/** The earlier request an improvement points at, when its link is an Eranos request page. */
export function improvedRequest(prefs: Prefs, words: AdvancedWords): string | null {
  if (!improving(prefs, words)) return null;
  return /\/requests\/(rq-r_[0-9a-f]{32}-[0-9a-z]+)/.exec(prefs.improve_link)?.[1] ?? null;
}

function OtherBox({ question, words, value, onChange }: { question: AdvancedQuestion; words: AdvancedWords; value: string; onChange: (text: string) => void }) {
  const [open, setOpen] = useState(Boolean(value));
  const text = value.trim();
  const label = text ? fill(words.other.chosen, { text: text.length > 24 ? `${text.slice(0, 22)}…` : text }) : open ? words.other.open : words.other.button;
  return (
    <>
      <button type="button" className={text ? "er-choice-pill er-pill-on" : "er-choice-pill"} aria-expanded={open} onClick={() => setOpen(!open)}>
        {label}
      </button>
      {open && (
        <input
          className="er-input er-other-input"
          type="text"
          maxLength={200}
          value={value}
          placeholder={words.other.placeholder}
          aria-label={fill(words.other.aria, { question: question.label })}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </>
  );
}

export function AdvancedSettings({ words, prefs, onChange }: { words: AdvancedWords; prefs: Prefs; onChange: (prefs: Prefs) => void }) {
  const count = prefsCount(prefs, words);
  const origin = window.location.origin;
  // "Or pick a recent public request": requests are public, so the recent ones come from their public records.
  const [recent, setRecent] = useState<{ id: string; title: string; sentAt: number | null }[] | null>(null);
  const improvingNow = improving(prefs, words);
  // Open when the page starts as an improvement (a library link), so the earlier solution's link is in view.
  const [open, setOpen] = useState(improvingNow);
  useEffect(() => {
    if (!improvingNow || recent !== null) return;
    getJson<{ records?: { key: string; value?: { text?: string } }[] }>("/api/nouns/eranos.requests")
      .then((list) =>
        setRecent(
          (list.records ?? [])
            .filter((record) => /^rq-r_[0-9a-f]{32}-[0-9a-z]+$/.test(record.key))
            .map((record) => {
              const sent = parseInt(record.key.slice(record.key.lastIndexOf("-") + 1), 36);
              return { id: record.key, title: firstSentence(record.value?.text ?? "") || shortRequestId(record.key), sentAt: Number.isFinite(sent) ? sent : null };
            })
            .sort((x, y) => (y.sentAt ?? 0) - (x.sentAt ?? 0))
            .slice(0, 4),
        ),
      )
      .catch(() => setRecent([]));
  }, [improvingNow, recent]);
  const choose = (question: AdvancedQuestion, option: string) => {
    if (question.id === "start") return onChange({ ...prefs, start: option });
    if (question.id === "skill") return onChange({ ...prefs, skill: prefs.skill === option ? "" : option });
    const field = question.id as ListField;
    const list = prefs[field];
    onChange({ ...prefs, [field]: list.includes(option) ? list.filter((v) => v !== option) : [...list, option] });
  };
  const chosen = (question: AdvancedQuestion, option: string) =>
    question.id === "start"
      ? (prefs.start || question.default) === option
      : question.id === "skill"
        ? prefs.skill === option
        : prefs[question.id as ListField].includes(option);

  return (
    <details className="er-details er-advanced" data-testid="advanced-settings" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        <span className="er-advanced-title">{words.summary}</span> <span className="er-small">{words.optional}</span>{" "}
        <span className="er-chip er-chip-noun" data-testid="advanced-count">
          {count ? fill(words.count_some, { n: count }) : words.count_none}
        </span>
      </summary>
      <p className="er-small">{words.intro}</p>
      {words.questions.map((question) => (
        <fieldset key={question.id} className="er-adv-question" data-question={question.id}>
          <legend>
            {question.label} {question.id !== "start" && <span className="er-small">{question.pick === "one" ? words.pick_one : words.pick_any}</span>}
          </legend>
          <div className="er-choice-options er-choice-pills">
            {question.options.map((option) => (
              <label key={option} className="er-choice-pill">
                <input
                  type={question.pick === "one" ? "radio" : "checkbox"}
                  name={`adv-${question.id}`}
                  checked={chosen(question, option)}
                  onChange={() => choose(question, option)}
                />
                <span>{option}</span>
              </label>
            ))}
            {question.other !== false && (
              <OtherBox
                question={question}
                words={words}
                value={prefs.other[question.id] ?? ""}
                onChange={(text) => onChange({ ...prefs, other: { ...prefs.other, [question.id]: text } })}
              />
            )}
          </div>
          {question.id === "start" && improving(prefs, words) && (
            <div className="er-improve" data-testid="improve-panel">
              <div className="er-field">
                <label htmlFor="improve-link">{words.improve.link_label}</label>
                <input
                  id="improve-link"
                  className="er-input"
                  type="url"
                  data-field="improve"
                  value={prefs.improve_link}
                  placeholder={words.improve.link_placeholder}
                  onChange={(event) => onChange({ ...prefs, improve_link: event.target.value })}
                />
              </div>
              <div className="er-field">
                <label htmlFor="improve-what">{words.improve.what_label}</label>
                <input
                  id="improve-what"
                  className="er-input"
                  type="text"
                  maxLength={600}
                  value={prefs.improve_what}
                  placeholder={words.improve.what_placeholder}
                  onChange={(event) => onChange({ ...prefs, improve_what: event.target.value })}
                />
              </div>
              <p className="er-small">{words.improve.recent_label}</p>
              {recent && recent.length ? (
                <div className="er-examples">
                  {recent.map((saved) => (
                    <button
                      key={saved.id}
                      type="button"
                      className="er-example-chip"
                      onClick={() => onChange({ ...prefs, improve_link: `${origin}/requests/${saved.id}` })}
                    >
                      {saved.title.length > 40 ? `${saved.title.slice(0, 38)}\u2026` : saved.title}
                      {saved.sentAt ? ` · ${new Date(saved.sentAt).toLocaleDateString(undefined, { month: "short", day: "numeric" })}` : ""}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="er-small">{words.improve.recent_none}</p>
              )}
            </div>
          )}
        </fieldset>
      ))}
      <p className="er-small">{words.footer}</p>
      <button type="button" className="er-btn-secondary er-btn-small" onClick={() => onChange(EMPTY_PREFS)}>
        {words.clear}
      </button>
    </details>
  );
}
