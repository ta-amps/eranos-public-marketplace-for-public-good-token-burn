import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { AdvancedSettings, EMPTY_PREFS, improvedRequest, improving, parsePrefs, prefsBrief, prefsText, type Prefs } from "./AdvancedSettings";
import { flushSync } from "react-dom";

import { FABRIC_PUBLIC_URL, SNAPSHOT } from "../config";
import { loadLibrary, searchLibrary, type LibraryItem } from "../lib/library";
import { fill, type NonprofitsPageNoun } from "../lib/nouns";
import { personalDataKinds } from "../lib/privacy";
import { queueFromFabric } from "../lib/status/live";
import type { FabricResponse } from "../lib/types";
import { useResource } from "../lib/useResource";
import { rememberSent } from "../lib/status/handoff";
import { rememberKey } from "../lib/status/keys";
import { AppLink, navigateWithTransition } from "../router";
import { Icon } from "./Icon";

type Problem =
  | { kind: "refused"; personal: boolean; reason: string; filed: boolean }
  | { kind: "quota"; until: number }
  | { kind: "rate"; until: number }
  | { kind: "offline" };

interface Draft {
  text: string;
  /** The kinds of output chosen, comma separated: "process", "information" or both. */
  output: string;
  frequency: string;
  cadence: string;
  name: string;
  type: string;
  links: string;
  causes: string;
  /** The optional settings, kept as JSON text like the rest of the draft. */
  prefs: string;
}

const DRAFT_KEY = "eranos.request-draft.v1";
const EMPTY: Draft = { text: "", output: "", frequency: "", cadence: "", name: "", type: "", links: "", causes: "", prefs: "" };

/** Library items are read once per visit, for the check before sending. */
let library: Promise<LibraryItem[]> | null = null;

export interface LibraryWords {
  check: { title: string; lead: string; read: string; read_note: string; send: string; send_note: string };
}

// Zero browser storage on Eranos (owner, Nov 1): an unsent request lives only in this tab's memory.
function loadDraft(): Draft {
  return EMPTY;
}

function saveDraft(_draft: Draft): void {
  // Nothing is written to the browser.
}

class SendError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string | undefined,
    readonly retryAfter: number | undefined,
    readonly filed: boolean,
  ) {
    super(message);
  }
}

async function failure(response: Response, filed: boolean): Promise<SendError> {
  let detail = String(response.status);
  let code: string | undefined;
  try {
    const body = (await response.json()) as { detail?: string; code?: string };
    detail = body.detail ?? detail;
    code = body.code;
  } catch {
    // keep the status
  }
  const retry = Number(response.headers.get("retry-after"));
  return new SendError(detail, response.status, code, Number.isFinite(retry) && retry > 0 ? retry : undefined, filed);
}

function frequencyHelp(page: NonprofitsPageNoun, outputs: string[], frequency: string, cadence: string): string {
  const help = page.frequency.help;
  if (!outputs.length || !frequency) return help.none;
  const every = (page.frequency.cadences.find((c) => c.value === cadence)?.label ?? "").toLowerCase();
  const regular = frequency === "recurring";
  return outputs
    .map((kind) => {
      const line = help[`${kind === "process" ? "process" : "information"}_${regular ? "regular" : "once"}` as keyof typeof help];
      return fill(line, { every });
    })
    .join(" ");
}

function clock(at: number): string {
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(at * 1000));
}

/**
 * The request box: what kind of output, how often, and the job in plain words. Every label and line is the
 * `eranos.instructions/nonprofits-page` noun. Sending signs the organization up for a narrow requester key,
 * keeps the request as a noun in its own namespace and files it as one request verb, exactly as before; the
 * brief now also says what kind of output and how often. Then the page opens the request's private link,
 * `/requests/<id>#k=<key>`: the key rides in the fragment, which is never sent to a server.
 */
