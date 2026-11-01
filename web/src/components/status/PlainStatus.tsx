import { useEffect, useRef, useState } from "react";

import { AGORA_HOW_IT_WORKS_URL } from "../../lib/marketplace";
import { fill, type PlainWords } from "../../lib/nouns";
import { applyEvents, type Facts } from "../../lib/status/derive";
import { ordinal } from "../../lib/status/estimate";
import type { StatusEvent } from "../../lib/status/types";
import { AppLink, useHash } from "../../router";

/**
 * The request page's plain view (RequestStatusPage v6, Claude Design 20:15): a progress strip and four bands, in
 * plain words. No volunteer names, ids or receipts; those stay in the technical view. Every line is read from the
 * same recorded facts as the diagram, so the two views never disagree.
 */

type StageState = "done" | "now" | "upcoming";
type Kind = "process" | "information";
type Part = Facts["parts"][number];

/** A task nobody claims within this time goes to one of Eranos's own workers ("volunteers first"). */
const FALLBACK_SECONDS = 90;

function kindOf(part: Part): Kind {
  const declared = part.plan.output_type;
  if (declared === "process" || declared === "information") return declared;
  if (part.plan.route === "reused") {
    const from = (part.plan as { reused_from?: { kind?: string } }).reused_from;
    return from?.kind === "report" ? "information" : "process";
  }
  return part.plan.route === "private-files" ? "process" : "information";
}

