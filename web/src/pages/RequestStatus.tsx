import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Icon } from "../components/Icon";
import { SNAPSHOT } from "../config";
import { PlainStatus, plainSummary } from "../components/status/PlainStatus";
import { QueuePanel, StateNotice, StatusDiagram, StatusList, StatusLog } from "../components/status/StatusParts";
import { getJson } from "../lib/api";
import { modelName, useModels } from "../lib/models";
import { fill, type RequestStatusNoun } from "../lib/nouns";
import { deriveView, type StatusView } from "../lib/status/derive";
import { exampleNow, exampleRecord, MOMENTS, type RequestExampleNoun } from "../lib/status/example";
import { sentRequest } from "../lib/status/handoff";
import { dropKeyFromAddress, privateLink, requesterKeyFor } from "../lib/status/keys";
import { firstSentence, queueFromFabric, readKeyed, readLive, type KeyedData, type LiveSnapshot } from "../lib/status/live";
import { useStatusMotion } from "../lib/status/motion";
import { REQUEST_ID_RE } from "../lib/status/ids";
import { TesseraError } from "../lib/status/tessera";
import type { QueueSnapshot, StatusRecord } from "../lib/status/types";
import type { FabricResponse } from "../lib/types";
import { REDUCED_MOTION, useMediaQuery } from "../lib/useMediaQuery";
import { useNoun } from "../lib/useNoun";
import { AppLink, useHash, useSearch } from "../router";

export const EXAMPLES: Record<string, string> = { example: "request-example", "example-process": "request-example-process", "REQ-INTAKE-07": "request-example" };
/** Older addresses that now open the example request; the page says plainly that it is an example. */
const EXAMPLE_ALIASES = new Set(["REQ-INTAKE-07"]);

export function formatTime(at: number): string {
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(new Date(at * 1000));
}

export function formatClock(at: number): string {
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(at * 1000));
}

function ago(words: RequestStatusNoun, seconds: number): string {
  if (seconds < 5) return words.modes.ago_now ?? "";
  if (seconds < 60) return fill(words.modes.ago_seconds ?? "", { n: Math.round(seconds) });
  return fill(words.modes.ago_minutes ?? "", { n: Math.round(seconds / 60) });
}

function choiceLine(words: RequestStatusNoun, record: StatusRecord): string | null {
  const output = record.request.output_type ? words.choices.output[record.request.output_type] : null;
  const often = record.request.frequency ? words.choices.frequency[record.request.frequency] : null;
  return [output, often].filter(Boolean).join(" · ") || null;
}

function resultPath(id: string, part: number): string {
  return `/requests/${encodeURIComponent(id)}/result?part=${part}`;
}

interface StatusFrameProps {
  words: RequestStatusNoun;
  record: StatusRecord;
  now: number;
  routeId: string;
  example?: { mark: string; onReplay?: () => void };
  live?: { updated: number | null; paused: { at: number; retryIn: number } | null; onTryNow: () => void; key: string | null; queue: QueueSnapshot | null };
  notices?: React.ReactNode;
}