export function RequestBox({ page, libraryWords }: { page: NonprofitsPageNoun; libraryWords: LibraryWords | null }) {
  const form = page.form;
  const ids = useId();
  const [draft, setDraft] = useState<Draft>(loadDraft);
  const [consent, setConsent] = useState(false);
  const [tried, setTried] = useState(false);
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [online, setOnline] = useState(() => navigator.onLine);
  const [copied, setCopied] = useState(false);
  const [hits, setHits] = useState<LibraryItem[] | null>(null);
  const newRequest = useRef(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const alert = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLFormElement>(null);
  // As before, a key minted in this visit is used again if sending has to be retried.
  const minted = useRef<{ key: string; principal: string; organizationType: string } | null>(null);
  // The live line under Send: real counts from the queue, or nothing when it can't be read.
  const fabric = useResource<FabricResponse>("/api/fabric");
  const queue = !SNAPSHOT && fabric.state.status === "ready" ? queueFromFabric(fabric.state.data.queues) : null;

  useEffect(() => saveDraft(draft), [draft]);

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  useEffect(() => {
    if (problem) alert.current?.focus();
  }, [problem]);

  const waitingUntil = problem && (problem.kind === "quota" || problem.kind === "rate") ? problem.until : 0;
  useEffect(() => {
    if (!waitingUntil) return;
    const timer = window.setTimeout(() => setProblem(null), Math.max(0, waitingUntil * 1000 - Date.now()));
    return () => window.clearTimeout(timer);
  }, [waitingUntil]);

  const set = (field: keyof Draft) => (value: string) => setDraft((current) => ({ ...current, [field]: value }));
  const prefs: Prefs = draft.prefs ? parsePrefs(draft.prefs) : EMPTY_PREFS;
  const setPrefs = (next: Prefs) => set("prefs")(next === EMPTY_PREFS ? "" : JSON.stringify(next));
  // The privacy check reads the main box, every "Other" box and the improvement note together, as you type.
  const flags = personalDataKinds([draft.text, prefsText(prefs, page.advanced)].filter(Boolean).join("\n"));
  const chooseFrequency = (value: string) =>
    setDraft((current) => ({ ...current, frequency: value, cadence: value === "recurring" ? current.cadence || page.frequency.default_cadence : "" }));
  const outputs = draft.output.split(",").filter(Boolean);
  const toggleOutput = (value: string) =>
    set("output")(
      (outputs.includes(value) ? outputs.filter((v) => v !== value) : [...outputs, value])
        .sort((a, b) => page.output.options.findIndex((o) => o.value === a) - page.output.options.findIndex((o) => o.value === b))
        .join(","),
    );
  const missing = {
    output: outputs.length === 0,
    need: draft.text.trim().length < form.min_chars,
    private: flags.length > 0,
    improve: improving(prefs, page.advanced) && !prefs.improve_link.trim(),
    name: draft.name.trim().length < 2,
    type: draft.type.trim().length < 3,
    consent: !consent,
  };
  const unmet = (Object.keys(missing) as (keyof typeof missing)[]).filter((field) => missing[field]);
  const canSend = unmet.length === 0 && online && !sending && !waitingUntil;
  const notReady = (() => {
    const order = ["output", "need", "private", "consent", "name", "type", "improve"] as const;
    const parts = order.filter((field) => missing[field]).map((field) => form.not_ready[field]);
    if (!parts.length) return "";
    const list = parts.length > 1 ? `${parts.slice(0, -1).join(", ")}${form.not_ready.and}${parts[parts.length - 1]}` : parts[0];
    return `${tried ? form.not_ready.lead_after : form.not_ready.lead} ${list}.`;
  })();
  const sendLabel = sending ? form.sending : online ? form.send : form.waiting_connection;

  function pick(example: (typeof form.examples)[number]) {
    setDraft((current) => ({ ...current, text: example.text, output: example.output_type, frequency: example.frequency, cadence: example.cadence ?? "" }));
    setHits(null);
    newRequest.current = false;
    textarea.current?.focus();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTried(true);
    setProblem(null);
    const first = unmet[0];
    if (first) {
      const target = box.current?.querySelector<HTMLElement>(`[data-field="${first === "private" ? "need" : first}"]`);
      target?.focus();
      return;
    }
    if (SNAPSHOT) {
      setProblem({ kind: "refused", personal: false, reason: page.states.snapshot, filed: false });
      return;
    }
    if (!navigator.onLine) {
      setProblem({ kind: "offline" });
      return;
    }
    const text = draft.text.trim();
    const links = draft.links.split(/\s+/).filter((link) => link.startsWith("https://"));
    // The shared library first: work already done needs no new agent work.
    if (!newRequest.current) {
      library ??= loadLibrary();
      const found = searchLibrary(await library.catch(() => []), text).slice(0, 3);
      if (found.length) {
        setHits(found);
        return;
      }
    }
    setHits(null);
    setSending(true);
    let filed = false;
    try {
      if (!minted.current) {
        const signup = await fetch(FABRIC_PUBLIC_URL + "/v1/session/requester", {
          method: "POST",
          credentials: "omit",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            profile: {
              display_name: draft.name,
              organization_type: draft.type,
              causes: draft.causes
                .split(",")
                .map((cause) => cause.trim())
                .filter(Boolean),
            },
          }),
        });
        if (!signup.ok) throw await failure(signup, false);
        const body = (await signup.json()) as { key?: string; principal_id?: string; profile?: { organization_type: string } };
        if (!body.key || !body.principal_id) throw new SendError("no key was returned", 502, undefined, undefined, false);
        minted.current = { key: body.key, principal: body.principal_id, organizationType: body.profile?.organization_type ?? draft.type };
      }
      const token = minted.current.key;
      const organizationType = minted.current.organizationType;
      const outputType = outputs.length > 1 ? "both" : (outputs[0] ?? "");
      const brief = {
        text,
        links,
        organization_type: organizationType,
        output_type: outputType,
        frequency: draft.frequency || "one-off",
        ...(draft.frequency === "recurring" ? { cadence: draft.cadence || page.frequency.default_cadence } : {}),
        ...(prefsBrief(prefs, page.advanced) ? { prefs: prefsBrief(prefs, page.advanced) } : {}),
        ...(improvedRequest(prefs, page.advanced) ? { follows: { request_id: improvedRequest(prefs, page.advanced) } } : {}),
      };
      const taskId = `rq-${minted.current.principal}-${Date.now().toString(36)}`;
      const call = (path: string, body: unknown, shared = false) =>
        fetch(FABRIC_PUBLIC_URL + path, {
          method: "POST",
          credentials: "omit",
          headers: { "content-type": "application/json", authorization: `Bearer ${token}`, ...(shared ? { "x-namespace": "main" } : {}) },
          body: JSON.stringify(body),
        });
      const noun = await call(`/v1/stores/org.requests/records/${taskId}`, { value: { schema_version: 1, ...brief }, expected_version: 0 });
      if (!noun.ok) throw await failure(noun, false);
      filed = true;
      const verb = await call("/v1/tasks", { queue: "eq01", kind: "request", effect_class: "write-internal", task_id: taskId, brief }, true);
      if (!verb.ok) throw await failure(verb, true);
      rememberKey(taskId, token);
      rememberSent(taskId, { text, organization_type: organizationType, output_type: outputType, frequency: draft.frequency || "one-off", sent_at: Date.now() / 1000 });
      setDraft(EMPTY);
      saveDraft(EMPTY);
      navigateWithTransition(`/requests/${encodeURIComponent(taskId)}#k=${token}`, (commit) => flushSync(commit));
    } catch (error) {
      setSending(false);
      if (error instanceof SendError) {
        const now = Date.now() / 1000;
        if (error.status === 503 && error.code === "storage_quota_exhausted") {
          setProblem({ kind: "quota", until: now + (error.retryAfter ?? 3600) });
        } else if (error.status === 429) {
          setProblem({ kind: "rate", until: now + (error.retryAfter ?? 60) });
        } else {
          const personal = /personal|payment|contact/i.test(error.message);
          setProblem({ kind: "refused", personal, reason: error.message, filed: error.filed || filed });
        }
      } else if (!navigator.onLine) {
        setProblem({ kind: "offline" });
      } else {
        setProblem({ kind: "refused", personal: false, reason: error instanceof Error ? error.message : String(error), filed });
      }
      return;
    }
  }

  const kindWords = flags.map((kind) => form.check.kinds[kind] ?? kind);
  const showMissing = (field: keyof typeof missing) => tried && missing[field];

  return (
    <form ref={box} className="er-ask" data-testid="request-box" noValidate onSubmit={(event) => void submit(event)}>
      <fieldset className="er-choice" data-field="output" tabIndex={-1} aria-describedby={showMissing("output") ? `${ids}-output-missing` : `${ids}-output-hint`}>
        <legend>{page.output.legend}</legend>
        <p id={`${ids}-output-hint`} className="er-small">
          {page.output.hint}
        </p>
        <div className="er-choice-options er-choice-cards">
          {page.output.options.map((option) => (
            <label key={option.value} className="er-choice-card">
              <input
                type="checkbox"
                name="output_type"
                value={option.value}
                checked={outputs.includes(option.value)}
                onChange={() => toggleOutput(option.value)}
                aria-describedby={`${ids}-${option.value}-hint`}
              />
              <span className="er-choice-text">
                <span className="er-choice-label">
                  {option.label}
                  {option.tip && (
                    <span className="er-tip">
                      <button type="button" className="er-tip-button" aria-describedby={`${ids}-${option.value}-tip`}>
                        <Icon name="info" size={18} />
                        <span className="er-visually-hidden">{option.tip_label}</span>
                      </button>
                      <span role="tooltip" id={`${ids}-${option.value}-tip`} className="er-tip-text">
                        {option.tip_title && <strong className="er-tip-title">{option.tip_title}</strong>}
                        {option.tip}
                      </span>
                    </span>
                  )}
                </span>
                <span id={`${ids}-${option.value}-hint`} className="er-choice-hint">
                  {option.hint}
                  {option.example && <span className="er-choice-example">{option.example}</span>}
                </span>
              </span>
            </label>
          ))}
        </div>
        {showMissing("output") && (
          <p id={`${ids}-output-missing`} className="er-field-error">
            {form.missing.output}
          </p>
        )}
      </fieldset>

      <fieldset className="er-choice" data-field="frequency" tabIndex={-1}>
        <legend>{page.frequency.legend}</legend>
        <div className="er-choice-options er-choice-pills">
          {page.frequency.options.map((option) => (
            <label key={option.value} className="er-choice-pill">
              <input
                type="radio"
                name="frequency"
                value={option.value}
                checked={draft.frequency === option.value}
                onChange={() => chooseFrequency(option.value)}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
        {draft.frequency === "recurring" && (
          <div className="er-choice-options er-choice-pills er-cadence" role="radiogroup" aria-label={page.frequency.cadence_label}>
            {page.frequency.cadences.map((cadence) => (
              <label key={cadence.value} className="er-choice-pill">
                <input
                  type="radio"
                  name="cadence"
                  value={cadence.value}
                  checked={draft.cadence === cadence.value}
                  onChange={() => set("cadence")(cadence.value)}
                />
                <span>{cadence.label}</span>
              </label>
            ))}
          </div>
        )}
        <p className="er-small" data-testid="frequency-help">
          {frequencyHelp(page, outputs, draft.frequency, draft.cadence)}
        </p>
      </fieldset>

      <div className="er-describe">
        <label htmlFor="need" className="er-describe-label">
          {form.label}
        </label>
        <p id="need-hint" className="er-describe-hint">
          {form.hint}
        </p>
        <textarea
          id="need"
          name="need"
          ref={textarea}
          data-field="need"
          className="er-input er-textarea er-describe-box"
          rows={6}
          dir="auto"
          maxLength={4000}
          value={draft.text}
          placeholder={outputs.length === 1 ? form.placeholders[outputs[0] as "process" | "information"] : outputs.length ? form.placeholders.process : form.placeholders.none}
          aria-describedby={["need-hint", flags.length ? `${ids}-flag` : "", showMissing("need") ? `${ids}-need-missing` : ""].filter(Boolean).join(" ")}
          aria-invalid={showMissing("need") || undefined}
          onChange={(event) => set("text")(event.target.value)}
        />
        {showMissing("need") && (
          <p id={`${ids}-need-missing`} className="er-field-error">
            {form.missing.need}
          </p>
        )}
        <div className="er-examples">
          <span>{form.examples_label}</span>
          {form.examples.map((example) => (
            <button key={example.id} type="button" className="er-example-chip" onClick={() => pick(example)}>
              {example.short}
            </button>
          ))}
        </div>
        <div role="status" aria-live="polite" className="er-describe-checks">
          {flags.length > 0 ? (
            <p id={`${ids}-flag`} className="er-flag" data-testid="personal-data-hint">
              <Icon name="circle-alert" size={20} strokeWidth={2} />
              <span>
                {fill(form.check.lead, { kinds: kindWords.join(form.check.and) })} {form.check.ask}
              </span>
            </p>
          ) : (
            <p className="er-small er-check-line" data-testid="check-line">
              {draft.text.trim() ? form.check.clean : form.check.empty}
            </p>
          )}
          {flags.length > 0 && !outputs.includes("process") && (
            <p className="er-switch" data-testid="switch-to-process">
              <span>{form.switch.text}</span>
              <button type="button" className="er-btn-secondary er-btn-small" onClick={() => toggleOutput("process")}>
                {form.switch.action}
              </button>
            </p>
          )}
        </div>
      </div>

      <AdvancedSettings words={page.advanced} prefs={prefs} onChange={setPrefs} />

      <div className="er-profile">
        <div className="er-field">
          <label htmlFor="name">{form.name_label}</label>
          <input
            id="name"
            name="name"
            data-field="name"
            className="er-input"
            dir="auto"
            maxLength={80}
            autoComplete="organization"
            value={draft.name}
            aria-invalid={showMissing("name") || undefined}
            onChange={(event) => set("name")(event.target.value)}
          />
          {showMissing("name") && <p className="er-field-error">{form.missing.name}</p>}
        </div>
        <div className="er-field">
          <label htmlFor="type">{form.type_label}</label>
          <input
            id="type"
            name="type"
            data-field="type"
            className="er-input"
            dir="auto"
            maxLength={120}
            placeholder={form.type_placeholder}
            value={draft.type}
            aria-invalid={showMissing("type") || undefined}
            onChange={(event) => set("type")(event.target.value)}
          />
          {showMissing("type") && <p className="er-field-error">{form.missing.type}</p>}
        </div>
        <p className="er-small er-profile-note">{form.profile_note}</p>
      </div>

      <label className="er-consent" data-field="consent" tabIndex={-1}>
        <input type="checkbox" name="consent" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
        <span>{form.consent}</span>
      </label>
      {showMissing("consent") && <p className="er-field-error">{form.missing.consent}</p>}

      <details className="er-details er-more-details">
        <summary>{form.details_summary}</summary>
        <div className="er-details-grid">
          <div className="er-field er-span-2">
            <label htmlFor="links">{form.links_label}</label>
            <textarea
              id="links"
              name="links"
              className="er-input er-textarea"
              rows={2}
              dir="auto"
              maxLength={2000}
              aria-describedby="links-hint"
              value={draft.links}
              onChange={(event) => set("links")(event.target.value)}
            />
            <p id="links-hint" className="er-small">
              {form.links_hint}
            </p>
          </div>
          <div className="er-field">
            <label htmlFor="causes">{form.causes_label}</label>
            <input id="causes" name="causes" className="er-input" dir="auto" maxLength={300} value={draft.causes} onChange={(event) => set("causes")(event.target.value)} />
          </div>
        </div>
      </details>

      {problem && (
        <div ref={alert} className={problem.kind === "offline" ? "er-state er-state-info" : "er-state er-state-error"} role="alert" tabIndex={-1} data-testid="request-problem">
          <Icon name={problem.kind === "offline" ? "info" : "circle-alert"} size={20} strokeWidth={2} />
          <div>
            {problem.kind === "refused" && (
              <p>
                {problem.reason === page.states.snapshot ? (
                  page.states.snapshot
                ) : (
                  <>
                    <strong>{page.states.refused.head}</strong>{" "}
                    {problem.personal
                      ? page.states.refused.personal
                      : fill(problem.filed ? page.states.refused.not_filed : page.states.refused.other, { reason: problem.reason })}
                  </>
                )}
              </p>
            )}
            {problem.kind === "quota" && (
              <>
                <p>
                  <strong>{page.states.quota.head}</strong> {fill(page.states.quota.body, { time: clock(problem.until) })}
                </p>
                <button
                  type="button"
                  className="er-btn-secondary"
                  onClick={() =>
                    void navigator.clipboard.writeText(draft.text).then(
                      () => setCopied(true),
                      () => textarea.current?.select(),
                    )
                  }
                >
                  {copied ? page.states.quota.copied : page.states.quota.action}
                </button>
              </>
            )}
            {problem.kind === "rate" && (
              <p>
                <strong>{page.states.rate.head}</strong> {fill(page.states.rate.body, { time: clock(problem.until) })}
              </p>
            )}
            {problem.kind === "offline" && (
              <p>
                <strong>{page.states.offline.head}</strong> {page.states.offline.body}
              </p>
            )}
          </div>
        </div>
      )}
      {!online && !problem && (
        <p className="er-state er-state-info" role="status">
          <Icon name="info" size={20} strokeWidth={2} />
          <span>
            <strong>{page.states.offline.head}</strong> {page.states.offline.body}
          </span>
        </p>
      )}

      {hits && libraryWords && (
        <section className="er-library-check" aria-labelledby={`${ids}-library`} data-testid="library-check" tabIndex={-1}>
          <h2 id={`${ids}-library`}>{libraryWords.check.title}</h2>
          <p className="er-small">{libraryWords.check.lead}</p>
          <ul>
            {hits.map((item) => (
              <li key={item.id}>
                <strong>{item.title}</strong>
                {item.reviewer && <span className="er-small">{item.forWho}</span>}
                <AppLink to={item.href} className="er-btn-primary">
                  {libraryWords.check.read}
                </AppLink>
              </li>
            ))}
          </ul>
          <p className="er-small">{libraryWords.check.read_note}</p>
          <div className="er-actions">
            <button
              type="button"
              className="er-btn-secondary"
              onClick={() => {
                newRequest.current = true;
                box.current?.requestSubmit();
              }}
            >
              {libraryWords.check.send}
            </button>
            <span className="er-small">{libraryWords.check.send_note}</span>
          </div>
        </section>
      )}

      <div className="er-send-row">
        <button type="submit" className="er-btn-primary er-btn-large" aria-disabled={!canSend} disabled={sending}>
          {sendLabel}
        </button>
        <p className="er-send-note" data-testid="send-note">
          {canSend ? form.ready_note : notReady || form.after_send}
        </p>
      </div>
      {queue && (
        <p className="er-small" data-testid="queue-line">
          {fill(form.hosted, { waiting: queue.waiting, working: queue.working + queue.checking })}
        </p>
      )}
    </form>
  );
}