/** A date and time for a run that may be days away. */
function when(at: number): string {
  return new Date(at * 1000).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** The first sentence of a worker's reason, short enough for one line. */
function shortReason(reason: string): string {
  const first = reason.split(/(?<=[.!?])\s/)[0] ?? reason;
  return first.length > 140 ? `${first.slice(0, 138)}\u2026` : first;
}

/** True when one of Eranos's own (dedicated) workers recorded the fact: its flag, or else its label. */
function byEranos(event: StatusEvent): boolean {
  return event.dedicated ?? /^eranos[-_.\s]/i.test(event.worker ?? "");
}

/** Where a reused answer came from: its catalog page, or the public record that holds it. */
function sourceHref(event: StatusEvent): string | null {
  if (/^(KIT|PRC)-/.test(event.result_id ?? "")) return `/catalog/${encodeURIComponent(event.result_id ?? "")}`;
  const ref = /^(eranos\.[a-z_.]+)\/([A-Za-z0-9][A-Za-z0-9_.:-]*)/.exec(event.ref ?? "");
  return ref ? `/api/nouns/${ref[1]}/${encodeURIComponent(ref[2] ?? "")}` : null;
}

/** A part is being remade after the requester asked for changes, until a new check approves it. */
function changing(part: Part): boolean {
  return part.decision?.choice === "changes" && part.decide !== "yourturn";
}

export interface PlainSummary {
  /** The four bands' states (sorted, made, checked, ready), in order. */
  bands: StageState[];
  /** The request track (owner v2, Nov 1): one station and its tone, the one source for the token and aria-current. */
  track: TrackState;
  chip: string;
  waiting: boolean;
  yourTurn: boolean;
}

/** wait: in line, or a person's turn to wait for; work: someone is on it; turn: a person decides; done: delivered. */
export type TrackTone = "wait" | "work" | "turn" | "done";
export interface TrackState {
  at: number;
  tone: TrackTone;
  /** True when the request is back at "Being made": a check sent it back, or the team asked for changes. */
  back: boolean;
}

/** Where one part stands on the six stations (CLAUDE-CODE-PROMPT §4.2 and the RequestStatusPage board's rule). */
function partStation(part: Part): TrackState {
  if (part.library || (part.decide === "decided" && part.decision?.choice !== "changes")) return { at: 5, tone: "done", back: false };
  if (changing(part) || part.check === "sent_back") return { at: 2, tone: "work", back: true };
  if (part.decide === "yourturn" || part.check === "approved") return { at: 5, tone: "turn", back: false };
  if (part.check === "working") return { at: 4, tone: "work", back: false };
  if (part.work === "done") return { at: 3, tone: "wait", back: false };
  if (part.work === "working") return { at: 1, tone: "work", back: false };
  return { at: 0, tone: "wait", back: false };
}

/**
 * The request's station: its least advanced part, so a second part's progress, a later decision or a recurring
 * run's next queue never moves it the wrong way. Before the plan exists, it is in line.
 */
export function trackState(facts: Facts): TrackState {
  const parts = facts.parts;
  if (facts.plan !== "done" || parts.length === 0) return { at: 0, tone: "wait", back: false };
  return parts.map(partStation).reduce((low, next) => (next.at < low.at ? next : low));
}

export function plainSummary(facts: Facts, words: PlainWords, every: string, requester = true): PlainSummary {
  const parts = facts.parts;
  const planned = facts.plan === "done" && parts.length > 0;
  const anyWorking = parts.some((p) => p.work === "working");
  const allMade = planned && parts.every((p) => p.work === "done");
  const anyChecking = parts.some((p) => p.check === "working");
  const allChecked = planned && parts.every((p) => p.check === "approved");
  const sentBack = parts.some((p) => p.check === "sent_back");
  const waitingCheck = parts.some((p) => p.work === "done" && p.check !== "approved" && p.check !== "working" && p.check !== "sent_back");
  const yourTurn = parts.some((p) => p.decide === "yourturn");
  const allDecided = planned && parts.every((p) => p.decide === "decided");
  const used = parts.some((p) => p.decision?.choice === "use");
  const inLibrary = parts.some((p) => p.library);
  const remaking = parts.some(changing);
  const state = (done: boolean, now: boolean): StageState => (done ? "done" : now ? "now" : "upcoming");
  const bands: StageState[] = [
    state(planned, !planned),
    state(allMade && !remaking, planned),
    state(allChecked && !remaking, anyChecking || waitingCheck || sentBack),
    state(allDecided, yourTurn),
  ];

  const c = words.chip;
  const chip = facts.withdrawn
    ? c.withdrawn
    : facts.blocked
      ? c.blocked
      : yourTurn
        ? requester
          ? c.ready
          : c.ready_public
        : allDecided
          ? used
            ? inLibrary
              ? c.in_use
              : every
                ? fill(c.in_use_regular, { every })
                : c.in_use_plain
            : c.not_used
          : remaking
            ? c.changes
            : sentBack
              ? c.sent_back
              : anyChecking
                ? c.checking
                : waitingCheck
                  ? c.waiting_check
                  : anyWorking
                    ? c.making
                    : planned
                      ? c.waiting_volunteer
                      : c.planning;
  const waiting = !facts.withdrawn && !facts.blocked && !yourTurn && !allDecided && !anyWorking && !anyChecking;
  return { bands, track: trackState(facts), chip, waiting, yourTurn };
}

/** The board's caption names for the film frame (RequestStatusPage onEvent), from the recorded event types. */
/** The four bands' anchors (DESIGN-SPEC 0.2); the judge tour links to #step-ready. */
const BAND_IDS = ["step-split", "step-build", "step-review", "step-ready"];
/** Which band each of the six stations opens: In line, Picked up, Being made, In line for a check, Being checked, Ready. */
const STATION_BAND = [0, 1, 1, 2, 2, 3];

/** The station before the request's last move, so a page that opens on a settled request shows only that one hop. */
function stationBefore(events: StatusEvent[], now: TrackState): number {
  for (let n = events.length - 1; n > 0; n -= 1) {
    const earlier = trackState(applyEvents(events.slice(0, n))).at;
    if (earlier !== now.at) return earlier;
  }
  return now.at;
}

/**
 * The token. It mounts only on settled facts, at the station before the request's last move, and two frames later
 * moves to where the request is: one hop on load, then one move per change. With reduced motion it jumps.
 */
function TrackToken({ track, events }: { track: TrackState; events: StatusEvent[] }) {
  const [shown, setShown] = useState(() => stationBefore(events, track));
  const [animate, setAnimate] = useState(false);
  useEffect(() => {
    let inner = 0;
    const outer = window.requestAnimationFrame(() => {
      inner = window.requestAnimationFrame(() => {
        setAnimate(true);
        setShown(track.at);
      });
    });
    return () => {
      window.cancelAnimationFrame(outer);
      window.cancelAnimationFrame(inner);
    };
  }, [track.at]);
  return (
    <span className="er-track-lane" aria-hidden="true" data-animate={animate}>
      <span className="er-track-token" data-testid="track-token" data-pos={shown} data-tone={track.tone} data-back={track.back} />
    </span>
  );
}

/**
 * The request track (owner v2, Nov 1): six stations and one token, both from the request's state (trackState), so
 * the token and aria-current never disagree. The token moves 900 ms by transform only when the state changes; a
 * page that opens on a settled request shows only the last hop, and with reduced motion it jumps. A check that
 * sends the work back moves it backwards. Ghost pills stand for the requests ahead in line.
 */
function RequestTrack({
  track,
  events,
  words,
  label,
  ahead,
  settled,
  requester,
  onStation,
}: {
  track: TrackState;
  events: StatusEvent[];
  words: PlainWords["track"];
  label: string;
  ahead: number;
  settled: boolean;
  requester: boolean;
  /** Opens the band a station stands for (1 to 4). */
  onStation?: (band: number) => void;
}) {
  const delivered = track.tone === "done";
  // The track's measured height, as --er-track-h on the page: focus and anchors scroll clear of it at every width
  // (it is taller on phones, where the station names wrap). WCAG 2.2 SC 2.4.11.
  const nav = useRef<HTMLElement>(null);
  useEffect(() => {
    const element = nav.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const root = document.documentElement;
    const observer = new ResizeObserver(() => root.style.setProperty("--er-track-h", `${Math.ceil(element.getBoundingClientRect().height)}px`));
    observer.observe(element);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--er-track-h");
    };
  }, []);
  return (
    <nav ref={nav} className="er-track" aria-label={label} data-testid="request-track">
      <ol>
        {words.stations.map((station, i) => {
          const done = i < track.at || (i === 5 && delivered);
          const now = i === track.at && !done;
          const name = now ? (i === 5 && !requester ? (station.now_public ?? station.now) : station.now) : station.other;
          return (
            <li key={i} data-step={i} data-state={done ? "done" : now ? "now" : "upcoming"} data-tone={now ? track.tone : undefined}>
              <a href={`#${BAND_IDS[STATION_BAND[i] ?? 0]}`} aria-current={now ? "step" : undefined} onClick={() => onStation?.((STATION_BAND[i] ?? 0) + 1)}>
                <span className="er-track-dot" aria-hidden="true" />
                <span className="er-track-name">{name}</span>
                {done && words.done && <span className="er-visually-hidden"> ({words.done})</span>}
                {!done && !now && words.next && <span className="er-visually-hidden"> ({words.next})</span>}
                {i === 0 && now && ahead > 0 && (
                  <span className="er-ghosts" aria-hidden="true" data-testid="ghost-pills">
                    {Array.from({ length: Math.min(ahead, 4) }, (_, k) => (
                      <span key={k} className="er-ghost" />
                    ))}
                  </span>
                )}
              </a>
            </li>
          );
        })}
      </ol>
      {settled && <TrackToken track={track} events={events} />}
    </nav>
  );
}