/** The page around the diagram: title row, mode line, the view, what happened, the queue and the request itself. */
function StatusFrame({ words, record, now, routeId, example, live, notices }: StatusFrameProps) {
  const wide = useMediaQuery("(min-width: 1200px)");
  const reduced = useMediaQuery(REDUCED_MOTION);
  const [view, setView] = useState<"diagram" | "list">("diagram");
  const [copied, setCopied] = useState("");
  const host = useRef<HTMLDivElement>(null);
  const listHost = useRef<HTMLDivElement>(null);
  // The plain view is the default; `?view=technical` (or the switch) shows the diagram, names and receipts.
  const [technical, setTechnical] = useState(() => new URLSearchParams(window.location.search).get("view") === "technical");
  function toggleView() {
    const next = !technical;
    setTechnical(next);
    const url = new URL(window.location.href);
    if (next) url.searchParams.set("view", "technical");
    else url.searchParams.delete("view");
    // The private key never goes back into the address (see dropKeyFromAddress).
    window.history.replaceState(window.history.state, "", url.pathname + url.search);
  }
  // Every recorded step links to the public record that holds it (never to a hash): the example's own noun, or the
  // request's version history in Tessera's public mirror.
  const recordHref = example
    ? `/api/nouns/eranos.instructions/${EXAMPLES[routeId] ?? "request-example"}`
    : `/api/nouns/eranos.requests/${encodeURIComponent(routeId)}/history`;
  // Model names in the details come from the models.meta Task Object, read through the Worker from Tessera.
  const catalog = useModels();
  const derived: StatusView = useMemo(
    () =>
      deriveView(record, words, {
        now,
        formatTime,
        formatClock,
        resultHref: (part) => resultPath(routeId, part),
        modelName: (id, dedicated) => (words.model_names ? modelName(catalog, id, words.model_names, dedicated) : null),
      }),
    [record, words, now, routeId, catalog],
  );
  const every = record.request.frequency === "recurring" ? (words.plain.every[record.request.cadence ?? ""] ?? "") : "";
  const requester = Boolean(live?.key) || Boolean(example);
  const plain = useMemo(() => plainSummary(derived.facts, words.plain, every, requester), [derived.facts, words.plain, every, requester]);
  const showDiagram = wide && view === "diagram";
  useStatusMotion(showDiagram ? host : listHost, record.events, derived, {
    reduced,
    frozen: Boolean(live?.paused) || !technical,
    packetText: words.diagram.packet ?? "",
  });

  useEffect(() => {
    document.title = technical ? derived.docTitle : `${plain.yourTurn ? `${words.plain.ready_title} \u00b7 ` : ""}${words.plain.tab_title}`;
  }, [technical, derived.docTitle, plain.yourTurn, words.plain]);

  const choices = choiceLine(words, record);
  const sent = record.request.sent_at ? fill(words.meta.sent ?? "", { time: formatClock(record.request.sent_at) }) : null;
  const queue = example ? derived.queue : (live?.queue ?? null);

  const [publicCopied, setPublicCopied] = useState(false);
  async function copyPublicLink() {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/requests/${encodeURIComponent(routeId)}`);
      setPublicCopied(true);
      window.setTimeout(() => setPublicCopied(false), 2400);
    } catch {
      setPublicCopied(false);
    }
  }

  async function copyLink() {
    if (!live?.key) return;
    try {
      await navigator.clipboard.writeText(privateLink(window.location.origin, record.request.id, live.key));
      setCopied(words.actions.copied ?? "");
    } catch {
      setCopied(words.actions.copy_failed ?? "");
    }
  }

  return (
    <div className="er-status-page" data-testid="request-status" data-mode={record.mode}>
      <div className="er-status-head">
        <div className="er-status-titles">
          <p className="er-status-meta">
            {!technical ? (
              <>
                {example && <span>{words.meta.example} · </span>}
                <span data-testid="plain-sent">
                  {record.request.sent_at
                    ? fill(live?.key ? words.plain.sent_line_key : words.plain.sent_line, { time: formatClock(record.request.sent_at) })
                    : ""}
                </span>
              </>
            ) : example ? (
              <span>{words.meta.example}</span>
            ) : (
              <>
                {words.meta.request} <span className="er-mono">{derived.shortId}</span>
              </>
            )}
            {technical && sent && <span>· {sent}</span>}
            {technical && choices && <span>· {choices}</span>}
          </p>
          <h1>{derived.title || (example ? words.titles.example : words.titles.yours)}</h1>
        </div>
        <div className="er-status-actions">
          <span className={`er-chip er-overall er-overall-${derived.overall.tone}`} data-motion="overall" data-testid="overall">
            {technical ? derived.overall.label : plain.chip}
          </span>
          <button type="button" className="er-btn-secondary er-btn-small" aria-pressed={technical} onClick={toggleView} data-testid="view-switch">
            {technical ? words.plain.show_simple : words.plain.show_technical}
          </button>
          <button type="button" className="er-btn-secondary" data-testid="copy-public-link" onClick={() => void copyPublicLink()}>
            {publicCopied ? words.plain.copied_link : words.plain.copy_link}
          </button>
          {live?.key && (
            <button type="button" className="er-btn-secondary" data-testid="copy-private-link" onClick={() => void copyLink()}>
              <Icon name="link" size={18} />
              {words.actions.copy_link}
            </button>
          )}
        </div>
      </div>
      {/* The private link's card: stable for the film's recorder, which masks it (the link itself is never shown). */}
      <div data-testid="private-link-card">
        {copied && (
          <p className="er-small" role="status">
            {copied}
          </p>
        )}
        {!technical && live?.key && (
          <p className="er-small" data-testid="private-line">
            {words.plain.private_line}
          </p>
        )}
      </div>

      {!technical && (
        <PlainStatus
          summary={plain}
          facts={derived.facts}
          events={record.events}
          words={words.plain}
          clock={formatClock}
          shareUrl={`${window.location.origin}/requests/${encodeURIComponent(routeId)}`}
          routeId={routeId}
          requester={requester}
          settled={record.mode !== "live" || Boolean(live?.updated)}
        />
      )}

      {technical && (
      <section className="er-live" aria-label={words.diagram.label}>
        <div className="er-live-bar">
          <p className="er-mode-line" data-testid="mode-line">
            {example ? (
              <>
                <span className="er-live-dot er-live-dot-example" aria-hidden="true" />
                <strong>{words.titles.example}</strong> · {words.modes.example}
              </>
            ) : (
              <>
                <span className={live?.paused ? "er-live-dot er-live-dot-paused" : "er-live-dot"} aria-hidden="true" />
                <strong>{words.modes.live}</strong>
                {live?.updated ? ` · ${fill(words.modes.updated ?? "", { ago: ago(words, now - live.updated) })}` : ""} ·{" "}
                {words.modes.rule}
              </>
            )}
          </p>
          <div className="er-live-tools">
            {wide && (
              <div className="er-segmented" role="group" aria-label={words.actions.view_label}>
                <button type="button" aria-pressed={view === "diagram"} onClick={() => setView("diagram")}>
                  {words.actions.diagram}
                </button>
                <button type="button" aria-pressed={view === "list"} onClick={() => setView("list")}>
                  {words.actions.list}
                </button>
              </div>
            )}
            {example?.onReplay && (
              <button type="button" className="er-btn-secondary er-btn-small" onClick={example.onReplay}>
                {words.actions.replay}
              </button>
            )}
          </div>
        </div>
        {showDiagram ? (
          <StatusDiagram view={derived} words={words} now={now} host={host} />
        ) : (
          <div ref={listHost}>
            <StatusList view={derived} words={words} recordHref={recordHref} />
          </div>
        )}
        <p className="er-visually-hidden" aria-live="polite" data-testid="live-summary">
          {derived.summary}
        </p>
        <div className="er-legend" data-testid="legend">
          <p className="er-legend-title">{words.legend.title}</p>
          <ul>
            {words.legend.items.map((item) => (
              <li key={item.state}>
                <span className={`er-legend-swatch er-node-${item.state}`} aria-hidden="true" />
                {item.text}
              </li>
            ))}
          </ul>
          <p className="er-small">{words.legend.motion}</p>
        </div>
      </section>
      )}

      {notices}

      {technical && <AddedPanel view={derived} words={words} routeId={routeId} example={Boolean(example)} />}

      <div className={technical ? "er-status-lower" : "er-status-lower er-status-lower-plain"}>
        {technical && <StatusLog rows={derived.log} words={words} formatTime={formatTime} recordHref={recordHref} />}
        <aside className="er-status-side">
          {technical && queue && <QueuePanel queue={queue} words={words} showAgents={Boolean(example)} />}
          <section className="er-panel">
            <h2 className="er-panel-title">{words.about.as_sent}</h2>
            <p>{record.request.text ?? words.about.removed}</p>
            {record.request.text && <p className="er-small">{words.about.public_note}</p>}
          </section>
          <section className="er-panel">
            <h2 className="er-panel-title">{words.about.how_title}</h2>
            <p className="er-small">{words.about.how_body}</p>
            {!example && <p className="er-small">{words.about.unseen}</p>}
            <p className="er-small">{words.about.legal}</p>
          </section>
          <AppLink to={`/library?request=${encodeURIComponent(routeId)}`} className="er-text-link">
            {words.library_link} →
          </AppLink>
          {example && <p className="er-small">{words.log.models_note}</p>}
        </aside>
      </div>
    </div>
  );
}

/**
 * "Added to the shared library": once a part is delivered or published, what it made, as task objects and tasks.
 * Every link opens a public record that exists: the report or kit, the request and plan records (or, for the
 * example, its result page and its own record).
 */
function AddedPanel({ view, words, routeId, example }: { view: StatusView; words: RequestStatusNoun; routeId: string; example: boolean }) {
  const done = view.facts.parts.filter((p) => p.result === "noun" && (p.decide === "yourturn" || p.decide === "decided" || p.library));
  if (!done.length) return null;
  const a = words.added;
  // The hosted site answers /api/nouns/...; a static copy of the site carries the same nouns as files.
  const nounHref = (store: string, key: string) =>
    SNAPSHOT ? `/snapshot/nouns/${store}/${encodeURIComponent(key)}.json` : `/api/nouns/${store}/${encodeURIComponent(key)}`;
  const objects: { label: string; href: string }[] = [];
  const tasks: { label: string; href: string }[] = [];
  for (const part of done) {
    const n = part.plan.part;
    const result = part.resultEvidence?.id ?? part.library?.id ?? part.plan.report_id ?? part.plan.kit_id ?? "";
    if (!result) continue;
    const resultPage = `/requests/${encodeURIComponent(routeId)}/result?part=${n}`;
    if (part.plan.route === "private-files" || part.plan.route === "process" || part.plan.output_type === "process") {
      objects.push({ label: fill(a.kit ?? "", { id: result }), href: example ? resultPage : `/catalog/${encodeURIComponent(result)}` });
      tasks.push({ label: fill(a.run ?? "", { id: result }), href: resultPage });
    } else {
      objects.push({ label: fill(a.report ?? "", { id: result }), href: example ? resultPage : nounHref("eranos.solutions", result) });
    }
  }
  if (example) {
    objects.push({ label: fill(a.request ?? "", { short: view.shortId }), href: nounHref("eranos.instructions", EXAMPLES[routeId] ?? "request-example") });
  } else {
    objects.push({ label: fill(a.request ?? "", { short: view.shortId }), href: nounHref("eranos.requests", view.id) });
    objects.push({ label: fill(a.plan ?? "", { short: view.shortId }), href: nounHref("eranos.plans", view.id) });
  }
  return (
    <section className="er-panel er-added" aria-labelledby="added-title" data-testid="added-panel">
      <h2 id="added-title" className="er-panel-title">
        {a.title}
      </h2>
      <p className="er-small">{a.lead}</p>
      <div className="er-stored-columns">
        {([
          [a.objects, objects],
          [a.tasks, tasks],
        ] as const).map(([title, items]) =>
          items.length ? (
            <div key={title}>
              <h3>{title}</h3>
              <ul>
                {items.map((item) => (
                  <li key={item.label}>
                    {item.href.startsWith("/requests/") || item.href.startsWith("/catalog/") ? (
                      <AppLink to={item.href}>{item.label}</AppLink>
                    ) : (
                      <a href={item.href}>{item.label}</a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null,
        )}
      </div>
      <p className="er-small">{a.record_note}</p>
    </section>
  );
}

/** `/requests/example`: the example request, replayed at reading speed. `?moment=` holds one of six moments. */
function ExampleStatus({ words, routeId }: { words: RequestStatusNoun; routeId: string }) {
  const noun = useNoun<RequestExampleNoun>(EXAMPLES[routeId] ?? "request-example").value;
  const search = useSearch();
  const hash = useHash();
  const params = new URLSearchParams(search);
  const moment = params.get("moment") ?? (hash === "#step-ready" ? "your-turn" : null);
  const speed = Math.min(4, Math.max(0.1, Number(params.get("speed")) || 1));
  const replayable = params.get("replay") !== "0";
  // A moment page opens on that moment's facts from its first render, so the track shows only the last hop.
  const momentCount = noun && moment && (MOMENTS as readonly string[]).includes(moment) ? (noun.moments[moment] ?? noun.events.length) : null;
  const [count, setCount] = useState(1);
  const [run, setRun] = useState(0);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    if (!noun) return;
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
    if (moment && (MOMENTS as readonly string[]).includes(moment)) {
      setCount(noun.moments[moment] ?? noun.events.length);
      return;
    }
    setCount(1);
    noun.events.forEach((event, index) => {
      if (index === 0) return;
      timers.current.push(window.setTimeout(() => setCount(index + 1), (event.replay_ms ?? index * 1500) / speed));
    });
    return () => timers.current.forEach((t) => window.clearTimeout(t));
  }, [noun, moment, speed, run]);

  const record = useMemo(() => (noun ? exampleRecord(noun, momentCount ?? count) : null), [noun, count, momentCount]);
  if (!noun || !record) return null;
  return (
    <StatusFrame
      words={words}
      record={record}
      now={exampleNow(noun, momentCount ?? count)}
      routeId={routeId}
      example={{ mark: noun.mark, onReplay: replayable && !moment ? () => setRun((n) => n + 1) : undefined }}
      notices={
        EXAMPLE_ALIASES.has(routeId) ? (
          <div className="er-notices">
            <StateNotice tone="info" head={words.notices.example_alias?.head ?? ""} body={words.notices.example_alias?.body} testId="notice-example-alias" />
          </div>
        ) : null
      }
    />
  );
}

const VISIBLE_MS = 5_000;
const HIDDEN_MS = 30_000;
// The requester key's claim events: at most one long poll every 15 s, only while the tab is visible; the task and
// the key's own nouns every 5 minutes.
const EVENTS_MS = 15_000;
const FULL_MS = 300_000;
const PAUSE_MS = 30_000;

/** A real request: public nouns every 5 s (30 s in a hidden tab), the requester key's view of its verb every 60 s. */
function LiveStatus({ id, words }: { id: string; words: RequestStatusNoun }) {
  const [key] = useState(() => requesterKeyFor(id, window.location.hash));
  useEffect(() => dropKeyFromAddress(id), [id]);
  const [snapshot, setSnapshot] = useState<LiveSnapshot | null>(null);
  const [updated, setUpdated] = useState<number | null>(null);
  const [pausedAt, setPausedAt] = useState<number | null>(null);
  const [queue, setQueue] = useState<QueueSnapshot | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);
  const [tick, setTick] = useState(0);
  const keyed = useRef<KeyedData | null>(null);
  const lastKeyed = useRef(0);
  const lastFull = useRef(0);
  const failures = useRef(0);
  const notBefore = useRef(0);

  const poll = useCallback(async () => {
    if (Date.now() < notBefore.current) return;
    try {
      const visible = document.visibilityState === "visible";
      if (key && (keyed.current === null || (visible && Date.now() - lastKeyed.current >= EVENTS_MS))) {
        const full = keyed.current === null || Date.now() - lastFull.current >= FULL_MS;
        lastKeyed.current = Date.now();
        keyed.current = await readKeyed(id, key, keyed.current, full, full ? 0 : 15);
        if (full) lastFull.current = Date.now();
      }
      const snap = await readLive(id, keyed.current);
      setSnapshot(snap);
      setUpdated(Date.now() / 1000);
      failures.current = 0;
      setPausedAt(null);
      try {
        const fabric = await getJson<FabricResponse>("/api/fabric");
        setQueue(queueFromFabric(fabric.queues));
      } catch {
        setQueue(null);
      }
    } catch (error) {
      if (error instanceof TesseraError && error.retryAfter) notBefore.current = Date.now() + error.retryAfter * 1000;
      failures.current += 1;
      if (failures.current >= 3) setPausedAt((at) => at ?? Date.now() / 1000);
    }
  }, [id, key]);

  useEffect(() => {
    let timer = 0;
    let stopped = false;
    const run = async () => {
      await poll();
      if (stopped) return;
      const delay = failures.current >= 3 ? PAUSE_MS : document.visibilityState === "visible" ? VISIBLE_MS : HIDDEN_MS;
      timer = window.setTimeout(() => void run(), delay);
    };
    void run();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [poll, tick]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);

  function tryNow() {
    failures.current = 0;
    notBefore.current = 0;
    lastKeyed.current = 0;
    lastFull.current = 0;
    setPausedAt(null);
    setTick((n) => n + 1);
  }

  if (!REQUEST_ID_RE.test(id)) {
    return (
      <div className="er-status-page">
        <StateNotice
          tone="info"
          head={fill(words.notices.unknown?.head ?? "", { id })}
          body={words.notices.unknown?.body}
          action={
            <AppLink to="/nonprofits" className="er-btn-secondary">
              {words.notices.unknown?.action}
            </AppLink>
          }
          testId="notice-unknown"
        />
      </div>
    );
  }

  const handoff = sentRequest(id);
  const record: StatusRecord = snapshot?.record ?? {
    mode: "live",
    request: {
      id,
      text: handoff?.text,
      title: handoff ? firstSentence(handoff.text) : undefined,
      organization_type: handoff?.organization_type,
      output_type: handoff?.output_type as StatusRecord["request"]["output_type"],
      frequency: handoff?.frequency as StatusRecord["request"]["frequency"],
      sent_at: handoff?.sent_at ?? null,
    },
    events: [{ type: "received", at: handoff?.sent_at ?? null, ref: id }],
  };
  if (handoff && record.request.output_type === undefined) {
    record.request.output_type = handoff.output_type as StatusRecord["request"]["output_type"];
    record.request.frequency = handoff.frequency as StatusRecord["request"]["frequency"];
  }

  const missing = snapshot?.missing ?? false;
  const notices: React.ReactNode[] = [];
  if (pausedAt) {
    notices.push(
      <StateNotice
        key="paused"
        tone="info"
        head={words.notices.paused?.head ?? ""}
        body={fill(words.notices.paused?.body ?? "", { time: formatClock(pausedAt), n: PAUSE_MS / 1000 })}
        action={
          <button type="button" className="er-btn-secondary" onClick={tryNow}>
            {words.notices.paused?.action}
          </button>
        }
        testId="notice-paused"
      />,
    );
  }
  if (!key && missing) {
    notices.push(<StateNotice key="key" tone="info" head={words.notices.key_missing?.head ?? ""} body={words.notices.key_missing?.body} testId="notice-key-missing" />);
  } else if (!key) {
    notices.push(<StateNotice key="ro" tone="info" head={words.notices.read_only?.head ?? ""} body={words.notices.read_only?.body} testId="notice-read-only" />);
  }
  const facts = snapshot ? deriveView(record, words, { now, formatTime, formatClock, resultHref: (p) => resultPath(id, p) }).facts : null;
  if (facts?.blocked) {
    const personal = facts.blocked.findings.some((f) => /personal|contact|email|phone|address|number/i.test(f));
    notices.push(
      <StateNotice
        key="blocked"
        tone="error"
        head={words.notices.blocked?.head ?? ""}
        body={personal ? words.notices.blocked?.personal : words.notices.blocked?.scope}
        action={
          <AppLink to="/nonprofits" className="er-btn-secondary">
            {words.notices.blocked?.action}
          </AppLink>
        }
        testId="notice-blocked"
      />,
    );
  }
  for (const part of facts?.parts ?? []) {
    if (part.check === "sent_back") {
      notices.push(
        <StateNotice key={`sb-${part.plan.part}`} tone="error" head={fill(words.notices.sent_back?.head ?? "", { reason: part.checkEvidence?.reason ?? "" })} body={words.notices.sent_back?.body} testId="notice-sent-back" />,
      );
    }
    if (part.decide === "person") {
      notices.push(<StateNotice key={`so-${part.plan.part}`} tone="turn" head={words.notices.signoff?.head ?? ""} body={words.notices.signoff?.body} testId="notice-signoff" />);
    }
    if (part.released && part.work !== "working") {
      notices.push(
        part.released.reason && words.notices.released_reason ? (
          <StateNotice
            key={`rl-${part.plan.part}`}
            tone="error"
            head={fill(words.notices.released_reason.head ?? "", {
              who: part.released.who ?? words.chips.agent ?? "",
              reason: part.released.reason,
            })}
            body={words.notices.released_reason.body}
            testId="notice-released"
          />
        ) : (
          <StateNotice
            key={`rl-${part.plan.part}`}
            tone="wait"
            head={fill(words.notices.released?.head ?? "", { who: part.released.who ?? words.chips.agent ?? "" })}
            body={words.notices.released?.body}
            testId="notice-released"
          />
        ),
      );
    }
  }
  if (facts?.withdrawn) {
    notices.push(
      <StateNotice key="wd" tone="info" head={fill(words.notices.withdrawn?.head ?? "", { date: facts.withdrawn.at ? new Date(facts.withdrawn.at * 1000).toLocaleDateString("en-US") : "" })} body={words.notices.withdrawn?.body} testId="notice-withdrawn" />,
    );
  }
  if (facts && facts.plan === "waiting" && !pausedAt) {
    const line = queue ? fill(words.about.live_line ?? "", { waiting: queue.waiting, working: queue.working + queue.checking }) : "";
    notices.push(<StateNotice key="hosted" tone="wait" head={words.about.hosted ?? ""} body={line} testId="notice-hosted" />);
  }

  return (
    <StatusFrame
      words={words}
      record={record}
      now={now}
      routeId={id}
      live={{ updated, paused: pausedAt ? { at: pausedAt, retryIn: PAUSE_MS / 1000 } : null, onTryNow: tryNow, key, queue }}
      notices={notices.length ? <div className="er-notices">{notices}</div> : null}
    />
  );
}

/** `/requests/<id>`: a real request's private or public status page, or `/requests/example`. */
export function RequestStatus({ id }: { id: string }) {
  const words = useNoun<RequestStatusNoun>("request-status").value;
  if (!words) return null;
  if (EXAMPLES[id]) return <ExampleStatus words={words} routeId={id} />;
  return <LiveStatus id={id} words={words} />;
}