const CAPTION: Partial<Record<StatusEvent["type"], { type: string; band: number }>> = {
  received: { type: "received", band: 1 },
  planned: { type: "split", band: 1 },
  queued: { type: "queued", band: 2 },
  work_claimed: { type: "claimed", band: 2 },
  work_submitted: { type: "submitted", band: 2 },
  check_refused: { type: "refused", band: 3 },
  check_claimed: { type: "rclaimed", band: 3 },
  check_approved: { type: "approved", band: 3 },
  check_sent_back: { type: "sentback", band: 3 },
  signoff_required: { type: "signoff", band: 4 },
  delivered: { type: "ready", band: 4 },
  published: { type: "ready", band: 4 },
  decided: { type: "decision", band: 4 },
  library_added: { type: "library", band: 4 },
};

/** "What has happened", newest first: one plain sentence per recorded fact, with its caption name for the film. */
export function plainHappened(events: StatusEvent[], facts: Facts, words: PlainWords): { at: number | null; text: string; type: StatusEvent["type"] }[] {
  const h = words.happened;
  const many = facts.parts.length > 1;
  const label = (n: number | undefined) => {
    const part = facts.parts.find((p) => p.plan.part === n);
    return many && part ? `${words.kind[kindOf(part)]}: ` : "";
  };
  const remade = new Set<number>();
  const readied = new Set<string>();
  const rows: { at: number | null; text: string; type: StatusEvent["type"] }[] = [];
  for (const event of events) {
    if (!(event.receipt || event.ref)) continue;
    const n = event.part ?? 0;
    const again = remade.has(n);
    const push = (text: string | undefined) => text && rows.push({ at: event.at ?? null, text: label(event.part) + text, type: event.type });
    switch (event.type) {
      case "received":
        push(h.received);
        break;
      case "queued": {
        if (event.summary?.next_at) {
          push(fill(h.scheduled, { time: when(event.summary.next_at) }));
          break;
        }
        const place = event.part ? (event.places?.[String(event.part)] ?? event.place) : event.place;
        if (place) push(place === 1 ? h.queued_next : fill(h.queued, { nth: ordinal(place) }));
        break;
      }
      case "plan_claimed":
        push(byEranos(event) && h.plan_claimed_eranos ? h.plan_claimed_eranos : h.plan_claimed);
        break;
      case "planned":
        push(h.planned);
        break;
      case "blocked":
        push(fill(h.blocked, { reason: event.reason ?? "" }));
        break;
      case "work_claimed": {
        const eranos = byEranos(event);
        push(again ? h.work_claimed_changes : eranos ? h.work_claimed_eranos : h.work_claimed);
        break;
      }
      case "work_released":
        push(event.reason ? h.work_failed : h.work_released);
        break;
      case "work_submitted":
        push(again ? h.work_submitted_changes : h.work_submitted);
        break;
      case "check_refused":
        push(h.check_refused);
        break;
      case "check_claimed": {
        const eranos = byEranos(event);
        push(again ? (eranos ? (h.check_claimed_changes_eranos ?? h.check_claimed_changes) : h.check_claimed_changes) : eranos ? (h.check_claimed_eranos ?? h.check_claimed) : h.check_claimed);
        break;
      }
      case "check_sent_back":
        push(h.check_sent_back);
        break;
      case "check_approved":
      case "delivered":
      case "published": {
        if (event.summary?.reused) {
          push(h.reused);
          break;
        }
        const keyFor = `${n}:${again ? "again" : "first"}`;
        if (readied.has(keyFor)) break;
        readied.add(keyFor);
        push(again ? h.ready_changes : h.ready);
        break;
      }
      case "signoff_required":
        push(h.signoff_required);
        break;
      case "decided":
        if (event.choice === "changes") remade.add(n);
        push(event.choice === "use" ? h.decided_use : event.choice === "changes" ? h.decided_changes : h.decided_dont);
        break;
      case "library_added":
        push(h.library_added);
        break;
      case "withdrawn":
        push(h.withdrawn);
        break;
      case "closed":
        push(h.closed);
        break;
      default:
        break;
    }
  }
  return rows.reverse();
}

/** When a part started waiting for a volunteer: its plan, its place in line, a release or a request for changes. */
function waitingSince(events: StatusEvent[], part: number): number | null {
  let since: number | null = null;
  for (const event of events) {
    if (!(event.receipt || event.ref) || event.at == null) continue;
    if (event.type === "planned" || ((event.type === "queued" || event.type === "work_released") && event.part === part)) since = event.at;
    if (event.type === "decided" && event.part === part && event.choice === "changes") since = event.at;
  }
  return since;
}

/** The band each `#step-*` anchor opens. */
const BAND_FOR_HASH: Record<string, number> = { "#step-split": 1, "#step-build": 2, "#step-review": 3, "#step-ready": 4 };

/**
 * The four bands as an accordion (owner, Nov 1): the current step is open; when a recorded fact moves the request
 * on, the finished step folds to its one-line status and the next one opens. A section the person opened by hand
 * stays open, and an anchor (a station, or a `#step-*` link) opens its section and scrolls to it.
 */
function useBands(current: number) {
  const hash = useHash();
  const fromHash = BAND_FOR_HASH[typeof window === "undefined" ? "" : window.location.hash];
  const byHand = useRef<Set<number>>(new Set(fromHash ? [fromHash] : []));
  const [open, setOpen] = useState<Set<number>>(() => new Set([current, ...byHand.current]));
  const [byEvent, setByEvent] = useState<number | null>(null);
  const shown = useRef(current);
  useEffect(() => {
    if (current === shown.current) return;
    shown.current = current;
    setOpen(new Set([current, ...byHand.current]));
    setByEvent(current);
  }, [current]);
  const reveal = (n: number) => {
    byHand.current.add(n);
    setOpen((was) => (was.has(n) ? was : new Set([...was, n])));
    // After the section opens, bring it to the top, clear of the sticky track (its scroll-margin-top).
    window.requestAnimationFrame(() => document.getElementById(BAND_IDS[n - 1] ?? "")?.scrollIntoView({ block: "start" }));
  };
  useEffect(() => {
    const n = BAND_FOR_HASH[hash];
    if (n) reveal(n);
  }, [hash]);
  const toggle = (n: number) =>
    setOpen((was) => {
      const next = new Set(was);
      if (next.has(n)) {
        next.delete(n);
        byHand.current.delete(n);
      } else {
        next.add(n);
        byHand.current.add(n);
      }
      return next;
    });
  return { open, byEvent, toggle, reveal };
}

function Band({
  n,
  title,
  state,
  status,
  open,
  byEvent,
  onToggle,
  children,
}: {
  n: number;
  title: string;
  state: StageState;
  status: string;
  open: boolean;
  byEvent: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section
      id={BAND_IDS[n - 1]}
      className={`er-panel er-rq-band er-rq-band-${state}`}
      data-band={n}
      data-state={state}
      data-open={open}
      aria-labelledby={`band-${n}`}
    >
      <h2 id={`band-${n}`} className="er-panel-title er-band-head">
        <button type="button" className="er-band-toggle" aria-expanded={open} aria-controls={`band-${n}-body`} onClick={onToggle} data-testid={`band-toggle-${n}`}>
          <span className="er-band-n" aria-hidden="true">
            {n}
          </span>
          <span className="er-band-title">{title}</span>
          <span className="er-band-status" data-testid={`band-status-${n}`}>
            {status}
          </span>
          <span className="er-band-chevron" aria-hidden="true" />
        </button>
      </h2>
      <div id={`band-${n}-body`} className="er-band-body" hidden={!open} data-by-event={byEvent}>
        {children}
      </div>
    </section>
  );
}

export function PlainStatus({
  summary,
  facts,
  events,
  words,
  clock,
  shareUrl,
  routeId,
  requester,
  settled = true,
}: {
  /** False until a live page has read the request's first real snapshot: the track shows no token before then. */
  settled?: boolean;
  summary: PlainSummary;
  facts: Facts;
  events: StatusEvent[];
  words: PlainWords;
  clock: (at: number) => string;
  shareUrl: string;
  routeId: string;
  requester: boolean;
}) {
  const [all, setAll] = useState(false);
  const [shared, setShared] = useState(false);
  const happened = plainHappened(events, facts, words);
  const shown = all ? happened : happened.slice(0, 5);
  const parts = facts.parts;
  const many = parts.length > 1;
  const b = words.bands;
  const planned = facts.plan === "done" && parts.length > 0;

  // Each new recorded fact is announced once for the film frame (the board's onEvent): its caption name, band and line.
  const announced = useRef(happened.length);
  useEffect(() => {
    const fresh = happened.length - announced.current;
    announced.current = happened.length;
    if (fresh <= 0) return;
    for (const row of happened.slice(0, fresh).reverse()) {
      const caption = CAPTION[row.type];
      if (!caption) continue;
      window.dispatchEvent(new CustomEvent("eranos:status-event", { detail: { n: happened.length, type: caption.type, band: caption.band, text: row.text } }));
    }
  }, [happened]);

  async function share() {
    try {
      await navigator.clipboard.writeText(fill(words.share_text, { url: shareUrl }));
      setShared(true);
      window.setTimeout(() => setShared(false), 2400);
    } catch {
      setShared(false);
    }
  }

  const tagFor = (part: Part, index: number): string => {
    const t = words.tags;
    if (index === 0) return facts.plan === "done" ? t.made : t.not_yet;
    if (changing(part)) return t.changing;
    if (part.check === "approved") return t.checked;
    if (part.work === "done") return t.made;
    return t.not_yet;
  };
  const stripState = (n: number): StageState => summary.bands[n - 1] ?? "upcoming";
  const resultPage = (n: number) => `/requests/${encodeURIComponent(routeId)}/result?part=${n}`;
  // The current step: the first band in progress, or the last one once everything is done.
  const nowBand = summary.bands.findIndex((state) => state === "now");
  const current = nowBand >= 0 ? nowBand + 1 : summary.bands.every((state) => state === "done") ? 4 : 1;
  const bands = useBands(current);
  // Each band's one-line, present-tense status, shown in its header whether it is open or folded.
  const st = b.status;
  const lastAt = (types: StatusEvent["type"][]) => [...events].reverse().find((e) => types.includes(e.type) && e.at)?.at ?? null;
  const doneLine = (at: number | null) => (at ? fill(st.done, { time: clock(at) }) : st.done_untimed);
  const anyChecking = parts.some((p) => p.check === "working");
  const sentBack = parts.some((p) => p.check === "sent_back");
  const bandStatus = [
    stripState(1) === "done" ? doneLine(lastAt(["planned"])) : stripState(1) === "now" ? st.sorting : st.upcoming,
    stripState(2) === "done"
      ? doneLine(lastAt(["work_submitted"]))
      : stripState(2) === "now"
        ? parts.some((p) => p.work === "working")
          ? st.working
          : st.waiting_helper
        : st.upcoming,
    stripState(3) === "done"
      ? doneLine(lastAt(["check_approved"]))
      : stripState(3) === "now"
        ? sentBack
          ? st.sent_back
          : anyChecking
            ? st.checking
            : st.waiting_check
        : st.upcoming,
    stripState(4) === "done" ? doneLine(lastAt(["decided", "library_added"])) : stripState(4) === "now" ? (requester ? st.your_turn : st.their_turn) : st.upcoming,
  ];
  const bandProps = (n: number) => ({
    status: bandStatus[n - 1] ?? "",
    open: bands.open.has(n),
    byEvent: bands.byEvent === n,
    onToggle: () => bands.toggle(n),
  });

  return (
    <div className="er-plain" data-testid="plain-status">
      <RequestTrack
        track={summary.track}
        events={events}
        words={words.track}
        label={words.stages_label}
        settled={settled}
        requester={requester}
        onStation={(n) => bands.reveal(n)}
        ahead={parts.some((p) => !p.workAgent && p.work !== "done") ? Math.max(0, (parts.find((p) => !p.workAgent && p.work !== "done")?.place ?? 1) - 1) : 0}
      />
      <p className="er-visually-hidden" aria-live="polite" data-testid="track-live">
        {happened[0]?.text ?? ""}
      </p>

      <Band n={1} title={b.sorted.title} state={stripState(1)} {...bandProps(1)}>
        {facts.received?.at != null && <p className="er-band-ok">{fill(b.sorted.checked, { time: clock(facts.received.at) })}</p>}
        {planned ? (
          <ul className="er-band-list">
            {parts.map((part) => (
              <li key={part.plan.part}>
                <strong>{kindOf(part) === "process" ? b.sorted.process : b.sorted.information}</strong>
                <span className="er-small">{part.plan.text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="er-small">{b.sorted.waiting}</p>
        )}
      </Band>

      <Band n={2} title={stripState(2) === "done" ? b.made.title_done : b.made.title_now} state={stripState(2)} {...bandProps(2)}>
        {!planned && <p className="er-small">{b.made.waiting.replace(/ · .*$/, "")}</p>}
        {parts.map((part) => {
          const n = part.plan.part;
          const agent = part.workAgent;
          const done = part.work === "done";
          const waitingForVolunteer = !agent && !done && part.work !== "held";
          const since = waitingForVolunteer ? waitingSince(events, n) : null;
          return (
            <div key={n} className="er-band-part" data-part={n}>
              {many && <h3 className="er-making-kind">{words.kind[kindOf(part)]}</h3>}
              {agent && (
                <p className="er-helper" data-testid={`helper-${n}`}>
                  <strong>{agent.dedicated ? b.made.helper_eranos : b.made.helper_volunteer}</strong>{" "}
                  {agent.claimedAt != null && fill(agent.dedicated ? b.made.picked_eranos : b.made.picked, { time: clock(agent.claimedAt) })}
                </p>
              )}
              {(() => {
                const tries = events.filter((e) => e.part === n && (e.type === "work_claimed" || e.type === "work_released"));
                const last = tries.at(-1);
                if (!last || last.type !== "work_released" || !last.reason || done) return null;
                const retry = last.summary?.attempt && last.summary.max_attempts ? fill(b.made.retry_count, { n: last.summary.attempt, m: last.summary.max_attempts }) : b.made.retry;
                return (
                  <p className="er-band-failed" data-testid={`failed-${n}`}>
                    {fill(b.made.failed, { reason: shortReason(last.reason) })} {retry}
                  </p>
                );
              })()}
              {waitingForVolunteer && (
                <p className="er-small" data-testid={`waiting-${n}`}>
                  {fill(b.made.waiting, { nth: ordinal(part.place ?? 1) })}{" "}
                  {since != null && fill(b.made.fallback, { time: clock(since + FALLBACK_SECONDS) })}
                </p>
              )}
              <ul className="er-making" data-testid={`making-${n}`}>
                {words.making[kindOf(part)].map((item, index) => (
                  <li key={item}>
                    <span>{item}</span>
                    <span className="er-tag">{tagFor(part, index)}</span>
                  </li>
                ))}
              </ul>
              {done && (
                <p className="er-small er-band-ok">
                  {b.made.recorded}
                  {b.made.models_link && b.made.models_href && (
                    <>
                      {" "}
                      <a href={b.made.models_href}>{b.made.models_link}</a>
                    </>
                  )}
                </p>
              )}
            </div>
          );
        })}
      </Band>

      <Band n={3} title={parts.some((p) => p.checkAgent?.dedicated) && b.checked.title_eranos ? b.checked.title_eranos : b.checked.title} state={stripState(3)} {...bandProps(3)}>
        <p className="er-small">{b.checked.rule}</p>
        {parts.map((part) => {
          const n = part.plan.part;
          const refused = events.some((e) => e.type === "check_refused" && e.part === n && (e.receipt || e.ref));
          const notes = part.checkEvidence?.reason ? 1 : 0;
          const findings = events.filter((e) => e.type === "check_sent_back" && e.part === n).at(-1)?.findings?.length ?? notes;
          const line =
            part.check === "approved"
              ? b.checked.done
              : part.check === "sent_back"
                ? findings > 1
                  ? fill(b.checked.sent_back_many, { n: findings })
                  : b.checked.sent_back_one
                : part.check === "working"
                  ? part.checkAgent?.dedicated && b.checked.checking_eranos
                    ? b.checked.checking_eranos
                    : b.checked.checking
                  : part.work === "done"
                    ? b.checked.waiting
                    : b.checked.upcoming;
          return (
            <p key={n} className="er-band-line" data-testid={`check-${n}`}>
              {many && <strong>{words.kind[kindOf(part)]}: </strong>}
              {refused && <span className="er-band-blocked">{b.checked.blocked} · </span>}
              {line}
            </p>
          );
        })}
      </Band>

      <Band n={4} title={stripState(4) === "done" && b.ready.title_done ? b.ready.title_done : requester ? b.ready.title : b.ready.title_public} state={stripState(4)} {...bandProps(4)}>
        {(() => {
          const next = events.filter((e) => e.type === "queued" && e.summary?.next_at && (e.receipt || e.ref)).at(-1)?.summary?.next_at;
          return next ? (
            <p className="er-small" data-testid="next-run">
              {fill(b.ready.next_run, { time: when(next) })}
            </p>
          ) : null;
        })()}
        {parts.some((p) => p.decide === "yourturn" || p.decide === "decided") ? (
          <>
            <div className="er-ready-cards">
              {parts
                .filter((p) => p.decide === "yourturn" || p.decide === "decided")
                .map((part) => (
                  <div key={part.plan.part} className="er-ready-card" data-testid={`ready-${part.plan.part}`}>
                    <strong>{kindOf(part) === "process" ? b.ready.process : b.ready.information}</strong>
                    <AppLink to={resultPage(part.plan.part)} className="er-text-link">
                      {kindOf(part) === "process" ? b.ready.open_process : b.ready.open_information}
                    </AppLink>
                  </div>
                ))}
            </div>
            {parts.map((part) => {
              const reused = events.filter((e) => e.part === part.plan.part && (e.type === "delivered" || e.type === "published") && e.summary?.reused).at(-1);
              if (!reused) return null;
              const href = sourceHref(reused);
              return (
                <p key={`reused-${part.plan.part}`} data-testid={`reused-${part.plan.part}`}>
                  {b.ready.reused}{" "}
                  {href &&
                    (href.startsWith("/catalog/") ? (
                      <AppLink to={href} className="er-text-link">
                        {b.ready.reused_link}
                      </AppLink>
                    ) : (
                      <a href={href} className="er-text-link">
                        {b.ready.reused_link}
                      </a>
                    ))}
                </p>
              );
            })}
            {requester && summary.yourTurn && (
              <p>
                <strong>{b.ready.decide}</strong>{" "}
                <AppLink to={resultPage(parts.find((p) => p.decide === "yourturn")?.plan.part ?? 1)} className="er-text-link">
                  {b.ready.decide_link}
                </AppLink>
              </p>
            )}
            {parts.some((p) => p.library) && (
              <p className="er-small" data-testid="ready-library">
                <strong>{b.ready.library_title}:</strong> {b.ready.library_added}{" "}
                <AppLink to={`/library?request=${encodeURIComponent(routeId)}`} className="er-text-link">
                  {b.ready.library_link}
                </AppLink>{" "}
                <a href={AGORA_HOW_IT_WORKS_URL} className="er-text-link">
                  {b.ready.library_how}
                </a>
              </p>
            )}
          </>
        ) : (
          <p className="er-small">{b.ready.upcoming}</p>
        )}
      </Band>

      {summary.waiting && (
        <section className="er-panel er-share" data-testid="share-request">
          <p>{words.share_lead}</p>
          <button type="button" className="er-btn-secondary" onClick={() => void share()}>
            {shared ? words.shared : words.share}
          </button>
        </section>
      )}

      <section className="er-panel" aria-labelledby="happened-title">
        <h2 id="happened-title" className="er-panel-title">
          {words.happened_title}
        </h2>
        <ol className="er-happened" data-testid="plain-happened">
          {shown.map((row, index) => (
            <li key={`${index}-${row.text}`}>
              {row.at !== null && <span className="er-small er-happened-time">{clock(row.at)}</span>}
              <span>{row.text}</span>
            </li>
          ))}
        </ol>
        {happened.length > 5 && !all && (
          <button type="button" className="er-text-link er-link-button" onClick={() => setAll(true)}>
            {fill(words.happened_more, { n: happened.length })}
          </button>
        )}
      </section>
    </div>
  );
}
